from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_TIMESTAMP_RE = re.compile(r"^(?P<h>\d{2,}):(?P<m>[0-5]\d):(?P<s>[0-5]\d),(?P<ms>\d{3})$")
_TECH_MARKER_RE = re.compile(
    r"\[(?:music|singing|applause|instrumental|background music|musica|música|cantando|aplausos)\]",
    re.IGNORECASE,
)
_TERMINAL_RE = re.compile(r"[.!?…][\"'’”)]*$")
_SUSPICIOUS_TOKEN_RE = re.compile(r"(^|\s)[^\w\s'’.,!?-]{2,}(?=\s|$)")
_WORD_RE = re.compile(r"\b[\w'’]+\b", re.UNICODE)


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    text: str


def _timestamp_seconds(value: str) -> float | None:
    match = _TIMESTAMP_RE.fullmatch(value.strip())
    if not match:
        return None
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000.0
    )


def _format_timestamp(seconds: float) -> str:
    value = max(0.0, float(seconds))
    total_ms = int(round(value * 1000.0))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt(content: str) -> tuple[list[Cue], list[str], dict[str, int]]:
    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    errors: list[str] = []
    counts = {
        "overlap_count": 0,
        "empty_cue_count": 0,
        "malformed_cue_count": 0,
        "duplicate_index_count": 0,
    }
    if not text:
        return [], ["empty_srt"], {**counts, "malformed_cue_count": 1}

    cues: list[Cue] = []
    seen_indices: set[int] = set()
    blocks = re.split(r"\n\s*\n", text)
    for block_no, block in enumerate(blocks, 1):
        lines = [line.rstrip() for line in block.split("\n")]
        if len(lines) < 2:
            counts["malformed_cue_count"] += 1
            errors.append(f"malformed_block:{block_no}")
            continue
        try:
            index = int(lines[0].strip())
        except Exception:
            counts["malformed_cue_count"] += 1
            errors.append(f"invalid_index:{block_no}")
            continue
        if index in seen_indices:
            counts["duplicate_index_count"] += 1
            errors.append(f"duplicate_index:{index}")
        seen_indices.add(index)

        if "-->" not in lines[1]:
            counts["malformed_cue_count"] += 1
            errors.append(f"missing_timing:{index}")
            continue
        left, right = [part.strip() for part in lines[1].split("-->", 1)]
        start = _timestamp_seconds(left)
        end = _timestamp_seconds(right)
        if start is None or end is None:
            counts["malformed_cue_count"] += 1
            errors.append(f"invalid_timestamp:{index}")
            continue

        cue_text = "\n".join(lines[2:]).strip()
        if not cue_text:
            counts["empty_cue_count"] += 1
            errors.append(f"empty_cue:{index}")
        if end <= start:
            errors.append(f"non_positive_duration:{index}")
        cues.append(Cue(index=index, start=start, end=end, text=cue_text))

    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end, cue.index))
    if [cue.index for cue in ordered] != [cue.index for cue in cues]:
        errors.append("invalid_temporal_order")
    for previous, current in zip(ordered, ordered[1:]):
        if current.start < previous.end - 0.001:
            counts["overlap_count"] += 1
    return cues, errors, counts


def _dedupe_words(text: str) -> str:
    words = text.split()
    if not words:
        return ""
    out: list[str] = []
    for word in words:
        if out and word.casefold() == out[-1].casefold():
            continue
        out.append(word)
    result = " ".join(out)
    # Collapse an immediately repeated short phrase of up to four words.
    tokens = result.split()
    for size in range(4, 1, -1):
        i = 0
        rebuilt: list[str] = []
        while i < len(tokens):
            if i + 2 * size <= len(tokens):
                a = [x.casefold() for x in tokens[i:i + size]]
                b = [x.casefold() for x in tokens[i + size:i + 2 * size]]
                if a == b:
                    rebuilt.extend(tokens[i:i + size])
                    i += 2 * size
                    continue
            rebuilt.append(tokens[i])
            i += 1
        tokens = rebuilt
    return " ".join(tokens)


