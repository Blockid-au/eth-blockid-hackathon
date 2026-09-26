.PHONY: help contracts-deps test test-contracts test-agents demo svi slither lint

help:
	@echo "make contracts-deps   install OpenZeppelin + forge-std into contracts/lib"
	@echo "make test             run all tests (Solidity + Python)"
	@echo "make demo             offline end-to-end demo (no API spend, no GPU)"
	@echo "make svi PROFILE=f  live: Brave research + SVI (Claude CLI, DeepInfra fallback)"
	@echo "make slither          static analysis of the contracts"

contracts-deps:
	cd contracts && forge install OpenZeppelin/openzeppelin-contracts@v5.4.0 foundry-rs/forge-std --no-git

test: test-contracts test-agents

test-contracts:
	cd contracts && forge test

test-agents:
	cd agents && python -m pytest -q

demo:
	cd agents && PYTHONPATH=src python -m blockid_agents demo

svi:
	cd agents && PYTHONPATH=src .venv/bin/python -m blockid_agents svi $${PROFILE:-examples/agritrace.json}

slither:
	cd contracts && slither . --filter-paths "lib|test|script" --exclude-dependencies

lint:
	ruff check agents/src
