import json
import os
from scripts.subtitles import build_project_subtitles, chunk_three_words, format_srt


def test_chunk_three_words_splits_every_three_words():
    words = [
        [0.0, 0.2, "One"],
        [0.25, 0.45, "two"],
        [0.5, 0.7, "three"],
        [0.75, 0.95, "four"],
        [1.0, 1.2, "five"],
    ]
    cues = chunk_three_words(words)
    assert len(cues) == 2
    assert cues[0]["id"] == "sub_0"
    assert cues[0]["text"] == "One two three"
    assert cues[0]["start"] == 0.0
    assert cues[0]["end"] == 0.7
    assert cues[1]["id"] == "sub_1"
    assert cues[1]["text"] == "four five"
    assert cues[1]["start"] == 0.75
    assert cues[1]["end"] == 1.2


def test_chunk_three_words_breaks_on_punctuation_and_pause():
    words = [
        [0.0, 0.3, "Wait."],
        [0.35, 0.6, "Watch"],
        [1.1, 1.4, "this"],
        [1.45, 1.7, "now"],
    ]
    cues = chunk_three_words(words, max_words=3, pause_break=0.35)
    assert [c["text"] for c in cues] == ["Wait.", "Watch", "this now"]


def test_chunk_three_words_handles_empty_and_overrides():
    words = [
        [0.0, 0.2, "  "],
        [0.2, 0.5, "hello"],
        [0.55, 0.8, "world"],
    ]
    cues = chunk_three_words(words, overrides={"sub_0": "Custom Text"}, uppercase=True)
    assert len(cues) == 1
    assert cues[0]["text"] == "CUSTOM TEXT"


def test_format_srt_outputs_valid_srt_blocks():
    cues = [{"id": "sub_0", "start": 0.5, "end": 1.75, "text": "Hello world today", "words": []}]
    srt = format_srt(cues)
    assert "1\n00:00:00,500 --> 00:00:01,750\nHello world today\n" in srt


def test_chunk_three_words_min_duration_fallback():
    # If word is very short (e.g. 0.05s), end should be fallback to at least start + 0.2s
    words = [[0.1, 0.15, "quick"]]
    cues = chunk_three_words(words)
    assert len(cues) == 1
    assert cues[0]["start"] == 0.1
    assert cues[0]["end"] >= round(0.1 + 0.2, 3)


def test_build_project_subtitles_e2e(tmp_path):
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    prog_data = {
        "words": [
            [0.1, 0.3, "Hello"],
            [0.35, 0.6, "Antigravity"],
            [0.65, 0.9, "World!"],
            [1.5, 1.8, "Next"],
            [1.85, 2.1, "line"],
        ]
    }
    edits_data = {
        "subtitles": {
            "uppercase": True,
            "overrides": {"sub_0": "HELLO UNIVERSE!"}
        }
    }
    with open(work_dir / "program.json", "w", encoding="utf-8") as f:
        json.dump(prog_data, f)
    with open(work_dir / "edits.json", "w", encoding="utf-8") as f:
        json.dump(edits_data, f)

    cues = build_project_subtitles(str(tmp_path))
    assert len(cues) == 2
    assert cues[0]["text"] == "HELLO UNIVERSE!"
    assert cues[1]["text"] == "NEXT LINE"

    sub_json_path = work_dir / "subtitles.json"
    sub_srt_path = work_dir / "subtitles.srt"
    assert sub_json_path.exists()
    assert sub_srt_path.exists()

    with open(sub_srt_path, "r", encoding="utf-8") as f:
        srt_content = f.read()
    assert "HELLO UNIVERSE!" in srt_content
    assert "NEXT LINE" in srt_content
