"use client";
import Link from "next/link";
import { Home, kwh, rs } from "@/lib/api";
import { NeighbourhoodMap } from "@/components/NeighbourhoodMap";
import { CardHead } from "@/components/Bits";
import { usePoll } from "@/lib/usePoll";

const ROLE = { prosumer: "seller (solar)", consumer: "buyer", battery: "community battery" } as const;

export default function HomesPage() {
  const { data } = usePoll<Home[]>("/api/homes", 3000);
  return (
    <main className="grid">
      <div className="page-title"><h1>Participants</h1><span className="code">{data ? `${data.length} meters online` : ""}</span></div>
      <p className="muted" style={{ marginTop: -10 }}>Every participant has an AI trading agent. Pick one to see its forecast, decisions and certificates, or to give it instructions.</p>
      <section className="card">
        <CardHead title="Live meters" tag="FIG 4" />
        {data && <NeighbourhoodMap homes={data} />}
      </section>
      <section className="card">
      <CardHead title="Ledger" tag="ALL" />
      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th>Home</th><th>Type</th><th className="num">Solar</th><th>Now</th>
              <th className="num">Sold</th><th className="num">Bought</th>
              <th className="num">Extra vs grid buy-back</th><th className="num">Saved vs grid</th>
              <th className="num">Points</th><th className="num">Wallet balance</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((h) => {
              const r = h.last_reading;
              const now = h.role === "battery"
                ? `${h.soc_pct}% charged`
                : r
                  ? r.accepted === 0
                    ? "✕ reading blocked"
                    : r.export_wh > 0
                      ? `exporting ${Math.round(r.export_wh)} Wh`
                      : `importing ${Math.round(r.import_wh)} Wh`
                  : "-";
              return (
                <tr key={h.home_id}>
                  <td><Link href={`/homes/${h.home_id}`}>{h.name}</Link> <span className="muted small mono">{h.home_id}</span></td>
                  <td className="small"><span className={`badge ${h.role === "prosumer" ? "sell" : h.role === "consumer" ? "buy" : ""}`}>{ROLE[h.role]}</span>{h.kind === "business" ? " · business" : ""}{h.has_ev ? " · EV" : ""}{h.has_ac ? " · AC" : ""}</td>
                  <td className="num">{h.role === "battery" ? `${h.capacity_kwh} kWh` : h.pv_kwp ? `${h.pv_kwp} kWp` : "-"}</td>
                  <td className="small">{now}</td>
                  <td className="num">{h.sold_wh ? kwh(h.sold_wh) : "-"}</td>
                  <td className="num">{h.bought_wh ? kwh(h.bought_wh) : "-"}</td>
                  <td className="num">{h.role === "prosumer" ? rs(h.extra_vs_feed_in) : "-"}</td>
                  <td className="num">{h.bought_wh && h.role !== "battery" ? rs(h.saved_vs_grid) : "-"}</td>
                  <td className="num">{h.points}</td>
                  <td className="num">{rs(h.balance)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      </section>
    </main>
  );
}
