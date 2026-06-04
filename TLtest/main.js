import fs from "fs";
import { getVisibleSatellites } from "tle.js";
const gateway_router_position = JSON.parse(
  fs.readFileSync("data/vnu_leo_router_gateway_locations.json", "utf8")
);
const { latitude_router, longitude_router, altitude_m_router } = gateway_router_position.router;
console.log("Router:", {
  latitude_router,
  longitude_router,
  altitude_m_router
});
const tle = fs.readFileSync(
  "data/constellation_tle.txt",
  "utf8"
)
const lines = tle.split("\n").filter(Boolean);
const uniquetles = [];
for (let i = 0; i < lines.length; i += 3) {
  const tleEntry = [lines[i], lines[i + 1], lines[i + 2]];
  uniquetles.push(tleEntry);
}
const allVisible_router = getVisibleSatellites({
  observerLat: latitude_router,
  observerLng: longitude_router,
  observerHeight: altitude_m_router,

  // Array of 3-line TLE arrays.
  tles: uniquetles,

  // Filters satellites above a certain elevation (0 is horizon, 90 is directly overhead).
  // E.g. 75 will only return satellites 75 degrees or greater above the horizon.
  // Defaults to 0.
  elevationThreshold: 5,

  // Defaults to current time.
  timestampMS: Date.now()
});
const Hanoi = gateway_router_position.gateways[0];
const { latitude_gateway, longitude_gateway, altitude_m_gateway } = Hanoi;
console.log("Gateway:", {
  latitude_gateway,
  longitude_gateway,
  altitude_m_gateway
});
const allVisible_Hanoi = getVisibleSatellites({
  observerLat: latitude_gateway,
  observerLng: longitude_gateway,
  observerHeight: altitude_m_gateway,
  tles: uniquetles,
  elevationThreshold: 5,
  timestampMS: Date.now()
});
const allVisible_Danang = getVisibleSatellites({
  observerLat: gateway_router_position.gateways[1].latitude_gateway,
  observerLng: gateway_router_position.gateways[1].longitude_gateway,
  observerHeight: gateway_router_position.gateways[1].altitude_m_gateway,
  tles: uniquetles,
  elevationThreshold: 5,
  timestampMS: Date.now()
});
const allVisible_HCM = getVisibleSatellites({
  observerLat: gateway_router_position.gateways[2].latitude_gateway,
  observerLng: gateway_router_position.gateways[2].longitude_gateway,
  observerHeight: gateway_router_position.gateways[2].altitude_m_gateway,
  tles: uniquetles,
  elevationThreshold: 5,
  timestampMS: Date.now()
});
console.log(allVisible_router);
console.log(allVisible_Hanoi);
console.log(allVisible_Danang);
console.log(allVisible_HCM);
console.log(uniquetles);