// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {SettlementToken} from "../src/SettlementToken.sol";
import {MeterRegistry} from "../src/MeterRegistry.sol";
import {GreenHourPoints} from "../src/GreenHourPoints.sol";
import {GranularCertificate} from "../src/GranularCertificate.sol";
import {HourGridMarket} from "../src/HourGridMarket.sol";
import {IERC1155Errors} from "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";

contract HourGridTest is Test {
    SettlementToken inr;
    MeterRegistry registry;
    GreenHourPoints points;
    GranularCertificate certs;
    HourGridMarket market;

    address admin = address(this);
    address treasury = makeAddr("discom");
    address seller = makeAddr("prosumer");
    uint256 meterKey = 0xA11CE;
    address meterSigner;
    uint256 buyerKey = 0xB0B;
    address buyer;
    bytes32 constant METER = keccak256("MTR-AP-100200");
    bytes32 constant ZONE = keccak256("AMR-FEEDER-07");

    // 2026-10-21 12:00 IST = 06:30 UTC -> intervalId = ts / 900
    uint64 constant IV = uint64(1792564200 / 900);

    function setUp() public {
        meterSigner = vm.addr(meterKey);
        buyer = vm.addr(buyerKey);
        inr = new SettlementToken(admin, "HourGrid Test Rupee", "tINR");
        registry = new MeterRegistry(admin);
        points = new GreenHourPoints(admin);
        certs = new GranularCertificate(admin, points);
        market = new HourGridMarket(admin, inr, registry, certs, points, treasury, 1_010_000, 420_000, 19800);
        certs.grantRole(certs.MINTER_ROLE(), address(market));
        points.grantRole(points.MINTER_ROLE(), address(market));
        points.grantRole(points.MINTER_ROLE(), address(certs));

        registry.register(METER, meterSigner, seller, 3000, MeterRegistry.Kind.SOLAR, ZONE); // 3 kWp
        inr.mint(admin, 1_000e6);
        inr.approve(address(market), type(uint256).max);
        market.depositFor(buyer, 100e6); // Rs 100
    }

    // ---------------------------------------------------------------- helpers
    function _fill(uint32 index, uint32 wh, uint128 price) internal view returns (HourGridMarket.Fill memory) {
        return HourGridMarket.Fill(IV, index, METER, seller, buyer, wh, price);
    }

    function _leaf(HourGridMarket.Fill memory f) internal pure returns (bytes32) {
        return keccak256(bytes.concat(keccak256(abi.encode(f.intervalId, f.index, f.sellerMeter, f.seller, f.buyer, f.wh, f.price))));
    }

    function _pair(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return a < b ? keccak256(abi.encodePacked(a, b)) : keccak256(abi.encodePacked(b, a));
    }

    function _reading(uint32 exportWh) internal pure returns (HourGridMarket.Reading memory) {
        return HourGridMarket.Reading(METER, IV, exportWh, 0);
    }

    function _sign(uint256 key, HourGridMarket.Reading memory r) internal view returns (bytes memory) {
        (uint8 v, bytes32 rr, bytes32 s) = vm.sign(key, market.readingDigest(r));
        return abi.encodePacked(rr, s, v);
    }

    function _commitSingle(HourGridMarket.Fill memory f) internal {
        market.commitInterval(IV, keccak256("book"), f.price, _leaf(f), 1);
    }

    // ---------------------------------------------------------------- tests
    function test_SettleHappyPath() public {
        HourGridMarket.Fill memory f = _fill(0, 500, 4_500_000); // 0.5 kWh at Rs 4.50
        _commitSingle(f);
        HourGridMarket.Reading memory r = _reading(600);
        uint256 id = market.settle(f, new bytes32[](0), r, _sign(meterKey, r));

        // gross 2.25, fees 0.715 split -> buyer 2.25+0.3575, seller 2.25-0.3575
        assertEq(market.balanceOf(seller), 2_250_000 - 357_500);
        assertEq(market.balanceOf(buyer), 100e6 - 2_250_000 - 357_500);
        assertEq(market.balanceOf(treasury), 715_000);
        assertEq(certs.balanceOf(buyer, id), 500);
        assertEq(id, certs.certId(METER, market.localHourStart(IV)));
        assertEq(points.balanceOf(buyer), 500);
        assertEq(market.soldWh(METER, IV), 500);
    }

    function test_LocalHourIsIST() public view {
        // 12:00 IST interval -> certificate hour starts 12:00 IST (06:30 UTC)
        assertEq(market.localHourStart(IV), 1792564200);
        // 12:45 IST interval -> same hour
        assertEq(market.localHourStart(IV + 3), 1792564200);
        // 13:00 IST -> next hour
        assertEq(market.localHourStart(IV + 4), 1792564200 + 3600);
    }

    function test_LocalHourTurkeyAndGermany() public {
        // Istanbul (UTC+3) and Berlin (UTC+1/+2) hours align with UTC hour boundaries
        HourGridMarket tr = new HourGridMarket(admin, inr, registry, certs, points, treasury, 0, 0, 10800);
        uint64 iv = uint64(1792569600 / 900); // 2026-10-21 08:00 UTC = 11:00 Istanbul
        assertEq(tr.localHourStart(iv + 2), 1792569600);
        assertEq(tr.localHourStart(iv + 4), 1792569600 + 3600);
    }

    function test_TwoFillsMerkle() public {
        HourGridMarket.Fill memory a = _fill(0, 300, 4_000_000);
        HourGridMarket.Fill memory b = _fill(1, 200, 4_000_000);
        bytes32 root = _pair(_leaf(a), _leaf(b));
        market.commitInterval(IV, keccak256("book"), 4_000_000, root, 2);
        HourGridMarket.Reading memory r = _reading(500);
        bytes memory sig = _sign(meterKey, r);
        bytes32[] memory pa = new bytes32[](1);
        pa[0] = _leaf(b);
        bytes32[] memory pb = new bytes32[](1);
        pb[0] = _leaf(a);
        market.settle(a, pa, r, sig);
        market.settle(b, pb, r, sig);
        assertEq(market.soldWh(METER, IV), 500);
        (,,,, uint32 settledCount,) = market.intervals(IV);
        assertEq(settledCount, 2);
    }

    function test_RevertDoubleSettle() public {
        HourGridMarket.Fill memory f = _fill(0, 500, 4_500_000);
        _commitSingle(f);
        HourGridMarket.Reading memory r = _reading(600);
        bytes memory sig = _sign(meterKey, r);
        market.settle(f, new bytes32[](0), r, sig);
        vm.expectRevert(HourGridMarket.AlreadySettled.selector);
        market.settle(f, new bytes32[](0), r, sig);
    }

    function test_RevertTamperedFill() public {
        HourGridMarket.Fill memory f = _fill(0, 500, 4_500_000);
        _commitSingle(f);
        f.wh = 700; // operator or attacker tries to inflate the committed trade
        HourGridMarket.Reading memory r = _reading(800);
        bytes memory sig = _sign(meterKey, r);
        vm.expectRevert(HourGridMarket.InvalidProof.selector);
        market.settle(f, new bytes32[](0), r, sig);
    }

    function test_RevertForgedMeterSignature() public {
        HourGridMarket.Fill memory f = _fill(0, 500, 4_500_000);
        _commitSingle(f);
        HourGridMarket.Reading memory r = _reading(600);
        bytes memory sig = _sign(0xBAD, r);
        vm.expectRevert(HourGridMarket.BadMeterSignature.selector);
        market.settle(f, new bytes32[](0), r, sig);
    }

    function test_RevertPhysicallyImpossibleExport() public {
        // 3 kWp can export at most 3000 * 1.15 / 4 = 862 Wh in 15 minutes
        HourGridMarket.Fill memory f = _fill(0, 800, 4_500_000);
        _commitSingle(f);
        HourGridMarket.Reading memory r = _reading(3000); // "3 kWh at 7 PM"
        bytes memory sig = _sign(meterKey, r);
        vm.expectRevert(abi.encodeWithSelector(HourGridMarket.ExceedsPhysicalLimit.selector, uint32(3000), uint256(862)));
        market.settle(f, new bytes32[](0), r, sig);
    }

    function test_RevertSellMoreThanMetered() public {
        HourGridMarket.Fill memory f = _fill(0, 500, 4_500_000);
        _commitSingle(f);
        HourGridMarket.Reading memory r = _reading(400);
        bytes memory sig = _sign(meterKey, r);
        vm.expectRevert(abi.encodeWithSelector(HourGridMarket.ExceedsMeteredExport.selector, uint32(500), uint32(400)));
        market.settle(f, new bytes32[](0), r, sig);
    }

    function test_RevertConflictingAttestation() public {
        HourGridMarket.Fill memory a = _fill(0, 100, 4_000_000);
        HourGridMarket.Fill memory b = _fill(1, 100, 4_000_000);
        market.commitInterval(IV, keccak256("book"), 4_000_000, _pair(_leaf(a), _leaf(b)), 2);
        HourGridMarket.Reading memory r1 = _reading(200);
        HourGridMarket.Reading memory r2 = _reading(250);
        bytes32[] memory pa = new bytes32[](1);
        pa[0] = _leaf(b);
        bytes32[] memory pb = new bytes32[](1);
        pb[0] = _leaf(a);
        market.settle(a, pa, r1, _sign(meterKey, r1));
        bytes memory sig2 = _sign(meterKey, r2);
        vm.expectRevert(HourGridMarket.AttestationConflict.selector);
        market.settle(b, pb, r2, sig2);
    }

    function test_RetireOnceAndDoubleRetireReverts() public {
        HourGridMarket.Fill memory f = _fill(0, 500, 4_500_000);
        _commitSingle(f);
        HourGridMarket.Reading memory r = _reading(600);
        uint256 id = market.settle(f, new bytes32[](0), r, _sign(meterKey, r));

        vm.prank(buyer);
        certs.retire(id, 500, "EV charge 21 Oct, Amaravati");
        (,,,, uint256 retired) = certs.info(id);
        assertEq(retired, 500);
        assertEq(points.balanceOf(buyer), 1000); // 500 for buying + 500 for retiring

        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(IERC1155Errors.ERC1155InsufficientBalance.selector, buyer, 0, 500, id)
        );
        certs.retire(id, 500, "same kWh again");
    }

    function test_RetireWithSigGasless() public {
        HourGridMarket.Fill memory f = _fill(0, 500, 4_500_000);
        _commitSingle(f);
        HourGridMarket.Reading memory r = _reading(600);
        uint256 id = market.settle(f, new bytes32[](0), r, _sign(meterKey, r));

        uint256 deadline = block.timestamp + 1 hours;
        bytes32 structHash = keccak256(
            abi.encode(
                keccak256("Retire(address holder,uint256 id,uint256 amount,string beneficiary,uint256 nonce,uint256 deadline)"),
                buyer, id, uint256(200), keccak256(bytes("Green Hour Society")), uint256(0), deadline
            )
        );
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", certs.domainSeparator(), structHash));
        (uint8 v, bytes32 rr, bytes32 s) = vm.sign(buyerKey, digest);
        vm.prank(makeAddr("relayer"));
        certs.retireWithSig(buyer, id, 200, "Green Hour Society", deadline, abi.encodePacked(rr, s, v));
        assertEq(certs.balanceOf(buyer, id), 300);
        // replay fails: nonce already used
        vm.expectRevert(GranularCertificate.BadSignature.selector);
        certs.retireWithSig(buyer, id, 200, "Green Hour Society", deadline, abi.encodePacked(rr, s, v));
    }

    function test_PointsAreSoulbound() public {
        points.grantRole(points.MINTER_ROLE(), admin);
        points.award(buyer, 10);
        vm.prank(buyer);
        vm.expectRevert(GreenHourPoints.Soulbound.selector);
        points.transfer(seller, 5);
    }

    function test_InsufficientBuyerBalance() public {
        address poor = makeAddr("poor");
        HourGridMarket.Fill memory f = HourGridMarket.Fill(IV, 0, METER, seller, poor, 500, 4_500_000);
        market.commitInterval(IV, keccak256("book"), f.price, _leaf(f), 1);
        HourGridMarket.Reading memory r = _reading(600);
        bytes memory sig = _sign(meterKey, r);
        vm.expectRevert();
        market.settle(f, new bytes32[](0), r, sig);
    }

    function test_OnlyOperatorCommits() public {
        vm.prank(seller);
        vm.expectRevert();
        market.commitInterval(IV, bytes32(0), 1, bytes32(0), 1);
    }

    /// Fuzz: rupees are conserved and certificates minted never exceed metered export.
    function testFuzz_ConservationAndNoOverMint(uint32 exportWh, uint32 wh, uint128 price) public {
        exportWh = uint32(bound(exportWh, 1, 862));
        wh = uint32(bound(wh, 1, 2000));
        price = uint128(bound(price, 1, 20_000_000));
        HourGridMarket.Fill memory f = _fill(0, wh, price);
        _commitSingle(f);
        HourGridMarket.Reading memory r = _reading(exportWh);
        bytes memory sig = _sign(meterKey, r);
        uint256 before = market.balanceOf(buyer) + market.balanceOf(seller) + market.balanceOf(treasury);

        // seller's half of the 1.43 Rs/kWh network fee must be covered by the price
        if (wh > exportWh || (uint256(wh) * price) / 1000 < (uint256(wh) * 1_430_000) / 1000 / 2) {
            vm.expectRevert();
            market.settle(f, new bytes32[](0), r, sig);
            return;
        }
        uint256 id = market.settle(f, new bytes32[](0), r, sig);
        uint256 afterBal = market.balanceOf(buyer) + market.balanceOf(seller) + market.balanceOf(treasury);
        assertEq(before, afterBal, "rupees not conserved");
        (,,, uint256 minted,) = certs.info(id);
        assertLe(minted, exportWh, "over-minted certificates");
    }
}
