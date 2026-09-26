// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title DividendDistributor
/// @notice Pull-based dividend payments. For each round the Dividend agent computes, off-chain,
///         a snapshot of share balances at a record block and a Merkle tree of (holder, amount).
///         The issuer Safe approves the round (root + funding) and holders claim with a proof.
/// @dev Leaf format matches OpenZeppelin StandardMerkleTree:
///      keccak256(bytes.concat(keccak256(abi.encode(account, amount)))), sorted-pair hashing.
contract DividendDistributor is AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant ISSUER_ROLE = keccak256("ISSUER_ROLE");

    struct Round {
        bytes32 merkleRoot;
        IERC20 payToken; // e.g. AUD/USD stablecoin
        uint256 total;
        uint256 claimed;
        uint64 recordBlock; // share balances snapshot block (informational)
        uint64 claimDeadline;
        bytes32 resolutionRef; // hash of the board resolution declaring the dividend
        bool closed;
    }

    address public immutable shareToken;
    Round[] private _rounds;
    mapping(uint256 => mapping(address => bool)) public hasClaimed;

    event RoundCreated(
        uint256 indexed roundId, bytes32 merkleRoot, address payToken, uint256 total, uint64 recordBlock, uint64 deadline
    );
    event Claimed(uint256 indexed roundId, address indexed account, uint256 amount);
    event RoundClosed(uint256 indexed roundId, uint256 reclaimed);

    error InvalidProof();
    error AlreadyClaimed();
    error RoundIsClosed();
    error DeadlinePassed();
    error DeadlineNotReached();
    error BadParams();

    constructor(address shareToken_, address issuerSafe) {
        if (shareToken_ == address(0) || issuerSafe == address(0)) revert BadParams();
        shareToken = shareToken_;
        _grantRole(DEFAULT_ADMIN_ROLE, issuerSafe);
        _grantRole(ISSUER_ROLE, issuerSafe);
    }

    /// @notice Create and fund a dividend round. Caller (Safe) must have approved `total` of payToken.
    function createRound(
        bytes32 merkleRoot,
        IERC20 payToken,
        uint256 total,
        uint64 recordBlock,
        uint64 claimDeadline,
        bytes32 resolutionRef
    ) external onlyRole(ISSUER_ROLE) nonReentrant returns (uint256 roundId) {
        if (merkleRoot == bytes32(0) || total == 0 || claimDeadline <= block.timestamp) revert BadParams();
        payToken.safeTransferFrom(msg.sender, address(this), total);
        roundId = _rounds.length;
        _rounds.push(Round(merkleRoot, payToken, total, 0, recordBlock, claimDeadline, resolutionRef, false));
        emit RoundCreated(roundId, merkleRoot, address(payToken), total, recordBlock, claimDeadline);
    }

    function claim(uint256 roundId, uint256 amount, bytes32[] calldata proof) external nonReentrant {
        _claimFor(roundId, msg.sender, amount, proof);
    }

    /// @notice Anyone (e.g. a relayer paying gas on the zero-gas chain) may trigger payment to the holder.
    function claimFor(uint256 roundId, address account, uint256 amount, bytes32[] calldata proof)
        external
        nonReentrant
    {
        _claimFor(roundId, account, amount, proof);
    }

    function _claimFor(uint256 roundId, address account, uint256 amount, bytes32[] calldata proof) internal {
        Round storage r = _rounds[roundId];
        if (r.closed) revert RoundIsClosed();
        if (block.timestamp > r.claimDeadline) revert DeadlinePassed();
        if (hasClaimed[roundId][account]) revert AlreadyClaimed();
        bytes32 leaf = keccak256(bytes.concat(keccak256(abi.encode(account, amount))));
        if (!MerkleProof.verifyCalldata(proof, r.merkleRoot, leaf)) revert InvalidProof();

        hasClaimed[roundId][account] = true;
        r.claimed += amount;
        r.payToken.safeTransfer(account, amount);
        emit Claimed(roundId, account, amount);
    }

    /// @notice After the deadline the issuer reclaims unpaid funds (to be held as unclaimed dividends).
    function closeRound(uint256 roundId, address to) external onlyRole(ISSUER_ROLE) nonReentrant {
        Round storage r = _rounds[roundId];
        if (r.closed) revert RoundIsClosed();
        if (block.timestamp <= r.claimDeadline) revert DeadlineNotReached();
        r.closed = true;
        uint256 rest = r.total - r.claimed;
        if (rest > 0) r.payToken.safeTransfer(to, rest);
        emit RoundClosed(roundId, rest);
    }

    function roundCount() external view returns (uint256) {
        return _rounds.length;
    }

    function getRound(uint256 roundId) external view returns (Round memory) {
        return _rounds[roundId];
    }
}
