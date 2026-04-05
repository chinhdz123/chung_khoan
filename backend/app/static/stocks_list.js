const healthBadge = document.getElementById("healthBadge");
const updateBadge = document.getElementById("updateBadge");
const stockTableBodyAttack = document.getElementById("stockTableBodyAttack");
const stockTableBodyBalance = document.getElementById("stockTableBodyBalance");
const stockTableBodyDefense = document.getElementById("stockTableBodyDefense");
const emptyStateAttack = document.getElementById("emptyStateAttack");
const emptyStateBalance = document.getElementById("emptyStateBalance");
const emptyStateDefense = document.getElementById("emptyStateDefense");
const adviceSummary = document.getElementById("adviceSummary");
const runEtlBtn = document.getElementById("runEtlBtn");
const runAdviceBtn = document.getElementById("runAdviceBtn");
const manualSymbolInput = document.getElementById("manualSymbolInput");
const addToWatchlistBtn = document.getElementById("addToWatchlistBtn");
const watchlistActionResult = document.getElementById("watchlistActionResult");
const sortMode = document.getElementById("sortMode");

let currentRows = [];
let currentWatchlistSymbols = [];

const WATCH_GROUP_KEYS = ["attack", "balance", "defense"];
const WATCH_GROUP_LABELS = {
  attack: "Tấn công",
  balance: "Cân bằng",
  defense: "Phòng thủ",
};
const WATCH_GROUP_OVERRIDE_KEY = "watchlist-group-overrides:v1";
let draggingGroupSymbol = null;
let draggingRowElement = null;