def sanitize_caption_text(text: str, *, preserve_sdh_markers: bool = False, music_mode: bool = False) -> str:
    raw_lines = str(text or "").replace("\r", "").split("\n")
    clean_lines: list[str] = []
    for raw in raw_lines:
        line = " ".join(raw.strip().split())
        if not preserve_sdh_markers:
            line = _TECH_MARKER_RE.sub("", line)
        line = " ".join(line.split())
        if line:
            clean_lines.append(_dedupe_words(line))
    if not clean_lines:
        return ""
    if music_mode:
        return "\n".join(clean_lines[:2])
    return " ".join(clean_lines)


def _wrap_two_lines(text: str, *, max_line_length: int) -> str:
    words = text.split()
    if not words:
        return ""
    lines: list[str] = [""]
    for word in words:
        candidate = word if not lines[-1] else f"{lines[-1]} {word}"
        if len(candidate) <= max_line_length or len(lines) == 2:
            lines[-1] = candidate
        else:
            lines.append(word)
    return "\n".join(lines[:2])


def _repair_timing(cues: list[Cue], video_duration: float | None) -> list[Cue]:
    repaired: list[Cue] = []
    for raw in sorted(cues, key=lambda cue: (cue.start, cue.end, cue.index)):
        start = max(0.0, raw.start)
        if repaired and start < repaired[-1].end:
            start = repaired[-1].end
        end = raw.end
        if video_duration is not None:
            end = min(end, video_duration)
        if end <= start:
            end = start + 0.5
            if video_duration is not None:
                end = min(end, video_duration)
        repaired.append(Cue(index=raw.index, start=start, end=end, text=raw.text))
    return repaired


def _merge_fragmented(cues: list[Cue], *, music_mode: bool) -> list[Cue]:
    if music_mode:
        return cues
    merged: list[Cue] = []
    for cue in cues:
        if not merged:
            merged.append(cue)
            continue
        previous = merged[-1]
        gap = cue.start - previous.end
        combined = f"{previous.text} {cue.text}".strip()
        if (
            gap <= 0.35
            and not _TERMINAL_RE.search(previous.text)
            and (cue.end - previous.start) <= 7.0
            and len(combined) <= 84
        ):
            merged[-1] = Cue(index=previous.index, start=previous.start, end=cue.end, text=combined)
        else:
            merged.append(cue)
    return merged


def _text_warnings(cues: list[Cue]) -> list[str]:
    warnings: list[str] = []
    joined = " ".join(cue.text for cue in cues)
    if re.search(r"\b\w+-\s*$", joined):
        warnings.append("possible_truncated_word")
    if _SUSPICIOUS_TOKEN_RE.search(joined):
        warnings.append("suspicious_tokens")
    words = [word.casefold() for word in _WORD_RE.findall(joined)]
    for i in range(max(0, len(words) - 3)):
        if len(words[i]) > 2 and len(set(words[i:i + 4])) == 1:
            warnings.append("abnormal_repetition")
            break
    for cue in cues:
        if cue.text and not _TERMINAL_RE.search(cue.text) and (cue.end - cue.start) >= 6.5:
            warnings.append("possible_incomplete_phrase")
            break
    return list(dict.fromkeys(warnings))


def render_srt(cues: list[Cue]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, 1):
        blocks.append(
            f"{index}\n{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}\n{cue.text}"
        )
    return "\n\n".join(blocks).strip() + "\n"


