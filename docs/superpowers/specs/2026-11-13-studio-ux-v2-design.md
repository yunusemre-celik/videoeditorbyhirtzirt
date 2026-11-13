# Antigravity Video Studio — Phase 2 UX & Workflow Upgrade Design Spec

**Date:** 2026-11-13
**Repository:** `videoeditorbyhirtzirt`
**Branch:** `feat/studio-ux-v2`

## 1. Goal & Scope
Upgrade the browser-based Antigravity Studio (`template/editor.js`, `template/editor.css`, `template/engine.js`, `scripts/serve.py`, `scripts/cuts.py`) to close the 6 user-side workflow gaps identified after Phase 1:

1. **One-Click "⚡ Rebuild" & "🎬 Export MP4" in the Top Bar:**
   - Users can trigger `POST /api/rebuild` (`cuts.py` + `build.py`) and `POST /api/export` (`render.mjs` + `mix.py` -> `out/FINAL.mp4`) directly from the studio top bar without switching to the terminal.
2. **Audio / SFX Inspector Tab, Timeline Track, & Live Preview:**
   - Add an `Audio` tab in the Right Inspector to inspect, adjust volume (`gain_db`), edit `start` / `end` / `trim_start`, and delete placed `.mp3`/`.wav` clips and SFX cues.
   - Add a 4th timeline track (`#track-audio`) displaying `audio_clips`.
   - Extend `template/engine.js` so custom `audio_clips` (`type: "audio"`) as well as `type: "sfx"` are decoded and previewed via WebAudio with `gain_db` and `trim_start`.
3. **Interactive Timeline Drag & Edge-Trim Handles:**
   - Timeline bars on `#track-overlays`, `#track-speed`, and `#track-audio` support horizontal drag-to-move and left/right edge handles (`.seg-handle.left`, `.seg-handle.right`) to trim `start` and `end` times directly on the timeline, integrated with the 20-step Undo/Redo history.
4. **TikTok / Reels Safe Zone Overlay Guide:**
   - Toggle button `#btn-safe-zone` in the top bar shows/hides a `#safe-zone-guide` overlay inside `#stage` marking the TikTok/Reels right-rail action buttons and bottom caption area. Strictly hidden in `?still` headless render mode (`.still-mode`).
5. **Transcript-Based Video Cutting (`deleted_ranges`):**
   - Each 3-word subtitle cue row in the Subtitles Inspector includes a `✂️` cut button that adds `{id, start, end, text}` to `edits.deleted_ranges` (and shows a restore list for deleted ranges).
   - In browser preview (`engine.js`), playback automatically skips over `edits.deleted_ranges` and hides subtitles inside deleted ranges.
   - During `cuts.py` (`apply_deleted_ranges_to_pieces`), any `deleted_ranges` in `work/edits.json` are physically excised from `pieces`, `words`, and `chapters` before `speed_ranges` are applied.
6. **Raw Source Video Upload & One-Click Project Bootstrap:**
   - Left Panel includes a "Source Video (`src/`)" section with `#src-file-input` and `#btn-init-project` allowing users to upload raw `.mp4`/`.mov`/`.webm` footage to `src/` (`POST /api/source-video`) and run the initial pipeline (`POST /api/init-project`: `transcribe.py` -> `auto_cut.py` -> `cuts.py` -> `build.py`) directly from the browser.

---

## 2. Data Schema Additions (`work/edits.json`)
`default_edits()` in `scripts/serve.py`, `template/engine.js`, and `template/editor.js` includes `"deleted_ranges": []`:

```json
{
  "version": 1,
  "aspect": "9:16",
  "stage": { "width": 1080, "height": 1920 },
  "subtitles": {
    "enabled": true,
    "x": 0.5,
    "y": 0.78,
    "fontSize": 56,
    "color": "#ffffff",
    "bgColor": "rgba(15, 17, 22, 0.78)",
    "uppercase": false,
    "overrides": {}
  },
  "speed_ranges": [],
  "deleted_ranges": [
    { "id": "del-0", "start": 1.2, "end": 2.4, "text": "um let me" }
  ],
  "media_overlays": [],
  "audio_clips": [
    {
      "id": "aud-1",
      "type": "audio",
      "name": "whoosh_custom.mp3",
      "src": "assets/whoosh_custom.mp3",
      "url": "../assets/whoosh_custom.mp3",
      "start": 1.5,
      "end": 4.5,
      "trim_start": 0.0,
      "gain_db": 0.0
    }
  ]
}
```

---

## 3. Backend API Specification (`scripts/serve.py` & `scripts/cuts.py`)
1. `apply_deleted_ranges_to_pieces(pieces, words, deleted_ranges, fps, chapters=None)` in `scripts/cuts.py`:
   - Excises any `[start, end]` intervals in `deleted_ranges` from `pieces`, splitting pieces that partially overlap a deleted range and re-packing `p` frame offsets contiguously.
   - Filters out `words` whose midpoint `(w[0] + w[1]) / 2.0` lies inside any deleted range, and shifts surviving word timestamps (`w[0]`, `w[1]`) and `chapters` (`ch['time']`, `ch['frame']`) left by the cumulative deleted duration prior to that timestamp.
   - Called in `cuts.py:build()` from `edits.get("deleted_ranges", [])` prior to `apply_speed_ranges_to_pieces`.
2. `GET /api/project-status` in `scripts/serve.py`:
   - Returns `{"ok": True, "has_program": bool, "has_proxy": bool, "has_final": bool, "src_files": list[str]}`.
3. `POST /api/source-video` in `scripts/serve.py`:
   - Reads `X-Filename` header, validates extension in `{'.mp4', '.mov', '.webm', '.mkv'}`, sanitizes filename via `sanitize_source_filename(filename)`, saves binary payload to `src/<safe_name>`, and returns `{"ok": True, "file": safe_name}`.
4. `POST /api/init-project` in `scripts/serve.py`:
   - Runs `transcribe.py`, `auto_cut.py` (for each clip in `src/`), `cuts.py`, and `build.py` in sequence (when those scripts exist), returning `{"ok": True, "clips": [...]}`.
5. `POST /api/export` in `scripts/serve.py`:
   - Runs `node scripts/render.mjs --project <project_dir> --scene http://127.0.0.1:<port>/scene/` and `python scripts/mix.py --project <project_dir>` (when scripts exist), returning `{"ok": True, "download_url": "../out/FINAL.mp4"}`.
