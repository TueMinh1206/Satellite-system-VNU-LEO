<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import Globe from './Globe.svelte';

  type GatewayStatus = 'Alive' | 'Dead';
  type Region = 'North' | 'Central' | 'South';
  type SignalQuality = 'Good' | 'Medium' | 'Poor';
  type SessionStatus = 'Connected' | 'Handover' | 'Interrupted';

  type Gateway = { id: string; name: string; status: GatewayStatus; traffic: number; ping: number; };
  type Satellite = { id: string; altitude: number; region: Region; visibleGateway: string; elevation: number; azimuth: number; status: 'Visible' | 'Hidden'; };
  type Router = { mac: string; type: 'Fixed' | 'Mobility'; assignedGW: string; trackingSatellite: string; cnRatio: number; pathLoss: number; azimuth: number; elevation: number; signalQuality: SignalQuality; antennaLock: boolean; geoViolation: boolean; bandwidth: string; };
  type Session = { id: string; routerMac: string; satelliteId: string; gatewayId: string; status: SessionStatus; latency: number; packetLoss: number; throughput: number; handoverCount: number; };

  let gateways: Gateway[] = [];
  let satellites: Satellite[] = [];
  let routers: Router[] = [];
  let sessions: Session[] = [];

  let bestConn: any = null;
  let handoverHistory: any[] = [];
  let simulationInterval: number | undefined;

  async function fetchData() {
    try {
      const [satRes, obsRes, histRes] = await Promise.all([
        fetch('http://localhost:3001/api/satellites'),
        fetch('http://localhost:3001/api/observers'),
        fetch('http://localhost:3001/api/history')
      ]);
      
      if (!satRes.ok || !obsRes.ok || !histRes.ok) throw new Error('API request failed');
      
      const satData = await satRes.json();
      const obsData = await obsRes.json();
      const histData = await histRes.json();

      bestConn = satData.bestConnection;
      handoverHistory = histData;

      // Update Gateways
      gateways = obsData.gateways.map((gw: any, index: number) => ({
        id: `GW-${index}`,
        name: gw.name_gateway || `Gateway ${index}`,
        status: 'Alive',
        traffic: Math.round(Math.random() * 500 + 200),
        ping: Math.round(Math.random() * 20 + 10)
      }));

      // Update Satellites
      const allSats: Satellite[] = [];
      const seenSats = new Set();
      
      // Satellites visible to gateways
      satData.gateways.forEach((gwData: any, index: number) => {
          const gwId = `GW-${index}`;
          gwData.visible.forEach((s: any) => {
              const name = s.tleArr[0];
              if (!seenSats.has(name)) {
                  allSats.push({
                      id: name,
                      altitude: Math.round(s.info.height),
                      region: 'Visible' as Region,
                      visibleGateway: gwId,
                      elevation: Math.round(s.info.elevation),
                      azimuth: Math.round(s.info.azimuth),
                      status: 'Visible'
                  });
                  seenSats.add(name);
              }
          });
      });

      // Satellites visible to router
      satData.router.forEach((s: any) => {
          const name = s.tleArr[0];
          if (!seenSats.has(name)) {
              allSats.push({
                  id: name,
                  altitude: Math.round(s.info.height),
                  region: 'North',
                  visibleGateway: 'Router',
                  elevation: Math.round(s.info.elevation),
                  azimuth: Math.round(s.info.azimuth),
                  status: 'Visible'
              });
              seenSats.add(name);
          }
      });

      satellites = allSats;

      // Update Routers
      if (bestConn) {
          routers = [
            {
              mac: '00:1A:2B:VNU',
              type: 'Fixed',
              assignedGW: bestConn.gateway,
              trackingSatellite: bestConn.satellite,
              cnRatio: parseFloat(bestConn.cn),
              pathLoss: parseFloat(bestConn.pathLoss),
              azimuth: Math.round(parseFloat(bestConn.azimuth)),
              elevation: Math.round(parseFloat(bestConn.elevation)),
              signalQuality: bestConn.quality > 80 ? 'Good' : bestConn.quality > 40 ? 'Medium' : 'Poor',
              antennaLock: true,
              geoViolation: false,
              bandwidth: `${bestConn.quality}%`
            }
          ];

          // Update Sessions
          sessions = [
            {
              id: 'SESS-VNU',
              routerMac: '00:1A:2B:VNU',
              satelliteId: bestConn.satellite,
              gatewayId: bestConn.gateway,
              status: 'Connected',
              latency: Math.round(2 * 550 / 300), 
              packetLoss: bestConn.quality > 80 ? 0.1 : 1.5,
              throughput: Math.round(bestConn.quality * 2),
              handoverCount: handoverHistory.length
            }
          ];
      } else {
          routers = [{
              mac: '00:1A:2B:VNU',
              type: 'Fixed',
              assignedGW: 'Searching...',
              trackingSatellite: 'None',
              cnRatio: 0,
              pathLoss: 0,
              azimuth: 0,
              elevation: 0,
              signalQuality: 'Poor',
              antennaLock: false,
              geoViolation: false,
              bandwidth: '0%'
          }];
          sessions = [];
      }

    } catch (e) {
      console.error("Connection to API failed. Using defaults.", e);
    }
  }

  // --- TRẠNG THÁI LỌC DỮ LIỆU (UI DRILL-DOWN) ---
  let selectedGatewayId: string | null = null;
  let selectedSatelliteId: string | null = null;

  function toggleGateway(id: string) {
    if (selectedGatewayId === id) {
      selectedGatewayId = null;
      selectedSatelliteId = null;
    } else {
      selectedGatewayId = id;
      selectedSatelliteId = null;
    }
  }

  function toggleSatellite(id: string) {
    if (selectedSatelliteId === id) {
      selectedSatelliteId = null;
    } else {
      selectedSatelliteId = id;
      const sat = satellites.find(s => s.id === id);
      if (sat && !selectedGatewayId) {
        selectedGatewayId = sat.visibleGateway;
      }
    }
  }

  function clearFilters() {
    selectedGatewayId = null;
    selectedSatelliteId = null;
  }

  $: displaySatellites = selectedGatewayId ? satellites.filter(s => s.visibleGateway === selectedGatewayId) : satellites;
  $: displaySessions = selectedSatelliteId ? sessions.filter(s => s.satelliteId === selectedSatelliteId) : selectedGatewayId ? sessions.filter(s => s.gatewayId === selectedGatewayId) : sessions;
  $: displayRouters = selectedSatelliteId ? routers.filter(r => r.trackingSatellite === selectedSatelliteId) : selectedGatewayId ? routers.filter(r => r.assignedGW === selectedGatewayId) : routers;
  $: totalTraffic = gateways.reduce((sum, gw) => sum + (gw.status === 'Alive' ? gw.traffic : 0), 0);
  $: activeGateways = gateways.filter((g) => g.status === 'Alive').length;
  $: activeSessions = sessions.filter((s) => s.status !== 'Interrupted').length;


  onMount(() => {
    fetchData();
    simulationInterval = window.setInterval(fetchData, 5000); 
  });
  onDestroy(() => { if (simulationInterval !== undefined) window.clearInterval(simulationInterval); });

