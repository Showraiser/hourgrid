"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { CountryProfile, post, setCurrency, State, Weather } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";

const LINKS = [
  { href: "/", label: "Market" },
  { href: "/homes", label: "Participants" },
  { href: "/certificates", label: "Certificates" },
  { href: "/trust", label: "Trust demo" },
];
const dotClass = (s?: string) => (s === "live" ? "live" : s === "needs-credentials" ? "warn" : s === "fallback" ? "off" : "");
const statusText = (s?: string) =>
  s === "live" ? "real" : s === "needs-credentials" ? "add key" : s === "n/a" || s === "static" ? "official factor" : s === "pending" ? "…" : "modelled";

export function Header() {
  const path = usePathname();
  const { data: s, error, refresh } = usePoll<State>("/api/state", 2000);
  const { data: w } = usePoll<Weather>("/api/weather", 60000);
  const { data: list } = usePoll<{ countries: CountryProfile[] }>("/api/countries", 600000);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (s?.country) setCurrency(s.country.symbol); }, [s?.country]);

  const act = async (p: string, body?: unknown) => {
    setBusy(true);
    try { await post(p, body); await refresh(); } finally { setBusy(false); }
  };
  const choose = (v: string) => {
    const [country, site] = v.split(":");
    if (confirm(`Switch the market? Today's trades are cleared${s?.chain.enabled ? " and fresh contracts are deployed" : ""}.`)) act("/api/country", { country, site });
  };
  const chain = s?.chain;
  const ds = s?.data_sources;

  return (
    <header>
      <div className="topnav">
        <Link href="/" className="logo">HourGrid<span className="it">market study</span></Link>
        <nav className="tabs">
          {LINKS.map((l, i) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return <Link key={l.href} href={l.href} className={active ? "active" : ""}><span className="n">0{i + 1}</span>{l.label}</Link>;
          })}
        </nav>
        <span className="spacer" />
        {s?.country && list && (
          <select value={`${s.country.code}:${s.site.id}`} onChange={(e) => choose(e.target.value)} disabled={busy || !s.ready} title="market">
            {list.countries.map((c) => (
              <optgroup key={c.code} label={`${c.name} / ${c.currency}`}>
                {c.sites.map((site) => <option key={site.id} value={`${c.code}:${site.id}`}>{c.flag} {c.name} / {site.name.split(" (")[0].split(",")[0]}</option>)}
              </optgroup>
            ))}
          </select>
        )}
        {s?.ready && (
          <div className="row">
            {s.running
              ? <button disabled={busy} onClick={() => act("/api/sim/pause")}>Pause</button>
              : <button className="primary" disabled={busy} onClick={() => act("/api/sim/start")}>Run</button>}
            <button disabled={busy || s.running} onClick={() => act("/api/sim/step?n=4")} title="advance one hour">+1h</button>
            <select value={s.seconds_per_interval} title="seconds per 15-minute slot" onChange={(e) => act("/api/sim/speed", { seconds_per_interval: Number(e.target.value) })}>
              {Array.from(new Set([1, 2, 4, 8, 15, s.seconds_per_interval])).sort((a, b) => a - b).map((v) => <option key={v} value={v}>{v}s/slot</option>)}
            </select>
            <button disabled={busy} onClick={() => confirm("Restart the day? All trades are cleared.") && act("/api/sim/reset")} title="restart the day">Reset</button>
          </div>
        )}
      </div>
      <div className="rail">
        {error && !s ? (
          <span className="chip"><span className="dot off" />backend offline / run uvicorn hourgrid.api:app --port 8000</span>
        ) : !s || !s.country ? (
          <span className="chip"><span className="dot warn" />{s?.status ?? "connecting"}…</span>
        ) : (
          <>
            <span className="chip"><span className={`dot ${s.running ? "live" : ""}`} /><span className="v">{s.clock.slice(11, 16)}</span> local</span>
            <span className="chip"><span className="k">tariff</span><span className="v">{s.period_label}</span></span>
            {w && <span className="chip"><span className="k">sky now</span><span className="v">{Math.round(w.current.ghi ?? 0)} w/m² / {w.current.temp_air}°c / {w.current.cloud_cover}% cloud</span></span>}
            {ds && (["weather", "market_price", "grid_carbon"] as const).map((k) => (
              <span key={k} className="chip" title={ds[k].source}><span className={`dot ${dotClass(ds[k].status)}`} /><span className="k">{k === "weather" ? "weather" : k === "market_price" ? "price" : "co₂"}</span><span className="v">{statusText(ds[k].status)}</span></span>
            ))}
            <span className="chip" title={chain?.error}><span className={`dot ${chain?.status === "connected" ? "live" : chain?.status === "error" ? "off" : ""}`} /><span className="k">ledger</span><span className="v">{!chain?.enabled ? "off-chain" : chain.status === "connected" ? `chain ${chain.chain_id} / block ${chain.block}` : chain.status}</span></span>
          </>
        )}
      </div>
    </header>
  );
}
