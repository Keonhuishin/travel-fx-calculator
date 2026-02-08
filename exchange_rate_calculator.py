#!/usr/bin/env python3

"""네이버 환율을 기반으로 다중 통화를 변환하는 Flask 웹 앱.

핵심 포인트:
- 네이버 금융 환율표는 "매매기준율/현찰(사실 때/파실 때)/송금(보내실 때/받으실 때)"를 각각 제공합니다.
- 통화 A -> 통화 B 변환은 같은 '기준 컬럼'을 사용해 원화(KRW) 기준으로 교차환산합니다.
  이는 일반적인 크로스레이트 계산 방식이며, 실제 은행 거래 금액은 스프레드/수수료로 달라질 수 있습니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
import json
from datetime import date, datetime, timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Flask, render_template_string

app = Flask(__name__)

NAVER_EXCHANGE_LIST_URL = "https://finance.naver.com/marketindex/exchangeList.naver"
EXCHANGERATE_TIMESERIES_URL = "https://api.exchangerate.host/timeseries"

# 간단 캐시(과도한 외부 호출 방지). 프로세스 재시작 시 초기화됩니다.
_HIST_CACHE: dict[str, tuple[datetime, list[tuple[str, float]]]] = {}

# `source_unit`:
# - JPY/VND는 네이버에서 100단위 기준으로 제공되므로 1단위로 환산하기 위해 사용합니다.
# - 나머지는 1단위 기준 환율입니다.
CURRENCY_META = {
    "KRW": {"label": "대한민국 원화 (KRW)", "flag": "🇰🇷", "market_code": None, "source_unit": 1},
    "USD": {"label": "미국 달러 (USD)", "flag": "🇺🇸", "market_code": "FX_USDKRW", "source_unit": 1},
    "PHP": {"label": "필리핀 페소 (PHP)", "flag": "🇵🇭", "market_code": "FX_PHPKRW", "source_unit": 1},
    "TWD": {"label": "대만 달러 (TWD)", "flag": "🇹🇼", "market_code": "FX_TWDKRW", "source_unit": 1},
    "JPY": {"label": "일본 엔화 (JPY)", "flag": "🇯🇵", "market_code": "FX_JPYKRW", "source_unit": 100},
    "VND": {"label": "베트남 동 (VND)", "flag": "🇻🇳", "market_code": "FX_VNDKRW", "source_unit": 100},
    "THB": {"label": "태국 바트 (THB)", "flag": "🇹🇭", "market_code": "FX_THBKRW", "source_unit": 1},
    "EUR": {"label": "유로 (EUR)", "flag": "🇪🇺", "market_code": "FX_EURKRW", "source_unit": 1},
    "AUD": {"label": "호주 달러 (AUD)", "flag": "🇦🇺", "market_code": "FX_AUDKRW", "source_unit": 1},
}

HTML_TEMPLATE = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="format-detection" content="telephone=no" />
  <title>환율 계산기</title>
  <style>
    :root {
      --bg1: #f8fbff;
      --bg2: #eef5ff;
      --card: #ffffff;
      --line: #dbe7ff;
      --text: #15223b;
      --muted: #4e628b;
      --accent: #2057d8;
      --error-bg: #fff2f2;
      --error-line: #ffb3b3;
      --error-text: #8a1f1f;
    }
    * { box-sizing: border-box; }
    html { -webkit-text-size-adjust: 100%; }
    body {
      margin: 0;
      font-family: 'Noto Sans KR', 'Apple SD Gothic Neo', 'Segoe UI', 'Apple Color Emoji', 'Segoe UI Emoji', sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 90% 10%, #dbe8ff 0%, transparent 42%),
        linear-gradient(160deg, var(--bg1), var(--bg2));
      min-height: 100vh;
      padding: calc(20px + env(safe-area-inset-top)) calc(12px + env(safe-area-inset-right)) calc(16px + env(safe-area-inset-bottom)) calc(12px + env(safe-area-inset-left));
    }
    .wrap {
      max-width: 760px;
      margin: 0 auto;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 24px 20px;
      box-shadow: 0 10px 30px rgba(18, 45, 102, 0.08);
    }
    h1 { margin: 0; font-size: 28px; letter-spacing: -0.02em; }
    .subtitle { margin: 8px 0 18px; color: var(--muted); }
    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }
    .toolbar button {
      border: 1px solid #c9dafd;
      border-radius: 10px;
      background: #fff;
      color: var(--text);
      font-weight: 700;
      padding: 8px 12px;
      min-height: 44px;
      cursor: pointer;
      touch-action: manipulation;
    }
    .toolbar button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .toolbar select {
      border: 1px solid #c9dafd;
      border-radius: 10px;
      background: #fff;
      color: var(--text);
      font-weight: 700;
      padding: 8px 12px;
      min-height: 44px;
      font-size: 14px;
    }
    .toolbar .count {
      font-size: 13px;
      color: var(--muted);
      font-weight: 700;
    }
    .grid {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 18px;
    }
    .field {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: #fbfdff;
      display: grid;
      grid-template-columns: minmax(190px, 260px) 1fr;
      gap: 10px;
      align-items: end;
    }
    .field.hidden { display: none; }
    .field label {
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 8px;
      font-weight: 700;
    }
    .currency-label {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .flag-chip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      border-radius: 999px;
      background: #edf3ff;
      font-size: 13px;
      line-height: 1;
      border: 1px solid #d6e3ff;
    }
    .field input {
      width: 100%;
      border: 1px solid #c9dafd;
      border-radius: 10px;
      padding: 10px 12px;
      min-height: 46px;
      font-size: 16px;
      font-weight: 700;
      color: var(--text);
      background: #fff;
    }
    .field select {
      width: 100%;
      border: 1px solid #c9dafd;
      border-radius: 10px;
      padding: 10px 12px;
      min-height: 46px;
      font-size: 16px;
      font-weight: 700;
      color: var(--text);
      background: #fff;
      -webkit-appearance: none;
      appearance: none;
    }
    .field select:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(32, 87, 216, 0.12);
    }
    .field input:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(32, 87, 216, 0.12);
    }
    .meta {
      margin-top: 16px;
      border: 1px dashed #c7d8ff;
      border-radius: 12px;
      background: #f7faff;
      padding: 12px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .history {
      margin-top: 16px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #ffffff;
      padding: 12px;
    }
    .history h2 {
      margin: 0 0 8px;
      font-size: 16px;
      letter-spacing: -0.01em;
    }
    .history .meme {
      font-weight: 800;
      color: #142a57;
      margin: 6px 0 10px;
    }
    .history details {
      margin-top: 8px;
    }
    .history table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    .history th, .history td {
      border-top: 1px solid #eef3ff;
      padding: 8px 6px;
      text-align: right;
      white-space: nowrap;
    }
    .history th:first-child, .history td:first-child { text-align: left; }
    .error {
      margin-top: 14px;
      border: 1px solid var(--error-line);
      border-radius: 12px;
      background: var(--error-bg);
      color: var(--error-text);
      padding: 11px 12px;
      font-size: 14px;
    }
    @media (max-width: 760px) {
      .wrap {
        border-radius: 14px;
        padding: 16px 14px;
      }
      h1 { font-size: 24px; }
      .field { grid-template-columns: 1fr; }
      .subtitle { margin-bottom: 14px; font-size: 14px; }
      .toolbar { margin-bottom: 2px; }
      .toolbar .count { width: 100%; }
    }
  </style>
</head>
<body>
  <main class="wrap">
    <h1>실시간 환율 계산기</h1>
    <p class="subtitle">입력 칸은 최대 4개까지 추가할 수 있고, 한 칸의 값을 바꾸면 나머지 칸이 실시간으로 계산됩니다.</p>

    <section class="toolbar">
      <button type="button" id="add_field">+ 칸 추가</button>
      <button type="button" id="remove_field">- 칸 제거</button>
      <select id="rate_type">
        <option value="sale" selected>매매기준율</option>
        <option value="buy">현찰 사실 때</option>
        <option value="sell">현찰 파실 때</option>
        <option value="send">송금 보내실 때</option>
        <option value="receive">송금 받으실 때</option>
      </select>
      <span class="count" id="field_count_text"></span>
    </section>

    <section class="grid">
      {% for idx in range(1, 5) %}
        <div class="field field-row" data-index="{{ idx - 1 }}">
          <div>
            <label for="currency_{{ idx }}">기준 통화 {{ idx }}</label>
            <select id="currency_{{ idx }}" class="currency-select">
              {% for item in currencies %}
                <option value="{{ item.code }}" {% if item.code == default_codes[idx - 1] %}selected{% endif %}>{{ item.flag }} {{ item.label }}</option>
              {% endfor %}
            </select>
          </div>
          <div>
            <label for="amount_{{ idx }}">금액</label>
            <input id="amount_{{ idx }}" class="amount-input" type="text" inputmode="decimal" value="0" />
          </div>
        </div>
      {% endfor %}
    </section>

    <section class="meta">
      <div>환율 기준 시각: {{ rate_time_text }}</div>
      <div>
        적용 환율(선택 기준, KRW 기준):
        {% for item in currencies if item.code != "KRW" %}
          <span>{{ item.flag }} 1 {{ item.code }} = {{ "{:,.4f}".format(rates_by_type["sale"][item.code]) }} KRW (매매기준율){% if not loop.last %}, {% endif %}</span>
        {% endfor %}
      </div>
      <div>환율 종류: 네이버 금융의 <strong>매매기준율/현찰/송금</strong> 중 하나를 선택합니다. 변환은 선택된 기준을 동일하게 적용해 교차환산합니다.</div>
      <div>참고: JPY, VND는 네이버의 100단위 기준 값을 1단위 기준으로 환산해 적용합니다.</div>
    </section>

    <section class="history">
      <h2>최근 6개월 USD/KRW (일자별, 참고용)</h2>
      <div class="meme">{{ hist_meme }}</div>
      <div class="meta">
        데이터 소스: exchangerate.host (시장환율 계열, 은행 거래 환율과 다를 수 있음)<br/>
        기간: {{ hist_start }} ~ {{ hist_end }} ({{ hist_count }}일)
      </div>
      <details>
        <summary>일자별 보기</summary>
        <table>
          <thead>
            <tr><th>일자</th><th>USD/KRW</th></tr>
          </thead>
          <tbody>
            {% for d, v in hist_series %}
              <tr><td>{{ d }}</td><td>{{ "{:,.4f}".format(v) }}</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </details>
    </section>

    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}
  </main>

  <script>
    // 서버에서 내려준 KRW 기준 환율표(기준 타입별).
    // 예: ratesByType["sale"]["USD"] = 1 USD 당 KRW (매매기준율)
    const ratesByType = {{ rates_by_type | tojson }};
    const rowElements = Array.from(document.querySelectorAll(".field-row"));
    const fields = rowElements.map((row, index) => ({
      row,
      select: document.getElementById(`currency_${index + 1}`),
      input: document.getElementById(`amount_${index + 1}`),
      titleLabel: row.querySelector(`label[for="currency_${index + 1}"]`)
    }));
    const addFieldBtn = document.getElementById("add_field");
    const removeFieldBtn = document.getElementById("remove_field");
    const rateTypeSelect = document.getElementById("rate_type");
    const fieldCountText = document.getElementById("field_count_text");
    const MIN_FIELDS = 1;
    const MAX_FIELDS = 4;
    let activeCount = 3;

    function currentRates() {
      const t = rateTypeSelect.value;
      return ratesByType[t] || ratesByType["sale"];
    }

    function canConvertNow() {
      const r = currentRates();
      return Object.values(r).every((v) => Number.isFinite(v) && v > 0);
    }
    // 입력 이벤트가 연쇄적으로 재호출되는 것을 방지하는 락
    let isSyncing = false;

    function asNumber(value) {
      // 사용자가 넣은 천단위 콤마를 제거하고 숫자로 변환
      const cleaned = String(value).replace(/,/g, "").trim();
      const n = Number.parseFloat(cleaned);
      return Number.isFinite(n) && n >= 0 ? n : 0;
    }

    function toInputValue(value) {
      if (!Number.isFinite(value) || value < 0) {
        return "0";
      }

      // 소수점 4자리까지만 보여주고 불필요한 0은 제거
      const normalized = value.toFixed(4).replace(/\\.?0+$/, "");
      const parts = normalized.split(".");
      parts[0] = parts[0].replace(/\\B(?=(\\d{3})+(?!\\d))/g, ",");
      return parts.join(".");
    }

    function convertAmount(amount, fromCode, toCode) {
      if (fromCode === toCode) {
        return amount;
      }
      // from -> KRW -> to 방식으로 계산 (선택한 기준 타입을 동일하게 적용)
      const r = currentRates();
      const inKrw = amount * r[fromCode];
      return inKrw / r[toCode];
    }

    function updateFieldLabels() {
      fields.forEach((field, index) => {
        const optionText = field.select.options[field.select.selectedIndex]?.text || "";
        const flag = optionText.trim().split(" ")[0] || "";
        field.titleLabel.innerHTML = `기준 통화 ${index + 1} <span class="flag-chip">${flag}</span>`;
      });
    }

    function updateFrom(index) {
      if (isSyncing) {
        return;
      }

      isSyncing = true;
      // 현재 화면에 보이는 칸(최대 4)만 계산 대상
      const activeFields = fields.slice(0, activeCount);
      const source = activeFields[index];
      if (!source) {
        isSyncing = false;
        return;
      }
      const sourceCode = source.select.value;
      const sourceAmount = asNumber(source.input.value);
      source.input.value = toInputValue(sourceAmount);

      activeFields.forEach((field, i) => {
        if (i === index) {
          return;
        }
        const targetCode = field.select.value;
        const converted = convertAmount(sourceAmount, sourceCode, targetCode);
        field.input.value = toInputValue(converted);
      });
      isSyncing = false;
    }

    function refreshRows() {
      fields.forEach((field, index) => {
        field.row.classList.toggle("hidden", index >= activeCount);
      });
      fieldCountText.textContent = `표시 중: ${activeCount} / ${MAX_FIELDS}`;
      addFieldBtn.disabled = activeCount >= MAX_FIELDS;
      removeFieldBtn.disabled = activeCount <= MIN_FIELDS;
    }

    function addField() {
      if (activeCount >= MAX_FIELDS) {
        return;
      }
      activeCount += 1;
      refreshRows();
      updateFrom(0);
    }

    function removeField() {
      if (activeCount <= MIN_FIELDS) {
        return;
      }
      activeCount -= 1;
      refreshRows();
      updateFrom(0);
    }

    if (canConvertNow()) {
      fields.forEach((field, index) => {
        field.input.addEventListener("input", () => updateFrom(index));
        field.select.addEventListener("change", () => {
          updateFieldLabels();
          updateFrom(index);
        });
      });
      rateTypeSelect.addEventListener("change", () => updateFrom(0));
      addFieldBtn.addEventListener("click", addField);
      removeFieldBtn.addEventListener("click", removeField);
      updateFieldLabels();
      refreshRows();
      updateFrom(0);
    } else {
      fields.forEach((field) => {
        field.input.disabled = true;
        field.select.disabled = true;
      });
      rateTypeSelect.disabled = true;
      addFieldBtn.disabled = true;
      removeFieldBtn.disabled = true;
      fieldCountText.textContent = "환율 조회 실패";
      updateFieldLabels();
      refreshRows();
    }
  </script>
</body>
</html>
"""


