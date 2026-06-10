const express = require('express');
const cors = require('cors');
const fs = require('fs');
const { getVisibleSatellites } = require('tle.js');
const path = require('path');
const { calculatePathLoss, calculateCN, calculateSignalQuality } = require('./utils/physics');

const app = express();
const port = 3001;

app.use(cors());
app.use(express.json());

// Frequency configuration (e.g., Ku-band for Starlink-like performance)
const FREQUENCY_MHZ = 12000;

// Connection History (simple in-memory log for now)
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

app.get('/api/observers', (req, res) => {
    res.json(gateway_router_position);
});

app.get('/api/history', (req, res) => {
    res.json(connectionHistory.slice(-50).reverse());
});

app.get('/api/satellites', (req, res) => {
    const { router, gateways } = gateway_router_position;
    const now = Date.now();

    const getVisibleFromStore = (observer) => {
        const lat = observer.latitude_router || observer.latitude_gateway;
        const lng = observer.longitude_router || observer.longitude_gateway;
        const alt = observer.altitude_m_router || observer.altitude_m_gateway;

        return getVisibleSatellites({
            observerLat: lat,
            observerLng: lng,
            observerHeight: alt/1000, // convert m to km
            tles: uniquetles,
            elevationThreshold: 29.11,
            timestampMS: now
        });
    };
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
        alt: geo.height / 6371
      };
    } catch { return null; }
  }).filter(Boolean);

  res.json({ satellites: positions, gateways: gateway_router_position.gateways });
});

    const routerVisible = getVisibleFromStore(router);
    const gatewaysVisible = gateways.map(gw => ({
        name: gw.name,
        visible: getVisibleFromStore(gw)
    }));

    // HANDOVER & BEST CONNECTION LOGIC
    // We need a satellite that is visible to the router and at least one gateway
    let bestConnection = null;
    let maxQuality = -1;

    routerVisible.forEach(sat => {
        const satId = sat.tleArr[0];

        gatewaysVisible.forEach(gw => {
            const satInGw = gw.visible.find(s => s.tleArr[0] === satId);

            if (satInGw) {
                // Potential connection! Calculate quality based on router-to-satellite link
                const pathLoss = calculatePathLoss(sat.info.range, FREQUENCY_MHZ);
                const cn = calculateCN(pathLoss);
                const quality = calculateSignalQuality(cn, sat.info.elevation);

                if (quality > maxQuality) {
                    maxQuality = quality;
                    bestConnection = {
                        satellite: satId,
                        gateway: gw.name,
                        quality: quality,
                        cn: cn.toFixed(2),
                        pathLoss: pathLoss.toFixed(2),
                        azimuth: sat.info.azimuth.toFixed(2),
                        elevation: sat.info.elevation.toFixed(2),
                        range: sat.info.range.toFixed(2),
                        timestamp: new Date(now).toISOString()
                    };
                }
            }
        });
    });

    // Log connection if it changed significantly or sporadically
    if (bestConnection && (!connectionHistory.length || connectionHistory[connectionHistory.length - 1].satellite !== bestConnection.satellite)) {
        connectionHistory.push(bestConnection);
        if (connectionHistory.length > 100) connectionHistory.shift();
    }

    const results = {
        router: routerVisible,
        gateways: gatewaysVisible,
        bestConnection: bestConnection
    };

    res.json(results);
});

app.listen(port, () => {
    console.log(`Server running at http://localhost:${port}`);
});
