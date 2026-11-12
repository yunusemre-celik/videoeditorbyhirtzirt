#!/usr/bin/env python3
"""Final mix: rendered video + program voice + sound-effects track -> one file.

The voice keeps the level build.py gave it. Effects are added under it. If the sum would pass the true-peak
ceiling, the whole mix is lowered by the excess (linear, no limiter), and the report says so.

usage:
  python3 scripts/mix.py --project . --video out/frames --out out/FINAL.mp4 [--sfx-gain 0] [--no-sfx]
    --video   a render folder from render.mjs (part_*.mp4 + sfx.json) or a single video file
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from scripts._common import decode, ffmpeg, loudness, project_paths, write_wav  # noqa: E402
    from scripts.sfx import SR, MAKERS, make  # noqa: E402
except ImportError:
    from _common import decode, ffmpeg, loudness, project_paths, write_wav  # noqa: E402
    from sfx import SR, MAKERS, make  # noqa: E402


def mix_audio_buffers(
    voice: np.ndarray,
    sfx_cues: list[dict],
    audio_clips: list[dict],
    root: str,
    sfx_gain: float = 0.0,
    ceiling: float = -1.0,
) -> np.ndarray:
    """Mix voice track, synthesized sound effects, and custom audio clips.

    Truncates any clips extending past len(voice).
    If ceiling is specified and peak exceeds ceiling, scales mix to ceiling.
    """
    mix = voice.copy().astype(np.float64)
    if mix.ndim == 1:
        mix = np.column_stack([mix, mix])

    lib: dict[str, np.ndarray] = {}

    # 1. Synthesized SFX from cues (sfx.json)
    if sfx_cues:
        for c in sfx_cues:
            name = c.get('name')
            if not name or name not in MAKERS:
                continue
            if name not in lib:
                lib[name] = make(name, sfx_gain)
            gain = float(c.get('gain', c.get('gain_db', 0.0)) or 0.0)
            x = lib[name] * (10.0 ** (gain / 20.0))
            s = int(float(c.get('t', c.get('start', 0.0)) or 0.0) * SR)
            if 0 <= s < len(mix):
                avail = len(mix) - s
                take = x[:avail]
                if take.ndim == 1 and mix.ndim == 2:
                    take = np.column_stack([take, take])
                mix[s:s + len(take)] += take

    # 2. Audio clips from edits.json
    if audio_clips:
        for clip in audio_clips:
            if not isinstance(clip, dict):
                continue
            clip_type = str(clip.get('type', '')).lower()
            gain_db = float(clip.get('gain_db', clip.get('gain', 0.0)) or 0.0)
            start = float(clip.get('start', 0.0) or 0.0)

            if clip_type == 'sfx':
                name = clip.get('name')
                if not name or name not in MAKERS:
                    continue
                if name not in lib:
                    lib[name] = make(name, sfx_gain)
                x = lib[name] * (10.0 ** (gain_db / 20.0))
                s = int(start * SR)
                if 0 <= s < len(mix):
                    avail = len(mix) - s
                    take = x[:avail]
                    if take.ndim == 1 and mix.ndim == 2:
                        take = np.column_stack([take, take])
                    mix[s:s + len(take)] += take
            else:
                # Custom audio file (.mp3, .wav, etc.)
                src = clip.get('src') or clip.get('name')
                if not src:
                    continue
                clean_src = str(src).replace('\\', '/')
                while clean_src.startswith('../'):
                    clean_src = clean_src[3:]
                while clean_src.startswith('./'):
                    clean_src = clean_src[2:]

                resolved_path = os.path.normpath(os.path.join(root, clean_src))
                if not os.path.isfile(resolved_path):
                    alt = os.path.join(root, 'assets', os.path.basename(clean_src))
                    if os.path.isfile(alt):
                        resolved_path = alt
                    elif os.path.isfile(str(src)):
                        resolved_path = str(src)

                if not os.path.isfile(resolved_path):
                    continue

                try:
                    raw = decode(resolved_path, SR, 2).astype(np.float64)
                except Exception:
                    continue

                if raw.ndim == 1:
                    raw = np.column_stack([raw, raw])
                elif raw.ndim == 2 and raw.shape[1] == 1:
                    raw = np.column_stack([raw[:, 0], raw[:, 0]])

                trim_start = float(clip.get('trim_start', 0.0) or 0.0)
                trim_samples = int(trim_start * SR)
                if trim_samples > 0:
                    if trim_samples < len(raw):
                        raw = raw[trim_samples:]
                    else:
                        continue

                end = clip.get('end')
                if end is not None:
                    dur_samples = max(0, int(round((float(end) - start) * SR)))
                    raw = raw[:dur_samples]
                    if len(raw) == 0:
                        continue

                if gain_db != 0.0:
                    raw = raw * (10.0 ** (gain_db / 20.0))

                s = int(start * SR)
                if 0 <= s < len(mix):
                    avail = len(mix) - s
                    take = raw[:avail]
                    mix[s:s + len(take)] += take
                elif s < 0:
                    offset = -s
                    if offset < len(raw):
                        take = raw[offset:offset + len(mix)]
                        mix[:len(take)] += take

    # Ceiling check
    if ceiling is not None and ceiling < 0:
        peak = float(np.max(np.abs(mix))) if mix.size > 0 else 0.0
        max_allowed = 10.0 ** (ceiling / 20.0)
        if peak > max_allowed:
            mix = mix * (max_allowed / peak)

    return mix


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', default='.')
    ap.add_argument('--video', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--sfx-gain', type=float, default=0.0)
    ap.add_argument('--no-sfx', action='store_true')
    ap.add_argument('--ceiling', type=float, default=-1.0)
    a = ap.parse_args()
    root, work = project_paths(a.project)
    tmp = tempfile.mkdtemp(prefix='ve-mix-')
    try:
        if os.path.isdir(a.video):
            parts = sorted(glob.glob(os.path.join(a.video, 'part_*.mp4')),
                           key=lambda p: int(re.search(r'part_(\d+)', p).group(1)))
            if not parts:
                sys.exit(f'no part_*.mp4 in {a.video}')
            lst = os.path.join(tmp, 'parts.txt')
            with open(lst, 'w') as f:
                f.write(''.join(f"file '{os.path.abspath(p)}'\n" for p in parts))
            video_in = ['-f', 'concat', '-safe', '0', '-i', lst]
            cues_path = os.path.join(a.video, 'sfx.json')
        else:
            video_in = ['-i', a.video]
            cues_path = os.path.join(os.path.dirname(a.video), 'sfx.json')

        voice = decode(os.path.join(work, 'prog.wav'), SR, 2).astype(np.float64)
        cues = []
        if not a.no_sfx and os.path.exists(cues_path):
            with open(cues_path, encoding='utf-8') as f:
                cues = json.load(f)

        audio_clips = []
        edits_path = os.path.join(work, 'edits.json')
        if not a.no_sfx and os.path.exists(edits_path):
            try:
                with open(edits_path, encoding='utf-8') as f:
                    edits = json.load(f)
                    audio_clips = edits.get('audio_clips', [])
            except Exception:
                audio_clips = []

        mix = mix_audio_buffers(voice, cues, audio_clips, root, sfx_gain=a.sfx_gain, ceiling=a.ceiling)

        wav = os.path.join(tmp, 'mix.wav')
        write_wav(wav, mix)
        i, tp, lra = loudness(wav)
        if tp > a.ceiling:
            g = a.ceiling - tp - 0.1
            mix *= 10 ** (g / 20)
            write_wav(wav, mix)
            print(f'note: effects pushed the true peak to {tp:.1f} dBTP; whole mix lowered by {-g:.1f} dB')
            i, tp, lra = loudness(wav)

        ffmpeg(*video_in, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '320k',
               '-shortest', '-movflags', '+faststart', a.out)
        total_effects = len(cues) + len(audio_clips)
        print(f'{a.out}: {total_effects} effects, {i:.1f} LUFS, true peak {tp:.1f} dBTP, LRA {lra:.1f} LU')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
