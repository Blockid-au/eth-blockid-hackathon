#!/usr/bin/env bash
# End-to-end TESTNET demo on HashKey Chain testnet (chain id 133) — EAG hackathon HSK track.
#   1) deployer (issuer service): deploy AgentProvenance + RWA stack, record the valuation agent's SVI report hash
#   2) approver (a DIFFERENT, human-held wallet): approve the agent proposal on-chain (four-eyes rule)
#   3) deployer: execute only if approved — KYC, issue shares, anchor valuation + cap table, fund dividend round
#   4) relayer: gasless claimFor for each shareholder
#   5) publish web/hsk-demo.json for https://eth.blockid.au/hsk
# Keys: encrypted Foundry keystores (~/.foundry/keystores/blockid-{deployer,admin,relayer}); passwords in
# ~/.blockid/*.password (mode 600). AI agents never touch these keys. Testnet only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.foundry/bin:$PATH"
RPC="${HSK_RPC_URL:-https://testnet.hsk.xyz}"
EXPLORER="${HSK_EXPLORER:-https://testnet-explorer.hskchain.net}"
KEYS="$HOME/.blockid"
DEPLOYER=$(cat "$KEYS/deployer.address")
APPROVER=$(cat "$KEYS/admin.address")
RELAYER=$(cat "$KEYS/relayer.address")
OUT="$ROOT/contracts/deployments/out/hsk-demo.json"
FIXTURE="$ROOT/contracts/test/fixtures/dividend_round.json"
REPORT="$ROOT/contracts/deployments/params/hsk-svi-report.json"
TXLOG="$ROOT/contracts/deployments/out/hsk-txs.json"

[[ $(cast chain-id --rpc-url "$RPC") == 133 ]] || { echo "RPC is not HashKey Chain testnet"; exit 1; }
echo "== deployer $DEPLOYER balance: $(cast from-wei "$(cast balance "$DEPLOYER" --rpc-url "$RPC")") HSK"
REPORT_HASH=$(cast keccak "$(cat "$REPORT")")
echo "== SVI report hash (AI output provenance): $REPORT_HASH"
[[ -f $TXLOG ]] || echo '{}' > "$TXLOG"
logtx() { jq --arg k "$1" --arg v "$2" '. + {($k): $v}' "$TXLOG" > "$TXLOG.tmp" && mv "$TXLOG.tmp" "$TXLOG"; }
lasttx() { jq -r '[.transactions[] | select(.function != null and (.function | startswith($f)))] | last | .hash // empty' --arg f "$2" "$1"; }

cd "$ROOT/contracts"
BCAST="broadcast/HskDemo.s.sol/133"
if [[ ! -f $OUT ]]; then
  echo "== 1) propose: deploy + register agents + record SVI report hash"
  forge test --offline >/dev/null && echo "   forge test: ok"
  RELAYER="$RELAYER" APPROVER="$APPROVER" REPORT_HASH="$REPORT_HASH" \
    forge script script/HskDemo.s.sol:HskDemo --sig "propose()" --rpc-url "$RPC" --broadcast --slow \
    --account blockid-deployer --password-file "$KEYS/deployer.password" > /tmp/hsk-propose.log 2>&1 \
    || { tail -20 /tmp/hsk-propose.log; exit 3; }
  grep -E 'AgentProvenance|proposal' /tmp/hsk-propose.log || true
  logtx propose "$(lasttx "$BCAST/propose-latest.json" 'propose(')"
else
  echo "== 1) already proposed ($OUT) — skipping"
fi

