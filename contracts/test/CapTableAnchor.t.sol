// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {CapTableAnchor} from "../src/CapTableAnchor.sol";
import {DemoAUD} from "../src/DemoAUD.sol";

contract CapTableAnchorTest is Test {
    CapTableAnchor anchorC;
    address admin = makeAddr("admin");
    address issuer = makeAddr("issuer");
    address mallory = makeAddr("mallory");
    address localToken = makeAddr("localToken");

    // 3-leaf OZ StandardMerkleTree produced by the Python tooling (same leaf format as dividends)
    string constant FIXTURE = "./test/fixtures/dividend_round.json";
    string fx;
    bytes32 root;

    event Anchored(
        string indexed tickerHash,
        string ticker,
        address localToken,
        uint256 localChainId,
        uint64 localBlock,
        bytes32 merkleRoot,
        uint256 totalSupply,
        string uri,
        uint256 anchorIndex
    );

    function setUp() public {
        anchorC = new CapTableAnchor(admin);
        bytes32 role = anchorC.ANCHOR_ROLE();
        vm.prank(admin);
        anchorC.grantRole(role, issuer);
        fx = vm.readFile(FIXTURE);
        root = vm.parseJsonBytes32(fx, ".root");
    }

    function _anchor(string memory t, bytes32 r, uint64 blk) internal returns (uint256) {
        vm.prank(issuer);
        return anchorC.anchor(t, localToken, 262626, blk, r, 999999999, "https://eth.blockid.au/c/ABC");
    }

    function test_AnchorStoresLatestAndEmits() public {
        vm.expectEmit(true, false, false, true);
        emit Anchored("ABC", "ABC", localToken, 262626, 42, root, 999999999, "https://eth.blockid.au/c/ABC", 0);
        uint256 idx = _anchor("ABC", root, 42);
        assertEq(idx, 0);
        CapTableAnchor.Anchor memory a = anchorC.latest("ABC");
        assertEq(a.localToken, localToken);
        assertEq(a.localChainId, 262626);
        assertEq(a.localBlock, 42);
        assertEq(a.merkleRoot, root);
        assertEq(a.totalSupply, 999999999);
        assertEq(a.uri, "https://eth.blockid.au/c/ABC");
        assertEq(a.anchoredAt, block.timestamp);
        assertEq(anchorC.anchorCount("ABC"), 1);
        assertEq(anchorC.anchorCount("XYZ"), 0);
    }

    function test_MultipleAnchorsKeepHistory() public {
        _anchor("ABC", keccak256("r1"), 10);
        _anchor("XYZ", keccak256("x1"), 11);
        uint256 idx = _anchor("ABC", keccak256("r2"), 20);
        assertEq(idx, 1);
        assertEq(anchorC.anchorCount("ABC"), 2);
        assertEq(anchorC.anchorCount("XYZ"), 1);
        assertEq(anchorC.latest("ABC").merkleRoot, keccak256("r2"));
        assertEq(anchorC.latest("ABC").localBlock, 20);
        assertEq(anchorC.anchorAt("ABC", 0).merkleRoot, keccak256("r1"));
        assertEq(anchorC.latest("XYZ").merkleRoot, keccak256("x1"));
    }

    function test_RevertAnchorWithoutRole() public {
        bytes32 role = anchorC.ANCHOR_ROLE();
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, mallory, role));
        vm.prank(mallory);
        anchorC.anchor("ABC", localToken, 262626, 1, root, 1, "");
    }

    function test_AdminCanRevokeAnchorRole() public {
        bytes32 role = anchorC.ANCHOR_ROLE();
        vm.prank(admin);
        anchorC.revokeRole(role, issuer);
        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, issuer, role));
        vm.prank(issuer);
        anchorC.anchor("ABC", localToken, 262626, 1, root, 1, "");
    }

    function test_RevertEmptyTickerOrZeroRoot() public {
        vm.startPrank(issuer);
        vm.expectRevert(CapTableAnchor.EmptyTicker.selector);
        anchorC.anchor("", localToken, 262626, 1, root, 1, "");
        vm.expectRevert(CapTableAnchor.ZeroRoot.selector);
        anchorC.anchor("ABC", localToken, 262626, 1, bytes32(0), 1, "");
        vm.stopPrank();
    }

    function test_RevertLatestWhenNone() public {
        vm.expectRevert(abi.encodeWithSelector(CapTableAnchor.NoAnchor.selector, "NOP"));
        anchorC.latest("NOP");
    }

    function test_VerifyAllHoldersWithPythonProofs() public {
        _anchor("ABC", root, 42);
        for (uint256 i = 0; i < 3; i++) {
            string memory k = string.concat(".holders[", vm.toString(i), "]");
            address acc = vm.parseJsonAddress(fx, string.concat(k, ".account"));
            uint256 amt = vm.parseJsonUint(fx, string.concat(k, ".amount"));
            bytes32[] memory proof = vm.parseJsonBytes32Array(fx, string.concat(k, ".proof"));
            assertTrue(anchorC.verify("ABC", acc, amt, proof));
            assertFalse(anchorC.verify("ABC", acc, amt + 1, proof));
            assertFalse(anchorC.verify("XYZ", acc, amt, proof)); // other ticker has no anchor
        }
    }

    function test_VerifyUsesLatestRoot() public {
        _anchor("ABC", root, 42);
        address acc = vm.parseJsonAddress(fx, ".holders[2].account");
        uint256 amt = vm.parseJsonUint(fx, ".holders[2].amount");
        bytes32[] memory proof = vm.parseJsonBytes32Array(fx, ".holders[2].proof");
        assertTrue(anchorC.verify("ABC", acc, amt, proof));
        _anchor("ABC", keccak256("new-cap-table"), 43);
        assertFalse(anchorC.verify("ABC", acc, amt, proof));
    }

    function test_RevertZeroAdmin() public {
        vm.expectRevert(CapTableAnchor.ZeroAddress.selector);
        new CapTableAnchor(address(0));
    }

    function test_DemoAUDOwnerMint() public {
        DemoAUD aud = new DemoAUD(issuer);
        assertEq(aud.decimals(), 6);
        vm.prank(issuer);
        aud.mint(mallory, 5e6);
        assertEq(aud.balanceOf(mallory), 5e6);
        vm.expectRevert();
        vm.prank(mallory);
        aud.mint(mallory, 1);
    }
}
