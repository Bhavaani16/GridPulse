"""Write /data/signals_cached.csv. Importing this module does not open a socket.

The committed cache is the SPEC 5.1 synthetic series. Live providers are tried
only with --probe or --live, and --live writes /data/signals_live.csv.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from data_tools.models import GridSignal
from data_tools.synthetic import synthetic_rows

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
CACHE_PATH = DATA_DIR / "signals_cached.csv"
LIVE_PATH = DATA_DIR / "signals_live.csv"
TIMEOUT_SECONDS = 10

CSV_COLUMNS = (
    "ts",
    "price_usd_per_mwh",
    "marginal_gco2_per_kwh",
    "curtailment_mw",
    "water_stress_index",
    "source",
)

# Documented in EIA APIv2.1.0: https://api.eia.gov/v2/electricity/rto?api_key=
EIA_RTO_ROUTE = "https://api.eia.gov/v2/electricity/rto"
# Documented base in Electricity Maps v3 docs, header auth-token.
EM_LATEST = "https://api.electricitymaps.com/v3/carbon-intensity/latest"
# Documented in CAISO OASIS interface spec, PRC_LMP example node LAPLMG1_7_B2.
CAISO_LMP = "https://oasis.caiso.com/oasisapi/SingleZip"


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    env_path = path or (REPO_ROOT / ".env")
    found: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            found[key.strip()] = value.strip().strip('"').strip("'")
    for key in (
        "EIA_API_KEY",
        "ELECTRICITYMAPS_TOKEN",
        "WATTTIME_USER",
        "WATTTIME_PASSWORD",
    ):
        if os.environ.get(key):
            found[key] = os.environ[key]
    return found


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "REDACTED")
    return re.sub(r"(api_key|auth-token|token)=([^&\s]+)", r"\1=REDACTED", text, flags=re.I)


def _request(url: str, headers: dict[str, str] | None = None) -> tuple[int | None, bytes]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "gridpulse-data"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read(8000)
    except urllib.error.HTTPError as exc:
        body = exc.read(800) if exc.fp else b""
        return exc.code, body
    except Exception:
        return None, b""


def probe_eia(env: dict[str, str]) -> str:
    key = env.get("EIA_API_KEY", "")
    if not key:
        return "SKIP"
    url = EIA_RTO_ROUTE + "?" + urllib.parse.urlencode({"api_key": key})
    status, body = _request(url)
    if status != 200:
        return "FAIL"
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return "FAIL"
    return "PASS" if isinstance(payload, dict) and "response" in payload else "FAIL"


def probe_electricity_maps(env: dict[str, str]) -> str:
    token = env.get("ELECTRICITYMAPS_TOKEN", "")
    if not token:
        return "SKIP"
    status, body = _request(
        EM_LATEST + "?zone=US-CAL-CISO",
        headers={"auth-token": token, "User-Agent": "gridpulse-data"},
    )
    if status != 200:
        return "FAIL"
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return "FAIL"
    return "PASS" if isinstance(payload, dict) and "carbonIntensity" in payload else "FAIL"


def probe_caiso() -> str:
    query = urllib.parse.urlencode(
        {
            "queryname": "PRC_LMP",
            "startdatetime": "20261016T07:00-0000",
            "enddatetime": "20261017T07:00-0000",
            "version": "1",
            "market_run_id": "DAM",
            "node": "LAPLMG1_7_B2",
            "resultformat": "6",
        }
    )
    status, body = _request(CAISO_LMP + "?" + query)
    if status == 200 and body[:2] == b"PK":
        return "PASS"
    return "FAIL"


def probe_watttime(env: dict[str, str]) -> str:
    if env.get("WATTTIME_USER") and env.get("WATTTIME_PASSWORD"):
        # No WattTime URL is listed in /docs. Do not invent one.
        return "SKIP"
    return "SKIP"


def write_signal_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "ts": row["ts"],
                    "price_usd_per_mwh": f"{float(row['price_usd_per_mwh']):.1f}",
                    "marginal_gco2_per_kwh": f"{float(row['marginal_gco2_per_kwh']):.1f}",
                    "curtailment_mw": f"{float(row['curtailment_mw']):.1f}",
                    "water_stress_index": f"{float(row['water_stress_index']):.4f}",
                    "source": row["source"],
                }
            )


def load_cached_signals(path: Path | None = None) -> list[GridSignal]:
    csv_path = path or CACHE_PATH
    signals: list[GridSignal] = []
    with csv_path.open(newline="") as handle:
        for raw in csv.DictReader(handle):
            signals.append(
                GridSignal(
                    ts=raw["ts"],
                    price_usd_per_mwh=float(raw["price_usd_per_mwh"]),
                    marginal_gco2_per_kwh=float(raw["marginal_gco2_per_kwh"]),
                    curtailment_mw=float(raw["curtailment_mw"]),
                    water_stress_index=float(raw["water_stress_index"]),
                    source=raw["source"],
                )
            )
    return signals


def write_cached_csv(path: Path | None = None) -> Path:
    target = path or CACHE_PATH
    write_signal_csv(target, synthetic_rows())
    return target


def try_live_rows(env: dict[str, str]) -> list[dict[str, object]] | None:
    """Return 48 hourly rows from a provider, or None.

    Does not open a socket. The documented EIA route is a catalog, the
    documented Electricity Maps latest route is one hour, and CAISO's zip
    has no column map in /docs/data_sources.txt. `--probe` is the only path
    that calls those endpoints. `env` is accepted so the signature can grow
    when a 48-hour URL is written into that file.
    """
    del env
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    env = load_dotenv()
    secrets = [env.get("EIA_API_KEY", ""), env.get("ELECTRICITYMAPS_TOKEN", "")]
    if "--probe" in args:
        print(f"EIA {_redact(probe_eia(env), secrets)}")
        print(f"ELECTRICITY_MAPS {_redact(probe_electricity_maps(env), secrets)}")
        print(f"CAISO {probe_caiso()}")
        print(f"WATTTIME {probe_watttime(env)}")
        return 0
    if "--live" in args:
        live_rows = try_live_rows(env)
        if live_rows is None:
            live_rows = synthetic_rows()
            print("live fetch did not return 48 hours; wrote synthetic rows to signals_live.csv")
        write_signal_csv(LIVE_PATH, live_rows)
        print(LIVE_PATH)
        return 0
    write_cached_csv()
    print(CACHE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
