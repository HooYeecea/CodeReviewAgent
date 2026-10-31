"""Per-file content fingerprints, with process-local metadata reuse.

Resume, staging and commit boundaries request strict reads. Intermediate UI
checks can reuse content hashes only while identity, size and timestamps match.
No metadata cache is trusted across process restarts.
"""
import hashlib
import json
import os
import stat

from gai.common.git import GitError, ensure_repo, run_git


def file_manifest(root, *, cache=None, strict=True):
    cache = {} if cache is None else cache
    result = run_git("ls-files", "--cached", "--others", "--exclude-standard", "-z", cwd=root)
    if result.returncode:
        raise GitError(result.stderr)
    files = {}
    for name in sorted(set(result.stdout.split("\0")) - {""}):
        if name == ".gai" or name.startswith(".gai/"):
            continue
        path = root / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        key = str(path)
        stamp = (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        cached = cache.get(key)
        if not strict and cached and cached[0] == stamp and not stat.S_ISDIR(info.st_mode):
            files[name] = cached[1]
            continue
        digest = hashlib.sha256()
        digest.update(str(info.st_mode).encode())
        if stat.S_ISLNK(info.st_mode):
            digest.update(os.readlink(path).encode())
        elif stat.S_ISREG(info.st_mode):
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        elif stat.S_ISDIR(info.st_mode):
            if ensure_repo(path).resolve() == path.resolve():
                head = run_git("rev-parse", "HEAD", cwd=path)
                if head.returncode:
                    raise GitError(head.stderr)
                digest.update(head.stdout.encode())
                digest.update(manifest_digest(file_manifest(path, cache=cache, strict=strict)).encode())
            else:
                digest.update(b"uninitialized-submodule")
        after = path.lstat()
        new_stamp = (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if new_stamp != stamp:
            raise GitError(f"文件在检查期间变化 / File changed during inspection: {name}")
        files[name] = digest.hexdigest()
        cache[key] = (stamp, files[name])
    return files


def manifest_digest(files):
    return "v2:" + hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def changed_files(before, after):
    return sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
