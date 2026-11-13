# Antigravity Video Studio — Phase 2 UX & Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 6 Phase 2 user-side UX upgrades: One-Click Rebuild & Export MP4, Audio/SFX Track + Inspector + Live WebAudio Preview, Timeline Bar Drag & Edge-Trim Handles, TikTok/Reels Safe Zone Guide, Transcript-Based Video Cutting (`deleted_ranges`), and Raw Source Video Upload + One-Click Project Bootstrap.

**Architecture:**
- **Task 1 (Backend):** Extend `scripts/cuts.py` with `apply_deleted_ranges_to_pieces` so transcript-based cuts in `work/edits.json["deleted_ranges"]` are frame-accurately excised from `pieces`, `words`, and `chapters`. Extend `scripts/serve.py` with `deleted_ranges` in `default_edits()`, `sanitize_source_filename`, `GET /api/project-status`, `POST /api/source-video`, `POST /api/init-project`, and `POST /api/export`.
- **Task 2 (Frontend & Docs):** Upgrade `template/engine.js`, `template/editor.js`, and `template/editor.css` with top-bar Rebuild & Export MP4 buttons, Safe Zone overlay toggle (hidden in `?still`), Audio/SFX Inspector tab + 4th timeline track + custom audio WebAudio preview, timeline segment drag & left/right trim handles, transcript cue cut/restore (`deleted_ranges`), and raw `src/` video upload + Auto-Cut bootstrap UI. Update `README.md` and `SKILL.md`.

**Spec:** `docs/superpowers/specs/2026-11-13-studio-ux-v2-design.md`

## Global Constraints
- `default_edits()` in `scripts/serve.py`, `template/engine.js`, and `template/editor.js` MUST include `"deleted_ranges": []`.
- `apply_deleted_ranges_to_pieces(pieces, words, deleted_ranges, fps, chapters=None)` in `scripts/cuts.py` MUST excise deleted intervals `[start, end]`, split partially overlapping pieces, repack `p` frame positions contiguously, remove words whose midpoint falls inside a deleted range, and shift surviving words and chapter markers earlier by the cumulative deleted duration before them.
- In `?still` render mode (`.still-mode`), `#safe-zone-guide` and all editor UI chrome MUST remain hidden (`display: none !important`).
- Audio clips inserted in `template/editor.js` MUST include both `src` (`assets/<name>`) and `url` (`../assets/<name>`), plus `gain_db` (default `0`), `start`, `end`, and `trim_start` (`0`) so both `template/engine.js` preview and `scripts/mix.py` render work seamlessly.
- All existing 29 tests and all new tests MUST pass via `python -m pytest -v`.

---

### Task 1: Backend Transcript Cuts (`deleted_ranges`) & Studio Workflow Endpoints (`scripts/cuts.py`, `scripts/serve.py`)

**Files:**
- Modify: `scripts/cuts.py`
- Modify: `scripts/serve.py`
- Create: `tests/test_studio_v2_backend.py`

