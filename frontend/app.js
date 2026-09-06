const API_BASE = "/api";

const els = {
  tickers: document.getElementById("tickers"),
  strategy: document.getElementById("strategy"),
  minOi: document.getElementById("minOi"),
  minDelta: document.getElementById("minDelta"),
  minDte: document.getElementById("minDte"),
  scanBtn: document.getElementById("scanBtn"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
};

function fmtMoney(value) {
  if (value === null || value === undefined) return "Unlimited";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtBreakeven(breakeven) {
  if (!breakeven || breakeven.length === 0) return "n/a";
  return breakeven.map((b) => `$${b.toFixed(2)}`).join(" / ");
}

async function loadStrategies() {
  const resp = await fetch(`${API_BASE}/strategies`);
  const body = await resp.json();
  for (const s of body.strategies) {
    const opt = document.createElement("option");
    opt.value = s.key;
    opt.textContent = s.name;
    els.strategy.appendChild(opt);
  }
}

function legRow(leg) {
  const actionClass = leg.action === "buy" ? "action-buy" : "action-sell";
  const contractLabel = leg.contract
    ? `${leg.contract.expiration} $${leg.contract.strike} ${leg.contract.option_type.toUpperCase()} ` +
      `(&Delta; ${leg.contract.delta}, OI ${leg.contract.open_interest})`
    : leg.description;
  return `<tr>
    <td class="${actionClass}">${leg.action.toUpperCase()}</td>
    <td>${leg.quantity}</td>
    <td>${contractLabel}</td>
  </tr>`;
}

function ideaCard(idea) {
  const legsHtml = idea.legs.map(legRow).join("");
  const netCostLabel = idea.net_cost >= 0 ? "Net debit" : "Net credit";
  const netCostClass = idea.net_cost >= 0 ? "negative" : "positive";
  return `<div class="idea-card">
    <div class="strategy-name">${idea.strategy_name}</div>
    <div class="attribution">${idea.trader_attribution}</div>
    <div class="rationale">${idea.rationale}</div>
    <table class="legs-table">
      <thead><tr><th>Action</th><th>Qty</th><th>Contract</th></tr></thead>
      <tbody>${legsHtml}</tbody>
    </table>
    <div class="stat-row">
      <div class="stat"><span class="label">${netCostLabel}</span><span class="value ${netCostClass}">${fmtMoney(Math.abs(idea.net_cost))}</span></div>
      <div class="stat"><span class="label">Max profit</span><span class="value positive">${fmtMoney(idea.max_profit)}</span></div>
      <div class="stat"><span class="label">Max loss</span><span class="value negative">${fmtMoney(idea.max_loss)}</span></div>
      <div class="stat"><span class="label">Breakeven</span><span class="value">${fmtBreakeven(idea.breakeven)}</span></div>
    </div>
  </div>`;
}

function tickerBlock(result) {
  if (result.error) {
    return `<div class="ticker-block">
      <div class="ticker-header"><h2>${result.symbol}</h2></div>
      <div class="error-msg">${result.error}</div>
    </div>`;
  }
  const ideasHtml = result.ideas.length
    ? result.ideas.map(ideaCard).join("")
    : `<div class="error-msg" style="color: var(--muted)">No ideas met the screening criteria for this ticker.</div>`;
  return `<div class="ticker-block">
    <div class="ticker-header">
      <h2>${result.symbol} <span class="price">$${result.underlying.price.toFixed(2)}</span></h2>
      <span class="meta">${result.qualifying_contracts} qualifying contract(s)</span>
    </div>
    <div class="idea-grid">${ideasHtml}</div>
  </div>`;
}

async function runScan() {
  const tickers = els.tickers.value.trim();
  if (!tickers) {
    els.status.textContent = "Enter at least one ticker.";
    return;
  }
  els.scanBtn.disabled = true;
  els.status.textContent = "Scanning...";
  els.results.innerHTML = "";

  const params = new URLSearchParams({
    tickers,
    strategy: els.strategy.value,
    min_oi: els.minOi.value,
    min_delta: els.minDelta.value,
    min_dte: els.minDte.value,
  });

  try {
    const resp = await fetch(`${API_BASE}/scan?${params.toString()}`);
    const body = await resp.json();
    if (!resp.ok) {
      els.status.textContent = body.detail || "Scan failed.";
      return;
    }
    els.status.textContent = `Criteria: OI > ${body.criteria.min_open_interest}, |delta| >= ${body.criteria.min_abs_delta}, DTE >= ${body.criteria.min_days_to_expiration} days`;
    els.results.innerHTML = body.results.map(tickerBlock).join("");
  } catch (err) {
    els.status.textContent = `Error: ${err.message}`;
  } finally {
    els.scanBtn.disabled = false;
  }
}

els.scanBtn.addEventListener("click", runScan);
els.tickers.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runScan();
});

loadStrategies().then(runScan);
