# 3-minute pitch video

Narrated video of the 3-minute deck (`docs/pitch/build3.js`), 1920×1080, 2:56, English voice-over
(edge-tts `en-AU-WilliamMultilingualNeural`, rate −4%), loudness-normalised to −16 LUFS.

| File | Use |
|---|---|
| `../blockid-startup-passport-pitch-3min.mp4` | upload (clean video) — also https://eth.blockid.au/deck/blockid-startup-passport-pitch-3min.mp4 |
| `../blockid-startup-passport-pitch-3min-captions.mp4` | upload where `.srt` is not supported (captions burned in) |
| `../blockid-startup-passport-pitch-3min.srt` | caption track for YouTube / Devfolio / Vimeo |

## Rebuild

```bash
# 1. deck -> PDF -> slide PNGs (copy the screenshots the deck uses into docs/pitch/img/ first, see build3.js)
cd docs/pitch && sudo docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -v ~/blockid-eth-platform:/r \
  -w /r/docs/pitch node:20 node build3.js
cd out && soffice --headless --convert-to pdf BlockID-Startup-Passport-3min.pptx
pdftoppm -png -scale-to-x 1920 -scale-to-y 1080 BlockID-Startup-Passport-3min.pdf ../../video/pitch3/slides/slide
# 2. voice-over from narration.tsv (slide, planned seconds, text)
cd ../../video/pitch3 && while IFS=$'\t' read n slot text; do
  edge-tts --voice en-AU-WilliamMultilingualNeural --rate=-4% --text "$text" \
    --write-media audio/s$n.mp3 --write-subtitles audio/s$n.vtt; done < narration.tsv
# 3. video (Docker ffmpeg): cross-fades, voice placed per slide, captions, burned-caption variant
python3 build.py
```

Update the live numbers on slide 7 (`build3.js` and `narration.tsv`) from
`GET https://eth.blockid.au/api/v1/platform/stats` before rebuilding.
