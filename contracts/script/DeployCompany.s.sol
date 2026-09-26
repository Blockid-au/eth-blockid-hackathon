// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script, console2} from "forge-std/Script.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {BlockIDShareToken} from "../src/BlockIDShareToken.sol";
import {DividendDistributor} from "../src/DividendDistributor.sol";

/// @notice Deploys one company's share register from a params JSON produced (and human-approved)
///         by the Contract Builder agent. The agent never writes Solidity — only this JSON.
/// Usage:
///   PARAMS_FILE=deployments/params/<company>.json \
///   forge script script/DeployCompany.s.sol --rpc-url blockid_chain --broadcast --account deployer
/// The deployer key lives in the operator's keystore / hardware wallet, never on the AI VM.
contract DeployCompany is Script {
    function run() external {
        string memory json = vm.readFile(vm.envString("PARAMS_FILE"));

        address issuerSafe = vm.parseJsonAddress(json, ".issuerSafe");
        address transferAgent = vm.parseJsonAddress(json, ".transferAgent");
        address kycAgent = vm.parseJsonAddress(json, ".kycAgent");
        address existingRegistry = vm.parseJsonAddress(json, ".identityRegistry");

        vm.startBroadcast();

        IdentityRegistry reg;
        if (existingRegistry == address(0)) {
            // Deployer is temporary admin only to wire the KYC agent, then hands admin to the Safe.
            reg = new IdentityRegistry(msg.sender);
            reg.grantRole(reg.KYC_AGENT_ROLE(), kycAgent);
            reg.grantRole(reg.DEFAULT_ADMIN_ROLE(), issuerSafe);
            reg.renounceRole(reg.DEFAULT_ADMIN_ROLE(), msg.sender);
        } else {
            reg = IdentityRegistry(existingRegistry);
        }

        BlockIDShareToken token = new BlockIDShareToken(
            BlockIDShareToken.InitParams({
                name: vm.parseJsonString(json, ".name"),
                symbol: vm.parseJsonString(json, ".symbol"),
                companyName: vm.parseJsonString(json, ".companyName"),
                companyNumber: vm.parseJsonString(json, ".companyNumber"),
                shareClass: vm.parseJsonString(json, ".shareClass"),
                identityRegistry: address(reg),
                issuerSafe: issuerSafe,
                transferAgent: transferAgent,
                lockupUntil: uint64(vm.parseJsonUint(json, ".lockupUntil")),
                maxShareholders: uint32(vm.parseJsonUint(json, ".maxShareholders")),
                legalDocHash: vm.parseJsonBytes32(json, ".legalDocHash")
            })
        );

        DividendDistributor dist = new DividendDistributor(address(token), issuerSafe);

        vm.stopBroadcast();

        console2.log("IdentityRegistry   ", address(reg));
        console2.log("BlockIDShareToken  ", address(token));
        console2.log("DividendDistributor", address(dist));
    }
}
