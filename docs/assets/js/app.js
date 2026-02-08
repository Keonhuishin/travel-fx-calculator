// Main app module (no bundler). Loads rates snapshot from ./data/rates.json
// and does client-side cross-rate conversion in real time.

import { flagUrl } from "./flags.js";
import {
  parseEditableNumber,
  formatEditableNumberText,
  toInputValue,
  setValuePreserveCaret,
  selectAllSoon,
} from "./format.js";

const DEFAULT_CODES = ["USD", "KRW", "PHP", "EUR", "JPY"]; // initial selection
const MIN_FIELDS = 1;
const MAX_FIELDS = 5;

// Pretty version label for UX (semver-ish). Override with ?ver=1.3.5
const UI_SEMVER = "1.3.4";

const CODE_LABEL = {
  USD: "미국 달러 (USD)",
  KRW: "대한민국 원화 (KRW)",
  PHP: "필리핀 페소 (PHP)",
  TWD: "대만 달러 (TWD)",
  JPY: "일본 엔화 (JPY)",
  EUR: "유로 (EUR)",
  AUD: "호주 달러 (AUD)",
  THB: "태국 바트 (THB)",
  VND: "베트남 동 (VND)",
  CNY: "중국 위안 (CNY)",
};

const CODE_ORDER = ["USD", "KRW", "PHP", "TWD", "JPY", "EUR", "AUD", "THB", "VND", "CNY"];

// Local-only 기록: localStorage on the user's device.
const STORAGE_KEY = "travel-fx-calculator.history.v1";
const MAX_SAVED = 50;

let activeCount = 3;
let lastEditedIndex = 0;
let isSyncing = false;

const addFieldBtn = document.getElementById("add_field");
const removeFieldBtn = document.getElementById("remove_field");
const saveBtn = document.getElementById("save_calc");
const rateTypeSelect = document.getElementById("rate_type");
const fieldCountText = document.getElementById("field_count_text");
const grid = document.getElementById("grid");
const meta = document.getElementById("meta");
const errorEl = document.getElementById("error");
const savedEl = document.getElementById("saved");
const appVersionEl = document.getElementById("app_version");

function qsParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

function setVersionPill(data) {
  if (!appVersionEl) return;

  const uiVersion = qsParam("ver") || UI_SEMVER;
  appVersionEl.textContent = `v${uiVersion}`;

  const sha = data && data.build_sha ? String(data.build_sha) : "";
  const fetchedAt = data && data.fetched_at ? String(data.fetched_at) : "";
  const parts = [];
  if (sha) parts.push(`build ${sha}`);
  if (fetchedAt) parts.push(`rates ${fetchedAt}`);

  appVersionEl.title = parts.length ? `v${uiVersion} - ${parts.join(" | ")}` : `v${uiVersion}`;
}

function updateKeyboardClass() {
  const vv = window.visualViewport;
  const baseH = window.innerHeight || 0;
  const vvH = vv ? vv.height : baseH;
  const ratio = baseH ? vvH / baseH : 1;

  const ae = document.activeElement;
  const tag = ae && ae.tagName ? ae.tagName.toLowerCase() : "";
  const isEditing = tag === "input" || tag === "select" || tag === "textarea";

  const openByViewport = vv ? ratio < 0.78 : false;

  // Keep the version pill inside the visual viewport (iOS keyboard can cover fixed UI).
  if (appVersionEl && vv) {
    const overlap = Math.max(0, (window.innerHeight || 0) - (vv.height + vv.offsetTop));
    appVersionEl.style.transform = overlap > 0 ? `translateY(${-overlap}px)` : "";
  }

  document.body.classList.toggle("kbd-open", Boolean(isEditing && openByViewport) || (!vv && isEditing));
}

function setupKeyboardCompactMode() {
  updateKeyboardClass();
  window.addEventListener("focusin", updateKeyboardClass);
  window.addEventListener("focusout", () => setTimeout(updateKeyboardClass, 80));
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", updateKeyboardClass);
    window.visualViewport.addEventListener("scroll", updateKeyboardClass);
  } else {
    window.addEventListener("resize", updateKeyboardClass);
  }
}

setupKeyboardCompactMode();

