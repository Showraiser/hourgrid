"use client";
import { useEffect, useRef } from "react";

/**
 * "Botanical study": a powder-blue hydrangea drawn from ~460 procedural florets,
 * lit by a streaked beam of sunlight, with white cross-stitch marks. Live data:
 *   beam brightness + length   = measured irradiance (the sun)
 *   florets open + brighten    = irradiance (closed and grey at night)
 *   cross-stitch over the head = energy traded P2P in the last 15-min slot
 *   stitch cluster by the stem = hourly certificates minted today
 *   leaf colour                = battery state of charge (deeper green when full)
 * Transparent canvas on a black page.
 */
export interface HydrangeaData {
  ghi: number;
  tradedWh: number;
  certificates: number;
  soc: number;
}

const W = 1260;
const H = 880;
const S = H;
// beam palette: pinks and the hydrangea's own colours (rose, orchid, lavender, powder blue)
const SPECTRUM = [[255, 150, 196], [246, 160, 226], [214, 168, 255], [185, 179, 230], [169, 195, 234], [200, 215, 248], [255, 182, 214]];
const CX = 900, CY = 345;           // flower head centre (art spans the whole hero)
const RX = 245, RY = 210;           // flower head radii
type Ctx = CanvasRenderingContext2D;

function rng(seed: number) {
  let s = seed;
  return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
}

// smooth value noise for the stitch pattern
function makeNoise(seed: number) {
  const r = rng(seed);
  const g: number[] = Array.from({ length: 64 * 64 }, () => r());
  const at = (x: number, y: number) => g[((y & 63) * 64) + (x & 63)];
  return (x: number, y: number) => {
    const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
    const s = (t: number) => t * t * (3 - 2 * t);
    const a = at(xi, yi), b = at(xi + 1, yi), c = at(xi, yi + 1), d = at(xi + 1, yi + 1);
    return a + (b - a) * s(xf) + (c - a) * s(yf) + (a - b - c + d) * s(xf) * s(yf);
  };
}

/** A hydrangea leaf: ovate, serrated, slightly curved, lit half + shaded half, curving veins. */
function drawLeaf(g: Ctx, x: number, y: number, len: number, wid: number, ang: number, green: [number, number, number], bend = 0.08, flip = false, pet = 34) {
  g.save(); g.translate(x, y); g.rotate(ang);
  if (flip) g.scale(1, -1);
  const N = 90, teeth = 30;
  const mid = (u: number) => bend * len * u * u;                                   // curved midrib
  const half = (u: number) => {                                                     // half-width with a pointed tip
    const base = Math.sin(Math.PI * Math.pow(u, 0.72)) * wid * (1 - 0.18 * u);
    const f = (u * teeth) % 1;
    const tooth = (f < 0.75 ? f / 0.75 : (1 - f) / 0.25) * 3.2 * Math.min(1, u * 6) * Math.min(1, (1 - u) * 5);
    return base + tooth;
  };
  const upper: [number, number][] = [], lower: [number, number][] = [];
  for (let i = 0; i <= N; i++) {
    const u = i / N;
    upper.push([u * len, mid(u) - half(u)]);
    lower.push([u * len, mid(u) + half(u) * 0.94]);
  }
  const midPts: [number, number][] = Array.from({ length: N + 1 }, (_, i) => [(i / N) * len, mid(i / N)]);
  const [r0, g0, b0] = green;
  // petiole: from the stem (origin) out to the blade
  g.beginPath(); g.moveTo(0, 0); g.quadraticCurveTo(pet * 0.5, -3, pet, 0);
  g.strokeStyle = `rgb(${r0 + 28},${g0 + 38},${b0 + 8})`; g.lineWidth = 6; g.lineCap = "round"; g.stroke();
  g.translate(pet, 0);
  // lit half (upper) and shaded half (lower)
  for (const [edge, light] of [[upper, true], [lower, false]] as const) {
    g.beginPath();
    edge.forEach(([px, py], i) => (i ? g.lineTo(px, py) : g.moveTo(px, py)));
    for (let i = N; i >= 0; i--) g.lineTo(midPts[i][0], midPts[i][1]);
    g.closePath();
    const lg = g.createLinearGradient(0, light ? -wid : wid, len * 0.3, 0);
    if (light) {
      lg.addColorStop(0, `rgb(${r0 + 10},${g0 + 18},${b0})`);
      lg.addColorStop(0.7, `rgb(${r0 + 38},${g0 + 62},${b0 + 18})`);
      lg.addColorStop(1, `rgb(${r0 + 52},${g0 + 78},${b0 + 26})`);
    } else {
      lg.addColorStop(0, `rgb(${r0 - 30},${g0 - 42},${b0 - 18})`);
      lg.addColorStop(1, `rgb(${r0 - 6},${g0 - 6},${b0 - 6})`);
    }
    g.fillStyle = lg; g.fill();
    g.strokeStyle = `rgba(${Math.max(0, r0 - 50)},${Math.max(0, g0 - 70)},${Math.max(0, b0 - 30)},0.55)`; g.lineWidth = 0.8; g.stroke();
  }
  // soft sheen along the lit half
  const sh = g.createRadialGradient(len * 0.42, mid(0.42) - wid * 0.35, 2, len * 0.42, mid(0.42) - wid * 0.35, wid * 0.9);
  sh.addColorStop(0, "rgba(235,255,210,0.22)"); sh.addColorStop(1, "rgba(235,255,210,0)");
  g.fillStyle = sh; g.beginPath(); g.ellipse(len * 0.42, mid(0.42) - wid * 0.35, wid * 0.9, wid * 0.5, 0, 0, Math.PI * 2); g.fill();
  // veins: from the midrib, curving outward and toward the tip
  for (let i = 1; i <= 8; i++) {
    const u = 0.06 + i * 0.1;
    if (u > 0.9) break;
    for (const sgn of [-1, 1]) {
      const sx = u * len, sy = mid(u);
      const eu = Math.min(0.97, u + 0.2);
      const ex = eu * len, ey = mid(eu) + sgn * half(eu) * 0.86;
      g.beginPath(); g.moveTo(sx, sy);
      g.quadraticCurveTo(sx + len * 0.05, sy + sgn * half(u) * 0.75, ex, ey);
      g.strokeStyle = sgn < 0 ? "rgba(205,240,170,0.42)" : "rgba(160,200,120,0.28)";
      g.lineWidth = 1.2 - i * 0.07; g.stroke();
    }
  }
  // midrib, tapering
  for (let i = 0; i < N; i += 3) {
    const [ax, ay] = midPts[i], [bx, by] = midPts[Math.min(N, i + 3)];
    g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by);
    g.strokeStyle = "rgba(215,245,180,0.6)"; g.lineWidth = 2.6 * (1 - i / N) + 0.5; g.stroke();
  }
  g.restore();
}

