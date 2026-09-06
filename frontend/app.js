const API_BASE = "/api";

const els = {
  loginOverlay: document.getElementById("loginOverlay"),
  loginForm: document.getElementById("loginForm"),
  loginUsername: document.getElementById("loginUsername"),
  loginPassword: document.getElementById("loginPassword"),
  loginPasswordToggle: document.getElementById("loginPasswordToggle"),
  loginError: document.getElementById("loginError"),
  app: document.getElementById("app"),
  liveBanner: document.getElementById("liveBanner"),
  brokerBadge: document.getElementById("brokerBadge"),
  logoutBtn: document.getElementById("logoutBtn"),

  acctBroker: document.getElementById("acctBroker"),
  acctCash: document.getElementById("acctCash"),
  acctPositionsValue: document.getElementById("acctPositionsValue"),
  acctPortfolio: document.getElementById("acctPortfolio"),
  positionsTable: document.querySelector("#positionsTable tbody"),
  ordersTable: document.querySelector("#ordersTable tbody"),

  tickers: document.getElementById("tickers"),
  strategy: document.getElementById("strategy"),
  minOi: document.getElementById("minOi"),
  minDelta: document.getElementById("minDelta"),
  minDte: document.getElementById("minDte"),
  scanBtn: document.getElementById("scanBtn"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),

  confirmModal: document.getElementById("confirmModal"),
  confirmModalBody: document.getElementById("confirmModalBody"),
  confirmModalInput: document.getElementById("confirmModalInput"),
  confirmModalOk: document.getElementById("confirmModalOk"),
  confirmModalCancel: document.getElementById("confirmModalCancel"),

  etradeConnectBtn: document.getElementById("etradeConnectBtn"),
  etradeVerifierRow: document.getElementById("etradeVerifierRow"),
  etradeVerifierInput: document.getElementById("etradeVerifierInput"),
  etradeCompleteBtn: document.getElementById("etradeCompleteBtn"),
  etradeStatus: document.getElementById("etradeStatus"),
};

const state = {
  isLive: false,
  etradeRequestToken: null,
  etradeRequestTokenSecret: null,
};

// Populated fresh on every render; trade buttons reference an idea/leg
// index rather than embedding JSON in HTML attributes.
let legRegistry = [];

function fmtMoney(value) {
  if (value === null || value === undefined) return "Unlimited";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtBreakeven(breakeven) {
  if (!breakeven || breakeven.length === 0) return "n/a";
  return breakeven.map((b) => `$${b.toFixed(2)}`).join(" / ");
}

// --- Authenticated fetch helper --------------------------------------------

async function apiFetch(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, options);
  if (resp.status === 401) {
    showLogin();
    throw new Error("Not authenticated");
  }
  return resp;
}

class ApiError extends Error {}

async function apiGetJSON(path) {
  const resp = await apiFetch(path);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(data.detail || `Request to ${path} failed (HTTP ${resp.status}).`);
  }
  return data;
}

async function apiPostJSON(path, body) {
  const resp = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await resp.json().catch(() => ({}));
  return { ok: resp.ok, status: resp.status, data };
}

// --- Auth --------------------------------------------------------------------

function showLogin() {
  els.app.hidden = true;
  els.loginOverlay.hidden = false;
}

function showApp() {
  els.loginOverlay.hidden = true;
  els.app.hidden = false;
  loadStrategies();
  loadBrokerStatus();
  loadAccount();
  loadOrders();
  runScan();
}

async function checkAuth() {
  try {
    const resp = await fetch(`${API_BASE}/auth/me`);
    return resp.ok;
  } catch {
    return false;
  }
}

els.loginPasswordToggle.addEventListener("click", () => {
  const showing = els.loginPassword.type === "text";
  els.loginPassword.type = showing ? "password" : "text";
  els.loginPasswordToggle.textContent = showing ? "Show" : "Hide";
});

els.loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  els.loginError.hidden = true;
  try {
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: els.loginUsername.value, password: els.loginPassword.value }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      els.loginError.textContent = body.detail || "Login failed.";
      els.loginError.hidden = false;
      return;
    }
    els.loginPassword.value = "";
    showApp();
  } catch (err) {
    els.loginError.textContent = `Error: ${err.message}`;
    els.loginError.hidden = false;
  }
});

els.logoutBtn.addEventListener("click", async () => {
  await apiFetch("/auth/logout", { method: "POST" });
  showLogin();
});

// --- Confirm-live-order modal --------------------------------------------------

function confirmLiveOrder(summaryText) {
  return new Promise((resolve) => {
    els.confirmModalBody.textContent = summaryText;
    els.confirmModalInput.value = "";
    els.confirmModal.hidden = false;
    els.confirmModalInput.focus();

    const cleanup = (result) => {
      els.confirmModal.hidden = true;
      els.confirmModalOk.removeEventListener("click", onOk);
      els.confirmModalCancel.removeEventListener("click", onCancel);
      resolve(result);
    };
    const onOk = () => {
      if (els.confirmModalInput.value.trim() === "CONFIRM") cleanup(true);
      else els.confirmModalInput.focus();
    };
    const onCancel = () => cleanup(false);
    els.confirmModalOk.addEventListener("click", onOk);
    els.confirmModalCancel.addEventListener("click", onCancel);
  });
}

