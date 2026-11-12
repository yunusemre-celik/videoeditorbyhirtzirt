# Antigravity Video Editor (`videoeditorbyhirtzirt`) Design Spec

## 1. Intent & Why
Build an open-source, local-first Reels/TikTok & Shorts video editing system powered by **Antigravity** and built on the **`YildizDikme/claude-video-edit`** backbone. The creator records raw English talking-head or explainer footage, lets the coding agent perform word-accurate cuts (via `faster-whisper` + 10ms RMS energy envelope + `auto-editor`), generate 3-word dynamic subtitles, and place sound effects/visuals, and then uses a **Canva/CapCut-style browser editor** on top of the HTML/GSAP scene (`scene/`) to tweak anything visually (drag subtitle position, add `.png/.jpeg/.mp4/.mp3` files, change playback speed for specific time ranges, undo/redo) before final frame-exact MP4 rendering.

## 2. Goals, Non-Goals & Anti-Goals
### Goals
- **100% Free Local English Transcription & Cutting:** Use `faster-whisper` (chunked at pauses) + 10ms energy envelope (`cuts.py`) + `auto-editor` CLI integration (`scripts/auto_cut.py`) to cut dead air and retakes without clipping words.
- **Dynamic 3-Word Subtitles:** Group spoken words into phrase-aware chunks of up to 3 words (breaking on punctuation `.,!?;:` or pauses `>= 0.35s`). Display one 3-word chunk at a time synchronously with speech (no karaoke per-word color change).
- **Segment-Specific Speed Control:** Allow setting playback speed (`0.25x` to `4.0x`) for specific time segments (`speed_ranges` or per-EDL item `speed`), keeping audio (pitch-preserved via `atempo`), video frames, and word/subtitle timestamps synchronized.
- **Custom Media Uploads (`.mp3`, `.mp4`, `.png`, `.jpg/.jpeg`):** Let the user upload and place custom images, B-roll/PIP videos, and custom MP3 audio/SFX onto the timeline alongside synthesized mathematical SFX (`whoosh`, `pop`, `click`, `tick`, `typing`, `chime`).
- **Canva/CapCut-Style Interactive Scene Editor (Option A):** Turn `template/` (`scene/`) into a dual-mode application:
  - **Interactive Edit Mode (Browser):** Drag-and-drop positioning/resizing with normalized `0..1` coordinates (`x, y, width, height`), 20-step Undo/Redo history (inspired by `banana-studio`), Asset Tray for `.mp3/.mp4/.png/.jpeg`, timeline bars for overlays/audio/speed segments, and two-way persistence via `work/edits.json`.
  - **Headless Render Mode (`?still`):** Hides all editor chrome and renders every frame deterministically via `render.mjs` + `mix.py` (including custom `.mp3` audio tracks and segment speeds).
- **Antigravity Skill Integration:** Provide `SKILL.md` tailored for Antigravity so the agent and human editor share `work/edl.json`, `work/program.json`, and `work/edits.json`.