function drawFloret(g: Ctx, x: number, y: number, size: number, rot: number, hue: number, light: number, sat: number) {
  g.save(); g.translate(x, y); g.rotate(rot);
  for (let k = 0; k < 4; k++) {
    g.rotate(Math.PI / 2);
    g.beginPath(); g.moveTo(0, 0);
    g.bezierCurveTo(size * 0.15, -size * 0.52, size * 0.9, -size * 0.5, size, 0);
    g.bezierCurveTo(size * 0.9, size * 0.5, size * 0.15, size * 0.52, 0, 0);
    g.fillStyle = `hsl(${hue}, ${sat}%, ${light}%)`; g.fill();
    g.strokeStyle = `hsla(${hue}, ${sat}%, ${light - 18}%, 0.55)`; g.lineWidth = 0.7; g.stroke();
    g.beginPath(); g.moveTo(size * 0.15, 0); g.lineTo(size * 0.8, 0);
    g.strokeStyle = `hsla(${hue}, ${sat}%, ${Math.min(96, light + 10)}%, 0.6)`; g.lineWidth = 0.6; g.stroke();
  }
  g.beginPath(); g.arc(0, 0, size * 0.13, 0, Math.PI * 2); g.fillStyle = `hsl(${hue + 20}, 30%, 92%)`; g.fill();
  g.restore();
}

