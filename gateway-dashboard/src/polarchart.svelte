<script lang="ts">
  import { afterUpdate, onMount } from "svelte";

  export let data:      any = null;   // từ api.py /api/phased-array
  export let satellite: any = null;   // bestSatellite từ index.js

  let canvas: HTMLCanvasElement;
  let patCanvas: HTMLCanvasElement;

  $: if (data && canvas)     { drawPolar();   }
  $: if (data && patCanvas)  { drawPattern(); }

  onMount(() => {
    if (data) { drawPolar(); drawPattern(); }
  });

  afterUpdate(() => {
    if (data) { drawPolar(); drawPattern(); }
  });

  // ── Setup canvas với DPR ─────────────────────────────────────────────
  function setup(c: HTMLCanvasElement) {
    const r    = window.devicePixelRatio || 1;
    const rect = c.getBoundingClientRect();
    c.width    = rect.width  * r;
    c.height   = rect.height * r;
    const ctx  = c.getContext("2d")!;
    ctx.scale(r, r);
    return { ctx, w: rect.width, h: rect.height };
  }

  // ── Polar Chart ──────────────────────────────────────────────────────
  function drawPolar() {
    if (!canvas || !data) return;
    const { ctx, w, h } = setup(canvas);

    const cx = w / 2;
    const cy = h / 2;
    const R  = Math.min(w, h) / 2 - 28;

    // Background
    ctx.fillStyle = "#060d1a";
    ctx.fillRect(0, 0, w, h);

    // Rings + labels
    const rings = [0.25, 0.5, 0.75, 1.0];
    const dbLabels = ["-49", "-33", "-16", "0"];
    rings.forEach((r, i) => {
      ctx.strokeStyle = "rgba(255,255,255,0.07)";
      ctx.lineWidth   = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, R * r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "#334155";
      ctx.font = "9px Inter";
      ctx.textAlign = "center";
      ctx.fillText(dbLabels[i], cx + R * r + 4, cy - 3);
    });

    // Spokes (0°, 30°, 60°... = N/S/E/W + diagonals)
    const dirs: [number, string][] = [
      [0,"N"],[30,""],[60,""],[90,"E"],[120,""],[150,""],[180,"S"],[210,""],[240,""],[270,"W"],[300,""],[330,""]
    ];
    dirs.forEach(([deg, lbl]) => {
      const rad = (deg - 90) * Math.PI / 180;
      ctx.strokeStyle = "rgba(255,255,255,0.06)";
      ctx.lineWidth   = 1;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + R * Math.cos(rad), cy + R * Math.sin(rad));
      ctx.stroke();
      if (lbl) {
        ctx.fillStyle = "#475569";
        ctx.font = "10px Inter";
        ctx.textAlign = "center";
        ctx.fillText(lbl,
          cx + (R + 14) * Math.cos(rad),
          cy + (R + 14) * Math.sin(rad) + 3
        );
      }
    });

    // Pattern fill + stroke
    const angles  = data.angles  as number[];
    const pattern = data.pattern as number[];
    const minDb   = -65;
    const maxDb   = 0;

    const toXY = (angleDeg: number, db: number) => {
      const norm = Math.max(db - minDb, 0) / (maxDb - minDb);
      const r    = R * norm;
      // elevation angle → map to polar: 0°=top, rotate
      const rad  = (angleDeg - 90) * Math.PI / 180;
      return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
    };

    // Gradient fill
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
    grad.addColorStop(0,   "rgba(56,189,248,0.35)");
    grad.addColorStop(0.6, "rgba(56,189,248,0.15)");
    grad.addColorStop(1,   "rgba(56,189,248,0.02)");

    ctx.beginPath();
    angles.forEach((a, i) => {
      const { x, y } = toXY(a, pattern[i]);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.beginPath();
    angles.forEach((a, i) => {
      const { x, y } = toXY(a, pattern[i]);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth   = 2;
    ctx.stroke();

    // Steering direction (θ₀) — beam chính
    const theta0  = data.params.theta0;
    const { x: sx, y: sy } = toXY(theta0, 0);
    ctx.strokeStyle = "#f59e0b";
    ctx.lineWidth   = 2;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(sx, sy);
    ctx.stroke();

    // Arrowhead tại đầu beam
    const angle0 = (theta0 - 90) * Math.PI / 180;
    ctx.fillStyle = "#f59e0b";
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx - 8 * Math.cos(angle0 - 0.4), sy - 8 * Math.sin(angle0 - 0.4));
    ctx.lineTo(sx - 8 * Math.cos(angle0 + 0.4), sy - 8 * Math.sin(angle0 + 0.4));
    ctx.closePath();
    ctx.fill();

    // Null direction (θⱼ)
    const thetaJ  = data.params.theta_j;
    const { x: nx, y: ny } = toXY(thetaJ, 0);
    ctx.strokeStyle = "#ef4444";
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(nx, ny);
    ctx.stroke();
    ctx.setLineDash([]);

    // Satellite dot nếu có bestSatellite
    if (satellite) {
      const satAz  = satellite.azimuth;
      const satEl  = satellite.elevation;
      // Map: elevation 90° = center, 0° = edge
      const satR   = R;  // dot nằm ở vành ngoài (0 dB)
      const satRad = (data.params.theta0 - 90) * Math.PI / 180;
      const satX   = cx + satR * Math.cos(satRad);
      const satY   = cy + satR * Math.sin(satRad);

      ctx.fillStyle   = "#22c55e";
      ctx.strokeStyle = "#022c22";
      ctx.lineWidth   = 2;
      ctx.beginPath();
      ctx.arc(satX, satY, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      // Label
      ctx.fillStyle = "#22c55e";
      ctx.font = "bold 10px Inter";
      ctx.textAlign = "center";
      ctx.fillText("🛰", satX, satY - 10);
    }

    // Center dot
    ctx.fillStyle = "#38bdf8";
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fill();

    // Title
    ctx.fillStyle = "#94a3b8";
    ctx.font = "bold 11px Inter";
    ctx.textAlign = "center";
    ctx.fillText(
      `Polar · El ${data.params.elevation}° Az ${data.params.azimuth}°`,
      cx, 14
    );

    // Legend
    const legends = [
      { color: "#38bdf8", dash: false, label: "Pattern" },
      { color: "#f59e0b", dash: false, label: `Beam θ₀=${theta0.toFixed(1)}°` },
      { color: "#ef4444", dash: true,  label: `Null θⱼ=${thetaJ.toFixed(1)}°` },
      { color: "#22c55e", dot: true,   label: "Satellite" },
    ];
    legends.forEach((l, i) => {
      const lx = 8;
      const ly = h - 12 - i * 16;
      if ((l as any).dot) {
        ctx.fillStyle = l.color;
        ctx.beginPath();
        ctx.arc(lx + 6, ly - 4, 4, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.strokeStyle = l.color;
        ctx.lineWidth   = 1.5;
        if (l.dash) ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(lx, ly - 4);
        ctx.lineTo(lx + 14, ly - 4);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.fillStyle = "#64748b";
      ctx.font = "10px Inter";
      ctx.textAlign = "left";
      ctx.fillText(l.label, lx + 18, ly);
    });
  }

  // ── Radiation Pattern (Cartesian) ────────────────────────────────────
  function drawPattern() {
    if (!patCanvas || !data) return;
    const { ctx, w, h } = setup(patCanvas);

    const pad = { top: 20, right: 12, bottom: 28, left: 36 };
    const pw  = w - pad.left - pad.right;
    const ph  = h - pad.top  - pad.bottom;
    const minDb = -65, maxDb = 3;
    const dbRange = maxDb - minDb;

    ctx.fillStyle = "#060d1a";
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    [-60, -40, -20, 0].forEach(db => {
      const y = pad.top + ph * (1 - (db - minDb) / dbRange);
      ctx.strokeStyle = "rgba(255,255,255,0.06)";
      ctx.lineWidth   = 1;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + pw, y);
      ctx.stroke();
      ctx.fillStyle = "#334155";
      ctx.font = "9px Inter";
      ctx.textAlign = "right";
      ctx.fillText(`${db}`, pad.left - 3, y + 3);
    });

    [-90, -60, -30, 0, 30, 60, 90].forEach(a => {
      const x = pad.left + pw * ((a + 90) / 180);
      ctx.strokeStyle = "rgba(255,255,255,0.04)";
      ctx.beginPath();
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + ph);
      ctx.stroke();
      ctx.fillStyle = "#334155";
      ctx.font = "9px Inter";
      ctx.textAlign = "center";
      ctx.fillText(`${a}°`, x, pad.top + ph + 12);
    });

    // Pattern fill
    const angles  = data.angles  as number[];
    const pattern = data.pattern as number[];

    ctx.beginPath();
    angles.forEach((a, i) => {
      const x = pad.left + pw * ((a + 90) / 180);
      const y = pad.top  + ph * (1 - (pattern[i] - minDb) / dbRange);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    const fill = ctx.createLinearGradient(0, pad.top, 0, pad.top + ph);
    fill.addColorStop(0, "rgba(56,189,248,0.25)");
    fill.addColorStop(1, "rgba(56,189,248,0.02)");
    ctx.lineTo(pad.left + pw, pad.top + ph);
    ctx.lineTo(pad.left,      pad.top + ph);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();

    ctx.beginPath();
    angles.forEach((a, i) => {
      const x = pad.left + pw * ((a + 90) / 180);
      const y = pad.top  + ph * (1 - (pattern[i] - minDb) / dbRange);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth   = 1.8;
    ctx.stroke();

    // Beam line
    const theta0 = data.params.theta0;
    const x0 = pad.left + pw * ((theta0 + 90) / 180);
    ctx.strokeStyle = "#f59e0b";
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    ctx.moveTo(x0, pad.top);
    ctx.lineTo(x0, pad.top + ph);
    ctx.stroke();

    // Null line
    const thetaJ = data.params.theta_j;
    const xj = pad.left + pw * ((thetaJ + 90) / 180);
    ctx.strokeStyle = "#ef4444";
    ctx.lineWidth   = 1.2;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(xj, pad.top);
    ctx.lineTo(xj, pad.top + ph);
    ctx.stroke();
    ctx.setLineDash([]);

    // Title
    ctx.fillStyle = "#94a3b8";
    ctx.font = "bold 10px Inter";
    ctx.textAlign = "center";
    ctx.fillText(`Pattern — ${data.params.algo.toUpperCase()} N=${data.params.N}`, w / 2, 13);
  }
</script>

<div class="polar-wrap">
  {#if data}
    <div class="charts">
      <div class="polar-box">
        <canvas bind:this={canvas}></canvas>
      </div>
      <div class="pattern-box">
        <canvas bind:this={patCanvas}></canvas>
      </div>
    </div>
  {:else}
    <div class="placeholder">
      <div class="spinner"></div>
      <p>Đang tính beam pattern...</p>
    </div>
  {/if}
</div>

<style>
  .polar-wrap { width: 100%; }

  .charts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    height: 200px;
  }

  .polar-box, .pattern-box { height: 100%; }

  canvas {
    width: 100%;
    height: 100%;
    display: block;
    border-radius: 8px;
    border: 1px solid #1e293b;
  }

  .placeholder {
    height: 200px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    color: #475569;
    font-size: 13px;
  }

  .spinner {
    width: 28px; height: 28px;
    border: 3px solid #1e293b;
    border-top-color: #38bdf8;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>