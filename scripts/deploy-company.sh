#!/usr/bin/env bash
# Human-run deployment of one company's share register, AFTER the contract gate is approved.
# The deployer key is in the operator's encrypted Foundry keystore (or a hardware wallet) on the
# operator's own machine — never on the servers, never visible to any agent.
#
# Usage: scripts/deploy-company.sh <workflow-id> [network]
#   network: blockid_chain (default) | sepolia
set -euo pipefail

WID="${1:?workflow id}"
NET="${2:-blockid_chain}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARAMS="deployments/params/${WID}.json"

cd "$ROOT/contracts"
[[ -f "$PARAMS" ]] || { echo "params not found: contracts/$PARAMS (download it from the contract gate)"; exit 1; }

echo "== Parameters to deploy:"; cat "$PARAMS"; echo
read -r -p "Deploy these parameters to ${NET}? Type the workflow id to confirm: " CONFIRM
[[ "$CONFIRM" == "$WID" ]] || { echo "aborted"; exit 1; }

forge test --offline
PARAMS_FILE="$PARAMS" forge script script/DeployCompany.s.sol \
  --rpc-url "$NET" --account "${DEPLOYER_ACCOUNT:-blockid-deployer}" --broadcast \
  | tee "deployments/out/${WID}-${NET}.log"

echo
echo "== Next: resume the workflow with the three addresses printed above:"
echo "curl -X POST https://eth.blockid.au/api/v1/workflows/${WID}/decision -H 'X-API-Key: ...' \\"
echo "  -H 'Content-Type: application/json' -d '{\"decision\":{\"approved\":true,\"reviewer\":\"you@blockid.au\","
echo "  \"deployment\":{\"token\":\"0x...\",\"identity_registry\":\"0x...\",\"distributor\":\"0x...\"},"
echo "  \"cap_table\":[...], \"kyc\":{...}}}'"