function currentRates(ratesByType) {
  const t = rateTypeSelect.value;
  return ratesByType[t] || ratesByType.sale;
}

function canConvertSelected(ratesByType, fields) {
  const r = currentRates(ratesByType);
  return fields.slice(0, activeCount).every((f) => Number.isFinite(r[f.sel.value]) && r[f.sel.value] > 0);
}

function convertAmount(ratesByType, amount, fromCode, toCode) {
  if (fromCode === toCode) return amount;
  const r = currentRates(ratesByType);
  const inKrw = amount * r[fromCode];
  return inKrw / r[toCode];
}

function refreshRows(fields) {
  fields.forEach((f, idx) => f.row.classList.toggle("hidden", idx >= activeCount));
  fieldCountText.textContent = `표시 중: ${activeCount} / ${MAX_FIELDS}`;
  addFieldBtn.disabled = activeCount >= MAX_FIELDS;
  removeFieldBtn.disabled = activeCount <= MIN_FIELDS;
}

function applyEnabledState(ratesByType, fields) {
  const ok = canConvertSelected(ratesByType, fields);

  fields.slice(0, activeCount).forEach((f) => {
    f.inp.disabled = !ok;
    f.sel.disabled = false;
  });

  fields.slice(activeCount).forEach((f) => {
    f.inp.disabled = true;
    f.sel.disabled = true;
  });

  if (!ok) fieldCountText.textContent = `표시 중: ${activeCount} / ${MAX_FIELDS} (환율 데이터 부족)`;
  return ok;
}

function renderMeta(data) {
  const typeLabel = rateTypeSelect.options[rateTypeSelect.selectedIndex]?.textContent || "";

  meta.replaceChildren();

  const l1 = document.createElement("div");
  l1.appendChild(document.createTextNode("환율 기준: "));
  const strong = document.createElement("strong");
  strong.textContent = typeLabel;
  l1.appendChild(strong);

  const l2 = document.createElement("div");
  l2.textContent = `업데이트: ${data.fetched_at || "-"}`;

  const l3 = document.createElement("div");
  l3.textContent = data.source
    ? `출처: 네이버 금융 (${data.source})`
    : "출처: 네이버 금융";

  meta.appendChild(l1);
  meta.appendChild(l2);
  meta.appendChild(l3);
}

function setPrevCode(f, code) {
  f.row.dataset.prevCode = code;
}

function getPrevCode(f) {
  return f.row.dataset.prevCode || f.sel.value;
}

function updateFrom(ratesByType, fields, index, preserveSourceCaret = false, sourceOldText = "", sourceOldCaret = 0) {
  if (isSyncing) return;
  isSyncing = true;

  const activeFields = fields.slice(0, activeCount);
  const source = activeFields[index];
  if (!source) {
    isSyncing = false;
    return;
  }

  const sourceCode = source.sel.value;
  const parsed = parseEditableNumber(source.inp.value);
  if (parsed.empty) {
    activeFields.forEach((f, i) => {
      if (i !== index) f.inp.value = "";
    });
    isSyncing = false;
    return;
  }

  const sourceAmount = parsed.number;
  const sourceFormatted = parsed.cleaned.endsWith(".")
    ? formatEditableNumberText(parsed.cleaned)
    : toInputValue(sourceAmount);

  if (preserveSourceCaret) {
    setValuePreserveCaret(source.inp, sourceFormatted, sourceOldText, sourceOldCaret);
  } else {
    source.inp.value = sourceFormatted;
  }

  activeFields.forEach((f, i) => {
    if (i === index) return;
    f.inp.value = toInputValue(convertAmount(ratesByType, sourceAmount, sourceCode, f.sel.value));
  });

  isSyncing = false;
}

