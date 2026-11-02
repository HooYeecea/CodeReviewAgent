"""Readable, bounded Windows-compatible names; identities stay separate."""
import re
import unicodedata

_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.I)


def shorten(value: str, limit: int) -> str:
    # Windows counts UTF-16 code units, including both halves of emoji.
    return value.encode("utf-16-le", "replace")[:limit * 2].decode("utf-16-le", "ignore")


def safe_name(value: str, *, limit: int = 36, fallback: str = "代码审查") -> str:
    value = unicodedata.normalize("NFKC", value)
    value = "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)
    value = _FORBIDDEN.sub("_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip(" ._")
    value = shorten(value, limit).rstrip(" ._") or fallback
    if _RESERVED.fullmatch(value):
        value = shorten("_" + value, limit)
    return value


def valid_component(value, *, limit=96) -> bool:
    return (isinstance(value, str) and bool(value) and value not in {".", ".."}
            and value == value.strip(" .") and not _FORBIDDEN.search(value)
            and not any(unicodedata.category(c).startswith("C") for c in value)
            and not _RESERVED.fullmatch(unicodedata.normalize("NFKC", value))
            and len(value.encode("utf-16-le")) <= limit * 2)


def short_title(text: str) -> str:
    """Use a short sentence from existing prose, without another model call."""
    generic = {"summary", "review summary", "摘要", "审查摘要", "总结", "ok", "looks fine",
               "no issues", "no issues found", "代码审查", "无问题", "未发现问题"}
    for line in str(text).splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", line).strip(" `*_")
        line = re.split(r"[。！？!?；;]|\.\s", line, maxsplit=1)[0].strip(" .：:")
        if line and line.casefold() not in generic:
            return line
    return ""


def review_title(record: dict, batch_title: str = "") -> str:
    fallback = "代码审查" if record["language"] == "cn" else "Code-review"
    # devflow uses a synthetic batch title, which is not a review topic.
    title = short_title(batch_title) if batch_title not in {"devflow", "splitflow"} else ""
    if not title and record["result"]["parsed_ok"]:
        title = short_title(record["result"].get("summary", ""))
    if not title:
        names = [path.replace("\\", "/").rsplit("/", 1)[-1] for path in record["staged_files"]]
        title = "_".join(names[:2]) or fallback
    return safe_name(title, fallback=fallback)


def report_stem(record: dict) -> str:
    # Existing archives retain their original filenames and links on resume.
    return record.get("filename") or "review-" + record["id"]
