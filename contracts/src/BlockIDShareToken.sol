// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {IdentityRegistry} from "./IdentityRegistry.sol";

/// @title BlockIDShareToken
/// @notice Permissioned digital share register for one share class of one company.
///         - 1 token = 1 share (decimals = 0)
///         - Only KYC-verified wallets (IdentityRegistry) can receive shares
///         - Issuer role (held by a Safe multisig) mints/burns according to the off-chain cap table
///         - Transfer lock-up, per-wallet freeze, global pause, shareholder cap
///         - Legal document hash + SVI valuation report hash anchored on-chain
/// @dev Deployed from JSON parameters produced by the Contract Builder agent (no AI-written Solidity).
contract BlockIDShareToken is ERC20, AccessControl, Pausable {
    bytes32 public constant ISSUER_ROLE = keccak256("ISSUER_ROLE"); // Safe multisig
    bytes32 public constant TRANSFER_AGENT_ROLE = keccak256("TRANSFER_AGENT_ROLE"); // freeze / recovery
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");

    IdentityRegistry public immutable identityRegistry;
    string public companyName;
    string public companyNumber; // ACN / ABN / MST
    string public shareClass; // e.g. "ORD", "PREF-A"
    uint64 public immutable lockupUntil; // no secondary transfers before this time
    uint32 public immutable maxShareholders; // 0 = unlimited
    uint32 public shareholderCount;

    bytes32 public legalDocHash; // hash of constitution / shareholders agreement
    bytes32 public valuationReportHash; // hash of the latest SVI report
    uint256 public valuationPerShareCents; // latest valuation (AUD cents) — informational only

    mapping(address => bool) public frozen;

    event SharesIssued(address indexed to, uint256 amount, bytes32 indexed resolutionRef);
    event SharesCancelled(address indexed from, uint256 amount, bytes32 indexed resolutionRef);
    event ForcedTransfer(address indexed from, address indexed to, uint256 amount, bytes32 indexed courtOrReason);
    event WalletFrozen(address indexed wallet, bool frozen);
    event LegalDocUpdated(bytes32 docHash);
    event ValuationAnchored(bytes32 reportHash, uint256 valuationPerShareCents);

    error NotVerified(address wallet);
    error WalletIsFrozen(address wallet);
    error LockupActive(uint64 until);
    error ShareholderCapReached(uint32 cap);
    error ZeroAddress();

    struct InitParams {
        string name;
        string symbol;
        string companyName;
        string companyNumber;
        string shareClass;
        address identityRegistry;
        address issuerSafe;
        address transferAgent;
        uint64 lockupUntil;
        uint32 maxShareholders;
        bytes32 legalDocHash;
    }

    constructor(InitParams memory p) ERC20(p.name, p.symbol) {
        if (p.identityRegistry == address(0) || p.issuerSafe == address(0) || p.transferAgent == address(0)) {
            revert ZeroAddress();
        }
        identityRegistry = IdentityRegistry(p.identityRegistry);
        companyName = p.companyName;
        companyNumber = p.companyNumber;
        shareClass = p.shareClass;
        lockupUntil = p.lockupUntil;
        maxShareholders = p.maxShareholders;
        legalDocHash = p.legalDocHash;

        _grantRole(DEFAULT_ADMIN_ROLE, p.issuerSafe);
        _grantRole(ISSUER_ROLE, p.issuerSafe);
        _grantRole(PAUSER_ROLE, p.issuerSafe);
        _grantRole(TRANSFER_AGENT_ROLE, p.transferAgent);
    }

    function decimals() public pure override returns (uint8) {
        return 0;
    }

    // ---------------------------------------------------------------- issuer actions (multisig)

    function issue(address to, uint256 amount, bytes32 resolutionRef) external onlyRole(ISSUER_ROLE) {
        _mint(to, amount);
        emit SharesIssued(to, amount, resolutionRef);
    }

    function cancel(address from, uint256 amount, bytes32 resolutionRef) external onlyRole(ISSUER_ROLE) {
        _burn(from, amount);
        emit SharesCancelled(from, amount, resolutionRef);
    }

    function anchorValuation(bytes32 reportHash, uint256 perShareCents) external onlyRole(ISSUER_ROLE) {
        valuationReportHash = reportHash;
        valuationPerShareCents = perShareCents;
        emit ValuationAnchored(reportHash, perShareCents);
    }

    function setLegalDocHash(bytes32 docHash) external onlyRole(ISSUER_ROLE) {
        legalDocHash = docHash;
        emit LegalDocUpdated(docHash);
    }

    function pause() external onlyRole(PAUSER_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    // ---------------------------------------------------------------- transfer agent actions

    function setFrozen(address wallet, bool isFrozen) external onlyRole(TRANSFER_AGENT_ROLE) {
        frozen[wallet] = isFrozen;
        emit WalletFrozen(wallet, isFrozen);
    }

    /// @notice Recovery / court-ordered transfer (e.g. lost wallet). Bypasses lock-up and freeze,
    ///         but the receiver must still be a verified investor.
    function forcedTransfer(address from, address to, uint256 amount, bytes32 reason)
        external
        onlyRole(TRANSFER_AGENT_ROLE)
    {
        _forced = true;
        _transfer(from, to, amount);
        _forced = false;
        emit ForcedTransfer(from, to, amount, reason);
    }

    bool private _forced;

    // ---------------------------------------------------------------- compliance hook

    function _update(address from, address to, uint256 value) internal override {
        bool isMint = from == address(0);
        bool isBurn = to == address(0);

        if (!isBurn) {
            if (!identityRegistry.isVerified(to)) revert NotVerified(to);
        }
        if (!isMint && !isBurn && !_forced) {
            _requireNotPaused();
            if (frozen[from]) revert WalletIsFrozen(from);
            if (frozen[to]) revert WalletIsFrozen(to);
            if (block.timestamp < lockupUntil) revert LockupActive(lockupUntil);
            if (!identityRegistry.isVerified(from)) revert NotVerified(from);
        }

        bool toWasEmpty = !isBurn && balanceOf(to) == 0 && value > 0;
        super._update(from, to, value);
        bool fromNowEmpty = !isMint && balanceOf(from) == 0 && value > 0;

        if (toWasEmpty) {
            shareholderCount += 1;
            if (maxShareholders != 0 && shareholderCount > maxShareholders) {
                revert ShareholderCapReached(maxShareholders);
            }
        }
        if (fromNowEmpty) shareholderCount -= 1;
    }
}
