// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {AgentProvenance} from "../src/AgentProvenance.sol";

contract AgentProvenanceTest is Test {
    AgentProvenance prov;
    address admin = makeAddr("admin");
    address issuer = makeAddr("issuer");
    address human = makeAddr("human");
    address mallory = makeAddr("mallory");
    bytes32 constant VALUATION = keccak256("agent:valuation");
    bytes32 constant REPORT = keccak256("svi-report");

    function setUp() public {
        prov = new AgentProvenance(admin);
        vm.startPrank(admin);
        prov.grantRole(prov.REGISTRAR_ROLE(), admin);
        prov.grantRole(prov.RECORDER_ROLE(), issuer);
        prov.grantRole(prov.APPROVER_ROLE(), human);
        prov.grantRole(prov.APPROVER_ROLE(), issuer); // lets us test the four-eyes rule
        prov.registerAgent(VALUATION, "valuation", keccak256("policy-v1"));
        vm.stopPrank();
    }

    function _propose() internal returns (uint256) {
        vm.prank(issuer);
        return prov.propose(VALUATION, "svi_report", REPORT, "claude-opus-5-5", "https://eth.blockid.au/v/1");
    }

    function test_fullLifecycle() public {
        uint256 id = _propose();
        assertFalse(prov.verify(id, REPORT)); // not approved yet

        vm.prank(human);
        prov.approve(id);
        assertTrue(prov.verify(id, REPORT));
        assertFalse(prov.verify(id, keccak256("tampered")));

        vm.prank(issuer);
        prov.markExecuted(id, bytes32(uint256(0xbeef)));
        AgentProvenance.Proposal memory p = prov.getProposal(id);
        assertEq(uint8(p.status), uint8(AgentProvenance.Status.Executed));
        assertEq(p.approver, human);
        assertEq(p.recorder, issuer);
        assertTrue(prov.verify(id, REPORT));

        AgentProvenance.Agent memory a = prov.getAgent(VALUATION);
        assertEq(a.proposals, 1);
        assertEq(a.approved, 1);
    }

    function test_recorderCannotApproveOwnProposal() public {
        uint256 id = _propose();
        vm.prank(issuer);
        vm.expectRevert(abi.encodeWithSelector(AgentProvenance.SelfApproval.selector, id));
        prov.approve(id);
    }

    function test_cannotExecuteWithoutApproval() public {
        uint256 id = _propose();
        vm.prank(issuer);
        vm.expectRevert(
            abi.encodeWithSelector(AgentProvenance.BadStatus.selector, id, AgentProvenance.Status.Proposed)
        );
        prov.markExecuted(id, bytes32(0));
    }

    function test_rejectedIsFinal() public {
        uint256 id = _propose();
        vm.prank(human);
        prov.reject(id, "valuation too optimistic");
        assertFalse(prov.verify(id, REPORT));
        vm.prank(human);
        vm.expectRevert(
            abi.encodeWithSelector(AgentProvenance.BadStatus.selector, id, AgentProvenance.Status.Rejected)
        );
        prov.approve(id);
        assertEq(prov.getAgent(VALUATION).rejected, 1);
    }

    function test_onlyRolesCanAct() public {
        bytes32 recorderRole = prov.RECORDER_ROLE();
        bytes32 approverRole = prov.APPROVER_ROLE();
        vm.prank(mallory);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, mallory, recorderRole
            )
        );
        prov.propose(VALUATION, "svi_report", REPORT, "m", "");

        uint256 id = _propose();
        vm.prank(mallory);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, mallory, approverRole
            )
        );
        prov.approve(id);
    }

    function test_inactiveOrUnknownAgentCannotPropose() public {
        vm.prank(admin);
        prov.setAgentActive(VALUATION, false);
        vm.prank(issuer);
        vm.expectRevert(abi.encodeWithSelector(AgentProvenance.AgentInactive.selector, VALUATION));
        prov.propose(VALUATION, "svi_report", REPORT, "m", "");

        vm.prank(issuer);
        vm.expectRevert(abi.encodeWithSelector(AgentProvenance.UnknownAgent.selector, bytes32("x")));
        prov.propose(bytes32("x"), "svi_report", REPORT, "m", "");
    }

    function test_verifyOutOfRangeIsFalse() public view {
        assertFalse(prov.verify(42, REPORT));
    }
}
