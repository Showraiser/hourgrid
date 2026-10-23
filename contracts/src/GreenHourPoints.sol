// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title GreenHourPoints - soulbound reward points (1 point = 1 Wh of clean action).
/// @notice Earned by buying neighbour solar and by retiring certificates. Non-transferable
///         on purpose: an incentive, not a speculative token.
contract GreenHourPoints is ERC20, AccessControl {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    error Soulbound();

    constructor(address admin) ERC20("HourGrid Green Hour Points", "GHP") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    function decimals() public pure override returns (uint8) {
        return 0;
    }

    function award(address to, uint256 amount) external onlyRole(MINTER_ROLE) {
        _mint(to, amount);
    }

    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0)) revert Soulbound();
        super._update(from, to, value);
    }
}
