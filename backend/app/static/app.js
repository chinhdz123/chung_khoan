const actionResult = document.getElementById("actionResult");
const healthBadge = document.getElementById("healthBadge");
const updateBadge = document.getElementById("updateBadge");

const watchlistList = document.getElementById("watchlistList");
const addWatchlistBtn = document.getElementById("addWatchlistBtn");
const watchlistChips = document.getElementById("watchlistChips");
const symbolDetailCard = document.getElementById("symbolDetailCard");

const positionsList = document.getElementById("positionsList");
const addPositionBtn = document.getElementById("addPositionBtn");

const symbolRuleList = document.getElementById("symbolRuleList");
const addSymbolRuleBtn = document.getElementById("addSymbolRuleBtn");

let selectedSymbol = null;

async function cachedGetJson(url, key, ttlMs, options = {}) {
  if (window.UiCache?.fetchJson) {
    const result = await window.UiCache.fetchJson(url, {
      key,
      ttlMs,
      bypassCache: Boolean(options.bypassCache),
    });
    return result.data;
  }
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

function invalidateCachePrefixes(prefixes = []) {
  if (!window.UiCache?.invalidatePrefix) return;
  prefixes.forEach((prefix) => window.UiCache.invalidatePrefix(prefix));
}

function setResult(text) {
  actionResult.textContent = text;
}

function normalizeSymbol(value) {
  return String(value || "")
    .trim()
    .toUpperCase();
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("vi-VN");
}

function formatBillionVnd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return (Number(value) / 1_000_000_000).toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function createWatchlistRow(symbol = "") {
  const wrapper = document.createElement("div");
  wrapper.className = "editable-row";
  wrapper.innerHTML = `
    <div class="field-row">
      <label>Mã cổ phiếu</label>
      <input data-role="symbol" type="text" placeholder="VD: VCB" value="${normalizeSymbol(symbol)}" />
    </div>
    <button type="button" class="danger" data-role="remove">Xoá</button>
  `;

  const input = wrapper.querySelector('[data-role="symbol"]');
  const removeBtn = wrapper.querySelector('[data-role="remove"]');

  input.addEventListener("input", () => {
    input.value = normalizeSymbol(input.value);
    refreshWatchlistChips();
  });
  removeBtn.addEventListener("click", () => {
    wrapper.remove();
    if (!watchlistList.children.length) addWatchlistRow();
    refreshWatchlistChips();
  });

  return wrapper;
}

function addWatchlistRow(symbol = "") {
  watchlistList.appendChild(createWatchlistRow(symbol));
}

function collectWatchlistSymbols() {
  const symbols = Array.from(watchlistList.querySelectorAll('[data-role="symbol"]'))
    .map((el) => normalizeSymbol(el.value))
    .filter(Boolean);
  return Array.from(new Set(symbols));
}

function loadWatchlistRows(symbols = []) {
  watchlistList.innerHTML = "";
  if (!symbols.length) {
    addWatchlistRow();
  } else {
    symbols.forEach((symbol) => addWatchlistRow(symbol));
  }
  refreshWatchlistChips(symbols[0]);
}

function createPositionRow(position = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = "editable-row position-row";
  wrapper.innerHTML = `
    <div class="field-row">
      <label>Mã</label>
      <input data-role="symbol" type="text" placeholder="VCB" value="${normalizeSymbol(position.symbol)}" />
    </div>
    <div class="field-row">
      <label>Số lượng</label>
      <input data-role="quantity" type="number" min="0" step="1" value="${position.quantity ?? ""}" />
    </div>
    <div class="field-row">
      <label>Giá vốn TB</label>
      <input data-role="avg_cost" type="number" min="0" step="0.01" value="${position.avg_cost ?? ""}" />
    </div>
    <button type="button" class="danger" data-role="remove">Xoá</button>
  `;

  wrapper.querySelector('[data-role="symbol"]').addEventListener("input", (e) => {
    e.target.value = normalizeSymbol(e.target.value);
  });

  wrapper.querySelector('[data-role="remove"]').addEventListener("click", () => {
    wrapper.remove();
    if (!positionsList.children.length) addPositionRow();
  });

  return wrapper;
}

function addPositionRow(position = {}) {
  positionsList.appendChild(createPositionRow(position));
}

function collectPositions() {
  return Array.from(positionsList.querySelectorAll(".position-row"))
    .map((row) => {
      const symbol = normalizeSymbol(row.querySelector('[data-role="symbol"]').value);
      const quantity = Number(row.querySelector('[data-role="quantity"]').value);
      const avgCost = Number(row.querySelector('[data-role="avg_cost"]').value);
      return { symbol, quantity, avg_cost: avgCost };
    })
    .filter((x) => x.symbol && !Number.isNaN(x.quantity) && !Number.isNaN(x.avg_cost));
}

function loadPositionRows(positions = []) {
  positionsList.innerHTML = "";
  if (!positions.length) {
    addPositionRow();
  } else {
    positions.forEach((position) => addPositionRow(position));
  }
}

function createSymbolRuleItem(rule = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = "symbol-rule-item";
  wrapper.innerHTML = `
    <div class="symbol-rule-grid">
      <div class="field-row">
        <label>Mã</label>
        <input data-role="symbol" type="text" placeholder="VCB" value="${rule.symbol || ""}" />
      </div>
      <div class="field-row">
        <label>Ngừng tích sản</label>
        <input data-role="stop" type="number" min="0" step="0.01" value="${rule.stop_accumulate_price ?? ""}" />
      </div>
      <div class="field-row">
        <label>Chốt lời</label>
        <input data-role="take" type="number" min="0" step="0.01" value="${rule.take_profit_price ?? ""}" />
      </div>
      <button type="button" class="danger" data-role="remove">Xoá</button>
    </div>
  `;

  wrapper.querySelector('[data-role="symbol"]').addEventListener("input", (e) => {
    e.target.value = normalizeSymbol(e.target.value);
  });

  wrapper.querySelector('[data-role="remove"]').addEventListener("click", () => {
    wrapper.remove();
    if (!symbolRuleList.children.length) {
      addSymbolRuleItem();
    }
  });

  return wrapper;
}

function addSymbolRuleItem(rule = {}) {
  symbolRuleList.appendChild(createSymbolRuleItem(rule));
}

function collectSymbolRules() {
  const items = Array.from(symbolRuleList.querySelectorAll(".symbol-rule-item"));
  return items
    .map((item) => {
      const symbol = normalizeSymbol(item.querySelector('[data-role="symbol"]').value);
      const stopRaw = item.querySelector('[data-role="stop"]').value;
      const takeRaw = item.querySelector('[data-role="take"]').value;

      return {
        symbol,
        stop_accumulate_price: stopRaw ? Number(stopRaw) : null,
        take_profit_price: takeRaw ? Number(takeRaw) : null,
      };
    })
    .filter((x) => x.symbol && (x.stop_accumulate_price || x.take_profit_price));
}

function loadSymbolRules(rules = []) {
  symbolRuleList.innerHTML = "";
  if (!rules.length) {
    addSymbolRuleItem();
    return;
  }
  rules.forEach((rule) => addSymbolRuleItem(rule));
}

async function loadSymbolDetail(symbol) {
  const code = normalizeSymbol(symbol);
  if (!code) {
    symbolDetailCard.className = "card muted";
    symbolDetailCard.textContent = "Bấm vào mã trong watchlist để xem chi tiết nhanh.";
    return;
  }

  symbolDetailCard.className = "card muted";
  symbolDetailCard.textContent = `Đang tải chi tiết ${code}...`;

  try {
    const data = await cachedGetJson(
      `/api/market/${encodeURIComponent(code)}/snapshot`,
      `market:snapshot:${code}`,
      45000
    );
    const market = data.market || {};
    const financial = data.financial || {};

    symbolDetailCard.className = "card";
    symbolDetailCard.innerHTML = `
      <div class="detail-head">
        <strong>${code}</strong>
        <span class="pill">${market.snapshot_date || "-"}</span>
      </div>
      <div class="detail-grid">
        <div>Giá đóng cửa: <b>${formatNumber(market.close_price)}</b></div>
        <div>Khối lượng: <b>${formatNumber(market.volume)}</b></div>
        <div>Ngoại ròng (tỷ đồng): <b>${formatBillionVnd(market.foreign_net_value)}</b></div>
        <div>Tự doanh ròng (tỷ đồng): <b>${formatBillionVnd(market.proprietary_net_value)}</b></div>
        <div>P/E: <b>${formatNumber(financial.pe)}</b></div>
        <div>P/B: <b>${formatNumber(financial.pb)}</b></div>
        <div>ROE: <b>${formatNumber(financial.roe)}</b></div>
        <div>D/E: <b>${formatNumber(financial.debt_to_equity)}</b></div>
      </div>
    `;
  } catch (err) {
    symbolDetailCard.className = "card muted";
    symbolDetailCard.textContent = `${code}: ${err.message}`;
  }
}

function refreshWatchlistChips(preferredSymbol) {
  const symbols = collectWatchlistSymbols();
  watchlistChips.innerHTML = "";

  if (!symbols.length) {
    selectedSymbol = null;
    loadSymbolDetail(null);
    return;
  }

  if (preferredSymbol && symbols.includes(normalizeSymbol(preferredSymbol))) {
    selectedSymbol = normalizeSymbol(preferredSymbol);
  } else if (!selectedSymbol || !symbols.includes(selectedSymbol)) {
    selectedSymbol = symbols[0];
  }

  symbols.forEach((symbol) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = symbol;
    button.className = `chip-btn ${symbol === selectedSymbol ? "active" : ""}`;
    button.addEventListener("click", () => {
      selectedSymbol = symbol;
      refreshWatchlistChips();
      loadSymbolDetail(symbol);
    });
    watchlistChips.appendChild(button);
  });

  loadSymbolDetail(selectedSymbol);
}

