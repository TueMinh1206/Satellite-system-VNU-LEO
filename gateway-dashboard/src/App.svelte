<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import PolarChart from "./polarchart.svelte";

  // ── Types ──────────────────────────────────────────────────────────
  type GatewayStatus = "Alive" | "Dead";
  type SignalQuality = "Good" | "Medium" | "Poor";
  type SessionStatus = "Connected" | "Handover" | "Searching" | "Interrupted";

  type Gateway = {
    id: string;
    name: string;
    status: GatewayStatus;
    traffic: number;
    ping: number;
  };

  type Satellite = {
    id: string;
    visibleGateway: string;
    elevation: number;
    azimuth: number;
  };

  type Router = {
    mac: string;
    type: "Fixed" | "Mobility";
    assignedGW: string;
    trackingSatellite: string;
    cnRatio: number;
    pathLoss: number;
    azimuth: number;
    elevation: number;
    signalQuality: SignalQuality;
    antennaLock: boolean;
    bandwidth: string;
  };

  type Session = {
    id: string;
    routerMac: string;
    satelliteId: string;
    gatewayId: string;
    status: SessionStatus;
    latency: number;
    packetLoss: number;
    throughput: number;
    handoverCount: number;
  };

  type WsEvent = {
    type: string;
    state: string;
    satellite_id: string;
    gateway: string;
    elevation: number;
    azimuth: number;
    cn_db: number;
    signal_quality: number;
    range_km: number;
    handover_count: number;
  };

  // ── State ───────────────────────────────────────────────────────────
  let bestSatellite: any  = null;
  let gatewaysView:  any[] = [];
  let selectedGateway: string | null = null;  // gateway được engine chọn

  let gateways:   Gateway[]   = [];
  let satellites: Satellite[] = [];
  let routers:    Router[]    = [];
  let sessions:   Session[]   = [];
  let handoverHistory: any[]  = [];

  // Phased array data từ api.py
  let phasedData: any  = null;
  let phasedAlgo       = "mvdr";
  let phasedN          = 8;

  // WebSocket
  let wsEvent:      WsEvent | null = null;
  let sessionState: SessionStatus  = "Connected";
  let handoverCount = 0;
  let ws: WebSocket | null = null;

  // UI
  let selectedGatewayId:  string | null = null;
  let selectedSatelliteId: string | null = null;

  let pollInterval:   number;
  let phasedInterval: number;

  // ── Fetch từ index.js ───────────────────────────────────────────────
  async function fetchData() {
    try {
      const [satRes, obsRes, histRes] = await Promise.all([
        fetch("http://localhost:3001/api/satellites"),
        fetch("http://localhost:3001/api/observers"),
        fetch("http://localhost:3001/api/history"),
      ]);
      if (!satRes.ok) return;

      const satData  = await satRes.json();
      const obsData  = await obsRes.json();
      const histData = await histRes.json();

      // Dữ liệu mới từ index.js
      bestSatellite = satData.bestSatellite;
      gatewaysView  = satData.gatewaysView ?? [];
      handoverHistory = histData;

      // Gateways từ observers
      gateways = obsData.gateways.map((gw: any, i: number) => ({
        id:      `GW-${i}`,
        name:    gw.name,
        status:  "Alive" as GatewayStatus,
        traffic: Math.round(Math.random() * 500 + 200),
        ping:    Math.round(Math.random() * 20 + 10),
      }));

      // Satellites visible
      const seen    = new Set<string>();
      const allSats: Satellite[] = [];
      satData.gateways?.forEach((gw: any, i: number) => {
        gw.visible?.forEach((s: any) => {
          const name = s.tleArr[0];
          if (!seen.has(name)) {
            allSats.push({
              id:             name,
              visibleGateway: `GW-${i}`,
              elevation:      Math.round(s.info.elevation),
              azimuth:        Math.round(s.info.azimuth),
            });
            seen.add(name);
          }
        });
      });
      satellites = allSats;

      // Router + Session từ bestSatellite
      if (bestSatellite) {
        routers = [{
          mac:               "00:1A:2B:VNU",
          type:              "Fixed",
          assignedGW:        selectedGateway ?? "...",
          trackingSatellite: bestSatellite.id,
          cnRatio:           bestSatellite.cn,
          pathLoss:          0,
          azimuth:           Math.round(bestSatellite.azimuth),
          elevation:         Math.round(bestSatellite.elevation),
          signalQuality:     bestSatellite.quality > 70 ? "Good"
                           : bestSatellite.quality > 40 ? "Medium" : "Poor",
          antennaLock:       true,
          bandwidth:         `${bestSatellite.quality?.toFixed(0)}%`,
        }];
        sessions = [{
          id:           "SESS-VNU",
          routerMac:    "00:1A:2B:VNU",
          satelliteId:  bestSatellite.id,
          gatewayId:    selectedGateway ?? "...",
          status:       sessionState,
          latency:      0,
          packetLoss:   0,
          throughput:   0,
          handoverCount,
        }];

        // POST telemetry sang api.py
        postTelemetry();
      } else {
        routers = [{
          mac: "00:1A:2B:VNU", type: "Fixed",
          assignedGW: "Searching...", trackingSatellite: "None",
          cnRatio: 0, pathLoss: 0, azimuth: 0, elevation: 0,
          signalQuality: "Poor", antennaLock: false, bandwidth: "0%",
        }];
        sessions = [];
      }
    } catch (e) {
      console.error("Fetch error:", e);
    }
  }

  // ── POST telemetry → api.py → nhận selected_gateway ────────────────
  async function postTelemetry() {
    if (!bestSatellite) return;
    try {
      const res = await fetch("http://localhost:8000/api/telemetry", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          satellite_id: bestSatellite.id,
          elevation:    bestSatellite.elevation,
          azimuth:      bestSatellite.azimuth,
          range_km:     bestSatellite.range_km,
          cn:           bestSatellite.cn,
          gateways:     gatewaysView,
        }),
      });
      if (res.ok) {
        const result = await res.json();
        // Cập nhật gateway được engine chọn
        if (result.selected_gateway) {
          selectedGateway = result.selected_gateway;
          // Cập nhật lại session + router với gateway thực
          if (sessions.length > 0)  sessions[0].gatewayId    = selectedGateway;
          if (routers.length > 0)   routers[0].assignedGW    = selectedGateway;
          sessions = [...sessions];
          routers  = [...routers];
        }
        handoverCount = result.handover_count ?? handoverCount;
        sessionState  = (result.session?.charAt(0).toUpperCase()
                       + result.session?.slice(1)) as SessionStatus ?? "Connected";
      }
    } catch (_) {}
  }

  // ── GET phased-array từ api.py ──────────────────────────────────────
  async function fetchPhasedArray() {
    if (!bestSatellite) return;
    try {
      const el  = bestSatellite.elevation;
      const az  = bestSatellite.azimuth;
      const res = await fetch(
        `http://localhost:8000/api/phased-array?el=${el}&az=${az}&N=${phasedN}&algo=${phasedAlgo}&rain=20`
      );
      if (res.ok) phasedData = await res.json();
    } catch (_) {}
  }

  // ── WebSocket /ws ───────────────────────────────────────────────────
  function connectWS() {
    try {
      ws = new WebSocket("ws://localhost:8000/ws");
      ws.onmessage = (e) => {
        const data: WsEvent = JSON.parse(e.data);
        wsEvent       = data;
        sessionState  = (data.state.charAt(0).toUpperCase()
                       + data.state.slice(1)) as SessionStatus;
        handoverCount = data.handover_count;
        if (data.type === "HANDOVER_START" || data.type === "HANDOVER_DONE") {
          fetchPhasedArray();
        }
      };
      ws.onclose = () => setTimeout(connectWS, 3000);
      ws.onerror = () => ws?.close();
    } catch (_) {}
  }

  // ── Lifecycle ───────────────────────────────────────────────────────
  onMount(() => {
    fetchData();
    connectWS();
    pollInterval   = window.setInterval(fetchData,        5000);
    phasedInterval = window.setInterval(fetchPhasedArray, 5000);
  });
  onDestroy(() => {
    clearInterval(pollInterval);
    clearInterval(phasedInterval);
    ws?.close();
  });

  // ── Computed ────────────────────────────────────────────────────────
  $: signalQuality = (() => {
    const cn = bestSatellite?.cn ?? 0;
    return cn >= 15 ? "Good" : cn >= 8 ? "Medium" : "Poor";
  })();

  $: qualityColor = signalQuality === "Good"  ? "#22c55e"
                  : signalQuality === "Medium" ? "#f59e0b" : "#ef4444";

  $: stateColor = sessionState === "Connected"  ? "#22c55e"
                : sessionState === "Handover"    ? "#f59e0b"
                : sessionState === "Searching"   ? "#818cf8" : "#ef4444";

  $: displaySatellites = selectedGatewayId
    ? satellites.filter(s => s.visibleGateway === selectedGatewayId)
    : satellites;

  $: displaySessions = selectedSatelliteId
    ? sessions.filter(s => s.satelliteId === selectedSatelliteId)
    : selectedGatewayId
    ? sessions.filter(s => s.gatewayId   === selectedGatewayId)
    : sessions;

  $: displayRouters = selectedSatelliteId
    ? routers.filter(r => r.trackingSatellite === selectedSatelliteId)
    : selectedGatewayId
    ? routers.filter(r => r.assignedGW === selectedGatewayId)
    : routers;

  $: totalTraffic   = gateways.reduce((s, g) => s + (g.status === "Alive" ? g.traffic : 0), 0);
  $: activeGateways = gateways.filter(g => g.status === "Alive").length;
  $: activeSessions = sessions.filter(s => s.status !== "Interrupted").length;

  function toggleGateway(id: string) {
    selectedGatewayId   = selectedGatewayId === id ? null : id;
    selectedSatelliteId = null;
  }
  function toggleSatellite(id: string) {
    selectedSatelliteId = selectedSatelliteId === id ? null : id;
  }
  function clearFilters() {
    selectedGatewayId = null; selectedSatelliteId = null;
  }
