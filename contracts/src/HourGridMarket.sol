// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import {MeterRegistry} from "./MeterRegistry.sol";
import {GranularCertificate} from "./GranularCertificate.sol";
import {GreenHourPoints} from "./GreenHourPoints.sol";

/// @title HourGridMarket - settlement layer for 15-minute P2P energy auctions.
/// @notice The double auction clears off-chain (fast, cheap). The operator commits one
///         record per interval: the order book hash, the uniform clearing price and the
///         Merkle root of all fills. Each fill is then settled against that root, but only
///         if the seller's smart meter signed a reading showing at least that much export.
///         Settlement moves money between escrow balances, pays DISCOM network fees and
///         mints hour-stamped certificates to the buyer.
contract HourGridMarket is AccessControl, EIP712 {
    using SafeERC20 for IERC20;

    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");
    bytes32 public constant READING_TYPEHASH =
        keccak256("Reading(bytes32 meterId,uint64 intervalId,uint32 exportWh,uint32 importWh)");
    uint64 public constant INTERVAL_SECONDS = 900;

    struct Fill {
        uint64 intervalId; // unix_seconds / 900
        uint32 index; // position in the interval's fill list
        bytes32 sellerMeter;
        address seller;
        address buyer;
        uint32 wh;
        uint128 price; // micro-units of the settlement token per kWh
    }

    struct Reading {
        bytes32 meterId;
        uint64 intervalId;
        uint32 exportWh;
        uint32 importWh;
    }

    struct Interval {
        bytes32 orderbookHash;
        bytes32 fillsRoot;
        uint128 clearingPrice;
        uint32 fillCount;
        uint32 settledCount;
        uint64 committedAt;
    }

    IERC20 public immutable currency; // settlement token (tINR / tTRY / tEUR)
    MeterRegistry public immutable registry;
    GranularCertificate public immutable certificates;
    GreenHourPoints public immutable points;

    address public treasury; // DISCOM account that receives network charges
    uint128 public wheelingFee; // micro-units per kWh, split 50/50 buyer/seller
    uint128 public transactionFee; // micro-units per kWh, split 50/50 buyer/seller
    int32 public tzOffsetSeconds; // UTC offset of the market's time zone; certificates are stamped by local hour
    uint16 public physicsMarginBps = 11500; // export cap = capacity x 15 min x 115%

    mapping(address => uint256) public balanceOf; // settlement-token escrow
    mapping(uint64 => Interval) public intervals;
    mapping(uint64 => mapping(uint32 => bool)) public settled;
    mapping(bytes32 => mapping(uint64 => uint32)) public attestedExportWh;
    mapping(bytes32 => mapping(uint64 => uint32)) public soldWh;
    uint64[] public intervalIds;

    event Deposited(address indexed account, uint256 amount);
    event Withdrawn(address indexed account, uint256 amount);
    event IntervalCommitted(uint64 indexed intervalId, bytes32 orderbookHash, uint128 clearingPrice, bytes32 fillsRoot, uint32 fillCount);
    event ReadingAttested(bytes32 indexed meterId, uint64 indexed intervalId, uint32 exportWh, uint32 importWh);
    event TradeSettled(
        uint64 indexed intervalId, uint32 index, bytes32 indexed sellerMeter, address seller, address indexed buyer,
        uint32 wh, uint128 price, uint256 certificateId
    );
    event FeesUpdated(uint128 wheelingFee, uint128 transactionFee, address treasury);

    error AlreadyCommitted();
    error NotCommitted();
    error AlreadySettled();
    error InvalidProof();
    error ReadingMismatch();
    error BadMeterSignature();
    error MeterInactive();
    error SellerNotMeterOwner();
    error ExceedsPhysicalLimit(uint32 exportWh, uint256 maxWh);
    error AttestationConflict();
    error ExceedsMeteredExport(uint32 requested, uint32 available);
    error InsufficientBalance(address account, uint256 needed, uint256 available);
    error IndexOutOfRange();
    error LengthMismatch();
    error PriceBelowFees(uint128 price);

    constructor(
        address admin,
        IERC20 currency_,
        MeterRegistry registry_,
        GranularCertificate certificates_,
        GreenHourPoints points_,
        address treasury_,
        uint128 wheelingFee_,
        uint128 transactionFee_,
        int32 tzOffsetSeconds_
    ) EIP712("HourGrid", "1") {
        tzOffsetSeconds = tzOffsetSeconds_;
        currency = currency_;
        registry = registry_;
        certificates = certificates_;
        points = points_;
        treasury = treasury_;
        wheelingFee = wheelingFee_;
        transactionFee = transactionFee_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(OPERATOR_ROLE, admin);
    }

    // ------------------------------------------------------------------ escrow
    function depositFor(address account, uint256 amount) external {
        currency.safeTransferFrom(msg.sender, address(this), amount);
        balanceOf[account] += amount;
        emit Deposited(account, amount);
    }

    function withdraw(uint256 amount) external {
        uint256 bal = balanceOf[msg.sender];
        if (bal < amount) revert InsufficientBalance(msg.sender, amount, bal);
        balanceOf[msg.sender] = bal - amount;
        currency.safeTransfer(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
    }

    // ------------------------------------------------------------------ auction commit
    function commitInterval(uint64 intervalId, bytes32 orderbookHash, uint128 clearingPrice, bytes32 fillsRoot, uint32 fillCount)
        external
        onlyRole(OPERATOR_ROLE)
    {
        if (intervals[intervalId].committedAt != 0) revert AlreadyCommitted();
        intervals[intervalId] = Interval(orderbookHash, fillsRoot, clearingPrice, fillCount, 0, uint64(block.timestamp));
        intervalIds.push(intervalId);
        emit IntervalCommitted(intervalId, orderbookHash, clearingPrice, fillsRoot, fillCount);
    }

    // ------------------------------------------------------------------ settlement
    /// @notice Settle one fill. Permissionless: anyone holding the proof and the meter's
    ///         signed reading can settle, so the operator cannot censor a committed trade.
    function settle(Fill calldata f, bytes32[] calldata proof, Reading calldata r, bytes calldata meterSig)
        public
        returns (uint256 certificateId)
    {
        Interval storage iv = intervals[f.intervalId];
        if (iv.committedAt == 0) revert NotCommitted();
        if (f.index >= iv.fillCount) revert IndexOutOfRange();
        if (settled[f.intervalId][f.index]) revert AlreadySettled();
        if (!MerkleProof.verifyCalldata(proof, iv.fillsRoot, fillLeaf(f))) revert InvalidProof();

        MeterRegistry.Meter memory m = registry.meter(f.sellerMeter);
        _checkReading(f, r, meterSig, m);

        uint32 sold = soldWh[f.sellerMeter][f.intervalId] + f.wh;
        uint32 available = attestedExportWh[f.sellerMeter][f.intervalId];
        if (sold > available) revert ExceedsMeteredExport(f.wh, available - soldWh[f.sellerMeter][f.intervalId]);
        soldWh[f.sellerMeter][f.intervalId] = sold;
        settled[f.intervalId][f.index] = true;
        iv.settledCount += 1;

        _pay(f);

        if (m.kind == MeterRegistry.Kind.SOLAR) {
            certificateId = certificates.mint(f.buyer, f.sellerMeter, localHourStart(f.intervalId), m.zone, f.wh);
            points.award(f.buyer, f.wh);
        }
        emit TradeSettled(f.intervalId, f.index, f.sellerMeter, f.seller, f.buyer, f.wh, f.price, certificateId);
    }

    function settleBatch(
        Fill[] calldata fills,
        bytes32[][] calldata proofs,
        Reading[] calldata readings,
        bytes[] calldata meterSigs
    ) external {
        uint256 n = fills.length;
        if (proofs.length != n || readings.length != n || meterSigs.length != n) revert LengthMismatch();
        for (uint256 i; i < n; ++i) {
            settle(fills[i], proofs[i], readings[i], meterSigs[i]);
        }
    }

    function _checkReading(Fill calldata f, Reading calldata r, bytes calldata sig, MeterRegistry.Meter memory m)
        internal
    {
        if (r.meterId != f.sellerMeter || r.intervalId != f.intervalId) revert ReadingMismatch();
        if (!m.active) revert MeterInactive();
        if (m.owner != f.seller) revert SellerNotMeterOwner();

        bytes32 digest = _hashTypedDataV4(
            keccak256(abi.encode(READING_TYPEHASH, r.meterId, r.intervalId, r.exportWh, r.importWh))
        );
        if (ECDSA.recover(digest, sig) != m.signer) revert BadMeterSignature();

        // On-chain physics bound: a meter can never export more than its rated capacity
        // for 15 minutes (plus margin), even if the off-chain oracle were bypassed.
        uint256 maxWh = (uint256(m.capacityW) * physicsMarginBps) / 10000 / 4;
        if (r.exportWh > maxWh) revert ExceedsPhysicalLimit(r.exportWh, maxWh);

        uint32 prev = attestedExportWh[r.meterId][r.intervalId];
        if (prev == 0) {
            attestedExportWh[r.meterId][r.intervalId] = r.exportWh;
            emit ReadingAttested(r.meterId, r.intervalId, r.exportWh, r.importWh);
        } else if (prev != r.exportWh) {
            revert AttestationConflict();
        }
    }

    function _pay(Fill calldata f) internal {
        uint256 gross = (uint256(f.wh) * f.price) / 1000;
        uint256 fee = (uint256(f.wh) * (wheelingFee + transactionFee)) / 1000;
        uint256 half = fee / 2;
        if (gross < half) revert PriceBelowFees(f.price);
        uint256 buyerPays = gross + (fee - half);
        uint256 bal = balanceOf[f.buyer];
        if (bal < buyerPays) revert InsufficientBalance(f.buyer, buyerPays, bal);
        balanceOf[f.buyer] = bal - buyerPays;
        balanceOf[f.seller] += gross - half;
        balanceOf[treasury] += fee;
    }

    // ------------------------------------------------------------------ views / helpers
    function fillLeaf(Fill calldata f) public pure returns (bytes32) {
        return keccak256(
            bytes.concat(keccak256(abi.encode(f.intervalId, f.index, f.sellerMeter, f.seller, f.buyer, f.wh, f.price)))
        );
    }

    function localHourStart(uint64 intervalId) public view returns (uint64) {
        int256 t = int256(uint256(intervalId) * INTERVAL_SECONDS) + tzOffsetSeconds;
        return uint64(uint256(t - (t % 3600) - tzOffsetSeconds));
    }

    function readingDigest(Reading calldata r) external view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(READING_TYPEHASH, r.meterId, r.intervalId, r.exportWh, r.importWh)));
    }

    function intervalCount() external view returns (uint256) {
        return intervalIds.length;
    }

    // ------------------------------------------------------------------ admin
    function setFees(uint128 wheelingFee_, uint128 transactionFee_, address treasury_)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        wheelingFee = wheelingFee_;
        transactionFee = transactionFee_;
        treasury = treasury_;
        emit FeesUpdated(wheelingFee_, transactionFee_, treasury_);
    }

    function setTzOffset(int32 offset) external onlyRole(DEFAULT_ADMIN_ROLE) {
        tzOffsetSeconds = offset;
    }
}
