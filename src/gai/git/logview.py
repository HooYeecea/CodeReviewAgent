"""Commit listing, identity, log/graph snapshots for reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gai.git.core import GitError, ensure_repo, run_git
from gai.git.remote import current_branch_name, list_remotes
from gai.git.workflow import list_local_branches


@dataclass(frozen=True)
class CommitInfo:
    hash: str
    author_name: str
    author_email: str
    date: str
    subject: str
    body: str = ""
    shortstat: str = ""

    def to_dict(self) -> dict:
        return {
            "hash": self.hash,
            "author_name": self.author_name,
            "author_email": self.author_email,
            "date": self.date,
            "subject": self.subject,
            "body": self.body,
            "shortstat": self.shortstat,
        }


_RELATIVE_SINCE = re.compile(r"^(\d+)\s*([dwmy])$", re.IGNORECASE)
_COMMIT_MARKER = "===GAI_COMMIT==="
_ALLTIME_TOKENS = frozenset({"alltime", "all-time", "all_time", "all"})


def is_alltime_token(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _ALLTIME_TOKENS


def resolve_since(value: str | None) -> str | None:
    """Normalize --since: '7d'/'1w'/'2026-09-01'/'alltime' → git --since argument.

    Returns None for empty values or alltime tokens (no --since filter).
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if is_alltime_token(text):
        return None

    rel = _RELATIVE_SINCE.match(text)
    if not rel:
        return text

    amount = int(rel.group(1))
    unit = rel.group(2).lower()
    unit_map = {
        "d": "days",
        "w": "weeks",
        "m": "months",
        "y": "years",
    }
    return f"{amount} {unit_map[unit]} ago"


def current_git_identity(cwd: Path | None = None) -> tuple[str, str]:
    """Return ``(user.name, user.email)``; empty strings if unavailable.

    Does not require a git repository (falls back to global config) and never
    raises. Silent w.r.t. ``--trace`` so usage logging does not pollute the chain.
    """
    try:
        name_r = run_git("config", "user.name", cwd=cwd, trace=False)
        email_r = run_git("config", "user.email", cwd=cwd, trace=False)
    except GitError:
        return "", ""
    name = name_r.stdout.strip() if name_r.returncode == 0 else ""
    email = email_r.stdout.strip() if email_r.returncode == 0 else ""
    return name, email


def current_repo_identity(cwd: Path | None = None) -> tuple[str, str | None]:
    """Return ``(repo_root_name, remote_name)``.

    ``remote_name`` is the preferred remote alias (``origin`` if present, else the
    first remote). When the repo has no remotes, ``remote_name`` is ``None``.
    Never raises; silent w.r.t. ``--trace``.
    """
    repo_name = ""
    try:
        top = run_git("rev-parse", "--show-toplevel", cwd=cwd, trace=False)
        if top.returncode == 0 and top.stdout.strip():
            repo_name = Path(top.stdout.strip()).name
    except GitError:
        pass
    if not repo_name:
        base = Path(cwd) if cwd is not None else Path.cwd()
        repo_name = base.resolve().name

    try:
        result = run_git("remote", cwd=cwd, trace=False)
    except GitError:
        return repo_name, None
    if result.returncode != 0:
        return repo_name, None
    remotes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not remotes:
        return repo_name, None
    if "origin" in remotes:
        return repo_name, "origin"
    return repo_name, remotes[0]


def current_author_filter(cwd: Path | None = None) -> str:
    """Build --author filter for the current git user (email preferred)."""
    ensure_repo(cwd)
    email = run_git("config", "user.email", cwd=cwd)
    name = run_git("config", "user.name", cwd=cwd)
    if email.returncode == 0 and email.stdout.strip():
        return email.stdout.strip()
    if name.returncode == 0 and name.stdout.strip():
        return name.stdout.strip()
    raise GitError(
        "Cannot resolve current user. Set git user.email/user.name "
        "or pass --author explicitly.",
        code="no_author",
    )


def get_commits(
    cwd: Path | None = None,
    *,
    since: str | None = None,
    until: str | None = None,
    author: str | None = None,
    max_count: int = 100,
    include_stat: bool = True,
    include_merges: bool = False,
) -> list[CommitInfo]:
    """Fetch commit history for work-report summarization."""
    ensure_repo(cwd)
    if max_count <= 0:
        raise GitError("max_count must be positive")

    pretty = (
        f"{_COMMIT_MARKER}%n"
        "%H%n"
        "%an%n"
        "%ae%n"
        "%ad%n"
        "%s"
    )
    args = [
        "log",
        f"--pretty=format:{pretty}",
        "--date=short",
        f"-n{max_count}",
    ]
    if not include_merges:
        args.append("--no-merges")
    if include_stat:
        args.append("--shortstat")
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    if author:
        args.append(f"--author={author}")

    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or "git log failed",
            code="log_failed",
        )

    return _parse_commit_log(result.stdout)


