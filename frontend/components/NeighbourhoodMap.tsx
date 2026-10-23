"use client";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { Home } from "@/lib/api";

const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16);
const COL = { export: "#7fbf63", import: "#a9c3ea", rejected: "#b9b3e6", battery: "#f1f1ee", idle: "rgba(241,241,238,0.2)" };

type Mode = keyof typeof COL;

/** Dot-density meter: dots = Wh this slot (green dots = export, blue rings = import). */
export function Pattern({ mode, level, ink }: { mode: Mode; level: number; ink?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current!;
    const w = 60, h = 18, s = 3;
    c.width = w * s;
    c.height = h * s;
    const g = c.getContext("2d")!;
    g.clearRect(0, 0, c.width, c.height);
    g.fillStyle = ink ?? COL[mode];
    g.strokeStyle = ink ?? COL[mode];
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const b = BAYER[(y & 3) * 4 + (x & 3)];
        if (mode === "export" && b < level) g.fillRect(x * s, y * s, 2, 2);
        else if (mode === "import" && b < level && (x + y) % 2 === 0) { g.lineWidth = 0.8; g.strokeRect(x * s + 0.4, y * s + 0.4, 2, 2); }
        else if (mode === "rejected" && (x + y) % 4 === 0) g.fillRect(x * s, y * s, 2, 2);
        else if (mode === "battery" && x / w < level && y > 3 && y < h - 3 && b < 0.9) g.fillRect(x * s, y * s, 2, 2);
        else if (mode === "idle" && x % 5 === 0 && y % 5 === 0) g.fillRect(x * s, y * s, 1.5, 1.5);
      }
    }
    if (mode === "battery") { g.lineWidth = 2; g.strokeRect(1, 6, c.width - 9, c.height - 12); g.fillRect(c.width - 6, c.height / 2 - 6, 5, 12); }
  }, [mode, level, ink]);
  return <canvas ref={ref} />;
}

export function NeighbourhoodMap({ homes }: { homes: Home[] }) {
  const max = Math.max(200, ...homes.map((h) => Math.max(h.last_reading?.export_wh ?? 0, h.last_reading?.import_wh ?? 0)));
  return (
    <div>
      <div className="nmap">
        {homes.map((h) => {
          const r = h.last_reading;
          let mode: Mode = "idle", level = 0, v = "—", cls = "";
          if (h.role === "battery") {
            mode = "battery"; level = (h.soc_pct ?? 0) / 100; v = `${h.soc_pct}%`;
          } else if (r && r.accepted === 0) {
            mode = "rejected"; v = "BLOCKED"; cls = "bad";
          } else if (r && r.export_wh > 5) {
            mode = "export"; level = 0.15 + 0.85 * (r.export_wh / max); v = `+${Math.round(r.export_wh)} Wh`;
          } else if (r && r.import_wh > 5) {
            mode = "import"; level = 0.15 + 0.85 * (r.import_wh / max); v = `−${Math.round(r.import_wh)} Wh`;
          }
          return (
            <Link key={h.home_id} href={`/homes/${h.home_id}`} className={`ncell ${cls}`} title={h.name}>
              <div className="top">
                <span className="num">{h.home_id === "BAT" ? "B1" : h.home_id.slice(1)}</span>
                <span>{h.role === "prosumer" ? `${h.pv_kwp} kWp` : h.role === "battery" ? `${h.capacity_kwh} kWh` : h.kind === "business" ? "shop" : "home"}</span>
              </div>
              <Pattern mode={mode} level={level} />
              <div className="v">{v}</div>
            </Link>
          );
        })}
      </div>
      <div className="legend">
        <span><i style={{ background: "radial-gradient(#7fbf63 1px, transparent 1.3px) 0 0 / 3px 3px", borderColor: "#7fbf63" }} />[A] exporting / dot density = wh</span>
        <span><i style={{ background: "repeating-linear-gradient(90deg, transparent 0 2px, #a9c3ea 2px 3px)", borderColor: "#a9c3ea" }} />[B] importing</span>
        <span><i style={{ borderStyle: "dashed" }} />[X] reading blocked</span>
        <span><i style={{ background: "repeating-linear-gradient(0deg, #f1f1ee 0 2px, transparent 2px 4px)" }} />B1 community battery</span>
      </div>
    </div>
  );
}
