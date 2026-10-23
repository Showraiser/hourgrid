// Typed client for the HourGrid FastAPI backend.
export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {}
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
}

export const get = <T,>(p: string) => req<T>(p);
export const post = <T,>(p: string, body?: unknown) =>
  req<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

// ---------------------------------------------------------------- types
export type Period = "solar" | "peak" | "normal" | "night";

export interface CountryProfile {
  code: string;
  name: string;
  flag: string;
  currency: string;
  symbol: string;
  token_symbol: string;
  tz: string;
  sites: { id: string; name: string; lat: number; lon: number; zone: string; landmark: string }[];
  periods: { kind: string; label: string; start: number; end: number; price: number }[];
  feed_in: number;
  wheeling_fee: number;
  transaction_fee: number;
  grid_ef: number;
  grid_ef_source: string;
  prosumer_kind: string;
  headline: string;
  regulation: { text: string; source: string; url: string }[];
  tariff_source: string;
  fee_source: string;
  market_price_provider: string;
  carbon_provider: string;
  dynamic_retail: boolean;
  notes: string[];
}

export interface DataSource { source: string; status: string; kg_per_kwh?: number }

export interface State {
  ready: boolean;
  status: string;
  running: boolean;
  clock: string;
  clock_mode: string;
  seconds_per_interval: number;
  period: Period;
  period_label: string;
  site: { id: string; name: string; lat: number; lon: number; zone: string; landmark: string; tz: string };
  country: CountryProfile;
  data_sources: Record<"weather" | "market_price" | "grid_carbon", DataSource>;
  weather_source: string;
  chain: {
    enabled: boolean;
    status: string;
    error: string;
    chain_id?: number;
    contracts?: Record<string, string>;
    explorer?: string;
    block?: number;
  };
  last_interval: Interval | null;
  tariffs: Record<string, number | string | number[]>;
}

export interface Kpis {
  intervals: number;
  intervals_settled_onchain: number;
  trades: number;
  traded_kwh: number;
  solar_traded_kwh: number;
  solar_generated_kwh: number;
  surplus_kwh: number;
  local_use_of_surplus_pct: number;
  battery_charged_kwh: number;
  battery_discharged_kwh: number;
  battery_soc_pct: number;
  prosumer_extra_earnings: number;
  consumer_savings: number;
  hourly_cfe_pct: number;
  co2_displaced_kg: number;
  grid_intensity_kg_per_kwh: number;
  delivery_shortfall_pct: number;
  oracle_rejections: number;
  forecast: {
    holdout: {
      generation_mae_wh?: Record<string, number>;
      load_mae_wh?: Record<string, number>;
      train_rows?: number;
    };
    live_mae_wh: { generation: number; load: number };
  };
}

export interface SeriesPoint {
  id: number;
  ts: string;
  period: Period;
  price: number | null;
  ref_price: number | null;
  period_label: string;
  grid_price: number;
  feed_in: number;
  volume_wh: number;
  scheduled_wh: number;
  fills: number;
  solar_wh: number;
  load_wh: number;
  export_wh: number;
  battery_soc: number;
  ghi: number;
  status: string;
}

export interface Order {
  agent: string;
  name?: string;
  side: "buy" | "sell";
  wh: number;
  price: number;
  reason: string;
  ts?: string;
}

export interface Fill {
  interval_id: number;
  idx: number;
  seller: string;
  buyer: string;
  seller_name?: string;
  buyer_name?: string;
  wh: number;
  scheduled_wh: number;
  price: number;
  cert_id: string | null;
  status: string;
  ts?: string;
}

export interface Interval {
  id: number;
  start_ts: string;
  period: Period;
  clearing_price: number | null;
  volume_wh: number;
  scheduled_wh: number;
  n_bids: number;
  n_asks: number;
  n_fills: number;
  orderbook_hash: string;
  fills_root: string;
  ghi: number;
  temp: number;
  grid_price: number;
  floor: number;
  ceiling: number;
  ref_price: number | null;
  period_label: string;
  battery_soc: number;
  status: string;
  commit_tx: string | null;
  settle_tx: string | null;
  error: string | null;
  curves?: { demand: { wh: number; price: number }[]; supply: { wh: number; price: number }[] };
  totals?: Record<string, number>;
  orders?: Order[];
  fills?: Fill[];
  explorer?: string | null;
}

