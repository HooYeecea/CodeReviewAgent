"""Opt-in review exports. Flow checkpoints are the source for retryable exports."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
from functools import wraps
import hashlib
import html
import inspect
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from gai.common.git import ensure_repo, run_git, staged_name_status, assert_staged_snapshot

_CURRENT: ContextVar[ReviewCollection | None] = ContextVar("review_collection", default=None)
_DIRECTORY = re.compile(r"\d{8}-\d{6}_[0-9a-f]{32}")
_ID = re.compile(r"[0-9a-f]{32}")


class ReviewSaveError(RuntimeError):
    """Saving was requested but could not be completed; do not continue to push."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_archive(command: str) -> dict:
    return {"directory": datetime.now().strftime("%Y%m%d-%H%M%S_") + uuid.uuid4().hex,
            "command": command, "records": []}


def validate_archive(value):
    if not isinstance(value, dict) or not _DIRECTORY.fullmatch(str(value.get("directory", ""))):
        raise ValueError("Invalid review archive directory")
    if not isinstance(value.get("command"), str) or not isinstance(value.get("records"), list):
        raise ValueError("Invalid review archive metadata")
    seen = set()
    for record in value["records"]:
        if (not isinstance(record, dict) or not _ID.fullmatch(str(record.get("id", "")))
                or record["id"] in seen or not isinstance(record.get("result"), dict)
                or not isinstance(record.get("snapshot"), dict)):
            raise ValueError("Invalid archived review")
        seen.add(record["id"])
    return value


def atomic_text(path: Path, text: str) -> None:
    if path.is_symlink():
        raise OSError(f"Refusing symlink: {path}")
    fd, filename = tempfile.mkstemp(prefix=".review-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(filename, path)
    finally:
        Path(filename).unlink(missing_ok=True)


def md(value) -> str:
    """Keep model/file text literal: no active HTML, links or injected headings."""
    value = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value).replace("\n", "  \n")


def review_markdown(record: dict) -> str:
    result = record["result"]
    snapshot = record["snapshot"]
    lines = ["# 代码审查 / Code review", "",
             f"- ID: {record['id']}",
             f"- 审查时间 / Reviewed: {md(record.get('reviewed_at') or 'unknown (cached result)')}",
             f"- 保存时间 / Saved: {md(record['saved_at'])}",
             f"- 命令 / Command: {md(record['command'])}",
             f"- 模型（配置） / Configured model: {md(record['model'])}",
             f"- 分支 / Branch: {md(snapshot.get('ref', ''))}",
             f"- HEAD: {md(snapshot.get('head', ''))}",
             f"- 暂存内容 / Index tree: {md(snapshot.get('tree', ''))}",
             f"- 流程 / Flow: {md(record.get('flow_id') or '—')}",
             f"- 批次 / Batch: {md(record.get('batch') or '—')}",
             f"- 提交 / Commit: {md(record.get('commit') or '未关联 / Not linked')}",
             f"- 解析成功 / Parsed: {result['parsed_ok']}",
             f"- Diff 截断 / Truncated: {result['truncated_diff']}", "",
             "## 摘要 / Summary", "", md(result.get("summary", "")), "",
             "## 问题 / Findings", ""]
    if not result["parsed_ok"]:
        lines.append("解析失败，本次审查不能视为通过。 / Parsing failed; this is not a passing review.")
    elif not result["review"]:
        lines.append("模型未报告问题；不代表代码没有缺陷。 / The model reported no findings.")
    for i, item in enumerate(result["review"], 1):
        lines.extend([f"### {i}. {md(item['severity'])}", "",
                      f"位置 / Location: {md(item['file'])}:{md(item.get('line') or '—')}", "",
                      md(item["issue"]), "", "建议 / Suggestion: " + md(item.get("suggestion", "")), ""])
    lines.extend(["", "## 审查范围 / Scope", "",
                  "以下为当时暂存的文件；发送内容受忽略规则和长度限制影响。 / Staged files; ignore filters and size limits apply.", ""])
    lines.extend("- " + md(name) for name in record["staged_files"])
    lines.extend(["", "忽略规则 / Ignore patterns: " + md(", ".join(record["ignore_patterns"])), "",
                  "未保存完整 diff、请求内容、API 密钥或原始模型响应。 / Full diffs, requests, API keys and raw responses are not stored.", ""])
    return "\n".join(lines)


