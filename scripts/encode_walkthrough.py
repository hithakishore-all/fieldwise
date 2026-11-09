"""Encode recorded walkthrough frames into a 30 fps H.264 MP4 and a poster image.

    python scripts/encode_walkthrough.py REC_DIR OUT.mp4 POSTER.jpg
"""
import json
import os
import subprocess
import sys
from pathlib import Path

rec, out, poster = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
t = json.loads((rec / "timeline.json").read_text())
starts = [e[1] for e in t["events"] if e[0] == "start"]
ends = [e[1] for e in t["events"] if e[0] == "end"]
lines = ["ffconcat version 1.0"]
last = None
for s, e in zip(starts, ends):
    seg = sorted((tm, p) for p, tm in t["frames"] if s <= tm <= e)
    for i, (tm, p) in enumerate(seg):
        nxt = seg[i + 1][0] if i + 1 < len(seg) else e
        lines += [f"file '{p}'", f"duration {max(nxt - tm, 0.001):.4f}"]
        last = p
lines.append(f"file '{last}'")
lst = rec / "frames.ffconcat"
lst.write_text("\n".join(lines) + "\n")
tmp = out.with_name(out.stem + ".part.mp4")
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-movflags", "+faststart", "-an", str(tmp)], check=True)
os.replace(tmp, out)
first = json.loads((rec / "chapters.json").read_text())
poster_t = next((c["t"] + 3.5 for c in first if c["title"].startswith("Now: cited")), 45)
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{poster_t:.2f}", "-i", str(out), "-frames:v", "1", "-q:v", "3",
                str(poster)], check=True)
print("wrote", out, out.stat().st_size // 1024, "KB")