function fillTemplateForm(data) {
  document.getElementById("cash").value = data.cash ?? 0;
  loadWatchlistRows(data.watchlist_symbols || []);
  loadPositionRows(data.positions || []);
  loadSymbolRules(data.symbol_rules || []);
}

async function fetchHealth() {
  try {
    const data = await cachedGetJson("/api/health", "api:health", 15000);
    healthBadge.textContent = `Hệ thống: ${data.ok ? "hoạt động" : "lỗi"}`;
    updateBadge.textContent = `Thời gian máy chủ: ${data.time}`;
  } catch (err) {
    healthBadge.textContent = "Hệ thống: không truy cập được";
  }
}

async function loadTemplate() {
  const data = await cachedGetJson("/api/portfolio/template", "portfolio:template", 120000);
  fillTemplateForm(data);
}

async function saveTemplate(event) {
  event.preventDefault();
  const payload = {
    cash: Number(document.getElementById("cash").value || 0),
    watchlist_symbols: collectWatchlistSymbols(),
    positions: collectPositions(),
    symbol_rules: collectSymbolRules(),
  };

  const res = await fetch("/api/portfolio/template", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok) {
    setResult(`Lưu thất bại: ${JSON.stringify(data)}`);
    return;
  }
  invalidateCachePrefixes(["portfolio:template", "portfolio:watchlist-config", "portfolio:holdings-config"]);
  fillTemplateForm(data);
  setResult("Đã lưu template thành công.");
}

