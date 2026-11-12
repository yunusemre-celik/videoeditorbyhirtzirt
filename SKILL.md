---
name: video-edit
description: Edit talking-head, tutorial, explainer, TikTok, Reels, and YouTube Shorts videos with Antigravity. Word-accurate cuts from raw takes, automated auto_cut, 3-word dynamic subtitles, segment speed control, interactive Canva/CapCut-style browser studio with two-way sync via edits.json, custom audio and media overlays, sound effects synthesized from math, honest loudness handling and frame-exact rendering.
---

# Video Edit with Antigravity

This skill turns raw footage into a finished, polished video edit (vertical 9:16 Shorts/Reels/TikTok or horizontal 16:9 explainers) using Antigravity, local CLI scripts, and an interactive Canva/CapCut-style web studio.

Read this entire guide before touching a project. Read `reference/audio.md` before making any cuts or level adjustments, and `reference/style.md` before styling graphics.

---

## Read First: What You Can and Cannot Do

- **You cannot hear.** You never listen to audio. Everything you know about sound comes from numbers: Whisper word timestamps, a 10 ms RMS energy envelope, loudness meters, and spectrograms. Say this to the user plainly and never claim that something "sounds good".
- **The human ear is the final check.** Whether a cut clips a word, whether an effect is too loud, or whether a voice sounds muffled: the human creator decides. Your job is to make every problem measurable and every fix fast.
- **The first pass is never the final edit.** Work stage by stage, hand over a preview after each stage, and expect corrections. Most good results come from short review loops between Antigravity and the creator.
- **Sync by construction, not by ear.** Animations, subtitles, overlays, and sound effects are triggered from the same timeline clock, derived from measured word times and frame counts. That is how effects land on the picture without you hearing them.
- **Be creative, on purpose.** Every visual should help the viewer understand, and nothing should look like an uninspired template.

---

## Project Structure

```
project/
  src/            Raw video clips (or symlinks to them)
  work/           Generated intermediate files:
                    clips.json, env/*.npy, transcripts/*.json,
                    edl.json, program.json, edits.json,
                    subtitles.json, subtitles.srt,
                    proxy.mp4, prog.wav, backup/
  scene/          Motion graphics and interactive studio web app (copied from template/)
  assets/         User assets: .mp3, .wav, .mp4, .webm, .png, .jpg, .jpeg, .webp
  out/            Final rendered videos and frames (e.g. out/FINAL.mp4)
```

Keep the project outside cloud-synced folders (Dropbox, iCloud Drive, OneDrive) if possible to prevent file locks or eviction during rendering.

---

## The 7-Stage Antigravity Pipeline

### 1. Transcribe (`scripts/transcribe.py`)
Extracts audio from raw takes, calculates a 10 ms RMS energy envelope (`work/env/<clip>.npy`), splits each clip at natural pauses, and runs local English word-timestamp transcription via `faster-whisper` (or `whisperkit-cli` on Apple Silicon). Chunking at pauses prevents Whisper from dropping repeated words or hallucinations during retakes.

```bash
python scripts/transcribe.py --project . src/*.mp4 --lang en
```
Outputs:
- `work/transcripts/<clip>.json` and `<clip>.txt` with numbered utterances and word times.
- `work/env/<clip>.npy` (10 ms RMS energy envelope used for snapping cuts).
- `work/clips.json` (clip map).

### 2. Auto Cut (`scripts/auto_cut.py`)
Generates an automatic Edit Decision List (`work/edl.json`) from the transcripts and energy envelope, removing silences, false starts, and retakes. Optionally integrates with `auto-editor` for advanced audio-based jump-cutting.

```bash
python scripts/auto_cut.py --project .                  # Automatic EDL generation
python scripts/auto_cut.py --project . --use-auto-editor # Optional auto-editor integration
```
Outputs:
- `work/edl.json` containing selected utterance ranges, target pace (`tight`, `natural`, `relaxed`), and optional initial speed settings.

### 3. Snapped Cuts & Speed Ranges (`scripts/cuts.py`)
Converts `work/edl.json` into a frame-accurate `work/program.json`. Snaps cut points to the nearest measured word boundaries using the 10 ms energy envelope so speech is never clipped. Incorporates segment speed adjustments specified in `work/edl.json` (per-cut `"speed"`) and `work/edits.json` (`"speed_ranges"`).

```bash
python scripts/cuts.py --project .
```
Outputs:
- `work/program.json` (frame-accurate cut list with scaled timings, speed factors, and chapter markers).
- `work/chapters.txt` (YouTube/social timestamp chapter list).

### 4. Dynamic 3-Word Subtitles (`scripts/subtitles.py`)
Chunks speech into punchy 1-to-3 word subtitle groups ideal for TikTok, Instagram Reels, and YouTube Shorts. Subtitles do not use distracting karaoke color transitions. Automatically breaks on sentence punctuation (`.`, `!`, `?`, `,`, `:`, `;`), pauses exceeding 250 ms, and respects custom word overrides defined in `work/edits.json`.