def process_srt(
    content: str,
    *,
    video_duration: float | None = None,
    preserve_sdh_markers: bool = False,
    music_mode: bool = False,
    min_duration: float = 1.0,
    max_duration: float = 7.0,
    max_line_length: int = 42,
) -> dict[str, Any]:
    parsed, parse_errors, original_counts = parse_srt(content)
    structural_errors = [
        error
        for error in parse_errors
        if error.startswith(("malformed_", "invalid_", "duplicate_", "missing_", "empty_cue", "non_positive_"))
    ]
    if video_duration is not None:
        for cue in parsed:
            if cue.start < 0 or cue.end > video_duration + 0.001 or cue.start > video_duration + 0.001:
                structural_errors.append(f"cue_outside_video:{cue.index}")

    sanitized: list[Cue] = []
    for cue in parsed:
        clean = sanitize_caption_text(
            cue.text,
            preserve_sdh_markers=preserve_sdh_markers,
            music_mode=music_mode,
        )
        sanitized.append(Cue(cue.index, cue.start, cue.end, clean))

    repaired = _repair_timing(sanitized, video_duration)
    rebuilt = _merge_fragmented(repaired, music_mode=music_mode)

    final_cues: list[Cue] = []
    warnings: list[str] = []
    for cue in rebuilt:
        text = cue.text.strip()
        if not text:
            structural_errors.append(f"empty_cue_after_sanitization:{cue.index}")
            continue
        wrapped = text if music_mode and "\n" in text else _wrap_two_lines(text, max_line_length=max_line_length)
        duration = cue.end - cue.start
        if duration < min_duration - 0.001:
            warnings.append(f"short_cue:{cue.index}")
        if duration > max_duration + 0.001:
            warnings.append(f"long_cue:{cue.index}")
        if any(len(line) > max_line_length for line in wrapped.split("\n")):
            warnings.append(f"long_line:{cue.index}")
        final_cues.append(Cue(cue.index, cue.start, cue.end, wrapped))

    final_srt = render_srt(final_cues) if final_cues else ""
    final_parsed, final_errors, final_counts = parse_srt(final_srt)
    for error in final_errors:
        if error not in structural_errors:
            structural_errors.append(error)

    if video_duration is not None:
        for cue in final_parsed:
            if cue.end > video_duration + 0.001:
                structural_errors.append(f"cue_outside_video:{cue.index}")

    total_caption_time = sum(max(0.0, cue.end - cue.start) for cue in final_parsed)
    coverage = None
    if video_duration and video_duration > 0:
        coverage = min(1.0, total_caption_time / video_duration)

    cps_values = [
        len(cue.text.replace("\n", " ")) / max(0.001, cue.end - cue.start)
        for cue in final_parsed
        if cue.text
    ]
    avg_cps = sum(cps_values) / len(cps_values) if cps_values else 0.0
    if avg_cps == 0:
        readability = "unknown"
    elif avg_cps <= 17:
        readability = "good"
    elif avg_cps <= 21:
        readability = "fast"
    else:
        readability = "too_fast"

    warnings.extend(_text_warnings(final_parsed))
    if original_counts["overlap_count"]:
        warnings.append(f"timing_overlap_repaired:{original_counts['overlap_count']}")
    if any(_TECH_MARKER_RE.search(cue.text) for cue in parsed) and not preserve_sdh_markers:
        warnings.append("technical_markers_removed")

    errors = list(dict.fromkeys(structural_errors))
    warnings = list(dict.fromkeys(warnings))
    return {
        "content": final_srt,
        "validation_passed": not errors,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "cue_count": len(final_parsed),
        "overlap_count": final_counts["overlap_count"],
        "source_overlap_count": original_counts["overlap_count"],
        "empty_cue_count": final_counts["empty_cue_count"],
        "malformed_cue_count": final_counts["malformed_cue_count"],
        "duplicate_index_count": final_counts["duplicate_index_count"],
        "duration_coverage": coverage,
        "estimated_readability": {
            "rating": readability,
            "average_chars_per_second": round(avg_cps, 2),
            "max_line_length": max_line_length,
            "max_lines": 2,
            "target_duration_seconds": [min_duration, max_duration],
        },
    }
