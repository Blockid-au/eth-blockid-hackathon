#!/usr/bin/env python3
"""Build the full demo video (EAG online round): slides + live screen recordings + English voice-over.

  python3 build.py --durations   # audio lengths -> durations.json (read by record.mjs)
  node record.mjs                # (in the Playwright container) frames -> clips/<id>/
  python3 build.py               # clips -> mp4, then the final video, .srt and a burned-caption variant

Inputs: narration.tsv (id, slide:<name> | rec:<name>, text), audio/<id>.mp3 + .vtt (edge-tts),
slides/slide-<name>.png, clips/<id>/*.jpg + frames.json. Needs Pillow (labels) and Docker (jrottenberg/ffmpeg).
Outputs (docs/video/): blockid-business-passport-full-demo.mp4, -captions.mp4, .srt
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
CUT = os.environ.get("CUT", "full")  # "full" (4:46) or "3min"
SFX = "" if CUT == "full" else "-" + CUT
NAME = "blockid-business-passport-full-demo" if CUT == "full" else f"blockid-business-passport-demo-{CUT}"
LEAD, TAIL, XF, END_HOLD, FPS = 0.6, 0.7, 0.4, 2.5, 30
FFMPEG = ["sudo", "docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{OUT}:/w",
          "-v", "/usr/share/fonts/truetype/liberation:/fonts:ro",
          "jrottenberg/ffmpeg:6.1-alpine"]
# on-screen message for each recorded scene: (feature label, the one line a muted viewer should take away)
HEADS = {
    "r01": ("Investor portal · live on testnet", "Every holding at its approved value. Dividends already in the wallet."),
    "r02": ("One holding", "Your stake, a checked price, and the same update as every investor."),
    "r03": ("For businesses", "Paste a website. Get an evidence-based valuation in minutes."),
    "r04": ("AI research", "AI agents research the business. They hold no keys, they only propose."),
    "r05": ("Valuation report", "Grade A–E and a value range. Every number links to its source."),
    "r06": ("Human approval", "Nothing reaches the chain until a person approves it."),
    "r07": ("Share register on blockchain", "Ownership read straight from the chain, not from a spreadsheet."),
    "r08": ("Offerings and dividends", "Dilution shown before new shares. Dividends to every wallet, no gas."),
    "r09": ("Check it yourself", "Your browser checks 3 blockchains. Change one number: it turns red."),
    "r10": ("HashKey Chain", "On-chain proof of which agent proposed and which person approved."),
    "r11": ("BlockID HR · founding team", "Know the people: each claim checked against public sources."),
}


def w(p: Path) -> str:
    return "/w/" + str(p.relative_to(OUT))


def probe(path: Path) -> float:
    out = subprocess.run(FFMPEG[:-1] + ["--entrypoint", "ffprobe", FFMPEG[-1], "-v", "error", "-show_entries",
                                         "format=duration", "-of", "csv=p=0", w(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def ff(*args: str) -> None:
    subprocess.run(FFMPEG + ["-hide_banner", "-loglevel", "error", "-y", *args], check=True)


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


def split_cue(a: float, b: float, text: str, max_words: int = 12) -> list[tuple[float, float, str]]:
    """Split a sentence-long cue into short chunks (prefer breaks after punctuation); time shared by length."""
    words, chunks, cur = text.split(), [], []
    for i, wd in enumerate(words):
        cur.append(wd)
        rest = len(words) - i - 1
        if len(cur) >= max_words or (len(cur) >= 5 and wd[-1] in ",.:;?!" and rest >= 3):
            chunks.append(" ".join(cur)); cur = []
    if cur:
        if chunks and len(cur) < 3:
            chunks[-1] += " " + " ".join(cur)
        else:
            chunks.append(" ".join(cur))
    total = sum(len(c) for c in chunks)
    out, t = [], a
    for c in chunks:
        d = (b - a) * len(c) / total
        out.append((t, t + d, c)); t += d
    return out


def rows() -> list[list[str]]:
    return [line.split("\t") for line in (HERE / f"narration{SFX}.tsv").read_text().splitlines() if line.strip()]


def durations() -> dict[str, float]:
    rs = rows()
    d = {}
    for i, r in enumerate(rs):
        d[r[0]] = LEAD + probe(HERE / f"audio{SFX}" / f"{r[0]}.mp3") + TAIL + (END_HOLD if i == len(rs) - 1 else 0)
    return d


def band_png(cid: str, path: Path) -> None:
    """1920x1080 frame overlay: dark surround + bottom message band (recording sits in a 1536x864 window above)."""
    from PIL import Image, ImageDraw, ImageFont
    lab, msg = HEADS.get(cid, (cid, ""))
    bold = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    im = Image.new("RGBA", (1920, 1080), (10, 19, 17, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((192, 24, 192 + 1536 - 1, 24 + 864 - 1), fill=(0, 0, 0, 0))  # window for the recording
    d.rounded_rectangle((188, 20, 192 + 1536 + 3, 24 + 864 + 3), radius=10, outline=(37, 64, 58, 255), width=4)
    d.rectangle((192, 24, 192 + 1536 - 1, 24 + 864 - 1), fill=(0, 0, 0, 0))
    fl, fm, fb = ImageFont.truetype(bold, 26), ImageFont.truetype(bold, 46), ImageFont.truetype(bold, 22)
    d.ellipse((192, 919, 210, 937), fill=(127, 224, 194, 255))
    d.text((224, 912), lab.upper(), font=fl, fill=(34, 160, 127, 255))
    size = 46
    while d.textlength(msg, font=fm) > 1536 and size > 30:
        size -= 2; fm = ImageFont.truetype(bold, size)
    d.text((192, 958), msg, font=fm, fill=(242, 247, 245, 255))
    brand = "BlockID Business Passport  ·  eth.blockid.au"
    d.text((192 + 1536 - d.textlength(brand, font=fb), 914), brand, font=fb, fill=(126, 148, 143, 255))
    im.save(path)


def render_clip(cid: str, dur: float) -> Path:
    """Frames (variable timing) -> constant-fps mp4 of exactly dur seconds, framed above the message band."""
    d = HERE / f"clips{SFX}" / cid
    meta = json.loads((d / "frames.json").read_text())
    frames = meta["frames"]
    lines = []
    for i, (name, t) in enumerate(frames):
        nxt = frames[i + 1][1] if i + 1 < len(frames) else dur
        if t >= dur:
            break
        lines += [f"file '{name}'", f"duration {max(0.001, min(nxt, dur) - t):.4f}"]
    lines.append(f"file '{frames[min(len(frames), len(lines) // 2) - 1][0]}'")
    (d / "list.txt").write_text("\n".join(lines) + "\n")
    lab = HERE / f"clips{SFX}" / f"{cid}-band.png"
    band_png(cid, lab)
    out = HERE / f"clips{SFX}" / f"{cid}.mp4"
    ff("-f", "concat", "-safe", "0", "-i", w(d / "list.txt"), "-i", w(lab),
       "-filter_complex", f"[0:v]scale=1536:864:flags=lanczos,setsar=1,fps={FPS},tpad=stop_mode=clone:stop_duration=30,"
       f"trim=duration={dur:.3f},pad=1920:1080:192:24:color=0x0A1311[b];[b][1:v]overlay=0:0:format=auto,format=yuv420p[v]",
       "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS), w(out))
    return out


def main() -> None:
    if "--durations" in sys.argv:
        d = durations()
        (HERE / f"durations{SFX}.json").write_text(json.dumps({k: round(v, 3) for k, v in d.items()}, indent=1))
        print(json.dumps(d, indent=1), "total", round(sum(d.values()) - XF * (len(d) - 1), 1))
        return
    rs = rows()
    dur = durations()
    n = len(rs)
    seg = []
    for r in rs:
        kind, name = r[1].split(":")
        if kind == "rec":
            seg.append(HERE / f"clips{SFX}" / f"{r[0]}.mp4" if "--captions-only" in sys.argv else render_clip(r[0], dur[r[0]]))
        else:
            seg.append(HERE / "slides" / f"slide-{name}.png")
    D = [dur[r[0]] for r in rs]
    starts = [sum(D[:i]) - XF * i for i in range(n)]
    total = sum(D) - XF * (n - 1)

    srt, k = [], 1
    for i, r in enumerate(rs):
        for a0, b0, t0 in parse_cues((HERE / f"audio{SFX}" / f"{r[0]}.vtt").read_text()):
          for a, b, t in split_cue(a0, b0, t0):
            srt.append(f"{k}\n{srt_time(starts[i] + LEAD + a)} --> {srt_time(starts[i] + LEAD + b)}\n{t}\n")
            k += 1
    (OUT / f"{NAME}.srt").write_text("\n".join(srt))

    inputs = []
    for i, s in enumerate(seg):
        if s.suffix == ".png":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D[i]:.3f}", "-i", w(s)]
        else:
            inputs += ["-i", w(s)]
    for r in rs:
        inputs += ["-i", w(HERE / f"audio{SFX}" / f"{r[0]}.mp3")]
    f = [f"[{i}:v]scale=1920:1080,setsar=1,fps={FPS},format=yuv420p[s{i}]" for i in range(n)]
    prev, off = "s0", 0.0
    for i in range(1, n):
        off += D[i - 1] - XF
        f.append(f"[{prev}][s{i}]xfade=transition=fade:duration={XF}:offset={off:.3f}[v{i}]")
        prev = f"v{i}"
    f.append(f"[{prev}]fade=t=out:st={total - 1.2:.3f}:d=1.2[vout]")
    for i in range(n):
        ms = round((starts[i] + LEAD) * 1000)
        f.append(f"[{n + i}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
    f.append("".join(f"[a{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,"
             f"atrim=0:{total:.3f}[aout]")
    clean = OUT / f"{NAME}.mp4"
    if "--captions-only" not in sys.argv:
      ff(*inputs, "-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset",
       "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
       "-movflags", "+faststart", w(clean))
    style = ("FontName=Liberation Sans,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,"
             "BackColour=&H99000000,BorderStyle=4,Outline=1,Shadow=0,MarginV=56,MarginL=40,MarginR=40")
    ff("-i", w(clean), "-vf", f"subtitles=/w/{NAME}.srt:fontsdir=/fonts:force_style='{style}'", "-c:v", "libx264", "-preset",
       "medium", "-crf", "19", "-c:a", "copy", "-movflags", "+faststart", w(OUT / f"{NAME}-captions.mp4"))
    print("total", round(total, 1), "s ->", clean)


if __name__ == "__main__":
    main()