```bash
python scripts/subtitles.py --project .
```
Outputs:
- `work/subtitles.json` (structured cue array with `start`, `end`, and `text` in program time).
- `work/subtitles.srt` (standard SubRip subtitle file for social platform upload).

### 5. Build Preview Media (`scripts/build.py`)
Assembles sample-exact audio and frame-exact video according to `work/program.json`. Audio slices are extracted at 48 kHz with micro-fades (4 ms in, 15 ms out) to eliminate clicks. Speed adjustments use pitch-preserving FFmpeg `atempo` filter chains for audio and `setpts` for video. One linear gain is applied to normalize dialogue loudness.

```bash
python scripts/build.py --project . audio video         # Builds work/prog.wav and work/proxy.mp4
python scripts/verify.py --project .                     # Verifies cut joins to catch clipped words
```
Outputs:
- `work/prog.wav` (clean 48 kHz dialogue track).
- `work/proxy.mp4` (1080p preview video aligned with program time).

### 6. Interactive Web Studio (`scripts/serve.py`)
Launches the Canva/CapCut-style interactive editor at `http://127.0.0.1:5600/scene/`.

```bash
python scripts/serve.py --project . --port 5600
```
Key Studio Features:
- **Two-Way Sync via `work/edits.json`:** Every visual change made in the browser studio is immediately saved to disk; external edits to `work/edits.json` update the studio live via `GET /api/edits` and `POST /api/edits`.
- **20-Step Undo / Redo:** Full history state stack (`Ctrl+Z` / `Ctrl+Y`).
- **Normalized Drag & Resize Bounding Boxes:** Visual handles with `0..1` normalized coordinates for positioning subtitles and media overlays across any aspect ratio.
- **Asset Tray:** Direct drag-and-drop file upload for supported media assets (`.mp3`, `.wav`, `.mp4`, `.webm`, `.png`, `.jpg`, `.jpeg`, `.webp`) into `assets/` via `POST /api/assets`.
- **Speed Segment Editor:** Add and tweak speed ranges (`0.25x` to `4.0x`) directly on the timeline.
- **Subtitles Inspector:** Customize position, font size, uppercase transform, and word replacement overrides.
- **Sound Effects Library:** Audition and preview mathematical SFX synthesized via `scripts/sfx.py`.

### 7. Final Render & Audio Mix (`scripts/render.mjs` & `scripts/mix.py`)
Renders the motion graphics, subtitle overlays, and visual effects frame-exact in headless Chrome using `?still` mode, then mixes dialogue, mathematical SFX, and custom audio tracks.

```bash
# Render high-resolution video background:
python scripts/build.py --project . video --final

# Headless Chrome frame-by-frame render:
node scripts/render.mjs "http://127.0.0.1:5600/scene/?src=../work/prog-final.mp4" --out out/frames --workers 4 --dpr 2

# Mix audio (voice + sfx + custom audio clips) and mux final MP4:
python scripts/mix.py --project . --video out/frames --out out/FINAL.mp4

# Check loudness standards (target -14 LUFS, true peak ceiling -1 dBTP):
python scripts/loudness.py out/FINAL.mp4
```
Outputs:
- `out/FINAL.mp4` (production-ready high-bitrate video).

---

## Scripts Reference

| Script | Purpose |
|---|---|
| `transcribe.py` | Pause-chunked transcription with word timestamps (`faster-whisper`) and 10 ms RMS energy envelope calculation. |
| `auto_cut.py` | Automatic `work/edl.json` generation with optional `--use-auto-editor` CLI integration. |
| `cuts.py` | Snaps EDL cuts to energy envelope word edges and applies segment speeds to create `work/program.json`. |
| `subtitles.py` | Generates 3-word dynamic subtitle chunks (`work/subtitles.json` and `work/subtitles.srt`) with override support. |
| `build.py` | Builds sample-exact audio with pitch-safe `atempo` stretching and frame-exact video with `setpts`. |
| `serve.py` | Local development server with HTTP range support, asset upload API, and two-way `work/edits.json` synchronization. |
| `verify.py` | Re-transcribes cut joins to verify no words or syllables were clipped. |
| `sfx.py` | Synthesizes clean sound effects from mathematical formulas (whoosh, pop, click, tick, chime). |
| `render.mjs` | Multi-process headless Chrome frame-exact renderer using deterministic `?still` stepping. |
| `mix.py` | Mixes dialogue audio, synthesized SFX, and custom audio tracks with true-peak limiting. |
| `loudness.py` | Measures integrated LUFS, true peak (dBTP), and loudness range (LRA) according to ITU-R BS.1770 / EBU R128. |
| `audit.mjs` | Automated visual check for overlapping elements, text occluding faces, or bounding box overflows. |

---

## Working Notes & Edits Sync

Keep `work/NOTES.md` updated with creator preferences, intake answers, and revision logs. Use `work/edits.json` as the single source of truth for canvas overlays, subtitle styling, speed ranges, and custom audio cues.
