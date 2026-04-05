const actionResult = document.getElementById("actionResult");
const watchlistList = document.getElementById("watchlistList");
const addWatchlistBtn = document.getElementById("addWatchlistBtn");
const watchlistChips = document.getElementById("watchlistChips");
const symbolDetailCard = document.getElementById("symbolDetailCard");
const quickSymbolSelect = document.getElementById("quickSymbolSelect");
const addSelectedBtn = document.getElementById("addSelectedBtn");

const DEFAULT_SYMBOL_UNIVERSE = [
  "ACB", "ACV", "BMP", "BWE", "DCM", "DGC", "DHC", "DHG", "DPM", "DPR", "FPT", "GAS", "HAX", "HCM", "HDB",
  "HDG", "HND", "HPG", "IDC", "IMP", "LHG", "MBB", "MSB", "MSN", "MWG", "NLG", "NT2", "OCB", "PHR", "PLX",
  "PNJ", "POW", "PTB", "PVS", "PVT", "QNS", "QTP", "REE", "SIP", "SSI", "STB", "TCB", "TCX", "TDM", "TPB",
  "VCB", "VCI", "VCS", "VEA", "VHC", "VHM", "VIB", "VND", "VNM", "VPB", "VRE", "VSC",
];

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
  return String(value || "").trim().toUpperCase();
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
  input.addEventListener("input", () => {
    input.value = normalizeSymbol(input.value);
    refreshWatchlistChips();
  });
  wrapper.querySelector('[data-role="remove"]').addEventListener("click", () => {
    wrapper.remove();
    if (!watchlistList.children.length) addWatchlistRow();
    refreshWatchlistChips();
  });
  return wrapper;
}

function addWatchlistRow(symbol = "") {
  watchlistList.appendChild(createWatchlistRow(symbol));
}

function addSymbolsToWatchlist(symbols = []) {
  const current = new Set(collectWatchlistSymbols());
  let added = 0;
  for (const raw of symbols) {
    const symbol = normalizeSymbol(raw);
    if (!symbol || current.has(symbol)) continue;
    addWatchlistRow(symbol);
    current.add(symbol);
    added += 1;
  }
  if (added > 0) {
    refreshWatchlistChips();
  }
  return added;
}

function collectWatchlistSymbols() {
  const symbols = Array.from(watchlistList.querySelectorAll('[data-role="symbol"]'))
    .map((el) => normalizeSymbol(el.value))
    .filter(Boolean);
  return Array.from(new Set(symbols));
}

function loadWatchlistRows(symbols = []) {
  watchlistList.innerHTML = "";
  if (!symbols.length) addWatchlistRow();
  else symbols.forEach((symbol) => addWatchlistRow(symbol));
  refreshWatchlistChips(symbols[0]);
}

function populateQuickSelect(seedSymbols = []) {
  if (!quickSymbolSelect) return;
  const current = new Set(collectWatchlistSymbols());
  const allSymbols = Array.from(
    new Set([...DEFAULT_SYMBOL_UNIVERSE, ...(seedSymbols || []), ...Array.from(current)])
  )
    .map((x) => normalizeSymbol(x))
    .filter(Boolean)
    .sort();

  quickSymbolSelect.innerHTML = "";
  allSymbols.forEach((symbol) => {
    const option = document.createElement("option");
    option.value = symbol;
    if (current.has(symbol)) {
      option.textContent = `${symbol} (đã có)`;
      option.disabled = true;
    } else {
      option.textContent = symbol;
    }
    quickSymbolSelect.appendChild(option);
  });
}

