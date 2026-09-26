// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

/// @title CapTableAnchor
/// @notice Deployed once on Ethereum (Hoodi testnet). The BlockID issuer service periodically anchors the
///         cap table of each company issued on BlockID Chain: a Merkle root over (holder, balance) leaves at a
///         given BlockID Chain block. Anyone can then verify a holder's balance against the anchored root.
/// @dev Leaf format matches OpenZeppelin StandardMerkleTree for ["address","uint256"]:
///      keccak256(bytes.concat(keccak256(abi.encode(holder, balance)))), sorted-pair hashing.
contract CapTableAnchor is AccessControl {
    bytes32 public constant ANCHOR_ROLE = keccak256("ANCHOR_ROLE");

    struct Anchor {
        address localToken; // share token on BlockID Chain
        uint256 localChainId; // 262626
        uint64 localBlock; // BlockID Chain block of the cap table snapshot
        bytes32 merkleRoot; // OZ StandardMerkleTree root over (holder, balance)
        uint256 totalSupply;
        string uri; // public page describing the company / snapshot
        uint64 anchoredAt; // timestamp on this chain
        uint256 anchorIndex; // 0-based index within this ticker's history
    }

    mapping(bytes32 => Anchor[]) private _history;

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

    error EmptyTicker();
    error ZeroRoot();
    error NoAnchor(string ticker);
    error ZeroAddress();

    constructor(address admin) {
        if (admin == address(0)) revert ZeroAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    function anchor(
        string calldata ticker,
        address localToken,
        uint256 localChainId,
        uint64 localBlock,
        bytes32 merkleRoot,
        uint256 totalSupply,
        string calldata uri
    ) external onlyRole(ANCHOR_ROLE) returns (uint256 anchorIndex) {
        if (bytes(ticker).length == 0) revert EmptyTicker();
        if (merkleRoot == bytes32(0)) revert ZeroRoot();
        Anchor[] storage h = _history[keccak256(bytes(ticker))];
        anchorIndex = h.length;
        h.push(
            Anchor(localToken, localChainId, localBlock, merkleRoot, totalSupply, uri, uint64(block.timestamp), anchorIndex)
        );
        emit Anchored(ticker, ticker, localToken, localChainId, localBlock, merkleRoot, totalSupply, uri, anchorIndex);
    }

    /// @notice Latest anchor for `ticker` (reverts if none).
    function latest(string calldata ticker) external view returns (Anchor memory) {
        Anchor[] storage h = _history[keccak256(bytes(ticker))];
        if (h.length == 0) revert NoAnchor(ticker);
        return h[h.length - 1];
    }

    function anchorCount(string calldata ticker) external view returns (uint256) {
        return _history[keccak256(bytes(ticker))].length;
    }

    function anchorAt(string calldata ticker, uint256 index) external view returns (Anchor memory) {
        return _history[keccak256(bytes(ticker))][index];
    }

    /// @notice True if (holder, balance) is a leaf of the latest anchored root for `ticker`.
    function verify(string calldata ticker, address holder, uint256 balance, bytes32[] calldata proof)
        external
        view
        returns (bool)
    {
        Anchor[] storage h = _history[keccak256(bytes(ticker))];
        if (h.length == 0) return false;
        bytes32 leaf = keccak256(bytes.concat(keccak256(abi.encode(holder, balance))));
        return MerkleProof.verifyCalldata(proof, h[h.length - 1].merkleRoot, leaf);
    }
}
