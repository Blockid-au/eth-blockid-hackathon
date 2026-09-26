// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Demo-only stablecoin for testnet dividend rounds (6 decimals, owner-mintable).
contract DemoAUD is ERC20, Ownable {
    constructor(address owner_) ERC20("BlockID Demo AUD", "mAUD") Ownable(owner_) {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amt) external onlyOwner {
        _mint(to, amt);
    }
}
