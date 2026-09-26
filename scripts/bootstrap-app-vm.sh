#!/usr/bin/env bash
# GCE startup script for VM-A (blockid-app, Sydney). Idempotent: runs on every boot.
set -euo pipefail
exec > >(tee -a /var/log/blockid-bootstrap.log) 2>&1
echo "== bootstrap $(date -Is)"

meta() { curl -fsS -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/$1"; }
PROJECT=$(meta project/project-id)
DOMAIN=$(meta instance/attributes/domain || echo eth.blockid.au)

# 1) Data disk -> /mnt/app-data (format only if blank)
DEV=/dev/disk/by-id/google-app-data
mkdir -p /mnt/app-data
if ! blkid "$DEV" >/dev/null 2>&1; then mkfs.ext4 -m 0 -F -E lazy_itable_init=0,discard "$DEV"; fi
grep -q "/mnt/app-data" /etc/fstab || echo "$DEV /mnt/app-data ext4 discard,defaults,nofail 0 2" >> /etc/fstab
mountpoint -q /mnt/app-data || mount /mnt/app-data
mkdir -p /mnt/app-data/{postgres,agents,evmd,caddy}
chown -R 10001:10001 /mnt/app-data/agents

# 2) Docker + compose plugin + unattended security upgrades
if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y ca-certificates curl gnupg unattended-upgrades
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

# 3) Secrets from Secret Manager -> env file readable by root only
mkdir -p /opt/blockid && chmod 700 /opt/blockid
secret() { gcloud secrets versions access latest --secret="$1" --project="$PROJECT"; }
umask 077
cat > /opt/blockid/app.env <<EOF
DOMAIN=${DOMAIN}
GCP_PROJECT=${PROJECT}
POSTGRES_PASSWORD=$(secret postgres-password)
BLOCKID_API_KEY=$(secret blockid-api-key)
BRAVE_API_KEY=$(secret brave-api-key)
LITELLM_CLIENT_KEY=$(secret litellm-master-key)
EVMD_KEYRING_PASSWORD=$(secret evmd-keyring-password)
EOF

# 4) Application code: copy the repo to /opt/blockid/repo (git clone with a deploy key, or gcloud scp)
if [[ ! -d /opt/blockid/repo/deploy/vm-app ]]; then
  echo "!! /opt/blockid/repo missing — copy the repository there, then reboot or re-run this script"
  exit 0
fi
cd /opt/blockid/repo/deploy/vm-app
docker compose --env-file /opt/blockid/app.env up -d --build
echo "== bootstrap done"
