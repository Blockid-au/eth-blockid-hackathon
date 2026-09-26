// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title IdentityRegistry
/// @notice Simplified ERC-3643-style identity registry for BlockID.
///         Maps a wallet to a verified investor record (KYC status, ISO-3166 country, expiry).
///         No personal data is stored on-chain — only a hash that points to the off-chain KYC file.
/// @dev For production securities issuance, replace with the audited ERC-3643 (T-REX) suite
///      and ONCHAINID. This contract keeps the same `isVerified(address)` surface so the token
///      can be switched to the official registry without changing its transfer logic.
contract IdentityRegistry is AccessControl {
    bytes32 public constant KYC_AGENT_ROLE = keccak256("KYC_AGENT_ROLE");

    struct Investor {
        bool verified;
        uint16 country; // ISO-3166 numeric, e.g. 36 = Australia, 704 = Viet Nam
        uint64 expiresAt; // unix seconds; 0 = never
        bytes32 kycRef; // hash of the off-chain KYC record (no PII on-chain)
    }

    mapping(address => Investor) private _investors;
    mapping(uint16 => bool) public countryBlocked;

    event InvestorRegistered(address indexed wallet, uint16 country, uint64 expiresAt, bytes32 kycRef);
    event InvestorRevoked(address indexed wallet);
    event CountryBlocked(uint16 indexed country, bool blocked);

    error ZeroAddress();

    constructor(address admin) {
        if (admin == address(0)) revert ZeroAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    function registerInvestor(address wallet, uint16 country, uint64 expiresAt, bytes32 kycRef)
        external
        onlyRole(KYC_AGENT_ROLE)
    {
        if (wallet == address(0)) revert ZeroAddress();
        _investors[wallet] = Investor(true, country, expiresAt, kycRef);
        emit InvestorRegistered(wallet, country, expiresAt, kycRef);
    }

    function revokeInvestor(address wallet) external onlyRole(KYC_AGENT_ROLE) {
        delete _investors[wallet];
        emit InvestorRevoked(wallet);
    }

    function setCountryBlocked(uint16 country, bool blocked) external onlyRole(DEFAULT_ADMIN_ROLE) {
        countryBlocked[country] = blocked;
        emit CountryBlocked(country, blocked);
    }

    /// @notice ERC-3643-compatible eligibility check used by the share token on every transfer.
    function isVerified(address wallet) public view returns (bool) {
        Investor memory inv = _investors[wallet];
        if (!inv.verified) return false;
        if (inv.expiresAt != 0 && inv.expiresAt < block.timestamp) return false;
        if (countryBlocked[inv.country]) return false;
        return true;
    }

    function investorOf(address wallet) external view returns (Investor memory) {
        return _investors[wallet];
    }
}
