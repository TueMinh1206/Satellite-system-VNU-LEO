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

  let gateways: Gateway[] = [
    { id: 'GW-HN', name: 'Trạm Gateway Hà Nội', status: 'Alive', traffic: 450, ping: 12 },
    { id: 'GW-DN', name: 'Trạm Gateway Đà Nẵng', status: 'Alive', traffic: 320, ping: 18 },
    { id: 'GW-HCM', name: 'Trạm Gateway TP.HCM', status: 'Alive', traffic: 680, ping: 15 }
  ];

  let satellites: Satellite[] = [
    { id: 'SAT-01', altitude: 550, region: 'North', visibleGateway: 'GW-HN', elevation: 62, azimuth: 35, status: 'Visible' },
    { id: 'SAT-02', altitude: 550, region: 'Central', visibleGateway: 'GW-DN', elevation: 48, azimuth: 120, status: 'Visible' },
    { id: 'SAT-03', altitude: 550, region: 'South', visibleGateway: 'GW-HCM', elevation: 55, azimuth: 210, status: 'Visible' }
  ];

  let routers: Router[] = [
    { mac: '00:1A:2B:3C', type: 'Fixed', assignedGW: 'GW-HN', trackingSatellite: 'SAT-01', cnRatio: 18.5, pathLoss: 161.2, azimuth: 35, elevation: 62, signalQuality: 'Good', antennaLock: true, geoViolation: false, bandwidth: '100%' },
    { mac: '00:1A:2B:4D', type: 'Mobility', assignedGW: 'GW-DN', trackingSatellite: 'SAT-02', cnRatio: 14.2, pathLoss: 165.5, azimuth: 120, elevation: 48, signalQuality: 'Medium', antennaLock: true, geoViolation: false, bandwidth: '100%' },
    { mac: '00:1B:3C:5F', type: 'Fixed', assignedGW: 'GW-HCM', trackingSatellite: 'SAT-03', cnRatio: 19.1, pathLoss: 160.8, azimuth: 210, elevation: 55, signalQuality: 'Good', antennaLock: true, geoViolation: false, bandwidth: '100%' }
  ];

  let sessions: Session[] = [
    { id: 'SESSION-001', routerMac: '00:1A:2B:3C', satelliteId: 'SAT-01', gatewayId: 'GW-HN', status: 'Connected', latency: 35, packetLoss: 0.8, throughput: 120, handoverCount: 0 },
    { id: 'SESSION-002', routerMac: '00:1A:2B:4D', satelliteId: 'SAT-02', gatewayId: 'GW-DN', status: 'Connected', latency: 42, packetLoss: 1.1, throughput: 95, handoverCount: 0 },
    { id: 'SESSION-003', routerMac: '00:1B:3C:5F', satelliteId: 'SAT-03', gatewayId: 'GW-HCM', status: 'Connected', latency: 38, packetLoss: 0.6, throughput: 140, handoverCount: 0 }
  ];

  let logs: string[] = ['Hệ thống giám sát VNU-LEO khởi động thành công.'];
  let simulationInterval: number | undefined;

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

  function addLog(msg: string) { logs = [`[${new Date().toLocaleTimeString()}] ${msg}`, ...logs].slice(0, 6); }
  function randomNumber(min: number, max: number): number { return Math.random() * (max - min) + min; }
  function clamp(value: number, min: number, max: number): number { return Math.min(max, Math.max(min, value)); }

  function getGatewayByRegion(region: Region): string {
    if (region === 'North') return 'GW-HN';
    if (region === 'Central') return 'GW-DN';
    return 'GW-HCM';
  }

  function moveSatelliteRegion(region: Region): Region {
    if (region === 'North') return 'Central';
    if (region === 'Central') return 'South';
    return 'North';
  }

  function getSignalQuality(cnRatio: number): SignalQuality {
    if (cnRatio >= 18) return 'Good';
    if (cnRatio >= 14) return 'Medium';
    return 'Poor';
  }

  function simulateNetwork() {
    gateways = gateways.map((gw) => {
      if (gw.status === 'Alive') {
        const newTraffic = gw.traffic + randomNumber(-25, 25);
        if (Math.random() < 0.02) {
          addLog(`CẢNH BÁO: ${gw.name} mất kết nối!`);
          return { ...gw, status: 'Dead', traffic: 0 };
        }
        return { ...gw, traffic: Math.max(0, Math.round(newTraffic)), ping: Math.round(randomNumber(10, 25)) };
      }
      if (Math.random() < 0.1) {
        addLog(`Phục hồi: ${gw.name} đã kết nối lại.`);
        return { ...gw, status: 'Alive', traffic: 100 };
      }
      return gw;
    });

    satellites = satellites.map((sat) => {
      const shouldMove = Math.random() < 0.35;
      const newRegion = shouldMove ? moveSatelliteRegion(sat.region) : sat.region;
      return {
        ...sat,
        region: newRegion,
        visibleGateway: getGatewayByRegion(newRegion),
        elevation: Math.round(randomNumber(25, 85)),
        azimuth: Math.round((sat.azimuth + randomNumber(15, 45)) % 360)
      };
    });

    const aliveGatewayIds = new Set(gateways.filter((gw) => gw.status === 'Alive').map((gw) => gw.id));

    sessions = sessions.map((session) => {
      const satellite = satellites.find((sat) => sat.id === session.satelliteId);
      const preferredGateway = satellite ? satellite.visibleGateway : session.gatewayId;
      let newGateway = preferredGateway;

      if (!aliveGatewayIds.has(preferredGateway)) {
        const fallbackGateway = gateways.find((gw) => gw.status === 'Alive');
        if (fallbackGateway) newGateway = fallbackGateway.id;
      }

      const isConnected = aliveGatewayIds.has(newGateway);
      const isHandover = newGateway !== session.gatewayId;
      return {
        ...session,
        gatewayId: newGateway,
        status: !isConnected ? 'Interrupted' : isHandover ? 'Handover' : 'Connected',
        latency: Math.round(randomNumber(25, 75)),
        packetLoss: +randomNumber(0.2, 3.5).toFixed(1),
        throughput: Math.round(randomNumber(60, 180)),
        handoverCount: session.handoverCount + (isHandover ? 1 : 0)
      };
    });

    routers = routers.map((router) => {
      const session = sessions.find((s) => s.routerMac === router.mac);
      const satellite = satellites.find((sat) => sat.id === session?.satelliteId);
      const elevation = satellite ? clamp(satellite.elevation + randomNumber(-4, 4), 5, 85) : router.elevation;
      const cnRatio = +clamp(10 + elevation * 0.18 + randomNumber(-2, 2), 6, 26).toFixed(1);
      
      return {
        ...router,
        assignedGW: session?.gatewayId ?? router.assignedGW,
        trackingSatellite: session?.satelliteId ?? router.trackingSatellite,
        elevation: Math.round(elevation),
        cnRatio,
        pathLoss: +clamp(172 - elevation * 0.08 + randomNumber(-1, 1), 155, 175).toFixed(1),
        signalQuality: getSignalQuality(cnRatio),
        antennaLock: cnRatio >= 12 && Boolean(satellite)
      };
    });
  }

  onMount(() => { simulationInterval = window.setInterval(simulateNetwork, 2000); });
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
        <h3>System Logs</h3>
        <ul>{#each logs as log} <li>{log}</li> {/each}</ul>
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