export function HydrangeaScene({ data }: { data: HydrangeaData }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const live = useRef(data);
  live.current = data;

  useEffect(() => {
    const c = ref.current!;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = W * dpr; c.height = H * dpr;
    const g = c.getContext("2d")!;
    const r = rng(11);

    // florets: sunflower spiral inside an ellipse, drawn back (top) to front (bottom)
    const florets = Array.from({ length: 540 }, (_, i) => {
      const t = Math.sqrt((i + 0.5) / 540), a = i * 2.39996;
      const jitter = 0.94 + r() * 0.12;
      return {
        x: CX + Math.cos(a) * RX * t * jitter, y: CY + Math.sin(a) * RY * t * jitter,
        size: 20 + r() * 13, rot: r() * Math.PI, hueJ: Math.pow(r(), 2.2), depth: t,
      };
    }).sort((p, q) => p.y - q.y);

    const beam = Array.from({ length: 230 }, () => {
      const off = (r() - 0.5) * 390;
      // colour follows position across the beam (a prism), with some random sparkle
      const pos = Math.max(0, Math.min(SPECTRUM.length - 1.001, ((off + 195) / 390) * (SPECTRUM.length - 1) + (r() - 0.5) * 1.2));
      const i0 = Math.floor(pos), f = pos - i0, c0 = SPECTRUM[i0], c1 = SPECTRUM[i0 + 1];
      const tint = r() < 0.12 ? [255, 255, 255] : c0.map((v, k) => Math.round(v + (c1[k] - v) * f));
      return { off, w: 1 + r() * 5, a: 0.10 + r() * 0.34, tint, ph: r() * 6, len: 0.55 + r() * 0.45 };
    });
    const noise = makeNoise(5);
    const cluster = Array.from({ length: 60 }, () => ({ x: CX + 230 + (r() - 0.5) * 120 * r(), y: CY + 370 + (r() - 0.5) * 110 * r() }));

    // cache the flower layer; re-render only when bloom or leaf colour changes noticeably
    const head = document.createElement("canvas");
    head.width = W * dpr; head.height = H * dpr;
    const hg = head.getContext("2d")!;
    let cachedKey = "";
    let coverage = 0;
    let raf = 0, last = 0;
    const t0 = performance.now();

    const renderHead = (bloom: number, night: boolean, soc: number) => {
      hg.setTransform(dpr, 0, 0, dpr, 0, 0);
      hg.clearRect(0, 0, W, H);
      const green: [number, number, number] = [Math.round(58 + 14 * (1 - soc)), Math.round(112 + 22 * soc), Math.round(46 + 6 * soc)];
      // stem (cubic bezier); leaves attach to points on it
      const P = [[CX + 40, CY + RY - 30], [CX + 58, CY + RY + 140], [CX + 30, CY + RY + 260], [CX + 64, H + 10]];
      const stemAt = (t: number) => {
        const u = 1 - t;
        return [0, 1].map((k) => u * u * u * P[0][k] + 3 * u * u * t * P[1][k] + 3 * u * t * t * P[2][k] + t * t * t * P[3][k]) as [number, number];
      };
      hg.beginPath(); hg.moveTo(P[0][0], P[0][1]);
      hg.bezierCurveTo(P[1][0], P[1][1], P[2][0], P[2][1], P[3][0], P[3][1]);
      hg.strokeStyle = `rgb(${green[0] + 25},${green[1] + 25},${green[2]})`; hg.lineWidth = 11; hg.stroke();
      hg.strokeStyle = "rgba(220,240,190,0.35)"; hg.lineWidth = 2; hg.stroke();
      const [rx, ry] = stemAt(0.26);   // right leaf: higher, reaching right and slightly up
      const [lx, ly] = stemAt(0.44);   // left leaf: lower, reaching left and drooping
      drawLeaf(hg, rx + 4, ry, 250, 92, -0.4, green, 0.1, false, 30);
      drawLeaf(hg, lx - 4, ly, 285, 106, Math.PI - 0.24, green, 0.12, true, 34);
      // redraw the stem over the leaf joints so the stalks tuck in behind it
      hg.beginPath(); hg.moveTo(P[0][0], P[0][1]);
      hg.bezierCurveTo(P[1][0], P[1][1], P[2][0], P[2][1], P[3][0], P[3][1]);
      hg.strokeStyle = `rgb(${green[0] + 25},${green[1] + 25},${green[2]})`; hg.lineWidth = 11; hg.stroke();
      hg.strokeStyle = "rgba(220,240,190,0.35)"; hg.lineWidth = 2; hg.stroke();
      // flower head
      for (const f of florets) {
        const shade = 1 - 0.35 * Math.max(0, (f.x - CX) / RX * 0.5 + (f.y - CY) / RY * 0.5);   // light from upper left
        const hue = 212 + f.hueJ * 40;                 // mostly powder blue, a few lavender
        const light = night ? 36 + 14 * shade : (70 + 18 * shade) * (0.88 + 0.12 * bloom);
        const sat = night ? 16 : 55 + 10 * f.hueJ;
        drawFloret(hg, f.x, f.y, f.size * (0.55 + 0.45 * bloom), f.rot, hue, Math.min(92, light), sat);
      }
    };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (now - last < 40) return;
      last = now;
      const t = (now - t0) / 1000;
      const d = live.current;
      const sun = Math.max(0, Math.min(1, d.ghi / 950));
      const night = d.ghi < 8;
      const bloom = night ? 0.25 : 0.45 + 0.55 * sun;
      const soc = Math.max(0, Math.min(1, d.soc / 100));
      const key = `${night}:${Math.round(bloom * 10)}:${Math.round(soc * 5)}`;
      if (key !== cachedKey) { renderHead(bloom, night, soc); cachedKey = key; }

      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, W, H);

      // sunbeam: prismatic streaks from the upper left toward the flower
      if (!night) {
        g.save();
        g.translate(CX - 60, CY - 20);
        g.rotate(-Math.PI * 0.79);
        g.globalCompositeOperation = "lighter";
        const L = 760 + 420 * sun;
        // a soft spectral band across the beam's width
        const band = g.createLinearGradient(0, -200, 0, 200);
        SPECTRUM.forEach((c, i) => band.addColorStop(i / (SPECTRUM.length - 1), `rgba(${c[0]},${c[1]},${c[2]},${0.10 + 0.10 * sun})`));
        g.fillStyle = band; g.fillRect(0, -200, L, 400);
        for (const b of beam) {
          const len = L * b.len;
          const grd = g.createLinearGradient(0, 0, len, 0);
          const a = b.a * (0.45 + 0.55 * sun) * (0.75 + 0.25 * Math.sin(t * 0.7 + b.ph));
          grd.addColorStop(0, `rgba(${b.tint[0]},${b.tint[1]},${b.tint[2]},0)`);
          grd.addColorStop(0.2, `rgba(${b.tint[0]},${b.tint[1]},${b.tint[2]},${a})`);
          grd.addColorStop(1, `rgba(${b.tint[0]},${b.tint[1]},${b.tint[2]},${a * 0.5})`);
          g.fillStyle = grd;
          g.fillRect(0, b.off, len, b.w);
        }
        // feather the beam: fade along its length and across its edges
        g.globalCompositeOperation = "destination-out";
        const along = g.createLinearGradient(0, 0, L, 0);
        along.addColorStop(0, "rgba(0,0,0,0.9)"); along.addColorStop(0.1, "rgba(0,0,0,0)");
        along.addColorStop(0.78, "rgba(0,0,0,0)"); along.addColorStop(1, "rgba(0,0,0,1)");
        g.fillStyle = along; g.fillRect(0, -210, L + 10, 420);
        const across = g.createLinearGradient(0, -205, 0, 205);
        across.addColorStop(0, "rgba(0,0,0,1)"); across.addColorStop(0.18, "rgba(0,0,0,0)");
        across.addColorStop(0.82, "rgba(0,0,0,0)"); across.addColorStop(1, "rgba(0,0,0,1)");
        g.fillStyle = across; g.fillRect(0, -210, L + 10, 420);
        g.globalCompositeOperation = "source-over";
        g.restore();
        // soften where the beam meets the top and left edges of the hero
        g.globalCompositeOperation = "destination-out";
        const top = g.createLinearGradient(0, 0, 0, 90);
        top.addColorStop(0, "rgba(0,0,0,1)"); top.addColorStop(1, "rgba(0,0,0,0)");
        g.fillStyle = top; g.fillRect(0, 0, W, 90);
        const left = g.createLinearGradient(0, 0, 120, 0);
        left.addColorStop(0, "rgba(0,0,0,1)"); left.addColorStop(1, "rgba(0,0,0,0)");
        g.fillStyle = left; g.fillRect(0, 0, 120, H);
        g.globalCompositeOperation = "source-over";
      }

      g.drawImage(head, 0, 0, W, H);

      // cross-stitch over the head: coverage follows energy traded (eased)
      const target = Math.min(0.34, d.tradedWh / 14000);
      coverage += (target - coverage) * 0.06;
      const cell = 11;
      g.strokeStyle = "rgba(255,255,255,0.95)"; g.lineWidth = 2.1; g.lineCap = "square";
      g.beginPath();
      for (let y = CY - RY; y < CY + RY + 20; y += cell) {
        for (let x = CX - RX - 20; x < CX + RX + 20; x += cell) {
          const ex = (x - CX) / (RX + 10), ey = (y - CY) / (RY + 10);
          if (ex * ex + ey * ey > 1) continue;
          const n = noise(x / 46 + 3, y / 46 + t * 0.03);
          if (n > 1 - coverage) {
            const s = 3.4;
            g.moveTo(x - s, y - s); g.lineTo(x + s, y + s); g.moveTo(x + s, y - s); g.lineTo(x - s, y + s);
          }
        }
      }
      // certificate stitches by the stem
      const nC = Math.min(cluster.length, Math.round(Math.sqrt(Math.max(0, d.certificates)) * 4));
      for (let i = 0; i < nC; i++) {
        const p = cluster[i];
        const s = 4;
        g.moveTo(p.x - s, p.y - s); g.lineTo(p.x + s, p.y + s); g.moveTo(p.x + s, p.y - s); g.lineTo(p.x - s, p.y + s);
      }
      g.stroke();
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);

  return <canvas ref={ref} style={{ aspectRatio: `${W} / ${H}` }} aria-label="Hydrangea study: beam is sunlight, stitches are energy traded, stitch cluster is certificates minted" />;
}