async function loadSymbolDetail(symbol) {
  const code = normalizeSymbol(symbol);
  if (!code) {
    symbolDetailCard.className = "card muted";
    symbolDetailCard.textContent = "Bấm vào mã trong danh sách theo dõi để xem chi tiết.";
    return;
  }

  symbolDetailCard.className = "card muted";
  symbolDetailCard.textContent = `Đang tải ${code}...`;
  try {
    const data = await cachedGetJson(
      `/api/market/${encodeURIComponent(code)}/snapshot`,
      `market:snapshot:${code}`,
      45000
    );
    const market = data.market || {};
    const fin = data.financial || {};
    symbolDetailCard.className = "card";
    symbolDetailCard.innerHTML = `
      <div class="detail-head"><strong>${code}</strong><span class="pill">${market.snapshot_date || "-"}</span></div>
      <div class="detail-grid">
        <div>Giá đóng cửa (nghìn đồng/cp): <b>${formatNumber(market.close_price)}</b></div>
        <div>Khối lượng (cp): <b>${formatNumber(market.volume)}</b></div>
        <div title="Giá trị mua ròng của khối ngoại">Ngoại ròng (tỷ đồng): <b>${formatBillionVnd(market.foreign_net_value)}</b></div>
        <div title="Giá trị mua ròng của khối tự doanh">Tự doanh ròng (tỷ đồng): <b>${formatBillionVnd(market.proprietary_net_value)}</b></div>
        <div title="Giá thị trường / Lợi nhuận trên mỗi cổ phiếu">P/E: <b>${formatNumber(fin.pe)}</b></div>
        <div title="Giá thị trường / Giá trị sổ sách">P/B: <b>${formatNumber(fin.pb)}</b></div>
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
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `chip-btn ${symbol === selectedSymbol ? "active" : ""}`;
    btn.textContent = symbol;
    btn.addEventListener("click", () => {
      selectedSymbol = symbol;
      refreshWatchlistChips();
      loadSymbolDetail(symbol);
    });
    watchlistChips.appendChild(btn);
  });

  loadSymbolDetail(selectedSymbol);
}

async function loadConfig() {
  const data = await cachedGetJson("/api/portfolio/watchlist-config", "portfolio:watchlist-config", 120000);
  loadWatchlistRows(data.watchlist_symbols || []);
  populateQuickSelect(data.watchlist_symbols || []);
}

async function saveConfig(event) {
  event.preventDefault();
  const payload = {
    watchlist_symbols: collectWatchlistSymbols(),
  };
  const res = await fetch("/api/portfolio/watchlist-config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    setResult(`Lưu thất bại: ${JSON.stringify(data)}`);
    return;
  }
  invalidateCachePrefixes(["portfolio:watchlist-config", "market:watchlist-snapshots"]);
  loadWatchlistRows(data.watchlist_symbols || []);
  populateQuickSelect(data.watchlist_symbols || []);
  setResult("Đã lưu cấu hình theo dõi thành công.");
}

async function triggerJob(endpoint) {
  setResult(`Đang chạy ${endpoint} ...`);
  const res = await fetch(endpoint, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    setResult(`Tác vụ lỗi: ${JSON.stringify(data)}`);
    return;
  }
  invalidateCachePrefixes(["advice:latest", "market:watchlist-snapshots", "market:snapshot:", "alerts:list"]);
  setResult(JSON.stringify(data, null, 2));
  refreshWatchlistChips();
}

document.getElementById("watchlistForm").addEventListener("submit", saveConfig);
document.getElementById("runEtlBtn").addEventListener("click", () => triggerJob("/api/jobs/run-etl"));
document.getElementById("runAdviceBtn").addEventListener("click", () => triggerJob("/api/jobs/run-advice"));
addWatchlistBtn.addEventListener("click", () => addWatchlistRow());
if (addSelectedBtn && quickSymbolSelect) {
  addSelectedBtn.addEventListener("click", () => {
    const selected = Array.from(quickSymbolSelect.selectedOptions || []).map((opt) => normalizeSymbol(opt.value));
    if (!selected.length) {
      setResult("Chưa chọn mã nào trong hộp chọn nhiều.");
      return;
    }
    const added = addSymbolsToWatchlist(selected);
    populateQuickSelect();
    if (added > 0) {
      setResult(`Đã thêm ${added} mã vào danh sách theo dõi.`);
    } else {
      setResult("Các mã đã chọn đều đã có sẵn trong danh sách theo dõi.");
    }
  });
}

async function bootstrap() {
  try {
    await loadConfig();
  } catch (err) {
    setResult(err.message);
    loadWatchlistRows([]);
    populateQuickSelect([]);
  }
}

bootstrap();
