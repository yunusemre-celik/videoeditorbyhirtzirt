#!/usr/bin/env python3
"""3-Word Dynamic Subtitle Chunker & SRT Generator.

Reads speech words from work/program.json and optional subtitle config / overrides
from work/edits.json, grouping spoken words into dynamic phrase-aware cues of at
most 3 words that swap cleanly without per-word karaoke color changes.
Outputs work/subtitles.json and work/subtitles.srt.
"""
import argparse
import os
import sys

try:
    from scripts._common import load_json, project_paths, save_json
except ImportError:
    from _common import load_json, project_paths, save_json

MAX_WORDS = 3
PAUSE_BREAK_SEC = 0.35
PUNCT_BREAK = set(".,!?;:")
MIN_DURATION_SEC = 0.2


def chunk_three_words(
    words: list,
    max_words: int = MAX_WORDS,
    pause_break: float = PAUSE_BREAK_SEC,
    overrides: dict | None = None,
    uppercase: bool = False,
) -> list[dict]:
    """Group words into dynamic phrase-aware chunks of at most max_words words.

    Breaks on:
    - len(current) >= max_words
    - word ends with punctuation in PUNCT_BREAK (.,!?;:)
    - silence gap between current word end and next word start >= pause_break
    - end of words list

    Empty, whitespace-only, or punctuation-only tokens are filtered out.
    Ensures end > start with a minimum duration fallback of 0.2s.
    """
    valid_words = [
        w for w in (words or [])
        if len(w) >= 3 and any(c.isalnum() for c in str(w[2]))
    ]
    if not valid_words:
        return []

    cues: list[dict] = []
    current: list = []
    cue_idx = 0

    for i, w in enumerate(valid_words):
        current.append(w)
        w_text = str(w[2]).strip()

        # Check closing conditions
        reached_limit = len(current) >= max_words
        punct_hit = any(w_text.rstrip('"\'“”‘’').endswith(p) for p in PUNCT_BREAK)
        pause_hit = False
        if i + 1 < len(valid_words):
            next_start = float(valid_words[i + 1][0])
            curr_end = float(w[1])
            if round(next_start - curr_end, 3) >= pause_break:
                pause_hit = True
        is_last = (i == len(valid_words) - 1)

        if reached_limit or punct_hit or pause_hit or is_last:
            cue_id = f"sub_{cue_idx}"
            start = round(float(current[0][0]), 3)
            raw_end = float(current[-1][1])
            end = round(max(raw_end, start + MIN_DURATION_SEC), 3)
            next_word_start = float(valid_words[i + 1][0]) if i + 1 < len(valid_words) else None
            if next_word_start is not None and next_word_start > start:
                end = min(end, round(next_word_start, 3))

            text = " ".join(str(item[2]).strip() for item in current)
            if overrides and cue_id in overrides:
                text = overrides[cue_id]
            if uppercase:
                text = text.upper()

            cues.append({
                "id": cue_id,
                "start": start,
                "end": end,
                "text": text,
                "words": [list(item) for item in current],
            })
            current = []
            cue_idx += 1

    return cues


def _format_srt_time(seconds: float) -> str:
    """Format seconds into SRT timestamp format HH:MM:SS,mmm."""
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_srt(cues: list[dict]) -> str:
    """Format subtitle cues into standard SubRip (.srt) text."""
    blocks: list[str] = []
    for idx, cue in enumerate(cues, start=1):
        start_ts = _format_srt_time(cue["start"])
        end_ts = _format_srt_time(cue["end"])
        text = cue.get("text", "")
        blocks.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")
    return "\n".join(blocks)


def build_project_subtitles(
    project: str,
    max_words: int = MAX_WORDS,
    pause_break: float = PAUSE_BREAK_SEC,
) -> list[dict]:
    """Generate work/subtitles.json and work/subtitles.srt from work/program.json and work/edits.json."""
    _, work = project_paths(project)
    prog_path = os.path.join(work, "program.json")
    if not os.path.exists(prog_path):
        words = []
    else:
        prog = load_json(prog_path)
        words = prog.get("words", [])

    overrides = None
    uppercase = False
    edits_path = os.path.join(work, "edits.json")
    if os.path.exists(edits_path):
        edits = load_json(edits_path)
        sub_cfg = edits.get("subtitles") or {}
        overrides = sub_cfg.get("overrides")
        uppercase = bool(sub_cfg.get("uppercase", False))

    cues = chunk_three_words(
        words,
        max_words=max_words,
        pause_break=pause_break,
        overrides=overrides,
        uppercase=uppercase,
    )

    save_json(os.path.join(work, "subtitles.json"), cues)
    srt_content = format_srt(cues)
    with open(os.path.join(work, "subtitles.srt"), "w", encoding="utf-8") as f:
        f.write(srt_content)

    return cues


def main():
    parser = argparse.ArgumentParser(description="Generate 3-word dynamic subtitles and SRT")
    parser.add_argument("--project", default=".", help="Project directory (default: current directory)")
    parser.add_argument("--max-words", type=int, default=MAX_WORDS, help=f"Max words per cue (default: {MAX_WORDS})")
    parser.add_argument(
        "--pause-break",
        type=float,
        default=PAUSE_BREAK_SEC,
        help=f"Pause break threshold in seconds (default: {PAUSE_BREAK_SEC})",
    )
    args = parser.parse_args()
    cues = build_project_subtitles(args.project, max_words=args.max_words, pause_break=args.pause_break)
    print(f"Generated {len(cues)} subtitle cues for {args.project}")


if __name__ == "__main__":
    main()
