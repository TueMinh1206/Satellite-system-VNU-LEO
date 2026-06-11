const express = require('express');
const cors = require('cors');
const fs = require('fs');
const { getVisibleSatellites } = require('tle.js');
const path = require('path');
const WebSocket = require('ws');
const { calculatePathLoss, calculateCN, calculateSignalQuality } = require('./utils/physics');

const app = express();
const port = 3001;

app.use(cors());
app.use(express.json());

// Tần số Ku-band
const FREQUENCY_MHZ = 12000;

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

// ---------- HANDOVER ENGINE (nhẹ, tích hợp sẵn) ----------
class HandoverEngine {
    constructor(config = {}) {
        this.elevWarnDeg = config.elevWarnDeg ?? 25;
        this.elevCriticalDeg = config.elevCriticalDeg ?? 15;
        this.elevMinDeg = config.elevMinDeg ?? 5;
        this.cnWarnDb = config.cnWarnDb ?? 8;
        this.cnCriticalDb = config.cnCriticalDb ?? 5;
        this.alphaElev = config.alphaElev ?? 0.4;
        this.betaCn = config.betaCn ?? 0.6;
        this.handoverHistory = [];
        this.currentGateway = null;
        this.currentSatellite = null;
        this.wss = null;
    }

    // Chọn gateway tốt nhất từ danh sách gatewaysView (elevation, cn)
    selectBestGateway(gatewaysView) {
        if (!gatewaysView || gatewaysView.length === 0) return "Unknown";
        let best = null, bestScore = -Infinity;
        for (const gw of gatewaysView) {
            if (gw.elevation < this.elevMinDeg) continue;
            const score = this.alphaElev * gw.elevation + this.betaCn * gw.cn;
            if (score > bestScore) {
                bestScore = score;
                best = gw.name;
            }
        }
        return best || gatewaysView[0]?.name || "Unknown";
    }

    needHandover(currentSat, gatewaysView, currentGwName) {
        if (!currentSat) return false;
        if (currentSat.elevation < this.elevCriticalDeg) return true;
        if (currentSat.cn < this.cnCriticalDb) return true;
        const bestGwName = this.selectBestGateway(gatewaysView);
        if (bestGwName === currentGwName) return false;
        const currentGw = gatewaysView.find(g => g.name === currentGwName);
        const bestGw = gatewaysView.find(g => g.name === bestGwName);
        if (!currentGw || !bestGw) return false;
        const currentScore = this.alphaElev * currentGw.elevation + this.betaCn * currentGw.cn;
        const bestScore = this.alphaElev * bestGw.elevation + this.betaCn * bestGw.cn;
        return (bestScore - currentScore) > 5;
    }

    recordHandover(oldSat, newSat, oldGw, newGw, quality, cn, type = "handover") {
        const entry = {
            timestamp: Date.now() / 1000,
            from_sat: oldSat?.id || "unknown",
            to_sat: newSat?.id || "unknown",
            from_gw: oldGw,
            to_gw: newGw,
            quality: quality,
            cn: cn,
            type: type
        };
        this.handoverHistory.unshift(entry);
        if (this.handoverHistory.length > 100) this.handoverHistory.pop();
        this.currentGateway = newGw;
        this.currentSatellite = newSat;
        return entry;
    }

    broadcast(data) {
        if (!this.wss) return;
        this.wss.clients.forEach(client => {
            if (client.readyState === WebSocket.OPEN) {
                client.send(JSON.stringify(data));
            }
        });
    }

    processTelemetry(bestSat, gatewaysView, timestamp = Date.now()) {
        if (!bestSat) return { handoverDone: false };
        const oldGw = this.currentGateway;
        const oldSat = this.currentSatellite;
        const newGw = this.selectBestGateway(gatewaysView);

        if (this.needHandover(bestSat, gatewaysView, oldGw) || (newGw && newGw !== oldGw)) {
            this.broadcast({
                type: "HANDOVER_START",
                state: "handover",
                satellite_id: bestSat.id,
                gateway: oldGw,
                elevation: bestSat.elevation,
                azimuth: bestSat.azimuth,
                cn_db: bestSat.cn,
                signal_quality: bestSat.quality,
                range_km: bestSat.range_km,
                handover_count: this.handoverHistory.length + 1,
                timestamp: timestamp / 1000
            });
            const type = (newGw !== oldGw) ? "gateway_switch" : "handover";
            const entry = this.recordHandover(oldSat, bestSat, oldGw, newGw, bestSat.quality, bestSat.cn, type);
            setTimeout(() => {
                this.broadcast({
                    type: "HANDOVER_DONE",
                    state: "connected",
                    satellite_id: bestSat.id,
                    gateway: newGw,
                    elevation: bestSat.elevation,
                    azimuth: bestSat.azimuth,
                    cn_db: bestSat.cn,
                    signal_quality: bestSat.quality,
                    range_km: bestSat.range_km,
                    handover_count: this.handoverHistory.length,
                    timestamp: Date.now() / 1000
                });
            }, 50);
            return { handoverDone: true, entry };
        } else {
            if (!this.currentGateway) this.currentGateway = newGw;
            if (!this.currentSatellite) this.currentSatellite = bestSat;
            this.broadcast({
                type: "TELEMETRY",
                state: "connected",
                satellite_id: bestSat.id,
                gateway: this.currentGateway,
                elevation: bestSat.elevation,
                azimuth: bestSat.azimuth,
                cn_db: bestSat.cn,
                signal_quality: bestSat.quality,
                range_km: bestSat.range_km,
                handover_count: this.handoverHistory.length,
                timestamp: timestamp / 1000
            });
            return { handoverDone: false };
        }
    }

