from __future__ import annotations

import re
from dataclasses import dataclass

# Tokens often appended by scene groups — strip before matching
_QUALITY_TOKENS = re.compile(
    r"(?i)[.\-_\s]?(?:1080p|720p|2160p|4k|8k|x264|x265|h264|h265|hevc|aac|ac3|flac|web-?dl|bluray|blu-?ray|remux|hdr|uhd|dvdrip|hdrip|fhd|chs|cht|jav)$"
)

_FC2 = re.compile(r"(?i)\bFC2[-_ ]?(?:PPV[-_ ]?)?(\d{6,8})\b")
_HEYZO = re.compile(r"(?i)\bHEYZO[-_ ]?(\d{3,5})\b")
_STANDARD = re.compile(
    r"(?i)\b([A-Z]{2,15})[-_ ]?(\d{2,5})(?:[-_ ]?(C|CD\d+|PART\d+))?\b"
)
_DISC = re.compile(r"(?i)(?:^|[-_\s.])(cd\d+|part\d+)(?:$|[-_\s.])")
_SUB_C = re.compile(r"(?i)(?:^|[-_\s.])C(?:$|[-_\s.])|中字|中文字幕")


@dataclass
class ParsedName:
    number: str | None
    disc: str | None
    subtitle_flag: str | None
    raw_stem: str


def _strip_quality(stem: str) -> str:
    prev = None
    cur = stem
    while prev != cur:
        prev = cur
        cur = _QUALITY_TOKENS.sub("", cur)
    return cur.strip(" .-_")


def extract_number(filename: str) -> ParsedName:
    """Extract 番号-style code from a media filename."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    raw_stem = stem
    cleaned = stem.replace(" ", "-")
    cleaned = _strip_quality(cleaned)

    disc: str | None = None
    m_disc = _DISC.search(cleaned)
    if m_disc:
        disc = m_disc.group(1).lower()

    subtitle_flag: str | None = None
    if _SUB_C.search(cleaned) or re.search(r"(?i)-C(?:-|$)", cleaned):
        subtitle_flag = "C"

    m = _FC2.search(cleaned)
    if m:
        return ParsedName(number=f"FC2-{m.group(1)}", disc=disc, subtitle_flag=subtitle_flag, raw_stem=raw_stem)

    m = _HEYZO.search(cleaned)
    if m:
        return ParsedName(number=f"HEYZO-{m.group(1)}", disc=disc, subtitle_flag=subtitle_flag, raw_stem=raw_stem)

    # Prefer match closest to start; skip pure quality-looking codes
    for m in _STANDARD.finditer(cleaned):
        prefix = m.group(1).upper()
        digits = m.group(2)
        if prefix in {"CD", "PART", "VOL", "DISC", "H264", "H265", "X264", "X265", "AAC"}:
            continue
        number = f"{prefix}-{digits}"
        extra = m.group(3)
        if extra:
            extra_u = extra.upper()
            if extra_u == "C":
                subtitle_flag = subtitle_flag or "C"
            elif extra_u.startswith("CD") or extra_u.startswith("PART"):
                disc = disc or extra.lower()
        return ParsedName(number=number, disc=disc, subtitle_flag=subtitle_flag, raw_stem=raw_stem)

    return ParsedName(number=None, disc=disc, subtitle_flag=subtitle_flag, raw_stem=raw_stem)


def normalize_number(raw: str | None) -> str | None:
    """Normalize a user- or filename-sourced 番号 for storage / MetaTube search."""
    s = (raw or "").strip()
    if not s:
        return None
    # Prefer structured parse (works for free-typed codes like "ssis 001")
    candidate = s if "." in s else f"{s}.mp4"
    parsed = extract_number(candidate)
    if parsed.number:
        return parsed.number[:64]
    s = re.sub(r"[\s_]+", "-", s.upper())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:64] if s else None
