"use client";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { HomeLink } from "@/components/Bits";
import { Certificate, hhmm } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";

export default function CertificatesPage() {
  const { data } = usePoll<Certificate[]>("/api/certificates?limit=150", 4000);
  const [q, setQ] = useState("");
  const router = useRouter();
  return (
    <main className="grid">
      <div className="page-title"><h1>Certificates</h1><span className="code">ERC-1155 · 1 unit = 1 Wh</span></div>
      <section className="card glow">
        <h2 style={{ marginBottom: 8 }}>Hourly clean-energy certificates</h2>
        <p className="muted">
          Each certificate is an ERC-1155 token for one producer meter and one hour. 1 unit = 1 Wh that was metered, traded and settled.
          Retiring burns it, so the same Wh can never be claimed twice.
        </p>
        <div className="row">
          <input style={{ flex: 1, maxWidth: 560 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Paste a certificate ID (0x…) to verify" />
          <button className="primary" onClick={() => q && router.push(`/verify/${q.trim()}`)}>Verify</button>
        </div>
      </section>
      <section className="card tablewrap">
        <table>
          <thead>
            <tr><th>Hour</th><th>Producer</th><th className="num">Minted</th><th className="num">Retired</th><th>Held by</th><th>ID</th></tr>
          </thead>
          <tbody>
            {data?.map((c) => (
              <tr key={c.cert_id}>
                <td className="mono small">{c.hour_start.slice(5, 10)} {hhmm(c.hour_start)}</td>
                <td><HomeLink id={c.home_id} name={c.producer} /></td>
                <td className="num">{c.minted_wh} Wh</td>
                <td className="num">{c.retired_wh ? `${c.retired_wh} Wh` : "-"}</td>
                <td className="small">{c.holders?.map((x) => `${x.home_id} (${x.wh})`).join(", ")}</td>
                <td><Link className="mono small" href={`/verify/${c.cert_id}`}>{c.cert_id.slice(0, 12)}…</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data?.length && <p className="empty">No certificates yet. Run the market through solar hours.</p>}
      </section>
    </main>
  );
}