def _parse_commit_log(raw: str) -> list[CommitInfo]:
    if not raw.strip():
        return []

    commits: list[CommitInfo] = []
    chunks = raw.split(_COMMIT_MARKER)
    for chunk in chunks:
        block = chunk.strip()
        if not block:
            continue
        nonempty = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(nonempty) < 5:
            continue

        commit_hash = nonempty[0]
        author_name = nonempty[1]
        author_email = nonempty[2]
        date = nonempty[3]
        subject = nonempty[4]
        shortstat = ""
        for ln in nonempty[5:]:
            if "file changed" in ln or "files changed" in ln:
                shortstat = ln
                break

        commits.append(
            CommitInfo(
                hash=commit_hash,
                author_name=author_name,
                author_email=author_email,
                date=date,
                subject=subject,
                shortstat=shortstat,
            )
        )
    return commits


def format_commits_for_prompt(
    commits: list[CommitInfo],
    *,
    max_chars: int | None = None,
) -> tuple[str, bool]:
    """Render commits into a compact text block for the LLM."""
    lines: list[str] = []
    for c in commits:
        short = c.hash[:8] if c.hash else ""
        lines.append(f"- [{c.date}] {short} {c.author_name}: {c.subject}")
        if c.shortstat:
            lines.append(f"  stat: {c.shortstat}")

    text = "\n".join(lines)
    truncated = False
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars] + "\n\n... [commit list truncated by gai] ...\n"
        truncated = True
    return text, truncated


def status_plain(cwd: Path | None = None) -> str:
    """Full ``git status`` output (human-readable)."""
    ensure_repo(cwd)
    result = run_git("status", cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git status failed",
            code="status_failed",
        )
    return (result.stdout or "").rstrip()


@dataclass(frozen=True)
class LogEntry:
    """One commit row for ``gai log`` pretty / HTML views."""

    hash: str
    short: str
    author: str
    date: str
    subject: str
    decorations: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "hash": self.hash,
            "short": self.short,
            "author": self.author,
            "date": self.date,
            "subject": self.subject,
            "decorations": self.decorations,
        }


@dataclass(frozen=True)
class GraphCommit:
    """One commit node for ``gai graph`` HTML visualization."""

    hash: str
    short: str
    parents: tuple[str, ...]
    author: str
    date: str
    subject: str
    decorations: str = ""
    email: str = ""
    body: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "hash": self.hash,
            "short": self.short,
            "parents": list(self.parents),
            "author": self.author,
            "email": self.email,
            "date": self.date,
            "subject": self.subject,
            "body": self.body,
            "decorations": self.decorations,
        }


@dataclass(frozen=True)
class GraphBranch:
    """Local branch tip for ``gai graph``."""

    name: str
    tip: str
    current: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "tip": self.tip, "current": self.current}


_LOG_FIELD_SEP = "\x1f"


def collect_log_entries(
    cwd: Path | None = None,
    *,
    max_count: int | None = None,
    ref: str | None = None,
) -> list[LogEntry]:
    """Return commits as structured rows. ``max_count=None`` means all commits.

    ``ref`` selects a branch/commit (default: current ``HEAD``).
    """
    ensure_repo(cwd)
    fmt = f"%H{_LOG_FIELD_SEP}%h{_LOG_FIELD_SEP}%an{_LOG_FIELD_SEP}%aI{_LOG_FIELD_SEP}%s{_LOG_FIELD_SEP}%D"
    args: list[str] = ["log"]
    if max_count is not None:
        args.append(f"-n{max(1, int(max_count))}")
    args.append(f"--pretty=format:{fmt}")
    if ref:
        args.append(ref)
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git log failed",
            code="log_failed",
        )
    entries: list[LogEntry] = []
    for line in (result.stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split(_LOG_FIELD_SEP)
        if len(parts) < 5:
            continue
        full, short, author, date, subject = parts[:5]
        deco = parts[5].strip() if len(parts) > 5 else ""
        entries.append(
            LogEntry(
                hash=full.strip(),
                short=short.strip(),
                author=author.strip(),
                date=date.strip(),
                subject=subject.strip(),
                decorations=deco,
            )
        )
    return entries


def log_plain(
    cwd: Path | None = None,
    *,
    max_count: int | None = None,
    graph: bool = False,
) -> str:
    """Raw ``git log`` text (optional ``--graph --decorate``). ``max_count=None`` = all."""
    ensure_repo(cwd)
    args: list[str] = ["log"]
    if max_count is not None:
        args.append(f"-n{max(1, int(max_count))}")
    if graph:
        args.extend(["--graph", "--decorate", "--oneline"])
    else:
        args.append("--oneline")
        args.append("--decorate")
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git log failed",
            code="log_failed",
        )
    return (result.stdout or "").rstrip()


