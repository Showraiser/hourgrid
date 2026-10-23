"use client";
import Link from "next/link";
import { Alerts, CardHead, HomeLink, StatusBadge, Tx } from "@/components/Bits";
import { EnergyChart, OrderBookChart, PriceChart, WeatherChart } from "@/components/Charts";
import { Barcode, Sliced, XMark } from "@/components/Decor";
import { HydrangeaScene } from "@/components/HydrangeaScene";
import { NeighbourhoodMap } from "@/components/NeighbourhoodMap";
import { Alert, Certificate, cur, hhmm, hhmmPlus, Home, Interval, Kpis, rs, SeriesPoint, State, Weather } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";

/** Per market: large background words in the local language, and the italic quote. */
const LOCAL: Record<string, { big: string[]; lang: string; quote: string[] }> = {
  TR: { big: ["GÜNEŞİ", "PAYLAŞ", "KOMŞUNA"], lang: "tr", quote: ["noon sun shared", "across a single", "street"] },
  IN: { big: ["सूरज", "बाँटो"], lang: "hi", quote: ["noon sun shared", "across a single", "street"] },
  DE: { big: ["TEILE", "DIE", "SONNE"], lang: "de", quote: ["noon sun shared", "across a single", "street"] },
};
const LEDE: Record<string, string> = {
  TR: "Since 1 May 2026 rooftop surplus not used in the same hour earns ₺0. Here it is traded to the neighbours every 15 minutes, signed, settled and stamped with its hour.",
  IN: "P2P pilots work, but nobody trades by hand. Here an AI agent trades for every home every 15 minutes, signed, settled and stamped with its hour.",
  DE: "Energy sharing is legal since June 2026. Here it runs every 15 minutes, signed, settled and stamped with its hour.",
};

function Leader({ k, v, blue }: { k: string; v: string; blue?: boolean }) {
  return <div className="leader"><span className="k">{k}</span><span className="dots" /><span className={`v ${blue ? "blue" : ""}`}>{v}</span></div>;
}

function Section({ n, title, sub }: { n: string; title: string; sub?: string }) {
  return <div className="section-head"><span className="n">{n}</span><h2>{title}</h2>{sub && <span className="it">{sub}</span>}<span className="rule" /></div>;
}