// --- Broker status / account / positions / orders --------------------------------

async function loadBrokerStatus() {
  try {
    const body = await apiGetJSON("/broker/status");
    state.isLive = body.is_live;
    els.brokerBadge.textContent = body.is_live ? "LIVE" : "paper";
    els.brokerBadge.classList.toggle("live", body.is_live);
    els.liveBanner.hidden = !body.is_live;
  } catch (err) {
    if (err instanceof ApiError) els.brokerBadge.textContent = "unknown";
  }
}

async function loadAccount() {
  try {
    const account = await apiGetJSON("/account");
    els.acctBroker.textContent = account.broker;
    els.acctCash.textContent = fmtMoney(account.cash_balance);
    els.acctPositionsValue.textContent = fmtMoney(account.positions_value);
    els.acctPortfolio.textContent = fmtMoney(account.portfolio_value);

    els.positionsTable.innerHTML = account.positions
      .map((p) => {
        const label = p.asset_type === "option" ? `${p.expiration} $${p.strike} ${p.option_type.toUpperCase()}` : p.asset_type;
        const plClass = p.unrealized_pl >= 0 ? "positive" : "negative";
        return `<tr>
          <td>${p.symbol}</td><td>${label}</td><td>${p.quantity}</td>
          <td>$${p.avg_cost.toFixed(2)}</td><td>$${p.current_price.toFixed(2)}</td>
          <td class="${plClass}">${fmtMoney(p.unrealized_pl)}</td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="6" class="empty-row">No open positions.</td></tr>`;
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    els.acctBroker.textContent = "error";
    els.acctCash.textContent = els.acctPositionsValue.textContent = els.acctPortfolio.textContent = "—";
    els.positionsTable.innerHTML = `<tr><td colspan="6" class="empty-row error-msg">${err.message}</td></tr>`;
  }
}

async function loadOrders() {
  try {
    const body = await apiGetJSON("/orders");
    els.ordersTable.innerHTML = body.orders
      .map((o) => {
        const fill = o.status === "filled" ? `$${o.filled_price.toFixed(2)}` : o.rejection_reason || "&ndash;";
        const cancelBtn = o.status === "pending" ? `<button class="mini-btn" data-cancel-order="${o.id}">Cancel</button>` : "";
        return `<tr>
          <td>${o.symbol}</td><td>${o.side.toUpperCase()}</td><td>${o.quantity}</td>
          <td>${o.asset_type}${o.asset_type === "option" ? ` ${o.strike} ${o.option_type}` : ""}</td>
          <td class="status-${o.status}">${o.status}</td><td class="fill-cell">${fill}</td>
          <td>${cancelBtn}</td>
        </tr>`;
      })
      .join("") || `<tr><td colspan="7" class="empty-row">No orders yet.</td></tr>`;
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    els.ordersTable.innerHTML = `<tr><td colspan="7" class="empty-row error-msg">${err.message}</td></tr>`;
  }
}

els.ordersTable.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-cancel-order]");
  if (!btn) return;
  const orderId = btn.getAttribute("data-cancel-order");
  const { ok, data } = await apiPostJSON(`/orders/${orderId}/cancel`);
  els.status.textContent = ok ? `Order ${orderId} canceled.` : data.detail || "Cancel failed.";
  loadOrders();
});

// --- E*TRADE OAuth connection -------------------------------------------------

els.etradeConnectBtn.addEventListener("click", async () => {
  els.etradeStatus.textContent = "Requesting authorization URL...";
  els.etradeConnectBtn.disabled = true;
  try {
    const data = await apiGetJSON("/broker/etrade/auth-url");
    state.etradeRequestToken = data.request_token;
    state.etradeRequestTokenSecret = data.request_token_secret;
    window.open(data.authorize_url, "_blank", "noopener");
    els.etradeVerifierRow.hidden = false;
    els.etradeVerifierInput.focus();
    els.etradeStatus.textContent =
      "A new tab opened for E*TRADE login. After you authorize, E*TRADE shows a verifier code -- paste it below and click Complete Connection.";
  } catch (err) {
    els.etradeStatus.textContent = err.message;
  } finally {
    els.etradeConnectBtn.disabled = false;
  }
});

