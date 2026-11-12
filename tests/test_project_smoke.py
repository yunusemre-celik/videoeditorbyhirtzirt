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
