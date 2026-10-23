"use client";
import Link from "next/link";
import { use } from "react";
import { HomeLink, StatusBadge, Tx } from "@/components/Bits";
import { cur, hhmm, Verification } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";

export default function VerifyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: v, error } = usePoll<Verification>(`/api/certificates/${id}`, 5000);
  if (error) return <main className="card"><h1>Certificate not found</h1><p className="mono small">{id}</p></main>;
  if (!v) return <main className="card">Verifying…</main>;
  const c = v.certificate;
  const remaining = c.minted_wh - c.retired_wh;
  const matches = v.onchain && !v.onchain.error ? v.onchain.minted_wh === c.minted_wh && v.onchain.retired_wh === c.retired_wh : null;

  return (
    <main className="grid">
      <section className="card glow">
        <Link href="/certificates" className="small">← certificates</Link>
        <h1>Certificate verification</h1>
        <p className="mono small" style={{ wordBreak: "break-all" }}>{c.cert_id}</p>
        <p>
          <strong>{c.minted_wh} Wh</strong> of rooftop solar from <HomeLink id={v.producer.home_id} name={v.producer.name} />, generated{" "}
          <strong>{c.hour_start.slice(0, 10)} between {hhmm(c.hour_start)} and {c.hour_start.slice(11, 13)}:59 local time</strong> on feeder {v.producer.zone}.{" "}
          {c.retired_wh} Wh retired, {remaining} Wh still claimable.
        </p>
        {matches !== null && (
          <span className={`pill ${matches ? "ok" : "bad"}`}>
            {matches ? "✓ On-chain record matches" : "✗ On-chain record differs"} · contract {v.onchain?.contract?.slice(0, 10)}…
          </span>
        )}
        {v.onchain === null && <span className="pill">Off-chain mode: ledger record only</span>}
      </section>

      <section className="card">
        <h2>Provenance chain</h2>
        <div className="chain">
          <div className="step">
            <h3>[01] Registered meter</h3>
            <p className="small">Meter <span className="mono">{v.producer.meter_id}</span> ({v.producer.pv_kwp} kWp), onboarded by the DISCOM. Signing key <span className="mono">{v.producer.signer}</span>.</p>
          </div>
          {v.trades.map((t) => (
            <div className="step" key={`${t.interval_id}-${t.idx}`}>
              <h3>[02] {hhmm(t.ts)} interval: signed reading → trade → settlement</h3>
              <p className="small">
                Meter signed an export of <strong>{t.export_wh} Wh</strong> (physics limit at that irradiance: {Math.round(t.max_plausible_wh)} Wh ✓).
                Auction sold <strong>{t.wh} Wh</strong> to <HomeLink id={t.buyer} name={t.buyer_name} /> at {cur()}{t.price.toFixed(2)}/kWh.
              </p>
              <p className="small muted">
                Signature <span className="mono">{t.signature.slice(0, 18)}…</span> · fills root <span className="mono">{t.fills_root.slice(0, 14)}…</span> ·
                commit <Tx hash={t.commit_tx} explorer={v.explorer} /> · settle <Tx hash={t.settle_tx} explorer={v.explorer} /> · <StatusBadge status={t.interval_status} />
              </p>
            </div>
          ))}
          {v.retirements.map((r) => (
            <div className="step" key={r.id}>
              <h3>[03] Retired</h3>
              <p className="small">
                {r.wh} Wh retired by <HomeLink id={r.home_id} name={r.name} /> for &quot;{r.beneficiary}&quot; at {r.ts.slice(0, 16).replace("T", " ")} ·{" "}
                {r.tx ? <Tx hash={r.tx} explorer={v.explorer} /> : r.status}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>Current holders</h2>
        {v.holders.length ? v.holders.map((x) => (
          <p key={x.home_id} className="small"><HomeLink id={x.home_id} name={x.name} />: {x.wh} Wh</p>
        )) : <p className="muted small">Fully retired.</p>}
      </section>
    </main>
  );
}
