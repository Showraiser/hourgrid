"""Runtime settings, read from environment variables (or backend/.env)."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]  # repo root


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # market / location (set by apply_country; defaults: Türkiye, İstanbul)
    country: str = os.getenv("COUNTRY", "TR").upper()
    site_id: str = os.getenv("SITE", "")
    lat: float = 0.0
    lon: float = 0.0
    site_name: str = ""
    zone: str = ""
    landmark: str = ""
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Istanbul"))

    # neighbourhood
    n_homes: int = int(os.getenv("N_HOMES", "24"))
    prosumer_share: float = float(os.getenv("PROSUMER_SHARE", "0.4"))
    battery_kwh: float = float(os.getenv("BATTERY_KWH", "20"))
    battery_kw: float = float(os.getenv("BATTERY_KW", "5"))
    demo_seed: str = os.getenv("DEMO_SEED", "hourgrid-ieee-climatechain-2026")

    # clock: "demo" = accelerated from 06:00 today, "live" = real wall clock
    clock_mode: str = os.getenv("CLOCK_MODE", "demo")
    seconds_per_interval: float = float(os.getenv("SECONDS_PER_INTERVAL", "4"))
    demo_start_hour: int = int(os.getenv("DEMO_START_HOUR", "6"))
    autostart: bool = _bool("AUTOSTART", True)

    # weather
    weather_provider: str = os.getenv("WEATHER_PROVIDER", "auto")  # auto | openmeteo | nasa | offline
    history_days: int = int(os.getenv("HISTORY_DAYS", "14"))

    # blockchain
    chain_enabled: bool = _bool("CHAIN_ENABLED", False)
    rpc_url: str = os.getenv("RPC_URL", "http://127.0.0.1:8545")
    operator_key: str = os.getenv("OPERATOR_KEY", "")
    deployments_file: str = os.getenv("DEPLOYMENTS_FILE", "")
    explorer_url: str = os.getenv("EXPLORER_URL", "")  # e.g. https://amoy.polygonscan.com
    contracts_out: Path = ROOT / "contracts" / "out"

    # Hugging Face (optional agent assistant)
    hf_token: str = os.getenv("HF_TOKEN", "")
    hf_model: str = os.getenv("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    hf_base_url: str = os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1")

    db_path: Path = Path(os.getenv("DB_PATH", str(Path(__file__).resolve().parents[1] / "hourgrid.db")))
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")


settings = Settings()


def apply_country(code: str | None = None, site_id: str | None = None):
    """Switch the active market profile (currency, tariffs, time zone, site)."""
    from . import countries, tariffs
    p = countries.get(code or settings.country)
    site = p.site(site_id if site_id is not None else settings.site_id)
    settings.country, settings.site_id = p.code, site.id
    settings.lat = float(os.getenv("SITE_LAT", site.lat)) if code is None and os.getenv("SITE_LAT") else site.lat
    settings.lon = float(os.getenv("SITE_LON", site.lon)) if code is None and os.getenv("SITE_LON") else site.lon
    settings.site_name, settings.zone, settings.landmark = site.name, site.zone, site.landmark
    settings.tz = ZoneInfo(p.tz)
    tariffs.set_profile(p)
    return p, site


apply_country()