def log_graph_text(
    cwd: Path | None = None,
    *,
    max_count: int | None = None,
    ref: str | None = None,
) -> str:
    """``git log --graph`` with a parse-friendly pretty format for pretty terminal."""
    ensure_repo(cwd)
    # Keep graph prefixes; fields after the hash for light styling.
    fmt = "%C(auto)%h %s %C(dim)(%an, %ar)%C(reset)%C(auto)%d"
    args: list[str] = [
        "-c",
        "color.ui=always",
        "log",
    ]
    if max_count is not None:
        args.append(f"-n{max(1, int(max_count))}")
    args.extend(
        [
            "--graph",
            "--decorate",
            f"--pretty=format:{fmt}",
        ]
    )
    if ref:
        args.append(ref)
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git log --graph failed",
            code="log_failed",
        )
    return (result.stdout or "").rstrip()


def collect_graph_snapshot(
    cwd: Path | None = None,
    *,
    max_count: int | None = None,
) -> dict[str, object]:
    """Collect local-branch tips + commits (with parents) for HTML graph viz.

    Uses ``git log --branches`` so remotes are excluded; ``max_count=None`` = all.
    Raises ``GitError(code=not_repo)`` when cwd is not a repository.
    """
    ensure_repo(cwd)
    current = current_branch_name(cwd)
    if current == "HEAD":
        current = ""
    names = list_local_branches(cwd)
    if current and current not in names:
        names = [current, *names]
    names = sorted(set(names), key=lambda b: (b != current, b.lower()))

    branches: list[GraphBranch] = []
    for name in names:
        tip_res = run_git("rev-parse", name, cwd=cwd, trace=False)
        if tip_res.returncode != 0:
            continue
        tip = (tip_res.stdout or "").strip()
        if not tip:
            continue
        branches.append(GraphBranch(name=name, tip=tip, current=(name == current)))

    # NUL-terminated records so commit bodies may contain newlines safely.
    fmt = (
        f"%H{_LOG_FIELD_SEP}%P{_LOG_FIELD_SEP}%h{_LOG_FIELD_SEP}"
        f"%an{_LOG_FIELD_SEP}%ae{_LOG_FIELD_SEP}%aI{_LOG_FIELD_SEP}"
        f"%s{_LOG_FIELD_SEP}%D{_LOG_FIELD_SEP}%b"
    )
    args: list[str] = ["log", "--branches", "--date-order", "-z"]
    if max_count is not None:
        args.append(f"-n{max(1, int(max_count))}")
    args.append(f"--pretty=format:{fmt}")
    result = run_git(*args, cwd=cwd)
    if result.returncode != 0:
        raise GitError(
            result.stderr.strip() or result.stdout.strip() or "git log failed",
            code="log_failed",
        )

    commits: list[GraphCommit] = []
    for record in (result.stdout or "").split("\0"):
        if not record.strip():
            continue
        parts = record.split(_LOG_FIELD_SEP)
        if len(parts) < 7:
            continue
        full, parents_s, short, author, email, date, subject = parts[:7]
        deco = parts[7].strip() if len(parts) > 7 else ""
        body = parts[8].strip() if len(parts) > 8 else ""
        parents = tuple(p for p in parents_s.split() if p)
        commits.append(
            GraphCommit(
                hash=full.strip(),
                short=short.strip(),
                parents=parents,
                author=author.strip(),
                email=email.strip(),
                date=date.strip(),
                subject=subject.strip(),
                body=body,
                decorations=deco,
            )
        )

    root = ensure_repo(cwd)
    repo_name = root.name
    remote_name = ""
    remote_url = ""
    try:
        remotes = list_remotes(cwd)
    except GitError:
        remotes = []
    if remotes:
        remote_name = "origin" if "origin" in remotes else remotes[0]
        url_res = run_git("remote", "get-url", remote_name, cwd=cwd, trace=False)
        if url_res.returncode == 0:
            remote_url = (url_res.stdout or "").strip()

    return {
        "branch": current or (branches[0].name if branches else ""),
        "branches": [b.to_dict() for b in branches],
        "commits": [c.to_dict() for c in commits],
        "maxCount": max_count,
        "repoName": repo_name,
        "remoteName": remote_name,
        "remoteUrl": remote_url,
    }