class ReviewCollection:
    def __init__(self, command: str, enabled: bool = False):
        self.enabled = enabled
        self.archive = new_archive(command)
        self.root = None
        self.path = None
        self._written = None
        self._record_written = {}
        self._prepared = False

    def bind(self, session):
        stored = session.data.get("review_archive")
        if stored is not None:
            self.archive = validate_archive(stored)
            self.enabled = True
        elif self.enabled:
            session.data["review_archive"] = self.archive
        self.root = session.root

    def prepare(self):
        if self._prepared:
            return
        self.root = (self.root or ensure_repo()).resolve()
        validate_archive(self.archive)
        folder = self.root / ".gai" / "reviews"
        self.path = folder / self.archive["directory"]
        # Local reports must not escape the repo through symlinked directories.
        for directory in (self.root / ".gai", folder, self.path):
            if directory.is_symlink() or not directory.resolve().is_relative_to(self.root):
                raise OSError(f"Unsafe review directory: {directory}")
        tracked = run_git("ls-files", "-z", "--", ".gai/reviews", cwd=self.root)
        if tracked.returncode or tracked.stdout:
            raise OSError(".gai/reviews contains tracked files; choose a clean local report directory first")
        probe = ".gai/reviews/.ignore-check"
        ignored = run_git("check-ignore", "-q", "--", probe, cwd=self.root)
        if ignored.returncode == 1:
            info = run_git("rev-parse", "--git-path", "info/exclude", cwd=self.root)
            if info.returncode:
                raise OSError(info.stderr)
            exclude = Path(info.stdout.strip())
            if not exclude.is_absolute():
                exclude = self.root / exclude
            exclude.parent.mkdir(parents=True, exist_ok=True)
            # Append a local rule; never rewrite the user's .gitignore or index.
            with exclude.open("a", encoding="utf-8") as stream:
                stream.write("\n# gai local review reports\n/.gai/reviews/\n")
            ignored = run_git("check-ignore", "-q", "--", probe, cwd=self.root)
        if ignored.returncode:
            raise OSError("Cannot ignore .gai/reviews; check repository ignore rules")
        self.path.mkdir(parents=True, exist_ok=True)
        self._prepared = True

    def sync(self, session=None):
        if not self.enabled or not self.archive["records"]:
            return
        try:
            # Export commit links without mutating an already checksummed checkpoint.
            records = [dict(record) for record in self.archive["records"]]
            phase = "reviewed"
            if session:
                phase = session.data["phase"]
                # Link only the exact reviewed tree. Old re-reviews remain unlinked.
                batches = session.data.get("completed_batches", []) + session.data["batches"]
                by_id = {b.get("review", {}).get("export_id"): b for b in batches if b.get("commit")}
                for record in records:
                    batch = by_id.get(record["id"])
                    if batch:
                        record["commit"] = batch["commit"]
            state = {"schema": 1, "command": self.archive["command"], "phase": phase,
                     "completion": session.data.get("completion") if session else None, "reviews": records}
            counts = {severity: sum(item["severity"] == severity for record in records
                                   for item in record["result"]["review"])
                      for severity in ("critical", "warning", "info")}
            state["findings_by_severity"] = counts
            state["parse_failures"] = sum(not r["result"]["parsed_ok"] for r in records)
            state["truncated_reviews"] = sum(r["result"]["truncated_diff"] for r in records)
            encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            if fingerprint == self._written:
                return
            self.prepare()
            summaries = ["# 审查汇总 / Review summary", "",
                         f"- 命令 / Command: {md(state['command'])}", f"- 阶段 / Phase: {md(phase)}",
                         f"- 审查次数 / Reviews: {len(records)}", "",
                         f"- 问题记录数（含重复审查） / Findings including re-reviews: {counts}",
                         f"- 解析失败 / Parse failures: {state['parse_failures']}",
                         f"- 截断审查 / Truncated reviews: {state['truncated_reviews']}", "",
                         "重复审查分别保留；未关联提交的记录不代表已提交。 / Re-reviews are retained separately; an unlinked review does not imply a commit.", ""]
            for record in records:
                stem = "review-" + record["id"]
                record_text = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
                if (self._record_written.get(record["id"]) != record_text
                        or not (self.path / (stem + ".json")).is_file()
                        or not (self.path / (stem + ".md")).is_file()):
                    atomic_text(self.path / (stem + ".json"), record_text)
                    atomic_text(self.path / (stem + ".md"), review_markdown(record))
                    self._record_written[record["id"]] = record_text
                status = record["result"]["status"]
                coverage = "truncated" if record["result"]["truncated_diff"] else "not truncated"
                summaries.append(f"- [{md(record.get('batch') or 'Review')} / {record['id'][:8]}]({stem}.md) · {md(status)} · {coverage} · {md(record.get('commit') or 'not linked')}")
            atomic_text(self.path / "index.json", encoded + "\n")
            atomic_text(self.path / "summary.md", "\n".join(summaries) + "\n")
            self._written = fingerprint
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ReviewSaveError(
                "审查报告保存失败，后续操作已停止；流程可修复目录权限后 --resume。 / "
                f"Review export failed; fix storage before continuing: {exc}"
            ) from exc