async function cachedGetJson(url, key, ttlMs, options = {}) {
  const bypassCache = Boolean(options.bypassCache);
  const requestUrl = bypassCache
    ? `${url}${String(url).includes("?") ? "&" : "?"}_ts=${Date.now()}`
    : url;
  if (window.UiCache?.fetchJson) {
    const result = await window.UiCache.fetchJson(requestUrl, {
      key,
      ttlMs,
      bypassCache,
    });
    return result.data;
  }
  const res = await fetch(requestUrl, { cache: bypassCache ? "no-store" : "default" });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

function invalidateCachePrefixes(prefixes = []) {
  if (!window.UiCache?.invalidatePrefix) return;
  prefixes.forEach((prefix) => window.UiCache.invalidatePrefix(prefix));
}

function normalizeSymbol(value) {
  return String(value || "").trim().toUpperCase();
}

function setWatchlistResult(text, type = "info") {
  const value = String(text || "").trim();
  if (!value) return;
  if (window.Toast) {
    window.Toast[type] ? window.Toast[type](value) : window.Toast.info(value);
  }
  if (watchlistActionResult) {
    watchlistActionResult.textContent = value;
    watchlistActionResult.style.display = value ? "block" : "none";
  }
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("vi-VN");
}

function formatBillionVnd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const billion = Number(value) / 1_000_000_000;
  return billion.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function parseManualSymbols(raw) {
  return String(raw || "")
    .split(/[\s,;\n\t]+/)
    .map((x) => normalizeSymbol(x))
    .filter(Boolean);
}

function normalizeWatchGroup(group) {
  return WATCH_GROUP_KEYS.includes(group) ? group : "balance";
}

function buildManualGroupMap() {
  const map = new Map();
  const groups = window.ManualRecoData?.groups || {};
  WATCH_GROUP_KEYS.forEach((group) => {
    (groups[group] || []).forEach((symbol) => {
      map.set(normalizeSymbol(symbol), group);
    });
  });
  return map;
}

const manualGroupMap = buildManualGroupMap();

function defaultWatchGroupForSymbol(symbol) {
  return normalizeWatchGroup(manualGroupMap.get(normalizeSymbol(symbol)) || "balance");
}

function loadWatchGroupOverrides() {
  try {
    const raw = window.localStorage.getItem(WATCH_GROUP_OVERRIDE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_) {
    return {};
  }
}

let watchGroupOverrides = loadWatchGroupOverrides();

function saveWatchGroupOverrides() {
  try {
    window.localStorage.setItem(WATCH_GROUP_OVERRIDE_KEY, JSON.stringify(watchGroupOverrides));
  } catch (_) {
    // Ignore localStorage errors.
  }
}

function resolveWatchGroup(symbol) {
  const key = normalizeSymbol(symbol);
  return normalizeWatchGroup(watchGroupOverrides[key] || defaultWatchGroupForSymbol(key));
}

function setWatchGroupOverride(symbol, group) {
  const key = normalizeSymbol(symbol);
  if (!key) return;
  watchGroupOverrides[key] = normalizeWatchGroup(group);
  saveWatchGroupOverrides();
}

function removeWatchGroupOverride(symbol) {
  const key = normalizeSymbol(symbol);
  if (!key || !Object.prototype.hasOwnProperty.call(watchGroupOverrides, key)) return;
  delete watchGroupOverrides[key];
  saveWatchGroupOverrides();
}

function getTableBodyByGroup(group) {
  const key = normalizeWatchGroup(group);
  if (key === "attack") return stockTableBodyAttack;
  if (key === "defense") return stockTableBodyDefense;
  return stockTableBodyBalance;
}

function getEmptyStateByGroup(group) {
  const key = normalizeWatchGroup(group);
  if (key === "attack") return emptyStateAttack;
  if (key === "defense") return emptyStateDefense;
  return emptyStateBalance;
}

function getDragAfterRow(container, y) {
  const candidates = Array.from(container.querySelectorAll("tr.watch-row:not(.dragging)"));
  let closest = null;
  let closestOffset = Number.NEGATIVE_INFINITY;
  candidates.forEach((element) => {
    const box = element.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closestOffset) {
      closestOffset = offset;
      closest = element;
    }
  });
  return closest;
}

function setupWatchGroupDnD() {
  const cards = Array.from(document.querySelectorAll(".holdings-group-card[data-group]"));
  cards.forEach((card) => {
    const group = normalizeWatchGroup(card.dataset.group || "balance");
    const body = getTableBodyByGroup(group);

    card.addEventListener("dragover", (event) => {
      if (!draggingGroupSymbol) return;
      event.preventDefault();
      card.classList.add("drag-over");
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      if (draggingRowElement) {
        const afterElement = getDragAfterRow(body, event.clientY);
        if (!afterElement) body.appendChild(draggingRowElement);
        else body.insertBefore(draggingRowElement, afterElement);
      }
    });
    card.addEventListener("dragleave", (event) => {
      if (event.relatedTarget && card.contains(event.relatedTarget)) return;
      card.classList.remove("drag-over");
    });
    card.addEventListener("drop", (event) => {
      if (!draggingGroupSymbol) return;
      event.preventDefault();
      card.classList.remove("drag-over");
      setWatchGroupOverride(draggingGroupSymbol, group);
      setWatchlistResult(`Đã chuyển ${draggingGroupSymbol} sang nhóm ${WATCH_GROUP_LABELS[group]}.`);
      renderTablesByGroup(currentRows);
    });
  });
}

async function saveWatchlistSymbols(symbols) {
  const res = await fetch("/api/portfolio/watchlist-config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ watchlist_symbols: symbols }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(JSON.stringify(data));
  }
  invalidateCachePrefixes(["portfolio:watchlist-config", "market:watchlist-snapshots"]);
  return data.watchlist_symbols || [];
}

function getManualReference(symbol) {
  const key = normalizeSymbol(symbol);
  return window.ManualRecoData?.items?.[key] || null;
}

function actionText(action) {
  if (action === "BUY_ZONE") return "Trong vùng mua";
  if (action === "SELL_ZONE") return "Đạt vùng bán";
  if (action === "HOLD") return "Giữa vùng mua-bán";
  return "Chưa nhập tay";
}

function closePrice(row) {
  return Number(row?.market?.close_price || 0);
}

function upsideToSellPct(row, ref) {
  const close = closePrice(row);
  const sell = Number(ref?.sell_price || 0);
  if (!Number.isFinite(close) || !Number.isFinite(sell) || close <= 0 || sell <= 0) {
    return Number.NaN;
  }
  return ((sell - close) / close) * 100;
}

function resolveManualAction(row, ref) {
  if (!ref) return "NO_SIGNAL";
  const close = closePrice(row);
  const buy = Number(ref.buy_price || 0);
  const sell = Number(ref.sell_price || 0);
  if (!Number.isFinite(close) || close <= 0 || buy <= 0 || sell <= 0) return "NO_SIGNAL";
  if (close <= buy) return "BUY_ZONE";
  if (close >= sell) return "SELL_ZONE";
  return "HOLD";
}

function priorityScore(action, upsidePct) {
  const actionRank = {
    BUY_ZONE: 3,
    HOLD: 2,
    SELL_ZONE: 1,
    NO_SIGNAL: 0,
  };
  const rank = actionRank[action] || 0;
  const upside = Number.isFinite(upsidePct) ? upsidePct : -999;
  return rank * 1000 + upside;
}

function netFlowValue(row) {
  const market = row?.market || {};
  const foreign = Number(market.foreign_net_value || 0);
  const prop = Number(market.proprietary_net_value || 0);
  return foreign + prop;
}

function buySafetyMarginPct(row, ref) {
  const price = closePrice(row);
  const buyZone = Number(ref?.buy_price || 0);
  if (!Number.isFinite(price) || !Number.isFinite(buyZone) || buyZone <= 0) {
    return Number.NEGATIVE_INFINITY;
  }
  return ((buyZone - price) / buyZone) * 100;
}

function compareNumberDesc(a, b) {
  const aOk = Number.isFinite(a);
  const bOk = Number.isFinite(b);
  if (aOk && bOk) return b - a;
  if (aOk) return -1;
  if (bOk) return 1;
  return 0;
}

function compareNumberAsc(a, b) {
  const aOk = Number.isFinite(a);
  const bOk = Number.isFinite(b);
  if (aOk && bOk) return a - b;
  if (aOk) return -1;
  if (bOk) return 1;
  return 0;
}

function applyFiltersAndSort(rows) {
  const list = rows
    .map((row) => {
      const ref = getManualReference(row.symbol);
      const action = resolveManualAction(row, ref);
      const upsidePct = upsideToSellPct(row, ref);
      return {
        row,
        ref,
        action,
        upsidePct,
        netFlow: netFlowValue(row),
        safetyMargin: buySafetyMarginPct(row, ref),
      };
    });

  const mode = sortMode?.value || "priority";
  list.sort((a, b) => {
    if (mode === "safety_margin_desc") {
      const bySafety = compareNumberDesc(a.safetyMargin, b.safetyMargin);
      if (bySafety !== 0) return bySafety;
      return priorityScore(b.action, b.upsidePct) - priorityScore(a.action, a.upsidePct);
    }
    if (mode === "net_flow_desc") {
      const byFlow = compareNumberDesc(a.netFlow, b.netFlow);
      if (byFlow !== 0) return byFlow;
      return priorityScore(b.action, b.upsidePct) - priorityScore(a.action, a.upsidePct);
    }
    if (mode === "close_asc") {
      const aClose = Number(a.row?.market?.close_price);
      const bClose = Number(b.row?.market?.close_price);
      const byClose = compareNumberAsc(aClose, bClose);
      if (byClose !== 0) return byClose;
      return priorityScore(b.action, b.upsidePct) - priorityScore(a.action, a.upsidePct);
    }
    if (mode === "close_desc") {
      const aClose = Number(a.row?.market?.close_price);
      const bClose = Number(b.row?.market?.close_price);
      const byClose = compareNumberDesc(aClose, bClose);
      if (byClose !== 0) return byClose;
      return priorityScore(b.action, b.upsidePct) - priorityScore(a.action, a.upsidePct);
    }
    return priorityScore(b.action, b.upsidePct) - priorityScore(a.action, a.upsidePct);
  });

  return list;
}

function actionBadge(action) {
  if (!action || action === "NO_SIGNAL") return '<span class="pill">CHƯA NHẬP TAY</span>';
  const cls = action.toLowerCase().replace("_", "-");
  return `<span class="pill ${cls}">${actionText(action)}</span>`;
}

async function fetchHealth(options = {}) {
  try {
    const data = await cachedGetJson("/api/health", "api:health", 15000, options);
    if (healthBadge) healthBadge.textContent = `Hệ thống: ${data.ok ? "hoạt động" : "lỗi"}`;
    if (updateBadge) updateBadge.textContent = `Thời gian máy chủ: ${data.time}`;
  } catch (_) {
    if (healthBadge) healthBadge.textContent = "Hệ thống: không truy cập được";
  }
}

function renderManualSummary(rows) {
  if (!adviceSummary) return;
  const total = rows.length;
  const withRef = rows.filter((row) => Boolean(getManualReference(row.symbol))).length;
  let buyCount = 0;
  let holdCount = 0;
  let sellCount = 0;
  const upsideList = [];

  rows.forEach((row) => {
    const ref = getManualReference(row.symbol);
    const action = resolveManualAction(row, ref);
    if (action === "BUY_ZONE") buyCount += 1;
    if (action === "HOLD") holdCount += 1;
    if (action === "SELL_ZONE") sellCount += 1;
    const upside = upsideToSellPct(row, ref);
    if (Number.isFinite(upside)) upsideList.push(upside);
  });

  const avgUpside = upsideList.length ? upsideList.reduce((a, b) => a + b, 0) / upsideList.length : Number.NaN;
  adviceSummary.innerHTML = `
    <div><b>Chế độ:</b> Khuyến nghị mua/bán và cổ tức nhập tay theo bảng tham khảo</div>
    <div><b>Số mã trong watchlist:</b> ${formatNumber(total)} | <b>Đã có mốc nhập tay:</b> ${formatNumber(withRef)}</div>
    <div><b>Trong vùng mua:</b> ${formatNumber(buyCount)} | <b>Giữa vùng:</b> ${formatNumber(
      holdCount
    )} | <b>Đạt vùng bán:</b> ${formatNumber(sellCount)}</div>
    <div><b>Chênh lệch bình quân tới giá bán:</b> ${
      Number.isFinite(avgUpside) ? `${formatNumber(avgUpside.toFixed(2))}%` : "-"
    }</div>
  `;
}

function renderTableForGroup(group, rows) {
  const body = getTableBodyByGroup(group);
  const empty = getEmptyStateByGroup(group);
  body.innerHTML = "";

  if (!rows.length) {
    empty.style.display = "block";
    return;
  }

  empty.style.display = "none";
  const sorted = applyFiltersAndSort(rows);
  sorted.forEach(({ row, ref, action, upsidePct }, index) => {
    const market = row.market || {};
    const upsideText = Number.isFinite(upsidePct) ? `${formatNumber(upsidePct.toFixed(2))}%` : "-";
    const dividendText = ref?.annual_dividend ? formatNumber(ref.annual_dividend) : "-";

    const tr = document.createElement("tr");
    tr.className = "watch-row";
    tr.dataset.symbol = normalizeSymbol(row.symbol);
    tr.setAttribute("draggable", "true");
    tr.innerHTML = `
      <td data-label="Ưu tiên"><b>#${index + 1}</b> <b>${row.symbol}</b></td>
      <td data-label="Mã"><b>${row.symbol}</b></td>
      <td data-label="Phiên">${market.snapshot_date || "-"}</td>
      <td data-label="Giá đóng cửa">${formatNumber(market.close_price)}</td>
      <td data-label="Giá mua">${formatNumber(ref?.buy_price)}</td>
      <td data-label="Giá bán">${formatNumber(ref?.sell_price)}</td>
      <td data-label="Chênh lệch bán">${upsideText}</td>
      <td data-label="Cổ tức TB">${dividendText}</td>
      <td data-label="Ngoại ròng">${formatBillionVnd(market.foreign_net_value)}</td>
      <td data-label="Tự doanh ròng">${formatBillionVnd(market.proprietary_net_value)}</td>
      <td data-label="Khuyến nghị">${actionBadge(action)}</td>
      <td data-label="Chi tiết"><a class="table-link" href="/stocks/${encodeURIComponent(row.symbol)}">Xem</a></td>
      <td data-label="Cập nhật"><button type="button" class="secondary" data-role="refresh-symbol" data-symbol="${row.symbol}">Cập nhật</button></td>
      <td data-label="Xóa"><button type="button" class="danger" data-role="remove-symbol" data-symbol="${row.symbol}">Xóa</button></td>
    `;

    tr.addEventListener("dragstart", (event) => {
      draggingGroupSymbol = tr.dataset.symbol;
      draggingRowElement = tr;
      tr.classList.add("dragging");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", tr.dataset.symbol || "");
      }
    });
    tr.addEventListener("dragend", () => {
      tr.classList.remove("dragging");
      draggingGroupSymbol = null;
      draggingRowElement = null;
      document.querySelectorAll(".watch-table-card").forEach((card) => card.classList.remove("drag-over"));
    });

    body.appendChild(tr);
  });

  body.querySelectorAll('button[data-role="refresh-symbol"]').forEach((button) => {
    button.addEventListener("click", () => {
      refreshDataAndAdviceBySymbol(button.dataset.symbol, button);
    });
  });
  body.querySelectorAll('button[data-role="remove-symbol"]').forEach((button) => {
    button.addEventListener("click", () => {
      removeSymbolFromWatchlist(button.dataset.symbol, button);
    });
  });
}

