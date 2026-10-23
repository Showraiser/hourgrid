"use client";
import {
  Area, Bar, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { cur, hhmm, SeriesPoint } from "@/lib/api";

// one colour per meaning (see globals.css); every series also carries a [NN] tag
export const C = {
  sun: "#f1f1ee", flow: "#a9c3ea", grid: "rgba(241,241,238,0.6)", ref: "#b9b3e6", battery: "#5e9a45",
  text: "#f1f1ee", muted: "rgba(241,241,238,0.42)", line: "rgba(241,241,238,0.12)", alert: "#b9b3e6", spot: "#a9c3ea", ink: "#f1f1ee",
};
const FONT = "IBM Plex Mono, ui-monospace, monospace";
const axis = { fill: "currentColor", stroke: "none", fontSize: 10, fontFamily: FONT, opacity: 0.75 };
const tip = {
  contentStyle: { background: "#0d0d10", border: "1px solid rgba(241,241,238,0.12)", borderRadius: 2, fontSize: 11.5, color: "#f1f1ee", fontFamily: FONT },
  labelStyle: { color: "rgba(241,241,238,0.5)" },
  cursor: { stroke: "rgba(241,241,238,0.3)" },
};
const legend = { wrapperStyle: { fontSize: 11, fontFamily: FONT, color: "rgba(241,241,238,0.7)" } };
const gridc = { stroke: "currentColor", strokeOpacity: 0.15, strokeDasharray: "1 4" };

export function PriceChart({ data }: { data: SeriesPoint[] }) {
  const d = data.map((p) => ({ ...p, t: hhmm(p.ts) }));
  const hasRef = data.some((p) => p.ref_price != null);
  return (
    <ResponsiveContainer width="100%" height={290}>
      <LineChart data={d} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
        <CartesianGrid {...gridc} vertical={false} />
        <XAxis dataKey="t" tick={axis} minTickGap={30} />
        <YAxis tick={axis} domain={[0, "auto"]} tickFormatter={(v: number) => v.toFixed(v < 1 ? 2 : 1)} width={48} />
        <Tooltip {...tip} formatter={(v: number) => `${cur()}${Number(v).toFixed(2)}/kWh`} />
        <Legend {...legend} />
        <Line type="stepAfter" dataKey="grid_price" name="[01] Grid tariff" stroke={C.grid} strokeDasharray="6 4" dot={false} />
        <Line type="stepAfter" dataKey="feed_in" name="[02] Paid for surplus" stroke={C.muted} strokeDasharray="2 5" dot={false} />
        {hasRef && <Line type="stepAfter" dataKey="ref_price" name="[04] Wholesale (real)" stroke={C.ref} strokeDasharray="1 3" strokeWidth={2} dot={false} />}
        <Line type="monotone" dataKey="price" name="[03] P2P clearing" stroke={C.flow} strokeWidth={2.5} style={{ filter: "drop-shadow(0 0 4px rgba(169,195,234,.7))" }} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function EnergyChart({ data }: { data: SeriesPoint[] }) {
  const d = data.map((p) => ({
    t: hhmm(p.ts),
    solar: +(p.solar_wh / 1000).toFixed(2),
    load: +(p.load_wh / 1000).toFixed(2),
    traded: +(p.volume_wh / 1000).toFixed(2),
    soc: p.battery_soc,
  }));
  return (
    <ResponsiveContainer width="100%" height={250}>
      <ComposedChart data={d} margin={{ top: 8, right: 0, left: -10, bottom: 0 }}>
        <defs>
          <pattern id="sunfill" width="4" height="4" patternUnits="userSpaceOnUse">
            <rect x="1" y="1" width="1.2" height="1.2" fill="#a9c3ea" opacity="0.6" />
          </pattern>
        </defs>
        <CartesianGrid {...gridc} vertical={false} />
        <XAxis dataKey="t" tick={axis} minTickGap={30} />
        <YAxis yAxisId="e" tick={axis} unit=" kWh" width={64} />
        <YAxis yAxisId="s" orientation="right" tick={axis} unit="%" domain={[0, 100]} width={40} />
        <Tooltip {...tip} />
        <Legend {...legend} />
        <Area yAxisId="e" type="monotone" dataKey="solar" name="[01] Solar" fill="url(#sunfill)" stroke={C.sun} strokeWidth={1.5} />
        <Line yAxisId="e" type="monotone" dataKey="load" name="[02] Use" stroke={C.grid} strokeDasharray="6 3" dot={false} strokeWidth={1.5} />
        <Bar yAxisId="e" dataKey="traded" name="[03] Traded P2P" fill="#a9c3ea" />
        <Line yAxisId="s" type="monotone" dataKey="soc" name="[04] Battery %" stroke={C.battery} strokeDasharray="1 3" strokeWidth={2} dot={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function OrderBookChart({ curves, price }: { curves: { demand: { wh: number; price: number }[]; supply: { wh: number; price: number }[] }; price: number | null }) {
  const max = Math.max(1, ...curves.demand.map((p) => p.wh), ...curves.supply.map((p) => p.wh));
  return (
    <ResponsiveContainer width="100%" height={270}>
      <LineChart margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
        <CartesianGrid {...gridc} vertical={false} />
        <XAxis dataKey="wh" type="number" tick={axis} unit=" Wh" domain={[0, max]} />
        <YAxis tick={axis} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(2)} width={48} />
        <Tooltip {...tip} formatter={(v: number) => `${cur()}${Number(v).toFixed(2)}`} labelFormatter={(l) => `${l} Wh`} />
        <Legend {...legend} />
        <Line data={curves.demand} dataKey="price" name="[B] Bids" stroke={C.grid} strokeDasharray="6 3" strokeWidth={1.5} dot={false} type="linear" />
        <Line data={curves.supply} dataKey="price" name="[A] Asks" stroke={C.sun} strokeWidth={2} dot={false} type="linear" />
        {price != null && (
          <Line data={[{ wh: 0, price }, { wh: max, price }]} dataKey="price" name="[P] Clearing" stroke={C.flow} strokeWidth={2} dot={false} />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ForecastChart({ data }: { data: { ts: string; gen_wh: number; load_wh: number; gen_fc: number; load_fc: number }[] }) {
  const d = data.map((p) => ({ ...p, t: hhmm(p.ts) }));
  return (
    <ResponsiveContainer width="100%" height={250}>
      <LineChart data={d} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
        <CartesianGrid {...gridc} vertical={false} />
        <XAxis dataKey="t" tick={axis} minTickGap={30} />
        <YAxis tick={axis} unit=" Wh" width={60} />
        <Tooltip {...tip} formatter={(v: number) => `${Math.round(v)} Wh`} />
        <Legend {...legend} />
        <Line dataKey="gen_wh" name="[01] Solar" stroke={C.sun} strokeWidth={2} dot={false} />
        <Line dataKey="gen_fc" name="[01F] Solar forecast" stroke={C.sun} strokeDasharray="3 3" dot={false} />
        <Line dataKey="load_wh" name="[02] Use" stroke={C.muted} strokeWidth={2} dot={false} />
        <Line dataKey="load_fc" name="[02F] Use forecast" stroke={C.muted} strokeDasharray="3 3" dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function WeatherChart({ data }: { data: { ts: string; ghi: number; ghi_forecast: number }[] }) {
  const d = data.map((p) => ({ ...p, t: hhmm(p.ts) }));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <ComposedChart data={d} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
        <CartesianGrid {...gridc} vertical={false} />
        <XAxis dataKey="t" tick={axis} minTickGap={36} />
        <YAxis tick={axis} width={44} />
        <Tooltip {...tip} formatter={(v: number) => `${Math.round(v)} W/m²`} />
        <Legend {...legend} />
        <Area dataKey="ghi" name="[01] Measured W/m²" stroke="#a9c3ea" fill="url(#sunfill2)" strokeWidth={1.5} />
        <Line dataKey="ghi_forecast" name="[02] Day-ahead forecast" stroke={C.muted} strokeDasharray="3 3" dot={false} />
        <defs>
          <linearGradient id="sunfill2" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#a9c3ea" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#a9c3ea" stopOpacity={0} />
          </linearGradient>
        </defs>
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Tiny inline sparkline for KPI tiles. */
export function Spark({ values, color, bars = false }: { values: number[]; color: string; bars?: boolean }) {
  if (values.length < 2) return <svg className="spark" />;
  const w = 120, h = 28, max = Math.max(...values, 1e-9), min = Math.min(0, ...values);
  const x = (i: number) => (i / (values.length - 1)) * w;
  const y = (v: number) => h - 2 - ((v - min) / (max - min || 1)) * (h - 4);
  if (bars) {
    const bw = w / values.length;
    return (
      <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        {values.map((v, i) => <rect key={i} x={i * bw} y={y(v)} width={Math.max(0.6, bw - 0.6)} height={h - y(v)} fill={color} opacity={0.85} />)}
      </svg>
    );
  }
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <path d={`${path}L${w},${h}L0,${h}Z`} fill={color} opacity={0.12} />
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
