import io
import json
import threading
import urllib.request
import urllib.error
import numpy as np
import pytest
from scripts.mix import mix_audio_buffers
from scripts.serve import sanitize_asset_filename, create_server, default_edits
from scripts._common import write_wav


def test_sanitize_asset_filename_blocks_traversal_and_bad_ext():
    assert sanitize_asset_filename("../../my_photo.PNG") == "my_photo.PNG"
    assert sanitize_asset_filename("sound effect.mp3") == "sound_effect.mp3"
    with pytest.raises(ValueError):
        sanitize_asset_filename("malicious.exe")


def test_mix_audio_buffers_mixes_custom_audio_and_truncates_overflow(tmp_path):
    sr = 48000
    # 1 second of voice
    voice = np.zeros((sr, 2), dtype=np.float64)
    # 2 seconds of custom audio (will overflow 1s voice if not truncated)
    t = np.linspace(0, 2.0, sr * 2, endpoint=False, dtype=np.float32)
    custom_wav = tmp_path / "assets" / "custom.wav"
    custom_wav.parent.mkdir(parents=True)
    tone = np.stack([0.2 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1)
    write_wav(str(custom_wav), tone, sr=sr)

    audio_clips = [
        {"id": "a1", "type": "mp3", "name": "custom.wav", "src": "assets/custom.wav", "start": 0.5, "end": 2.5, "trim_start": 0.0, "gain_db": 0.0},
        {"id": "a2", "type": "sfx", "name": "pop", "start": 0.1, "gain_db": -6.0},
    ]
    mixed = mix_audio_buffers(voice, [], audio_clips, str(tmp_path))
    assert mixed.shape == (sr, 2)
    assert np.abs(mixed[int(0.6 * sr):int(0.9 * sr)]).max() > 0.05


def test_serve_api_edits_and_assets_upload(tmp_path):
    srv = create_server(str(tmp_path), port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # 1. GET /api/edits returns default schema
        with urllib.request.urlopen(f"{base}/api/edits") as r:
            edits = json.loads(r.read().decode())
            assert edits["aspect"] == "9:16"
            assert edits["subtitles"]["enabled"] is True

        # 2. POST /api/edits persists modifications
        edits["subtitles"]["y"] = 0.65
        req = urllib.request.Request(
            f"{base}/api/edits",
            data=json.dumps(edits).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read().decode())
            assert resp["ok"] is True
        assert json.loads((tmp_path / "work" / "edits.json").read_text())["subtitles"]["y"] == 0.65

        # 3. POST /api/assets uploads a PNG and rejects .exe
        png_bytes = b"\x89PNG\r\n\x1a\nfake"
        req_up = urllib.request.Request(
            f"{base}/api/assets",
            data=png_bytes,
            headers={"X-Filename": "../overlay.png", "Content-Type": "application/octet-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req_up) as r:
            up_resp = json.loads(r.read().decode())
            assert up_resp["ok"] is True
            assert up_resp["asset"]["name"] == "overlay.png"
            assert up_resp["asset"]["type"] == "image"
        assert (tmp_path / "assets" / "overlay.png").read_bytes() == png_bytes

        req_bad = urllib.request.Request(
            f"{base}/api/assets",
            data=b"bad",
            headers={"X-Filename": "hack.exe"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_bad)
        assert exc_info.value.code == 400
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_api_subtitles_and_assets_list(tmp_path):
    # Set up program.json with words
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True)
    program_data = {
        "words": [
            [0.1, 0.4, "Hello"],
            [0.5, 0.9, "world"],
            [1.0, 1.4, "testing"],
        ]
    }
    (work_dir / "program.json").write_text(json.dumps(program_data), encoding="utf-8")

    # Set up edits.json with subtitles config
    edits = default_edits()
    edits["subtitles"]["uppercase"] = True
    edits["subtitles"]["overrides"] = {"sub_0": "HELLO UNIVERSE"}
    (work_dir / "edits.json").write_text(json.dumps(edits), encoding="utf-8")

    # Put an audio asset in assets/
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "sample.mp3").write_bytes(b"dummy mp3")

    srv = create_server(str(tmp_path), port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"

        # Test GET /api/subtitles
        with urllib.request.urlopen(f"{base}/api/subtitles") as r:
            data = json.loads(r.read().decode())
            assert "cues" in data
            assert len(data["cues"]) == 1
            assert data["cues"][0]["text"] == "HELLO UNIVERSE"

        # Test GET /api/assets
        with urllib.request.urlopen(f"{base}/api/assets") as r:
            data = json.loads(r.read().decode())
            assert "assets" in data
            assert "sfx" in data
            assert "whoosh" in data["sfx"]
            assert any(a["name"] == "sample.mp3" and a["type"] == "audio" for a in data["assets"])
    finally:
        srv.shutdown()
        srv.server_close()


def test_mix_audio_buffers_sfx_and_ceiling():
    sr = 48000
    voice = np.zeros((sr, 2), dtype=np.float64)
    # Add a loud SFX cue and audio_clips sfx
    sfx_cues = [{"name": "pop", "t": 0.05, "gain": 0.0}]
    audio_clips = [{"id": "s1", "type": "sfx", "name": "chime", "start": 0.2, "gain_db": 0.0}]
    mixed = mix_audio_buffers(voice, sfx_cues, audio_clips, root=".", sfx_gain=0.0, ceiling=-3.0)
    assert mixed.shape == (sr, 2)
    # Ceiling is -3 dBFS, max allowed amplitude is 10 ** (-3 / 20) ~ 0.7079
    max_amp = float(np.max(np.abs(mixed)))
    assert max_amp <= 10.0 ** (-3.0 / 20.0) + 1e-5


def test_serve_range_request_partial_content(tmp_path):
    test_file = tmp_path / "test.bin"
    test_data = b"0123456789abcdefghijklmnopqrstuvwxyz"
    test_file.write_bytes(test_data)

    srv = create_server(str(tmp_path), port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        req = urllib.request.Request(f"{base}/test.bin", headers={"Range": "bytes=4-9"})
        with urllib.request.urlopen(req) as r:
            assert r.status == 206
            assert r.headers.get("Content-Range") == f"bytes 4-9/{len(test_data)}"
            body = r.read()
            assert body == test_data[4:10]
    finally:
        srv.shutdown()
        srv.server_close()
