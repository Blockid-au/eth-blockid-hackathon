# Business Passport video (3 min)

Narrated video of the 9-slide Business Passport deck (`docs/pitch/build-bp.js`) plus three live-app screenshot
scenes (`compose.py`: try it now, AI agents at work, cap table). 1920×1080, 2:59.8, English voice-over (edge-tts
`en-AU-WilliamMultilingualNeural`, rate +7%), loudness-normalised to −16 LUFS.

| File | Use |
|---|---|
| `../blockid-business-passport-3min.mp4` | clean video — https://eth.blockid.au/deck/blockid-business-passport-3min.mp4 |
| `../blockid-business-passport-3min-captions.mp4` | captions burned in (Devfolio) — https://eth.blockid.au/deck/blockid-business-passport-3min-captions.mp4 |
| `../blockid-business-passport-3min.srt` | caption track |

## Rebuild

```bash
cd docs/video/bp3
pdftoppm -png -scale-to-x 1920 -scale-to-y 1080 ../../pitch/BlockID-Business-Passport-3min.pdf slides/slide
python compose.py            # needs Pillow; writes slides/slide-1b.png, -4b, -5b
while IFS=$'\t' read n slot text; do
  edge-tts --voice en-AU-WilliamMultilingualNeural --rate=+7% --text "$text" \
    --write-media audio/s$n.mp3 --write-subtitles audio/s$n.vtt; done < narration.tsv
python3 build.py             # Docker ffmpeg: cross-fades, voice per scene, .srt, burned-caption variant
cp ../blockid-business-passport-3min* ../../../web/app/public/deck/
```
