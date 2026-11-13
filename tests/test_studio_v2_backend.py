import json
import os
import threading
import urllib.request
import urllib.error
import pytest

from scripts.cuts import apply_deleted_ranges_to_pieces
from scripts.serve import (
    ALLOWED_SOURCE_EXTENSIONS,
    create_server,
    default_edits,
    sanitize_source_filename,
)


def test_apply_deleted_ranges_to_pieces_splits_and_shifts():
    fps = 30
    # 4.0s piece (120 frames, 0..120)
    pieces = [{"clip": "c1", "a": 0, "b": 120, "p": 0, "pf_len": 120, "e": 0, "speed": 1.0}]
    words = [
        [0.2, 0.8, "intro", 0],
        [1.2, 1.8, "remove", 0],
        [2.5, 3.0, "keep", 0],
    ]
    # Delete 1.0s..2.0s
    deleted_ranges = [{"id": "del-1", "start": 1.0, "end": 2.0}]
    chapters = [
        {"title": "Intro", "frame": 0, "time": 0.0},
        {"title": "Part 2", "frame": 90, "time": 3.0},
    ]

    new_pieces, new_words, total_pf = apply_deleted_ranges_to_pieces(
        pieces, words, deleted_ranges, fps, chapters=chapters
    )

    # 1. Total frames = 90 frames (3.0s)
    assert total_pf == 90
    assert len(new_pieces) == 2

    # 2. First piece: [0..30] at p=0
    assert new_pieces[0]["a"] == 0
    assert new_pieces[0]["b"] == 30
    assert new_pieces[0]["p"] == 0
    assert new_pieces[0]["pf_len"] == 30

    # 3. Second piece: [60..120] at p=30
    assert new_pieces[1]["a"] == 60
    assert new_pieces[1]["b"] == 120
    assert new_pieces[1]["p"] == 30
    assert new_pieces[1]["pf_len"] == 60

    # 4. Words inside deleted range removed, word after shifted left by 1.0s
    assert len(new_words) == 2
    assert new_words[0] == [0.2, 0.8, "intro", 0]
    assert new_words[1] == [1.5, 2.0, "keep", 0]

    # 5. Chapter after deleted range shifted left by 1.0s to time=2.0, frame=60
    assert chapters[0]["time"] == 0.0 and chapters[0]["frame"] == 0
    assert chapters[1]["time"] == 2.0 and chapters[1]["frame"] == 60


def test_apply_deleted_ranges_overlapping_and_empty():
    fps = 30
    pieces = [
        {"clip": "c1", "a": 0, "b": 60, "p": 0, "pf_len": 60, "e": 0},
        {"clip": "c1", "a": 60, "b": 120, "p": 60, "pf_len": 60, "e": 1},
    ]
    words = [
        [0.5, 0.9, "stay", 0],
        [1.2, 1.4, "drop1", 0],
        [1.6, 1.8, "drop2", 1],
        [3.0, 3.5, "after", 1],
    ]
    # Overlapping deleted ranges [1.0, 1.5] and [1.3, 2.0] -> merges to [1.0, 2.0]
    # Plus empty range [2.5, 2.5]
    deleted_ranges = [
        {"id": "d1", "start": 1.0, "end": 1.5},
        {"id": "d2", "start": 1.3, "end": 2.0},
        {"id": "d3", "start": 2.5, "end": 2.5},
    ]
    new_pieces, new_words, total_pf = apply_deleted_ranges_to_pieces(
        pieces, words, deleted_ranges, fps
    )
    assert total_pf == 90
    assert len(new_words) == 2
    assert new_words[0][2] == "stay"
    assert new_words[1][2] == "after"
    assert new_words[1][0] == 2.0
    assert new_words[1][1] == 2.5


def test_default_edits_schema():
    edits = default_edits()
    assert "deleted_ranges" in edits
    assert isinstance(edits["deleted_ranges"], list)
    assert edits["deleted_ranges"] == []


def test_sanitize_source_filename():
    assert ALLOWED_SOURCE_EXTENSIONS == {".mp4", ".mov", ".webm", ".mkv"}
    assert sanitize_source_filename("raw clip.mp4") == "raw_clip.mp4"
    assert sanitize_source_filename("../../camera-01.MOV") == "camera-01.MOV"
    assert sanitize_source_filename("shot #2 (test).webm") == "shot__2__test_.webm"
    assert sanitize_source_filename("scene.mkv") == "scene.mkv"

    # Rejection of bad extensions or malicious inputs
    with pytest.raises(ValueError):
        sanitize_source_filename("malicious.exe")
    with pytest.raises(ValueError):
        sanitize_source_filename("photo.png")
    with pytest.raises(ValueError):
        sanitize_source_filename(".hidden.mp4")
    with pytest.raises(ValueError):
        sanitize_source_filename("")
    with pytest.raises(ValueError):
        sanitize_source_filename("///")


