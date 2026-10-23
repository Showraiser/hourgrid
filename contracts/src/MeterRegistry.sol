// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title MeterRegistry - DISCOM-maintained list of smart meters allowed to trade.
/// @notice Mirrors India's P2P pilots: only a DISCOM can onboard a meter, and each
///         meter has a signing key (in production, the AMI head-end or a secure element).
contract MeterRegistry is AccessControl {
    bytes32 public constant DISCOM_ROLE = keccak256("DISCOM_ROLE");

    enum Kind {
        CONSUMER,
        SOLAR,
        BATTERY
    }

    struct Meter {
        address signer; // key that signs 15-minute readings
        address owner; // wallet that receives payments and certificates
        uint32 capacityW; // PV peak (W) or battery inverter rating (W)
        Kind kind;
        bytes32 zone; // feeder / distribution transformer
        bool active;
    }

    mapping(bytes32 => Meter) private _meters;
    bytes32[] public meterIds;

    event MeterRegistered(bytes32 indexed meterId, address signer, address owner, uint32 capacityW, Kind kind, bytes32 zone);
    event MeterStatusChanged(bytes32 indexed meterId, bool active);

    error MeterExists();
    error UnknownMeter();
    error ZeroAddress();

    constructor(address admin) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(DISCOM_ROLE, admin);
    }

    function register(bytes32 meterId, address signer, address owner, uint32 capacityW, Kind kind, bytes32 zone)
        external
        onlyRole(DISCOM_ROLE)
    {
        if (_meters[meterId].signer != address(0)) revert MeterExists();
        if (signer == address(0) || owner == address(0)) revert ZeroAddress();
        _meters[meterId] = Meter(signer, owner, capacityW, kind, zone, true);
        meterIds.push(meterId);
        emit MeterRegistered(meterId, signer, owner, capacityW, kind, zone);
    }

    function setActive(bytes32 meterId, bool active) external onlyRole(DISCOM_ROLE) {
        if (_meters[meterId].signer == address(0)) revert UnknownMeter();
        _meters[meterId].active = active;
        emit MeterStatusChanged(meterId, active);
    }

    function meter(bytes32 meterId) external view returns (Meter memory m) {
        m = _meters[meterId];
        if (m.signer == address(0)) revert UnknownMeter();
    }

    function meterCount() external view returns (uint256) {
        return meterIds.length;
    }
}