function renderTablesByGroup(rows) {
  const grouped = {
    attack: [],
    balance: [],
    defense: [],
  };

  (rows || []).forEach((row) => {
    const group = resolveWatchGroup(row.symbol);
    grouped[group].push(row);
  });

  WATCH_GROUP_KEYS.forEach((group) => {
    renderTableForGroup(group, grouped[group]);
  });
}

async function removeSymbolFromWatchlist(symbol, button) {
  const targetSymbol = normalizeSymbol(symbol);
  if (!targetSymbol) return;

  const old = button.textContent;
  button.disabled = true;
  button.textContent = "Đang xóa...";
  setWatchlistResult(`Đang xóa ${targetSymbol} khỏi watchlist...`);

  try {
    const remaining = (currentWatchlistSymbols || []).map((x) => normalizeSymbol(x)).filter((x) => x && x !== targetSymbol);
    currentWatchlistSymbols = await saveWatchlistSymbols(remaining);
    removeWatchGroupOverride(targetSymbol);
    currentRows = currentRows.filter((row) => normalizeSymbol(row.symbol) !== targetSymbol);
    renderManualSummary(currentRows);
    renderTablesByGroup(currentRows);
    await loadList({ bypassCache: true });
    setWatchlistResult(`Đã xóa ${targetSymbol} khỏi watchlist.`);
  } catch (err) {
    setWatchlistResult(`Xóa ${targetSymbol} thất bại: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}

async function loadList(options = {}) {
  let rows;
  let watchCfg;
  try {
    [rows, watchCfg] = await Promise.all([
      cachedGetJson("/api/market/watchlist-snapshots", "market:watchlist-snapshots", 45000, options),
      cachedGetJson("/api/portfolio/watchlist-config", "portfolio:watchlist-config", 120000, options).catch(() => null),
    ]);
  } catch (err) {
    setWatchlistResult(`Không tải được dữ liệu watchlist: ${err.message}`);
    WATCH_GROUP_KEYS.forEach((group) => renderTableForGroup(group, []));
    return;
  }
  if (!Array.isArray(rows)) {
    setWatchlistResult("Không tải được dữ liệu watchlist.");
    WATCH_GROUP_KEYS.forEach((group) => renderTableForGroup(group, []));
    return;
  }

  currentRows = Array.isArray(rows) ? rows : [];
  if (watchCfg && typeof watchCfg === "object") {
    currentWatchlistSymbols = (watchCfg.watchlist_symbols || []).map((x) => normalizeSymbol(x));
  } else {
    currentWatchlistSymbols = currentRows.map((x) => normalizeSymbol(x.symbol));
  }

  renderManualSummary(currentRows);
  renderTablesByGroup(currentRows);
}

async function addSymbolsIntoWatchlist() {
  const manual = parseManualSymbols(manualSymbolInput?.value || "");
  const requested = Array.from(new Set(manual));

  if (!requested.length) {
    return { addedCount: 0, message: "Chưa chọn hoặc nhập mã nào để thêm." };
  }

  const beforeCount = (currentWatchlistSymbols || []).length;
  const merged = Array.from(new Set([...(currentWatchlistSymbols || []), ...requested])).sort();
  if (merged.length === beforeCount) {
    return { addedCount: 0, message: "Các mã đã chọn đều đã có trong watchlist." };
  }

  setWatchlistResult("Đang thêm mã vào watchlist...");
  currentWatchlistSymbols = await saveWatchlistSymbols(merged);
  requested.forEach((symbol) => {
    if (!Object.prototype.hasOwnProperty.call(watchGroupOverrides, symbol)) {
      setWatchGroupOverride(symbol, defaultWatchGroupForSymbol(symbol));
    }
  });
  if (manualSymbolInput) manualSymbolInput.value = "";
  await loadList({ bypassCache: true });
  const addedCount = currentWatchlistSymbols.length - beforeCount;
  return { addedCount, message: `Đã thêm ${addedCount} mã vào watchlist.` };
}

async function runJob(endpoint, button) {
  const old = button.textContent;
  button.disabled = true;
  button.textContent = "Đang chạy...";
  try {
    const res = await fetch(endpoint, { method: "POST" });
    if (!res.ok) {
      const err = await res.text();
      if (window.Toast) window.Toast.error(`Tác vụ lỗi: ${err}`); else alert(`Tác vụ lỗi: ${err}`);
      return;
    }
    invalidateCachePrefixes(["advice:latest", "portfolio:health", "alerts:list"]);
    await loadList({ bypassCache: true });
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}

async function refreshDataAndAdvice() {
  const old = runEtlBtn.textContent;
  runEtlBtn.disabled = true;
  runEtlBtn.textContent = "Đang cập nhật...";
  try {
    const etlRes = await fetch("/api/jobs/run-etl", { method: "POST" });
    const etlData = await etlRes.json();
    if (!etlRes.ok) {
      throw new Error(etlData?.detail || JSON.stringify(etlData));
    }
    if (etlData && etlData.ok === false) {
      const errors = etlData?.details?.errors || [];
      throw new Error(errors.length ? errors.slice(0, 2).join(" | ") : "ETL không thành công");
    }
    const etlErrors = etlData?.details?.errors || [];
    const marketSkipped = Number(etlData?.details?.market_skipped || 0);
    const quotaExhausted = Boolean(etlData?.details?.vnstock_quota_exhausted);
    if (quotaExhausted) {
      setWatchlistResult("Đã chạm quota VNSTOCK trong phiên này; hệ thống tự bỏ qua phần còn lại và vẫn lưu dữ liệu đã lấy được.");
    } else if (etlErrors.length) {
      setWatchlistResult(`ETL hoàn tất nhưng bỏ qua ${etlErrors.length} lỗi nguồn dữ liệu (đã log).`);
    } else if (marketSkipped > 0) {
      setWatchlistResult(`ETL bỏ qua ${marketSkipped} mã đã cập nhật trong ngày.`);
    }

    invalidateCachePrefixes(["market:watchlist-snapshots", "market:snapshot:", "market:history:"]);
    await loadList({ bypassCache: true });
    await fetchHealth({ bypassCache: true });
  } catch (err) {
    if (window.Toast) window.Toast.error(`Cập nhật dữ liệu thất bại: ${err.message}`); else alert(`Cập nhật dữ liệu thất bại: ${err.message}`);
  } finally {
    runEtlBtn.disabled = false;
    runEtlBtn.textContent = old;
  }
}

async function refreshDataAndAdviceBySymbol(symbol, button) {
  const targetSymbol = normalizeSymbol(symbol);
  if (!targetSymbol) return;

  const old = button.textContent;
  button.disabled = true;
  button.textContent = "Đang cập nhật...";
  setWatchlistResult(`Đang cập nhật giá + dòng tiền cho: ${targetSymbol}...`);

  try {
    const query = encodeURIComponent(targetSymbol);
    const etlRes = await fetch(`/api/jobs/refresh-market?symbols=${query}&force=true`, { method: "POST" });
    const etlData = await etlRes.json();
    if (!etlRes.ok) {
      throw new Error(etlData?.detail || JSON.stringify(etlData));
    }

    const etlErrors = etlData?.details?.errors || [];
    const quotaExhausted = Boolean(etlData?.details?.vnstock_quota_exhausted);
    if (quotaExhausted) {
      setWatchlistResult(
        `Đã chạm quota VNSTOCK khi cập nhật ${targetSymbol}; hệ thống đã bỏ qua phần còn lại và lưu dữ liệu đã lấy được.`
      );
    } else if (etlErrors.length) {
      setWatchlistResult(`Cập nhật thị trường ${targetSymbol} hoàn tất nhưng có ${etlErrors.length} lỗi nguồn dữ liệu (đã log).`);
    } else {
      setWatchlistResult(`Đã cập nhật giá + dòng tiền cho: ${targetSymbol}.`);
    }

    invalidateCachePrefixes([
      "market:watchlist-snapshots",
      `market:snapshot:${targetSymbol}`,
      `market:history:${targetSymbol}:`,
    ]);
    await loadList({ bypassCache: true });
    await fetchHealth({ bypassCache: true });
  } catch (err) {
    setWatchlistResult(`Cập nhật ${targetSymbol} thất bại: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}

runEtlBtn.addEventListener("click", refreshDataAndAdvice);
if (runAdviceBtn) {
  runAdviceBtn.addEventListener("click", () => runJob("/api/jobs/run-advice", runAdviceBtn));
}
if (sortMode) {
  sortMode.addEventListener("change", () => {
    renderTablesByGroup(currentRows);
  });
}
if (addToWatchlistBtn) {
  addToWatchlistBtn.addEventListener("click", async () => {
    try {
      const result = await addSymbolsIntoWatchlist();
      if (result?.message) setWatchlistResult(result.message);
    } catch (err) {
      setWatchlistResult(`Thêm mã thất bại: ${err.message}`);
    }
  });
}

setupWatchGroupDnD();

async function bootstrap() {
  await fetchHealth();
  await loadList();
}

bootstrap();
