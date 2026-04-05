const actionResult = document.getElementById("actionResult");
const positionsListAttack = document.getElementById("positionsListAttack");
const positionsListBalance = document.getElementById("positionsListBalance");
const positionsListDefense = document.getElementById("positionsListDefense");
const addPositionBtnAttack = document.getElementById("addPositionBtnAttack");
const addPositionBtnBalance = document.getElementById("addPositionBtnBalance");
const addPositionBtnDefense = document.getElementById("addPositionBtnDefense");
const allocationCard = document.getElementById("allocationCard");
const targetCashInput = document.getElementById("target_cash_ratio");
const targetStockInput = document.getElementById("target_stock_ratio");
const targetAttackInput = document.getElementById("target_attack_stock_ratio");
const targetBalanceInput = document.getElementById("target_balance_stock_ratio");
const targetDefenseInput = document.getElementById("target_defense_stock_ratio");

const GROUP_KEYS = ["attack", "balance", "defense"];
const GROUP_LABELS = {
  attack: "Tấn công",
  balance: "Cân bằng",
  defense: "Phòng thủ",
};
const GROUP_OVERRIDE_KEY = "holdings-group-overrides:v1";
let draggingRow = null;
const GROUP_RATIO_WARN_TOLERANCE = 0.05;

function buildGroupMap() {
  const map = new Map();
  const groups = window.ManualRecoData?.groups || {};
  GROUP_KEYS.forEach((group) => {
    (groups[group] || []).forEach((symbol) => {
      map.set(normalizeSymbol(symbol), group);
    });
  });
  return map;
}

const symbolGroupMap = buildGroupMap();

function loadGroupOverrides() {
  try {
    const raw = window.localStorage.getItem(GROUP_OVERRIDE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_) {
    return {};
  }
}

let groupOverrides = loadGroupOverrides();

function saveGroupOverrides() {
  try {
    window.localStorage.setItem(GROUP_OVERRIDE_KEY, JSON.stringify(groupOverrides));
  } catch (_) {
    // Ignore localStorage write failures.
  }
}

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

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("vi-VN");
}

function formatPercent(ratio) {
  return Number(ratio || 0).toLocaleString("vi-VN", { maximumFractionDigits: 1 });
}