def test_api_project_status(tmp_path):
    srv = create_server(str(tmp_path), port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # Initially empty project
        with urllib.request.urlopen(f"{base}/api/project-status") as r:
            status = json.loads(r.read().decode())
            assert status["ok"] is True
            assert status["has_program"] is False
            assert status["has_proxy"] is False
            assert status["has_final"] is False
            assert status["src_files"] == []

        # Populate files
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "b_clip.mov").write_bytes(b"mov")
        (src_dir / "a_clip.mp4").write_bytes(b"mp4")
        (src_dir / "ignored.txt").write_bytes(b"txt")
        (src_dir / ".hidden.mp4").write_bytes(b"hidden")

        work_dir = tmp_path / "work"
        work_dir.mkdir(parents=True)
        (work_dir / "program.json").write_text("{}", encoding="utf-8")
        (work_dir / "proxy.mp4").write_bytes(b"proxy")

        out_dir = tmp_path / "out"
        out_dir.mkdir(parents=True)
        (out_dir / "FINAL.mp4").write_bytes(b"final")

        with urllib.request.urlopen(f"{base}/api/project-status") as r:
            status = json.loads(r.read().decode())
            assert status["ok"] is True
            assert status["has_program"] is True
            assert status["has_proxy"] is True
            assert status["has_final"] is True
            assert status["src_files"] == ["a_clip.mp4", "b_clip.mov"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_source_video_upload(tmp_path):
    srv = create_server(str(tmp_path), port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        video_bytes = b"\x00\x00\x00 ftypmp42fakevideo"
        req = urllib.request.Request(
            f"{base}/api/source-video",
            data=video_bytes,
            headers={"X-Filename": "raw clip.mp4", "Content-Type": "application/octet-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read().decode())
            assert resp["ok"] is True
            assert resp["file"] == "raw_clip.mp4"

        saved_file = tmp_path / "src" / "raw_clip.mp4"
        assert saved_file.exists()
        assert saved_file.read_bytes() == video_bytes

        # Bad extension rejected
        req_bad = urllib.request.Request(
            f"{base}/api/source-video",
            data=b"exe content",
            headers={"X-Filename": "malicious.exe"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_bad)
        assert exc_info.value.code == 400
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_init_project(tmp_path, monkeypatch):
    recorded_commands = []

    def mock_run(cmd, *args, **kwargs):
        recorded_commands.append(cmd)
        return True

    monkeypatch.setattr("subprocess.run", mock_run)

    srv = create_server(str(tmp_path), port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # 1. No src files -> 400
        req_empty = urllib.request.Request(f"{base}/api/init-project", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_empty)
        assert exc_info.value.code == 400

        # 2. Add src files
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "clip1.mp4").write_bytes(b"v1")
        (src_dir / "clip2.mov").write_bytes(b"v2")

        req_init = urllib.request.Request(f"{base}/api/init-project", data=b"{}", method="POST")
        with urllib.request.urlopen(req_init) as r:
            resp = json.loads(r.read().decode())
            assert resp["ok"] is True
            assert resp["clips"] == ["clip1", "clip2"]

        # Verify transcribe called on each clip, auto_cut on first clip, cuts, build
        cmd_strs = [" ".join(str(x) for x in c) for c in recorded_commands]
        assert any("transcribe.py" in s and "clip1.mp4" in s for s in cmd_strs)
        assert any("transcribe.py" in s and "clip2.mov" in s for s in cmd_strs)
        assert any("auto_cut.py" in s and "--clip clip1" in s for s in cmd_strs)
        assert any("cuts.py" in s for s in cmd_strs)
        assert any("build.py" in s for s in cmd_strs)
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_export(tmp_path, monkeypatch):
    recorded_commands = []

    def mock_run(cmd, *args, **kwargs):
        recorded_commands.append(cmd)
        return True

    monkeypatch.setattr("subprocess.run", mock_run)

    srv = create_server(str(tmp_path), port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        req_export = urllib.request.Request(f"{base}/api/export", data=b"{}", method="POST")
        with urllib.request.urlopen(req_export) as r:
            resp = json.loads(r.read().decode())
            assert resp["ok"] is True
            assert resp["download_url"] == "../out/FINAL.mp4"

        cmd_strs = [" ".join(str(x) for x in c) for c in recorded_commands]
        assert any("render.mjs" in s and f"http://127.0.0.1:{port}/scene/" in s for s in cmd_strs)
        assert any("mix.py" in s for s in cmd_strs)
    finally:
        srv.shutdown()
        srv.server_close()


def test_cuts_build_with_deleted_ranges(tmp_path):
    import numpy as np
    from scripts.cuts import build

    work = tmp_path / "work"
    (work / "transcripts").mkdir(parents=True)
    (work / "env").mkdir(parents=True)

    (work / "transcripts" / "clip1.json").write_text(
        json.dumps({
            "clip": "clip1",
            "src": "src/clip1.mp4",
            "threshold": -45.0,
            "regions": [],
            "utterances": [],
        })
    )
    env_data = np.full(100, -70.0, dtype=np.float32)
    np.save(work / "env" / "clip1.npy", env_data)

    # 4-second piece at 30 fps = 120 frames
    (work / "edl.json").write_text(
        json.dumps({
            "fps": 30,
            "pace": "tight",
            "clips": {"clip1": "src/clip1.mp4"},
            "items": [{"clip": "clip1", "range": [0.0, 4.0], "speed": 1.0}],
        })
    )
    # Delete 1.0s to 2.0s (30 frames excised -> 90 frames left)
    (work / "edits.json").write_text(
        json.dumps({
            "deleted_ranges": [{"id": "del-1", "start": 1.0, "end": 2.0}],
            "speed_ranges": [],
        })
    )

    build(str(tmp_path))

    prog_path = work / "program.json"
    assert prog_path.exists()
    prog = json.loads(prog_path.read_text())
    assert prog["frames"] == 90
    assert len(prog["pieces"]) == 2
    assert prog["pieces"][0]["a"] == 0
    assert prog["pieces"][0]["b"] == 30
    assert prog["pieces"][0]["p"] == 0
    assert prog["pieces"][0]["pf_len"] == 30
    assert prog["pieces"][1]["a"] == 60
    assert prog["pieces"][1]["b"] == 120
    assert prog["pieces"][1]["p"] == 30
    assert prog["pieces"][1]["pf_len"] == 60
    assert prog["entries"][0]["pieces"] == [0, 1]

