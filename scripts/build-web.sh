#!/usr/bin/env bash
# Build the SPA (web/app) and publish it into web/dist WITHOUT breaking open tabs.
#
# Why: `vite build` with emptyOutDir wipes web/dist; a tab loaded before the rebuild then requests an old hashed
# chunk (/assets/Company-<oldhash>.js) -> 404 -> the page hangs. Here we build into a temp dir, copy the new hashed
# assets next to the old ones (old ones are kept for KEEP_DAYS, then pruned), keep runtime JSON at the dist root,
# and replace index.html LAST with an atomic mv.
#
# Usage: scripts/build-web.sh            (KEEP_DAYS=14 by default)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB="$ROOT/web"
DIST="$WEB/dist"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d%H%M%S)"
TMP_REL=".build-$STAMP"          # inside web/ so the container can write it
TMP="$WEB/$TMP_REL"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

echo "== build web/app -> web/$TMP_REL"
# vite outDir is ../dist in vite.config.ts; override it for this build (relative to web/app)
sudo docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WEB:/w" -w /w/app node:20 \
  sh -c "npm run typecheck && npx vite build --outDir ../$TMP_REL --emptyOutDir"

[[ -f $TMP/index.html ]] || { echo "build produced no index.html"; exit 1; }
mkdir -p "$DIST/assets"

echo "== sync hashed assets (old ones kept)"
if [[ -d $TMP/assets ]]; then
  # new files only; existing names are content-hashed so identical names mean identical content
  cp -a --update=none "$TMP/assets/." "$DIST/assets/"
  # refresh mtime of the assets the new index references, so pruning never removes live files
  (cd "$TMP/assets" && find . -type f -exec touch "$DIST/assets/{}" \;)
fi

echo "== other static files (not index.html; runtime *.json in dist are preserved)"
(cd "$TMP" && find . -type f ! -path "./assets/*" ! -name index.html ! -name "*.json" -print0) |
  while IFS= read -r -d '' f; do mkdir -p "$DIST/$(dirname "$f")"; cp -a "$TMP/$f" "$DIST/$f"; done
# json shipped by the build (e.g. copied hsk-demo.json) only when dist has none yet
(cd "$TMP" && find . -maxdepth 1 -type f -name "*.json" -print0) |
  while IFS= read -r -d '' f; do [[ -e $DIST/$f ]] || cp -a "$TMP/$f" "$DIST/$f"; done
[[ -f $WEB/hsk-demo.json ]] && cp -a "$WEB/hsk-demo.json" "$DIST/hsk-demo.json.tmp" && mv -f "$DIST/hsk-demo.json.tmp" "$DIST/hsk-demo.json"

echo "== index.html (atomic)"
cp -a "$TMP/index.html" "$DIST/.index.html.$STAMP"
mv -f "$DIST/.index.html.$STAMP" "$DIST/index.html"

echo "== prune assets older than $KEEP_DAYS days"
find "$DIST/assets" -type f -mtime "+$KEEP_DAYS" -print -delete || true

echo "done: $(ls "$DIST/assets" | wc -l) files in web/dist/assets"