- [ ] **Step 1: Write failing tests in `tests/test_studio_v2_backend.py`**
  - Test `apply_deleted_ranges_to_pieces` in `scripts/cuts.py`:
    - Deleting `[1.0, 2.0]` from a 4.0s piece (`a=0, b=120, p=0, pf_len=120` at `fps=30`) splits it into two pieces (`[0..30]` at `p=0` and `[60..120]` at `p=30`, total `pf=90` frames = `3.0s`).
    - Words inside `[1.0, 2.0]` (e.g. `[1.2, 1.8, "remove", 0]`) are removed, and words after `2.0s` (e.g. `[2.5, 3.0, "keep", 0]`) are shifted left by `1.0s` to `[1.5, 2.0, "keep", 0]`.
    - Chapter markers after `2.0s` (e.g. `{'title': 'Part 2', 'frame': 90, 'time': 3.0}`) are shifted left by `1.0s` to `time=2.0, frame=60`.
  - Test `scripts/serve.py` new endpoints:
    - `default_edits()` includes `"deleted_ranges": []`.
    - `GET /api/project-status` returns `ok: True`, `has_program`, `has_proxy`, `has_final`, and `src_files`.
    - `POST /api/source-video` with `X-Filename: raw clip.mp4` saves `src/raw_clip.mp4` and rejects invalid extensions (`.exe`) or traversal (`../evil.mp4`) with `400`.
    - `POST /api/init-project` and `POST /api/export` return `{"ok": True, ...}` (using monkeypatched `subprocess.run` in tests so external ffmpeg/node processes aren't required during unit tests).

- [ ] **Step 2: Implement `apply_deleted_ranges_to_pieces` in `scripts/cuts.py`**
  - Add `apply_deleted_ranges_to_pieces(pieces, words, deleted_ranges, fps, chapters=None) -> tuple[list[dict], list[list], int]`.
  - Normalize and merge overlapping `deleted_ranges` sorted by `start`.
  - For each piece, slice out any sub-interval overlapping a deleted range, map source frames `[a, b]` fractionally, and repack `p` contiguously.
  - Filter out words whose midpoint `(w[0] + w[1]) / 2.0` falls within any merged deleted interval, and shift surviving word start/end times and chapter times left by the sum of deleted durations before `t`.
  - In `cuts.py:build()`, load `deleted_ranges = edits.get('deleted_ranges', [])` from `work/edits.json` and call `apply_deleted_ranges_to_pieces` before `apply_speed_ranges_to_pieces`.

- [ ] **Step 3: Implement new Studio API endpoints in `scripts/serve.py`**
  - Add `"deleted_ranges": []` to `default_edits()`.
  - Add `ALLOWED_SOURCE_EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv'}` and `sanitize_source_filename(filename: str) -> str`.
  - Add `GET /api/project-status` (`_handle_get_project_status`).
  - Add `POST /api/source-video` (`_handle_post_source_video`).
  - Add `POST /api/init-project` (`_handle_post_init_project`): discovers video files in `src/`, runs `transcribe.py` on `src/` clips, runs `auto_cut.py` on the first clip if `work/edl.json` does not exist, then runs `cuts.py` and `build.py`.
  - Add `POST /api/export` (`_handle_post_export`): runs `node scripts/render.mjs --project <project_dir> --scene http://127.0.0.1:<port>/scene/` and `python scripts/mix.py --project <project_dir>`, returning `{"ok": True, "download_url": "../out/FINAL.mp4"}`.

- [ ] **Step 4: Run pytest and commit**
  - Run `python -m pytest -v` and commit changes on `feat/studio-ux-v2`.

---

### Task 2: Frontend Studio UX v2 (`template/editor.js`, `template/editor.css`, `template/engine.js`, `README.md`, `SKILL.md`)

**Files:**
- Modify: `template/engine.js`
- Modify: `template/editor.js`
- Modify: `template/editor.css`
- Modify: `README.md`
- Modify: `SKILL.md`
- Create: `tests/test_studio_v2_ui.py`

- [ ] **Step 1: Write failing tests in `tests/test_studio_v2_ui.py`**
  - Verify `template/editor.js`, `template/editor.css`, and `template/engine.js` contain:
    - Top-bar buttons: `#btn-safe-zone`, `#btn-rebuild`, `#btn-export`
    - Safe Zone guide element `#safe-zone-guide` inside `#stage` and `.still-mode #safe-zone-guide { display: none !important; }` in `template/editor.css`
    - 4th timeline track `#track-audio` (`Audio / SFX`) and Right Inspector `data-tab="audio"`
    - Timeline segment drag & trim handles (`.seg-handle.left`, `.seg-handle.right`) in `template/editor.js`
    - Transcript cue cut button (`data-cut-cue`) and restore button (`data-restore-del`) operating on `edits.deleted_ranges`
    - Raw source video upload (`#src-file-input`, `/api/source-video`) and `#btn-init-project` (`/api/init-project`) in the Left Panel
    - `engine.js` custom audio clip loading (`clip.type === 'audio'`) with `gain_db` / `gain` and automatic skipping over `edits.deleted_ranges` during playback

- [ ] **Step 2: Upgrade `template/engine.js`**
  - Add `deleted_ranges: []` to `defaultEdits()`.
  - Update `syncSfx()` and `loadSfx()` / `playCue()` so both `type === 'sfx'` (`sfx/${clip.name}.wav`) and `type === 'audio'` (`clip.url || ('../' + clip.src)`) are loaded into WebAudio buffers and triggered with `gain_db ?? gain ?? 0` and `trim_start` / duration `(clip.end - clip.start)`.
  - In `apply(t)` and `tick(now)`, if `currentEdits.deleted_ranges` contains an active deleted range `[del.start, del.end]` where `clock >= del.start && clock < del.end - 0.02`:
    - During `playing`, immediately advance `seek(del.end)` so deleted ranges are skipped live in preview even before `Rebuild`.
    - In `apply(t)`, hide `#subtitles-box` when `t` is inside a deleted range.

- [ ] **Step 3: Upgrade `template/editor.js` and `template/editor.css`**
  - **Top Bar:** Add `#btn-safe-zone` (`📱 Safe Zone`), `#btn-rebuild` (`⚡ Rebuild`), and `#btn-export` (`🎬 Export MP4`).
    - Clicking `#btn-rebuild` saves `edits` via `POST /api/edits`, then calls `POST /api/rebuild`, and reloads the page or refreshes `program.json`/`proxy.mp4`.
    - Clicking `#btn-export` saves `edits` via `POST /api/edits`, calls `POST /api/export`, shows progress toast, and offers a download link to `../out/FINAL.mp4`.
  - **TikTok/Reels Safe Zone Guide:** Inject `#safe-zone-guide` inside `#stage` with right-side action rail and bottom caption zone; toggle `.active` via `#btn-safe-zone`. Ensure `.still-mode #safe-zone-guide { display: none !important; }` in `template/editor.css`.
  - **Left Panel Source Video & Project Init:** Add a "Source Footage (`src/`)" section at the top of the Left Panel with `#btn-upload-src` (`#src-file-input` posting to `/api/source-video`) and `#btn-init-project` (posting to `/api/init-project`). Standardize newly added audio clips to include `src: 'assets/' + name`, `url: '../assets/' + name`, `gain_db: 0`, `trim_start: 0`.
  - **Right Inspector:**
    - Add `Audio` tab (`data-tab="audio"`) listing `edits.audio_clips` with controls for `start`, `end`, `trim_start`, `gain_db` (`-24` to `+12`), and delete (`data-del-aud`).
    - In `Subtitles` tab, add a `✂️` button (`data-cut-cue`) on each 3-word cue row that pushes `{id, start, end, text}` to `edits.deleted_ranges`, plus a "Deleted Cuts" list with a restore button (`data-restore-del`).
  - **Bottom Timeline (`#track-overlays`, `#track-speed`, `#track-audio`):**
    - Add `#track-audio` track row for `edits.audio_clips`.
    - Render `.seg-handle.left` and `.seg-handle.right` inside each `.track-segment` on overlays, speed, and audio tracks, and wire pointer drag (`move`, `trim-left`, `trim-right`) to update `start` and `end` live and commit via `applyChange(true)` on `pointerup`.

- [ ] **Step 4: Update `README.md` & `SKILL.md`, run full pytest suite, and commit**
  - Document the new Phase 2 Studio buttons and API endpoints in `README.md` and `SKILL.md`.
  - Run `python -m pytest -v` and commit on `feat/studio-ux-v2`.
