#!/usr/bin/env bash
# Record a deploy for the ops weekly report ("Deploys this week", agents/src/blockid_agents/ops/report.py).
# Appends "<ISO UTC time>\t<git sha>\t<subject>\t<who>" to /mnt/app-data/agents/deploys.log, which agents-api reads
# as /data/deploys.log (OPS_DEPLOY_LOG). Run it right after a deploy, e.g.
#   scripts/record-deploy.sh "backend: agents-api agents-worker issuer"
#   scripts/build-web.sh && scripts/record-deploy.sh web
# The optional argument says what was deployed (default: the last commit subject).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${DEPLOY_LOG:-/mnt/app-data/agents/deploys.log}"
SHA="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
DIRTY="$(git -C "$ROOT" status --porcelain 2>/dev/null | grep -q . && echo '+dirty' || true)"
SUBJECT="$(git -C "$ROOT" log -1 --pretty=%s 2>/dev/null || echo '')"
WHAT="${1:-}"
LINE="$(date -u +%Y-%m-%dT%H:%M:%SZ)	${SHA}${DIRTY}	${WHAT:+[$WHAT] }${SUBJECT//	/ }	${SUDO_USER:-${USER:-?}}"
echo "$LINE" | sudo tee -a "$LOG" >/dev/null
sudo chown 10001:10001 "$LOG" 2>/dev/null || true
echo "recorded: $LINE"
