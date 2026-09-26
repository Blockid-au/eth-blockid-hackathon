#!/usr/bin/env bash
# End-to-end TESTNET demo on Ethereum Hoodi (chain id 560048):
#   1) deployer: deploy registry/token/distributor + demo mAUD, KYC, issue, anchor SVI, fund dividend round
#   2) relayer: claimFor each shareholder (relayer pays gas, shareholder receives mAUD)
#   3) publish web/hoodi-demo.json for https://eth.blockid.au
# Keys: encrypted Foundry keystores (~/.foundry/keystores/blockid-{deployer,relayer}); the passwords are in
# ~/.blockid/*.password (mode 600). Testnet only — production deploys go through the Safe (docs/RUNBOOK.md).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.foundry/bin:$PATH"
RPC="${HOODI_RPC_URL:-https://ethereum-hoodi-rpc.publicnode.com}"
KEYS="$HOME/.blockid"
DEPLOYER=$(cat "$KEYS/deployer.address")
RELAYER=$(cat "$KEYS/relayer.address")
MIN_WEI="${MIN_WEI:-20000000000000000}"   # 0.02 ETH: ~0.0135 gas + 0.005 relayer gas
OUT="$ROOT/contracts/deployments/out/hoodi-demo.json"
FIXTURE="$ROOT/contracts/test/fixtures/dividend_round.json"

[[ $(cast chain-id --rpc-url "$RPC") == 560048 ]] || { echo "RPC is not Hoodi"; exit 1; }
BAL=$(cast balance "$DEPLOYER" --rpc-url "$RPC")
echo "== deployer $DEPLOYER balance: $(cast from-wei "$BAL") ETH"
if (( $(bc <<<"$BAL < $MIN_WEI") )); then
  echo "!! need >= $(cast from-wei "$MIN_WEI") Hoodi ETH on $DEPLOYER (faucet: https://hoodi-faucet.pk910.de)"; exit 2
fi

cd "$ROOT/contracts"
if [[ ! -f $OUT ]]; then
  echo "== 1) deploy + KYC + issue + valuation + dividend round"
  forge test --offline >/dev/null && echo "   forge test: ok"
  RELAYER="$RELAYER" forge script script/HoodiDemo.s.sol:HoodiDemo --rpc-url "$RPC" --broadcast --slow \
    --account blockid-deployer --password-file "$KEYS/deployer.password" | grep -E '^\s+(Identity|BlockID|Dividend|DemoAUD)|ONCHAIN|Error'
else
  echo "== 1) already deployed ($OUT) — skipping"
fi

DIST=$(jq -r .dividendDistributor "$OUT")
echo "== 2) relayer $RELAYER submits claimFor for each shareholder"
for i in 0 1 2; do
  ACC=$(jq -r ".holders[$i].account" "$FIXTURE"); AMT=$(jq -r ".holders[$i].amount" "$FIXTURE")
  PROOF="[$(jq -r ".holders[$i].proof | join(\",\")" "$FIXTURE")]"
  if [[ $(cast call "$DIST" "hasClaimed(uint256,address)(bool)" 0 "$ACC" --rpc-url "$RPC") == true ]]; then
    echo "   $ACC already claimed"; continue
  fi
  TX=$(cast send "$DIST" "claimFor(uint256,address,uint256,bytes32[])" 0 "$ACC" "$AMT" "$PROOF" \
        --rpc-url "$RPC" --account blockid-relayer --password-file "$KEYS/relayer.password" --json | jq -r .transactionHash)
  echo "   $ACC  +$AMT mAUD-units  tx $TX"
done

echo "== 3) publish web/hoodi-demo.json"
jq -s '.[0] + {holders: [.[1].holders[] | {account, amount}], merkleRoot: .[1].root}' "$OUT" "$FIXTURE" \
  > "$ROOT/web/hoodi-demo.json"
chmod 644 "$ROOT/web/hoodi-demo.json"
echo "done → https://eth.blockid.au"