@dataclass(slots=True)
class RateSnapshot:
    """네이버에서 읽어온 환율 스냅샷(KRW 기준, 타입별)과 시각 정보."""

    rates_by_type: dict[str, dict[str, float]]
    source_time_text: str | None
    fetched_at_text: str


def _parse_market_row(html: str, market_code: str) -> str:
    """환율 목록 HTML에서 지정 코드의 행(tr) 블록을 파싱합니다."""
    pattern = rf"<tr[^>]*>.*?marketindexCd={market_code}.*?</tr>"
    match = re.search(pattern, html, flags=re.DOTALL)
    if not match:
        raise ValueError(f"환율 코드를 찾을 수 없습니다: {market_code}")
    return match.group(0)


def _parse_rate(row_html: str) -> float:
    """행 HTML에서 매매기준율 숫자만 추출합니다."""
    match = re.search(r"<td class=\"sale\">([^<]+)</td>", row_html)
    if not match:
        raise ValueError("매매기준율을 파싱할 수 없습니다.")
    return float(match.group(1).strip().replace(",", ""))


def _parse_rate_time(row_html: str) -> str | None:
    """행 HTML에서 기준 시각 텍스트를 추출합니다(없으면 None)."""
    match = re.search(r"<td class=\"date\">([^<]+)</td>", row_html)
    if not match:
        return None
    return match.group(1).strip()


