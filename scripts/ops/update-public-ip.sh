#!/usr/bin/env bash
# Keep Cloudflare DNS and host nginx in step with this VM's public IP.
#
# The GCP VM has an ephemeral external IP, so it changes whenever the VM is
# stopped and started. Run at boot and on a timer by
# deploy/systemd/blockid-public-ip.{service,timer}:
#   1. read the current external IP from the GCP metadata server
#      (fallback: api.ipify.org),
#   2. update the Cloudflare A records in CF_RECORDS (keeps each record's
#      proxied flag and TTL; creates nothing, only fixes existing records),
#   3. replace the previous IP in /etc/nginx (if it appears) and refresh the
#      Cloudflare real-IP ranges, then `nginx -t && systemctl reload nginx`,
#   4. remember the IP in $STATE_DIR/last-ip and warn about other places
#      that still carry the old IP (e.g. the Google Workspace SMTP relay
#      allow-list, which has to be changed by hand in the Admin console).
#
# Config: /etc/blockid/cloudflare.env (root-only, created by the owner):
#   CF_API_TOKEN=...            # token with Zone:DNS:Edit on blockid.au
#   CF_ZONE=blockid.au
#   CF_RECORDS="eth.blockid.au hr.blockid.au scan.blockid.au"
# Without a token the script still does the nginx part and logs a warning.
#
# Usage: sudo scripts/ops/update-public-ip.sh [--dry-run]
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

ENV_FILE="${ENV_FILE:-/etc/blockid/cloudflare.env}"
STATE_DIR="${STATE_DIR:-/var/lib/blockid-public-ip}"
NGINX_DIR="${NGINX_DIR:-/etc/nginx}"
REALIP_CONF="${REALIP_CONF:-/etc/nginx/conf.d/cloudflare-realip.conf}"

CF_API_TOKEN=""
CF_ZONE="blockid.au"
CF_RECORDS="eth.blockid.au hr.blockid.au scan.blockid.au"
# shellcheck disable=SC1090
[[ -r "$ENV_FILE" ]] && source "$ENV_FILE"

log() { echo "[public-ip] $*"; logger -t blockid-public-ip -- "$*" 2>/dev/null || true; }
run() { if (( DRY_RUN )); then log "dry-run: $*"; else "$@"; fi; }
is_ipv4() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }

# --- 1. current public IP -------------------------------------------------
current_ip() {
  local ip=""
  for _ in $(seq 1 30); do   # network may not be up yet right after boot
    ip=$(curl -fsS -m 5 -H "Metadata-Flavor: Google" \
      http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip 2>/dev/null || true)
    is_ipv4 "$ip" || ip=$(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || true)
    is_ipv4 "$ip" && { echo "$ip"; return 0; }
    sleep 2
  done
  return 1
}

NEW_IP=$(current_ip) || { log "ERROR: could not determine public IP"; exit 1; }
mkdir -p "$STATE_DIR"
OLD_IP=$(cat "$STATE_DIR/last-ip" 2>/dev/null || true)
log "public IP now $NEW_IP (last seen ${OLD_IP:-unknown})"

# --- 2. Cloudflare DNS ----------------------------------------------------
cf() {  # cf METHOD PATH [JSON]
  curl -fsS -m 20 -X "$1" "https://api.cloudflare.com/client/v4$2" \
    -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
    ${3:+--data "$3"}
}

CF_OK=1
if [[ -z "$CF_API_TOKEN" ]]; then
  log "WARN: no CF_API_TOKEN in $ENV_FILE - Cloudflare DNS not checked"
  CF_OK=0