function buildRow(i, codes) {
  const row = document.createElement("div");
  row.className = "field field-row";
  row.dataset.index = String(i);

  const left = document.createElement("div");
  const right = document.createElement("div");

  const wrap = document.createElement("div");
  wrap.className = "currency-row";

  const flag = document.createElement("img");
  flag.className = "flag-big";
  flag.alt = "";
  flag.decoding = "async";
  flag.loading = "lazy";

  const sel = document.createElement("select");
  sel.id = `currency_${i + 1}`;
  sel.setAttribute("aria-label", "통화");
  codes.forEach((code) => {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = CODE_LABEL[code] || code;
    sel.appendChild(opt);
  });

  const defaultCode = DEFAULT_CODES[i] || "KRW";
  sel.value = codes.includes(defaultCode) ? defaultCode : (codes[0] || "KRW");
  row.dataset.prevCode = sel.value;
  flag.src = flagUrl(sel.value);

  wrap.appendChild(flag);
  wrap.appendChild(sel);
  left.appendChild(wrap);

  const inp = document.createElement("input");
  inp.type = "text";
  inp.inputMode = "decimal";
  inp.id = `amount_${i + 1}`;
  inp.setAttribute("aria-label", "금액");
  inp.value = "0.00";
  inp.placeholder = "0.00";

  right.appendChild(inp);
  row.appendChild(left);
  row.appendChild(right);

  return { row, sel, inp, flag };
}

function safeJsonParse(text, fallback) {
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

function loadHistory() {
  const raw = localStorage.getItem(STORAGE_KEY);
  const data = safeJsonParse(raw || "[]", []);
  return Array.isArray(data) ? data : [];
}

function saveHistory(list) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_SAVED)));
}

