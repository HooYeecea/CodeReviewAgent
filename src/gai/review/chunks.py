"""Bounded patch chunks that retain Git paths and original hunk coordinates."""
import re

from gai.common.git.diff_paths import patch_paths

HEADER = re.compile(r"(?=^diff --git )", re.MULTILINE)
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@.*(?:\n|$)")


def sections(text):
    return [part for part in HEADER.split(text) if part]


def paths(text):
    return sorted({patch_paths(part)[1] for part in sections(text)})


def coverage(text, sent_chars, all_files=(), *, failed=False, parts=1):
    reviewed, partial, missing = [], [], []
    offset = 0
    for section in sections(text):
        name = patch_paths(section)[1]
        end = offset + len(section)
        if failed or offset >= sent_chars:
            missing.append(name)
        elif re.search(r"^(?:Binary files .* differ|GIT binary patch)$", section, re.MULTILINE):
            # A binary marker/encoding contains no source text for the model.
            partial.append(name)
        elif end <= sent_chars:
            reviewed.append(name)
        else:
            partial.append(name)
        offset = end
    return {"state": "failed" if failed else ("incomplete" if partial or missing else "complete"),
            "reviewed_files": sorted(set(reviewed)),
            "partially_reviewed_files": sorted(set(partial)),
            "unreviewed_files": sorted(set(missing)),
            "ignored_files": sorted(set(all_files) - set(reviewed + partial + missing)),
            "parts": parts}


def split_patch(text, limit):
    """Split by files, then hunks, then whole lines with corrected coordinates."""
    output = []
    for section in sections(text):
        if len(section) <= limit:
            output.append(section)
            continue
        lines = section.splitlines(keepends=True)
        first = next((i for i, line in enumerate(lines) if HUNK.match(line)), None)
        if first is None:
            raise RuntimeError("Diff metadata exceeds limit; increase max_diff_chars")
        prefix = "".join(lines[:first])
        old = new = 0
        body = []
        body_chars = 0
        old_count = new_count = 0
        def emit():
            return prefix + f"@@ -{old},{old_count} +{new},{new_count} @@\n" + "".join(body)
        for line in lines[first:]:
            match = HUNK.match(line)
            if match:
                if body:
                    output.append(emit())
                old, new = map(int, match.groups())
                body, old_count, new_count, body_chars = [], 0, 0, 0
                continue
            # Reserve space for hunk coordinates; never cut a source line.
            if len(prefix) + 80 + body_chars + len(line) > limit:
                if not body:
                    raise RuntimeError("单行差异过长，请调大 max_diff_chars / Single diff line exceeds chunk limit")
                output.append(emit())
                old += old_count
                new += new_count
                body, old_count, new_count, body_chars = [], 0, 0, 0
                if len(prefix) + 80 + len(line) > limit:
                    raise RuntimeError("Single diff line exceeds chunk limit")
            body.append(line)
            body_chars += len(line)
            old_count += line.startswith((" ", "-"))
            new_count += line.startswith((" ", "+"))
        if body:
            output.append(emit())
    # Pack small files/hunks while respecting the configured input limit.
    packed = []
    for part in output:
        if packed and len(packed[-1]) + len(part) <= limit:
            packed[-1] += part
        else:
            packed.append(part)
    if len(packed) > 128:
        raise RuntimeError("More than 128 review chunks; narrow the review or increase max_diff_chars")
    return packed