function renderDecisions(decisions = []) {
  const el = document.getElementById("decisions");
  if (!decisions.length) {
    el.innerHTML = '<div class="card muted">Chưa có quyết định.</div>';
    return;
  }

  el.innerHTML = decisions
    .map((d) => {
      const actionClass = d.action.toLowerCase().replace("_", "-");
      return `
      <div class="item">
        <strong>${d.symbol}</strong>
        <span class="pill ${actionClass}">${d.action}</span>
        <div>Score: <b>${d.score}</b> | Risk: <b>${d.risk_score}</b> | Confidence: <b>${d.confidence}</b></div>
        <div>Giá hiện tại: ${d.current_price} | Buy zone: ${d.buy_zone} | Sell zone: ${d.sell_zone}</div>
        ${
          d.action === "BUY_ZONE"
            ? `<div>Giải ngân đề xuất: ${(d.disbursement_ratio * 100).toFixed(1)}% tổng tài sản | Kế hoạch: ${Number(
                d.planned_disbursement_value || 0
              ).toLocaleString("vi-VN")} ₫ (~${Number(d.planned_disbursement_quantity || 0).toLocaleString(
                "vi-VN"
              )} cp) | Theo tiền mặt hiện có: ${Number(d.final_disbursement_value || 0).toLocaleString(
                "vi-VN"
              )} ₫ (~${Number(d.final_disbursement_quantity || 0).toLocaleString("vi-VN")} cp)</div>`
            : ""
        }
        <div class="muted">${(d.reasons || []).join("; ")}</div>
      </div>
      `;
    })
    .join("");
}

