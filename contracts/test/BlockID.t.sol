// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IdentityRegistry} from "../src/IdentityRegistry.sol";
import {BlockIDShareToken} from "../src/BlockIDShareToken.sol";
import {DividendDistributor} from "../src/DividendDistributor.sol";

contract MockStable is ERC20 {
    constructor() ERC20("Mock AUD Stable", "mAUD") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amt) external {
        _mint(to, amt);
    }
}

abstract contract Base is Test {
    address admin = makeAddr("issuerSafe");
    address kycAgent = makeAddr("kycAgent");
    address transferAgent = makeAddr("transferAgent");
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    address mallory = makeAddr("mallory");

    IdentityRegistry reg;
    BlockIDShareToken token;

    uint16 constant AU = 36;
    uint16 constant VN = 704;

    function _deploy(uint64 lockup, uint32 cap) internal {
        reg = new IdentityRegistry(admin);
        bytes32 kycRole = reg.KYC_AGENT_ROLE(); // read before prank (prank applies to next call only)
        vm.prank(admin);
        reg.grantRole(kycRole, kycAgent);

        token = new BlockIDShareToken(
            BlockIDShareToken.InitParams({
                name: "Demo Startup Pty Ltd ORD",
                symbol: "DEMO-ORD",
                companyName: "Demo Startup Pty Ltd",
                companyNumber: "ACN 000 000 000",
                shareClass: "ORD",
                identityRegistry: address(reg),
                issuerSafe: admin,
                transferAgent: transferAgent,
                lockupUntil: lockup,
                maxShareholders: cap,
                legalDocHash: keccak256("constitution-v1")
            })
        );
    }

    function _kyc(address w, uint16 country) internal {
        vm.prank(kycAgent);
        reg.registerInvestor(w, country, 0, keccak256(abi.encode(w)));
    }
}

contract ShareTokenTest is Base {
    function setUp() public {
        _deploy(0, 50);
        _kyc(alice, AU);
        _kyc(bob, VN);
    }

    function test_DecimalsZero() public view {
        assertEq(token.decimals(), 0);
    }

    function test_IssueToVerified() public {
        vm.prank(admin);
        token.issue(alice, 1000, keccak256("res-1"));
        assertEq(token.balanceOf(alice), 1000);
        assertEq(token.shareholderCount(), 1);
    }

    function test_RevertIssueToUnverified() public {
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(BlockIDShareToken.NotVerified.selector, mallory));
        token.issue(mallory, 10, bytes32(0));
    }

    function test_RevertIssueByNonIssuer() public {
        vm.prank(mallory);
        vm.expectRevert();
        token.issue(alice, 10, bytes32(0));
    }

    function test_TransferBetweenVerified() public {
        vm.prank(admin);
        token.issue(alice, 100, bytes32(0));
        vm.prank(alice);
        token.transfer(bob, 40);
        assertEq(token.balanceOf(bob), 40);
        assertEq(token.shareholderCount(), 2);
    }

    function test_RevertTransferToUnverified() public {
        vm.prank(admin);
        token.issue(alice, 100, bytes32(0));
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(BlockIDShareToken.NotVerified.selector, mallory));
        token.transfer(mallory, 1);
    }

    function test_RevertWhenFrozen() public {
        vm.prank(admin);
        token.issue(alice, 100, bytes32(0));
        vm.prank(transferAgent);
        token.setFrozen(alice, true);
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(BlockIDShareToken.WalletIsFrozen.selector, alice));
        token.transfer(bob, 1);
    }

    function test_RevertWhenPaused() public {
        vm.prank(admin);
        token.issue(alice, 100, bytes32(0));
        vm.prank(admin);
        token.pause();
        vm.prank(alice);
        vm.expectRevert();
        token.transfer(bob, 1);
    }

    function test_KycExpiryBlocksReceive() public {
        address carol = makeAddr("carol");
        vm.prank(kycAgent);
        reg.registerInvestor(carol, AU, uint64(block.timestamp + 1 days), bytes32(0));
        vm.warp(block.timestamp + 2 days);
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(BlockIDShareToken.NotVerified.selector, carol));
        token.issue(carol, 1, bytes32(0));
    }

    function test_ForcedTransferRecovery() public {
        vm.prank(admin);
        token.issue(alice, 100, bytes32(0));
        vm.prank(transferAgent);
        token.setFrozen(alice, true);
        vm.prank(transferAgent);
        token.forcedTransfer(alice, bob, 100, keccak256("lost-wallet-claim-17"));
        assertEq(token.balanceOf(bob), 100);
        assertEq(token.shareholderCount(), 1);
    }

    function test_AnchorValuation() public {
        vm.prank(admin);
        token.anchorValuation(keccak256("svi-report"), 125);
        assertEq(token.valuationPerShareCents(), 125);
    }

    function testFuzz_TransferKeepsSupply(uint96 issued, uint96 moved) public {
        vm.assume(issued > 0);
        moved = uint96(bound(moved, 0, issued));
        vm.prank(admin);
        token.issue(alice, issued, bytes32(0));
        vm.prank(alice);
        token.transfer(bob, moved);
        assertEq(token.totalSupply(), issued);
        assertEq(token.balanceOf(alice) + token.balanceOf(bob), issued);
    }
}