### Non-Goals
- Paid cloud transcription APIs (ElevenLabs Scribe is not used).
- Paid generative AI APIs (OpenRouter/fal.ai from `banana-studio` are not required).
- Multi-user cloud hosting (runs locally on the user's machine).

### Anti-Goals
- Karaoke word-by-word color highlighting (the user explicitly requested clean 3-word blocks that appear and swap every 3 words without per-word color shifts).
- Muffling voice audio with heavy denoisers/compressors (preserve `claude-video-edit`'s linear gain + pitch-safe `atempo` philosophy).

## 3. Approaches Considered
1. **Option A (Selected) — Live HTML/GSAP Canvas Editor + Headless Chrome Frame-Exact Render (`claude-video-edit` Backbone):**
   - *Trade-off:* Browser canvas matches final MP4 pixel-for-pixel; DOM elements (3-word subtitles, PNG/JPEG images, MP4 overlays) are directly draggable/resizable like Canva. Rendering takes ~1 min for a 60s Reel via parallel workers in `render.mjs`.
2. **Option B — Pure FFmpeg Filtergraph (`video-use` style) + Coordinate Picker:**
   - *Trade-off:* Faster raw encode, but preview in browser diverges from `libass` subtitle rendering and lacks rich HTML/CSS styling.

## 4. Technical Architecture & Data Contracts

### 4.1. 3-Word Subtitle Chunker (`scripts/subtitles.py` & `template/subtitles.js`)
- Input: `words` list from `program.json`, where each item is `[start_sec, end_sec, word_str, entry_idx?]`.
- Rules:
  - `MAX_WORDS = 3`
  - `PAUSE_BREAK_SEC = 0.35`
  - `PUNCT_BREAK = set(".,!?;:")`
  - A chunk closes when:
    1. `len(current) == 3`, OR
    2. `word` ends with a character in `PUNCT_BREAK`, OR
    3. `next_word.start - word.end >= 0.35`, OR
    4. It is the last word.
- Output list of cue dicts:
  ```json
  [
    {
      "id": "sub_0",
      "start": 0.60,
      "end": 1.38,
      "text": "This scene shows",
      "words": [[0.60, 0.81, "This"], [0.87, 1.15, "scene"], [1.21, 1.38, "shows"]]
    }
  ]
  ```

### 4.2. Shared Edits State (`work/edits.json`)
`work/edits.json` is read by `serve.py`, `template/engine.js`, `template/editor.js`, `scripts/cuts.py`, and `scripts/mix.py`.
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
  "speed_ranges": [
    { "id": "spd_1", "start": 2.0, "end": 5.0, "speed": 1.25 }
  ],
  "media_overlays": [
    {
      "id": "ov_1",
      "type": "image",
      "src": "../assets/example.png",
      "start": 1.0,
      "end": 4.0,
      "x": 0.5,
      "y": 0.3,
      "width": 0.6,
      "height": 0.35,
      "opacity": 1.0
    }
  ],
  "audio_clips": [
    {
      "id": "aud_1",
      "type": "sfx",
      "name": "pop",
      "src": null,
      "start": 1.0,
      "gain_db": 0.0
    },
    {
      "id": "aud_2",
      "type": "mp3",
      "name": "custom.mp3",
      "src": "assets/custom.mp3",
      "start": 2.5,
      "end": 6.0,
      "trim_start": 0.0,
      "gain_db": -6.0
    }
  ]
}
```

### 4.3. Segment Speed Control (`scripts/cuts.py`, `scripts/build.py`, `template/engine.js`)
- **In `edl.json` / `cuts.py`:**
  - Any item in `edl.json` may include `"speed": float` (default `1.0`, clamped to `[0.25, 4.0]`).
  - Additionally, `cuts.py` supports splitting/applying `speed_ranges` from `work/edits.json` (source or program time ranges) or item-level `"speed"`.
  - For any piece with `speed != 1.0`:
    - Source frames remain `a` and `b` (`source_frames = b - a`).
    - Program frames `prog_frames = max(1, int(round((b - a) / speed)))`.
    - Piece dict in `program.json` stores `"speed": speed` and `"pf_len": prog_frames`.
    - Words falling inside piece `[a/fps, b/fps]` have their program timestamps scaled: `prog_t = piece_prog_start + (src_t - a/fps) / speed`.
- **In `scripts/build.py`:**
  - `build_audio`: When a piece has `speed != 1.0`, applies FFmpeg `atempo` chain (`_atempo_filter(speed)`) to stretch/compress the audio slice to match `prog_frames` samples before applying the 4ms/15ms join fades.
  - `build_video`: When a piece has `speed != 1.0`, adjusts PTS (`setpts=(PTS-STARTPTS)/{speed}`) and outputs exactly `prog_frames` frames at `fps`.
- **In Browser Preview (`template/engine.js`):**
  - If the user adds a live speed range in `edits.json` before rebuilding `proxy.mp4`, `engine.js` dynamically sets `video.playbackRate` during preview playback. Clicking "Apply Speed to Video (`Rebuild`)" calls `POST /api/rebuild` to bake the speed into `program.json` and `proxy.mp4`.

### 4.4. Custom Audio & SFX Mixing (`scripts/mix.py`)
- Reads both `sfx.json` (exported from scene) and `work/edits.json` (`audio_clips`).
- Built-in SFX (`whoosh`, `pop`, `click`, etc.) are synthesized via `sfx.make()`.
- Custom `.mp3` / `.wav` files in `audio_clips` are decoded at 48kHz stereo via `_common.decode()`, trimmed to `[trim_start, trim_start + (end - start)]`, scaled by `10 ** (gain_db / 20)`, and summed into the master mix under the true-peak ceiling (`-1.0 dBTP`).

### 4.5. `auto-editor` Integration (`scripts/auto_cut.py`)
- Provides a CLI helper that runs `auto-editor` (if installed on PATH, or falls back to ` _common.speech_regions` 10ms envelope silence cutter) to automatically generate an initial `work/edl.json` for raw Reels/TikTok clips.

### 4.6. Local Studio API Server (`scripts/serve.py`)
- Serves static project files with HTTP Range (`206 Partial Content`) support.
- Endpoints:
  - `GET /api/edits` — returns `work/edits.json` (creates default if missing).
  - `POST /api/edits` — writes validated JSON to `work/edits.json`.
  - `GET /api/assets` — returns JSON list of files in `assets/` and `scene/sfx/`.
  - `POST /api/assets` — accepts raw binary upload with header `X-Filename` (or multipart/JSON base64) for `.mp3`, `.mp4`, `.png`, `.jpg`, `.jpeg`, `.wav`, saves safely into `assets/`, and returns `{ "name": ..., "url": "../assets/...", "type": "image"|"video"|"audio" }`.
  - `POST /api/subtitles` — returns 3-word chunked subtitles generated from `work/program.json`.
