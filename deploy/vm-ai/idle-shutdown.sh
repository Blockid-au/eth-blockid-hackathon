#!/usr/bin/env bash
# Stops this GPU VM when vLLM has been idle for IDLE_MINUTES (default 20).
# Installed by bootstrap-ai-vm.sh as a systemd timer running every minute.
# `shutdown -h now` on GCE moves the VM to TERMINATED: GPU/CPU billing stops, only disks are billed.
set -euo pipefail

IDLE_MINUTES="${IDLE_MINUTES:-20}"
STATE=/var/lib/blockid-idle
mkdir -p "$STATE"

metrics=$(curl -fsS --max-time 5 http://127.0.0.1:8000/metrics 2>/dev/null || true)
if [[ -z "$metrics" ]]; then
  # vLLM still booting (downloading weights) — never shut down during startup
  date +%s > "$STATE/last_active"
  exit 0
fi

running=$(awk '/^vllm:num_requests_running/ {s+=$2} END {print s+0}' <<<"$metrics")
waiting=$(awk '/^vllm:num_requests_waiting/ {s+=$2} END {print s+0}' <<<"$metrics")
done_total=$(awk '/^vllm:request_success_total/ {s+=$2} END {print s+0}' <<<"$metrics")
prev_total=$(cat "$STATE/done_total" 2>/dev/null || echo "-1")
echo "$done_total" > "$STATE/done_total"

if (( $(printf '%.0f' "$running") > 0 || $(printf '%.0f' "$waiting") > 0 )) || [[ "$done_total" != "$prev_total" ]]; then
  date +%s > "$STATE/last_active"
  exit 0
fi

last=$(cat "$STATE/last_active" 2>/dev/null || date +%s)
idle_for=$(( ( $(date +%s) - last ) / 60 ))
if (( idle_for >= IDLE_MINUTES )); then
  logger -t blockid-idle "idle ${idle_for} min -> shutting down GPU VM"
  rm -f "$STATE/last_active"
  shutdown -h now
fi
