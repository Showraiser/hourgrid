// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC1155} from "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {GreenHourPoints} from "./GreenHourPoints.sol";

/// @title GranularCertificate - hour-stamped clean energy certificates (1 unit = 1 Wh).
/// @notice Token id = keccak256(meterId, hourStart). Every unit is born from a settled
///         P2P trade backed by a signed meter reading, and can be retired (burned) once.
///         Retirement can be signed off-chain by the holder and submitted by anyone, so
///         households never need gas.
contract GranularCertificate is ERC1155, AccessControl, EIP712 {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    bytes32 private constant RETIRE_TYPEHASH = keccak256(
        "Retire(address holder,uint256 id,uint256 amount,string beneficiary,uint256 nonce,uint256 deadline)"
    );

    struct CertInfo {
        bytes32 meterId;
        uint64 hourStart; // unix seconds, start of the local hour
        bytes32 zone;
        uint256 minted; // Wh
        uint256 retired; // Wh
    }

    struct Retirement {
        address holder;
        uint256 id;
        uint256 amount;
        string beneficiary;
        uint64 at;
    }

    GreenHourPoints public immutable points;
    mapping(uint256 => CertInfo) public info;
    mapping(address => uint256) public nonces;
    Retirement[] public retirements;

    event CertificateMinted(uint256 indexed id, bytes32 indexed meterId, uint64 hourStart, address indexed to, uint256 amount);
    event Retired(uint256 indexed retirementId, uint256 indexed id, address indexed holder, uint256 amount, string beneficiary);

    error Expired();
    error BadSignature();
    error ZeroAmount();

    constructor(address admin, GreenHourPoints points_)
        ERC1155("")
        EIP712("HourGridCertificate", "1")
    {
        points = points_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    function certId(bytes32 meterId, uint64 hourStart) public pure returns (uint256) {
        return uint256(keccak256(abi.encode(meterId, hourStart)));
    }

    function mint(address to, bytes32 meterId, uint64 hourStart, bytes32 zone, uint256 amount)
        external
        onlyRole(MINTER_ROLE)
        returns (uint256 id)
    {
        if (amount == 0) revert ZeroAmount();
        id = certId(meterId, hourStart);
        CertInfo storage c = info[id];
        if (c.minted == 0) {
            c.meterId = meterId;
            c.hourStart = hourStart;
            c.zone = zone;
        }
        c.minted += amount;
        _mint(to, id, amount, "");
        emit CertificateMinted(id, meterId, hourStart, to, amount);
    }

    /// @notice Holder retires their own certificates.
    function retire(uint256 id, uint256 amount, string calldata beneficiary) external returns (uint256) {
        return _retire(msg.sender, id, amount, beneficiary);
    }

    /// @notice Gasless retirement: the holder signs, anyone (e.g. the DISCOM relayer) submits.
    function retireWithSig(
        address holder,
        uint256 id,
        uint256 amount,
        string calldata beneficiary,
        uint256 deadline,
        bytes calldata signature
    ) external returns (uint256) {
        if (block.timestamp > deadline) revert Expired();
        bytes32 digest = _retireDigest(holder, id, amount, keccak256(bytes(beneficiary)), deadline);
        if (ECDSA.recover(digest, signature) != holder) revert BadSignature();
        return _retire(holder, id, amount, beneficiary);
    }

    function _retireDigest(address holder, uint256 id, uint256 amount, bytes32 beneficiaryHash, uint256 deadline)
        internal
        returns (bytes32)
    {
        uint256 nonce = nonces[holder]++;
        return _hashTypedDataV4(keccak256(abi.encode(RETIRE_TYPEHASH, holder, id, amount, beneficiaryHash, nonce, deadline)));
    }

    function _retire(address holder, uint256 id, uint256 amount, string calldata beneficiary)
        internal
        returns (uint256 retirementId)
    {
        if (amount == 0) revert ZeroAmount();
        _burn(holder, id, amount); // reverts if holder lacks balance: no double retirement
        info[id].retired += amount;
        retirementId = retirements.length;
        retirements.push(Retirement(holder, id, amount, beneficiary, uint64(block.timestamp)));
        points.award(holder, amount);
        emit Retired(retirementId, id, holder, amount, beneficiary);
    }

    function retirementCount() external view returns (uint256) {
        return retirements.length;
    }

    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    function supportsInterface(bytes4 interfaceId) public view override(ERC1155, AccessControl) returns (bool) {
        return super.supportsInterface(interfaceId);
    }
}
