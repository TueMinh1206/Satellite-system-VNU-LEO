<script lang="ts">
  export let azimuth: number = 0;   // 0–360°
  export let elevation: number = 0; // 0–90°
  export let locked: boolean = false;
  export let satelliteId: string = "";
  export let cn: number = 0;

  // Convert polar (az, el) to SVG cartesian
  // el=90° → center, el=0° → outer ring
  const SIZE = 200;
  const CENTER = SIZE / 2;
  const MAX_R = CENTER - 16;

  $: radius = ((90 - elevation) / 90) * MAX_R;
  $: angleRad = ((azimuth - 90) * Math.PI) / 180; // 0°=North → top
  $: px = CENTER + radius * Math.cos(angleRad);
  $: py = CENTER + radius * Math.sin(angleRad);

  // Rings at 0°, 30°, 60°, 90° elevation
  const elevations = [0, 30, 60, 90];
  $: rings = elevations.map(el => ({
    el,
    r: ((90 - el) / 90) * MAX_R,
    label: el + "°"
  }));

  // Cardinal direction labels
  const cardinals = [
    { label: "N", angle: 0 },
    { label: "E", angle: 90 },
    { label: "S", angle: 180 },
    { label: "W", angle: 270 },
  ];

  function cardinalPos(angle: number, offset = 14) {
    const r = MAX_R + offset;
    const rad = ((angle - 90) * Math.PI) / 180;
    return { x: CENTER + r * Math.cos(rad), y: CENTER + r * Math.sin(rad) };
  }
</script>

<div class="tracker-wrapper">
  <div class="tracker-title">
    📡 Anten Bám Vệ Tinh
    {#if locked}
      <span class="locked-badge">LOCKED</span>
    {:else}
      <span class="searching-badge">SEARCHING</span>
    {/if}
  </div>

  <svg width={SIZE} height={SIZE} viewBox="0 0 {SIZE} {SIZE}" class="polar-svg">
    <!-- Background -->
    <circle cx={CENTER} cy={CENTER} r={MAX_R + 2} fill="#070f1e" stroke="#1e3a5f" stroke-width="1" />

    <!-- Elevation rings -->
    {#each rings as ring}
      <circle
        cx={CENTER} cy={CENTER} r={ring.r}
        fill="none" stroke="#1e3a5f" stroke-width="0.8"
        stroke-dasharray={ring.el === 0 ? "none" : "3,3"}
      />
      {#if ring.el > 0 && ring.el < 90}
        <text x={CENTER + ring.r + 3} y={CENTER - 3} fill="#334155" font-size="8">{ring.label}</text>
      {/if}
    {/each}

    <!-- Cross hairs -->
    <line x1={CENTER} y1={CENTER - MAX_R} x2={CENTER} y2={CENTER + MAX_R} stroke="#1e3a5f" stroke-width="0.5" />
    <line x1={CENTER - MAX_R} y1={CENTER} x2={CENTER + MAX_R} y2={CENTER} stroke="#1e3a5f" stroke-width="0.5" />

    <!-- Cardinal labels -->
    {#each cardinals as c}
      {@const pos = cardinalPos(c.angle)}
      <text x={pos.x} y={pos.y + 3.5} text-anchor="middle" fill="#38bdf8" font-size="10" font-weight="bold">{c.label}</text>
    {/each}

    <!-- Satellite dot -->
    {#if locked}
      <!-- Pulse ring animation -->
      <circle cx={px} cy={py} r="14" fill="none" stroke="#22c55e" stroke-width="1.5" opacity="0.3" class="pulse-ring" />
      <circle cx={px} cy={py} r="7" fill="none" stroke="#22c55e" stroke-width="1" opacity="0.6" class="pulse-ring-2" />
      <!-- Main dot -->
      <circle cx={px} cy={py} r="5" fill="#22c55e" class="sat-dot" />
      <!-- Satellite label -->
      <text x={px} y={py - 10} text-anchor="middle" fill="#22c55e" font-size="7" font-weight="bold" class="sat-label">
        {satelliteId.length > 12 ? satelliteId.slice(0, 12) + "…" : satelliteId}
      </text>
    {:else}
      <circle cx={CENTER} cy={CENTER} r="4" fill="#475569" />
      <text x={CENTER} y={CENTER + 16} text-anchor="middle" fill="#475569" font-size="9">No signal</text>
    {/if}
  </svg>

  <!-- Stats row -->
  <div class="tracker-stats">
    <div class="ts-item">
      <span class="ts-label">Az</span>
      <span class="ts-value">{azimuth.toFixed(1)}°</span>
    </div>
    <div class="ts-item">
      <span class="ts-label">El</span>
      <span class="ts-value">{elevation.toFixed(1)}°</span>
    </div>
    <div class="ts-item">
      <span class="ts-label">C/N</span>
      <span class="ts-value" class:text-good={cn >= 15} class:text-warning={cn > 0 && cn < 15}>{cn.toFixed(1)} dB</span>
    </div>
  </div>
</div>

<style>
  .tracker-wrapper {
    background: #0b1728;
    border: 1px solid #1e293b;
    border-radius: 14px;
    padding: 14px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
  }
  .tracker-title {
    font-size: 13px;
    font-weight: bold;
    color: #94a3b8;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .locked-badge {
    background: #14532d;
    color: #86efac;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 10px;
    animation: blink 1.5s ease-in-out infinite;
  }
  .searching-badge {
    background: #3b1d00;
    color: #fb923c;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 10px;
  }
  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }

  .polar-svg {
    overflow: visible;
  }
  .sat-dot {
    transition: cx 0.8s ease-out, cy 0.8s ease-out;
    filter: drop-shadow(0 0 4px #22c55e);
  }
  .sat-label {
    transition: x 0.8s ease-out, y 0.8s ease-out;
  }
  .pulse-ring {
    animation: pulse 2s ease-out infinite;
    transition: cx 0.8s ease-out, cy 0.8s ease-out;
  }
  .pulse-ring-2 {
    animation: pulse 2s ease-out infinite 0.7s;
    transition: cx 0.8s ease-out, cy 0.8s ease-out;
  }
  @keyframes pulse {
    0% { transform-origin: center; transform: scale(0.7); opacity: 0.6; }
    100% { transform-origin: center; transform: scale(1.4); opacity: 0; }
  }

  .tracker-stats {
    display: flex;
    gap: 16px;
    width: 100%;
    justify-content: center;
  }
  .ts-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }
  .ts-label {
    font-size: 10px;
    color: #64748b;
    text-transform: uppercase;
  }
  .ts-value {
    font-size: 14px;
    font-weight: bold;
    color: #e2e8f0;
    font-family: 'Courier New', monospace;
  }
  .text-good { color: #4ade80; }
  .text-warning { color: #facc15; }
</style>
