// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {SettlementToken} from "../src/SettlementToken.sol";
import {MeterRegistry} from "../src/MeterRegistry.sol";
import {GreenHourPoints} from "../src/GreenHourPoints.sol";
import {GranularCertificate} from "../src/GranularCertificate.sol";
import {HourGridMarket} from "../src/HourGridMarket.sol";

/// forge script script/Deploy.s.sol --rpc-url $RPC_URL --private-key $OPERATOR_KEY --broadcast
/// Writes addresses to deployments/<chainId>.json for the backend to read.
/// Deploys the India profile; the backend (python -m hourgrid.deploy) deploys any country profile.
contract Deploy is Script {
    // UPERC-approved P2P charges, in micro-INR per kWh
    uint128 constant WHEELING = 1_010_000; // Rs 1.01
    uint128 constant TRANSACTION = 420_000; // Rs 0.42

    function run() external {
        vm.startBroadcast();
        address admin = msg.sender;

        SettlementToken inr = new SettlementToken(admin, "HourGrid Test Rupee", "tINR");
        MeterRegistry registry = new MeterRegistry(admin);
        GreenHourPoints points = new GreenHourPoints(admin);
        GranularCertificate certs = new GranularCertificate(admin, points);
        HourGridMarket market =
            new HourGridMarket(admin, inr, registry, certs, points, admin, WHEELING, TRANSACTION, 19800);

        certs.grantRole(certs.MINTER_ROLE(), address(market));
        points.grantRole(points.MINTER_ROLE(), address(market));
        points.grantRole(points.MINTER_ROLE(), address(certs));
        vm.stopBroadcast();

        string memory o = "deploy";
        vm.serializeAddress(o, "SettlementToken", address(inr));
        vm.serializeAddress(o, "MeterRegistry", address(registry));
        vm.serializeAddress(o, "GreenHourPoints", address(points));
        vm.serializeAddress(o, "GranularCertificate", address(certs));
        vm.serializeUint(o, "chainId", block.chainid);
        vm.serializeUint(o, "deployBlock", block.number);
        string memory json = vm.serializeAddress(o, "HourGridMarket", address(market));
        vm.writeJson(json, string.concat("deployments/", vm.toString(block.chainid), ".json"));
        console2.log("HourGridMarket", address(market));
    }
}
