// Local, vendored Twemoji flag SVGs.

const TWEMOJI_SVG_BASE = "./assets/twemoji/svg/";

const FLAG_SVG = {
  KRW: "1f1f0-1f1f7",
  USD: "1f1fa-1f1f8",
  CNY: "1f1e8-1f1f3",
  PHP: "1f1f5-1f1ed",
  TWD: "1f1f9-1f1fc",
  JPY: "1f1ef-1f1f5",
  VND: "1f1fb-1f1f3",
  THB: "1f1f9-1f1ed",
  EUR: "1f1ea-1f1fa",
  AUD: "1f1e6-1f1fa",
};

export function flagUrl(code) {
  const file = FLAG_SVG[code];
  return file ? `${TWEMOJI_SVG_BASE}${file}.svg` : "";
}

