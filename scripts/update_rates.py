#!/usr/bin/env python3
"""Fetch Naver exchange rates and write a snapshot for GitHub Pages.

Writes: docs/data/rates.json
Data source: https://finance.naver.com/marketindex/exchangeList.naver

Notes:
- Naver page provides columns: mid-market, cash buy/sell, remit send/receive.
- JPY/VND are shown per 100 units; we normalize to 1 unit.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


NAVER_EXCHANGE_LIST_URL = "https://finance.naver.com/marketindex/exchangeList.naver"

# Keep everything ASCII in the snapshot to avoid mojibake across environments.
CURRENCY_META: dict[str, dict[str, object]] = {
    "KRW": {"label": "Korean Won (KRW)", "market_code": None, "source_unit": 1},
    "USD": {"label": "US Dollar (USD)", "market_code": "FX_USDKRW", "source_unit": 1},
    "CNY": {"label": "Chinese Yuan (CNY)", "market_code": "FX_CNYKRW", "source_unit": 1},
    "PHP": {"label": "Philippine Peso (PHP)", "market_code": "FX_PHPKRW", "source_unit": 1},
    "TWD": {"label": "Taiwan Dollar (TWD)", "market_code": "FX_TWDKRW", "source_unit": 1},
    "JPY": {"label": "Japanese Yen (JPY)", "market_code": "FX_JPYKRW", "source_unit": 100},
    "VND": {"label": "Vietnamese Dong (VND)", "market_code": "FX_VNDKRW", "source_unit": 100},
    "THB": {"label": "Thai Baht (THB)", "market_code": "FX_THBKRW", "source_unit": 1},
    "EUR": {"label": "Euro (EUR)", "market_code": "FX_EURKRW", "source_unit": 1},
    "AUD": {"label": "Australian Dollar (AUD)", "market_code": "FX_AUDKRW", "source_unit": 1},
}


@dataclass(frozen=True, slots=True)
class Snapshot:
    fetched_at: str
    rates_by_type: dict[str, dict[str, float]]


def _iter_rows(html: str) -> list[str]:
    return [m.group(0) for m in re.finditer(r"<tr>\s*.*?</tr>", html, flags=re.DOTALL)]


def _find_row(rows: list[str], market_code: str) -> str:
    for row in rows:
        if f"marketindexCd={market_code}" in row and 'class="tit"' in row:
            return row
    raise ValueError(f"Row not found: {market_code}")


def _parse_row_numbers(row_html: str) -> list[float]:
    tds = re.findall(r"<td[^>]*>\s*([^<]+?)\s*</td>", row_html, flags=re.DOTALL)
    numbers: list[float] = []
    for raw in tds:
        cleaned = raw.strip().replace(",", "")
        if cleaned == "" or cleaned == "-":
            continue
        try:
            numbers.append(float(cleaned))
        except ValueError:
            continue
    return numbers


def fetch_snapshot() -> Snapshot:
    req = Request(NAVER_EXCHANGE_LIST_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=20) as response:
        html = response.read().decode("euc-kr", errors="ignore")

    rows = _iter_rows(html)
    rates_by_type: dict[str, dict[str, float]] = {
        "sale": {"KRW": 1.0},
        "buy": {"KRW": 1.0},
        "sell": {"KRW": 1.0},
        "send": {"KRW": 1.0},
        "receive": {"KRW": 1.0},
    }

    for code, meta in CURRENCY_META.items():
        market_code = meta["market_code"]
        unit = float(meta["source_unit"])
        if market_code is None:
            continue

        row = _find_row(rows, str(market_code))
        cols = _parse_row_numbers(row)
        if len(cols) < 5:
            raise RuntimeError(f"Not enough columns for {code}: {cols}")

        sale, buy, sell, send, receive = cols[0], cols[1], cols[2], cols[3], cols[4]
        rates_by_type["sale"][code] = sale / unit
        rates_by_type["buy"][code] = buy / unit
        rates_by_type["sell"][code] = sell / unit
        rates_by_type["send"][code] = send / unit
        rates_by_type["receive"][code] = receive / unit

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return Snapshot(fetched_at=fetched_at, rates_by_type=rates_by_type)


def main() -> None:
    snap = fetch_snapshot()
    build_sha = (os.getenv("GITHUB_SHA") or "")[:7]

    out = {
        "fetched_at": snap.fetched_at,
        "source": NAVER_EXCHANGE_LIST_URL,
        "build_sha": build_sha,
        "rates_by_type": snap.rates_by_type,
        "currencies": [
            {"code": code, "label": meta["label"], "source_unit": meta["source_unit"]}
            for code, meta in CURRENCY_META.items()
        ],
    }

    out_path = Path(__file__).resolve().parents[1] / "docs" / "data" / "rates.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
