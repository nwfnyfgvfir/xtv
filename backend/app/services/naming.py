from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

RECOGNITION_VERSION = "names-v2"

# Tokens often appended by scene groups — strip before matching
_QUALITY_TOKENS = re.compile(
    r"(?i)[.\-_\s]?(?:1080p|720p|2160p|4k|8k|x264|x265|h264|h265|hevc|aac|ac3|flac|web-?dl|bluray|blu-?ray|remux|hdr|uhd|dvdrip|hdrip|fhd|chs|cht|jav)$"
)

_FC2 = re.compile(r"(?i)(?<![a-z0-9])FC2[-_. ]*(?:PPV[-_. ]*)?(\d{6,8})(?![a-z0-9])")
_HEYZO = re.compile(r"(?i)(?<![a-z0-9])HEYZO[-_. ]*(\d{3,5})(?![a-z0-9])")
_STANDARD = re.compile(
    r"(?i)(?<![a-z0-9])([A-Z]{2,15})[-_. ]*(\d{2,5})(?![a-z0-9])"
)
_DATE_STYLE = re.compile(r"(?<!\d)(\d{6})[_.\- ](\d{2,3})(?!\d)")
_DISC = re.compile(r"(?i)(?:^|[-_\s.])(cd\d+|part\d+)(?:$|[-_\s.])")
_SUB_C = re.compile(r"(?i)(?:^|[-_\s.])C(?:$|[-_\s.])|中字|中文字幕")


@dataclass
class ParsedName:
    number: str | None
    disc: str | None
    subtitle_flag: str | None
    raw_stem: str
    candidates: list[str] = field(default_factory=list)
    source: str | None = None
    notes: list[str] = field(default_factory=list)


def _strip_quality(stem: str) -> str:
    prev = None
    cur = stem
    while prev != cur:
        prev = cur
        cur = _QUALITY_TOKENS.sub("", cur)
    return cur.strip(" .-_")


def extract_number(filename: str, *, stem_only: bool = False) -> ParsedName:
    """Extract 番号-style code from a media filename."""
    filename = unicodedata.normalize("NFKC", filename).translate(str.maketrans({c: "-" for c in "–—−﹣"}))
    stem = filename if stem_only else filename.rsplit(".", 1)[0] if "." in filename else filename
    raw_stem = stem
    cleaned = stem.replace(" ", "-")
    cleaned = _strip_quality(cleaned)
    cleaned = re.sub(r"(?i)^.*?[a-z0-9.-]+\.(?:com|net|org|xyz|example|tv)(?:/[^@\s]*)?[@_ -]+", "", cleaned)

    disc: str | None = None
    m_disc = _DISC.search(cleaned)
    if m_disc:
        disc = m_disc.group(1).lower()

    subtitle_flag: str | None = None
    if _SUB_C.search(cleaned) or re.search(r"(?i)-C(?:-|$)", cleaned):
        subtitle_flag = "C"

    candidates = []
    for regex, prefix in ((_FC2, "FC2"), (_HEYZO, "HEYZO")):
        candidates.extend(f"{prefix}-{m.group(1)}" for m in regex.finditer(cleaned))
    for m in _STANDARD.finditer(cleaned):
        prefix = m.group(1).upper()
        digits = m.group(2)
        if prefix in {"CD", "PART", "VOL", "DISC", "H264", "H265", "X264", "X265", "AAC", "HDR", "HEVC", "FC", "HEYZO"}:
            continue
        number = f"{prefix}-{digits}"
        candidates.append(number)
    candidates.extend(f"{m.group(1)}-{m.group(2)}" for m in _DATE_STYLE.finditer(cleaned))
    candidates = list(dict.fromkeys(candidates))
    return ParsedName(number=candidates[0] if len(candidates) == 1 else None, disc=disc,
        subtitle_flag=subtitle_flag, raw_stem=raw_stem, candidates=candidates,
        source="filename" if len(candidates) == 1 else None,
        notes=["文件名包含多个番号，请手动确认"] if len(candidates) > 1 else [])


def recognize_path(path: Path, root: Path, parent_depth: int = 2) -> ParsedName:
    result = extract_number(path.name)
    parent_result = None
    parent = path.parent
    for _ in range(max(0, min(parent_depth, 3))):
        if parent == root or not parent.is_relative_to(root):
            break
        candidate = extract_number(parent.name, stem_only=True)
        if re.search(r"(?i)合集|全集|collection|compilation", parent.name) or len(candidate.candidates) > 1:
            break
        if candidate.number:
            parent_result = candidate
            break
        parent = parent.parent
    if result.number and parent_result and result.number != parent_result.number:
        result.notes.append(f"文件名与父目录番号冲突：目录为 {parent_result.number}，采用文件名")
    if not result.candidates and parent_result:
        result.number, result.candidates, result.source = parent_result.number, parent_result.candidates, "parent"
        result.notes.append("番号取自最近的有效父目录")
    return result


def normalize_number(raw: str | None) -> str | None:
    """Normalize a user- or filename-sourced 番号 for storage / MetaTube search."""
    s = (raw or "").strip()
    if not s:
        return None
    # Prefer structured parse (works for free-typed codes like "ssis 001")
    candidate = s if "." in s else f"{s}.mp4"
    parsed = extract_number(candidate)
    if not parsed.number and "." in s:
        parsed = extract_number(s + ".mp4")
    if parsed.number:
        return parsed.number[:64]
    s = re.sub(r"[\s_]+", "-", s.upper())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:64] if s else None
