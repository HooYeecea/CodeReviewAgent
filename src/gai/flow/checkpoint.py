"""Checkpoint shape validation and integrity metadata (schema 1 compatible)."""
import hashlib
import json
import re
from pathlib import Path


def checksum(data):
    payload = {k: v for k, v in data.items() if k != "checksum"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require(condition):
    if not condition:
        raise ValueError("Invalid checkpoint shape")


def snapshot(value):
    require(isinstance(value, dict) and isinstance(value.get("worktree"), str))
    snap = value["snapshot"]
    require(isinstance(snap, dict))
    for key in ("tree", "head", "ref"):
        require(isinstance(snap[key], str))
    require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", snap["tree"]))
    require(not snap["head"] or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", snap["head"]))


def batch(value):
    from gai.flow.devflow import CommitBatch
    require(isinstance(value, dict))
    CommitBatch(**value)
    require(isinstance(value["paths"], list) and value["paths"])
    require(all(isinstance(p, str) and p.strip() for p in value["paths"]))
    require(all(isinstance(v, str) for k, v in value.items() if k != "paths"))


def plan(value):
    require(isinstance(value, dict) and isinstance(value["summary"], str))
    require(isinstance(value["batches"], list))
    for item in value["batches"]:
        batch(item)


def validate(data):
    """Never let partial or mistyped state reach orchestration."""
    require(isinstance(data, dict) and data["schema"] == 1)
    require(data["kind"] in ("devflow", "splitflow"))
    require(data["phase"] in ("prepare", "plan", "running", "push", "done", "aborted"))
    require(isinstance(data["root"], str) and Path(data["root"]).is_absolute())
    require(isinstance(data["id"], str) and re.fullmatch(r"[0-9a-f]{32}", data["id"]))
    require(isinstance(data["chinese"], bool))
    require(data["remote"] is None or isinstance(data["remote"], str))
    require(type(data["cursor"]) is int and isinstance(data["batches"], list))
    require(0 <= data["cursor"] <= len(data["batches"]))
    snapshot(data["observed"])
    if "files" in data["observed"]:
        require(isinstance(data["observed"]["files"], dict))
        require(all(isinstance(k, str) and isinstance(v, str) for k, v in data["observed"]["files"].items()))
    if data["plan"] is not None:
        plan(data["plan"])
    languages = data["languages"]
    require(languages is None or (isinstance(languages, list) and all(x in ("en", "cn") for x in languages)))
    if data["kind"] == "splitflow" and data["phase"] == "running":
        require(data["plan"] is not None and languages is not None)
    if data["phase"] == "running" and data["kind"] == "splitflow":
        require(isinstance(data["review_cn"], bool))
    if languages is not None and data["plan"] is not None:
        require(len(languages) == len(data["plan"]["batches"]))
    for key in ("auto_confirm", "no_push", "plan_confirmed", "review_cn", "suggest_split"):
        if key in data:
            require(type(data[key]) is bool)
    completed = data.get("completed_batches", [])
    require(isinstance(completed, list))
    for item in completed:
        require(isinstance(item, dict) and item.get("status") == "committed")
    for item in completed + data["batches"]:
        require(isinstance(item, dict) and isinstance(item["label"], str))
        require(item["status"] in ("pending", "staged", "restaging", "splitting", "committed", "skipped"))
        require(item["depth"] in (1, 2) and item["lang"] in ("", "en", "cn"))
        # devflow stages an explicitly selected index rather than a path plan.
        if data["kind"] == "devflow":
            value = dict(item["batch"], paths=item["batch"]["paths"] or ["."])
            batch(value)
        else:
            batch(item["batch"])
        for key in ("commit", "selected_message"):
            if key in item:
                require(isinstance(item[key], str) and item[key].strip())
        if item["status"] == "committed":
            require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", item["commit"]))
        if "children_plan" in item:
            plan(item["children_plan"])
        for key in ("review", "messages"):
            if key in item:
                require(isinstance(item[key]["key"], str) and isinstance(item[key]["result"], dict))
    pending = data["pending"]
    if pending is not None:
        require(isinstance(pending, dict) and pending["operation"] in ("add", "unadd", "commit"))
        snapshot(pending["before"])
        require(isinstance(pending["tree"], str) and isinstance(pending["updates"], dict))
        require(set(pending["updates"]) <= {"phase", "batch_status"})
        if pending["operation"] == "commit":
            require(isinstance(pending["message"], str) and pending["message"].strip())
        if "batch_status" in pending["updates"]:
            require(data["cursor"] < len(data["batches"]))
    if "revision" in data:
        require(type(data["revision"]) is int and data["revision"] >= 1)
    if "last_error" in data:
        require(isinstance(data["last_error"], dict))
        require(all(isinstance(data["last_error"][key], str) for key in ("kind", "phase", "at")))
        require(type(data["last_error"]["batch"]) is int and data["last_error"]["batch"] >= 0)
    if "push_target" in data:
        require(isinstance(data["push_target"], dict))
        require(all(isinstance(data["push_target"][key], str) for key in ("remote", "branch", "url_hash")))
        if "head" in data["push_target"]:
            require(isinstance(data["push_target"]["head"], str))
    if "recovery_history" in data:
        require(isinstance(data["recovery_history"], list))
    if "parents" in data:
        require(isinstance(data["parents"], dict))
    if "checksum" in data:
        require(data["checksum"] == checksum(data))
    return data


def load(path):
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (AssertionError, KeyError, TypeError, ValueError, OSError) as exc:
        raise RuntimeError(f"无法读取流程检查点 / Invalid checkpoint: {path}") from exc
