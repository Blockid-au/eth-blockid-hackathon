#!/usr/bin/env bash
# First boot: create a single-validator genesis for the BlockID chain (demo/testnet),
# with minimum gas price 0 (zero-gas for shareholders). Later boots just start the node.
# For production: generate genesis with >= 4 independent validators and review every parameter.
set -euo pipefail

HOME_DIR=/root/.evmd
CHAIN_ID="${CHAIN_ID:-blockid_262626-1}"
MONIKER="${MONIKER:-blockid-val-1}"
DENOM="${DENOM:-ablkd}"

if [[ ! -f "$HOME_DIR/config/genesis.json" ]]; then
  echo ">> initialising $CHAIN_ID"
  evmd init "$MONIKER" --chain-id "$CHAIN_ID" --home "$HOME_DIR"
  evmd keys add validator --keyring-backend file --home "$HOME_DIR" <<<"${KEYRING_PASSWORD:?set KEYRING_PASSWORD}
${KEYRING_PASSWORD}"
  # Replace the default denom and fund the validator
  jq --arg d "$DENOM" '(.. | objects | select(has("denom")) | .denom) |= $d
      | .app_state.staking.params.bond_denom = $d
      | .app_state.evm.params.evm_denom = $d
      | .app_state.evm.params.extended_denom_options.extended_denom = $d
      | .app_state.bank.denom_metadata = [{
          description: "BlockID chain native token", base: $d, display: "blkd",
          name: "BlockID", symbol: "BLKD",
          denom_units: [{denom: $d, exponent: 0, aliases: []}, {denom: "blkd", exponent: 18, aliases: []}]
        }]' \
     "$HOME_DIR/config/genesis.json" > /tmp/g.json && mv /tmp/g.json "$HOME_DIR/config/genesis.json"
  ADDR=$(evmd keys show validator -a --keyring-backend file --home "$HOME_DIR" <<<"$KEYRING_PASSWORD")
  evmd genesis add-genesis-account "$ADDR" "100000000000000000000000000${DENOM}" --home "$HOME_DIR"
  evmd genesis gentx validator "1000000000000000000000${DENOM}" --chain-id "$CHAIN_ID" \
       --keyring-backend file --home "$HOME_DIR" <<<"$KEYRING_PASSWORD"
  evmd genesis collect-gentxs --home "$HOME_DIR"
  evmd genesis validate-genesis --home "$HOME_DIR"

  # Zero gas price; JSON-RPC on all interfaces inside the container network only
  sed -i "s/^minimum-gas-prices = .*/minimum-gas-prices = \"0${DENOM}\"/" "$HOME_DIR/config/app.toml"
  sed -i 's/^address = "127.0.0.1:8545"/address = "0.0.0.0:8545"/; s/^ws-address = "127.0.0.1:8546"/ws-address = "0.0.0.0:8546"/' "$HOME_DIR/config/app.toml"
  sed -i 's#laddr = "tcp://127.0.0.1:26657"#laddr = "tcp://0.0.0.0:26657"#' "$HOME_DIR/config/config.toml"
fi

# Applied on every boot (idempotent): evmd >= v0.7 needs the app-side EVM mempool,
# and the EVM chain id must match BLOCKID_CHAIN_ID used by the agents/MetaMask.
EVM_CHAIN_ID="${EVM_CHAIN_ID:-262626}"
sed -i 's/^type = "flood"/type = "app"/' "$HOME_DIR/config/config.toml"
sed -i "s/^evm-chain-id = .*/evm-chain-id = ${EVM_CHAIN_ID}/" "$HOME_DIR/config/app.toml"
# Cosmos REST (explorer /lcd): listen inside the container network; published on 127.0.0.1 only
sed -i 's#^address = "tcp://localhost:1317"#address = "tcp://0.0.0.0:1317"#' "$HOME_DIR/config/app.toml"

exec evmd start --home "$HOME_DIR" --chain-id "$CHAIN_ID" \
  --api.enable \
  --json-rpc.enable --json-rpc.api eth,net,web3,txpool,debug
