# Runbook: setup & operations on GCP

## 0. Preparation (your machine)

```bash
gcloud auth login && gcloud config set project <PROJECT_ID>
gcloud services enable compute.googleapis.com secretmanager.googleapis.com iap.googleapis.com
# GPU quota: IAM & Admin → Quotas → "NVIDIA L4 GPUs" (and "Preemptible NVIDIA L4 GPUs") in asia-southeast1 ≥ 1
```

## 1. Infrastructure

```bash
cd infra/terraform
terraform init
terraform apply -var project_id=<PROJECT_ID>
# output: app_public_ip → point the A record of eth.blockid.au to this IP
```

## 2. Loading secrets (one time, never commit)

```bash
for s in blockid-api-key litellm-master-key postgres-password evmd-keyring-password; do
  openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add $s --data-file=-
done
echo -n "<BRAVE_KEY>"     | gcloud secrets versions add brave-api-key --data-file=-
echo -n "<ANTHROPIC_KEY>" | gcloud secrets versions add anthropic-api-key --data-file=-
echo -n "<HF_TOKEN>"      | gcloud secrets versions add hf-token --data-file=-
```

## 3. Choosing the model for the AI VM

Choose a **4-bit AWQ/GPTQ** build of Qwen3.8-27B on Hugging Face (about 17–19GB, fits the L4's 24GB), carefully check the license and source, then set it in the metadata:

```bash
gcloud compute instances add-metadata blockid-ai --zone asia-southeast1-c \
  --metadata model-id=<ORG/Qwen3.8-27B-AWQ>,max-model-len=32768,idle-minutes=20
```

## 4. Shipping code to the 2 VMs

```bash
make contracts-deps
tar czf /tmp/repo.tgz --exclude=.git .
gcloud compute scp /tmp/repo.tgz blockid-app:/tmp --zone australia-southeast1-b --tunnel-through-iap
gcloud compute ssh blockid-app --zone australia-southeast1-b --tunnel-through-iap -- \
  'sudo mkdir -p /opt/blockid/repo && sudo tar xzf /tmp/repo.tgz -C /opt/blockid/repo && sudo google_metadata_script_runner startup'
# Repeat for blockid-ai (zone asia-southeast1-c). On first boot the AI VM installs the driver itself, then reboots.
```

## 5. Verification

```bash
curl https://eth.blockid.au/api/healthz                    # {"ok":true,...}
curl -s https://eth.blockid.au/rpc -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'
# MetaMask: Add network → RPC https://eth.blockid.au/rpc, chain id from genesis
```

## 6. Issuance process for a startup

1. **Submit the file:** call `POST /api/v1/onboarding` with the data room and `issuance_inputs` (Safe address, transfer agent, KYC agent, constitution hash, board resolution ID).
2. **Gate 1:** review the SVI score and source list, then `POST .../decision` with `{approved, reviewer, overrides}`.
3. **Gate 2:** download the params file, then run `scripts/deploy-company.sh <workflow_id>` on your own machine (using the keystore via `cast wallet import blockid-deployer --interactive`).
4. **Continue the workflow:** submit the decision along with the 3 contract addresses, the cap table, and KYC information.
5. **Sign:** download `GET .../safe-batch`, go to Safe{Wallet} → Transaction Builder → import the JSON → review → sign.

## 7. Dividend distribution

1. Get shareholder balances at `record_block` from the indexer/explorer.
2. Call `POST /api/v1/dividends`.
3. Gate 3: cross-check against the board resolution, then approve.
4. Sign the Safe batch (`approve` + `createRound`).
5. Shareholders claim on the web app using the proof from `dividend_plan.claims`.

## 8. Operations

| Task | Command |
|---|---|
| Worker logs | `sudo docker compose -f /opt/blockid/repo/deploy/vm-app/docker-compose.yml logs -f agents-worker` |
| Check audit log | `sudo docker compose exec agents-api python -m blockid_agents verify-audit` |
| Manually start the GPU | `gcloud compute instances start blockid-ai --zone asia-southeast1-c` |
| Change GPU auto-shutdown time | metadata `idle-minutes`, then reboot the AI VM |
| Change model | edit `deploy/vm-ai/litellm-config.yaml` or the `model-id` metadata |
| Upgrade GPU | `terraform apply -var ai_machine_type=g4-standard-48` |

## 9. Common issues

| Symptom | Cause / fix |
|---|---|
| Job stuck in `running` for a long time | AI VM is downloading weights for the first time (10–20 minutes) or is short on Spot quota. Check the log at `/var/log/blockid-bootstrap.log` |
| Job `failed` after 3 attempts | Spot capacity keeps being reclaimed. Temporarily set `ai_provisioning_model=STANDARD` |
| Gate 2 reports `rejected_contract_checks_failed` | Check `contract_check`: fix the parameters, then rerun onboarding |
| Research has no data | Check the `brave-api-key` secret and Brave quota. Research will be skipped and valuation will fall back to a stage-based range |
