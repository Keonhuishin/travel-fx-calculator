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

// Pretty version label for UX (semver-ish). Override with ?ver=1.3.4
const UI_SEMVER = "1.3.4";

const CODE_LABEL = {
  KRW: "Korean Won (KRW)",
  USD: "US Dollar (USD)",
  CNY: "Chinese Yuan (CNY)",
  PHP: "Philippine Peso (PHP)",
  TWD: "Taiwan Dollar (TWD)",
  JPY: "Japanese Yen (JPY)",
  VND: "Vietnamese Dong (VND)",
  THB: "Thai Baht (THB)",
  EUR: "Euro (EUR)",
  AUD: "Australian Dollar (AUD)",
};

// Local-only save (privacy-friendly): localStorage on the user's device.
const STORAGE_KEY = "travel-fx-calculator.saved.v1";
const MAX_SAVED = 30;

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
  fieldCountText.textContent = `Showing: ${activeCount} / ${MAX_FIELDS}`;
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

  if (!ok) fieldCountText.textContent = `Showing: ${activeCount} / ${MAX_FIELDS} (rates missing)`;
  return ok;
}

function renderMeta(data) {
  const typeLabel = rateTypeSelect.options[rateTypeSelect.selectedIndex]?.textContent || "";

  meta.replaceChildren();

  const l1 = document.createElement("div");
  l1.appendChild(document.createTextNode("Rate basis: "));
  const strong = document.createElement("strong");
  strong.textContent = typeLabel;
  l1.appendChild(strong);

  const l2 = document.createElement("div");
  l2.textContent = `Updated: ${data.fetched_at || "-"}`;

  const l3 = document.createElement("div");
  l3.textContent = data.source ? `Source: Naver Finance (${data.source})` : "Source: Naver Finance";

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
  sel.setAttribute("aria-label", "Currency");
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
  inp.setAttribute("aria-label", "Amount");
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

function loadSaved() {
  const raw = localStorage.getItem(STORAGE_KEY);
  const data = safeJsonParse(raw || "[]", []);
  return Array.isArray(data) ? data : [];
}

function saveSaved(list) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_SAVED)));
}

function renderSaved(list, onLoad, onDelete, onClear) {
  if (!savedEl) return;

  savedEl.hidden = false;
  savedEl.replaceChildren();

  const details = document.createElement("details");
  details.className = "saved-details";

  const summary = document.createElement("summary");
  summary.textContent = `Saved (${list.length})`;
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "saved-body";

  if (list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "saved-empty";
    empty.textContent = "No saved calculations yet.";
    body.appendChild(empty);
  } else {
    const ul = document.createElement("ul");
    ul.className = "saved-list";

    list.forEach((item, idx) => {
      const li = document.createElement("li");
      li.className = "saved-item";

      const left = document.createElement("div");
      left.className = "saved-left";

      const title = document.createElement("div");
      title.className = "saved-title";
      title.textContent = item.title || `#${idx + 1}`;

      const sub = document.createElement("div");
      sub.className = "saved-sub";
      sub.textContent = item.at || "";

      left.appendChild(title);
      left.appendChild(sub);

      const actions = document.createElement("div");
      actions.className = "saved-actions";

      const loadBtn = document.createElement("button");
      loadBtn.type = "button";
      loadBtn.className = "saved-btn";
      loadBtn.textContent = "Load";
      loadBtn.addEventListener("click", () => onLoad(idx));

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "saved-btn danger";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", () => onDelete(idx));

      actions.appendChild(loadBtn);
      actions.appendChild(delBtn);

      li.appendChild(left);
      li.appendChild(actions);
      ul.appendChild(li);
    });

    body.appendChild(ul);

    const clearWrap = document.createElement("div");
    clearWrap.className = "saved-clear";

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "saved-btn danger";
    clearBtn.textContent = "Clear all";
    clearBtn.addEventListener("click", onClear);

    clearWrap.appendChild(clearBtn);
    body.appendChild(clearWrap);
  }

  details.appendChild(body);
  savedEl.appendChild(details);
}

async function loadSnapshot() {
  // Cache-bust using 't' param.
  const res = await fetch(`./data/rates.json?t=${Date.now()}`);
  if (!res.ok) throw new Error("rates.json not found");
  return await res.json();
}

loadSnapshot()
  .then((data) => {
    setVersionPill(data);

    const ratesByType = data.rates_by_type;
    const sale = ratesByType && ratesByType.sale ? ratesByType.sale : {};

    const supportedCodes = Object.keys(CODE_LABEL).filter((code) => Object.prototype.hasOwnProperty.call(sale, code));
    if (!supportedCodes.includes("KRW")) supportedCodes.unshift("KRW");

    const fields = [];
    for (let i = 0; i < MAX_FIELDS; i++) {
      const f = buildRow(i, supportedCodes);
      fields.push(f);
      grid.appendChild(f.row);
      setPrevCode(f, f.sel.value);
    }

    function rerenderSaved() {
      const list = loadSaved();
      renderSaved(
        list,
        (idx) => {
          const item = list[idx];
          if (!item) return;

          activeCount = Math.min(MAX_FIELDS, Math.max(MIN_FIELDS, item.activeCount || 3));
          rateTypeSelect.value = item.rateType || "sale";
          lastEditedIndex = Math.min(activeCount - 1, Math.max(0, item.sourceIndex || 0));

          refreshRows(fields);

          const rows = Array.isArray(item.rows) ? item.rows : [];
          for (let i = 0; i < Math.min(rows.length, MAX_FIELDS); i++) {
            const r = rows[i];
            if (!r) continue;
            if (r.code && supportedCodes.includes(r.code)) fields[i].sel.value = r.code;
            fields[i].flag.src = flagUrl(fields[i].sel.value);
            if (typeof r.text === "string") fields[i].inp.value = r.text;
            else if (typeof r.amount === "number") fields[i].inp.value = toInputValue(r.amount);
            setPrevCode(fields[i], fields[i].sel.value);
          }

          applyEnabledState(ratesByType, fields);
          renderMeta(data);
          updateFrom(ratesByType, fields, lastEditedIndex);
        },
        (idx) => {
          const next = loadSaved();
          next.splice(idx, 1);
          saveSaved(next);
          rerenderSaved();
        },
        () => {
          saveSaved([]);
          rerenderSaved();
        },
      );
    }

    rerenderSaved();

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
        const list = loadSaved();
        const at = new Date().toISOString();
        const rows = fields.slice(0, activeCount).map((ff) => ({
          code: ff.sel.value,
          text: String(ff.inp.value || "").trim(),
          amount: parseEditableNumber(ff.inp.value).number,
        }));

        const title = rows.map((r) => r.code).join(" / ");

        list.unshift({
          at,
          title,
          rateType: rateTypeSelect.value,
          activeCount,
          sourceIndex: Math.min(activeCount - 1, Math.max(0, lastEditedIndex)),
          rows,
        });

        saveSaved(list);
        rerenderSaved();
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
      errorEl.textContent = `Failed to load rates: ${e.message}`;
    }
    setVersionPill(null);
  });

