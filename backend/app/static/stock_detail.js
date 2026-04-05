const page = document.getElementById("detailPage");
const symbol = (page?.dataset?.symbol || "").toUpperCase();

const marketCard = document.getElementById("marketCard");
const financialCard = document.getElementById("financialCard");
const annualQualityCard = document.getElementById("annualQualityCard");
const decisionCard = document.getElementById("decisionCard");
const alertsCard = document.getElementById("alertsCard");
const daysSelect = document.getElementById("daysSelect");
const historyTableBody = document.getElementById("historyTableBody");
const historyEmpty = document.getElementById("historyEmpty");
const historyFlowSummary = document.getElementById("historyFlowSummary");
let latestClosePrice = Number.NaN;
let latestSnapshotDate = "-";

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

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("vi-VN");
}

function formatBillionVnd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const billion = Number(value) / 1_000_000_000;
  return billion.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatSignedPercent(value) {
  if (!Number.isFinite(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

function getManualReference() {
  return window.ManualRecoData?.items?.[symbol] || null;
}

function calcPctToSell(close, sell) {
  const c = Number(close || 0);
  const s = Number(sell || 0);
  if (!Number.isFinite(c) || !Number.isFinite(s) || c <= 0 || s <= 0) return Number.NaN;
  return ((s - c) / c) * 100;
}

function tipLabel(label, tip) {
  return `<span class="metric-label">${label} <span class="tip-badge" title="${tip}">?</span></span>`;
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

async function loadSnapshot() {
  try {
    const data = await cachedGetJson(
      `/api/market/${encodeURIComponent(symbol)}/snapshot`,
      `market:snapshot:${symbol}`,
      45000
    );
    const market = data.market || {};
    const financial = data.financial || {};
    const manual = getManualReference();
    latestClosePrice = Number(market.close_price);
    latestSnapshotDate = market.snapshot_date || "-";

    marketCard.className = "card";
    marketCard.innerHTML = `
      <div><b>${tipLabel("Ngày", "Ngày giao dịch của snapshot gần nhất")}</b>: ${market.snapshot_date || "-"}</div>
      <div><b>${tipLabel("Close (nghìn đồng/cp)", "Giá đóng cửa của phiên")}</b>: ${formatNumber(market.close_price)}</div>
    `;

    financialCard.className = "card";
    financialCard.innerHTML = `
      <div><b>${tipLabel("P/E", "Giá thị trường / Lợi nhuận trên mỗi cổ phiếu")}</b>: ${formatNumber(financial.pe)}</div>
      <div><b>${tipLabel("P/B", "Giá thị trường / Giá trị sổ sách")}</b>: ${formatNumber(financial.pb)}</div>
      <div><b>${tipLabel("ROE", "Lợi nhuận trên vốn chủ sở hữu")}</b>: ${formatNumber(financial.roe)}</div>
      <div><b>${tipLabel("Debt/Equity", "Tổng nợ / Vốn chủ sở hữu")}</b>: ${formatNumber(financial.debt_to_equity)}</div>
    `;

    annualQualityCard.className = "card";
    annualQualityCard.innerHTML = `
      <div><b>${tipLabel("Cổ tức tiền mặt tham khảo", "Nhập tay theo bảng tham khảo tháng 04/2026")}</b>: ${
        manual?.annual_dividend ? `${formatNumber(manual.annual_dividend)} ₫/năm` : "-"
      }</div>
      <div class="helper-text">Mốc cổ tức/mua/bán hiển thị theo dữ liệu nhập tay, không dùng tính toán tự động từ server.</div>
    `;
  } catch (err) {
    marketCard.className = "card muted";
    marketCard.textContent = err.message;
    financialCard.className = "card muted";
    financialCard.textContent = "Không có dữ liệu cơ bản.";
    annualQualityCard.className = "card muted";
    annualQualityCard.textContent = "Không có dữ liệu theo năm.";
  }
}

async function loadDecision() {
  const manual = getManualReference();
  if (!manual) {
    decisionCard.className = "card muted";
    decisionCard.textContent = "Chưa có mốc mua/bán nhập tay cho mã này.";
    return;
  }

  const close = Number(latestClosePrice);
  const buy = Number(manual.buy_price || 0);
  const sell = Number(manual.sell_price || 0);
  const toSellPct = calcPctToSell(close, sell);
  const toBuyPct = Number.isFinite(close) && close > 0 && buy > 0 ? ((buy - close) / close) * 100 : Number.NaN;

  let action = "Giữa vùng mua-bán";
  if (Number.isFinite(close) && buy > 0 && close <= buy) action = "Trong vùng mua";
  if (Number.isFinite(close) && sell > 0 && close >= sell) action = "Đạt vùng bán";

  decisionCard.className = "card";
  decisionCard.innerHTML = `
    <div><b>Nguồn mốc:</b> Nhập tay theo bảng tham khảo tháng 04/2026</div>
    <div><b>Phiên gần nhất:</b> ${latestSnapshotDate}</div>
    <div><b>Giá đóng cửa (nghìn đồng/cp):</b> ${formatNumber(close)}</div>
    <div><b>Giá mua / bán tham khảo (nghìn đồng/cp):</b> ${formatNumber(buy)} / ${formatNumber(sell)}</div>
    <div><b>Chênh lệch tới giá bán:</b> ${Number.isFinite(toSellPct) ? `${formatNumber(toSellPct.toFixed(2))}%` : "-"}</div>
    <div><b>Chênh lệch so với giá mua:</b> ${Number.isFinite(toBuyPct) ? `${formatNumber(toBuyPct.toFixed(2))}%` : "-"}</div>
    <div><b>Cổ tức tiền mặt tham khảo:</b> ${manual.annual_dividend ? `${formatNumber(manual.annual_dividend)} ₫/năm` : "-"}</div>
    <div><b>Trạng thái:</b> ${action}</div>
  `;
}

async function loadAlerts() {
  alertsCard.innerHTML = "";
  try {
    const data = await cachedGetJson("/api/alerts", "alerts:list", 30000);
    const rows = (Array.isArray(data) ? data : []).filter((x) => x.symbol === symbol).slice(0, 10);
    if (!rows.length) {
      alertsCard.innerHTML = '<div class="card muted">Chưa có cảnh báo cho mã này.</div>';
      return;
    }

    alertsCard.innerHTML = rows
      .map(
        (a) => `
      <div class="item alert-item ${a.severity || "medium"}">
        <div><b>${a.alert_type}</b> <span class="pill">${a.severity}</span></div>
        <div>${a.message}</div>
        <div class="muted">${a.created_at}</div>
      </div>`
      )
      .join("");
  } catch (err) {
    alertsCard.innerHTML = `<div class="card muted">Lỗi tải cảnh báo: ${err.message}</div>`;
  }
}

async function loadHistory(days) {
  historyTableBody.innerHTML = "";
  historyEmpty.style.display = "none";
  if (historyFlowSummary) {
    historyFlowSummary.className = "card muted";
    historyFlowSummary.textContent = "Đang tải thống kê dòng tiền theo kỳ...";
  }

  try {
    const rows = await cachedGetJson(
      `/api/market/${encodeURIComponent(symbol)}/history?days=${days}`,
      `market:history:${symbol}:${days}`,
      90000
    );
    if (!Array.isArray(rows) || !rows.length) {
      historyEmpty.style.display = "block";
      if (historyFlowSummary) {
        historyFlowSummary.className = "card muted";
        historyFlowSummary.textContent = "Không có dữ liệu để tính dòng tiền kỳ này.";
      }
      return;
    }

    const foreignSum = rows.reduce((acc, row) => acc + Number(row.foreign_net_value || 0), 0);
    const proprietarySum = rows.reduce((acc, row) => acc + Number(row.proprietary_net_value || 0), 0);
    const retailSum = rows.reduce((acc, row) => acc + Number(row.retail_estimated_value || 0), 0);
    if (historyFlowSummary) {
      historyFlowSummary.className = "card";
      historyFlowSummary.innerHTML = `
        <div><b>Tổng ngoại ròng ${days} ngày:</b> ${formatBillionVnd(foreignSum)} tỷ đồng</div>
        <div><b>Tổng tự doanh ròng ${days} ngày:</b> ${formatBillionVnd(proprietarySum)} tỷ đồng</div>
        <div><b>Tổng nhỏ lẻ ước tính ${days} ngày:</b> ${formatBillionVnd(retailSum)} tỷ đồng</div>
      `;
    }

    rows.forEach((row, index) => {
      const prevClose = Number(rows[index + 1]?.close_price || 0);
      const close = Number(row.close_price || 0);
      const changePct = prevClose > 0 && close > 0 ? ((close - prevClose) / prevClose) * 100 : Number.NaN;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td data-label="Phiên">${row.snapshot_date || "-"}</td>
        <td data-label="Mở cửa">${formatNumber(row.open_price)}</td>
        <td data-label="Cao nhất">${formatNumber(row.high_price)}</td>
        <td data-label="Thấp nhất">${formatNumber(row.low_price)}</td>
        <td data-label="Đóng cửa">${formatNumber(row.close_price)}</td>
        <td data-label="Biến động">${formatSignedPercent(changePct)}</td>
        <td data-label="KLượng">${formatNumber(row.volume)}</td>
        <td data-label="Ngoại ròng">${formatBillionVnd(row.foreign_net_value)}</td>
        <td data-label="Tự doanh ròng">${formatBillionVnd(row.proprietary_net_value)}</td>
        <td data-label="Nhỏ lẻ">${formatBillionVnd(row.retail_estimated_value)}</td>
      `;
      historyTableBody.appendChild(tr);
    });
  } catch (err) {
    historyEmpty.style.display = "block";
    historyEmpty.textContent = `Lỗi tải lịch sử: ${err.message}`;
    if (historyFlowSummary) {
      historyFlowSummary.className = "card muted";
      historyFlowSummary.textContent = `Không tính được dòng tiền kỳ này: ${err.message}`;
    }
  }
}

async function bootstrap() {
  await loadSnapshot();
  await Promise.all([loadDecision(), loadAlerts(), loadHistory(Number(daysSelect?.value || 5))]);
}

if (daysSelect) {
  daysSelect.addEventListener("change", () => {
    loadHistory(Number(daysSelect.value || 5));
  });
}

// --- Tab Navigation ---
document.addEventListener("DOMContentLoaded", () => {
  const tabNav = document.getElementById("detailTabs");
  if (!tabNav) return;
  tabNav.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.tab;
      tabNav.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".tab-content").forEach((tc) => {
        tc.classList.toggle("active", tc.id === targetId);
      });
    });
  });
});

bootstrap();