</script>

<!-- ══════════════════════════════════════════════════════════════════ -->
<main class="dashboard">

  <!-- Header -->
  <header>
    <div class="logo-area">
      <h1>VNU-LEO <span>NMS</span></h1>
      <p>Network Monitoring System</p>
    </div>

    <div class="global-stats">
      <div class="stat-box">
        <span class="label">Tổng lưu lượng</span>
        <span class="value value-neon">{totalTraffic} Mbps</span>
      </div>
      <div class="stat-box">
        <span class="label">Gateway Active</span>
        <span class="value">{activeGateways}/{gateways.length}</span>
      </div>
      <div class="stat-box">
        <span class="label">Active Sessions</span>
        <span class="value">{activeSessions}/{sessions.length}</span>
      </div>
      <div class="stat-box">
        <span class="label">Handovers</span>
        <span class="value value-amber">{handoverCount}</span>
      </div>
      <div class="stat-box">
        <span class="label">Session State</span>
        <span class="value" style="color:{stateColor}">{sessionState}</span>
      </div>
    </div>
  </header>

  <!-- Filter bar -->
  {#if selectedGatewayId || selectedSatelliteId}
    <div class="filter-bar">
      <span>Đang lọc:
        <strong>{selectedGatewayId ?? "Tất cả"}</strong>
        {#if selectedSatelliteId} ➔ <strong>{selectedSatelliteId}</strong>{/if}
      </span>
      <button class="btn-clear" on:click={clearFilters}>✖ Xóa bộ lọc</button>
    </div>
  {/if}

  <!-- Main grid -->
  <div class="grid-container">

    <!-- LEFT COLUMN -->
    <div class="left-col">

      <!-- Phased Array Polar Chart (thay Globe) -->
      <section class="panel">
        <h2>📡 Phased Array — Beam Tracking</h2>

        <!-- Controls -->
        <div class="phased-controls">
          <div class="algo-row">
            {#each ["conv","lms","mvdr","rls"] as a}
              <button
                class="algo-btn"
                class:active={phasedAlgo === a}
                on:click={() => { phasedAlgo = a; fetchPhasedArray(); }}
              >{a.toUpperCase()}</button>
            {/each}
          </div>
          <div class="n-row">
            <span class="n-label">N={phasedN}</span>
            <input type="range" min="2" max="16" step="2"
              bind:value={phasedN} on:change={fetchPhasedArray} />
          </div>
        </div>

        <!-- Polar chart component -->
        <PolarChart data={phasedData} satellite={bestSatellite} />

        <!-- Link budget mini -->
        {#if phasedData?.budget}
          <div class="budget-strip">
            <div class="bitem">
              <span class="blabel">C/N₀</span>
              <span class="bval accent">{phasedData.budget.CN0_dBHz} dBHz</span>
            </div>
            <div class="bitem">
              <span class="blabel">C/N</span>
              <span class="bval" style="color:{qualityColor}">{phasedData.budget.CN_db} dB</span>
            </div>
            <div class="bitem">
              <span class="blabel">FSPL</span>
              <span class="bval warn">{phasedData.budget.fspl_db} dB</span>
            </div>
            <div class="bitem">
              <span class="blabel">Margin</span>
              <span class="bval" class:good={phasedData.budget.link_ok}
                                 class:bad={!phasedData.budget.link_ok}>
                {phasedData.budget.link_margin_db > 0 ? "+" : ""}{phasedData.budget.link_margin_db} dB
              </span>
            </div>
            <div class="bitem">
              <span class="blabel">Link</span>
              <span class="bval" class:good={phasedData.budget.link_ok}
                                 class:bad={!phasedData.budget.link_ok}>
                {phasedData.budget.link_ok ? "✓ OK" : "✗ Fail"}
              </span>
            </div>
          </div>
        {/if}
      </section>

      <!-- Satellites -->
      <section class="panel mt-4">
        <h2>🛰️ Vệ Tinh ({displaySatellites.length})</h2>
        <div class="satellite-grid">
          {#each displaySatellites as sat}
            <div
              class="sat-chip interactive"
              class:active-sat={selectedSatelliteId === sat.id}
              class:best-sat={sat.id === bestSatellite?.id}
              on:click={() => toggleSatellite(sat.id)}
            >
              <div class="sat-title">{sat.id}</div>
              <div class="sat-info">
                <span>El {sat.elevation}°</span>
                <span>Az {sat.azimuth}°</span>
              </div>
              {#if sat.id === bestSatellite?.id}
                <div class="tracking-badge">● Tracking</div>
              {/if}
            </div>
          {/each}
          {#if displaySatellites.length === 0}
            <p class="text-muted">Không có vệ tinh nào.</p>
          {/if}
        </div>
      </section>
    </div>

    <!-- RIGHT COLUMN -->
    <div class="right-col">

      <!-- Gateways view từ engine -->
      <section class="panel">
        <h2>🌐 Gateways
          {#if selectedGateway}
            <span class="selected-gw-badge">Engine → {selectedGateway}</span>
          {/if}
        </h2>
        <div class="card-list">
          {#each gateways as gw}
            <div
              class="card interactive"
              class:border-green={gw.status === "Alive"}
              class:border-red={gw.status === "Dead"}
              class:active-gw={selectedGatewayId === gw.id}
              class:engine-selected={gw.name === selectedGateway}
              on:click={() => toggleGateway(gw.id)}
            >
              <div class="card-header">
                <h3>{gw.name}
                  {#if gw.name === selectedGateway}
                    <span class="engine-tag">▲ Engine</span>
                  {/if}
                </h3>
                <span class="badge" class:bg-green={gw.status==="Alive"} class:bg-red={gw.status==="Dead"}>
                  {gw.status}
                </span>
              </div>
              <div class="card-body">
                <!-- Gateway view từ engine -->
                {#each gatewaysView.filter(g => g.name === gw.name) as gv}
                  <p>El vệ tinh: <strong>{gv.elevation?.toFixed(1) ?? "N/A"}°</strong></p>
                  <p>C/N: <strong class:good={gv.cn > 10} class:warn={gv.cn <= 10}>
                    {gv.cn?.toFixed(1) ?? "N/A"} dB
                  </strong></p>
                {/each}
                <p>Traffic: <strong>{gw.traffic} Mbps</strong></p>
                <p>Ping: <strong>{gw.ping} ms</strong></p>
              </div>
            </div>
          {/each}
        </div>
      </section>

      <!-- Sessions -->
      <section class="panel mt-4">
        <h2>🔁 Sessions ({displaySessions.length})</h2>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>Session</th><th>Router</th><th>Satellite</th>
                <th>Gateway</th><th>Status</th><th>Latency/Loss</th>
              </tr>
            </thead>
            <tbody>
              {#each displaySessions as s}
                <tr>
                  <td>{s.id}</td>
                  <td><code>{s.routerMac.slice(-5)}</code></td>
                  <td><span class="highlight">{s.satelliteId}</span></td>
                  <td>{s.gatewayId}</td>
                  <td>
                    <span class="status-dot {s.status.toLowerCase()}"></span>
                    {s.status}
                  </td>
                  <td>{s.latency}ms / {s.packetLoss}%</td>
                </tr>
              {/each}
              {#if displaySessions.length === 0}
                <tr><td colspan="6" class="text-muted">Chưa có session.</td></tr>
              {/if}
            </tbody>
          </table>
        </div>
      </section>

      <!-- Routers -->
      <section class="panel mt-4">
        <h2>📡 Routers ({displayRouters.length})</h2>
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>MAC</th><th>Type</th><th>C/N</th>
                <th>Elevation</th><th>Signal</th><th>Lock</th>
              </tr>
            </thead>
            <tbody>
              {#each displayRouters as r}
                <tr>
                  <td><code>{r.mac}</code></td>
                  <td><span class="badge-outline">{r.type}</span></td>
                  <td class:text-warning={r.cnRatio < 15}
                      class:text-good={r.cnRatio >= 15}>
                    {r.cnRatio?.toFixed(1)} dB
                  </td>
                  <td>{r.elevation}°</td>
                  <td style="color:{
                    r.signalQuality === 'Good'   ? '#22c55e' :
                    r.signalQuality === 'Medium' ? '#f59e0b' : '#ef4444'
                  }">{r.signalQuality}</td>
                  <td>{r.antennaLock ? "✅" : "❌"}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>

      <!-- Handover history + WS live event -->
      <div class="system-logs mt-4">
        <div class="logs-header">
          <h3>🔄 Lịch sử Handover</h3>
          {#if wsEvent}
            <span class="ws-live
              {wsEvent.type === 'HANDOVER_START' ? 'ws-warn' :
               wsEvent.type === 'HANDOVER_DONE'  ? 'ws-good' : 'ws-info'}">
              ⚡ {wsEvent.type}
            </span>
          {/if}
        </div>
        <ul>
          {#each handoverHistory as event}
            <li>
              <span class="log-time">[{new Date(event.timestamp).toLocaleTimeString()}]</span>
              <strong>{event.satellite}</strong>
              ➔ <span class="log-gw">{event.gateway}</span>
              <span class="log-meta">Q:{event.quality}% C/N:{event.cn}dB</span>
            </li>
          {/each}
          {#if handoverHistory.length === 0}
            <li class="text-muted">Chưa có bản ghi.</li>
          {/if}
        </ul>
      </div>

    </div>
  </div>
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: 'Inter', system-ui, sans-serif;
    background: #07111f;
    color: #e2e8f0;
  }

  .dashboard { min-height: 100vh; padding: 20px 24px; box-sizing: border-box; }

  /* Header */
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
    gap: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid #1e293b;
  }
  .logo-area h1 { margin: 0; font-size: 26px; font-weight: 800; }
  .logo-area span { color: #38bdf8; }
  .logo-area p { margin: 2px 0 0; color: #64748b; font-size: 13px; }

  .global-stats { display: flex; gap: 10px; flex-wrap: wrap; }
  .stat-box {
    background: #0f1e33;
    border: 1px solid #1e3a5f;
    border-radius: 10px;
    padding: 10px 14px;
    min-width: 120px;
  }
  .label { display: block; font-size: 11px; color: #64748b; margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.4px; }
  .value { font-size: 18px; font-weight: 700; }
  .value-neon  { color: #22c55e; }
  .value-amber { color: #f59e0b; }

  /* Filter bar */
  .filter-bar {
    background: #1e3a8a;
    border-left: 4px solid #38bdf8;
    padding: 10px 16px;
    border-radius: 8px;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 14px;
  }
  .btn-clear {
    background: rgba(255,255,255,0.1);
    border: none; color: white;
    padding: 5px 12px; border-radius: 4px; cursor: pointer;
  }
  .btn-clear:hover { background: #ef4444; }

  /* Grid */
  .grid-container {
    display: grid;
    grid-template-columns: 380px 1fr;
    gap: 16px;
  }
  @media (max-width: 1100px) {
    .grid-container { grid-template-columns: 1fr; }
  }

  /* Panel */
  .panel {
    background: #0b1728;
    border: 1px solid #1e293b;
    border-radius: 12px;
    padding: 16px;
  }
  .panel h2 {
    margin: 0 0 14px;
    font-size: 15px;
    font-weight: 600;
    color: #94a3b8;
    border-bottom: 1px solid #1e293b;
    padding-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .mt-4 { margin-top: 16px; }

  /* Phased Array Controls */
  .phased-controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    gap: 12px;
  }
  .algo-row { display: flex; gap: 6px; }
  .algo-btn {
    background: #111f35;
    border: 1px solid #1e3a5f;
    color: #64748b;
    padding: 5px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
    transition: 0.15s;
  }
  .algo-btn.active { background: #38bdf8; color: #000; border-color: #38bdf8; }
  .algo-btn:hover:not(.active) { color: #e2e8f0; }
  .n-row { display: flex; align-items: center; gap: 8px; }
  .n-label { font-size: 12px; color: #64748b; white-space: nowrap; }
  input[type="range"] { width: 80px; accent-color: #38bdf8; }

  /* Budget strip */
  .budget-strip {
    display: flex;
    gap: 4px;
    margin-top: 10px;
    background: #060d1a;
    border-radius: 8px;
    padding: 10px;
    flex-wrap: wrap;
  }
  .bitem { flex: 1; min-width: 60px; text-align: center; }
  .blabel { display: block; font-size: 9px; color: #475569; text-transform: uppercase; margin-bottom: 3px; }
  .bval { font-size: 13px; font-weight: 700; }

  /* Satellites */
  .satellite-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    max-height: 280px;
    overflow-y: auto;
  }
  .sat-chip {
    background: #111f35;
    padding: 10px;
    border-radius: 8px;
    border: 1px solid transparent;
    cursor: pointer;
    transition: 0.15s;
  }
  .sat-chip:hover { border-color: #334155; }
  .sat-title { font-size: 12px; font-weight: 700; color: #f1f5f9; }
  .sat-info { display: flex; justify-content: space-between; font-size: 11px; color: #64748b; margin-top: 3px; }
  .tracking-badge { font-size: 10px; color: #f59e0b; font-weight: 600; margin-top: 3px; }
  .active-sat { border-color: #facc15 !important; background: #422006; }
  .best-sat   { border-color: #f59e0b; }

  /* Gateways */
  .card-list { display: flex; flex-direction: column; gap: 10px; }
  .card {
    background: #111f35;
    border-radius: 10px;
    padding: 12px;
    border: 1px solid transparent;
    border-left: 4px solid #475569;
    cursor: pointer;
    transition: 0.15s;
  }
  .card:hover { transform: translateY(-1px); }
  .border-green { border-left-color: #22c55e; }
  .border-red   { border-left-color: #ef4444; }
  .active-gw    { border-color: #38bdf8 !important; background: #0c4a6e; }
  .engine-selected { border-color: #f59e0b !important; }

  .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .card-header h3 { margin: 0; font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
  .engine-tag { font-size: 10px; color: #f59e0b; font-weight: 700; }
  .selected-gw-badge {
    font-size: 11px; color: #f59e0b;
    background: rgba(245,158,11,0.1);
    padding: 2px 8px; border-radius: 4px;
    font-weight: 600;
  }
  .card-body p { margin: 3px 0; font-size: 13px; color: #94a3b8; }

  /* Table */
  .table-wrapper { overflow-x: auto; }
  .data-table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 400px; }
  .data-table th, .data-table td { padding: 9px 10px; border-bottom: 1px solid #1e293b; text-align: left; }
  .data-table th { color: #64748b; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }
  .data-table tr:hover td { background: rgba(255,255,255,0.02); }

  /* Badges */
  .badge { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }
  .bg-green { background: #14532d; color: #86efac; }
  .bg-red   { background: #7f1d1d; color: #fecaca; }
  .badge-outline { border: 1px solid #38bdf8; color: #7dd3fc; padding: 2px 6px; border-radius: 4px; font-size: 11px; }

  /* Status dot */
  .status-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 5px; }
  .status-dot.connected   { background: #22c55e; }
  .status-dot.handover    { background: #f59e0b; }
  .status-dot.searching   { background: #818cf8; }
  .status-dot.interrupted { background: #ef4444; }

  /* Logs */
  .system-logs { background: #020617; border-radius: 10px; padding: 14px; border: 1px solid #1e293b; }
  .logs-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
  .system-logs h3 { margin: 0; color: #38bdf8; font-size: 14px; }
  .system-logs ul { list-style: none; padding: 0; margin: 0; }
  .system-logs li { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #94a3b8; padding: 5px 0; border-bottom: 1px dashed #1e293b; }
  .log-time { color: #475569; }
  .log-gw   { color: #38bdf8; }
  .log-meta { color: #475569; margin-left: 6px; }

  .ws-live { font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 4px; }
  .ws-warn { background: rgba(245,158,11,0.15); color: #f59e0b; }
  .ws-good { background: rgba(34,197,94,0.15);  color: #22c55e; }
  .ws-info { background: rgba(56,189,248,0.15); color: #38bdf8; }

  /* Utils */
  .highlight   { color: #facc15; font-weight: 700; }
  .accent      { color: #38bdf8; }
  .good        { color: #22c55e; }
  .bad         { color: #ef4444; }
  .warn        { color: #f59e0b; }
  .text-warning { color: #f59e0b; }
  .text-good    { color: #22c55e; }
  .text-muted   { color: #475569; font-style: italic; font-size: 13px; }
  .interactive  { cursor: pointer; transition: 0.15s; }
  .interactive:hover { transform: translateY(-1px); }

  :global(::-webkit-scrollbar) { width: 4px; }
  :global(::-webkit-scrollbar-thumb) { background: #1e293b; border-radius: 2px; }
</style>