def _parse_td_value(row_html: str, td_class: str) -> float:
    """행 HTML에서 특정 컬럼(td class)의 숫자를 추출합니다."""
    match = re.search(rf"<td class=\\\"{td_class}\\\">([^<]+)</td>", row_html)
    if not match:
        raise ValueError(f"{td_class} 값을 파싱할 수 없습니다.")
    return float(match.group(1).strip().replace(",", ""))


def fetch_naver_rates() -> RateSnapshot:
    """네이버 금융에서 선택 통화들의 환율을 타입별로(KRW 기준) 가져옵니다."""
    req = Request(
        NAVER_EXCHANGE_LIST_URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    try:
        with urlopen(req, timeout=10) as response:
            html = response.read().decode("euc-kr", errors="ignore")
    except URLError as exc:
        raise RuntimeError("네이버 환율 페이지에 연결할 수 없습니다.") from exc

    # KRW=1.0은 교차환산 편의를 위한 기준값입니다.
    rates_by_type: dict[str, dict[str, float]] = {
        "sale": {"KRW": 1.0},
        "buy": {"KRW": 1.0},
        "sell": {"KRW": 1.0},
        "send": {"KRW": 1.0},
        "receive": {"KRW": 1.0},
    }
    source_time_text: str | None = None

    for code, meta in CURRENCY_META.items():
        market_code = meta["market_code"]
        source_unit = float(meta["source_unit"])
        if market_code is None:
            continue

        row_html = _parse_market_row(html, market_code)

        # 네이버 표의 컬럼: sale(매매기준율), buy/sell(현찰), send/receive(송금)
        for rate_type, td_class in [
            ("sale", "sale"),
            ("buy", "buy"),
            ("sell", "sell"),
            ("send", "send"),
            ("receive", "receive"),
        ]:
            raw = _parse_td_value(row_html, td_class)
            rates_by_type[rate_type][code] = raw / source_unit

        if source_time_text is None:
            source_time_text = _parse_rate_time(row_html)

    fetched_at_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return RateSnapshot(
        rates_by_type=rates_by_type,
        source_time_text=source_time_text,
        fetched_at_text=fetched_at_text,
    )


def fetch_usdkrw_history(days: int = 183) -> list[tuple[str, float]]:
    """최근 N일(대략 6개월) USD/KRW 일자별 환율을 가져옵니다(참고용, 외부 API)."""
    cache_key = f"usdkrw:{days}"
    now = datetime.now()
    cached = _HIST_CACHE.get(cache_key)
    if cached and (now - cached[0]).total_seconds() < 6 * 3600:
        return cached[1]

    end = date.today()
    start = end - timedelta(days=days)
    url = (
        f"{EXCHANGERATE_TIMESERIES_URL}"
        f"?start_date={start.isoformat()}&end_date={end.isoformat()}"
        f"&base=USD&symbols=KRW"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))

    rates = payload.get("rates", {})
    series: list[tuple[str, float]] = []
    for d, obj in rates.items():
        try:
            v = float(obj["KRW"])
        except Exception:
            continue
        series.append((d, v))

    series.sort(key=lambda x: x[0])
    _HIST_CACHE[cache_key] = (now, series)
    return series