function renderHealth(data) {
  const el = document.getElementById("portfolioHealth");
  if (!data) {
    el.textContent = "Chưa có dữ liệu.";
    return;
  }
  const warnings = (data.portfolio_warnings || data.warnings || []).join("; ") || "Không có cảnh báo lớn";
  const suggestions = (data.portfolio_suggestions || data.suggestions || []).join("; ") || "Tiếp tục giữ kỷ luật";
  const risk = data.portfolio_risk_score ?? data.risk_score ?? "-";
  el.innerHTML = `
    <div><b>Risk score:</b> ${risk}/100</div>
    <div><b>Cảnh báo:</b> ${warnings}</div>
    <div><b>Gợi ý:</b> ${suggestions}</div>
  `;
}

async function loadAdvice() {
  const summaryEl = document.getElementById("adviceSummary");
  try {
    const data = await cachedGetJson("/api/advice/latest", "advice:latest", 45000);
    summaryEl.innerHTML = `
      <div><b>Ngày:</b> ${data.report_date}</div>
      <div><b>Tự động AI:</b> ${data.used_ai ? "Có" : "Không"}</div>
      <div><b>Độ tin cậy:</b> ${data.confidence}</div>
      <div style="margin-top:8px">${data.summary}</div>
      ${data.ai_text ? `<details style="margin-top:8px"><summary>AI text</summary><pre>${data.ai_text}</pre></details>` : ""}
    `;
    renderDecisions(data.decisions || []);
    renderHealth(data);
  } catch (err) {
    summaryEl.textContent = `Lỗi tải khuyến nghị: ${err.message}`;
  }
}

async function loadPortfolioHealthFallback() {
  try {
    const data = await cachedGetJson("/api/portfolio/health", "portfolio:health", 45000);
    renderHealth(data);
  } catch (_) {}
}

async function loadAlerts() {
  const el = document.getElementById("alerts");
  try {
    const data = await cachedGetJson("/api/alerts", "alerts:list", 30000);
    if (!Array.isArray(data) || !data.length) {
      el.innerHTML = '<div class="card muted">Chưa có cảnh báo.</div>';
      return;
    }

    el.innerHTML = data
      .map(
        (a) => `
      <div class="item">
        <strong>${a.symbol}</strong> <span class="pill">${a.severity}</span>
        <div>${a.message}</div>
        <div class="muted">${a.created_at}</div>
      </div>`
      )
      .join("");
  } catch (err) {
    el.innerHTML = `<div class="card">Lỗi tải alert: ${err.message}</div>`;
  }
}

async function triggerJob(endpoint) {
  setResult(`Đang chạy ${endpoint} ...`);
  const res = await fetch(endpoint, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    setResult(`Tác vụ lỗi: ${JSON.stringify(data)}`);
    return;
  }
  invalidateCachePrefixes([
    "advice:latest",
    "portfolio:health",
    "portfolio:allocation",
    "market:watchlist-snapshots",
    "market:snapshot:",
    "market:history:",
    "alerts:list",
  ]);
  setResult(JSON.stringify(data, null, 2));
  await loadAdvice();
  await loadAlerts();
  refreshWatchlistChips();
}

document.getElementById("templateForm").addEventListener("submit", saveTemplate);
document.getElementById("runEtlBtn").addEventListener("click", () => triggerJob("/api/jobs/run-etl"));
document.getElementById("runAdviceBtn").addEventListener("click", () => triggerJob("/api/jobs/run-advice"));

addWatchlistBtn.addEventListener("click", () => addWatchlistRow());
addPositionBtn.addEventListener("click", () => addPositionRow());
addSymbolRuleBtn.addEventListener("click", () => addSymbolRuleItem());

async function bootstrap() {
  await fetchHealth();
  try {
    await loadTemplate();
  } catch (err) {
    setResult(`Không tải được template: ${err.message}`);
    loadWatchlistRows([]);
    loadPositionRows([]);
    loadSymbolRules([]);
  }
  await loadAdvice();
  await loadPortfolioHealthFallback();
  await loadAlerts();
}

bootstrap();