else
  zone_id=$(cf GET "/zones?name=$CF_ZONE" | jq -r '.result[0].id // empty') || zone_id=""
  if [[ -z "$zone_id" ]]; then
    log "ERROR: Cloudflare zone $CF_ZONE not found (token scope?)"
    CF_OK=0
  else
    for name in $CF_RECORDS; do
      rec=$(cf GET "/zones/$zone_id/dns_records?type=A&name=$name" | jq -c '.result[0] // empty') || rec=""
      if [[ -z "$rec" ]]; then
        log "WARN: no A record for $name in $CF_ZONE - skipped"
        continue
      fi
      content=$(jq -r .content <<<"$rec")
      if [[ "$content" == "$NEW_IP" ]]; then
        log "cloudflare $name already $NEW_IP"
        continue
      fi
      body=$(jq -c --arg ip "$NEW_IP" '{type:"A", name:.name, content:$ip, ttl:.ttl, proxied:.proxied}' <<<"$rec")
      if (( DRY_RUN )); then
        log "dry-run: cloudflare $name $content -> $NEW_IP"
      elif cf PUT "/zones/$zone_id/dns_records/$(jq -r .id <<<"$rec")" "$body" | jq -e .success >/dev/null; then
        log "cloudflare $name $content -> $NEW_IP"
        [[ -z "$OLD_IP" ]] && OLD_IP="$content"
      else
        log "ERROR: cloudflare update failed for $name"
        CF_OK=0
      fi
    done
  fi
fi

# --- 3. nginx -------------------------------------------------------------
NGINX_CHANGED=0
if [[ -n "$OLD_IP" && "$OLD_IP" != "$NEW_IP" ]]; then
  old_re=${OLD_IP//./\\.}
  while IFS= read -r f; do
    log "nginx: $f had $OLD_IP -> $NEW_IP"
    run cp -a "$f" "$STATE_DIR/$(basename "$f").bak-$(date +%s)"
    run sed -i "s/\b$old_re\b/$NEW_IP/g" "$f"
    NGINX_CHANGED=1
  done < <(grep -rlw -- "$OLD_IP" "$NGINX_DIR" 2>/dev/null || true)
fi

# Refresh the Cloudflare edge ranges used for set_real_ip_from.
if [[ -f "$REALIP_CONF" ]]; then
  v4=$(curl -fsS -m 10 https://www.cloudflare.com/ips-v4 2>/dev/null || true)
  v6=$(curl -fsS -m 10 https://www.cloudflare.com/ips-v6 2>/dev/null || true)
  if [[ -n "$v4" && -n "$v6" ]]; then
    tmp=$(mktemp)
    {
      echo "# Managed by scripts/ops/update-public-ip.sh - Cloudflare edge ranges"
      for r in $v4 $v6; do echo "set_real_ip_from $r;"; done
      grep -E '^\s*(real_ip_header|real_ip_recursive)' "$REALIP_CONF" || echo "real_ip_header CF-Connecting-IP;"
    } >"$tmp"
    if ! diff -q <(grep set_real_ip_from "$REALIP_CONF" | sort) <(grep set_real_ip_from "$tmp" | sort) >/dev/null; then
      log "nginx: Cloudflare IP ranges changed, updating $REALIP_CONF"
      run cp -a "$REALIP_CONF" "$STATE_DIR/cloudflare-realip.conf.bak-$(date +%s)"
      run install -m 644 "$tmp" "$REALIP_CONF"
      NGINX_CHANGED=1
    fi
    rm -f "$tmp"
  fi
fi

if (( NGINX_CHANGED && ! DRY_RUN )); then
  if nginx -t 2>/dev/null; then
    systemctl reload nginx && log "nginx reloaded"
  else
    log "ERROR: nginx -t failed after edits - restore from $STATE_DIR/*.bak-*"
    exit 1
  fi
fi

# --- 4. remember + warn ---------------------------------------------------
if [[ -n "$OLD_IP" && "$OLD_IP" != "$NEW_IP" ]]; then
  log "WARN: IP changed $OLD_IP -> $NEW_IP. Update by hand: Google Workspace SMTP relay allow-list, any provider IP allow-lists."
  others=$(grep -rlw -- "$OLD_IP" /opt/blockid 2>/dev/null | grep -v keys || true)
  [[ -n "$others" ]] && log "WARN: old IP still in: $(tr '\n' ' ' <<<"$others")"
fi
(( DRY_RUN )) || echo "$NEW_IP" >"$STATE_DIR/last-ip"
(( CF_OK )) || exit 2
exit 0
