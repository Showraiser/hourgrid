"use client";
import Link from "next/link";
import { use, useState } from "react";
import { HomeLink, Kpi, StatusBadge } from "@/components/Bits";
import { ForecastChart } from "@/components/Charts";
import { cur, HomeDetail, hhmm, kwh, post, rs } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";

type Msg = { me: boolean; text: string; engine?: string };

export default function HomePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: h, refresh } = usePoll<HomeDetail>(`/api/homes/${id}`, 3000);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"instruct" | "ask">("instruct");
  const [busy, setBusy] = useState(false);
  const [retireMsg, setRetireMsg] = useState<string | null>(null);

  if (!h) return <main className="card">Loading…</main>;

  const send = async () => {
    if (!text.trim()) return;
    const t = text;
    setText("");
    setMsgs((m) => [...m, { me: true, text: t }]);
    setBusy(true);
    try {
      if (mode === "instruct") {
        const r = await post<{ reply: string; engine: string }>(`/api/agents/${id}/instruct`, { text: t });
        setMsgs((m) => [...m, { me: false, text: r.reply, engine: r.engine }]);
        refresh();
      } else {
        const r = await post<{ answer: string; engine: string }>(`/api/agents/${id}/ask`, { text: t });
        setMsgs((m) => [...m, { me: false, text: r.answer, engine: r.engine }]);
      }
    } catch (e) {
      setMsgs((m) => [...m, { me: false, text: `Error: ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  };

  const retire = async (cert_id: string, wh: number) => {
    const beneficiary = prompt("Retire on behalf of (e.g. 'EV charging, 21 Oct')", `${h.name} household use`);
    if (!beneficiary) return;
    const r = await post<{ ok: boolean; message?: string; error?: string; tx?: string }>("/api/certificates/retire", {
      home_id: id, cert_id, wh, beneficiary,
    });
    setRetireMsg(r.ok ? `Retired ${wh} Wh${r.tx ? ` · tx ${r.tx.slice(0, 12)}…` : ""}` : `Rejected: ${r.message ?? r.error}`);
    refresh();
  };

  const isBattery = h.role === "battery";
  return (
    <main className="grid">
      <div>
        <Link href="/homes" className="small">← all participants</Link>
        <div className="page-title" style={{ marginBottom: 6 }}><h1>{h.name}</h1><span className={`badge ${h.role === "prosumer" ? "sell" : "buy"}`}>{h.home_id} · {h.role === "prosumer" ? "seller" : h.role === "consumer" ? "buyer" : "battery"}</span></div>
        <p className="muted">
          {h.role === "prosumer" ? `${h.pv_kwp} kWp rooftop solar` : isBattery ? `${h.capacity_kwh} kWh community battery` : "No rooftop solar"}
          {h.has_ev ? " · EV" : ""}{h.has_ac ? " · AC" : ""} · meter <span className="mono">{h.meter_id}</span> · wallet <span className="mono">{h.wallet.slice(0, 10)}…</span>
        </p>
      </div>

      <section className="grid g4">
        <Kpi n="01" label="Sold to neighbours" value={kwh(h.sold_wh)} sub={h.role === "prosumer" ? `${rs(h.extra_vs_feed_in)} more than the grid pays` : ""} />
        <Kpi n="02" label="Bought from neighbours" value={kwh(h.bought_wh)} sub={!isBattery && h.bought_wh ? `${rs(h.saved_vs_grid)} saved vs grid` : ""} />
        <Kpi n="03" label="Green Hour points" value={h.points} sub="soulbound · earned by buying solar and retiring certificates" />
        <Kpi label={isBattery ? "State of charge" : "Wallet balance"} value={isBattery ? `${h.soc_pct}%` : rs(h.balance)} />
      </section>

      <section className="grid g3">
        <div className="card span2">
          <h2>{isBattery ? "Battery activity" : "AI forecast vs actual"}</h2>
          {h.series.length && !isBattery ? <ForecastChart data={h.series} /> : <p className="empty">{isBattery ? "See trades below." : "No data yet."}</p>}
        </div>
        <div className="card">
          <h2>Talk to the agent</h2>
          <div className="row" style={{ marginBottom: 8 }}>
            <button className={mode === "instruct" ? "primary" : ""} onClick={() => setMode("instruct")} disabled={isBattery}>Give instruction</button>
            <button className={mode === "ask" ? "primary" : ""} onClick={() => setMode("ask")}>Ask why</button>
          </div>
          <div className="chat">
            {msgs.length === 0 && (
              <p className="small muted">
                {mode === "instruct"
                  ? `Try: "never sell below ${cur()}2", "prefer neighbour solar", "only offer 50% of my surplus", "stop trading".`
                  : 'Try: "why did you sell at noon?" or "how much have I earned?"'}
              </p>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`bubble ${m.me ? "me" : ""}`}>
                {m.text}
                {m.engine && <div className="small muted">via {m.engine}</div>}
              </div>
            ))}
          </div>
          <div className="row">
            <input style={{ flex: 1 }} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder={mode === "instruct" ? "Instruction…" : "Question…"} />
            <button className="primary" onClick={send} disabled={busy}>{busy ? "…" : "Send"}</button>
          </div>
          <details style={{ marginTop: 10 }}>
            <summary className="small muted">Current agent settings</summary>
            <pre className="mono small">{JSON.stringify(h.prefs, null, 2)}</pre>
          </details>
        </div>
      </section>

      <section className="grid g2">
        <div className="card">
          <h2>Agent decisions</h2>
          {h.orders.length ? (
            <table>
              <tbody>
                {h.orders.slice(0, 12).map((o, i) => (
                  <tr key={i}>
                    <td className="mono small">{o.ts ? hhmm(o.ts) : ""}</td>
                    <td><span className={`badge ${o.side}`}>{o.side}</span></td>
                    <td className="small">{o.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted">No orders yet.</p>}
        </div>
        <div className="card">
          <h2>Trades</h2>
          {h.trades.length ? (
            <table>
              <thead><tr><th>Time</th><th>With</th><th className="num">Wh</th><th className="num">{cur()}/kWh</th><th>Status</th></tr></thead>
              <tbody>
                {h.trades.slice(0, 14).map((f) => {
                  const sold = f.seller === id;
                  return (
                    <tr key={`${f.interval_id}-${f.idx}`}>
                      <td className="mono small">{f.ts ? hhmm(f.ts) : ""}</td>
                      <td className="small">{sold ? "sold to " : "bought from "}<HomeLink id={sold ? f.buyer : f.seller} /></td>
                      <td className="num">{f.wh}</td>
                      <td className="num">{f.price.toFixed(2)}</td>
                      <td><StatusBadge status={f.status} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : <p className="muted">No trades yet.</p>}
        </div>
      </section>

      {!isBattery && (
        <section className="card">
          <h2>Clean-energy certificates held</h2>
          {retireMsg && <div className={`alert ${retireMsg.startsWith("Rejected") ? "critical" : ""}`}>{retireMsg}</div>}
          {h.certificates.length ? (
            <table>
              <thead><tr><th>Hour</th><th>Produced by</th><th className="num">Held</th><th>Certificate</th><th /></tr></thead>
              <tbody>
                {h.certificates.map((c) => (
                  <tr key={c.cert_id}>
                    <td className="mono small">{c.hour_start.slice(0, 10)} {hhmm(c.hour_start)}–{c.hour_start.slice(11, 13)}:59</td>
                    <td><HomeLink id={c.home_id} /></td>
                    <td className="num">{c.held_wh} Wh</td>
                    <td><Link className="mono small" href={`/verify/${c.cert_id}`}>{c.cert_id.slice(0, 14)}…</Link></td>
                    <td>{c.settled ? <button onClick={() => retire(c.cert_id, c.held_wh ?? 0)}>Retire</button> : <span className="badge">□ settling</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted">No certificates yet. They are minted when this home buys a neighbour&apos;s solar.</p>}
        </section>
      )}
    </main>
  );
}
