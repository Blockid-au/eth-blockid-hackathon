#!/usr/bin/env python3
"""
Generate official BlockID logo assets across the repository from the uploaded source logo.
Produces:
- Master official logos in docs/images/ and docs/pitch/img/
- Web app public assets in web/app/public/ (favicons, icons, og:image, PWA icons)
- Blockscout explorer assets in deploy/vm-app/chain/explorer/logos/ and web/app/public/logos/
- Scalable SVG vector versions of the logo and emblem
"""

import os
from pathlib import Path
from PIL import Image, ImageFilter
import numpy as np

REPO_ROOT = Path("/home/dovanlong/blockid-eth-platform")
SRC_PATH = Path("/home/dovanlong/.gemini/antigravity-ide/brain/be468578-ea38-45d5-8460-547ca17062d2/.user_uploaded/media_1790483887317.png")

def make_transparent(im_rgb, bg_diff_thresh=18.0, full_diff_thresh=52.0):
    """
    Cleanly converts near-white background to transparent alpha without edge halo.
    """
    rgba = im_rgb.convert("RGBA")
    arr = np.array(rgba, dtype=np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    # Max difference from pure white (255, 255, 255)
    diff = np.maximum(255.0 - r, np.maximum(255.0 - g, 255.0 - b))
    alpha = np.clip((diff - bg_diff_thresh) / (full_diff_thresh - bg_diff_thresh), 0.0, 1.0) * 255.0

    # De-multiply white from foreground to prevent white halos on dark backgrounds
    a_norm = np.clip(alpha / 255.0, 1e-4, 1.0)
    new_r = np.clip((r - (1.0 - a_norm) * 255.0) / a_norm, 0, 255)
    new_g = np.clip((g - (1.0 - a_norm) * 255.0) / a_norm, 0, 255)
    new_b = np.clip((b - (1.0 - a_norm) * 255.0) / a_norm, 0, 255)

    out_arr = np.stack([new_r, new_g, new_b, alpha], axis=-1).astype(np.uint8)
    return Image.fromarray(out_arr, "RGBA")


def generate_svg_emblem(filename):
    """
    Generates a crisp, precision SVG of the BlockID emblem mark (octagon + glowing diamond star).
    """
    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" fill="none">
  <defs>
    <linearGradient id="starGlow" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#00A3FF" />
      <stop offset="45%" stop-color="#0080FF" />
      <stop offset="100%" stop-color="#0040D0" />
    </linearGradient>
    <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="2" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>
  <!-- Octagon outer frame -->
  <polygon points="76,16 164,16 224,76 224,164 164,224 76,224 16,164 16,76"
           stroke="#002B7F" stroke-width="13" stroke-linejoin="round" fill="none" />
  <!-- Luminous 4-point star astroid -->
  <path d="M 120,48
           C 120,90 150,120 192,120
           C 150,120 120,150 120,192
           C 120,150 90,120 48,120
           C 90,120 120,90 120,48 Z"
        stroke="url(#starGlow)" stroke-width="12" stroke-linejoin="round" fill="none" />
</svg>
"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(svg_content.strip() + "\n")


def generate_svg_favicon(filename):
    """
    Favicon SVG adapted for both light and dark browser tabs.
    """
    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="starGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#00C0FF" />
      <stop offset="50%" stop-color="#0077FE" />
      <stop offset="100%" stop-color="#0040D0" />
    </linearGradient>
    <style>
      .oct { stroke: #002B7F; }
      @media (prefers-color-scheme: dark) {
        .oct { stroke: #4F80E2; }
      }
    </style>
  </defs>
  <!-- Background disc for perfect contrast in all environments -->
  <rect width="256" height="256" rx="56" fill="#FFFFFF" fill-opacity="0.08" />
  <!-- Octagon outer frame -->
  <polygon class="oct" points="80,24 176,24 232,80 232,176 176,232 80,232 24,176 24,80"
           stroke-width="16" stroke-linejoin="round" fill="none" />
  <!-- Star -->
  <path d="M 128,54
           C 128,98 158,128 202,128
           C 158,128 128,158 128,202
           C 128,158 98,128 54,128
           C 98,128 128,98 128,54 Z"
        stroke="url(#starGrad)" stroke-width="15" stroke-linejoin="round" fill="none" />
</svg>
"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(svg_content.strip() + "\n")


def main():
    print(f"Loading source logo from {SRC_PATH}...")
    orig = Image.open(SRC_PATH).convert("RGBA")
    w_orig, h_orig = orig.size

    # Prepare directories
    (REPO_ROOT / "docs/images").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "docs/pitch/img").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "web/app/public/logos").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "deploy/vm-app/chain/explorer/logos").mkdir(parents=True, exist_ok=True)

    # 1. Precise crops
    # Emblem center: cx = 167.5, cy = 276.0, radius ~93px
    cx, cy = 167.5, 276.0
    half = 105
    emblem_raw = orig.crop((int(round(cx - half)), int(round(cy - half)), int(round(cx + half)), int(round(cy + half))))
    emblem_trans = make_transparent(emblem_raw)

    # Full logo content tight box: [75, 185, 957, 383] (w=883, h=199)
    # Add comfortable margin
    full_crop = orig.crop((60, 170, 972, 398)) # 912 x 228
    full_trans = make_transparent(full_crop)

    # 2. Master square logo (1024x1024) with pure white background
    # Centered full logo with balanced proportions
    logo_sq = Image.new("RGBA", (1024, 1024), (255, 255, 255, 255))
    # Scale full_crop to fit nicely inside 1024x1024 (e.g. width ~ 900px)
    scale_w = 900
    scale_h = int(round(full_crop.height * (scale_w / full_crop.width)))
    full_resized = full_crop.resize((scale_w, scale_h), Image.Resampling.LANCZOS)
    pos_x = (1024 - scale_w) // 2
    pos_y = (1024 - scale_h) // 2
    logo_sq.paste(full_resized, (pos_x, pos_y), full_resized)

    # 3. Master square emblem mark (1024x1024)
    mark_sq = Image.new("RGBA", (1024, 1024), (255, 255, 255, 255))
    emblem_800 = emblem_raw.resize((820, 820), Image.Resampling.LANCZOS)
    mark_sq.paste(emblem_800, ((1024 - 820) // 2, (1024 - 820) // 2), emblem_800)

    # 4. Master square emblem transparent (1024x1024)
    mark_trans_sq = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    emblem_trans_800 = emblem_trans.resize((820, 820), Image.Resampling.LANCZOS)
    mark_trans_sq.paste(emblem_trans_800, ((1024 - 820) // 2, (1024 - 820) // 2), emblem_trans_800)

    # 5. OpenGraph banner (1200x630) on clean white
    og_im = Image.new("RGBA", (1200, 630), (255, 255, 255, 255))
    og_scale_w = 980
    og_scale_h = int(round(full_crop.height * (og_scale_w / full_crop.width)))
    og_resized = full_crop.resize((og_scale_w, og_scale_h), Image.Resampling.LANCZOS)
    og_im.paste(og_resized, ((1200 - og_scale_w) // 2, (630 - og_scale_h) // 2), og_resized)

    # Save to docs/images/
    print("Saving docs/images assets...")
    logo_sq.save(REPO_ROOT / "docs/images/logo.png", "PNG", optimize=True)
    mark_sq.save(REPO_ROOT / "docs/images/logo-mark.png", "PNG", optimize=True)
    mark_trans_sq.save(REPO_ROOT / "docs/images/logo-mark-transparent.png", "PNG", optimize=True)
    full_trans.save(REPO_ROOT / "docs/images/logo-transparent.png", "PNG", optimize=True)
    og_im.save(REPO_ROOT / "docs/images/logo-horizontal.png", "PNG", optimize=True)

    # Save to docs/pitch/img/
    print("Saving docs/pitch/img assets...")
    logo_sq.save(REPO_ROOT / "docs/pitch/img/logo.png", "PNG", optimize=True)

    # Save to web/app/public/
    print("Saving web/app/public assets...")
    og_im.save(REPO_ROOT / "web/app/public/logo.png", "PNG", optimize=True) # 1200x630 for og:image
    full_trans.save(REPO_ROOT / "web/app/public/logo-transparent.png", "PNG", optimize=True)
    
    # Square emblem (512x512)
    emblem_512 = emblem_raw.resize((512, 512), Image.Resampling.LANCZOS)
    emblem_512.save(REPO_ROOT / "web/app/public/logo-mark.png", "PNG", optimize=True)
    emblem_trans_512 = emblem_trans.resize((512, 512), Image.Resampling.LANCZOS)
    emblem_trans_512.save(REPO_ROOT / "web/app/public/logo-mark-transparent.png", "PNG", optimize=True)

    # Apple touch icon (180x180) with clean white background and rounded aesthetic
    apple_icon = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    emblem_156 = emblem_raw.resize((156, 156), Image.Resampling.LANCZOS)
    apple_icon.paste(emblem_156, (12, 12), emblem_156)
    apple_icon.save(REPO_ROOT / "web/app/public/apple-touch-icon.png", "PNG", optimize=True)

    # Favicon PNGs (32x32, 16x16, 48x48)
    fav_32 = emblem_raw.resize((32, 32), Image.Resampling.LANCZOS)
    fav_32.save(REPO_ROOT / "web/app/public/favicon-32x32.png", "PNG", optimize=True)
    fav_16 = emblem_raw.resize((16, 16), Image.Resampling.LANCZOS)
    fav_16.save(REPO_ROOT / "web/app/public/favicon-16x16.png", "PNG", optimize=True)
    fav_48 = emblem_raw.resize((48, 48), Image.Resampling.LANCZOS)

    # Multi-size favicon.ico
    fav_32.save(
        REPO_ROOT / "web/app/public/favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[fav_16, fav_48]
    )

    # Explorer logo
    emblem_512.save(REPO_ROOT / "web/app/public/logos/blockid.png", "PNG", optimize=True)
    emblem_512.save(REPO_ROOT / "deploy/vm-app/chain/explorer/logos/blockid.png", "PNG", optimize=True)

    # Vector SVGs
    print("Generating vector SVGs...")
    generate_svg_emblem(REPO_ROOT / "docs/images/logo-mark.svg")
    generate_svg_emblem(REPO_ROOT / "web/app/public/logo-mark.svg")
    generate_svg_favicon(REPO_ROOT / "web/app/public/favicon.svg")

    print("All official BlockID logo assets successfully generated!")

if __name__ == "__main__":
    main()
