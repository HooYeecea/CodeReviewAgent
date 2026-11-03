"""Decode Git patch paths, including C quoting and ambiguous spaces."""
import re


def unquote_path(value: str) -> str:
    if not value.startswith('"'):
        return value
    if not re.fullmatch(r'"(?:[^"\\]|\\.)*"', value):
        raise ValueError("Invalid Git quoted path")
    output = bytearray()
    escapes = {'a': 7, 'b': 8, 't': 9, 'n': 10, 'v': 11, 'f': 12, 'r': 13,
               '\\': 92, '"': 34}
    i = 1
    while i < len(value) - 1:
        if value[i] != '\\':
            output.extend(value[i].encode('utf-8'))
            i += 1
            continue
        i += 1
        if value[i] in escapes:
            output.append(escapes[value[i]])
            i += 1
        else:
            match = re.match(r'[0-7]{1,3}', value[i:-1])
            if not match or int(match[0], 8) > 255:
                raise ValueError("Invalid Git path escape")
            output.append(int(match[0], 8))
            i += len(match[0])
    return output.decode('utf-8', errors='surrogateescape')


def patch_paths(chunk: str) -> tuple[str, str]:
    header, _, body = chunk.partition('\n')
    header = header.removeprefix('diff --git ')
    candidates = set()
    # Git leaves ordinary spaces unquoted. Try each possible separator, then
    # disambiguate with rename/copy metadata or the two identical paths.
    for separator in re.finditer(r' (?=(?:b/|"b/))', header):
        try:
            left = unquote_path(header[:separator.start()])
            right = unquote_path(header[separator.end():])
        except ValueError:
            continue
        if left.startswith('a/') and right.startswith('b/'):
            candidates.add((left[2:], right[2:]))
    metadata = {}
    for line in body.split('\n'):
        if line.startswith(('@@', 'GIT binary patch', 'Binary files ')):
            break
        for prefix in ('rename from ', 'rename to ', 'copy from ', 'copy to '):
            if line.startswith(prefix):
                metadata[prefix] = unquote_path(line[len(prefix):])
    for kind in ('rename', 'copy'):
        if kind + ' from ' in metadata and kind + ' to ' in metadata:
            pair = (metadata[kind + ' from '], metadata[kind + ' to '])
            if pair not in candidates:
                raise ValueError("Inconsistent Git patch paths")
            return pair
    if len(candidates) == 1:
        return candidates.pop()
    identical = [pair for pair in candidates if pair[0] == pair[1]]
    if len(identical) == 1:
        return identical[0]
    raise ValueError("Cannot determine Git patch paths safely")