</script>

<main class="dashboard">
  <header>
    <div class="logo-area">
      <h1>VNU-LEO <span>NMS</span></h1>
      <p>Network Monitoring System</p>
    </div>

    <div class="global-stats">
      <div class="stat-box"><span class="label">Tổng lưu lượng</span><span class="value value-neon">{totalTraffic} Mbps</span></div>
      <div class="stat-box"><span class="label">Gateway Active</span><span class="value">{activeGateways}/{gateways.length}</span></div>
      <div class="stat-box"><span class="label">Active Sessions</span><span class="value">{activeSessions}/{sessions.length}</span></div>
    </div>
  </header>

  {#if selectedGatewayId || selectedSatelliteId}
    <div class="filter-bar">
      <span>Đang lọc theo: 
        <strong>{selectedGatewayId || 'Tất cả Gateway'}</strong> 
        {#if selectedSatelliteId} ➔ <strong>{selectedSatelliteId}</strong> {/if}
      </span>
      <button class="btn-clear" on:click={clearFilters}>✖ Xóa bộ lọc</button>
    </div>
  {/if}

  <div class="grid-container">
    <div class="left-col">
      <section class="panel">
        <h2>🌐 Gateways</h2>
        <Globe />
        <div class="card-list">
          {#each gateways as gw}
            <div class="card interactive {selectedGatewayId === gw.id ? 'active-gw' : ''}" 
                 class:border-green={gw.status === 'Alive'} class:border-red={gw.status === 'Dead'}
                 on:click={() => toggleGateway(gw.id)}>
              <div class="card-header">
                <h3>{gw.name}</h3>
                <span class:badge={true} class:bg-green={gw.status === 'Alive'} class:bg-red={gw.status === 'Dead'}>{gw.status}</span>
              </div>
              <div class="card-body">
                <p>Lưu lượng: <strong>{gw.traffic} Mbps</strong></p>
                <p>Ping: <strong>{gw.status === 'Alive' ? gw.ping + ' ms' : 'N/A'}</strong></p>
              </div>
            </div>
          {/each}
        </div>
      </section>

      <section class="panel mt-4">
        <h2>🛰️ Vệ Tinh ({displaySatellites.length})</h2>
        <div class="satellite-grid">
          {#each displaySatellites as sat}
            <div class="sat-chip interactive {selectedSatelliteId === sat.id ? 'active-sat' : ''}"
                 on:click={() => toggleSatellite(sat.id)}>
              <div class="sat-title">{sat.id}</div>
              <div class="sat-info">
                <span>{sat.region}</span>
                <span>El: {sat.elevation}°</span>
              </div>
              <div class="sat-gw">Thuộc: {sat.visibleGateway}</div>
            </div>
          {/each}
          {#if displaySatellites.length === 0}
            <p class="text-muted">Không có vệ tinh nào trong vùng này.</p>
          {/if}
        </div>
      </section>
    </div>

    <div class="right-col">
      <section class="panel">
        <h2>🔁 Sessions ({displaySessions.length})</h2>
        <div class="table-wrapper">
          <table class="data-table">
            <thead><tr><th>Session</th><th>Router</th><th>Satellite</th><th>Gateway</th><th>Status</th><th>Lat/Loss</th></tr></thead>
            <tbody>
              {#each displaySessions as session}
                <tr>
                  <td>{session.id}</td>
                  <td><code>{session.routerMac.slice(-5)}</code></td>
                  <td><span class="highlight">{session.satelliteId}</span></td>
                  <td>{session.gatewayId}</td>
                  <td><span class="status-dot {session.status.toLowerCase()}"></span>{session.status}</td>
                  <td>{session.latency}ms / {session.packetLoss}%</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel mt-4">
        <h2>📡 Routers ({displayRouters.length})</h2>
        <div class="table-wrapper">
          <table class="data-table">
            <thead><tr><th>MAC</th><th>Type</th><th>C/N</th><th>Elevation</th><th>Signal</th><th>Lock</th></tr></thead>
            <tbody>
              {#each displayRouters as router}
                <tr>
                  <td><code>{router.mac}</code></td>
                  <td><span class="badge-outline">{router.type}</span></td>
                  <td class:text-warning={router.cnRatio < 15} class:text-good={router.cnRatio >= 15}>{router.cnRatio} dB</td>
                  <td>{router.elevation}°</td>
                  <td>{router.signalQuality}</td>
                  <td>{router.antennaLock ? '✅' : '❌'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>

      <div class="system-logs mt-4">
        <h3>Lịch sử Handover</h3>
        <ul>
          {#each handoverHistory as event} 
            <li>
              <span class="log-time">[{new Date(event.timestamp).toLocaleTimeString()}]</span>
              <strong>{event.satellite}</strong> ➔ {event.gateway} 
              <span class="log-meta">({event.quality}%, {event.cn}dB)</span>
            </li> 
          {/each}
          {#if handoverHistory.length === 0}
            <li class="text-muted">Chưa có bản ghi kết nối nào.</li>
          {/if}
        </ul>
      </div>
    </div>
  </div>
</main>

<style>
  :global(body) { margin: 0; font-family: Arial, sans-serif; background: #07111f; color: #e5eefc; }
  .dashboard { min-height: 100vh; padding: 24px; box-sizing: border-box; }
  
  header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 20px; }
  .logo-area h1 { margin: 0; font-size: 28px; }
  .logo-area span { color: #38bdf8; }
  .logo-area p { margin: 4px 0 0; color: #94a3b8; font-size: 14px;}
  
  .global-stats { display: flex; gap: 12px; flex-wrap: wrap; }
  .stat-box { background: #0f1e33; border: 1px solid #1e3a5f; border-radius: 10px; padding: 12px 16px; min-width: 140px; }
  .label { display: block; font-size: 12px; color: #94a3b8; margin-bottom: 4px; }
  .value { font-size: 20px; font-weight: bold; }
  .value-neon { color: #22c55e; }

  /* Thanh lọc dữ liệu */
  .filter-bar {
    background: #1e3a8a; border-left: 4px solid #38bdf8; padding: 12px 16px;
    border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;
  }
  .btn-clear {
    background: rgba(255, 255, 255, 0.1); border: none; color: white; padding: 6px 12px;
    border-radius: 4px; cursor: pointer; transition: 0.2s;
  }
  .btn-clear:hover { background: #ef4444; }

  /* Bố cục chính */
  .grid-container { display: grid; grid-template-columns: 350px 1fr; gap: 20px; }
  @media (max-width: 1024px) { .grid-container { grid-template-columns: 1fr; } }
  
  .panel { background: #0b1728; border: 1px solid #1e293b; border-radius: 14px; padding: 16px; }
  .panel h2 { margin-top: 0; font-size: 18px; border-bottom: 1px solid #1e293b; padding-bottom: 10px; margin-bottom: 16px;}
  .mt-4 { margin-top: 20px; }
  
  /* Tương tác Card & Chip */
  .interactive { cursor: pointer; transition: all 0.2s ease; }
  .interactive:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
  
  .card-list { display: flex; flex-direction: column; gap: 12px; }
  .card { background: #111f35; border-radius: 10px; padding: 12px; border: 1px solid transparent; border-left: 5px solid #475569; }
  .card p { margin: 6px 0 0; font-size: 14px; color: #cbd5e1; }
  .card-header { display: flex; justify-content: space-between; align-items: center; }
  .card-header h3 { margin: 0; font-size: 15px; }
  
  .border-green { border-left-color: #22c55e; }
  .border-red { border-left-color: #ef4444; }
  .active-gw { border-color: #38bdf8 !important; background: #0c4a6e; }

  /* Lưới vệ tinh */
  .satellite-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .sat-chip { background: #1e293b; padding: 12px; border-radius: 8px; border: 1px solid transparent; }
  .sat-title { font-weight: bold; font-size: 15px; color: #f8fafc; }
  .sat-info { display: flex; justify-content: space-between; font-size: 12px; color: #94a3b8; margin: 4px 0; }
  .sat-gw { font-size: 11px; color: #38bdf8; background: rgba(56, 189, 248, 0.1); display: inline-block; padding: 2px 6px; border-radius: 4px;}
  .active-sat { border-color: #facc15; background: #422006; }

  /* Table */
  .table-wrapper { overflow-x: auto; }
  .data-table { width: 100%; border-collapse: collapse; min-width: 500px; font-size: 14px; }
  .data-table th, .data-table td { padding: 10px; border-bottom: 1px solid #1e293b; text-align: left; }
  .data-table th { color: #93c5fd; font-size: 12px; text-transform: uppercase; }
  .highlight { color: #facc15; font-weight: bold; }

  .badge { padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
  .bg-green { background: #14532d; color: #86efac; }
  .bg-red { background: #7f1d1d; color: #fecaca; }
  .badge-outline { border: 1px solid #38bdf8; color: #7dd3fc; padding: 2px 6px; border-radius: 4px; font-size: 12px; }

  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .status-dot.connected { background: #22c55e; }
  .status-dot.handover { background: #facc15; }
  .status-dot.interrupted { background: #ef4444; }

  .text-warning { color: #facc15; }
  .text-good { color: #4ade80; }
  .text-muted { color: #64748b; font-style: italic; }

  .system-logs { background: #020617; border-radius: 10px; padding: 12px; border: 1px solid #1e293b; }
  .system-logs h3 { margin: 0 0 10px; color: #38bdf8; font-size: 15px;}
  .system-logs ul { list-style: none; padding: 0; margin: 0; }
  .system-logs li { font-family: Consolas, monospace; font-size: 12px; color: #cbd5e1; padding: 4px 0; border-bottom: 1px dashed #1e293b; }
</style>