contract LockupAndCapTest is Base {
    function setUp() public {
        _deploy(uint64(block.timestamp + 365 days), 2);
        _kyc(alice, AU);
        _kyc(bob, AU);
        _kyc(mallory, AU);
    }

    function test_RevertTransferDuringLockup() public {
        vm.prank(admin);
        token.issue(alice, 100, bytes32(0));
        vm.prank(alice);
        vm.expectRevert();
        token.transfer(bob, 1);
    }

    function test_TransferAfterLockup() public {
        vm.prank(admin);
        token.issue(alice, 100, bytes32(0));
        vm.warp(block.timestamp + 366 days);
        vm.prank(alice);
        token.transfer(bob, 1);
        assertEq(token.balanceOf(bob), 1);
    }

    function test_RevertShareholderCap() public {
        vm.startPrank(admin);
        token.issue(alice, 1, bytes32(0));
        token.issue(bob, 1, bytes32(0));
        vm.expectRevert(abi.encodeWithSelector(BlockIDShareToken.ShareholderCapReached.selector, uint32(2)));
        token.issue(mallory, 1, bytes32(0));
        vm.stopPrank();
    }
}

/// Uses a Merkle tree generated by the Python Dividend agent (agents/.../merkle.py)
/// to prove both sides compute identical leaves, proofs and roots.
contract DividendDistributorTest is Base {
    DividendDistributor dist;
    MockStable stable;
    string fixture;

    function setUp() public {
        _deploy(0, 0);
        dist = new DividendDistributor(address(token), admin);
        stable = new MockStable();
        fixture = vm.readFile("./test/fixtures/dividend_round.json");

        uint256 total = vm.parseJsonUint(fixture, ".total");
        stable.mint(admin, total);
        vm.startPrank(admin);
        stable.approve(address(dist), total);
        dist.createRound(
            vm.parseJsonBytes32(fixture, ".root"),
            stable,
            total,
            uint64(block.number),
            uint64(block.timestamp + 30 days),
            keccak256("board-resolution-2026-09")
        );
        vm.stopPrank();
    }

    function _holder(uint256 i) internal view returns (address a, uint256 amt, bytes32[] memory proof) {
        string memory p = string.concat(".holders[", vm.toString(i), "]");
        a = vm.parseJsonAddress(fixture, string.concat(p, ".account"));
        amt = vm.parseJsonUint(fixture, string.concat(p, ".amount"));
        proof = vm.parseJsonBytes32Array(fixture, string.concat(p, ".proof"));
    }

    function test_AllHoldersClaimWithPythonProofs() public {
        uint256 total = vm.parseJsonUint(fixture, ".total");
        for (uint256 i = 0; i < 3; i++) {
            (address a, uint256 amt, bytes32[] memory proof) = _holder(i);
            dist.claimFor(0, a, amt, proof); // relayer pays gas
            assertEq(stable.balanceOf(a), amt);
        }
        assertEq(stable.balanceOf(address(dist)), 0);
        assertEq(dist.getRound(0).claimed, total);
    }

    function test_RevertDoubleClaim() public {
        (address a, uint256 amt, bytes32[] memory proof) = _holder(0);
        dist.claimFor(0, a, amt, proof);
        vm.expectRevert(DividendDistributor.AlreadyClaimed.selector);
        dist.claimFor(0, a, amt, proof);
    }

    function test_RevertWrongAmount() public {
        (address a, uint256 amt, bytes32[] memory proof) = _holder(1);
        vm.expectRevert(DividendDistributor.InvalidProof.selector);
        dist.claimFor(0, a, amt + 1, proof);
    }

    function test_CloseRoundReclaimsRest() public {
        (address a, uint256 amt, bytes32[] memory proof) = _holder(0);
        dist.claimFor(0, a, amt, proof);
        vm.warp(block.timestamp + 31 days);
        vm.prank(admin);
        dist.closeRound(0, admin);
        assertEq(stable.balanceOf(admin), vm.parseJsonUint(fixture, ".total") - amt);
    }

    function test_RevertCloseBeforeDeadline() public {
        vm.prank(admin);
        vm.expectRevert(DividendDistributor.DeadlineNotReached.selector);
        dist.closeRound(0, admin);
    }
}
