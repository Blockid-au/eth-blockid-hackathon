#!/usr/bin/env python3
"""Build the narrated 3-minute pitch video from the 3-minute deck.

Inputs (this folder):  slides/slide-N.png (1920x1080, rendered from docs/pitch/out/*.pdf with pdftoppm),
                       narration.tsv (slide, planned slot s, voice-over text),
                       audio/sN.mp3 + audio/sN.vtt (edge-tts, voice en-AU-WilliamMultilingualNeural, rate -4%).
Outputs (docs/video/): blockid-startup-passport-pitch-3min.mp4 (+ a burned-subtitle variant) and .srt

Each slide stays on screen for LEAD + narration + TAIL seconds; slides cross-fade (XF s). Needs Docker
(jrottenberg/ffmpeg). Regenerate audio first — see README section in docs/video/pitch3/README.md.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
NAME = "blockid-startup-passport-pitch-3min"
LEAD, TAIL, XF, END_HOLD = 0.7, 1.2, 0.5, 2.5
FFMPEG = ["sudo", "docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{OUT}:/w",
          "jrottenberg/ffmpeg:6.1-alpine"]


def probe(path: Path) -> float:
    out = subprocess.run(FFMPEG[:-1] + ["--entrypoint", "ffprobe", FFMPEG[-1], "-v", "error", "-show_entries",
                                         "format=duration", "-of", "csv=p=0", "/w/" + str(path.relative_to(OUT))],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def srt_time(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def parse_cues(text: str) -> list[tuple[float, float, str]]:
    def sec(s: str) -> float:
        h, m, rest = s.replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [x for x in block.splitlines() if x.strip() and not x.startswith("WEBVTT")]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = [x.strip() for x in line.split("-->")]
                cues.append((sec(a), sec(b.split()[0]), " ".join(lines[i + 1:])))
                break
    return cues


def main() -> None:
    rows = [line.split("\t") for line in (HERE / "narration.tsv").read_text().splitlines() if line.strip()]
    n = len(rows)
    audio = [HERE / "audio" / f"s{r[0]}.mp3" for r in rows]
    dur_a = [probe(a) for a in audio]
    dur = [LEAD + d + TAIL + (END_HOLD if i == n - 1 else 0) for i, d in enumerate(dur_a)]
    starts = [sum(dur[:i]) - XF * i for i in range(n)]  # when each slide becomes fully visible
    total = sum(dur) - XF * (n - 1)

    # subtitles: shift each slide's cues by its start + LEAD
    srt, k = [], 1
    for i, r in enumerate(rows):
        for a, b, t in parse_cues((HERE / "audio" / f"s{r[0]}.vtt").read_text()):
            srt.append(f"{k}\n{srt_time(starts[i] + LEAD + a)} --> {srt_time(starts[i] + LEAD + b)}\n{t}\n")
            k += 1
    (OUT / f"{NAME}.srt").write_text("\n".join(srt))

    inputs = []
    for i, r in enumerate(rows):
        inputs += ["-loop", "1", "-t", f"{dur[i]:.3f}", "-i", f"/w/pitch3/slides/slide-{r[0]}.png"]
    for a in audio:
        inputs += ["-i", "/w/" + str(a.relative_to(OUT))]
    f, prev, off = [], "0:v", 0.0
    for i in range(1, n):
        off += dur[i - 1] - XF
        f.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}[v{i}]")
        prev = f"v{i}"
    f.append(f"[{prev}]format=yuv420p[vout]")
    for i in range(n):
        ms = round((starts[i] + LEAD) * 1000)
        f.append(f"[{n + i}:a]adelay={ms}|{ms},aresample=48000[a{i}]")
    f.append("".join(f"[a{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,apad,atrim=0:{total:.3f}[aout]")
    graph = ";".join(f)

    base = ["-y", "-loglevel", "error"] + inputs + ["-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
                                                    "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                                                    "-tune", "stillimage", "-c:a", "aac", "-b:a", "160k",
                                                    "-movflags", "+faststart", "-t", f"{total:.3f}"]
    subprocess.run(FFMPEG + base + [f"/w/{NAME}.mp4"], check=True)
    # burned-in captions for platforms that ignore .srt files
    subprocess.run(FFMPEG + ["-y", "-loglevel", "error", "-i", f"/w/{NAME}.mp4", "-vf",
                             f"subtitles=/w/{NAME}.srt:force_style='FontName=DejaVu Sans,FontSize=12,"
                             "PrimaryColour=&H00FFFFFF,BackColour=&H99000000,BorderStyle=4,Outline=0,Shadow=0,"
                             "MarginV=8'", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy",
                             "-movflags", "+faststart", f"/w/{NAME}-captions.mp4"], check=True)
    for i, r in enumerate(rows):
        print(f"slide {r[0]}: {starts[i]:6.1f}s  on screen {dur[i]:5.1f}s  (planned {r[1]}s, voice {dur_a[i]:.1f}s)")
    print(f"total {total:.1f}s = {int(total // 60)}:{total % 60:04.1f}")


if __name__ == "__main__":
    main()
