# Antigravity Video Editor (`videoeditorbyhirtzirt`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Antigravity Reels/TikTok & Shorts video editing system on top of the `YildizDikme/claude-video-edit` backbone with free `faster-whisper` transcription, `auto-editor` silence cutting, 3-word dynamic subtitles, segment-based video speed control, custom `.mp3/.mp4/.png/.jpeg` media support, and a Canva/CapCut-style browser scene editor with 20-step Undo/Redo.

**Architecture:** Python backend scripts (`scripts/transcribe.py`, `scripts/auto_cut.py`, `scripts/cuts.py`, `scripts/build.py`, `scripts/subtitles.py`, `scripts/mix.py`, `scripts/serve.py`) process media and expose a local REST + Range HTTP server. The browser scene (`template/index.html`, `template/engine.js`, `template/editor.js`, `template/editor.css`) renders the video, 3-word subtitles, and custom media overlays on a normalized `0..1` stage in both interactive Canva/CapCut edit mode and headless Chrome frame-exact render mode (`?still` via `scripts/render.mjs`). Shared state lives in `work/program.json` and `work/edits.json`.

**Tech Stack:** Python 3.10+, `numpy`, `faster-whisper`, `auto-editor`, `ffmpeg`/`ffprobe`, Vanilla JS + GSAP 3.12, HTML5/CSS3, Node.js 20+ (headless Chrome CDP via `scripts/render.mjs`), `pytest`.

**Spec:** `docs/superpowers/specs/2026-11-13-videoeditor-design.md`

## Global Constraints

- Free local transcription only (`faster-whisper` / `whisperkit-cli`); never require paid ElevenLabs API keys.
- Subtitles must display in phrase-aware chunks of at most 3 words (`MAX_WORDS = 3`, `PAUSE_BREAK_SEC = 0.35`, `PUNCT_BREAK = set(".,!?;:")`), swapping cleanly chunk-by-chunk without karaoke per-word color changes.
- Segment speed multipliers (`speed`) are clamped to `[0.25, 4.0]`; audio time-stretching uses FFmpeg `atempo` chains to preserve voice pitch.
- Uploaded media extensions allowed in `/api/assets`: `.mp3`, `.wav`, `.mp4`, `.webm`, `.png`, `.jpg`, `.jpeg`, `.webp`. Filenames must be sanitized against path traversal.
- In `?still` mode (used by `scripts/render.mjs`), all editor UI chrome (`#editor-ui`, selection handles, toolbars) must be hidden (`display: none`) so only `#stage` is captured.
- Normalized coordinates (`x`, `y`, `width`, `height`) in `work/edits.json` are floats in `[0.0, 1.0]` relative to stage dimensions (`1080x1920` for `9:16` or `1920x1080` for `16:9`).

## Review Focus

- Empty or punctuation-only words in `program.json` must not produce empty 3-word subtitle cues or crash `chunk_three_words`.
- Speed multipliers outside `[0.5, 2.0]` (such as `0.25` or `3.0`) require chained FFmpeg `atempo` filters because a single `atempo` filter only accepts `[0.5, 100.0]` (and `< 0.5` requires chaining `atempo=0.5,atempo=...`).
- Path traversal in `POST /api/assets` via `X-Filename: ../../evil.png` must be stripped to its safe basename (`evil.png`) and rejected if the extension is not in the allowlist.
- Custom `.mp3` clips in `mix.py` that extend past the end of the program voice track must be truncated to the program length rather than raising a NumPy broadcast `ValueError`.
- Opening the scene with `?still` must still load and apply `work/edits.json` (subtitle position, custom overlays, text overrides) while hiding the interactive editor controls.

---

### Task 1: 3-Word Dynamic Subtitle Chunker & SRT Generator

**Files:**
- Create: `scripts/subtitles.py`
- Test: `tests/test_subtitles.py`

