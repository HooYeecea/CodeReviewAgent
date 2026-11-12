"""Read a pinned committed branch range without changing the index or refs."""
from gai.common.git import ensure_repo, run_git, StagedSnapshot, GitError
from gai.common.git.local import _PATCH_OPTIONS, filter_diff_by_ignore


def checked(*args):
    result = run_git(*args)
    if result.returncode:
        raise GitError(result.stderr.strip() or "Cannot inspect branch range")
    return result.stdout.strip()


def validate_scope(scope):
    if not scope or scope.get("kind") != "branch":
        return
    if (checked("rev-parse", "--verify", "HEAD") != scope["head"]
            or checked("rev-parse", "--verify", "--end-of-options", scope["base"] + "^{commit}") != scope["base_commit"]
            or run_git("symbolic-ref", "-q", "HEAD").stdout.strip() != scope["ref"]):
        raise GitError("分支或基准在审查期间变化，请重新审查 / Branch or base changed during review")


def load_branch_diff_info(base):
    from gai.common.config import load_settings
    from gai.review.engine import StagedDiffInfo
    ensure_repo()
    settings = load_settings()
    base_commit = checked("rev-parse", "--verify", "--end-of-options", base + "^{commit}")
    head = checked("rev-parse", "--verify", "HEAD")
    ref = run_git("symbolic-ref", "-q", "HEAD").stdout.strip()
    merge_bases = checked("merge-base", "--all", base_commit, head).splitlines()
    if len(merge_bases) != 1:
        raise GitError("Cannot choose a unique merge base")
    merge_base = merge_bases[0]
    diff = run_git("diff", *_PATCH_OPTIONS, merge_base, head, "--")
    if diff.returncode:
        raise GitError(diff.stderr)
    paths = run_git("diff", "--name-only", "-z", merge_base, head, "--")
    if paths.returncode:
        raise GitError(paths.stderr)
    scope = {"kind": "branch", "base": base, "base_commit": base_commit,
             "merge_base": merge_base, "head": head, "ref": ref,
             "files": [p for p in paths.stdout.split("\0") if p]}
    snapshot = StagedSnapshot(checked("rev-parse", head + "^{tree}"), head, ref)
    text = filter_diff_by_ignore(diff.stdout, settings.ignore_patterns)
    validate_scope(scope)
    return StagedDiffInfo(text, len(text), settings.max_diff_chars,
                          len(text) > settings.max_diff_chars, snapshot, scope)