PROV=$(jq -r .agentProvenance "$OUT"); ID=$(jq -r .proposalId "$OUT")
STATUS=$(cast call "$PROV" "getProposal(uint256)((bytes32,string,bytes32,string,string,address,address,uint64,uint64,bytes32,uint8))" "$ID" --rpc-url "$RPC" | tr -d '()' | awk -F', ' '{print $NF}')
if [[ $STATUS == 1 ]]; then
  echo "== 2) human approver $APPROVER approves proposal $ID"
  TX=$(cast send "$PROV" "approve(uint256)" "$ID" --rpc-url "$RPC" \
        --account blockid-admin --password-file "$KEYS/admin.password" --json | jq -r .transactionHash)
  logtx approve "$TX"; echo "   tx $TX"
else
  echo "== 2) proposal status $STATUS — approval already done"
fi

if [[ $(cast call "$PROV" "getProposal(uint256)((bytes32,string,bytes32,string,string,address,address,uint64,uint64,bytes32,uint8))" "$ID" --rpc-url "$RPC" | tr -d '()' | awk -F', ' '{print $NF}') != 4 ]]; then
  echo "== 3) execute (guarded by AgentProvenance.verify)"
  forge script script/HskDemo.s.sol:HskDemo --sig "execute()" --rpc-url "$RPC" --broadcast --slow \
    --account blockid-deployer --password-file "$KEYS/deployer.password" > /tmp/hsk-execute.log 2>&1 \
    || { tail -20 /tmp/hsk-execute.log; exit 4; }
  grep -E 'executed' /tmp/hsk-execute.log || true
  logtx issue "$(lasttx "$BCAST/execute-latest.json" 'issue(')"
  logtx anchorValuation "$(lasttx "$BCAST/execute-latest.json" 'anchorValuation(')"
  logtx anchorCapTable "$(lasttx "$BCAST/execute-latest.json" 'anchor(')"
  logtx createDividendRound "$(lasttx "$BCAST/execute-latest.json" 'createRound(')"
  logtx execute "$(lasttx "$BCAST/execute-latest.json" 'markExecuted(')"
else
  echo "== 3) already executed"
fi

DIST=$(jq -r .dividendDistributor "$OUT")
echo "== 4) relayer $RELAYER submits gasless claimFor for each shareholder"
for i in 0 1 2; do
  ACC=$(jq -r ".holders[$i].account" "$FIXTURE"); AMT=$(jq -r ".holders[$i].amount" "$FIXTURE")
  PROOF="[$(jq -r ".holders[$i].proof | join(\",\")" "$FIXTURE")]"
  if [[ $(cast call "$DIST" "hasClaimed(uint256,address)(bool)" 0 "$ACC" --rpc-url "$RPC") == true ]]; then
    echo "   $ACC already claimed"; continue
  fi
  TX=$(cast send "$DIST" "claimFor(uint256,address,uint256,bytes32[])" 0 "$ACC" "$AMT" "$PROOF" \
        --rpc-url "$RPC" --account blockid-relayer --password-file "$KEYS/relayer.password" --json | jq -r .transactionHash)
  logtx "claim$i" "$TX"; echo "   $ACC  +$AMT mAUD-units  tx $TX"
done

echo "== 5) publish web/hsk-demo.json"
jq -s --arg exp "$EXPLORER" --arg id "$ID" '
  .[0] + {
    explorer: $exp, roundId: 0,
    holders: [.[1].holders[] | {account, amount}], merkleRoot: .[1].root, dividendTotal: .[1].total,
    capTableRoot: .[3].root,
    shares: [.[3].claims | to_entries[] | {account: .key, shares: .value.amount}],
    txs: .[2],
    provenance: [{id: ($id|tonumber), agent: "valuation", kind: "svi_report", contentHash: .[0].reportHash,
                  modelId: "claude-opus-5-5", status: "Executed",
                  proposeTx: .[2].propose, approveTx: .[2].approve, executeTx: .[2].execute}]
  }' "$OUT" "$FIXTURE" "$TXLOG" "$ROOT/contracts/deployments/params/hsk-captable.json" > "$ROOT/web/hsk-demo.json"
chmod 644 "$ROOT/web/hsk-demo.json"
echo "done → https://eth.blockid.au/hsk"