export interface Home {
  home_id: string;
  name: string;
  role: "prosumer" | "consumer" | "battery";
  kind: "home" | "business";
  meter_id: string;
  meter_key: string;
  pv_kwp: number;
  occupants: number;
  has_ac: boolean;
  has_ev: boolean;
  wallet: string;
  signer: string;
  prefs: Record<string, unknown>;
  balance: number;
  earned: number;
  spent: number;
  sold_wh: number;
  bought_wh: number;
  points: number;
  extra_vs_feed_in: number;
  saved_vs_grid: number;
  soc_pct?: number;
  capacity_kwh?: number;
  last_reading?: { gen_wh: number; load_wh: number; export_wh: number; import_wh: number; accepted: number } | null;
}

export interface HomeDetail extends Home {
  series: { ts: string; gen_wh: number; load_wh: number; gen_fc: number; load_fc: number; accepted: number }[];
  orders: Order[];
  trades: Fill[];
  certificates: Certificate[];
  agent_log: { ts: string; instruction: string; explanation: string; engine: string }[];
}

export interface Certificate {
  cert_id: string;
  meter_id: string;
  home_id: string;
  producer?: string;
  hour_start: string;
  zone: string;
  minted_wh: number;
  retired_wh: number;
  held_wh?: number;
  settled?: number | boolean;
  holders?: { home_id: string; wh: number }[];
}

export interface Verification {
  certificate: Certificate;
  producer: { home_id: string; name: string; meter_id: string; meter_key: string; signer: string; pv_kwp: number; zone: string };
  trades: (Fill & {
    ts: string;
    commit_tx: string | null;
    settle_tx: string | null;
    fills_root: string;
    orderbook_hash: string;
    interval_status: string;
    export_wh: number;
    max_plausible_wh: number;
    signature: string;
    buyer_name: string;
  })[];
  holders: { home_id: string; name: string; wh: number }[];
  retirements: { id: number; home_id: string; name: string; wh: number; beneficiary: string; ts: string; tx: string | null; status: string }[];
  onchain: { minted_wh?: number; retired_wh?: number; contract?: string; error?: string } | null;
  explorer: string | null;
}

export interface Alert {
  id: number;
  ts: string;
  sim_ts: string | null;
  level: "info" | "warn" | "critical";
  kind: string;
  message: string;
  home_id: string | null;
}

export interface Weather {
  source: string;
  current: { temp_air: number; ghi: number; cloud_cover: number; is_day: number; time: string };
  site: { name: string };
  today: { ts: string; ghi: number; ghi_forecast: number; temp: number; cloud_cover: number }[];
}

// ---------------------------------------------------------------- formatting
// The active market's currency symbol, set by the header whenever /api/state loads.
let SYMBOL = "₺";
export const setCurrency = (sym: string) => { SYMBOL = sym; };
export const cur = () => SYMBOL;
export const rs = (v: number | null | undefined, d = 2) => (v == null ? "—" : `${SYMBOL}${v.toFixed(d)}`);
export const money = rs;
export const kwh = (wh: number) => `${(wh / 1000).toFixed(2)} kWh`;
export const hhmm = (iso: string) => iso.slice(11, 16);
export const short = (h: string | null | undefined, n = 6) => (h ? `${h.slice(0, n + 2)}…${h.slice(-4)}` : "-");
export const txUrl = (explorer: string | null | undefined, tx: string) => (explorer ? `${explorer}/tx/${tx}` : null);
export const hhmmPlus = (iso: string, mins = 15) => {
  const total = Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16)) + mins;
  return `${String(Math.floor(total / 60) % 24).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
};
