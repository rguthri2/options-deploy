const API = "/api";

// Fixed hue order from the dataviz reference palette -- never cycled/reassigned.
// Light and dark are each their own selected steps (per the dataviz skill),
// not one palette auto-darkened -- these mirror the CSS custom properties in
// site.css's light/dark blocks. Presentation attributes inside SVG strings
// use these resolved hex values directly rather than var(--...) for
// cross-browser reliability, so charts re-render (not CSS-repaint) on toggle.
const PALETTE = {
  light: {
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    up: "#2a78d6", down: "#e34948",
    ink: "#0b0b0b", inkSecondary: "#52514e", inkMuted: "#898781",
    grid: "#e1e0d9", baseline: "#c3c2b7",
  },
  dark: {
    series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    up: "#3987e5", down: "#e66767",
    ink: "#ffffff", inkSecondary: "#c3c2b7", inkMuted: "#898781",
    grid: "#2c2c2a", baseline: "#383835",
  },
};

function isDarkMode() {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "dark") return true;
  if (attr === "light") return false;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function colors() {
  return isDarkMode() ? PALETTE.dark : PALETTE.light;
}

const HOME_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"];
const NEWS_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"];
const WATCHLIST_KEY = "rginvestor.watchlist";

// ---------------------------------------------------------------------------
// Small API helpers (public endpoints never redirect on 401; only used where
// we deliberately probe auth state, e.g. the portfolio panel).
// ---------------------------------------------------------------------------

async function getJSON(path) {
  const resp = await fetch(`${API}${path}`);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || `Request failed (HTTP ${resp.status}).`);
  return data;
}

function fmtMoney(value, opts = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: opts.decimals ?? 2 })}`;
}

function fmtCompact(value) {
  if (value === null || value === undefined) return "—";
  return Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function timeAgo(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

// ---------------------------------------------------------------------------
// Chart primitives (hand-rolled SVG per the dataviz skill's mark specs:
// 2px lines, rounded caps, >=8px end markers with a surface ring, thin bars
// with rounded data-ends, fixed categorical hue order, a legend for 2+ series).
// ---------------------------------------------------------------------------

function sparklineSVG(values, { width = 120, height = 36 } = {}) {
  if (!values || values.length < 2) return "";
  const c = colors();
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const pts = values.map((v, i) => [i * stepX, height - ((v - min) / span) * (height - 4) - 2]);
  const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const color = values[values.length - 1] >= values[0] ? c.up : c.down;
  const last = pts[pts.length - 1];
  return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="price trend">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3" fill="${color}" stroke="#fff" stroke-width="1.5" />
  </svg>`;
}

// ---------------------------------------------------------------------------
// Technical indicators -- plain time-series math over a closes[] array.
// Each returns an array the same length as the input; a period's warm-up
// window is `null` rather than 0, so overlay lines skip it instead of
// drawing a false flat run at the bottom of the chart.
// ---------------------------------------------------------------------------

function indicatorSMA(values, period) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function indicatorEMA(values, period) {
  const out = new Array(values.length).fill(null);
  const k = 2 / (period + 1);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    if (i === period - 1) {
      let sum = 0;
      for (let j = 0; j <= i; j++) sum += values[j];
      prev = sum / period;
      out[i] = prev;
    } else if (i >= period) {
      prev = values[i] * k + prev * (1 - k);
      out[i] = prev;
    }
  }
  return out;
}

function indicatorBollinger(values, period = 20, mult = 2) {
  const mid = indicatorSMA(values, period);
  const upper = new Array(values.length).fill(null);
  const lower = new Array(values.length).fill(null);
  for (let i = 0; i < values.length; i++) {
    if (mid[i] == null) continue;
    let sumSq = 0;
    for (let j = i - period + 1; j <= i; j++) sumSq += (values[j] - mid[i]) ** 2;
    const stdDev = Math.sqrt(sumSq / period);
    upper[i] = mid[i] + mult * stdDev;
    lower[i] = mid[i] - mult * stdDev;
  }
  return { mid, upper, lower };
}

function indicatorRSI(values, period = 14) {
  const out = new Array(values.length).fill(null);
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i < values.length; i++) {
    const change = values[i] - values[i - 1];
    const gain = Math.max(0, change);
    const loss = Math.max(0, -change);
    if (i < period) {
      avgGain += gain;
      avgLoss += loss;
    } else if (i === period) {
      avgGain = (avgGain + gain) / period;
      avgLoss = (avgLoss + loss) / period;
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
  }
  return out;
}

function indicatorMACD(values, fast = 12, slow = 26, signalPeriod = 9) {
  const emaFast = indicatorEMA(values, fast);
  const emaSlow = indicatorEMA(values, slow);
  const macdLine = values.map((_, i) => (emaFast[i] != null && emaSlow[i] != null ? emaFast[i] - emaSlow[i] : null));
  const firstValid = macdLine.findIndex((v) => v != null);
  const signalLine = new Array(values.length).fill(null);
  if (firstValid >= 0) {
    const compact = indicatorEMA(macdLine.slice(firstValid), signalPeriod);
    for (let i = 0; i < compact.length; i++) signalLine[firstValid + i] = compact[i];
  }
  const histogram = values.map((_, i) =>
    macdLine[i] != null && signalLine[i] != null ? macdLine[i] - signalLine[i] : null
  );
  return { macdLine, signalLine, histogram };
}

// ---------------------------------------------------------------------------
// Main price chart: line / area / candlesticks, with optional SMA/EMA/
// Bollinger overlays, a shared hover crosshair, and a legend for whichever
// overlays are active (the price series itself needs none -- it's the
// chart's obvious subject, per the "single series needs no legend" rule).
// ---------------------------------------------------------------------------

let _priceChartSeq = 0;

const OVERLAY_SPECS = [
  { key: "sma20", label: "SMA 20", colorIndex: 1 },
  { key: "sma50", label: "SMA 50", colorIndex: 2 },
  { key: "ema12", label: "EMA 12", colorIndex: 4 },
  { key: "ema26", label: "EMA 26", colorIndex: 6 },
];

function pathSegmentsFor(values, xFn, yFn) {
  // Splits a value series into separate path strings at each null run (an
  // indicator's warm-up window) so the line never draws a false segment
  // connecting across missing data.
  const segments = [];
  let current = "";
  for (let i = 0; i < values.length; i++) {
    if (values[i] == null) {
      if (current) segments.push(current);
      current = "";
      continue;
    }
    current += `${current ? "L" : "M"}${xFn(i).toFixed(1)},${yFn(values[i]).toFixed(1)}`;
  }
  if (current) segments.push(current);
  return segments;
}

