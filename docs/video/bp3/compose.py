#!/usr/bin/env python3
"""Screenshot scenes in the deck's style (1920x1080): eyebrow, title, a real screenshot of the live app, footer.
Needs Pillow. Writes slides/slide-<id>.png next to the deck slides rendered by pdftoppm."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent.parent
BG, TEAL, WHITE, MUTED, FRAME = (10, 19, 17), (38, 166, 128), (240, 244, 242), (150, 165, 160), (30, 64, 54)
BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"
SCENES = [  # id, eyebrow, title, screenshot, crop height as share of width (None = whole image)
    ("1b", "LIVE APP · TRY IT NOW", "No sign-up. You start as a demo investor.", "pitch/img/bp-hero.png", None),
    ("4b", "LIVE APP · UNDERSTAND IT", "Agents research. Code does the maths. A person approves.",
     "screenshots/08-valuation-agent-log.png", None),
    ("5b", "LIVE APP · OWN IT", "Every holder, wallet and share count, read from the chain.",
     "pitch/img/bp-captable.png", 0.47),
]


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype(BOLD, size)


def scene(sid, eyebrow, title, shot, crop):
    im = Image.new("RGB", (1920, 1080), BG)
    d = ImageDraw.Draw(im)
    x = 80
    for ch in eyebrow:  # letter-spaced eyebrow like the deck
        d.text((x, 60), ch, font=font(BOLD, 24), fill=TEAL)
        x += d.textlength(ch, font=font(BOLD, 24)) + 7
    d.text((80, 120), title, font=font(BOLD, 60), fill=WHITE)
    d.text((1840, 1058), "eth.blockid.au  ·  Testnet demo. Not an offer of securities or financial advice.",
           font=font(REG, 22), fill=MUTED, anchor="rs")
    src = Image.open(DOCS / shot).convert("RGB")
    if crop:
        src = src.crop((0, 0, src.width, int(src.width * crop)))
    box_w, box_h = 1760, 760
    s = min(box_w / src.width, box_h / src.height)
    src = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
    ox, oy = (1920 - src.width) // 2, 225 + (box_h - src.height) // 2
    d.rounded_rectangle((ox - 8, oy - 8, ox + src.width + 8, oy + src.height + 8), 14, fill=FRAME)
    im.paste(src, (ox, oy))
    im.save(HERE / "slides" / f"slide-{sid}.png")


if __name__ == "__main__":
    for s in SCENES:
        scene(*s)
        print("slide-" + s[0])
