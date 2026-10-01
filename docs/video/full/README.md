# Demo videos: full (4:46) and 3-minute cut

Two cuts from one pipeline. Pick the cut with `CUT=full` (default) or `CUT=3min`:

| Cut | Narration | Audio · clips | Output |
|---|---|---|---|
| full, 4:46 | `narration.tsv` (17 scenes, edge-tts rate +5 %) | `audio/` · `clips/` | `blockid-business-passport-full-demo*.mp4` |
| 3 min, 2:45 (for "max 3 minutes" rules) | `narration-3min.tsv` (16 scenes, rate +0 %) | `audio-3min/` · `clips-3min/` | `blockid-business-passport-demo-3min*.mp4` · https://eth.blockid.au/deck/blockid-business-passport-demo-3min-captions.mp4 |

The 3-minute cut replays the same recorded actions faster (each scene's speed = its length ÷ the full cut's).

## Full cut (EAG Global Buildathon, online round)

About 4:45, 1920×1080. It covers what the organisers asked for: the core features, the user flow (investor and
business), the technical highlights and the current progress. It mixes deck slides, two new slides (`slides/progress.html`,
`slides/close.html`) and live screen recordings of https://eth.blockid.au and https://hr.blockid.au (testnet, sample
data). The voice-over is English (edge-tts `en-AU-WilliamMultilingualNeural`, rate +5 %), normalised to −16 LUFS.

| File | Use |
|---|---|
| `../blockid-business-passport-full-demo.mp4` | clean video: https://eth.blockid.au/deck/blockid-business-passport-full-demo.mp4 |
| `../blockid-business-passport-full-demo-captions.mp4` | captions burned in (Devfolio): https://eth.blockid.au/deck/blockid-business-passport-full-demo-captions.mp4 |
| `../blockid-business-passport-full-demo.srt` | caption track (YouTube upload) |

Scenes: `narration.tsv` (id, `slide:<name>` or `rec:<name>`, text). Recordings: `record.mjs` (Playwright and a CDP
screencast; a visible cursor is injected; the admin scene signs in with the public demo admin account).

## Rebuild

```bash
cd docs/video/full
while IFS=$'\t' read n slot text; do
  edge-tts --voice en-AU-WilliamMultilingualNeural --rate=+5% --text "$text" \
    --write-media audio/$n.mp3 --write-subtitles audio/$n.vtt; done < narration.tsv
python3 build.py --durations                       # needs Pillow; writes durations.json
sudo docker run --rm --network host --ipc host -v $PWD:/w \
  -v $PWD/../../../scripts/screenshots/node_modules:/w/node_modules -w /w \
  mcr.microsoft.com/playwright:v1.63.0-noble node record.mjs      # or: node record.mjs r05 r09
sudo chown -R $(id -u):$(id -g) clips
python3 build.py                                   # Docker ffmpeg -> ../blockid-business-passport-full-demo*.mp4
cp ../blockid-business-passport-full-demo* ../../../web/app/public/deck/
```

3-minute cut: same steps with `CUT=3min` (`--rate=+0%`, `narration-3min.tsv`, `audio-3min/`; pass `-e CUT=3min`
to the Playwright container; copy `../blockid-business-passport-demo-3min*`).

`slides/slide-{1,2,3,8}.png` come from `../bp3/slides` (the 3-minute deck). To re-render the two new slides, run
`slides/render.mjs` in the same Playwright container.