export default function MarketPage() {
  const { data: k } = usePoll<Kpis>("/api/kpis", 2500);
  const { data: series } = usePoll<SeriesPoint[]>("/api/series?limit=192", 2500);
  const { data: s } = usePoll<State>("/api/state", 2000);
  const lastId = s?.last_interval?.id;
  const { data: iv } = usePoll<Interval>(lastId ? `/api/intervals/${lastId}` : null, 2500);
  const { data: alerts } = usePoll<Alert[]>("/api/alerts?limit=5", 3000);
  const { data: w } = usePoll<Weather>("/api/weather", 60000);
  const { data: homes } = usePoll<Home[]>("/api/homes", 3000);
  const { data: certs } = usePoll<Certificate[]>("/api/certificates?limit=500", 6000);

  if (!s?.country) return <div className="empty">loading the market — weather, forecasts, contracts…</div>;

  const li = s.last_interval;
  const ghi = li?.ghi ?? w?.current.ghi ?? 0;
  const soc = k?.battery_soc_pct ?? 30;
  const city = s.site.name.split(" (")[0].split(",")[0];
  const sp = series ?? [];
  const fc = k?.forecast.holdout;
  const ds = s.data_sources;
  const slot = iv ? `${hhmm(iv.start_ts)}–${hhmmPlus(iv.start_ts)}` : "--:--";
  const loc = LOCAL[s.country.code] ?? LOCAL.TR;
  const nCerts = certs?.length ?? 0;

  return (
    <main>
      {/* ================================================= hero: botanical study */}
      <section className="poster">
        <div className="bigtext" lang={loc.lang}>{loc.big.map((b) => <div key={b}>{b}</div>)}</div>

        <div className="art">
          <HydrangeaScene data={{ ghi, tradedWh: li?.volume_wh ?? 0, certificates: nCerts, soc }} />
        </div>

        <div className="quote">
          <div className="u">Like a quiet</div>
          {loc.quote.slice(0, 2).map((q) => <div key={q} className="it">{q}</div>)}
          <div className="it">{city.toLocaleLowerCase(loc.lang)} {loc.quote[2]}</div>
          <div className="tiny muted" style={{ marginTop: 18, lineHeight: 1.6 }}>
            <b>beam</b> sunlight {ghi < 8 ? "— night" : `${Math.round(ghi)} w/m²`}<br />
            <b>stitches</b> {li ? (li.volume_wh / 1000).toFixed(2) : "0.00"} kwh traded {slot}<br />
            <b>stitch cluster</b> {nCerts} hourly certificates<br />
            <b>leaves</b> battery {soc}%
          </div>
        </div>

        <div className="stats" style={{ left: 0, right: "auto", top: 290 }}>
          <Leader k="traded p2p" v={k ? `${k.traded_kwh} kwh` : "—"} />
          <Leader k={`clearing ${slot}`} v={iv?.clearing_price != null ? `${rs(iv.clearing_price)}/kwh` : "—"} blue />
          <Leader k="grid tariff" v={iv ? `${rs(iv.grid_price)}/kwh` : "—"} />
          <Leader k="surplus kept local" v={k ? `${k.local_use_of_surplus_pct}%` : "—"} />
          <Leader k="sellers earned" v={k ? rs(k.prosumer_extra_earnings) : "—"} />
          <Leader k="buyers saved" v={k ? rs(k.consumer_savings) : "—"} />
          <Leader k="hourly clean match" v={k ? `${k.hourly_cfe_pct}%` : "—"} />
        </div>

        <p className="lede" style={{ top: 548 }}>{LEDE[s.country.code] ?? LEDE.TR}</p>

        <div className="titleblock">
          <div className="study">market study no. {s.country.code === "TR" ? "01" : s.country.code === "IN" ? "02" : "03"} <span className="it muted">— {s.period_label.toLowerCase()}</span></div>
          <Sliced text="HourGrid" />
          <Sliced text={city.toLocaleUpperCase(s.country.code === "TR" ? "tr" : "en")} />
        </div>
      </section>

      {/* ================================================= 01 now */}
      <Section n="01" title="Now" sub={`slot ${slot}`} />
      <section className="bento">
        <div className="c4 card glow">
          <CardHead title="live slot" code={iv ? `#${iv.id}` : ""} />
          <div style={{ fontSize: 48, fontWeight: 500, lineHeight: 1, letterSpacing: "-0.04em", color: "var(--blue)" }}>{iv?.clearing_price != null ? rs(iv.clearing_price) : "—"}<span className="small it muted"> /kwh p2p</span></div>
          <table style={{ margin: "18px 0" }}>
            <tbody>
              <tr><td className="muted">grid tariff now</td><td className="num">{iv ? rs(iv.grid_price) : "—"}</td></tr>
              <tr><td>p2p clearing</td><td className="num blue">{iv?.clearing_price != null ? rs(iv.clearing_price) : "—"}</td></tr>
              {iv?.ref_price != null && <tr><td className="muted">wholesale (real)</td><td className="num">{rs(iv.ref_price)}</td></tr>}
              <tr><td className="muted">paid for surplus</td><td className="num">{rs(s.country.feed_in)}</td></tr>
              <tr><td className="muted">regulated band</td><td className="num">{iv ? `${rs(iv.floor)} – ${rs(iv.ceiling)}` : "—"}</td></tr>
            </tbody>
          </table>
          {iv && <Barcode hash={iv.fills_root} label="merkle root of this slot's trades" />}
          <div className="row small" style={{ justifyContent: "space-between", marginTop: 12 }}>
            <span className="muted">commit <Tx hash={iv?.commit_tx} explorer={iv?.explorer} /></span>
            {iv && <StatusBadge status={iv.status} />}
          </div>
        </div>
        <div className="c8 card">
          <CardHead title="prices through the day" code={`${cur()}/kwh · ${s.country.currency}`} />
          {sp.length ? <PriceChart data={sp} /> : <p className="empty">waiting for the first slot…</p>}
          <p className="tiny muted it" style={{ marginTop: 6 }}>{s.country.tariff_source}</p>
        </div>
      </section>

      {/* ================================================= 02 market */}
      <Section n="02" title="Market" sub="what was offered, what cleared" />
      <section className="bento">
        <div className="c7 card">
          <CardHead title="energy flows" code="kwh per 15 min" />
          {sp.length ? <EnergyChart data={sp} /> : <p className="empty">waiting for the first slot…</p>}
        </div>
        <div className="c5 card">
          <CardHead title={`order book ${slot}`} code="uniform price" />
          {iv?.curves && (iv.curves.demand.length > 0 || iv.curves.supply.length > 0)
            ? <OrderBookChart curves={iv.curves} price={iv.clearing_price} />
            : <p className="empty">no orders this slot — nobody has surplus</p>}
        </div>
      </section>

      {/* ================================================= 03 people */}
      <Section n="03" title="People" sub={`${homes ? homes.length - 1 : 24} meters on ${s.site.zone}`} />
      <section className="bento">
        <div className="c8 card">
          <CardHead title="live meters" code="green dots export · blue rings import" />
          {homes ? <NeighbourhoodMap homes={homes} /> : <p className="empty">loading…</p>}
        </div>
        <div className="c4 stack">
          <div className="card">
            <CardHead title="security log" />
            <Alerts alerts={alerts} />
          </div>
          <div className="card">
            <CardHead title="ai forecast" code="error, wh per 15 min" />
            {fc?.generation_mae_wh ? (
              <table>
                <thead><tr><th>model</th><th className="num">solar</th><th className="num">use</th></tr></thead>
                <tbody>
                  <tr><td className="blue">hourgrid ai</td><td className="num blue">{fc.generation_mae_wh.hourgrid_ai}</td><td className="num blue">{fc.load_mae_wh?.hourgrid_ai}</td></tr>
                  <tr><td className="muted">physics only</td><td className="num">{fc.generation_mae_wh.physics_only}</td><td className="num">—</td></tr>
                  <tr><td className="muted">same as yesterday</td><td className="num">{fc.generation_mae_wh.yesterday_same_time}</td><td className="num">{fc.load_mae_wh?.yesterday_same_time}</td></tr>
                </tbody>
              </table>
            ) : <p className="muted it">training…</p>}
          </div>
        </div>
      </section>

      {/* ================================================= 04 ledger */}
      <Section n="04" title="Ledger" sub={k ? `${k.co2_displaced_kg} kg co₂ displaced today` : ""} />
      <section className="bento">
        <div className="c7 card">
          <CardHead title="latest trades" code="each sale mints an hourly certificate" />
          {iv?.fills?.length ? (
            <div className="tablewrap">
              <table>
                <thead><tr><th>#</th><th>seller</th><th>buyer</th><th className="num">wh</th><th className="num">{cur()}/kwh</th><th>certificate</th></tr></thead>
                <tbody>
                  {iv.fills.slice(0, 8).map((f) => (
                    <tr key={f.idx}>
                      <td className="muted">{String(f.idx).padStart(2, "0")}</td>
                      <td><HomeLink id={f.seller} name={f.seller_name} /></td>
                      <td><HomeLink id={f.buyer} name={f.buyer_name} /></td>
                      <td className="num">{f.wh}</td>
                      <td className="num blue">{f.price.toFixed(2)}</td>
                      <td>{f.cert_id ? <Link href={`/verify/${f.cert_id}`}><XMark size={9} /> {f.cert_id.slice(0, 10)}…</Link> : <span className="tiny muted it">battery — no certificate</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="empty">no trades in the latest slot</p>}
        </div>
        <div className="c5 card">
          <CardHead title={`sunlight in ${city.toLocaleLowerCase(loc.lang)} today`} />
          {w ? <WeatherChart data={w.today} /> : <p className="empty">loading…</p>}
          <p className="tiny muted it" style={{ marginTop: 6 }}>{w?.source}</p>
        </div>
      </section>

      {/* ================================================= 05 notes */}
      <Section n="05" title="Notes" sub={s.country.name.toLowerCase()} />
      <section className="bento">
        <div className="c8 card bare">
          <p style={{ fontSize: 20, lineHeight: 1.35, margin: "0 0 24px", fontWeight: 300 }}>{s.country.headline}</p>
          <div className="notes">
            <ul>
              {s.country.regulation.map((r, i) => <li key={i}>{r.text} <a href={r.url} target="_blank" rel="noreferrer" className="tiny it">{r.source} ↗</a></li>)}
              {s.country.notes.map((n, i) => <li key={`n${i}`}>{n}</li>)}
            </ul>
          </div>
        </div>
        <div className="c4 card">
          <CardHead title="where the numbers come from" />
          <div className="sources">
            {(["weather", "market_price", "grid_carbon"] as const).map((key) => (
              <div className="s" key={key}>
                <span className={`dot ${ds[key].status === "live" ? "live" : ds[key].status === "needs-credentials" ? "warn" : ds[key].status === "fallback" ? "off" : ""}`} />
                <span className="tiny muted upper">{key.replace("_", " ")}</span>
                <span>{ds[key].source}</span>
              </div>
            ))}
            <div className="s"><span className="dot" /><span className="tiny muted upper">fees</span><span>{s.country.fee_source}</span></div>
          </div>
        </div>
      </section>

      <footer className="footer">
        <span>hourgrid <span className="it">— market study</span></span>
        <span className="it muted">ieee climatechain 2026</span>
        <span className="r it muted">{s.clock.slice(0, 10)} · {s.clock.slice(11, 16)} local</span>
      </footer>
    </main>
  );
}
