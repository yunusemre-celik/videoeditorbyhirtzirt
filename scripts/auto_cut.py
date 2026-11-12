#!/usr/bin/env python3
"""Auto-cut EDL generator: builds work/edl.json from transcripts and silence detection.

Automatically assembles an initial edit list (work/edl.json) from all Whisper transcripts
found in work/transcripts/*.json. Supports optional auto-editor CLI refinement if installed.

usage:
  python3 scripts/auto_cut.py --project . --pace tight --fps 30
  python3 scripts/auto_cut.py --project . --use-auto-editor
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_json, project_paths, save_json  # noqa: E402


def generate_edl_from_transcripts(project: str, pace: str = "tight", fps: int = 30, use_auto_editor: bool = False) -> dict:
    """Build work/edl.json from transcripts in work/transcripts/*.json.

    Optionally refines silence regions via auto-editor CLI if installed and use_auto_editor is True.
    """
    root, work = project_paths(project)
    clips_path = os.path.join(work, "clips.json")
    clips = dict(load_json(clips_path)) if os.path.exists(clips_path) else {}

    t_pattern = os.path.join(work, "transcripts", "*.json")
    t_files = sorted(glob.glob(t_pattern))

    items = []
    for tf in t_files:
        t_data = load_json(tf)
        cid = t_data.get("clip") or os.path.splitext(os.path.basename(tf))[0]
        if cid not in clips:
            if t_data.get("src"):
                clips[cid] = t_data["src"]
            else:
                clips[cid] = f"src/{cid}.mp4"

        auto_editor_ranges = None
        if use_auto_editor and shutil.which("auto-editor"):
            src_val = clips.get(cid, "")
            src_path = os.path.join(root, src_val) if not os.path.isabs(src_val) else src_val
            if os.path.exists(src_path):
                ae_out = os.path.join(work, f"_ae_{cid}.json")
                try:
                    subprocess.run(
                        ["auto-editor", src_path, "--export", "json", "-o", ae_out, "--silent"],
                        capture_output=True,
                        check=True,
                    )
                    if os.path.exists(ae_out):
                        ae_data = load_json(ae_out)
                        if "chunks" in ae_data:
                            auto_editor_ranges = [
                                [round(c[0] / fps, 3), round(c[1] / fps, 3)]
                                for c in ae_data["chunks"]
                                if len(c) >= 3 and c[2] == 1.0 and c[1] > c[0]
                            ]
                        os.remove(ae_out)
                except Exception as e:
                    print(f"auto-editor notice for {cid}: {e}")

        if auto_editor_ranges:
            for r in auto_editor_ranges:
                items.append({"clip": cid, "range": r})
        else:
            utts = t_data.get("utterances", [])
            if utts:
                for u_idx in range(len(utts)):
                    items.append({"clip": cid, "utt": u_idx})
            elif "regions" in t_data and t_data["regions"]:
                for reg in t_data["regions"]:
                    items.append({"clip": cid, "range": reg})

    if clips:
        save_json(clips_path, clips)

    edl = {
        "fps": int(fps),
        "pace": pace,
        "clips": clips,
        "items": items,
    }
    edl_path = os.path.join(work, "edl.json")
    save_json(edl_path, edl)
    return edl


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".", help="Project path")
    ap.add_argument("--pace", choices=["natural", "tight"], default="tight", help="Pace preset")
    ap.add_argument("--fps", type=int, default=30, help="Frame rate")
    ap.add_argument("--use-auto-editor", action="store_true", help="Use auto-editor CLI if installed")
    args = ap.parse_args()

    edl = generate_edl_from_transcripts(args.project, pace=args.pace, fps=args.fps, use_auto_editor=args.use_auto_editor)
    print(f"Generated work/edl.json with {len(edl['items'])} items across {len(edl['clips'])} clips (pace: {edl['pace']}).")


if __name__ == "__main__":
    main()
