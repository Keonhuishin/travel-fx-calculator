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
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Flask, render_template_string

app = Flask(__name__)

NAVER_EXCHANGE_LIST_URL = "https://finance.naver.com/marketindex/exchangeList.naver"

# `source_unit`:
# - JPY/VND는 네이버에서 100단위 기준으로 제공되므로 1단위로 환산하기 위해 사용합니다.
# - 나머지는 1단위 기준 환율입니다.
CURRENCY_META = {
    "KRW": {"label": "대한민국 원화 (KRW)", "flag": "🇰🇷", "market_code": None, "source_unit": 1},
    "USD": {"label": "미국 달러 (USD)", "flag": "🇺🇸", "market_code": "FX_USDKRW", "source_unit": 1},
    "CNY": {"label": "중국 위안 (CNY)", "flag": "🇨🇳", "market_code": "FX_CNYKRW", "source_unit": 1},
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
    .currency-row {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .flag-big {
      width: 34px;
      text-align: center;
      font-size: 22px;
      line-height: 1;
      user-select: none;
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
    <h1>여행용 환율 계산기</h1>

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
            <div class="currency-row">
              <span class="flag-big" id="flag_{{ idx }}" aria-hidden="true">{{ currency_flags[default_codes[idx - 1]] }}</span>
              <select id="currency_{{ idx }}" class="currency-select">
                {% for item in currencies %}
                  <option value="{{ item.code }}" {% if item.code == default_codes[idx - 1] %}selected{% endif %}>{{ item.label }} {{ item.flag }}</option>
                {% endfor %}
              </select>
            </div>
          </div>
          <div>
            <label for="amount_{{ idx }}">금액</label>
            <input id="amount_{{ idx }}" class="amount-input" type="text" inputmode="decimal" value="0" placeholder="0" />
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
      <details>
        <summary>설명 보기</summary>
        <div>환율 종류: 네이버 금융의 <strong>매매기준율/현찰/송금</strong> 중 하나를 선택합니다. 변환은 선택된 기준을 동일하게 적용해 교차환산합니다.</div>
        <div>참고: JPY, VND는 네이버의 100단위 기준 값을 1단위 기준으로 환산해 적용합니다.</div>
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
    const currencyFlags = {{ currency_flags | tojson }};
    const rowElements = Array.from(document.querySelectorAll(".field-row"));
    const fields = rowElements.map((row, index) => ({
      row,
      select: document.getElementById(`currency_${index + 1}`),
      input: document.getElementById(`amount_${index + 1}`),
      titleLabel: row.querySelector(`label[for="currency_${index + 1}"]`),
      flag: document.getElementById(`flag_${index + 1}`)
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

    function canConvertSelected() {
      const r = currentRates();
      const activeFields = fields.slice(0, activeCount);
      // 현재 화면에서 선택된 통화만 환율이 있으면 계산 가능
      return activeFields.every((f) => Number.isFinite(r[f.select.value]) && r[f.select.value] > 0);
    }
    // 입력 이벤트가 연쇄적으로 재호출되는 것을 방지하는 락
    let isSyncing = false;
    // 사용자가 "마지막으로 금액을 입력한 칸"을 기준(source)으로 삼습니다.
    // 통화 셀렉트를 바꿀 때, 바꾼 칸이 source가 아니라면 그 칸의 금액이 변해야 UX가 자연스럽습니다.
    let lastEditedIndex = 0;

    function setPrevCode(index, code) {
      fields[index].row.dataset.prevCode = code;
    }

    function getPrevCode(index) {
      return fields[index].row.dataset.prevCode || fields[index].select.value;
    }

    function cleanEditableNumberText(value) {
      // Keep a permissive "in-progress" decimal format while typing:
      // - allow empty
      // - allow "1.", ".5"
      // - disallow negatives
      // - strip thousands separators
      const cleaned = String(value).replace(/,/g, "").trim();
      if (cleaned === "") return "";
      if (cleaned.includes("-")) return "";
      if (!/^\\d*\\.?\\d*$/.test(cleaned)) return "";
      return cleaned;
    }

    function parseEditableNumber(value) {
      const cleaned = cleanEditableNumberText(value);
      if (cleaned === "") return { empty: true, cleaned: "", number: 0 };
      // "." alone should behave like "0." while editing.
      const normalized = cleaned === "." ? "0." : cleaned;
      const n = Number.parseFloat(normalized);
      return { empty: false, cleaned: normalized, number: Number.isFinite(n) && n >= 0 ? n : 0 };
    }

    function formatEditableNumberText(cleaned) {
      // cleaned: digits with optional '.' and fractional digits (no commas)
      if (cleaned === "") return "";
      const hasDot = cleaned.includes(".");
      let [intPart, fracPart] = cleaned.split(".");
      if (intPart === "") intPart = "0";
      intPart = intPart.replace(/^0+(?=\\d)/, "");
      intPart = intPart.replace(/\\B(?=(\\d{3})+(?!\\d))/g, ",");
      if (!hasDot) return intPart;
      if (fracPart === undefined) return `${intPart}.`;
      return `${intPart}.${fracPart}`;
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

    function nonCommaIndex(text, caretPos) {
      // caret 이전까지의 "콤마 제외" 문자 개수 (숫자/소수점 포함)
      let count = 0;
      for (let i = 0; i < Math.min(text.length, caretPos); i++) {
        if (text[i] !== ",") count += 1;
      }
      return count;
    }

    function caretPosFromNonCommaIndex(text, idx) {
      // "콤마 제외" 문자 idx개가 지나간 위치의 caret pos
      if (idx <= 0) return 0;
      let count = 0;
      for (let i = 0; i < text.length; i++) {
        if (text[i] !== ",") count += 1;
        if (count >= idx) return i + 1;
      }
      return text.length;
    }

    function setValuePreserveCaret(inputEl, formatted, oldText, oldCaret) {
      // 포맷으로 input.value를 덮어써도 커서 위치가 유지되도록 매핑합니다.
      const idx = nonCommaIndex(oldText, oldCaret ?? oldText.length);
      inputEl.value = formatted;
      const pos = caretPosFromNonCommaIndex(inputEl.value, idx);
      try { inputEl.setSelectionRange(pos, pos); } catch { /* ignore */ }
    }

    function selectAllSoon(inputEl) {
      // 모바일 브라우저는 focus 직후 selection 설정이 씹히는 경우가 있어 tick을 한 번 넘깁니다.
      setTimeout(() => {
        try { inputEl.setSelectionRange(0, inputEl.value.length); } catch { /* ignore */ }
      }, 0);
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
        const code = field.select.value;
        field.titleLabel.textContent = `기준 통화 ${index + 1}`;
        field.flag.textContent = currencyFlags[code] || "";
      });
    }

    function updateFrom(index, preserveSourceCaret = false, sourceOldText = "", sourceOldCaret = 0) {
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
      const parsed = parseEditableNumber(source.input.value);
      if (parsed.empty) {
        // If user cleared the field, keep it empty and clear dependent fields.
        activeFields.forEach((f, i) => { if (i !== index) f.input.value = ""; });
        isSyncing = false;
        return;
      }
      const sourceAmount = parsed.number;
      const sourceFormatted = formatEditableNumberText(parsed.cleaned);
      if (preserveSourceCaret) setValuePreserveCaret(source.input, sourceFormatted, sourceOldText, sourceOldCaret);
      else source.input.value = sourceFormatted;

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

    function applyEnabledState() {
      const ok = canConvertSelected();
      const activeFields = fields.slice(0, activeCount);
      // 환율이 부족해도 통화 선택/칸 추가제거는 가능하게 두고, 금액 입력만 막습니다.
      activeFields.forEach((f) => {
        f.input.disabled = !ok;
        f.select.disabled = false;
      });
      // 숨겨진 칸은 이벤트가 남아있어도 입력 못 하게
      fields.slice(activeCount).forEach((f) => {
        f.input.disabled = true;
        f.select.disabled = true;
      });
      if (!ok) {
        fieldCountText.textContent = `표시 중: ${activeCount} / ${MAX_FIELDS} (환율 데이터 부족)`;
      }
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

    // 환율이 부분적으로만 있어도 UI는 조작 가능하게 유지합니다.
    fields.forEach((field, index) => {
      field.input.addEventListener("focus", () => {
        // 요구사항: 어디를 클릭해도 항상 맨 왼쪽부터(전체 선택 후 덮어쓰기)
        lastEditedIndex = index;
        selectAllSoon(field.input);
      });
      field.input.addEventListener("click", () => {
        lastEditedIndex = index;
        selectAllSoon(field.input);
      });
      field.input.addEventListener("input", () => {
        const oldText = field.input.value;
        const oldCaret = field.input.selectionStart ?? oldText.length;
        lastEditedIndex = index;
        updateFrom(index, true, oldText, oldCaret);
      });
      field.select.addEventListener("change", () => {
        const oldCode = getPrevCode(index);
        const newCode = field.select.value;
        updateFieldLabels();
        applyEnabledState();
        // UX 규칙:
        // - 마지막 입력 칸이 '다른 칸'이면: 통화 바꾼 칸의 값이 변해야 함 (source 유지).
        // - 마지막 입력 칸이 '바로 이 칸'이면: 동일 가치(원화 환산)를 유지한 채 표기 통화만 변경.
        if (index === lastEditedIndex) {
          const r = currentRates();
          const amountOld = parseEditableNumber(field.input.value).number;
          const krwValue = amountOld * r[oldCode];
          const amountNew = krwValue / r[newCode];
          field.input.value = toInputValue(amountNew);
          setPrevCode(index, newCode);
          updateFrom(index);
          return;
        }

        setPrevCode(index, newCode);
        const sourceIndex = Math.min(lastEditedIndex, activeCount - 1);
        updateFrom(sourceIndex);
      });
    });
    rateTypeSelect.addEventListener("change", () => {
      applyEnabledState();
      const sourceIndex = Math.min(lastEditedIndex, activeCount - 1);
      updateFrom(sourceIndex);
    });
    addFieldBtn.addEventListener("click", () => {
      addField();
      updateFieldLabels();
      applyEnabledState();
      const sourceIndex = Math.min(lastEditedIndex, activeCount - 1);
      updateFrom(sourceIndex);
    });
    removeFieldBtn.addEventListener("click", () => {
      removeField();
      updateFieldLabels();
      applyEnabledState();
      const sourceIndex = Math.min(lastEditedIndex, activeCount - 1);
      updateFrom(sourceIndex);
    });
    updateFieldLabels();
    // 초기 prevCode 세팅
    fields.forEach((f, idx) => setPrevCode(idx, f.select.value));
    refreshRows();
    applyEnabledState();
    updateFrom(0);
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
    # 정규식으로 "한 행"만 안전하게 뽑아야 합니다.
    # `.*?marketindexCd=...` 같은 패턴은 행 경계를 넘어 다음 행까지 먹어버릴 수 있어
    # USD 값이 다른 통화에 복사되는(1:1 변환) 치명 버그가 생깁니다.
    for m in re.finditer(r"<tr>\s*.*?</tr>", html, flags=re.DOTALL):
        row = m.group(0)
        if f"marketindexCd={market_code}" in row and 'class="tit"' in row:
            return row

    raise ValueError(f"환율 코드를 찾을 수 없습니다: {market_code}")


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


def _parse_row_numbers(row_html: str) -> list[float]:
    """데이터 행에서 숫자 컬럼을 순서대로 파싱합니다.

    네이버 환율표 데이터 행 구조(대략):
    - td.tit: 통화명
    - td.sale: 매매기준율
    - td: 현찰 사실 때
    - td: 현찰 파실 때
    - td: 송금 보내실 때
    - td: 송금 받으실 때
    - td: 미화환산율
    """
    tds = re.findall(r"<td[^>]*>\s*([^<]+?)\s*</td>", row_html, flags=re.DOTALL)
    # td.tit까지 포함될 수 있으므로 숫자만 필터링합니다.
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

        # 숫자 컬럼을 열 순서대로 파싱해 매핑합니다.
        # 기대하는 숫자 컬럼 순서: [매매기준율, 사실 때, 파실 때, 보내실 때, 받으실 때, 미화환산율]
        cols = _parse_row_numbers(row_html)
        if len(cols) < 5:
            raise RuntimeError(f"환율 컬럼 파싱 실패: {code} (cols={cols})")

        sale, buy, sell, send, receive = cols[0], cols[1], cols[2], cols[3], cols[4]
        rates_by_type["sale"][code] = sale / source_unit
        rates_by_type["buy"][code] = buy / source_unit
        rates_by_type["sell"][code] = sell / source_unit
        rates_by_type["send"][code] = send / source_unit
        rates_by_type["receive"][code] = receive / source_unit

        if source_time_text is None:
            source_time_text = _parse_rate_time(row_html)

    fetched_at_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return RateSnapshot(
        rates_by_type=rates_by_type,
        source_time_text=source_time_text,
        fetched_at_text=fetched_at_text,
    )


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
    currency_flags = {code: meta["flag"] for code, meta in CURRENCY_META.items()}
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

    return render_template_string(
        HTML_TEMPLATE,
        error=error,
        rates_by_type=rates_by_type,
        currencies=currencies,
        currency_flags=currency_flags,
        default_codes=default_codes,
        rate_time_text=rate_time_text,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
