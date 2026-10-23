"""Country market profiles.

Each profile carries what changes between electricity markets: currency, time zone,
retail tariff periods, what a prosumer is paid for surplus, network charges for local
trading, grid emission factor, the regulation that makes P2P relevant, and which real
data feeds exist. Values marked "assumption" have no official P2P equivalent yet and
should be stated as such in a pitch.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Period:
    kind: str  # solar | peak | normal | night  (agents and the battery key off this)
    label: str
    start: int  # local hour, inclusive
    end: int  # local hour, exclusive
    price: float  # retail price, currency/kWh


@dataclass
class Site:
    id: str
    name: str
    lat: float
    lon: float
    zone: str
    landmark: str  # drawing hint for the frontend scene


@dataclass
class Profile:
    code: str
    name: str
    flag: str
    currency: str
    symbol: str
    token_name: str
    token_symbol: str
    tz: str
    sites: list[Site]
    periods: list[Period]
    feed_in: float  # currency/kWh paid for exported surplus
    wheeling_fee: float  # currency/kWh, split 50/50
    transaction_fee: float  # currency/kWh, split 50/50
    grid_ef: float  # kg CO2 per kWh (static fallback)
    grid_ef_source: str
    deposit: float  # starting wallet balance per participant
    prosumer_kind: str  # residential | commercial
    names: list[str]
    business_names: list[str]
    headline: str
    regulation: list[dict]  # {text, source, url}
    tariff_source: str
    fee_source: str
    market_price_provider: str  # none | epias | energy-charts
    carbon_provider: str  # static | epias | energy-charts
    dynamic_retail_adder: float | None = None  # if set: retail = day-ahead price + adder
    notes: list[str] = field(default_factory=list)

    def site(self, site_id: str | None) -> Site:
        for s in self.sites:
            if s.id == site_id:
                return s
        return self.sites[0]

    def public(self) -> dict:
        return {
            "code": self.code, "name": self.name, "flag": self.flag, "currency": self.currency,
            "symbol": self.symbol, "token_symbol": self.token_symbol, "tz": self.tz,
            "sites": [s.__dict__ for s in self.sites],
            "periods": [p.__dict__ for p in self.periods],
            "feed_in": self.feed_in, "wheeling_fee": self.wheeling_fee, "transaction_fee": self.transaction_fee,
            "grid_ef": self.grid_ef, "grid_ef_source": self.grid_ef_source,
            "prosumer_kind": self.prosumer_kind, "headline": self.headline, "regulation": self.regulation,
            "tariff_source": self.tariff_source, "fee_source": self.fee_source,
            "market_price_provider": self.market_price_provider, "carbon_provider": self.carbon_provider,
            "dynamic_retail": self.dynamic_retail_adder is not None, "notes": self.notes,
        }


INDIA = Profile(
    code="IN", name="India", flag="🇮🇳", currency="INR", symbol="₹",
    token_name="HourGrid Test Rupee", token_symbol="tINR", tz="Asia/Kolkata",
    sites=[
        Site("amaravati", "Amaravati, Andhra Pradesh", 16.5062, 80.5150, "AMR-FEEDER-07", "stupa"),
        Site("delhi", "New Delhi (TPDDL/BRPL pilot area)", 28.6139, 77.2090, "DEL-FEEDER-12", "gate"),
    ],
    periods=[
        Period("normal", "Normal", 0, 9, 7.00),
        Period("solar", "Solar hours", 9, 17, 5.60),
        Period("normal", "Normal", 17, 18, 7.00),
        Period("peak", "Evening peak", 18, 22, 7.70),
        Period("normal", "Normal", 22, 24, 7.00),
    ],
    feed_in=2.50, wheeling_fee=1.01, transaction_fee=0.42,
    grid_ef=0.71, grid_ef_source="CEA CO2 Baseline Database (India grid, ~0.71 kg/kWh)",
    deposit=500, prosumer_kind="residential",
    names=["Lakshmi", "Ravi", "Sravani", "Venkat", "Anjali", "Kiran", "Padma", "Suresh", "Divya", "Naresh",
           "Bhavani", "Prasad", "Keerthi", "Mahesh", "Swathi", "Ramesh", "Harika", "Gopi", "Sirisha", "Arjun",
           "Madhavi", "Teja", "Pooja", "Srinivas"],
    business_names=[],
    headline="P2P pilots are live in Delhi and Uttar Pradesh, but volumes are tiny: people don't trade by hand.",
    regulation=[
        {"text": "DERC and UPERC approved P2P solar trading pilots under the India Energy Stack (Feb 2026), extended to 31 Mar 2027.",
         "source": "Renewable Watch", "url": "https://renewablewatch.in/2026/03/02/evolving-market-design-derc-and-uperc-approve-p2p-renewable-energy-trading/"},
        {"text": "UPERC-approved P2P charges: wheeling Rs 1.01/kWh + transaction Rs 0.42/kWh, shared equally.",
         "source": "Renewable Watch", "url": "https://renewablewatch.in/2026/02/23/uperc-approves-pilot-for-interstate-renewable-p2p-trading/"},
        {"text": "ToD rules: solar-hour tariff at least 20% below normal, peak at least 1.10x normal.",
         "source": "PIB", "url": "https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=1945236"},
    ],
    tariff_source="Placeholder AP-style ToD values following the 2023 ToD rules; set to the official DISCOM schedule.",
    fee_source="UPERC-approved P2P pilot charges (2026).",
    market_price_provider="none", carbon_provider="static",
)

TURKIYE = Profile(
    code="TR", name="Türkiye", flag="🇹🇷", currency="TRY", symbol="₺",
    token_name="HourGrid Test Lira", token_symbol="tTRY", tz="Europe/Istanbul",
    sites=[
        Site("istanbul", "İstanbul", 41.0082, 28.9784, "IST-OSB-03", "mosque"),
        Site("konya", "Konya (Türkiye's solar capital)", 37.8746, 32.4932, "KON-OSB-01", "konya"),
    ],
    periods=[
        Period("night", "T3 Gece (night)", 0, 6, 2.94),
        Period("solar", "T1 Gündüz (day)", 6, 17, 4.38),
        Period("peak", "T2 Puant (peak)", 17, 22, 6.17),
        Period("night", "T3 Gece (night)", 22, 24, 2.94),
    ],
    feed_in=0.0, wheeling_fee=0.60, transaction_fee=0.20,
    grid_ef=0.6345, grid_ef_source="TUESEF combined margin for solar/wind (Ministry of Energy, 0.6345 tCO2/MWh, 2021)",
    deposit=500, prosumer_kind="commercial",
    names=["Ayşe", "Mehmet", "Elif", "Mustafa", "Zeynep", "Ahmet", "Fatma", "Emre", "Merve", "Can",
           "Selin", "Burak", "Esra", "Murat", "Deniz", "Kemal", "Ebru", "Okan", "Gizem", "Serkan",
           "Nur", "Tolga", "Derya", "Baran"],
    business_names=["Yıldız Tekstil", "Demir Makina", "Anadolu Gıda", "Kaya Mobilya", "Ege Ambalaj",
                    "Toros Metal", "Mavi Plastik", "Güneş Matbaa", "Kardeşler Oto", "Sema Fırın"],
    headline=("Since 1 May 2026, commercial rooftop surplus not used in the same hour earns ₺0: "
              "it is donated to YEKDEM. Selling it to the neighbours next door is the only way it earns money."),
    regulation=[
        {"text": "Unlicensed generation moved from monthly to hourly netting on 1 May 2026 (Resmî Gazete 33212, 2 Apr 2026).",
         "source": "Paksoy", "url": "https://paksoy.av.tr/2026/04/lisanssiz-elektrik-uretiminde-saatlik-mahsuplasma-donemine-gecildi/"},
        {"text": "Surplus left after hourly netting is not paid; it counts as a free contribution to YEKDEM. Residential subscribers stay on monthly netting.",
         "source": "Anadolu Ajansı", "url": "https://www.aa.com.tr/tr/enerjiterminali/genel/lisanssiz-elektrik-uretiminde-saatlik-mahsuplasma-donemi-basladi/56064"},
        {"text": "Three-time residential tariff (Q2 2026, excl. VAT): T1 day 06-17 4.38, T2 peak 17-22 6.17, T3 night 22-06 2.94 TL/kWh.",
         "source": "akillitarife.com (EPDK tariff, Apr 2026)", "url": "https://akillitarife.com/enerji/rehber/tarife/elektrik/uc-zamanli-fiyat"},
        {"text": "Real hourly day-ahead price (PTF) and generation mix from the EPİAŞ Transparency Platform.",
         "source": "EPİAŞ", "url": "https://seffaflik.epias.com.tr/home"},
    ],
    tariff_source="EPDK three-time residential tariff, Q2 2026, excl. VAT (check for the current quarter).",
    fee_source="Assumption: Türkiye has no P2P network tariff yet; 0.60 TL/kWh wheeling + 0.20 TL/kWh platform fee.",
    market_price_provider="epias", carbon_provider="epias",
    notes=["Prosumers are commercial rooftops (workshops, shops) in an organised industrial zone; buyers are nearby homes and businesses."],
)

GERMANY = Profile(
    code="DE", name="Germany", flag="🇩🇪", currency="EUR", symbol="€",
    token_name="HourGrid Test Euro", token_symbol="tEUR", tz="Europe/Berlin",
    sites=[
        Site("freiburg", "Freiburg im Breisgau", 47.9990, 7.8421, "FR-VIERTEL-2", "spire"),
        Site("berlin", "Berlin", 52.5200, 13.4050, "BER-KIEZ-5", "tower"),
    ],
    periods=[
        Period("normal", "Night", 0, 10, 0.37),
        Period("solar", "Midday", 10, 16, 0.37),
        Period("normal", "Afternoon", 16, 17, 0.37),
        Period("peak", "Evening", 17, 21, 0.37),
        Period("normal", "Night", 21, 24, 0.37),
    ],
    feed_in=0.077, wheeling_fee=0.11, transaction_fee=0.01,
    grid_ef=0.38, grid_ef_source="Approx. German grid average; live value from Energy-Charts when reachable",
    deposit=60, prosumer_kind="residential",
    names=["Anna", "Lukas", "Mia", "Felix", "Lena", "Jonas", "Sophie", "Paul", "Emma", "Leon",
           "Hannah", "Finn", "Laura", "Noah", "Julia", "Ben", "Clara", "Tim", "Marie", "Max",
           "Lea", "Jan", "Nina", "Tom"],
    business_names=[],
    headline="Energy sharing (§42c EnWG) became legal on 1 June 2026, but needs 15-minute metering and full network charges.",
    regulation=[
        {"text": "Energy sharing under §42c EnWG from 1 June 2026: households, SMEs and cooperatives share solar within one balancing area; neighbouring areas from 2028.",
         "source": "solarzubau.de", "url": "https://solarzubau.de/news/energy-sharing-startet-1-juni-2026-paragraph-42c/"},
        {"text": "Requires smart meters with 15-minute values; network charges apply in full.",
         "source": "solarzubau.de", "url": "https://solarzubau.de/news/energy-sharing-startet-1-juni-2026-paragraph-42c/"},
        {"text": "EEG feed-in for new ≤10 kWp partial-feed rooftop PV: 7.70 ct/kWh (Aug 2026–Jan 2027); average household price 37.0 ct/kWh (BDEW 2026).",
         "source": "voltaplan.de", "url": "https://voltaplan.de/blog/einspeiseverguetung-2026-tabelle"},
        {"text": "Real day-ahead prices and grid CO2 intensity from Fraunhofer ISE Energy-Charts (no key).",
         "source": "Energy-Charts", "url": "https://api.energy-charts.info/"},
    ],
    tariff_source="Flat 37.0 ct/kWh (BDEW 2026 average); with live data, a dynamic tariff = day-ahead price + 28 ct.",
    fee_source="Assumption: ~11 ct/kWh network charges (apply in full under §42c) + 1 ct platform fee.",
    market_price_provider="energy-charts", carbon_provider="energy-charts",
    dynamic_retail_adder=0.28,
)

PROFILES = {p.code: p for p in (TURKIYE, INDIA, GERMANY)}
DEFAULT = "TR"


def get(code: str | None) -> Profile:
    return PROFILES.get((code or DEFAULT).upper(), PROFILES[DEFAULT])