@app.route("/", methods=["GET"])
def index() -> str:
    error: str | None = None
    # 조회 실패 시에도 UI는 깨지지 않게 기본값으로 렌더링합니다.
    rates_by_type: dict[str, dict[str, float]] = {
        "sale": {code: (1.0 if code == "KRW" else 0.0) for code in CURRENCY_META},
        "buy": {code: (1.0 if code == "KRW" else 0.0) for code in CURRENCY_META},
        "sell": {code: (1.0 if code == "KRW" else 0.0) for code in CURRENCY_META},
        "send": {code: (1.0 if code == "KRW" else 0.0) for code in CURRENCY_META},
        "receive": {code: (1.0 if code == "KRW" else 0.0) for code in CURRENCY_META},
    }
    rate_time_text = "조회 실패"
    currencies = [{"code": code, "label": meta["label"], "flag": meta["flag"]} for code, meta in CURRENCY_META.items()]
    default_codes = ["USD", "KRW", "PHP", "EUR"]

    try:
        snapshot = fetch_naver_rates()
        rates_by_type = snapshot.rates_by_type
        if snapshot.source_time_text:
            rate_time_text = f"{snapshot.source_time_text} (네이버 표기 시각)"
        else:
            rate_time_text = f"{snapshot.fetched_at_text} (앱 조회 시각)"
    except Exception as exc:
        error = f"환율 조회에 실패했습니다: {exc}"

    # 6개월 히스토리(참고용) + 밈
    hist_series: list[tuple[str, float]] = []
    hist_meme = "데이터를 불러오는 중..."
    hist_start = ""
    hist_end = ""
    try:
        hist_series = fetch_usdkrw_history(days=183)
        if hist_series:
            hist_start = hist_series[0][0]
            hist_end = hist_series[-1][0]
            today_rate = hist_series[-1][1]
            min_day, min_rate = min(hist_series, key=lambda x: x[1])
            max_day, max_rate = max(hist_series, key=lambda x: x[1])

            if today_rate > min_rate:
                diff = today_rate - min_rate
                hist_meme = (
                    f"아 그때({min_day}) 달러 샀으면 지금보다 {diff:,.2f}원/달러 싸게 샀는데..."
                    f" (최저 {min_rate:,.2f}, 오늘 {today_rate:,.2f})"
                )
            else:
                hist_meme = f"지금이 그때다. (최저={min_rate:,.2f}, 오늘={today_rate:,.2f})"

            # 범위 정보도 같이 보이게(짧게)
            hist_meme += f" / 6개월 고점({max_day}) {max_rate:,.2f}"
        else:
            hist_meme = "최근 6개월 데이터를 가져오지 못했습니다."
    except Exception:
        hist_meme = "최근 6개월 데이터를 가져오지 못했습니다."

    return render_template_string(
        HTML_TEMPLATE,
        error=error,
        rates_by_type=rates_by_type,
        currencies=currencies,
        default_codes=default_codes,
        rate_time_text=rate_time_text,
        hist_series=hist_series,
        hist_meme=hist_meme,
        hist_start=hist_start,
        hist_end=hist_end,
        hist_count=len(hist_series),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
