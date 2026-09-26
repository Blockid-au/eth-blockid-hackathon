#!/usr/bin/env bash
# Re-runnable, read-only screenshot tour of eth.blockid.au + scan.blockid.au.
# Usage: scripts/screenshots/run.sh            (all shots)
#        ONLY='^2[2-4]' scripts/screenshots/run.sh   (retake a subset by file-name regex)
#        NO_COMPRESS=1 scripts/screenshots/run.sh
# Needs Docker only (no host Node). Output goes to docs/screenshots/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PW_VERSION="${PW_VERSION:-1.63.0}"
IMAGE="mcr.microsoft.com/playwright:v${PW_VERSION}-noble"
DOCKER="${DOCKER:-docker}"; $DOCKER info >/dev/null 2>&1 || DOCKER="sudo docker"
UIDGID="$(id -u):$(id -g)"
mkdir -p "$ROOT/docs/screenshots"

$DOCKER run --rm --network host --ipc host \
  -v "$ROOT:/repo" -w /repo/scripts/screenshots \
  -e ONLY="${ONLY:-}" -e APP_URL -e SCAN_URL -e ADMIN_USER -e ADMIN_PASS -e VAL_ID -e OUT_DIR=/repo/docs/screenshots \
  "$IMAGE" bash -c "
    set -e
    [ -d node_modules/playwright ] || npm i --no-audit --no-fund --silent
    node capture.mjs
    if [ -z '${NO_COMPRESS:-}' ]; then
      (command -v pngquant >/dev/null || (apt-get update -qq && apt-get install -y -qq pngquant >/dev/null)) \
        && find /repo/docs/screenshots -name '*.png' -newer capture.mjs -print0 | xargs -0 -r pngquant --force --skip-if-larger --quality=70-92 --strip --ext .png || true
    fi
    chown -R $UIDGID node_modules package-lock.json /repo/docs/screenshots 2>/dev/null || true
  "
ls -la "$ROOT/docs/screenshots"
du -sh "$ROOT/docs/screenshots"