    getHistory(limit = 50) {
        return this.handoverHistory.slice(0, limit);
    }
}

// Khởi tạo handover engine
const handoverEngine = new HandoverEngine();

// Helper: lấy danh sách vệ tinh từ một observer (tái sử dụng)
function getVisibleFromStore(observer, timestampMS) {
    const lat = observer.latitude_router || observer.latitude_gateway;
    const lng = observer.longitude_router || observer.longitude_gateway;
    const alt = observer.altitude_m_router || observer.altitude_m_gateway;
    return getVisibleSatellites({
        observerLat: lat,
        observerLng: lng,
        observerHeight: alt / 1000,
        tles: uniquetles,
        elevationThreshold: 0,
        timestampMS: timestampMS
    });
}

// Hàm tính toán best satellite và gateways view
function computeCurrentState(now = Date.now()) {
    const { router, gateways } = gateway_router_position;
    const routerVisible = getVisibleFromStore(router, now);
    let bestSatellite = null;
    let maxQuality = -1;

    // Tìm best satellite dựa trên router
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

    // Tính gateways view cho best satellite
    let gatewaysView = [];
    if (bestSatellite) {
        gatewaysView = gateways.map(gw => {
            const visible = getVisibleFromStore(gw, now);
            const satInGw = visible.find(s => s.tleArr[0] === bestSatellite.id);
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
                return { name: gw.name, elevation: -90, cn: -999 };
            }
        });
    }
    return { bestSatellite, gatewaysView };
}

// ---------- KHỞI TẠO HTTP & WEBSOCKET SERVER ----------
const server = app.listen(port, () => {
    console.log(`Server running at http://localhost:${port}`);
});
const wss = new WebSocket.Server({ server });
handoverEngine.wss = wss;

wss.on('connection', (ws) => {
    console.log('WebSocket client connected');
    ws.on('close', () => console.log('WebSocket client disconnected'));
});

// Định kỳ cập nhật trạng thái và xử lý handover (mỗi 2 giây)
setInterval(() => {
    const now = Date.now();
    const { bestSatellite, gatewaysView } = computeCurrentState(now);
    if (bestSatellite) {
        handoverEngine.processTelemetry(bestSatellite, gatewaysView, now);
    }
}, 2000);

// ---------- API ENDPOINTS ----------
// 1. /api/observers – giữ nguyên
app.get('/api/observers', (req, res) => {
    res.json(gateway_router_position);
});

// 2. /api/history – trả về lịch sử handover (để tương thích cũ)
app.get('/api/history', (req, res) => {
    const history = handoverEngine.getHistory(50).map(ev => ({
        satellite: ev.to_sat,
        gateway: ev.to_gw,
        quality: ev.quality,
        cn: ev.cn,
        timestamp: new Date(ev.timestamp * 1000).toISOString()
    }));
    res.json(history);
});

// 3. /api/satellites – trả về bestSatellite, gatewaysView và các danh sách đầy đủ
app.get('/api/satellites', (req, res) => {
    const now = Date.now();
    const { bestSatellite, gatewaysView } = computeCurrentState(now);
    const routerVisible = getVisibleFromStore(gateway_router_position.router, now);
    const gatewaysVisible = gateway_router_position.gateways.map(gw => ({
        name: gw.name,
        visible: getVisibleFromStore(gw, now)
    }));
    res.json({
        bestSatellite,
        gatewaysView,
        router: routerVisible,
        gateways: gatewaysVisible
    });
});

// 4. /api/handover-history – endpoint mới cho frontend (dạng raw)
app.get('/api/handover-history', (req, res) => {
    res.json(handoverEngine.getHistory(50));
});

// Health check
app.get('/health', (req, res) => {
    res.json({ status: 'ok', clients: wss.clients.size, historyLength: handoverEngine.handoverHistory.length });
});