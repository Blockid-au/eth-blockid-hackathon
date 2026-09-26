# Runbook: cài đặt & vận hành trên GCP

## 0. Chuẩn bị (máy của bạn)

```bash
gcloud auth login && gcloud config set project <PROJECT_ID>
gcloud services enable compute.googleapis.com secretmanager.googleapis.com iap.googleapis.com
# Quota GPU: IAM & Admin → Quotas → "NVIDIA L4 GPUs" (và "Preemptible NVIDIA L4 GPUs") tại asia-southeast1 ≥ 1
```

## 1. Hạ tầng

```bash
cd infra/terraform
terraform init
terraform apply -var project_id=<PROJECT_ID>
# output: app_public_ip → trỏ bản ghi A của eth.blockid.au về IP này
```

## 2. Nạp secret (một lần, không bao giờ commit)

```bash
for s in blockid-api-key litellm-master-key postgres-password evmd-keyring-password; do
  openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add $s --data-file=-
done
echo -n "<BRAVE_KEY>"     | gcloud secrets versions add brave-api-key --data-file=-
echo -n "<ANTHROPIC_KEY>" | gcloud secrets versions add anthropic-api-key --data-file=-
echo -n "<HF_TOKEN>"      | gcloud secrets versions add hf-token --data-file=-
```

## 3. Chọn model cho VM AI

Chọn một bản Qwen3.8-27B **4-bit AWQ/GPTQ** trên Hugging Face (khoảng 17–19GB, vừa L4 24GB), kiểm tra kỹ giấy phép và nguồn phát hành, rồi gán vào metadata:

```bash
gcloud compute instances add-metadata blockid-ai --zone asia-southeast1-c \
  --metadata model-id=<ORG/Qwen3.8-27B-AWQ>,max-model-len=32768,idle-minutes=20
```

## 4. Đưa code lên 2 VM

```bash
make contracts-deps
tar czf /tmp/repo.tgz --exclude=.git .
gcloud compute scp /tmp/repo.tgz blockid-app:/tmp --zone australia-southeast1-b --tunnel-through-iap
gcloud compute ssh blockid-app --zone australia-southeast1-b --tunnel-through-iap -- \
  'sudo mkdir -p /opt/blockid/repo && sudo tar xzf /tmp/repo.tgz -C /opt/blockid/repo && sudo google_metadata_script_runner startup'
# Lặp lại cho blockid-ai (zone asia-southeast1-c). Lần đầu VM AI tự cài driver rồi reboot.
```

## 5. Kiểm tra

```bash
curl https://eth.blockid.au/api/healthz                    # {"ok":true,...}
curl -s https://eth.blockid.au/rpc -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'
# MetaMask: Add network → RPC https://eth.blockid.au/rpc, chain id theo genesis
```

## 6. Quy trình phát hành cho một startup

1. **Gửi hồ sơ:** gọi `POST /api/v1/onboarding` với data room và `issuance_inputs` (địa chỉ Safe, transfer agent, KYC agent, hash điều lệ, mã nghị quyết HĐQT).
2. **Cổng 1:** xem điểm SVI và danh sách nguồn, rồi `POST .../decision` với `{approved, reviewer, overrides}`.
3. **Cổng 2:** tải file params, sau đó chạy `scripts/deploy-company.sh <workflow_id>` trên máy của bạn (dùng keystore `cast wallet import blockid-deployer --interactive`).
4. **Tiếp tục workflow:** gửi decision kèm 3 địa chỉ contract, cap table và thông tin KYC.
5. **Ký:** tải `GET .../safe-batch`, vào Safe{Wallet} → Transaction Builder → import JSON → kiểm tra → ký.

## 7. Chia cổ tức

1. Lấy số dư cổ đông tại `record_block` từ indexer/explorer.
2. Gọi `POST /api/v1/dividends`.
3. Cổng 3: đối chiếu với nghị quyết HĐQT rồi duyệt.
4. Ký Safe batch (`approve` + `createRound`).
5. Cổ đông claim trên web bằng proof lấy từ `dividend_plan.claims`.

## 8. Vận hành

| Việc | Lệnh |
|---|---|
| Log worker | `sudo docker compose -f /opt/blockid/repo/deploy/vm-app/docker-compose.yml logs -f agents-worker` |
| Kiểm tra audit log | `sudo docker compose exec agents-api python -m blockid_agents verify-audit` |
| Bật GPU thủ công | `gcloud compute instances start blockid-ai --zone asia-southeast1-c` |
| Đổi thời gian tự tắt GPU | metadata `idle-minutes`, rồi reboot VM AI |
| Đổi model | sửa `deploy/vm-ai/litellm-config.yaml` hoặc metadata `model-id` |
| Nâng GPU | `terraform apply -var ai_machine_type=g4-standard-48` |

## 9. Sự cố thường gặp

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| Job đứng ở `running` lâu | VM AI đang tải weights lần đầu (10–20 phút) hoặc thiếu quota Spot. Xem log `/var/log/blockid-bootstrap.log` |
| Job `failed` sau 3 lần | Spot bị thu hồi liên tục. Tạm đặt `ai_provisioning_model=STANDARD` |
| Cổng 2 báo `rejected_contract_checks_failed` | Xem `contract_check`: sửa tham số rồi chạy lại onboarding |
| Research không có dữ liệu | Kiểm tra secret `brave-api-key` và quota Brave. Research sẽ bỏ qua và định giá dùng khoảng theo giai đoạn |
