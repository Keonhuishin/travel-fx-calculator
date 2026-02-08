// Formatting/parsing helpers for editable currency inputs.

export function cleanEditableNumberText(value) {
  const cleaned = String(value).replace(/,/g, "").trim();
  if (cleaned === "") return "";
  if (cleaned.includes("-")) return "";
  if (!/^\d*\.?\d*$/.test(cleaned)) return "";
  return cleaned;
}

export function parseEditableNumber(value) {
  const cleaned = cleanEditableNumberText(value);
  if (cleaned === "") return { empty: true, cleaned: "", number: 0 };
  const normalized = cleaned === "." ? "0." : cleaned;
  const n = Number.parseFloat(normalized);
  return { empty: false, cleaned: normalized, number: Number.isFinite(n) && n >= 0 ? n : 0 };
}

export function formatEditableNumberText(cleaned) {
  if (cleaned === "") return "";
  const hasDot = cleaned.includes(".");
  let [intPart, fracPart] = cleaned.split(".");
  if (intPart === "") intPart = "0";
  intPart = intPart.replace(/^0+(?=\d)/, "");
  intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  if (!hasDot) return intPart;
  if (fracPart === undefined) return `${intPart}.`;
  return `${intPart}.${fracPart}`;
}

export function toInputValue(value) {
  if (!Number.isFinite(value) || value < 0) return "0.00";
  const normalized = value.toFixed(2);
  const parts = normalized.split(".");
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return parts.join(".");
}

function nonCommaIndex(text, caretPos) {
  let count = 0;
  for (let i = 0; i < Math.min(text.length, caretPos); i++) {
    if (text[i] !== ",") count += 1;
  }
  return count;
}

function caretPosFromNonCommaIndex(text, idx) {
  if (idx <= 0) return 0;
  let count = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== ",") count += 1;
    if (count >= idx) return i + 1;
  }
  return text.length;
}

export function setValuePreserveCaret(inputEl, formatted, oldText, oldCaret) {
  const idx = nonCommaIndex(oldText, oldCaret ?? oldText.length);
  inputEl.value = formatted;
  const pos = caretPosFromNonCommaIndex(inputEl.value, idx);
  try { inputEl.setSelectionRange(pos, pos); } catch { /* ignore */ }
}

export function selectAllSoon(inputEl) {
  setTimeout(() => {
    try { inputEl.setSelectionRange(0, inputEl.value.length); } catch { /* ignore */ }
  }, 0);
}

