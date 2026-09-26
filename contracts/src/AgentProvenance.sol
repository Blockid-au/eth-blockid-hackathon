// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title AgentProvenance
/// @notice On-chain provenance and human approval for AI agent output. BlockID agents never hold keys:
///         the issuer service records each agent proposal (hash of the AI output + model id), a human approver
///         signs with their own wallet, and only an approved proposal can be marked executed.
/// @dev Four-eyes rule: the approver of a proposal must differ from the account that recorded it.
contract AgentProvenance is AccessControl {
    bytes32 public constant REGISTRAR_ROLE = keccak256("REGISTRAR_ROLE");
    bytes32 public constant RECORDER_ROLE = keccak256("RECORDER_ROLE");
    bytes32 public constant APPROVER_ROLE = keccak256("APPROVER_ROLE");

    enum Status {
        None,
        Proposed,
        Approved,
        Rejected,
        Executed
    }

    struct Agent {
        string name;
        bytes32 policyHash; // hash of the agent's permission policy (policy.py)
        bool active;
        uint64 proposals;
        uint64 approved;
        uint64 rejected;
    }

    struct Proposal {
        bytes32 agentId;
        string kind; // e.g. "svi_report", "cap_table", "dividend_round"
        bytes32 contentHash; // keccak256 of the canonical AI output
        string modelId;
        string uri;
        address recorder;
        address approver;
        uint64 proposedAt;
        uint64 decidedAt;
        bytes32 executionRef; // tx hash / object id of the action that executed it
        Status status;
    }

    mapping(bytes32 => Agent) private _agents;
    Proposal[] private _proposals;

    event AgentRegistered(bytes32 indexed agentId, string name, bytes32 policyHash);
    event AgentActiveSet(bytes32 indexed agentId, bool active);
    event Proposed(
        uint256 indexed id, bytes32 indexed agentId, string kind, bytes32 contentHash, string modelId, string uri
    );
    event Approved(uint256 indexed id, address indexed approver);
    event Rejected(uint256 indexed id, address indexed approver, string reason);
    event Executed(uint256 indexed id, bytes32 executionRef);

    error ZeroAddress();
    error UnknownAgent(bytes32 agentId);
    error AgentInactive(bytes32 agentId);
    error AgentExists(bytes32 agentId);
    error ZeroHash();
    error BadStatus(uint256 id, Status status);
    error SelfApproval(uint256 id);
    error NoProposal(uint256 id);

    constructor(address admin) {
        if (admin == address(0)) revert ZeroAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    function registerAgent(bytes32 agentId, string calldata name, bytes32 policyHash)
        external
        onlyRole(REGISTRAR_ROLE)
    {
        if (bytes(_agents[agentId].name).length != 0) revert AgentExists(agentId);
        _agents[agentId] = Agent(name, policyHash, true, 0, 0, 0);
        emit AgentRegistered(agentId, name, policyHash);
    }

    function setAgentActive(bytes32 agentId, bool active) external onlyRole(REGISTRAR_ROLE) {
        if (bytes(_agents[agentId].name).length == 0) revert UnknownAgent(agentId);
        _agents[agentId].active = active;
        emit AgentActiveSet(agentId, active);
    }

    function propose(
        bytes32 agentId,
        string calldata kind,
        bytes32 contentHash,
        string calldata modelId,
        string calldata uri
    ) external onlyRole(RECORDER_ROLE) returns (uint256 id) {
        Agent storage a = _agents[agentId];
        if (bytes(a.name).length == 0) revert UnknownAgent(agentId);
        if (!a.active) revert AgentInactive(agentId);
        if (contentHash == bytes32(0)) revert ZeroHash();
        id = _proposals.length;
        _proposals.push(
            Proposal(
                agentId, kind, contentHash, modelId, uri, msg.sender, address(0), uint64(block.timestamp), 0, 0,
                Status.Proposed
            )
        );
        a.proposals++;
        emit Proposed(id, agentId, kind, contentHash, modelId, uri);
    }

    function approve(uint256 id) external onlyRole(APPROVER_ROLE) {
        Proposal storage p = _decide(id);
        p.status = Status.Approved;
        _agents[p.agentId].approved++;
        emit Approved(id, msg.sender);
    }

    function reject(uint256 id, string calldata reason) external onlyRole(APPROVER_ROLE) {
        Proposal storage p = _decide(id);
        p.status = Status.Rejected;
        _agents[p.agentId].rejected++;
        emit Rejected(id, msg.sender, reason);
    }

    function markExecuted(uint256 id, bytes32 executionRef) external onlyRole(RECORDER_ROLE) {
        Proposal storage p = _get(id);
        if (p.status != Status.Approved) revert BadStatus(id, p.status);
        p.status = Status.Executed;
        p.executionRef = executionRef;
        emit Executed(id, executionRef);
    }

    // ---- views ----

    function getAgent(bytes32 agentId) external view returns (Agent memory) {
        return _agents[agentId];
    }

    function getProposal(uint256 id) external view returns (Proposal memory) {
        return _get(id);
    }

    function proposalCount() external view returns (uint256) {
        return _proposals.length;
    }

    /// @notice True when `contentHash` matches proposal `id` and a human approved it (approved or executed).
    function verify(uint256 id, bytes32 contentHash) external view returns (bool) {
        if (id >= _proposals.length) return false;
        Proposal storage p = _proposals[id];
        return p.contentHash == contentHash && (p.status == Status.Approved || p.status == Status.Executed);
    }

    // ---- internal ----

    function _get(uint256 id) private view returns (Proposal storage) {
        if (id >= _proposals.length) revert NoProposal(id);
        return _proposals[id];
    }

    function _decide(uint256 id) private returns (Proposal storage p) {
        p = _get(id);
        if (p.status != Status.Proposed) revert BadStatus(id, p.status);
        if (p.recorder == msg.sender) revert SelfApproval(id);
        p.approver = msg.sender;
        p.decidedAt = uint64(block.timestamp);
    }
}
