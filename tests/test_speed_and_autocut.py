import json
import numpy as np
import pytest

from scripts.cuts import clamp_speed, apply_speed_ranges_to_pieces
from scripts.build import atempo_chain, stretch_audio_piece
from scripts.auto_cut import generate_edl_from_transcripts


def test_clamp_speed():
    assert clamp_speed(0.1) == 0.25
    assert clamp_speed(1.5) == 1.5
    assert clamp_speed(10.0) == 4.0


def test_apply_speed_ranges_scales_frames_and_words():
    fps = 30
    # One 10-second piece (300 frames, 0..300)
    pieces = [{"clip": "a", "a": 0, "b": 300, "p": 0, "e": 0, "speed": 1.0, "pf_len": 300}]
    words = [
        [1.0, 2.0, "hello", 0],
        [4.0, 6.0, "fast", 0],
        [8.0, 9.0, "end", 0],
    ]
    # Speed up 2.0s..6.0s by 2.0x (4s of source becomes 2s in program -> total duration 8s = 240 frames)
    speed_ranges = [{"id": "s1", "start": 2.0, "end": 6.0, "speed": 2.0}]
    new_pieces, new_words, total_pf = apply_speed_ranges_to_pieces(pieces, words, speed_ranges, fps)
    assert total_pf == 240
    assert len(new_pieces) == 3
    assert [p["speed"] for p in new_pieces] == [1.0, 2.0, 1.0]
    # "hello" at 1.0..2.0 stays 1.0..2.0
    assert new_words[0][0] == 1.0 and new_words[0][1] == 2.0
    # "fast" was at 4.0..6.0 (2s into the 2x segment starting at 2.0s) -> 3.0..4.0 in new timeline
    assert abs(new_words[1][0] - 3.0) < 0.05
    assert abs(new_words[1][1] - 4.0) < 0.05
    # "end" was at 8.0..9.0 -> shifted earlier by 2.0s -> 6.0..7.0
    assert abs(new_words[2][0] - 6.0) < 0.05


def test_atempo_chain_handles_extreme_speeds():
    assert atempo_chain(1.0) == ""
    assert atempo_chain(1.25) == "atempo=1.2500"
    chain_slow = atempo_chain(0.25)
    assert "atempo=0.5" in chain_slow
    chain_fast = atempo_chain(3.0)
    assert "atempo=2.0" in chain_fast and "1.5" in chain_fast


def test_stretch_audio_piece_matches_target_length():
    sr = 48000
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    tone = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 440 * t)], axis=1)
    target_len = sr // 2  # 2.0x speed -> 0.5s
    out = stretch_audio_piece(tone, 2.0, target_len, sr=sr)
    assert out.shape == (target_len, 2)
    assert out.dtype == np.float32


def test_stretch_audio_piece_unity_speed():
    sr = 48000
    t = np.linspace(0, 0.5, sr // 2, endpoint=False, dtype=np.float32)
    tone = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 440 * t)], axis=1)
    out = stretch_audio_piece(tone, 1.0, sr // 2, sr=sr)
    assert out.shape == (sr // 2, 2)
    assert np.allclose(out, tone)


def test_generate_edl_from_transcripts(tmp_path):
    work = tmp_path / "work" / "transcripts"
    work.mkdir(parents=True)
    (tmp_path / "work" / "clips.json").write_text(json.dumps({"clip1": "src/clip1.mp4"}))
    (work / "clip1.json").write_text(json.dumps({
        "clip": "clip1",
        "src": "src/clip1.mp4",
        "threshold": -45.0,
        "hop": 0.01,
        "regions": [[0.5, 2.5]],
        "utterances": [{"start": 0.5, "end": 2.5, "text": "Hello Reels world", "words": [[0.5, 1.0, "Hello"], [1.1, 1.6, "Reels"], [1.7, 2.5, "world"]]}]
    }))
    edl = generate_edl_from_transcripts(str(tmp_path), pace="tight", fps=30)
    assert edl["pace"] == "tight"
    assert len(edl["items"]) == 1
    assert edl["items"][0]["clip"] == "clip1"
    # verify edl.json written to disk
    assert (tmp_path / "work" / "edl.json").exists()


def test_cuts_build_with_speed_and_edits(tmp_path):
    from scripts.cuts import build
    work = tmp_path / "work"
    (work / "transcripts").mkdir(parents=True)
    (work / "env").mkdir(parents=True)
    
    # Create minimal transcript and env
    (work / "transcripts" / "clip1.json").write_text(json.dumps({
        "clip": "clip1",
        "src": "src/clip1.mp4",
        "threshold": -45.0,
        "regions": [],
        "utterances": []
    }))
    env_data = np.full(100, -70.0, dtype=np.float32)
    np.save(work / "env" / "clip1.npy", env_data)
    
    # 4-second range at 2.0x -> 2.0s = 60 frames
    (work / "edl.json").write_text(json.dumps({
        "fps": 30,
        "pace": "tight",
        "clips": {"clip1": "src/clip1.mp4"},
        "items": [{"clip": "clip1", "range": [0.0, 4.0], "speed": 2.0}]
    }))
    # edits.json speeds up the first 1.0s (in initial program timeline) to 4.0x
    (work / "edits.json").write_text(json.dumps({
        "speed_ranges": [{"id": "sr1", "start": 0.0, "end": 1.0, "speed": 4.0}]
    }))

    build(str(tmp_path))

    prog_path = work / "program.json"
    assert prog_path.exists()
    prog = json.loads(prog_path.read_text())
    assert len(prog["pieces"]) == 2
    # subpiece 1: speed 4.0
    assert prog["pieces"][0]["speed"] == 4.0
    # subpiece 2: speed 2.0
    assert prog["pieces"][1]["speed"] == 2.0
    # total frames:
    # subpiece 1 had 60 source frames / 4.0 = 15 frames
    # subpiece 2 had 60 source frames / 2.0 = 30 frames
    # total = 45 frames
    assert prog["frames"] == 45
    assert prog["pieces"][0]["pf_len"] == 15
    assert prog["pieces"][1]["pf_len"] == 30