function renderPriceChart(container, bars, { chartType = "line", overlays = {}, width = 640, height = 280 } = {}) {
  container.innerHTML = "";
  if (!bars || bars.length < 2) {
    container.innerHTML = `<div class="empty-note">Not enough data to chart.</div>`;
    return;
  }
  const c = colors();
  const id = `pc${_priceChartSeq++}`;
  const margin = { top: 16, right: 12, bottom: 24, left: 56 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;

  const closes = bars.map((b) => b.c);
  const sma20 = overlays.sma20 ? indicatorSMA(closes, 20) : null;
  const sma50 = overlays.sma50 ? indicatorSMA(closes, 50) : null;
  const ema12 = overlays.ema12 ? indicatorEMA(closes, 12) : null;
  const ema26 = overlays.ema26 ? indicatorEMA(closes, 26) : null;
  const bollinger = overlays.bollinger ? indicatorBollinger(closes, 20, 2) : null;
  const overlaySeries = { sma20, sma50, ema12, ema26 };

  const domainValues = [...closes];
  if (chartType === "candles") {
    for (const b of bars) domainValues.push(b.h, b.l);
  }
  for (const key of Object.keys(overlaySeries)) {
    if (overlaySeries[key]) domainValues.push(...overlaySeries[key].filter((v) => v != null));
  }
  if (bollinger) domainValues.push(...bollinger.upper.filter((v) => v != null), ...bollinger.lower.filter((v) => v != null));

  let min = Math.min(...domainValues);
  let max = Math.max(...domainValues);
  if (min === max) { min -= 1; max += 1; }
  const pad = (max - min) * 0.08;
  min -= pad;
  max += pad;

  const x = (i) => margin.left + (i / (bars.length - 1)) * innerW;
  const y = (v) => margin.top + innerH - ((v - min) / (max - min)) * innerH;

  const trendColor = closes[closes.length - 1] >= closes[0] ? c.up : c.down;

  let gridLines = "";
  for (let g = 0; g <= 3; g++) {
    const v = min + ((max - min) * g) / 3;
    const yy = y(v).toFixed(1);
    gridLines += `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy}" y2="${yy}" stroke="${c.grid}" stroke-width="1" />`;
    gridLines += `<text x="${margin.left - 8}" y="${yy}" text-anchor="end" dominant-baseline="middle" font-size="10" fill="${c.inkMuted}">$${v.toFixed(2)}</text>`;
  }

  let priceMarks = "";
  if (chartType === "candles") {
    const bandW = innerW / bars.length;
    const bodyW = Math.max(2, Math.min(10, bandW * 0.6));
    bars.forEach((b, i) => {
      const cx = x(i);
      const up = b.c >= b.o;
      const color = up ? c.up : c.down;
      priceMarks += `<line x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${y(b.h).toFixed(1)}" y2="${y(b.l).toFixed(1)}" stroke="${color}" stroke-width="1" />`;
      const bodyTop = y(Math.max(b.o, b.c));
      const bodyBottom = y(Math.min(b.o, b.c));
      priceMarks += `<rect x="${(cx - bodyW / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${bodyW.toFixed(1)}" height="${Math.max(1, bodyBottom - bodyTop).toFixed(1)}" fill="${color}" />`;
    });
  } else {
    const linePath = bars.map((b, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(b.c).toFixed(1)}`).join(" ");
    if (chartType === "area") {
      const areaPath = `${linePath} L${x(bars.length - 1).toFixed(1)},${(margin.top + innerH).toFixed(1)} L${x(0).toFixed(1)},${(margin.top + innerH).toFixed(1)} Z`;
      priceMarks += `<path d="${areaPath}" fill="${trendColor}" opacity="0.10" stroke="none" />`;
    }
    priceMarks += `<path d="${linePath}" fill="none" stroke="${trendColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />`;
    const lastY = y(closes[closes.length - 1]);
    priceMarks += `<circle cx="${x(bars.length - 1).toFixed(1)}" cy="${lastY.toFixed(1)}" r="4" fill="${trendColor}" stroke="#fff" stroke-width="2" />`;
  }

  let overlayMarks = "";
  let legendItems = "";
  if (bollinger) {
    const upperSegs = pathSegmentsFor(bollinger.upper, x, y);
    const lowerSegs = pathSegmentsFor(bollinger.lower, x, y);
    // A light channel fill between the bands, band-by-band (upper/lower
    // stay aligned index-for-index since both come from the same SMA).
    for (let s = 0; s < upperSegs.length; s++) {
      overlayMarks += `<path d="${upperSegs[s]}" fill="none" stroke="${c.inkMuted}" stroke-width="1" stroke-dasharray="3,3" opacity="0.8" />`;
    }
    for (let s = 0; s < lowerSegs.length; s++) {
      overlayMarks += `<path d="${lowerSegs[s]}" fill="none" stroke="${c.inkMuted}" stroke-width="1" stroke-dasharray="3,3" opacity="0.8" />`;
    }
    legendItems += `<span class="legend-item"><span class="legend-swatch" style="background:${c.inkMuted}"></span>Bollinger (20, 2)</span>`;
  }
  for (const spec of OVERLAY_SPECS) {
    const series = overlaySeries[spec.key];
    if (!series) continue;
    const color = c.series[spec.colorIndex % c.series.length];
    for (const seg of pathSegmentsFor(series, x, y)) {
      overlayMarks += `<path d="${seg}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" />`;
    }
    legendItems += `<span class="legend-item"><span class="legend-swatch" style="background:${color}"></span>${spec.label}</span>`;
  }

  container.innerHTML = `
    <div style="position:relative">
      <svg viewBox="0 0 ${width} ${height}" id="${id}" role="img" aria-label="price chart">
        ${gridLines}
        ${priceMarks}
        ${overlayMarks}
        <g id="${id}-hover" style="display:none">
          <line id="${id}-crosshair" x1="0" x2="0" y1="${margin.top}" y2="${margin.top + innerH}" stroke="${c.baseline}" stroke-width="1" />
          <circle id="${id}-dot" r="4" fill="${trendColor}" stroke="#fff" stroke-width="2" />
        </g>
        <rect id="${id}-capture" x="${margin.left}" y="${margin.top}" width="${innerW}" height="${innerH}" fill="transparent" />
      </svg>
      <div id="${id}-tip" style="position:absolute; display:none; pointer-events:none; background:var(--text); color:#fff; font-size:11px; padding:4px 8px; border-radius:6px; white-space:nowrap; transform:translate(-50%,-115%); line-height:1.5;"></div>
    </div>
    ${legendItems ? `<div class="legend-row">${legendItems}</div>` : ""}`;

  const svg = container.querySelector(`#${id}`);
  const capture = container.querySelector(`#${id}-capture`);
  const hoverGroup = container.querySelector(`#${id}-hover`);
  const crosshair = container.querySelector(`#${id}-crosshair`);
  const dot = container.querySelector(`#${id}-dot`);
  const tip = container.querySelector(`#${id}-tip`);

  function pointerToSvgX(evt) {
    const rect = svg.getBoundingClientRect();
    const clientX = evt.touches ? evt.touches[0].clientX : evt.clientX;
    return ((clientX - rect.left) / rect.width) * width;
  }

  function onMove(evt) {
    const svgX = pointerToSvgX(evt);
    let idx = Math.round(((svgX - margin.left) / innerW) * (bars.length - 1));
    idx = Math.max(0, Math.min(bars.length - 1, idx));
    const b = bars[idx];
    const px = x(idx);
    const py = y(b.c);
    crosshair.setAttribute("x1", px.toFixed(1));
    crosshair.setAttribute("x2", px.toFixed(1));
    dot.setAttribute("cx", px.toFixed(1));
    dot.setAttribute("cy", py.toFixed(1));
    hoverGroup.style.display = "block";
    const rect = svg.getBoundingClientRect();
    tip.style.left = `${(px / width) * rect.width}px`;
    tip.style.top = `${(py / height) * rect.height}px`;
    tip.style.display = "block";
    const dt = new Date(b.t);
    const dateLabel = Number.isNaN(dt.getTime()) ? "" : dt.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    const lines = [dateLabel];
    if (chartType === "candles") {
      lines.push(`O ${b.o.toFixed(2)}  H ${b.h.toFixed(2)}  L ${b.l.toFixed(2)}  C ${b.c.toFixed(2)}`);
    } else {
      lines.push(`$${b.c.toFixed(2)}`);
    }
    for (const spec of OVERLAY_SPECS) {
      const series = overlaySeries[spec.key];
      if (series && series[idx] != null) lines.push(`${spec.label}: $${series[idx].toFixed(2)}`);
    }
    tip.innerHTML = lines.join("<br>");
  }

  capture.addEventListener("mousemove", onMove);
  capture.addEventListener("touchmove", onMove, { passive: true });
  capture.addEventListener("mouseleave", () => { hoverGroup.style.display = "none"; tip.style.display = "none"; });
}

// --- Sub-panels: volume, RSI, MACD -------------------------------------------

function renderVolumeChart(container, bars, { width = 640, height = 90 } = {}) {
  container.innerHTML = "";
  const c = colors();
  const margin = { top: 6, right: 12, bottom: 6, left: 56 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const maxVol = Math.max(...bars.map((b) => b.v), 1);
  const bandW = innerW / bars.length;
  const barW = Math.max(1, Math.min(10, bandW * 0.6));
  const x = (i) => margin.left + (i / (bars.length - 1)) * innerW;

  let bars_svg = "";
  bars.forEach((b, i) => {
    const h = (b.v / maxVol) * innerH;
    const color = b.c >= b.o ? c.up : c.down;
    bars_svg += `<rect x="${(x(i) - barW / 2).toFixed(1)}" y="${(margin.top + innerH - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" fill="${color}" opacity="0.6" />`;
  });

  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="volume">
    <text x="${margin.left - 8}" y="${margin.top + 4}" text-anchor="end" font-size="9" fill="${c.inkMuted}">${fmtCompact(maxVol)}</text>
    ${bars_svg}
  </svg>`;
}

function renderRSIChart(container, closes, { width = 640, height = 110 } = {}) {
  container.innerHTML = "";
  const rsi = indicatorRSI(closes, 14);
  if (!rsi.some((v) => v != null)) {
    container.innerHTML = `<div class="empty-note">Not enough bars in this range for RSI (needs 15+) — try a longer range.</div>`;
    return;
  }
  const c = colors();
  const margin = { top: 10, right: 12, bottom: 10, left: 56 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const x = (i) => margin.left + (i / (closes.length - 1)) * innerW;
  const y = (v) => margin.top + innerH - (v / 100) * innerH;
  const rsiColor = c.series[6];

  let refLines = "";
  for (const [level, label] of [[70, "70"], [30, "30"]]) {
    const yy = y(level).toFixed(1);
    refLines += `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy}" y2="${yy}" stroke="${c.grid}" stroke-width="1" stroke-dasharray="3,3" />`;
    refLines += `<text x="${margin.left - 8}" y="${yy}" text-anchor="end" dominant-baseline="middle" font-size="9" fill="${c.inkMuted}">${label}</text>`;
  }

  const segments = pathSegmentsFor(rsi, x, y);
  const lines = segments.map((seg) => `<path d="${seg}" fill="none" stroke="${rsiColor}" stroke-width="1.5" />`).join("");

  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="RSI">${refLines}${lines}</svg>`;
}

function renderMACDChart(container, closes, { width = 640, height = 130 } = {}) {
  container.innerHTML = "";
  const { macdLine, signalLine, histogram } = indicatorMACD(closes);
  if (!signalLine.some((v) => v != null)) {
    // MACD needs ~35+ bars before it can produce a single value (26 for the
    // slow EMA, then 9 more for the signal line's own EMA) -- a short range
    // like 1D/5D legitimately can't feed it, so say so instead of a blank panel.
    container.innerHTML = `<div class="empty-note">Not enough bars in this range for MACD (needs ~35+) — try 1M or 1Y.</div>`;
    return;
  }
  const c = colors();
  const margin = { top: 10, right: 12, bottom: 10, left: 56 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const values = [...macdLine, ...signalLine, ...histogram].filter((v) => v != null);
  let min = Math.min(0, ...values);
  let max = Math.max(0, ...values);
  if (min === max) { min -= 1; max += 1; }
  const pad = (max - min) * 0.1;
  min -= pad;
  max += pad;

  const x = (i) => margin.left + (i / (closes.length - 1)) * innerW;
  const y = (v) => margin.top + innerH - ((v - min) / (max - min)) * innerH;
  const zeroY = y(0).toFixed(1);

  const bandW = innerW / closes.length;
  const barW = Math.max(1, Math.min(8, bandW * 0.6));
  let histBars = "";
  histogram.forEach((v, i) => {
    if (v == null) return;
    const color = v >= 0 ? c.up : c.down;
    const yy = y(v);
    const top = Math.min(yy, y(0));
    histBars += `<rect x="${(x(i) - barW / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(1, Math.abs(yy - y(0))).toFixed(1)}" fill="${color}" opacity="0.5" />`;
  });

  const macdColor = c.series[0];
  const signalColor = c.series[1];
  const macdPath = pathSegmentsFor(macdLine, x, y).map((seg) => `<path d="${seg}" fill="none" stroke="${macdColor}" stroke-width="1.5" />`).join("");
  const signalPath = pathSegmentsFor(signalLine, x, y).map((seg) => `<path d="${seg}" fill="none" stroke="${signalColor}" stroke-width="1.5" />`).join("");

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="MACD">
      <line x1="${margin.left}" x2="${width - margin.right}" y1="${zeroY}" y2="${zeroY}" stroke="${c.baseline}" stroke-width="1" />
      ${histBars}
      ${macdPath}
      ${signalPath}
    </svg>
    <div class="legend-row">
      <span class="legend-item"><span class="legend-swatch" style="background:${macdColor}"></span>MACD</span>
      <span class="legend-item"><span class="legend-swatch" style="background:${signalColor}"></span>Signal</span>
    </div>`;
}

function renderDonutChart(container, segments, { width = 260, height = 260 } = {}) {
  container.innerHTML = "";
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  if (!total) {
    container.innerHTML = `<div class="empty-note">No positions to show.</div>`;
    return;
  }
  const c = colors();
  const cx = width / 2;
  const cy = height / 2;
  const rOuter = Math.min(width, height) / 2 - 8;
  const rInner = rOuter * 0.62;
  let angle = -Math.PI / 2;
  const gapRad = (2 * Math.PI) * (0.006); // ~2px surface gap between segments

  let paths = "";
  segments.forEach((seg, i) => {
    const frac = seg.value / total;
    const sweep = frac * 2 * Math.PI - gapRad;
    const a0 = angle + gapRad / 2;
    const a1 = a0 + Math.max(0, sweep);
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const x0o = cx + rOuter * Math.cos(a0), y0o = cy + rOuter * Math.sin(a0);
    const x1o = cx + rOuter * Math.cos(a1), y1o = cy + rOuter * Math.sin(a1);
    const x1i = cx + rInner * Math.cos(a1), y1i = cy + rInner * Math.sin(a1);
    const x0i = cx + rInner * Math.cos(a0), y0i = cy + rInner * Math.sin(a0);
    const color = c.series[i % c.series.length];
    paths += `<path d="M${x0o.toFixed(2)},${y0o.toFixed(2)} A${rOuter},${rOuter} 0 ${large} 1 ${x1o.toFixed(2)},${y1o.toFixed(2)} ` +
      `L${x1i.toFixed(2)},${y1i.toFixed(2)} A${rInner},${rInner} 0 ${large} 0 ${x0i.toFixed(2)},${y0i.toFixed(2)} Z" fill="${color}">` +
      `<title>${seg.label}: ${fmtMoney(seg.value)} (${(frac * 100).toFixed(1)}%)</title></path>`;
    angle += frac * 2 * Math.PI;
  });

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="portfolio composition">
      ${paths}
      <text x="${cx}" y="${cy - 6}" text-anchor="middle" font-size="13" fill="${c.inkSecondary}">Total</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="17" font-weight="800" fill="${c.ink}">${fmtCompact(total)}</text>
    </svg>
    <div class="legend-row">
      ${segments.map((s, i) => `<span class="legend-item"><span class="legend-swatch" style="background:${c.series[i % c.series.length]}"></span>${s.label} &middot; ${fmtMoney(s.value, { decimals: 0 })}</span>`).join("")}
    </div>`;
}

function renderBarChart(container, items, { width = 640, height = 220 } = {}) {
  // items: [{label, value}] -- value's sign picks the diverging pole (blue = up, red = down).
  container.innerHTML = "";
  if (!items || !items.length) {
    container.innerHTML = `<div class="empty-note">No data to show.</div>`;
    return;
  }
  const c = colors();
  const margin = { top: 16, right: 12, bottom: 26, left: 12 };
  const innerW = width - margin.left - margin.right;
  const innerH = height - margin.top - margin.bottom;
  const maxAbs = Math.max(...items.map((it) => Math.abs(it.value)), 1);
  const baselineY = margin.top + innerH / 2;
  const bandW = innerW / items.length;
  const barW = Math.min(28, bandW * 0.5);

  let bars = "";
  items.forEach((it, i) => {
    const cx = margin.left + bandW * (i + 0.5);
    const h = (Math.abs(it.value) / maxAbs) * (innerH / 2 - 8);
    const color = it.value >= 0 ? c.up : c.down;
    const y = it.value >= 0 ? baselineY - h : baselineY;
    const rx = 4;
    bars += `<rect x="${(cx - barW / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" rx="${rx}" fill="${color}">` +
      `<title>${it.label}: ${fmtMoney(it.value)}</title></rect>`;
    const labelY = it.value >= 0 ? y - 6 : y + h + 14;
    bars += `<text x="${cx.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="middle" font-size="10" fill="${c.inkSecondary}">${fmtCompact(it.value)}</text>`;
    bars += `<text x="${cx.toFixed(1)}" y="${(margin.top + innerH + 16).toFixed(1)}" text-anchor="middle" font-size="10" fill="${c.inkMuted}">${it.label}</text>`;
  });

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="monthly profit and loss">
      <line x1="${margin.left}" x2="${width - margin.right}" y1="${baselineY}" y2="${baselineY}" stroke="${c.baseline}" stroke-width="1" />
      ${bars}
    </svg>
    <div class="legend-row">
      <span class="legend-item"><span class="legend-swatch" style="background:${c.up}"></span>Gain</span>
      <span class="legend-item"><span class="legend-swatch" style="background:${c.down}"></span>Loss</span>
    </div>`;
}

// ---------------------------------------------------------------------------
// Nav / tabs
// ---------------------------------------------------------------------------

const tabButtons = Array.from(document.querySelectorAll(".tab-btn"));
const panels = Array.from(document.querySelectorAll(".tab-panel"));
const bnavButtons = Array.from(document.querySelectorAll(".bnav-btn[data-tab]"));

function activateTab(name) {
  tabButtons.forEach((b) => b.classList.toggle("is-active", b.dataset.tab === name));
  bnavButtons.forEach((b) => b.classList.toggle("is-active", b.dataset.tab === name));
  panels.forEach((p) => p.classList.toggle("is-active", p.dataset.panel === name));
  window.location.hash = name;
  onTabShown(name);
}

tabButtons.forEach((btn) => btn.addEventListener("click", () => activateTab(btn.dataset.tab)));
document.querySelectorAll("[data-goto]").forEach((btn) => btn.addEventListener("click", () => activateTab(btn.dataset.goto)));

const _tabInitDone = new Set();
function onTabShown(name) {
  if (_tabInitDone.has(name)) return;
  _tabInitDone.add(name);
  if (name === "news") loadNews();
  if (name === "watchlist") loadWatchlist();
  if (name === "portfolio") loadPortfolio();
  if (name === "scanner") {
    loadScannerStrategies();
    runStockFinder();
  }
  if (name === "level2") loadLevel2("AAPL");
}

// Re-runs whatever the currently visible tab needs, bypassing the
// "already loaded" guard -- used after a theme change so charts redraw in
// the new palette immediately, and incidentally keeps data fresh too.
function refreshActiveTab() {
  const active = panels.find((p) => p.classList.contains("is-active"));
  const name = active && active.dataset.panel;
  if (name === "home") loadHome();
  else if (name === "news") loadNews();
  else if (name === "watchlist") loadWatchlist();
  else if (name === "portfolio") loadPortfolio();
  else if (name === "research" && currentResearchSymbol) loadResearch(currentResearchSymbol, currentResearchRange);
  // scanner and level2 don't use JS-drawn SVG charts (CSS-themed only), so
  // there's nothing to redraw there on a theme flip.
}

// --- Bottom mobile nav + "More" sheet ---------------------------------------

const moreSheet = document.getElementById("moreSheet");

function openMoreSheet() {
  moreSheet.hidden = false;
}
function closeMoreSheet() {
  moreSheet.hidden = true;
}

document.querySelectorAll(".bnav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.tab === "more") {
      openMoreSheet();
      return;
    }
    if (btn.dataset.tab) activateTab(btn.dataset.tab);
    closeMoreSheet();
  });
});
document.getElementById("moreSheetBackdrop").addEventListener("click", closeMoreSheet);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !moreSheet.hidden) closeMoreSheet();
});

// --- Theme toggle ------------------------------------------------------------

const THEME_KEY = "rginvestor.theme";

function applyStoredTheme() {
  let stored = null;
  try {
    stored = localStorage.getItem(THEME_KEY);
  } catch {
    // localStorage unavailable -- falls back to the system preference.
  }
  if (stored === "dark" || stored === "light") {
    document.documentElement.setAttribute("data-theme", stored);
  }
}

document.getElementById("themeToggle").addEventListener("click", () => {
  const next = isDarkMode() ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    // per-viewer convenience only -- fine if it doesn't persist
  }
  refreshActiveTab();
});

applyStoredTheme();

// --- Toasts --------------------------------------------------------------

function showToast(message) {
  const stack = document.getElementById("toastStack");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => {
    el.classList.add("is-leaving");
    setTimeout(() => el.remove(), 200);
  }, 2200);
}

// ---------------------------------------------------------------------------
// Skeleton loading placeholders
// ---------------------------------------------------------------------------

function trendCardSkeleton() {
  return `<div class="trend-card skel-card" aria-hidden="true">
    <div class="trend-top">
      <div><div class="skel skel-line w-40" style="margin-bottom:6px"></div><div class="skel skel-line w-60" style="height:8px"></div></div>
      <div class="skel skel-line w-40" style="height:16px"></div>
    </div>
    <div class="skel skel-spark"></div>
  </div>`;
}

function newsCardSkeleton() {
  return `<div class="news-card skel-card" aria-hidden="true">
    <div class="skel skel-line w-40" style="height:16px;border-radius:999px"></div>
    <div class="skel skel-line w-90"></div>
    <div class="skel skel-line w-60"></div>
  </div>`;
}

function listRowSkeleton(cols) {
  return `<div class="list-row" aria-hidden="true">${Array.from({ length: cols }, () => `<span class="skel skel-line w-60"></span>`).join("")}</div>`;
}

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------

async function loadHome() {
  const grid = document.getElementById("trendGrid");
  grid.innerHTML = HOME_TICKERS.map(trendCardSkeleton).join("");
  const cards = await Promise.all(
    HOME_TICKERS.map(async (symbol) => {
      try {
        const [quote, history] = await Promise.all([
          getJSON(`/public/quote?symbol=${symbol}`),
          getJSON(`/public/history?symbol=${symbol}&range=1D`),
        ]);
        const values = history.points.map((p) => p.c);
        const up = quote.change >= 0;
        return `<div class="trend-card" data-symbol="${symbol}">
          <div class="trend-top">
            <div><div class="trend-symbol">${symbol}</div><div class="trend-name">${quote.name}</div></div>
            <div><div class="trend-price">${fmtMoney(quote.price)}</div><div class="trend-change ${up ? "up" : "down"}">${up ? "+" : ""}${quote.change_percent.toFixed(2)}%</div></div>
          </div>
          <div class="trend-spark">${sparklineSVG(values)}</div>
        </div>`;
      } catch (err) {
        return `<div class="trend-card"><div class="trend-symbol">${symbol}</div><div class="error-msg">${err.message}</div></div>`;
      }
    })
  );
  grid.innerHTML = cards.join("");
  grid.querySelectorAll("[data-symbol]").forEach((card) => {
    card.addEventListener("click", () => {
      activateTab("research");
      document.getElementById("researchInput").value = card.dataset.symbol;
      document.getElementById("researchForm").dispatchEvent(new Event("submit"));
    });
  });

  try {
    const news = await getJSON(`/public/news?symbols=${NEWS_TICKERS.join(",")}`);
    document.getElementById("homeNewsGrid").innerHTML = renderNewsCards(news.items.slice(0, 4));
  } catch (err) {
    document.getElementById("homeNewsGrid").innerHTML = `<div class="error-msg">${err.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// News
// ---------------------------------------------------------------------------

function renderNewsCards(items) {
  if (!items.length) return `<div class="empty-note">No news right now.</div>`;
  return items
    .map(
      (item) => `<div class="news-card">
        <span class="news-tag">${item.symbol}</span>
        <div class="news-title">${item.link ? `<a href="${item.link}" target="_blank" rel="noopener">${item.title}</a>` : item.title}</div>
        <div class="news-meta">${item.publisher}${item.publisher ? " &middot; " : ""}${timeAgo(item.published_at)}</div>
      </div>`
    )
    .join("");
}

async function loadNews() {
  const grid = document.getElementById("newsGrid");
  grid.innerHTML = Array.from({ length: 4 }, newsCardSkeleton).join("");
  try {
    const news = await getJSON(`/public/news?symbols=${NEWS_TICKERS.join(",")}`);
    grid.innerHTML = renderNewsCards(news.items);
  } catch (err) {
    grid.innerHTML = `<div class="error-msg">${err.message}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Watchlist (client-side only, localStorage)
// ---------------------------------------------------------------------------

function getWatchlist() {
  try {
    return JSON.parse(localStorage.getItem(WATCHLIST_KEY) || "[]");
  } catch {
    return [];
  }
}

function setWatchlist(list) {
  try {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(list));
  } catch {
    // localStorage unavailable (private mode, etc.) -- watchlist just won't persist.
  }
}

async function loadWatchlist() {
  const list = getWatchlist();
  const table = document.getElementById("watchlistTable");
  if (!list.length) {
    table.innerHTML = `<div class="empty-note">Your watchlist is empty. Add a ticker above.</div>`;
    return;
  }
  table.innerHTML =
    `<div class="list-row list-head"><span>Symbol</span><span>Price</span><span>Change</span><span class="list-cell-spark">Trend</span><span></span></div>` +
    list
      .map(
        (s) => `<div class="list-row is-clickable" data-row="${s}">
        <span>${s}</span><span class="skel skel-line w-60"></span><span class="skel skel-line w-40"></span>
        <span class="list-cell-spark skel skel-spark" style="height:24px"></span>
        <button class="list-remove" data-remove="${s}" title="Remove">&times;</button>
      </div>`
      )
      .join("");

  table.querySelectorAll(".list-row[data-row]").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("[data-remove]")) return;
      const symbol = row.dataset.row;
      activateTab("research");
      document.getElementById("researchInput").value = symbol;
      currentResearchSymbol = symbol;
      loadResearch(symbol, currentResearchRange);
    });
  });

  table.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      setWatchlist(getWatchlist().filter((s) => s !== btn.dataset.remove));
      showToast(`Removed ${btn.dataset.remove} from watchlist`);
      loadWatchlist();
    });
  });

  for (const symbol of list) {
    try {
      const [quote, history] = await Promise.all([
        getJSON(`/public/quote?symbol=${symbol}`),
        getJSON(`/public/history?symbol=${symbol}&range=1D`),
      ]);
      const row = table.querySelector(`[data-row="${symbol}"]`);
      if (!row) continue;
      const up = quote.change >= 0;
      const cells = row.querySelectorAll("span");
      cells[1].textContent = fmtMoney(quote.price);
      cells[1].classList.remove("skel", "skel-line", "w-60");
      cells[2].innerHTML = `<span class="trend-change ${up ? "up" : "down"}">${up ? "+" : ""}${quote.change_percent.toFixed(2)}%</span>`;
      cells[2].classList.remove("skel", "skel-line", "w-40");
      cells[3].innerHTML = sparklineSVG(history.points.map((p) => p.c), { width: 90, height: 28 });
      cells[3].classList.remove("skel", "skel-spark");
    } catch (err) {
      const row = table.querySelector(`[data-row="${symbol}"]`);
      if (row) {
        const cell = row.querySelectorAll("span")[1];
        cell.textContent = "error";
        cell.classList.remove("skel", "skel-line", "w-60");
      }
    }
  }
}

document.getElementById("watchlistForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("watchlistInput");
  const symbol = input.value.trim().toUpperCase();
  input.value = "";
  if (!symbol) return;
  const list = getWatchlist();
  if (!list.includes(symbol)) {
    list.push(symbol);
    setWatchlist(list);
    showToast(`Added ${symbol} to watchlist`);
  }
  loadWatchlist();
});

// ---------------------------------------------------------------------------
// Portfolio ("position UI") -- real data if logged into the Trading module,
// otherwise a clearly-labeled sample preview of the same layout.
// ---------------------------------------------------------------------------

const SAMPLE_PORTFOLIO = [
  { label: "AAPL", value: 82400 },
  { label: "MSFT", value: 61200 },
  { label: "NVDA", value: 44500 },
  { label: "TSLA", value: 28900 },
  { label: "SPY", value: 17211.21 },
];
const SAMPLE_PROFIT = [
  { label: "Apr", value: 4200 }, { label: "May", value: -1800 }, { label: "Jun", value: 6100 },
  { label: "Jul", value: 3300 }, { label: "Aug", value: -900 }, { label: "Sep", value: 5200 },
];

async function loadPortfolio() {
  const sub = document.getElementById("portfolioSub");
  const positionsCard = document.getElementById("portfolioPositions");
  document.getElementById("portfolioDonut").innerHTML = `<div class="skel" style="width:100%;aspect-ratio:1;border-radius:999px;max-width:260px;margin:0 auto"></div>`;
  document.getElementById("portfolioBar").innerHTML = `<div class="skel" style="width:100%;height:180px"></div>`;
  positionsCard.innerHTML = listRowSkeleton(5) + listRowSkeleton(5) + listRowSkeleton(5);
  try {
    const me = await fetch(`${API}/auth/me`);
    if (me.ok) {
      const account = await getJSON("/account");
      sub.textContent = "Your live account (Trading module).";
      document.getElementById("portfolioTotal").textContent = fmtMoney(account.portfolio_value);
      const segments = account.positions
        .filter((p) => p.market_value > 0)
        .map((p) => ({ label: p.symbol, value: p.market_value }));
      renderDonutChart(document.getElementById("portfolioDonut"), segments.length ? segments : [{ label: "Cash", value: account.cash_balance }]);

      const plItems = account.positions.map((p) => ({ label: p.symbol, value: p.unrealized_pl }));
      document.querySelectorAll(".chart-card .card-title")[1].textContent = "Position P/L (unrealized)";
      renderBarChart(document.getElementById("portfolioBar"), plItems);

      positionsCard.innerHTML =
        `<div class="list-row list-head" style="grid-template-columns: 1fr 1fr 1fr 1fr 1fr;"><span>Symbol</span><span>Qty</span><span>Avg cost</span><span>Current</span><span>Unrealized P/L</span></div>` +
        (account.positions.length
          ? account.positions
              .map(
                (p) => `<div class="list-row" style="grid-template-columns: 1fr 1fr 1fr 1fr 1fr;">
                <span>${p.symbol}</span><span>${p.quantity}</span><span>${fmtMoney(p.avg_cost)}</span>
                <span>${fmtMoney(p.current_price)}</span><span class="${p.unrealized_pl >= 0 ? "trend-change up" : "trend-change down"}">${fmtMoney(p.unrealized_pl)}</span>
              </div>`
              )
              .join("")
          : `<div class="empty-note">No open positions.</div>`);
      return;
    }
  } catch {
    // fall through to sample view
  }
  sub.textContent = "Sample data — log in to the Trading module to see your real account.";
  document.getElementById("portfolioTotal").textContent = fmtMoney(SAMPLE_PORTFOLIO.reduce((s, x) => s + x.value, 0));
  renderDonutChart(document.getElementById("portfolioDonut"), SAMPLE_PORTFOLIO);
  document.querySelectorAll(".chart-card .card-title")[1].textContent = "Profit statistics (sample)";
  renderBarChart(document.getElementById("portfolioBar"), SAMPLE_PROFIT);
  positionsCard.innerHTML = `<div class="empty-note">Log in to the <a href="trading.html">Trading module</a> to see your real positions here.</div>`;
}

// ---------------------------------------------------------------------------
// Research
// ---------------------------------------------------------------------------

let currentResearchSymbol = null;
let currentResearchRange = "1D";
let currentResearchBars = null;
let currentChartType = "line";
const currentIndicators = { sma20: false, sma50: false, ema12: false, ema26: false, bollinger: false, volume: false, rsi: false, macd: false };

function renderResearchCharts() {
  if (!currentResearchBars) return;
  const bars = currentResearchBars;
  const closes = bars.map((b) => b.c);

  renderPriceChart(document.getElementById("researchChart"), bars, {
    chartType: currentChartType,
    overlays: currentIndicators,
  });

  const volumeWrap = document.getElementById("volumeChartWrap");
  volumeWrap.hidden = !currentIndicators.volume;
  if (currentIndicators.volume) renderVolumeChart(document.getElementById("volumeChart"), bars);

  const rsiWrap = document.getElementById("rsiChartWrap");
  rsiWrap.hidden = !currentIndicators.rsi;
  if (currentIndicators.rsi) renderRSIChart(document.getElementById("rsiChart"), closes);

  const macdWrap = document.getElementById("macdChartWrap");
  macdWrap.hidden = !currentIndicators.macd;
  if (currentIndicators.macd) renderMACDChart(document.getElementById("macdChart"), closes);
}

async function loadResearch(symbol, range) {
  const status = document.getElementById("researchStatus");
  const card = document.getElementById("researchCard");
  status.textContent = "Loading…";
  try {
    const [quote, history] = await Promise.all([
      getJSON(`/public/quote?symbol=${symbol}`),
      getJSON(`/public/history?symbol=${symbol}&range=${range}`),
    ]);
    status.textContent = "";
    card.hidden = false;
    document.getElementById("researchSymbol").textContent = quote.symbol;
    document.getElementById("researchName").textContent = quote.name;
    document.getElementById("researchPrice").textContent = fmtMoney(quote.price);
    const up = quote.change >= 0;
    const changeEl = document.getElementById("researchChange");
    changeEl.textContent = `${up ? "+" : ""}${fmtMoney(quote.change)} (${up ? "+" : ""}${quote.change_percent.toFixed(2)}%)`;
    changeEl.className = `research-change ${up ? "up" : "down"}`;

    currentResearchBars = history.points;
    renderResearchCharts();

    document.getElementById("researchStats").innerHTML = [
      ["Previous close", fmtMoney(quote.previous_close)],
      ["Day high", fmtMoney(quote.day_high)],
      ["Day low", fmtMoney(quote.day_low)],
      ["Volume", fmtCompact(quote.volume)],
      ["Market cap", quote.market_cap ? fmtCompact(quote.market_cap) : "—"],
    ]
      .map(([label, value]) => `<div><div class="stat-label">${label}</div><div class="stat-value">${value}</div></div>`)
      .join("");
  } catch (err) {
    status.textContent = err.message;
    card.hidden = true;
    currentResearchBars = null;
  }
}

document.getElementById("researchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const symbol = document.getElementById("researchInput").value.trim().toUpperCase();
  if (!symbol) return;
  currentResearchSymbol = symbol;
  loadResearch(symbol, currentResearchRange);
});

document.getElementById("rangeTabs").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-range]");
  if (!btn || !currentResearchSymbol) return;
  currentResearchRange = btn.dataset.range;
  document.querySelectorAll("#rangeTabs .range-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
  loadResearch(currentResearchSymbol, currentResearchRange);
});

document.getElementById("chartTypeTabs").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-chart-type]");
  if (!btn) return;
  currentChartType = btn.dataset.chartType;
  document.querySelectorAll("#chartTypeTabs .range-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
  renderResearchCharts();
});

document.getElementById("indicatorToggles").addEventListener("change", (e) => {
  const input = e.target.closest("[data-indicator]");
  if (!input) return;
  currentIndicators[input.dataset.indicator] = input.checked;
  renderResearchCharts();
});

// ---------------------------------------------------------------------------
// Stock finder -- criteria-based screener (price, volume, % change, market
// cap) backed by /api/public/screen-stocks. Independent of the options
// scanner below, but its results can be pushed into that ticker list.
// ---------------------------------------------------------------------------

let lastFoundSymbols = [];

function stockFinderRow(stock) {
  const up = stock.change_percent >= 0;
  return `<div class="list-row" style="grid-template-columns: 1fr 1fr 1fr 1fr 1fr;">
    <span>${stock.symbol}</span>
    <span>${fmtMoney(stock.price)}</span>
    <span class="${up ? "trend-change up" : "trend-change down"}">${up ? "+" : ""}${stock.change_percent.toFixed(2)}%</span>
    <span>${fmtCompact(stock.volume)}</span>
    <span>${stock.market_cap ? fmtCompact(stock.market_cap) : "—"}</span>
  </div>`;
}

async function runStockFinder() {
  const status = document.getElementById("stockFinderStatus");
  const results = document.getElementById("stockFinderResults");
  const btn = document.getElementById("fFindBtn");
  const minMarketCapB = parseFloat(document.getElementById("fMinMarketCap").value) || 0;

  const params = new URLSearchParams({
    min_price: document.getElementById("fMinPrice").value || "0",
    min_volume: document.getElementById("fMinVolume").value || "0",
    min_change_pct: document.getElementById("fMinChange").value || "0",
    direction: document.getElementById("fDirection").value,
    min_market_cap: String(minMarketCapB * 1e9),
    limit: "25",
  });
  const maxPrice = document.getElementById("fMaxPrice").value;
  if (maxPrice) params.set("max_price", maxPrice);

  btn.disabled = true;
  status.textContent = "Finding stocks…";
  results.innerHTML = listRowSkeleton(5) + listRowSkeleton(5) + listRowSkeleton(5);
  try {
    const body = await getJSON(`/public/screen-stocks?${params.toString()}`);
    lastFoundSymbols = body.stocks.map((s) => s.symbol);
    if (!body.stocks.length) {
      status.textContent = "No stocks matched those criteria.";
      results.innerHTML = `<div class="empty-note">Try loosening a filter.</div>`;
      return;
    }
    status.textContent = `${body.stocks.length} match${body.stocks.length === 1 ? "" : "es"}.`;
    results.innerHTML =
      `<div class="list-row list-head" style="grid-template-columns: 1fr 1fr 1fr 1fr 1fr;"><span>Symbol</span><span>Price</span><span>Change</span><span>Volume</span><span>Mkt cap</span></div>` +
      body.stocks.map(stockFinderRow).join("") +
      `<div style="padding:0.75rem 1rem"><button class="btn-primary" id="useFoundTickersBtn">Use these ${body.stocks.length} in Options ideas ↓</button></div>`;
    document.getElementById("useFoundTickersBtn").addEventListener("click", () => {
      document.getElementById("sTickers").value = lastFoundSymbols.join(",");
      document.getElementById("scannerControls").scrollIntoView({ behavior: "smooth", block: "start" });
      runScannerScan();
    });
  } catch (err) {
    status.textContent = err.message;
    results.innerHTML = "";
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("fFindBtn").addEventListener("click", runStockFinder);

// ---------------------------------------------------------------------------
// Scanner (read-only: same screening engine as the Trading module, no Trade
// buttons -- order placement lives behind the password-protected module).
// ---------------------------------------------------------------------------

async function loadScannerStrategies() {
  try {
    const body = await getJSON("/strategies");
    const select = document.getElementById("sStrategy");
    for (const s of body.strategies) {
      const opt = document.createElement("option");
      opt.value = s.key;
      opt.textContent = s.name;
      select.appendChild(opt);
    }
  } catch {
    // scanner controls still work with "all strategies" if this fails
  }
}

function fmtBreakeven(breakeven) {
  if (!breakeven || !breakeven.length) return "n/a";
  return breakeven.map((b) => `$${b.toFixed(2)}`).join(" / ");
}

function scannerIdeaCard(idea) {
  const legsHtml = idea.legs
    .map((leg) => {
      const actionClass = leg.action === "buy" ? "action-buy" : "action-sell";
      const label = leg.contract
        ? `${leg.contract.expiration} $${leg.contract.strike} ${leg.contract.option_type.toUpperCase()} (&Delta; ${leg.contract.delta}, OI ${leg.contract.open_interest})`
        : leg.description;
      return `<tr><td class="${actionClass}">${leg.action.toUpperCase()}</td><td>${leg.quantity}</td><td>${label}</td></tr>`;
    })
    .join("");
  const netCostLabel = idea.net_cost >= 0 ? "Net debit" : "Net credit";
  const netCostClass = idea.net_cost >= 0 ? "negative" : "positive";
  return `<div class="idea-card">
    <div class="strategy-name">${idea.strategy_name}</div>
    <div class="attribution">${idea.trader_attribution}</div>
    <div class="rationale">${idea.rationale}</div>
    <table class="legs-table"><thead><tr><th>Action</th><th>Qty</th><th>Contract</th></tr></thead><tbody>${legsHtml}</tbody></table>
    <div class="stat-row">
      <div class="stat"><span class="label">${netCostLabel}</span><span class="value ${netCostClass}">${fmtMoney(Math.abs(idea.net_cost))}</span></div>
      <div class="stat"><span class="label">Max profit</span><span class="value positive">${idea.max_profit === null ? "Unlimited" : fmtMoney(idea.max_profit)}</span></div>
      <div class="stat"><span class="label">Max loss</span><span class="value negative">${idea.max_loss === null ? "Unlimited" : fmtMoney(idea.max_loss)}</span></div>
      <div class="stat"><span class="label">Breakeven</span><span class="value">${fmtBreakeven(idea.breakeven)}</span></div>
    </div>
  </div>`;
}

function scannerTickerBlock(result) {
  if (result.error) {
    return `<div class="ticker-block"><div class="ticker-header"><h3>${result.symbol}</h3></div><div class="error-msg">${result.error}</div></div>`;
  }
  const ideasHtml = result.ideas.length
    ? result.ideas.map(scannerIdeaCard).join("")
    : `<div class="empty-note">No ideas met the screening criteria for this ticker.</div>`;
  return `<div class="ticker-block">
    <div class="ticker-header">
      <h3>${result.symbol} <span class="price">${fmtMoney(result.underlying.price)}</span></h3>
      <span class="meta">${result.qualifying_contracts} qualifying contract(s)</span>
    </div>
    <div class="idea-grid">${ideasHtml}</div>
  </div>`;
}

async function runScannerScan() {
  const tickers = document.getElementById("sTickers").value.trim();
  const status = document.getElementById("scannerStatus");
  const results = document.getElementById("scannerResults");
  if (!tickers) {
    status.textContent = "Enter at least one ticker.";
    return;
  }
  const btn = document.getElementById("sScanBtn");
  btn.disabled = true;
  status.textContent = "Scanning…";
  results.innerHTML = "";
  const params = new URLSearchParams({
    tickers,
    strategy: document.getElementById("sStrategy").value,
    min_oi: document.getElementById("sMinOi").value,
    min_delta: document.getElementById("sMinDelta").value,
    min_dte: document.getElementById("sMinDte").value,
  });
  try {
    const body = await getJSON(`/scan?${params.toString()}`);
    status.textContent = `Criteria: OI > ${body.criteria.min_open_interest}, |delta| >= ${body.criteria.min_abs_delta}, DTE >= ${body.criteria.min_days_to_expiration} days`;
    results.innerHTML = body.results.map(scannerTickerBlock).join("");
  } catch (err) {
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("sScanBtn").addEventListener("click", runScannerScan);
document.getElementById("sTickers").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runScannerScan();
});

// ---------------------------------------------------------------------------
// Level 2 (simulated)
// ---------------------------------------------------------------------------

async function loadLevel2(symbol) {
  const box = document.getElementById("level2Book");
  box.innerHTML = Array.from({ length: 10 }, () => listRowSkeleton(2)).join("");
  try {
    const book = await getJSON(`/public/level2?symbol=${symbol}`);
    const maxSize = Math.max(...book.bids.map((b) => b.size), ...book.asks.map((a) => a.size), 1);
    const bidRows = book.bids
      .map(
        (b) => `<div class="book-row"><span class="book-price">${fmtMoney(b.price)}</span><span>${b.size.toLocaleString()}</span>
          <span class="depth-bar" style="width:${((b.size / maxSize) * 100).toFixed(0)}%"></span></div>`
      )
      .join("");
    const askRows = book.asks
      .map(
        (a) => `<div class="book-row"><span class="book-price">${fmtMoney(a.price)}</span><span>${a.size.toLocaleString()}</span>
          <span class="depth-bar" style="width:${((a.size / maxSize) * 100).toFixed(0)}%"></span></div>`
      )
      .join("");
    box.innerHTML = `
      <div class="book-col bids">
        <div class="book-col-head"><span>Bid</span><span>Size</span></div>
        ${bidRows}
      </div>
      <div class="book-col asks">
        <div class="book-col-head"><span>Ask</span><span>Size</span></div>
        ${askRows}
      </div>`;
  } catch (err) {
    box.innerHTML = `<div class="error-msg">${err.message}</div>`;
  }
}

document.getElementById("level2Form").addEventListener("submit", (e) => {
  e.preventDefault();
  const symbol = document.getElementById("level2Input").value.trim().toUpperCase();
  if (symbol) loadLevel2(symbol);
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

const initialTab = window.location.hash.replace("#", "");
if (initialTab && document.querySelector(`.tab-btn[data-tab="${initialTab}"]`)) {
  activateTab(initialTab);
} else {
  onTabShown("home");
}
loadHome();