**Interfaces:**
- Consumes: `work/program.json` (`words`: list of `[start, end, word, ...]` items) and optional `work/edits.json` (`subtitles.overrides`: dict mapping cue id `"sub_0"` to replacement text, `subtitles.uppercase`: bool).
- Produces:
  - `chunk_three_words(words: list, max_words: int = 3, pause_break: float = 0.35, overrides: dict | None = None, uppercase: bool = False) -> list[dict]` returning `[{"id": "sub_0", "start": float, "end": float, "text": str, "words": list}, ...]`
  - `format_srt(cues: list[dict]) -> str`
  - `build_project_subtitles(project: str) -> list[dict]` (writes `work/subtitles.json` and `work/subtitles.srt`)

- [ ] **Step 1: Write the failing test in `tests/test_subtitles.py`**

```python
from scripts.subtitles import chunk_three_words, format_srt


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_subtitles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.subtitles'`

- [ ] **Step 3: Implement `scripts/subtitles.py`**

Implement `chunk_three_words`, `format_srt`, `build_project_subtitles(project)`, and a CLI `main()` accepting `--project .`. Ignore whitespace-only words. Ensure `out_end > out_start` (minimum `0.2s` duration fallback).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_subtitles.py -v`
Expected: PASS (4/4 passing)

- [ ] **Step 5: Commit**

```bash
git add scripts/subtitles.py tests/test_subtitles.py
git commit -m "feat(subtitles): add 3-word dynamic subtitle chunker and SRT builder"
```

---

### Task 2: Segment Speed Control & `auto-editor` Integration

**Files:**
- Modify: `scripts/cuts.py`
- Modify: `scripts/build.py`
- Create: `scripts/auto_cut.py`
- Test: `tests/test_speed_and_autocut.py`

**Interfaces:**
- Consumes: `work/edl.json`, optional `work/edits.json` (`speed_ranges`: `[{"id": str, "start": float, "end": float, "speed": float}]`).
- Produces:
  - In `scripts/cuts.py`:
    - `clamp_speed(val: float) -> float` (clamps to `[0.25, 4.0]`).
    - `apply_speed_ranges_to_pieces(pieces: list[dict], words: list[list], speed_ranges: list[dict], fps: int) -> tuple[list[dict], list[list], int]` which splits/tags pieces overlapping program `speed_ranges` (`[{"start": float, "end": float, "speed": float}]`), recalculates each piece's program start frame `p`, program frame length `pf_len = max(1, int(round((b - a) / speed)))`, rescales word timestamps `[start, end, word, entry_idx]`, and returns `(updated_pieces, updated_words, total_pf)`.
    - Also supports per-item `"speed"` in `edl.json`.
  - In `scripts/build.py`:
    - `atempo_chain(speed: float) -> str` returning comma-separated `atempo=...` filters where each factor is in `[0.5, 2.0]` (e.g., `0.25` -> `"atempo=0.5,atempo=0.5"`, `3.0` -> `"atempo=2.0,atempo=1.5"`).
    - `stretch_audio_piece(samples: np.ndarray, speed: float, target_len: int, sr: int = 48000) -> np.ndarray` using `ffmpeg` + `atempo_chain(speed)` when `abs(speed - 1.0) > 1e-3`, padded or trimmed to `target_len`.
    - `build_video` respects `p.get("speed", 1.0)` and `p.get("pf_len", p["b"] - p["a"])` using `setpts=(PTS-STARTPTS)/{speed}` in `-vf`.
  - In `scripts/auto_cut.py`:
    - `generate_edl_from_transcripts(project: str, pace: str = "tight", fps: int = 30) -> dict` which builds `work/edl.json` from all transcripts in `work/transcripts/*.json` (and optionally refines silence regions via `auto-editor` CLI if installed and `--use-auto-editor` is passed).

- [ ] **Step 1: Write the failing tests in `tests/test_speed_and_autocut.py`**

```python
import numpy as np
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


def test_generate_edl_from_transcripts(tmp_path):
    work = tmp_path / "work" / "transcripts"
    work.mkdir(parents=True)
    import json
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_speed_and_autocut.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement speed functions in `scripts/cuts.py`, `scripts/build.py`, and create `scripts/auto_cut.py`**

1. In `scripts/cuts.py`: add `clamp_speed` and `apply_speed_ranges_to_pieces`. In `build(project)`, read item `"speed"` (default `1.0`) and also check if `work/edits.json` has `speed_ranges`; apply them and store `"speed"` and `"pf_len"` on each piece in `work/program.json`.
2. In `scripts/build.py`: add `atempo_chain` and `stretch_audio_piece`. Update `build_audio` to stretch pieces when `p.get('speed', 1.0) != 1.0` to `sample(p.get('pf_len', p['b'] - p['a']), fps)` samples. Update `build_video` to apply `setpts=(PTS-STARTPTS)/{speed}` and `-frames:v {pf_len}` when `speed != 1.0`.
3. Create `scripts/auto_cut.py` with `generate_edl_from_transcripts(project, pace="tight", fps=30)` and CLI support.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_speed_and_autocut.py -v`
Expected: PASS (5/5 passing)

- [ ] **Step 5: Commit**

```bash
git add scripts/cuts.py scripts/build.py scripts/auto_cut.py tests/test_speed_and_autocut.py
git commit -m "feat(speed,autocut): add segment speed stretching and auto-cut EDL generator"
```

---

### Task 3: Custom `.mp3`/`.wav` Audio Mixer & Studio API Server

**Files:**
- Modify: `scripts/mix.py`
- Modify: `scripts/serve.py`
- Test: `tests/test_serve_and_mix.py`

**Interfaces:**
- Consumes: `work/edits.json` (`audio_clips`: list of `{"id": str, "type": "sfx"|"mp3", "name": str, "src": str|None, "start": float, "end": float|None, "trim_start": float, "gain_db": float}`), `out/frames/sfx.json`.
- Produces:
  - In `scripts/mix.py`:
    - `mix_audio_buffers(voice: np.ndarray, sfx_cues: list[dict], audio_clips: list[dict], root: str, sfx_gain: float = 0.0, ceiling: float = -1.0) -> np.ndarray` which mixes synthesized SFX (`sfx.py`) and decoded user audio files (`.mp3`/`.wav` via `decode()`), truncating safely if a clip extends past `len(voice)`.
  - In `scripts/serve.py`:
    - `default_edits() -> dict` returning the default `work/edits.json` schema.
    - `sanitize_asset_filename(filename: str) -> str` (strips directory components; raises `ValueError` if extension not in `{'.mp3', '.wav', '.mp4', '.webm', '.png', '.jpg', '.jpeg', '.webp'}`).
    - `RangeHandler` supporting:
      - `GET /api/edits` -> returns `work/edits.json` (or `default_edits()`).
      - `POST /api/edits` -> validates and saves JSON body to `work/edits.json`, returns `{"ok": True}`.
      - `GET /api/assets` -> returns `{"assets": [{"name": str, "url": str, "type": "image"|"video"|"audio"}, ...], "sfx": ["whoosh", "soft-whoosh", "tick", "click", "key", "typing", "pop", "chime"]}`.
      - `POST /api/assets` -> reads header `X-Filename` and raw request body, saves into `<project>/assets/<safe_name>`, returns `{"ok": True, "asset": {"name": safe_name, "url": f"../assets/{safe_name}", "type": media_type}}`.
      - `GET /api/subtitles` -> reads `work/program.json` and `work/edits.json`, returns `{"cues": chunk_three_words(...)}`.

- [ ] **Step 1: Write the failing tests in `tests/test_serve_and_mix.py`**

```python
import io
import json
import threading
import urllib.request
import urllib.error
import numpy as np
import pytest
from scripts.mix import mix_audio_buffers
from scripts.serve import sanitize_asset_filename, create_server
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_serve_and_mix.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `mix_audio_buffers` in `scripts/mix.py` and API endpoints in `scripts/serve.py`**

1. In `scripts/mix.py`: extract `mix_audio_buffers(voice, sfx_cues, audio_clips, root, sfx_gain=0.0, ceiling=-1.0)` and update `main()` to load `work/edits.json` `audio_clips` alongside `sfx.json`.
2. In `scripts/serve.py`: implement `default_edits()`, `sanitize_asset_filename()`, `create_server(project, port=5600)` (using a per-server `project_root` attribute rather than relying only on global `os.chdir` so tests and concurrent requests are safe), and handle `GET/POST /api/edits`, `GET/POST /api/assets`, and `GET /api/subtitles`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_serve_and_mix.py -v`
Expected: PASS (3/3 passing)

- [ ] **Step 5: Commit**

```bash
git add scripts/mix.py scripts/serve.py tests/test_serve_and_mix.py
git commit -m "feat(server,mix): add studio REST API for edits/assets and custom audio track mixer"
```

---

### Task 4: Canva/CapCut Interactive Scene Engine, 3-Word Subtitles & Layer/Undo Editor

**Files:**
- Modify: `template/index.html`
- Modify: `template/style.css`
- Modify: `template/engine.js`
- Create: `template/editor.js`
- Create: `template/editor.css`
- Test: `tests/test_scene_editor.py`

**Interfaces:**
- Consumes: `/api/edits` (`work/edits.json`), `/api/assets`, `work/program.json`.
- Produces:
  - In `template/engine.js`:
    - `window.chunkThreeWords(words, overrides, uppercase)` — browser-side 3-word subtitle chunker matching `scripts/subtitles.py` rules (`max_words=3`, `pause_break=0.35`, `.,!?;:`).
    - Renders `#subtitles-box` inside `#stage` positioned at `(edits.subtitles.x * W, edits.subtitles.y * H)`, showing only the active 3-word chunk for the current `clock` time `t`.
    - Renders `#overlays-layer` inside `#stage` containing every item in `edits.media_overlays` (`image` `<img>` or `video` `<video>`) active at `[ov.start, ov.end]` positioned at normalized `(ov.x * W, ov.y * H, ov.width * W, ov.height * H)`. In `render(t)` (`?still` mode), seeks any active overlay `<video>` to `t - ov.start + (ov.trim_start || 0)`.
    - Applies `edits.speed_ranges` to `video.playbackRate` during live preview playback.
    - Exposes `window.__scene.applyEdits(edits)` and `window.__scene.getEdits()` so `editor.js` and `render.mjs` share the exact same rendering pipeline.
  - In `template/editor.js` & `template/editor.css`:
    - Automatically bypassed when `location.search` includes `?still` (`document.body.classList.add('still-mode')`).
    - Provides `window.__editor` with:
      - `pushHistory(nextEdits)`, `undo()`, `redo()` (20-step Undo/Redo stack modeled after `banana-studio`).
      - Interactive drag & resize pointer handlers on `#stage` for `#subtitles-box` and `.media-overlay-item` updating normalized `[0..1]` coordinates (`x`, `y`, `width`, `height`).
      - Left Sidebar Asset Tray: upload `.mp3`, `.mp4`, `.png`, `.jpg`, `.jpeg` via `POST /api/assets`, add image/video overlays, or trigger SFX/MP3 audio clips.
      - Right/Bottom Inspector & Timeline: toggle `9:16` (1080×1920) vs `16:9` (1920×1080), customize subtitle font size/color/background/uppercase, edit individual 3-word subtitle chunks, add/edit/remove `speed_ranges` (`start`, `end`, `speed`), and Save (`POST /api/edits`).

- [ ] **Step 1: Write the failing test in `tests/test_scene_editor.py`**

```python
from pathlib import Path
import subprocess
import json


def test_scene_files_and_js_chunker_and_undo_logic():
    root = Path(__file__).resolve().parent.parent
    assert (root / "template" / "editor.js").exists()
    assert (root / "template" / "editor.css").exists()
    html = (root / "template" / "index.html").read_text(encoding="utf-8")
    assert 'id="subtitles-box"' in html
    assert 'id="overlays-layer"' in html
    assert 'editor.js' in html

    # Run node verification of chunkThreeWords and HistoryManager exported on globalThis
    node_script = """
    const fs = require('fs');
    const code = fs.readFileSync('template/editor.js', 'utf8');
    // Execute in minimal mock environment
    globalThis.window = globalThis;
    globalThis.document = {
      body: { classList: { add(){}, toggle(){} }, dataset: { w: '1080', h: '1920' } },
      querySelector: () => null,
      querySelectorAll: () => [],
      createElement: () => ({ style: {}, classList: { add(){} }, appendChild(){} }),
      addEventListener: () => {}
    };
    globalThis.location = { search: '?still' };
    eval(code);

    const words = [
      [0.0, 0.2, 'One'], [0.25, 0.45, 'two'], [0.5, 0.7, 'three'],
      [0.75, 0.95, 'four']
    ];
    const cues = window.chunkThreeWords(words, {}, false);
    if (cues.length !== 2 || cues[0].text !== 'One two three' || cues[1].text !== 'four') {
      throw new Error('chunkThreeWords failed: ' + JSON.stringify(cues));
    }

    const hist = window.createHistoryManager({ a: 1 }, 20);
    hist.push({ a: 2 });
    hist.push({ a: 3 });
    const u1 = hist.undo();
    if (u1.a !== 2) throw new Error('undo failed');
    const r1 = hist.redo();
    if (r1.a !== 3) throw new Error('redo failed');
    console.log('JS_OK');
    """
    proc = subprocess.run(["node", "-e", node_script], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "JS_OK" in proc.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scene_editor.py -v`
Expected: FAIL because `template/editor.js` and `template/editor.css` do not exist yet.

- [ ] **Step 3: Implement `template/index.html`, `template/style.css`, `template/engine.js`, `template/editor.js`, and `template/editor.css`**

1. Update `template/index.html` to include `#overlays-layer`, `#subtitles-box`, `#editor-ui` container, `editor.css`, and `editor.js`.
2. Update `template/style.css` and create `template/editor.css` with styling for 3-word subtitle pills, overlay items with resize handles, dark Canva/CapCut studio layout, and `.still-mode #editor-ui { display: none !important; }`.
3. Create `template/editor.js` exporting `window.chunkThreeWords`, `window.createHistoryManager(initialState, maxSteps=20)`, and the interactive studio controller (drag/resize on stage, asset upload/insert, subtitle inspector, speed segment editor, audio/SFX timeline, `Ctrl+Z`/`Ctrl+Y` undo/redo, auto-save to `/api/edits`).
4. Update `template/engine.js` to fetch `../work/edits.json` (or `/api/edits`), render `#subtitles-box` and `#overlays-layer` on every `apply(t)` / `render(t)` call, and sync `SFX` cues from `edits.audio_clips`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scene_editor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add template/index.html template/style.css template/engine.js template/editor.js template/editor.css tests/test_scene_editor.py
git commit -m "feat(ui): add Canva/CapCut interactive scene editor, 3-word subtitles, and 20-step undo"
```

---

### Task 5: Antigravity Skill Definition, Project Sync & End-to-End Smoke Test

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `requirements.txt`
- Create: `tests/test_project_smoke.py`

**Interfaces:**
- Consumes: All modules from Tasks 1–4.
- Produces:
  - Updated `SKILL.md` and `README.md` documenting the Antigravity Reels/TikTok workflow, `auto_cut.py`, 3-word subtitles, segment speed control, custom `.mp3/.mp4/.png/.jpeg` assets, and the interactive browser editor.
  - Updated `requirements.txt` including `numpy`, `faster-whisper`, `auto-editor`, `pytest`.
  - End-to-end smoke test `tests/test_project_smoke.py` verifying: `generate_edl_from_transcripts` -> `cuts.py` (with `speed_ranges` in `edits.json`) -> `subtitles.py` (3-word chunks) -> `build.py` (audio + video with speed stretch) -> `mix.py` (voice + SFX + custom audio).

- [ ] **Step 1: Write the failing test in `tests/test_project_smoke.py`**

```python
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
from scripts._common import write_wav


def test_end_to_end_pipeline_with_speed_subtitles_and_custom_audio(tmp_path):
    root = Path(__file__).resolve().parent.parent
    src_dir = tmp_path / "src"
    work_dir = tmp_path / "work"
    assets_dir = tmp_path / "assets"
    src_dir.mkdir()
    (work_dir / "transcripts").mkdir(parents=True)
    (work_dir / "env").mkdir(parents=True)
    assets_dir.mkdir()

    # 1. Create a synthetic 2-second 30fps vertical 1080x1920 video clip with 440Hz tone
    clip_path = src_dir / "take1.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=360x640:r=30:d=2.0",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(clip_path)
    ], check=True)

    # 2. Write synthetic envelope and transcript
    env = np.full(200, -20.0, dtype=np.float32)
    np.save(str(work_dir / "env" / "take1.npy"), env)
    (work_dir / "clips.json").write_text(json.dumps({"take1": "src/take1.mp4"}))
    (work_dir / "transcripts" / "take1.json").write_text(json.dumps({
        "clip": "take1",
        "src": "src/take1.mp4",
        "threshold": -45.0,
        "hop": 0.01,
        "regions": [[0.1, 1.9]],
        "utterances": [{
            "start": 0.1,
            "end": 1.9,
            "text": "One two three four five",
            "words": [
                [0.1, 0.3, "One"], [0.35, 0.55, "two"], [0.6, 0.8, "three"],
                [0.9, 1.2, "four"], [1.3, 1.7, "five"]
            ]
        }]
    }))

    # 3. Write edits.json with a 1.5x speed range and a custom audio clip
    custom_fx = assets_dir / "beep.wav"
    sr = 48000
    t = np.linspace(0, 0.3, int(sr * 0.3), endpoint=False, dtype=np.float32)
    write_wav(str(custom_fx), np.stack([0.1 * np.sin(2 * np.pi * 880 * t)] * 2, axis=1), sr=sr)

    (work_dir / "edits.json").write_text(json.dumps({
        "version": 1,
        "aspect": "9:16",
        "stage": {"width": 1080, "height": 1920},
        "subtitles": {"enabled": True, "x": 0.5, "y": 0.78, "fontSize": 56, "uppercase": False, "overrides": {}},
        "speed_ranges": [{"id": "sp1", "start": 0.5, "end": 1.5, "speed": 1.5}],
        "media_overlays": [],
        "audio_clips": [{"id": "c1", "type": "mp3", "name": "beep.wav", "src": "assets/beep.wav", "start": 0.2, "end": 0.5, "trim_start": 0.0, "gain_db": 0.0}]
    }))

    # 4. Run auto_cut -> cuts -> subtitles -> build -> mix
    subprocess.run([sys.executable, str(root / "scripts" / "auto_cut.py"), "--project", str(tmp_path)], check=True)
    subprocess.run([sys.executable, str(root / "scripts" / "cuts.py"), "--project", str(tmp_path)], check=True)
    subprocess.run([sys.executable, str(root / "scripts" / "subtitles.py"), "--project", str(tmp_path)], check=True)
    subprocess.run([sys.executable, str(root / "scripts" / "build.py"), "--project", str(tmp_path), "audio", "video"], check=True)

    out_mp4 = tmp_path / "out" / "FINAL.mp4"
    out_mp4.parent.mkdir(exist_ok=True)
    subprocess.run([
        sys.executable, str(root / "scripts" / "mix.py"),
        "--project", str(tmp_path),
        "--video", str(work_dir / "proxy.mp4"),
        "--out", str(out_mp4)
    ], check=True)

    assert out_mp4.exists() and out_mp4.stat().st_size > 1000
    subs = json.loads((work_dir / "subtitles.json").read_text())
    assert len(subs) == 2
    assert subs[0]["text"] == "One two three"
    assert subs[1]["text"] == "four five"

    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert "Antigravity" in skill_text
    assert "edits.json" in skill_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project_smoke.py -v`
Expected: FAIL (`SKILL.md` does not yet contain `Antigravity` and `edits.json` workflow).

- [ ] **Step 3: Update `SKILL.md`, `README.md`, and `requirements.txt`**

Update `SKILL.md` and `README.md` with the complete Antigravity workflow, CLI commands (`transcribe.py`, `auto_cut.py`, `cuts.py`, `subtitles.py`, `build.py`, `serve.py`, `render.mjs`, `mix.py`), and instructions for the Canva/CapCut interactive web studio. Update `requirements.txt`.

- [ ] **Step 4: Run full pytest suite to verify all tests pass**

Run: `pytest -v`
Expected: PASS (all tests across all 5 test files passing)

- [ ] **Step 5: Commit**

```bash
git add SKILL.md README.md requirements.txt tests/test_project_smoke.py
git commit -m "docs(skill): update SKILL.md and README for Antigravity studio workflow with e2e smoke test"
```
