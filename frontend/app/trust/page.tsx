"use client";
import Link from "next/link";
import { useState } from "react";
import { Alerts } from "@/components/Bits";
import { Alert, Certificate, Home, post } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";

type RetireRes = { ok: boolean; layer?: string; error?: string; message?: string; tx?: string | null };

export default function TrustPage() {
  const { data: homes } = usePoll<Home[]>("/api/homes", 5000);
  const { data: certs, refresh: refreshCerts } = usePoll<Certificate[]>("/api/certificates?limit=200", 5000);
  const { data: alerts } = usePoll<Alert[]>("/api/alerts?limit=30", 2000);
  const [target, setTarget] = useState("H03");
  const [tamperMsg, setTamperMsg] = useState<string | null>(null);
  const [steps, setSteps] = useState<{ label: string; res: RetireRes }[]>([]);
  const [busy, setBusy] = useState(false);

  const prosumers = homes?.filter((h) => h.role === "prosumer") ?? [];
  const oracleAlerts = alerts?.filter((a) => a.kind === "oracle" || a.kind === "double-claim") ?? [];

  const tamper = async () => {
    const r = await post<{ meter_id: string; applies_to: string }>("/api/demo/tamper", { home_id: target, export_wh: 3000 });
    setTamperMsg(`Meter ${r.meter_id} will report 3,000 Wh exported in the ${r.applies_to.slice(11, 16)} interval. Run the market and watch the alerts.`);
  };

  const doubleClaim = async () => {
    const c = certs?.find((x) => !!x.settled && x.holders?.some((h) => h.home_id !== "BAT" && h.wh > 0));
    if (!c) return setSteps([{ label: "No settled certificate held by a household yet. Run the market through solar hours first.", res: { ok: false } }]);
    const holder = c.holders!.find((h) => h.home_id !== "BAT" && h.wh > 0)!;
    setBusy(true);
    try {
      const first = await post<RetireRes>("/api/certificates/retire", { home_id: holder.home_id, cert_id: c.cert_id, wh: holder.wh, beneficiary: "EV charging (first claim)" });
      const second = await post<RetireRes>("/api/certificates/retire", { home_id: holder.home_id, cert_id: c.cert_id, wh: holder.wh, beneficiary: "Same energy, second claim" });
      setSteps([
        { label: `1st claim: ${holder.home_id} retires ${holder.wh} Wh of certificate ${c.cert_id.slice(0, 10)}…`, res: first },
        { label: "2nd claim: the same household tries to retire the same Wh again", res: second },
      ]);
      refreshCerts();
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="grid">
      <div className="page-title"><h1>Trust demo</h1><span className="code">2 attacks · 9 on-chain checks</span></div>
      <section className="card glow">
        <h2 style={{ marginBottom: 8 }}>Two ways to cheat an energy market</h2>
        <p className="muted">The two ways energy markets get cheated: a meter that lies, and a clean-energy claim counted twice. Try both.</p>
      </section>

      <section className="grid g2">
        <div className="card">
          <h2>[01] A meter lies</h2>
          <p className="small">
            A prosumer&apos;s meter claims 3 kWh of solar export in one 15-minute slot. The physics oracle compares it with measured
            sunlight × panel size. In the evening that limit is close to zero, so the reading is rejected before it can trade.
            If the oracle were bypassed, the smart contract still caps export at capacity × 15 min × 115%.
          </p>
          <div className="row">
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              {prosumers.map((h) => <option key={h.home_id} value={h.home_id}>{h.name} ({h.pv_kwp} kWp)</option>)}
            </select>
            <button className="danger" onClick={tamper}>Inject fake reading</button>
          </div>
          {tamperMsg && <div className="alert" style={{ marginTop: 10 }}>{tamperMsg}</div>}
        </div>

        <div className="card">
          <h2>[02] Same kWh claimed twice</h2>
          <p className="small">
            Picks a certificate a household holds, retires it, then tries again. Retiring burns the token, so the second attempt fails in the
            GranularCertificate contract (or the ledger in off-chain mode).
          </p>
          <button className="danger" onClick={doubleClaim} disabled={busy}>{busy ? "Submitting…" : "Try double claim"}</button>
          <div style={{ marginTop: 10 }}>
            {steps.map((s, i) => (
              <div key={i} className={`step ${s.res.ok ? "" : "bad"}`} style={{ marginBottom: 8 }}>
                <p className="small"><strong>{s.label}</strong></p>
                {s.res.ok ? (
                  <p className="small">✓ Accepted{s.res.tx ? ` · tx ${s.res.tx.slice(0, 14)}…` : ""}</p>
                ) : s.res.error ? (
                  <p className="small">✗ Rejected by <strong>{s.res.layer}</strong>: <span className="mono">{s.res.error}</span>. {s.res.message}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="grid g2">
        <div className="card">
          <h2>Security alerts</h2>
          <Alerts alerts={oracleAlerts.length ? oracleAlerts : null} />
        </div>
        <div className="card">
          <h2>What the contracts enforce</h2>
          <table className="small">
            <tbody>
              <tr><td>Only DISCOM-registered meters can sell</td><td className="mono">MeterRegistry</td></tr>
              <tr><td>Every sale needs the meter&apos;s EIP-712 signed reading</td><td className="mono">BadMeterSignature</td></tr>
              <tr><td>Export ≤ capacity × 15 min × 115%</td><td className="mono">ExceedsPhysicalLimit</td></tr>
              <tr><td>Sold Wh ≤ metered export, per meter per interval</td><td className="mono">ExceedsMeteredExport</td></tr>
              <tr><td>A meter can&apos;t sign two different readings</td><td className="mono">AttestationConflict</td></tr>
              <tr><td>Only trades in the committed Merkle root settle, once</td><td className="mono">InvalidProof · AlreadySettled</td></tr>
              <tr><td>Money is conserved (fuzz-tested)</td><td className="mono">testFuzz_Conservation</td></tr>
              <tr><td>Certificates burn on retirement</td><td className="mono">ERC1155InsufficientBalance</td></tr>
              <tr><td>Reward points can&apos;t be traded</td><td className="mono">Soulbound</td></tr>
            </tbody>
          </table>
          <p className="small muted" style={{ marginTop: 8 }}>See <Link href="/certificates">certificates</Link> to trace any Wh back to its meter.</p>
        </div>
      </section>
    </main>
  );
}
