// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script, console2} from "forge-std/Script.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {BlockIDShareToken} from "../src/BlockIDShareToken.sol";
import {DividendDistributor} from "../src/DividendDistributor.sol";
import {DemoAUD} from "../src/DemoAUD.sol";
import {CapTableAnchor} from "../src/CapTableAnchor.sol";
import {AgentProvenance} from "../src/AgentProvenance.sol";

/// @notice TESTNET demo on HashKey Chain (chain id 133): the full BlockID RWA stack plus AgentProvenance.
///         Two phases so a *different* human wallet approves the agents' proposals in between:
///           1) propose(): deploy, register agents, record the valuation agent's SVI report hash (Proposed)
///           -- approver wallet calls AgentProvenance.approve(0) (scripts/hsk-demo.sh, cast send) --
///           2) execute(): only if approved -> KYC, issue shares, anchor valuation, cap table, dividend round,
///              then markExecuted(0, <execution ref>).
///         DEMO ONLY: the deployer plays issuer Safe, KYC agent and transfer agent (production: Safe multisig).
contract HskDemo is Script {
    string constant FIXTURE = "./test/fixtures/dividend_round.json";
    string constant OUT = "./deployments/out/hsk-demo.json";
    string constant CAPTABLE = "./deployments/params/hsk-captable.json";

    bytes32 constant AGENT_RESEARCH = keccak256("blockid.agent.research");
    bytes32 constant AGENT_VALUATION = keccak256("blockid.agent.valuation");
    bytes32 constant AGENT_DIVIDEND = keccak256("blockid.agent.dividend");

    function propose() external {
        address relayer = vm.envAddress("RELAYER");
        address approver = vm.envAddress("APPROVER");
        bytes32 reportHash = vm.envBytes32("REPORT_HASH");
        uint256 gasTopUp = vm.envOr("GAS_TOPUP_WEI", uint256(0.005 ether));

        vm.startBroadcast();
        address op = msg.sender;

        AgentProvenance prov = new AgentProvenance(op);
        prov.grantRole(prov.REGISTRAR_ROLE(), op);
        prov.grantRole(prov.RECORDER_ROLE(), op); // issuer service records, never approves (four-eyes)
        prov.grantRole(prov.APPROVER_ROLE(), approver);
        // policyHash = hash of the least-privilege policy each agent runs under (agents/.../policy.py)
        prov.registerAgent(AGENT_RESEARCH, "research", keccak256("policy:research:read_web,no_keys"));
        prov.registerAgent(AGENT_VALUATION, "valuation", keccak256("policy:valuation:compute_svi,no_keys"));
        prov.registerAgent(AGENT_DIVIDEND, "dividend", keccak256("policy:dividend:build_merkle,no_keys"));

        uint256 id = prov.propose(
            AGENT_VALUATION, "svi_report", reportHash, "claude-opus-5-5", "https://eth.blockid.au/hsk#svi-report"
        );

        IdentityRegistry reg = new IdentityRegistry(op);
        reg.grantRole(reg.KYC_AGENT_ROLE(), op);
        BlockIDShareToken token = new BlockIDShareToken(
            BlockIDShareToken.InitParams({
                name: "Demo Startup Pty Ltd ORD",
                symbol: "DEM-ORD",
                companyName: "Demo Startup Pty Ltd",
                companyNumber: "ACN 000 000 000",
                shareClass: "ORD",
                identityRegistry: address(reg),
                issuerSafe: op,
                transferAgent: op,
                lockupUntil: 0,
                maxShareholders: 50,
                legalDocHash: keccak256("demo-constitution-v1")
            })
        );
        DividendDistributor dist = new DividendDistributor(address(token), op);
        DemoAUD aud = new DemoAUD(op);
        CapTableAnchor anchorC = new CapTableAnchor(op);
        anchorC.grantRole(anchorC.ANCHOR_ROLE(), op);

        // gas for the human approver wallet and the gasless-claim relayer
        if (approver.balance < gasTopUp) payable(approver).transfer(gasTopUp);
        if (relayer.balance < gasTopUp) payable(relayer).transfer(gasTopUp);
        vm.stopBroadcast();

        string memory o = "out";
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeAddress(o, "operator", op);
        vm.serializeAddress(o, "relayer", relayer);
        vm.serializeAddress(o, "approver", approver);
        vm.serializeAddress(o, "agentProvenance", address(prov));
        vm.serializeAddress(o, "identityRegistry", address(reg));
        vm.serializeAddress(o, "shareToken", address(token));
        vm.serializeAddress(o, "dividendDistributor", address(dist));
        vm.serializeAddress(o, "payToken", address(aud));
        vm.serializeAddress(o, "capTableAnchor", address(anchorC));
        vm.serializeBytes32(o, "reportHash", reportHash);
        vm.writeJson(vm.serializeUint(o, "proposalId", id), OUT);

        console2.log("AgentProvenance    ", address(prov));
        console2.log("proposal id        ", id);
    }

    function execute() external {
        string memory d = vm.readFile(OUT);
        string memory fx = vm.readFile(FIXTURE);
        AgentProvenance prov = AgentProvenance(vm.parseJsonAddress(d, ".agentProvenance"));
        IdentityRegistry reg = IdentityRegistry(vm.parseJsonAddress(d, ".identityRegistry"));
        BlockIDShareToken token = BlockIDShareToken(vm.parseJsonAddress(d, ".shareToken"));
        DividendDistributor dist = DividendDistributor(vm.parseJsonAddress(d, ".dividendDistributor"));
        DemoAUD aud = DemoAUD(vm.parseJsonAddress(d, ".payToken"));
        CapTableAnchor anchorC = CapTableAnchor(vm.parseJsonAddress(d, ".capTableAnchor"));
        uint256 id = vm.parseJsonUint(d, ".proposalId");
        bytes32 reportHash = vm.parseJsonBytes32(d, ".reportHash");

        // Human gate: refuse to act on an unapproved (or tampered) agent proposal.
        require(prov.verify(id, reportHash), "agent proposal not approved by a human");

        vm.startBroadcast();
        uint256[3] memory shares = [uint256(6000), 3000, 1000];
        for (uint256 i = 0; i < 3; i++) {
            address h = vm.parseJsonAddress(fx, string.concat(".holders[", vm.toString(i), "].account"));
            reg.registerInvestor(h, 36, uint64(block.timestamp + 365 days), keccak256(abi.encode("kyc", i)));
            token.issue(h, shares[i], keccak256("board-resolution-2026-09-issue"));
        }
        token.anchorValuation(reportHash, 33600); // A$3.36M / 10k shares = 336 AUD cents per share

        // cap-table root over (holder, shares) from the Python Merkle tool (deployments/params/hsk-captable.json)
        bytes32 capRoot = vm.parseJsonBytes32(vm.readFile(CAPTABLE), ".root");
        anchorC.anchor(
            "DEM", address(token), block.chainid, uint64(block.number), capRoot, token.totalSupply(),
            "https://eth.blockid.au/hsk"
        );

        _dividendRound(fx, dist, aud);

        prov.markExecuted(id, keccak256(abi.encode(address(token), block.number)));
        vm.stopBroadcast();

        console2.log("executed proposal", id, "block", block.number);
    }

    function _dividendRound(string memory fx, DividendDistributor dist, DemoAUD aud) internal {
        uint256 total = vm.parseJsonUint(fx, ".total");
        aud.mint(msg.sender, total);
        aud.approve(address(dist), total);
        dist.createRound(
            vm.parseJsonBytes32(fx, ".root"),
            aud,
            total,
            uint64(block.number),
            uint64(block.timestamp + 30 days),
            keccak256("board-resolution-2026-09-dividend")
        );
    }
}