@contextmanager
def collection(command: str, enabled: bool = False):
    parent = _CURRENT.get()
    if parent is not None:
        parent.enabled |= enabled
        yield parent
        return
    value = ReviewCollection(command, enabled)
    token = _CURRENT.set(value)
    try:
        yield value
    finally:
        _CURRENT.reset(token)


def collect_reviews(command: str):
    """Keep opt-in state scoped to one CLI call, including automatic flow switches."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            arguments = signature.bind_partial(*args, **kwargs).arguments
            with collection(command, arguments.get("save_review") is True) as collector:
                try:
                    return function(*args, **kwargs)
                finally:
                    if collector.path and (collector.path / "summary.md").is_file():
                        from gai.cli_common import err_console
                        err_console.print(f"审查报告 / Review reports: {collector.path / 'summary.md'}", markup=False)
        # Typer resolves postponed annotations using the wrapper's globals.
        wrapped.__annotations__ = inspect.get_annotations(function, eval_str=True)
        wrapped.__signature__ = signature.replace(parameters=[
            p.replace(annotation=wrapped.__annotations__.get(p.name, p.annotation))
            for p in signature.parameters.values()
        ], return_annotation=wrapped.__annotations__.get("return", signature.return_annotation))
        return wrapped
    return decorate


def bind_flow(session):
    collector = _CURRENT.get()
    if collector:
        collector.bind(session)


def sync_flow(session):
    stored = session.data.get("review_archive")
    if stored is None:
        return
    collector = _CURRENT.get() or ReviewCollection(stored["command"], True)
    collector.bind(session)
    collector.sync(session)


def save_review(result, snapshot, *, chinese=False, cached=False):
    collector = _CURRENT.get()
    if not collector or not collector.enabled:
        return
    from gai.common.config import load_settings
    from gai.flow.session import current_session
    session = current_session()
    envelope = session.batch.get("review") if session else None
    if envelope and envelope.get("export_id"):
        collector.sync(session)
        return
    if snapshot is None:
        raise ReviewSaveError("缺少审查版本标识，无法保存 / Missing reviewed snapshot")
    settings = load_settings()
    assert_staged_snapshot(snapshot)
    result_data = result.to_dict()
    if not result.parsed_ok:
        # The parser's fallback summary can be a raw-response excerpt.
        result_data["summary"] = "审查响应解析失败 / Review response could not be parsed."
    files = [p for _, p in staged_name_status()]
    assert_staged_snapshot(snapshot)
    record = {"schema": 1, "id": uuid.uuid4().hex,
              "reviewed_at": getattr(result, "reviewed_at", "") or (None if cached else now()),
              "saved_at": now(), "command": collector.archive["command"],
              "model": getattr(result, "model", "") or settings.model, "language": "cn" if chinese else "en",
              "snapshot": asdict(snapshot), "staged_files": files,
              "ignore_patterns": list(settings.ignore_patterns), "result": result_data,
              "flow_id": session.data["id"] if session else None,
              "flow_kind": session.data["kind"] if session else None,
              "batch": session.batch["label"] if session else None, "commit": None}
    collector.archive["records"].append(record)
    if envelope:
        envelope["export_id"] = record["id"]
    if session:
        # Persist the export payload before writing reports, so resume can repair
        # a partial MD/JSON pair without repeating a successful model request.
        session.save()
    else:
        collector.sync()


def link_commit():
    """Called only after an ordinary commit succeeds, before any optional push."""
    collector = _CURRENT.get()
    if not collector or not collector.enabled or not collector.archive["records"]:
        return
    result = run_git("show", "-s", "--format=%H%x00%T", "HEAD")
    if result.returncode:
        raise ReviewSaveError("提交已创建，但无法关联审查报告 / Commit created; cannot link review")
    head, tree = result.stdout.strip().split("\0")
    record = collector.archive["records"][-1]
    if tree != record["snapshot"]["tree"]:
        raise ReviewSaveError("实际提交与审查内容不同，未关联报告，停止后续推送 / Commit differs from review; push stopped")
    record["commit"] = head
    collector.sync()