function formatSignedPercent(value) {
  if (!Number.isFinite(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

function normalizeStockGroupRatios(attackRaw, balanceRaw, defenseRaw) {
  const attack = Math.max(0, Number(attackRaw || 0));
  const balance = Math.max(0, Number(balanceRaw || 0));
  const defense = Math.max(0, Number(defenseRaw || 0));
  const total = attack + balance + defense;
  if (total <= 0) {
    return { attack: 0.34, balance: 0.33, defense: 0.33 };
  }
  return {
    attack: attack / total,
    balance: balance / total,
    defense: defense / total,
  };
}

function collectCurrentGroupStockRatios() {
  const values = { attack: 0, balance: 0, defense: 0 };
  Array.from(document.querySelectorAll(".position-row")).forEach((row) => {
    const symbol = normalizeSymbol(row.querySelector('[data-role="symbol"]')?.value || "");
    const qty = Number(row.querySelector('[data-role="quantity"]')?.value || 0);
    const price = Number(row.querySelector('[data-role="current_price"]')?.value || 0);
    if (!symbol || !Number.isFinite(qty) || !Number.isFinite(price) || qty <= 0 || price <= 0) return;
    const group = normalizeGroup(row.dataset.group || resolveGroupForSymbol(symbol));
    values[group] += qty * price;
  });
  const total = values.attack + values.balance + values.defense;
  if (total <= 0) {
    return { values, ratios: { attack: 0, balance: 0, defense: 0 }, total: 0 };
  }
  return {
    values,
    ratios: {
      attack: values.attack / total,
      balance: values.balance / total,
      defense: values.defense / total,
    },
    total,
  };
}

function setResult(text, type = "info") {
  actionResult.textContent = text;
  if (window.Toast && text && text !== "Sẵn sàng.") {
    window.Toast[type] ? window.Toast[type](text) : window.Toast.info(text);
  }
}

function normalizeSymbol(value) {
  return String(value || "").trim().toUpperCase();
}

function normalizeGroup(group) {
  return GROUP_KEYS.includes(group) ? group : "balance";
}

function guessGroupForSymbol(symbol) {
  const code = normalizeSymbol(symbol);
  return symbolGroupMap.get(code) || "balance";
}

function resolveGroupForSymbol(symbol) {
  const code = normalizeSymbol(symbol);
  return normalizeGroup(groupOverrides[code] || guessGroupForSymbol(code));
}

function setGroupOverride(symbol, group) {
  const code = normalizeSymbol(symbol);
  if (!code) return;
  groupOverrides[code] = normalizeGroup(group);
  saveGroupOverrides();
}

function removeGroupOverride(symbol) {
  const code = normalizeSymbol(symbol);
  if (!code || !Object.prototype.hasOwnProperty.call(groupOverrides, code)) return;
  delete groupOverrides[code];
  saveGroupOverrides();
}

function getPositionsListByGroup(group) {
  const key = normalizeGroup(group);
  if (key === "attack") return positionsListAttack;
  if (key === "defense") return positionsListDefense;
  return positionsListBalance;
}

function getGroupFromListElement(listElement) {
  if (listElement === positionsListAttack) return "attack";
  if (listElement === positionsListDefense) return "defense";
  return "balance";
}

function countPositionRows() {
  return document.querySelectorAll(".position-row").length;
}

function getDragAfterElement(container, y) {
  const candidates = Array.from(container.querySelectorAll(".position-row:not(.dragging)"));
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

function updateRowGroup(row, group, announce = true) {
  const targetGroup = normalizeGroup(group);
  row.dataset.group = targetGroup;
  const symbol = normalizeSymbol(row.querySelector('[data-role="symbol"]').value);
  if (symbol) setGroupOverride(symbol, targetGroup);
  if (announce) {
    setResult(`Đã chuyển ${symbol || "vị thế"} sang nhóm ${GROUP_LABELS[targetGroup]}.`);
  }
  loadAllocation().catch(() => {});
}

function bindRowDragEvents(row) {
  row.setAttribute("draggable", "true");
  row.addEventListener("dragstart", (event) => {
    draggingRow = row;
    row.classList.add("dragging");
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", row.querySelector('[data-role="symbol"]').value || "");
    }
  });
  row.addEventListener("dragend", () => {
    row.classList.remove("dragging");
    draggingRow = null;
    document.querySelectorAll(".holdings-group-card").forEach((card) => {
      card.classList.remove("drag-over");
    });
  });
}

function setupGroupDragAndDrop() {
  const cards = Array.from(document.querySelectorAll(".holdings-group-card"));
  cards.forEach((card) => {
    const list = card.querySelector(".editable-list");
    const group = normalizeGroup(card.dataset.group || getGroupFromListElement(list));

    card.addEventListener("dragover", (event) => {
      if (!draggingRow) return;
      event.preventDefault();
      card.classList.add("drag-over");
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = "move";
      }
      const afterElement = getDragAfterElement(list, event.clientY);
      if (!afterElement) {
        list.appendChild(draggingRow);
      } else {
        list.insertBefore(draggingRow, afterElement);
      }
    });
    card.addEventListener("dragenter", (event) => {
      if (!draggingRow) return;
      event.preventDefault();
      card.classList.add("drag-over");
    });
    card.addEventListener("dragleave", (event) => {
      if (event.relatedTarget && card.contains(event.relatedTarget)) return;
      card.classList.remove("drag-over");
    });
    card.addEventListener("drop", (event) => {
      if (!draggingRow) return;
      event.preventDefault();
      card.classList.remove("drag-over");
      const afterElement = getDragAfterElement(list, event.clientY);
      if (!afterElement) {
        list.appendChild(draggingRow);
      } else {
        list.insertBefore(draggingRow, afterElement);
      }
      updateRowGroup(draggingRow, group);
    });
  });
}

function renderNoticeList(items, type, emptyText) {
  const rows = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!rows.length) {
    return `<div class="notice-list"><div class="notice-chip empty">${emptyText}</div></div>`;
  }
  return `<div class="notice-list">${rows
    .map((text) => `<div class="notice-chip ${type}">${text}</div>`)
    .join("")}</div>`;
}

function createPositionRow(position = {}, group = "balance") {
  const wrapper = document.createElement("div");
  wrapper.className = "editable-row position-row";
  wrapper.dataset.group = normalizeGroup(group);
  wrapper.dataset.symbol = normalizeSymbol(position.symbol);
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
      <label>Giá vốn TB (nghìn đồng/cp)</label>
      <input data-role="avg_cost" type="number" min="0" step="0.01" value="${position.avg_cost ?? ""}" />
    </div>
    <div class="field-row">
      <label>Giá hiện tại (nghìn đồng/cp)</label>
      <input data-role="current_price" type="number" min="0" step="0.01" value="${position.current_price ?? ""}" readonly />
    </div>
    <div class="field-row">
      <label>Ngừng tích sản (nghìn)</label>
      <input data-role="stop" type="number" min="0" step="0.01" value="${position.stop_accumulate_price ?? ""}" />
    </div>
    <div class="field-row">
      <label>Chốt lời (nghìn)</label>
      <input data-role="take" type="number" min="0" step="0.01" value="${position.take_profit_price ?? ""}" />
    </div>
    <div class="field-row">
      <label>Chênh lệch tới bán (%)</label>
      <input data-role="spread_pct" type="text" value="-" readonly />
    </div>
    <button type="button" class="danger" data-role="remove">Xoá</button>
  `;

  const updateSpread = () => {
    const currentPrice = Number(wrapper.querySelector('[data-role="current_price"]').value);
    const take = Number(wrapper.querySelector('[data-role="take"]').value);
    const spreadInput = wrapper.querySelector('[data-role="spread_pct"]');
    if (!Number.isFinite(currentPrice) || !Number.isFinite(take) || currentPrice <= 0 || take <= 0) {
      spreadInput.value = "-";
      return;
    }
    spreadInput.value = formatSignedPercent(((take - currentPrice) / currentPrice) * 100);
  };

  wrapper.querySelector('[data-role="symbol"]').addEventListener("input", (e) => {
    const previousSymbol = wrapper.dataset.symbol || "";
    e.target.value = normalizeSymbol(e.target.value);
    const currentSymbol = normalizeSymbol(e.target.value);
    wrapper.dataset.symbol = currentSymbol;
    if (previousSymbol && previousSymbol !== currentSymbol) {
      removeGroupOverride(previousSymbol);
    }
    if (currentSymbol) {
      setGroupOverride(currentSymbol, wrapper.dataset.group);
    }
    loadAllocation().catch(() => {});
  });
  wrapper.querySelector('[data-role="current_price"]').addEventListener("input", updateSpread);
  wrapper.querySelector('[data-role="take"]').addEventListener("input", updateSpread);
  wrapper.querySelector('[data-role="quantity"]').addEventListener("input", () => {
    loadAllocation().catch(() => {});
  });
  wrapper.querySelector('[data-role="current_price"]').addEventListener("input", () => {
    loadAllocation().catch(() => {});
  });
  wrapper.querySelector('[data-role="remove"]').addEventListener("click", () => {
    const symbol = wrapper.dataset.symbol || normalizeSymbol(wrapper.querySelector('[data-role="symbol"]').value);
    if (symbol) removeGroupOverride(symbol);
    wrapper.remove();
    if (countPositionRows() === 0) addPositionRow({}, "balance");
    loadAllocation().catch(() => {});
  });

  bindRowDragEvents(wrapper);
  updateSpread();

  return wrapper;
}

function addPositionRow(position = {}, group = "balance") {
  const normalizedGroup = normalizeGroup(group);
  const host = getPositionsListByGroup(normalizedGroup);
  const row = createPositionRow(position, normalizedGroup);
  host.appendChild(row);
  const symbol = normalizeSymbol(position.symbol);
  if (symbol) setGroupOverride(symbol, normalizedGroup);
}

function mergePositionsWithRules(positions = [], symbolRules = []) {
  const ruleMap = new Map(
    (symbolRules || []).map((rule) => [normalizeSymbol(rule.symbol), rule])
  );
  const seen = new Set();
  const merged = (positions || []).map((position) => {
    const symbol = normalizeSymbol(position.symbol);
    seen.add(symbol);
    const matchedRule = ruleMap.get(symbol) || {};
    return {
      ...position,
      symbol,
      stop_accumulate_price: matchedRule.stop_accumulate_price ?? null,
      take_profit_price: matchedRule.take_profit_price ?? null,
    };
  });

  for (const rule of symbolRules || []) {
    const symbol = normalizeSymbol(rule.symbol);
    if (!symbol || seen.has(symbol)) continue;
    merged.push({
      symbol,
      quantity: 0,
      avg_cost: 0,
      current_price: 0,
      stop_accumulate_price: rule.stop_accumulate_price ?? null,
      take_profit_price: rule.take_profit_price ?? null,
    });
  }

  return merged;
}

function loadPositionRows(positions = [], symbolRules = []) {
  positionsListAttack.innerHTML = "";
  positionsListBalance.innerHTML = "";
  positionsListDefense.innerHTML = "";
  const mergedRows = mergePositionsWithRules(positions, symbolRules);
  if (!mergedRows.length) {
    addPositionRow({}, "balance");
    return;
  }
  mergedRows.forEach((position) => {
    addPositionRow(position, resolveGroupForSymbol(position.symbol));
  });
}

function collectPositions() {
  return Array.from(document.querySelectorAll(".position-row"))
    .map((row) => {
      const symbol = normalizeSymbol(row.querySelector('[data-role="symbol"]').value);
      const quantity = Number(row.querySelector('[data-role="quantity"]').value);
      const avgCost = Number(row.querySelector('[data-role="avg_cost"]').value);
      return { symbol, quantity, avg_cost: avgCost };
    })
    .filter((x) => x.symbol && !Number.isNaN(x.quantity) && !Number.isNaN(x.avg_cost));
}

function collectSymbolRulesFromPositions() {
  return Array.from(document.querySelectorAll(".position-row"))
    .map((row) => {
      const symbol = normalizeSymbol(row.querySelector('[data-role="symbol"]').value);
      const stopRaw = row.querySelector('[data-role="stop"]').value;
      const takeRaw = row.querySelector('[data-role="take"]').value;
      const stop = stopRaw ? Number(stopRaw) : null;
      const take = takeRaw ? Number(takeRaw) : null;
      return {
        symbol,
        stop_accumulate_price: Number.isNaN(stop) ? null : stop,
        take_profit_price: Number.isNaN(take) ? null : take,
      };
    })
    .filter((x) => x.symbol && ((x.stop_accumulate_price ?? 0) > 0 || (x.take_profit_price ?? 0) > 0));
}

async function loadConfig(options = {}) {
  const data = await cachedGetJson("/api/portfolio/holdings-config", "portfolio:holdings-config", 120000, options);
  document.getElementById("cash").value = data.cash ?? 0;
  targetCashInput.value = data.target_cash_ratio ?? 0.5;
  targetStockInput.value = data.target_stock_ratio ?? 0.5;
  targetAttackInput.value = data.target_attack_stock_ratio ?? 0.34;
  targetBalanceInput.value = data.target_balance_stock_ratio ?? 0.33;
  targetDefenseInput.value = data.target_defense_stock_ratio ?? 0.33;
  loadPositionRows(data.positions || [], data.symbol_rules || []);
}

function buildHoldingsPayload() {
  const groupTargets = normalizeStockGroupRatios(targetAttackInput.value, targetBalanceInput.value, targetDefenseInput.value);
  return {
    cash: Number(document.getElementById("cash").value || 0),
    positions: collectPositions(),
    symbol_rules: collectSymbolRulesFromPositions(),
    target_cash_ratio: Number(targetCashInput.value || 0.5),
    target_attack_stock_ratio: groupTargets.attack,
    target_balance_stock_ratio: groupTargets.balance,
    target_defense_stock_ratio: groupTargets.defense,
  };
}

async function saveConfig(event) {
  event.preventDefault();
  const payload = buildHoldingsPayload();
  const res = await fetch("/api/portfolio/holdings-config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    setResult(`Lưu thất bại: ${JSON.stringify(data)}`, "error");
    return;
  }
  document.getElementById("cash").value = data.cash ?? 0;
  targetCashInput.value = data.target_cash_ratio ?? 0.5;
  targetStockInput.value = data.target_stock_ratio ?? 0.5;
  targetAttackInput.value = data.target_attack_stock_ratio ?? 0.34;
  targetBalanceInput.value = data.target_balance_stock_ratio ?? 0.33;
  targetDefenseInput.value = data.target_defense_stock_ratio ?? 0.33;
  loadPositionRows(data.positions || [], data.symbol_rules || []);
  invalidateCachePrefixes(["portfolio:holdings-config", "portfolio:allocation"]);
  setResult("Đã lưu cấu hình nắm giữ thành công.", "success");
  await updateDashboard({ bypassCache: true });
}

async function triggerEtl() {
  setResult("Đang lưu cấu hình và lấy dữ liệu thị trường...");

  const saveRes = await fetch("/api/portfolio/holdings-config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildHoldingsPayload()),
  });
  const saveData = await saveRes.json();
  if (!saveRes.ok) {
    setResult(`Lưu thất bại: ${JSON.stringify(saveData)}`, "error");
    return;
  }

  const etlRes = await fetch("/api/jobs/refresh-market", { method: "POST" });
  const etlData = await etlRes.json();
  if (!etlRes.ok) {
    setResult(`Tác vụ ETL lỗi: ${JSON.stringify(etlData)}`, "error");
    return;
  }

  const errors = etlData?.details?.errors || [];
  const marketSkipped = Number(etlData?.details?.market_skipped || 0);
  if (!etlData.ok || errors.length) {
    setResult(`Đã lấy dữ liệu nhưng có ${errors.length} lỗi nguồn dữ liệu. Vẫn cập nhật được phần còn lại.`, "warning");
  } else if (marketSkipped > 0) {
    setResult(`Đã bỏ qua ${marketSkipped} mã vì đã cập nhật trong ngày.`);
  } else {
    setResult("Đã lấy dữ liệu thị trường thành công.", "success");
  }

  invalidateCachePrefixes([
    "portfolio:holdings-config",
    "portfolio:allocation",
    "market:snapshot:",
    "market:history:",
  ]);
  await loadConfig({ bypassCache: true });
  await updateDashboard({ bypassCache: true });
}

let lastAllocationData = null;

async function updateDashboard(options = {}) {
  await fetchAllocationData(options);
  renderAllocationCard();
}

async function fetchAllocationData(options) {
  try {
    lastAllocationData = await cachedGetJson("/api/portfolio/allocation", "portfolio:allocation", 30000, options);
  } catch (err) {
    lastAllocationData = { error: err.message };
  }
}

async function loadAllocation(options = {}) {
  await fetchAllocationData(options);
  renderAllocationCard();
}

function renderAllocationCard() {
  if (!lastAllocationData || lastAllocationData.error) {
    allocationCard.className = "card muted";
    allocationCard.textContent = `Lỗi tải tỷ lệ tài sản: ${lastAllocationData?.error || "Unknown error"}`;
    return;
  }
  
  const data = lastAllocationData;
  const stockPct = formatPercent(Number(data.stock_ratio || 0) * 100);
  const cashPct = formatPercent(Number(data.cash_ratio || 0) * 100);
  const targetStockPct = formatPercent(Number(data.target_stock_ratio || 0) * 100);
  const targetCashPct = formatPercent(Number(data.target_cash_ratio || 0) * 100);
  const groupTargets = normalizeStockGroupRatios(targetAttackInput.value, targetBalanceInput.value, targetDefenseInput.value);
  const currentGroups = collectCurrentGroupStockRatios();
  const attackPct = formatPercent(groupTargets.attack * 100);
  const balancePct = formatPercent(groupTargets.balance * 100);
  const defensePct = formatPercent(groupTargets.defense * 100);
  const currentAttackPct = formatPercent(currentGroups.ratios.attack * 100);
  const currentBalancePct = formatPercent(currentGroups.ratios.balance * 100);
  const currentDefensePct = formatPercent(currentGroups.ratios.defense * 100);

  allocationCard.className = "card";
  allocationCard.innerHTML = `
    <div><b>Tổng tài sản:</b> ${formatNumber(data.total_assets || 0)} ₫</div>
    <div><b>Tiền mặt:</b> ${formatNumber(data.cash || 0)} ₫ (${cashPct}%) | mục tiêu ${targetCashPct}%</div>
    <div><b>Cổ phiếu:</b> ${formatNumber(data.stock_value || 0)} ₫ (${stockPct}%) | mục tiêu ${targetStockPct}%</div>
    <br/>
    <div><b>Phân bổ cổ phiếu:</b></div>
    <div style="padding-left: 10px;">- Tấn công ${currentAttackPct}% | mục tiêu ${attackPct}%</div>
    <div style="padding-left: 10px;">- Cân bằng ${currentBalancePct}% | mục tiêu ${balancePct}%</div>
    <div style="padding-left: 10px;">- Phòng thủ ${currentDefensePct}% | mục tiêu ${defensePct}%</div>
  `;
}

document.getElementById("holdingsForm").addEventListener("submit", saveConfig);
document.getElementById("runEtlBtn").addEventListener("click", triggerEtl);
if (addPositionBtnAttack) addPositionBtnAttack.addEventListener("click", () => addPositionRow({}, "attack"));
if (addPositionBtnBalance) addPositionBtnBalance.addEventListener("click", () => addPositionRow({}, "balance"));
if (addPositionBtnDefense) addPositionBtnDefense.addEventListener("click", () => addPositionRow({}, "defense"));
setupGroupDragAndDrop();

targetCashInput.addEventListener("input", () => {
  const cashRatio = Math.min(1, Math.max(0, Number(targetCashInput.value || 0)));
  targetCashInput.value = cashRatio;
  targetStockInput.value = (1 - cashRatio).toFixed(2);
});

targetStockInput.addEventListener("input", () => {
  const stockRatio = Math.min(1, Math.max(0, Number(targetStockInput.value || 0)));
  targetStockInput.value = stockRatio;
  targetCashInput.value = (1 - stockRatio).toFixed(2);
});

function normalizeStockGroupInputs() {
  const normalized = normalizeStockGroupRatios(targetAttackInput.value, targetBalanceInput.value, targetDefenseInput.value);
  targetAttackInput.value = normalized.attack.toFixed(2);
  targetBalanceInput.value = normalized.balance.toFixed(2);
  targetDefenseInput.value = normalized.defense.toFixed(2);
  loadAllocation().catch(() => {});
}

[targetAttackInput, targetBalanceInput, targetDefenseInput].forEach((input) => {
  input.addEventListener("change", normalizeStockGroupInputs);
});

async function bootstrap() {
  try {
    await loadConfig();
  } catch (err) {
    setResult(err.message);
    loadPositionRows([], []);
  }
  await updateDashboard();
}

bootstrap();