els.etradeCompleteBtn.addEventListener("click", async () => {
  const verifier = els.etradeVerifierInput.value.trim();
  if (!verifier) {
    els.etradeStatus.textContent = "Enter the verifier code E*TRADE showed you first.";
    return;
  }
  if (!state.etradeRequestToken || !state.etradeRequestTokenSecret) {
    els.etradeStatus.textContent = "Click Connect E*TRADE again first -- the request token expired or was never fetched.";
    return;
  }
  els.etradeCompleteBtn.disabled = true;
  els.etradeStatus.textContent = "Completing connection...";
  try {
    const { ok, data } = await apiPostJSON("/broker/etrade/complete-auth", {
      request_token: state.etradeRequestToken,
      request_token_secret: state.etradeRequestTokenSecret,
      verifier,
    });
    if (!ok) {
      els.etradeStatus.textContent = data.detail || "Failed to complete E*TRADE connection.";
      return;
    }
    els.etradeStatus.textContent = "E*TRADE connected. Real order placement still requires ACTIVE_BROKER=etrade and LIVE_TRADING_ENABLED=true on the server.";
    els.etradeVerifierRow.hidden = true;
    els.etradeVerifierInput.value = "";
  } catch (err) {
    els.etradeStatus.textContent = `Error: ${err.message}`;
  } finally {
    els.etradeCompleteBtn.disabled = false;
  }
});

// --- Placing an order from a strategy leg ------------------------------------

async function placeOrder(orderBody) {
  if (state.isLive) {
    const summary = `${orderBody.side.toUpperCase()} ${orderBody.quantity} ${orderBody.symbol}` +
      (orderBody.asset_type === "option" ? ` ${orderBody.expiration} $${orderBody.strike} ${orderBody.option_type}` : "");
    const confirmed = await confirmLiveOrder(summary);
    if (!confirmed) {
      els.status.textContent = "Live order canceled.";
      return;
    }
    orderBody = { ...orderBody, confirm_live: true };
  }
  els.status.textContent = "Placing order...";
  const { ok, data } = await apiPostJSON("/orders", orderBody);
  if (!ok) {
    els.status.textContent = data.detail || "Order failed.";
    return;
  }
  els.status.textContent = data.status === "filled"
    ? `Order filled: ${data.side.toUpperCase()} ${data.quantity} ${data.symbol} @ $${data.filled_price.toFixed(2)}`
    : `Order ${data.status}: ${data.rejection_reason || ""}`;
  loadAccount();
  loadOrders();
}

els.results.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-leg-index]");
  if (!btn) return;
  const order = legRegistry[Number(btn.getAttribute("data-leg-index"))];
  if (!order) return;
  btn.disabled = true;
  placeOrder(order)
    .catch((err) => {
      // Guards against silent failures (e.g. a session expiring mid-click,
      // or a network error) that would otherwise show nothing at all --
      // apiFetch's own 401 handling already calls showLogin(), so this is
      // mainly for anything unexpected.
      els.status.textContent = `Error: ${err.message}`;
    })
    .finally(() => {
      btn.disabled = false;
    });
});

// --- Strategy scan / rendering ------------------------------------------------

async function loadStrategies() {
  const body = await apiGetJSON("/strategies");
  for (const s of body.strategies) {
    const opt = document.createElement("option");
    opt.value = s.key;
    opt.textContent = s.name;
    els.strategy.appendChild(opt);
  }
}

function legRow(idea, leg) {
  const actionClass = leg.action === "buy" ? "action-buy" : "action-sell";
  const contractLabel = leg.contract
    ? `${leg.contract.expiration} $${leg.contract.strike} ${leg.contract.option_type.toUpperCase()} ` +
      `(&Delta; ${leg.contract.delta}, OI ${leg.contract.open_interest})`
    : leg.description;

  const orderBody = leg.contract
    ? {
        symbol: leg.contract.symbol,
        asset_type: "option",
        side: leg.action,
        quantity: leg.quantity,
        order_type: "market",
        option_type: leg.contract.option_type,
        strike: leg.contract.strike,
        expiration: leg.contract.expiration,
        rationale: idea.rationale,
      }
    : {
        symbol: idea.symbol,
        asset_type: "equity",
        side: leg.action,
        quantity: leg.quantity,
        order_type: "market",
        rationale: idea.rationale,
      };
  const legIndex = legRegistry.push(orderBody) - 1;

  return `<tr>
    <td class="${actionClass}">${leg.action.toUpperCase()}</td>
    <td>${leg.quantity}</td>
    <td>${contractLabel}</td>
    <td><button class="mini-btn" data-leg-index="${legIndex}">Trade</button></td>
  </tr>`;
}

function ideaCard(idea) {
  const legsHtml = idea.legs.map((leg) => legRow(idea, leg)).join("");
  const netCostLabel = idea.net_cost >= 0 ? "Net debit" : "Net credit";
  const netCostClass = idea.net_cost >= 0 ? "negative" : "positive";
  return `<div class="idea-card">
    <div class="strategy-name">${idea.strategy_name}</div>
    <div class="attribution">${idea.trader_attribution}</div>
    <div class="rationale">${idea.rationale}</div>
    <table class="legs-table">
      <thead><tr><th>Action</th><th>Qty</th><th>Contract</th><th></th></tr></thead>
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
  legRegistry = [];

  const params = new URLSearchParams({
    tickers,
    strategy: els.strategy.value,
    min_oi: els.minOi.value,
    min_delta: els.minDelta.value,
    min_dte: els.minDte.value,
  });

  try {
    const resp = await apiFetch(`/scan?${params.toString()}`);
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

checkAuth().then((authed) => (authed ? showApp() : showLogin()));
