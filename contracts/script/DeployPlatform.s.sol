// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script, console2} from "forge-std/Script.sol";
import {CapTableAnchor} from "../src/CapTableAnchor.sol";
import {DemoAUD} from "../src/DemoAUD.sol";

/// @notice One-off platform contracts for the Issuance Studio.
///         - Ethereum Hoodi (560048) / Sepolia / mainnet: CapTableAnchor(admin = deployer), ANCHOR_ROLE -> ISSUER
///         - any other chain (BlockID Chain 262626, anvil): DemoAUD(owner = ISSUER) for dividend rounds
///         Override with PLATFORM_TARGET=anchor|aud|both.
///         Addresses are written to deployments/out/platform-<chainid>.json.
/// Usage:
///   ISSUER=0x... forge script script/DeployPlatform.s.sol --rpc-url hoodi --account blockid-deployer --broadcast --slow
contract DeployPlatform is Script {
    function run() external {
        string memory target = vm.envOr("PLATFORM_TARGET", _defaultTarget());
        bool doAnchor = _eq(target, "anchor") || _eq(target, "both");
        bool doAud = _eq(target, "aud") || _eq(target, "both");
        require(doAnchor || doAud, "PLATFORM_TARGET must be anchor|aud|both");

        vm.startBroadcast();
        address deployer = msg.sender;
        address issuer = vm.envOr("ISSUER", deployer);

        string memory o = "platform";
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeAddress(o, "deployer", deployer);
        vm.serializeAddress(o, "issuer", issuer);
        string memory json = vm.serializeUint(o, "block", block.number);

        if (doAnchor) {
            CapTableAnchor a = new CapTableAnchor(deployer);
            a.grantRole(a.ANCHOR_ROLE(), issuer);
            json = vm.serializeAddress(o, "capTableAnchor", address(a));
            console2.log("CapTableAnchor", address(a));
        }
        if (doAud) {
            DemoAUD aud = new DemoAUD(issuer);
            json = vm.serializeAddress(o, "demoAUD", address(aud));
            console2.log("DemoAUD (mAUD)", address(aud));
        }
        vm.stopBroadcast();

        vm.writeJson(json, string.concat("./deployments/out/platform-", vm.toString(block.chainid), ".json"));
    }

    function _defaultTarget() internal view returns (string memory) {
        uint256 id = block.chainid;
        return (id == 560048 || id == 11155111 || id == 1) ? "anchor" : "aud";
    }

    function _eq(string memory a, string memory b) internal pure returns (bool) {
        return keccak256(bytes(a)) == keccak256(bytes(b));
    }
}
