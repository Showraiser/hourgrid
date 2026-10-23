"use client";
import Link from "next/link";
import { Alert, short, txUrl } from "@/lib/api";
import { Spark } from "./Charts";
import { WarnIcon } from "./Decor";

export function Kpi({ n, label, value, sub, color, spark, bars }: {
  n?: string; label: string; value: React.ReactNode; sub?: React.ReactNode; color?: string; spark?: number[]; bars?: boolean;
}) {
  return (
    <div className="kpi" style={{ ["--accent" as string]: color }}>
      <div className="label">{n && <span className="n">[{n}]</span>}<span>{label}</span></div>
      <div className="value" style={{ color }}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
      {spark && <Spark values={spark} color={color ?? "#8b93a3"} bars={bars} />}
    </div>
  );
}

export function CardHead({ title, tag, code, children }: { title: string; tag?: string; code?: string; children?: React.ReactNode }) {
  return (
    <div className="card-head">
      {tag && <span className="tag">{tag}</span>}
      <h2>{title}</h2>
      {children}
      {code && <span className="code">{code}</span>}
    </div>
  );
}

export function Tx({ hash, explorer }: { hash: string | null | undefined; explorer?: string | null }) {
  if (!hash) return <span className="muted">—</span>;
  const first = hash.split(",")[0];
  const url = txUrl(explorer, first);
  return url ? (
    <a className="mono" href={url} target="_blank" rel="noreferrer">{short(first)}</a>
  ) : (
    <span className="mono" title={hash}>{short(first)}</span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const cls = status === "settled" ? "settled" : status.includes("error") ? "err" : "";
  const label: Record<string, string> = {
    settled: "on-chain ✓", committed: "committed", pending: "settling…", offchain: "off-chain",
    "no-trades": "no trades", "chain-error": "chain error",
  };
  return <span className={`badge ${cls}`}>{label[status] ?? status}</span>;
}

export function Alerts({ alerts }: { alerts: Alert[] | null }) {
  if (!alerts?.length) return <p className="small muted">No alerts. Every reading is within physical limits.</p>;
  return (
    <div>
      {alerts.map((a) => (
        <div key={a.id} className={`warnbox ${a.level === "info" ? "info" : ""}`}>
          <div className="ico"><WarnIcon /></div>
          <div>
            <div className="t">{a.kind}{a.sim_ts ? ` · ${a.sim_ts.slice(11, 16)}` : ""}</div>
            {a.message}
          </div>
        </div>
      ))}
    </div>
  );
}

export function HomeLink({ id, name }: { id: string; name?: string }) {
  return <Link href={`/homes/${id}`}>{name ?? id}</Link>;
}
