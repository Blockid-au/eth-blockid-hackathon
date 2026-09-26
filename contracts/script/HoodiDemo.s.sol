// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script, console2} from "forge-std/Script.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {BlockIDShareToken} from "../src/BlockIDShareToken.sol";
import {DividendDistributor} from "../src/DividendDistributor.sol";
import {DemoAUD} from "../src/DemoAUD.sol";

/// @notice End-to-end TESTNET demo on Ethereum Hoodi: deploy the share register, KYC 3 investors,
///         issue shares, anchor the SVI valuation and fund a Merkle dividend round.
///         DEMO ONLY: the deployer plays issuer Safe, KYC agent and transfer agent. In production
///         those roles belong to a Safe multisig (see DeployCompany.s.sol + docs/SECURITY.md).
/// Usage:
///   RELAYER=0x... forge script script/HoodiDemo.s.sol --rpc-url hoodi --account blockid-deployer --broadcast
contract HoodiDemo is Script {
    string constant FIXTURE = "./test/fixtures/dividend_round.json";
    string constant OUT = "./deployments/out/hoodi-demo.json";

    function run() external {
        string memory fx = vm.readFile(FIXTURE);
        address relayer = vm.envAddress("RELAYER");
        uint256 relayerGas = vm.envOr("RELAYER_FUND_WEI", uint256(0.005 ether));

        vm.startBroadcast();
        address op = msg.sender;

        IdentityRegistry reg = new IdentityRegistry(op);
        reg.grantRole(reg.KYC_AGENT_ROLE(), op);

        BlockIDShareToken token = new BlockIDShareToken(
            BlockIDShareToken.InitParams({
                name: "Demo Startup Pty Ltd ORD",
                symbol: "DEMO-ORD",
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

        // KYC + issuance: 60% / 30% / 10% so shares match the dividend fixture amounts.
        uint256[3] memory shares = [uint256(6000), 3000, 1000];
        address[3] memory holders;
        for (uint256 i = 0; i < 3; i++) {
            holders[i] = vm.parseJsonAddress(fx, string.concat(".holders[", vm.toString(i), "].account"));
            reg.registerInvestor(holders[i], 36, uint64(block.timestamp + 365 days), keccak256(abi.encode("kyc", i)));
            token.issue(holders[i], shares[i], keccak256("board-resolution-2026-09-issue"));
        }

        // SVI valuation anchor (demo report: SVI 66.77, ~A$3.36M -> 336 AUD cents/share on 10k shares)
        token.anchorValuation(keccak256("svi-report-demo-startup-66.77"), 33600);

        // Dividend round: Merkle root produced by the Python Dividend agent (fixture shared with the tests)
        uint256 total = vm.parseJsonUint(fx, ".total");
        aud.mint(op, total);
        aud.approve(address(dist), total);
        uint64 deadline = uint64(block.timestamp + 30 days);
        dist.createRound(
            vm.parseJsonBytes32(fx, ".root"), aud, total, uint64(block.number), deadline,
            keccak256("board-resolution-2026-09-dividend")
        );

        // Gas for the relayer that submits claimFor on behalf of shareholders
        if (relayerGas > 0 && relayer.balance < relayerGas) payable(relayer).transfer(relayerGas);

        vm.stopBroadcast();

        string memory o = "out";
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeAddress(o, "operator", op);
        vm.serializeAddress(o, "relayer", relayer);
        vm.serializeAddress(o, "identityRegistry", address(reg));
        vm.serializeAddress(o, "shareToken", address(token));
        vm.serializeAddress(o, "dividendDistributor", address(dist));
        vm.serializeAddress(o, "payToken", address(aud));
        vm.serializeUint(o, "roundId", 0);
        vm.serializeUint(o, "claimDeadline", deadline);
        vm.writeJson(vm.serializeUint(o, "dividendTotal", total), OUT);

        console2.log("IdentityRegistry   ", address(reg));
        console2.log("BlockIDShareToken  ", address(token));
        console2.log("DividendDistributor", address(dist));
        console2.log("DemoAUD (mAUD)     ", address(aud));
    }
}
