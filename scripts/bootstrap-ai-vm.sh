#!/usr/bin/env bash
# GCE startup script for VM-B (blockid-ai, Singapore, GPU). Idempotent: runs on every boot.
set -euo pipefail
exec > >(tee -a /var/log/blockid-bootstrap.log) 2>&1
echo "== bootstrap $(date -Is)"

meta() { curl -fsS -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/$1"; }
PROJECT=$(meta project/project-id)
MODEL_ID=$(meta instance/attributes/model-id 2>/dev/null || echo "REPLACE_WITH_VERIFIED_QWEN3.8-27B_AWQ_REPO")
MAX_LEN=$(meta instance/attributes/max-model-len 2>/dev/null || echo 32768)
IDLE_MINUTES=$(meta instance/attributes/idle-minutes 2>/dev/null || echo 20)

# 1) NVIDIA driver (reboots once on first install)
if ! command -v nvidia-smi >/dev/null || ! nvidia-smi >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ubuntu-drivers-common
  ubuntu-drivers install --gpgpu
  echo "== driver installed, rebooting"; reboot; exit 0
fi

# 2) Docker + NVIDIA container toolkit
if ! command -v docker >/dev/null; then
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /etc/apt/keyrings/nvidia.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/etc/apt/keyrings/nvidia.gpg] https://#' > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker && systemctl restart docker
fi

# 3) Secrets
mkdir -p /opt/blockid/hf-cache && chmod 700 /opt/blockid
secret() { gcloud secrets versions access latest --secret="$1" --project="$PROJECT"; }
umask 077
cat > /opt/blockid/ai.env <<EOF
MODEL_ID=${MODEL_ID}
SERVED_NAME=qwen3.8-27b
MAX_LEN=${MAX_LEN}
HF_TOKEN=$(secret hf-token)
EOF
cat > /opt/blockid/litellm.env <<EOF
ANTHROPIC_API_KEY=$(secret anthropic-api-key)
LITELLM_MASTER_KEY=$(secret litellm-master-key)
EOF

# 4) Idle shutdown timer (GPU billed only while working)
install -m 0755 /opt/blockid/repo/deploy/vm-ai/idle-shutdown.sh /usr/local/bin/blockid-idle-shutdown 2>/dev/null || true
cat > /etc/systemd/system/blockid-idle.service <<EOF
[Service]
Type=oneshot
Environment=IDLE_MINUTES=${IDLE_MINUTES}
ExecStart=/usr/local/bin/blockid-idle-shutdown
EOF
cat > /etc/systemd/system/blockid-idle.timer <<'EOF'
[Timer]
OnBootSec=10min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload && systemctl enable --now blockid-idle.timer

# 5) Start the stack
if [[ ! -d /opt/blockid/repo/deploy/vm-ai ]]; then
  echo "!! copy the repository to /opt/blockid/repo, then reboot"; exit 0
fi
cd /opt/blockid/repo/deploy/vm-ai
docker compose --env-file /opt/blockid/ai.env up -d
echo "== bootstrap done"