function commaInt(s) {
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function formatRecordAmount(code, n) {
  const v = Number.isFinite(n) && n >= 0 ? n : 0;
  const fixed = code === "KRW" ? 0 : 2;
  let s = v.toFixed(fixed);
  if (fixed === 2 && s.endsWith(".00")) s = s.slice(0, -3);
  const parts = s.split(".");
  parts[0] = commaInt(parts[0]);
  return parts.join(".");
}

function formatRecordTitle(rows) {
  return rows
    .map((r) => `${r.code} ${formatRecordAmount(r.code, r.amount)}`)
    .join(" / ");
}

function formatKoreanTime(iso) {
  try {
    return new Date(iso).toLocaleString("ko-KR", { hour12: false });
  } catch {
    return iso || "";
  }
}

function renderHistory(list, onDelete) {
  if (!savedEl) return;

  if (list.length === 0) {
    savedEl.hidden = true;
    savedEl.replaceChildren();
    return;
  }

  savedEl.hidden = false;
  savedEl.replaceChildren();

  const head = document.createElement("div");
  head.className = "history-head";

  const title = document.createElement("div");
  title.className = "history-title";
  title.textContent = `기록 (${list.length})`;\n  head.appendChild(title);\n  savedEl.appendChild(head);

  const ul = document.createElement("ul");
  ul.className = "saved-list";

  list.forEach((item, idx) => {
    const li = document.createElement("li");
    li.className = "saved-item";

    const left = document.createElement("div");
    left.className = "saved-left";

    const t = document.createElement("div");
    t.className = "saved-title";
    t.textContent = item.title || formatRecordTitle(item.rows || []);

    const sub = document.createElement("div");
    sub.className = "saved-sub";
    sub.textContent = formatKoreanTime(item.at);

    left.appendChild(t);
    left.appendChild(sub);

    const actions = document.createElement("div");
    actions.className = "saved-actions";

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "saved-btn danger";
    delBtn.textContent = "지우기";
    delBtn.addEventListener("click", () => onDelete(idx));

    actions.appendChild(delBtn);

    li.appendChild(left);
    li.appendChild(actions);

    ul.appendChild(li);
  });

  savedEl.appendChild(ul);
}

async function loadSnapshot() {
  const res = await fetch(`./data/rates.json?t=${Date.now()}`);
  if (!res.ok) throw new Error("rates.json not found");
  return await res.json();
}

loadSnapshot()\n  .then((data) => {\n    if (errorEl) { errorEl.style.display = "none"; errorEl.textContent = ""; }
    setVersionPill(data);

    const ratesByType = data.rates_by_type;
    const sale = ratesByType && ratesByType.sale ? ratesByType.sale : {};

    const supportedCodes = CODE_ORDER.filter((code) => Object.prototype.hasOwnProperty.call(sale, code));

    const fields = [];
    for (let i = 0; i < MAX_FIELDS; i++) {
      const f = buildRow(i, supportedCodes);
      fields.push(f);
      grid.appendChild(f.row);
      setPrevCode(f, f.sel.value);
    }

    function rerenderHistory() {
      const list = loadHistory();
      renderHistory(list, (idx) => {
          const next = loadHistory();
          next.splice(idx, 1);
          saveHistory(next);
          rerenderHistory();
        });
    }

    rerenderHistory();

    fields.forEach((f, idx) => {
      f.inp.addEventListener("focus", () => {
        lastEditedIndex = idx;
        selectAllSoon(f.inp);
      });
      f.inp.addEventListener("click", () => {
        lastEditedIndex = idx;
        selectAllSoon(f.inp);
      });
      f.inp.addEventListener("input", () => {
        const oldText = f.inp.value;
        const oldCaret = f.inp.selectionStart ?? oldText.length;
        lastEditedIndex = idx;
        updateFrom(ratesByType, fields, idx, true, oldText, oldCaret);
      });
      f.inp.addEventListener("blur", () => {
        const parsed = parseEditableNumber(f.inp.value);
        lastEditedIndex = idx;
        if (parsed.empty) {
          f.inp.value = "0.00";
          updateFrom(ratesByType, fields, idx);
          return;
        }
        f.inp.value = toInputValue(parsed.number);
        updateFrom(ratesByType, fields, idx);
      });

      f.sel.addEventListener("change", () => {
        const oldCode = getPrevCode(f);
        const newCode = f.sel.value;
        f.flag.src = flagUrl(newCode);

        const ok = applyEnabledState(ratesByType, fields);
        if (!ok) {
          setPrevCode(f, newCode);
          return;
        }

        // If the user changed the currency on the source row, keep value-equivalence.
        if (idx === lastEditedIndex) {
          const r = currentRates(ratesByType);
          const amountOld = parseEditableNumber(f.inp.value).number;
          const krwValue = amountOld * r[oldCode];
          const amountNew = krwValue / r[newCode];
          f.inp.value = toInputValue(amountNew);
          setPrevCode(f, newCode);
          updateFrom(ratesByType, fields, idx);
          return;
        }

        setPrevCode(f, newCode);
        updateFrom(ratesByType, fields, Math.min(lastEditedIndex, activeCount - 1));
      });
    });

    rateTypeSelect.addEventListener("change", () => {
      applyEnabledState(ratesByType, fields);
      renderMeta(data);
      updateFrom(ratesByType, fields, Math.min(lastEditedIndex, activeCount - 1));
    });

    addFieldBtn.addEventListener("click", () => {
      if (activeCount >= MAX_FIELDS) return;
      activeCount += 1;
      refreshRows(fields);
      applyEnabledState(ratesByType, fields);
      updateFrom(ratesByType, fields, Math.min(lastEditedIndex, activeCount - 1));
    });

    removeFieldBtn.addEventListener("click", () => {
      if (activeCount <= MIN_FIELDS) return;
      activeCount -= 1;
      refreshRows(fields);
      applyEnabledState(ratesByType, fields);
      updateFrom(ratesByType, fields, Math.min(lastEditedIndex, activeCount - 1));
    });

    if (saveBtn) {
      saveBtn.addEventListener("click", () => {
        const list = loadHistory();
        const at = new Date().toISOString();

        const rows = fields.slice(0, activeCount).map((ff) => ({
          code: ff.sel.value,
          amount: parseEditableNumber(ff.inp.value).number,
        }));

        list.unshift({
          at,
          title: formatRecordTitle(rows),
          rateType: rateTypeSelect.value,
          activeCount,
          sourceIndex: Math.min(activeCount - 1, Math.max(0, lastEditedIndex)),
          rows,
        });

        saveHistory(list);
        rerenderHistory();
      });
    }

    refreshRows(fields);
    applyEnabledState(ratesByType, fields);
    updateFrom(ratesByType, fields, 0);
    renderMeta(data);
  })
  .catch((e) => {
    if (errorEl) {
      errorEl.style.display = "block";
      errorEl.textContent = `환율 데이터를 불러오지 못했습니다: ${e.message}`;
    }
    setVersionPill(null);
  });


