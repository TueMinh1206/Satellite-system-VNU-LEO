const express = require('express');
const cors = require('cors');
const fs = require('fs');
const { getVisibleSatellites } = require('tle.js');
const path = require('path');
const satellite = require('satellite.js');
const { calculatePathLoss, calculateCN, calculateSignalQuality } = require('./utils/physics');
const {
    calculateLatency,
    calculatePing,
    calculateThroughput,
    calculatePacketLoss,
    calculateJitter,
    calculateLinkScore
} = require('./utils/network');

const app = express();
const port = 3001;

app.use(cors());
app.use(express.json());

// Frequency configuration (Ku-band)
const FREQUENCY_MHZ = 12000;

// Connection History (in-memory)
let connectionHistory = [];

// Load locations
const locationsPath = path.join(__dirname, 'data', 'vnu_leo_router_gateway_locations.json');
const gateway_router_position = JSON.parse(fs.readFileSync(locationsPath, 'utf8'));

// Load TLE
const tlePath = path.join(__dirname, 'data', 'constellation_tle.txt');
const tleData = fs.readFileSync(tlePath, 'utf8');
const lines = tleData.split('\n').filter(Boolean);
const uniquetles = [];
for (let i = 0; i < lines.length; i += 3) {
    uniquetles.push([lines[i], lines[i + 1], lines[i + 2]]);
}

// Helper: get visible satellites for an observer
function getVisibleFromStore(observer, timestampMS) {
    const lat = observer.latitude_router || observer.latitude_gateway;
    const lng = observer.longitude_router || observer.longitude_gateway;
    const alt = observer.altitude_m_router || observer.altitude_m_gateway;
    return getVisibleSatellites({
        observerLat: lat,
        observerLng: lng,
        observerHeight: alt / 1000, // m → km
        tles: uniquetles,
        elevationThreshold: 0,      // get all, filter later
        timestampMS: timestampMS
    });
}

app.get('/api/observers', (req, res) => {
    res.json(gateway_router_position);
});

app.get('/api/history', (req, res) => {
    res.json(connectionHistory.slice(-50).reverse());
});

app.get('/api/satellites', (req, res) => {
    const { router, gateways } = gateway_router_position;
    const now = Date.now();

    const routerVisible = getVisibleFromStore(router, now);
    const gatewaysVisible = gateways.map(gw => ({
        name: gw.name,
        visible: getVisibleFromStore(gw, now)
    }));

    // 1. Find best satellite for router (based on quality)
    let bestSatellite = null;
    let maxQuality = -1;
    routerVisible.forEach(sat => {
        const pathLoss = calculatePathLoss(sat.info.range, FREQUENCY_MHZ);
        const cn = calculateCN(pathLoss);
        const quality = calculateSignalQuality(cn, sat.info.elevation);
        if (quality > maxQuality) {
            maxQuality = quality;
            bestSatellite = {
                id: sat.tleArr[0],
                elevation: sat.info.elevation,
                azimuth: sat.info.azimuth,
                range_km: sat.info.range / 1000,
                cn: cn,
                quality: quality
            };
        }
    });

    // 2. For that best satellite, get visibility info from each gateway
    let gatewaysView = [];
    if (bestSatellite) {
        const gatewaysVisible = gateways.map(gw => ({
            name: gw.name,
            visible: getVisibleFromStore(gw, now)
        }));

        gatewaysView = gatewaysVisible.map(gw => {
            const satInGw = gw.visible.find(s => s.tleArr[0] === bestSatellite.id);
            if (satInGw && satInGw.info.elevation > 5) {
                const pathLossGw = calculatePathLoss(satInGw.info.range, FREQUENCY_MHZ);
                const cnGw = calculateCN(pathLossGw);
                return {
                    name: gw.name,
                    elevation: satInGw.info.elevation,
                    azimuth: satInGw.info.azimuth,
                    range_km: satInGw.info.range / 1000,
                    cn: cnGw
                };
            } else {
                return {
                    name: gw.name,
                    elevation: -90,
                    cn: -999
                };
            }
        });
    }

    // 3. Log connection change (optional)
    if (bestSatellite && (!connectionHistory.length || connectionHistory[connectionHistory.length - 1].satellite !== bestSatellite.id)) {
        connectionHistory.push({
            satellite: bestSatellite.id,
            gateway: "pending",   // gateway will be chosen by handover engine
            quality: bestSatellite.quality,
            cn: bestSatellite.cn,
            timestamp: new Date(now).toISOString()
        });
        if (connectionHistory.length > 100) connectionHistory.shift();
    }

    res.json({
        bestSatellite: bestSatellite,
        gatewaysView: gatewaysView,
        // still provide full lists if needed by other parts of frontend
        router: routerVisible,
        gateways: gatewaysVisible
    });
});

app.get('/api/globe', (req, res) => {
    const now = new Date();
    const positions = uniquetles.map(tle => {
        try {
            const satrec = satellite.twoline2satrec(tle[1], tle[2]);
            const pv = satellite.propagate(satrec, now);
            if (!pv.position) return null;
            const gmst = satellite.gstime(now);
            const geo = satellite.eciToGeodetic(pv.position, gmst);
            return {
                name: tle[0],
                lat: satellite.degreesLat(geo.latitude),
                lng: satellite.degreesLong(geo.longitude),
                alt: geo.height
            };
        } catch { return null; }
    }).filter(Boolean);

    res.json({ satellites: positions, gateways: gateway_router_position.gateways });
});

app.listen(port, () => {
    console.log(`Server running at http://localhost:${port}`);
});