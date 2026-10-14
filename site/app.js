const LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const DATA_CANDIDATES = LOCAL
  ? ["../data/cashflow.json", "./cashflow.json"]
  : [
      "https://raw.githubusercontent.com/dusohn/twohands/main/data/cashflow.json",
      "../data/cashflow.json",
      "./cashflow.json",
    ];

const TABS = [
  ["dashboard", "Dashboard"],
  ["cashflow", "Cashflow"],
  ["cards", "Cards"],
];

const state = { tab: "dashboard", year: null };

function fmt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "";
  const value = Math.round(n);
  const text = Math.abs(value).toLocaleString("ko-KR");
  return value < 0 ? `(${text})` : text;
}

function cls(n) {
  return n < 0 ? "num neg" : n > 0 ? "num pos" : "num";
}

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function pad(month) {
  return String(month).padStart(2, "0");
}

function ym(year, month) {
  return `${year}-${pad(month)}`;
}

function rowsForYear(data, year) {
  const found = new Map(data.rows.filter((row) => row.year === year).map((row) => [row.month, row]));
  return Array.from({ length: 12 }, (_, index) => {
    const month = index + 1;
    return (
      found.get(month) || {
        year,
        month,
        status: "",
        sales: 0,
        purchase: 0,
        card: 0,
        bankIn: 0,
        bankOut: 0,
        endCash: 0,
      }
    );
  });
}

function openingCash(data, rows, index) {
  if (index > 0) return rows[index - 1].endCash;
  const row = rows[0];
  const previous = data.rows.find((item) => item.year === row.year - 1 && item.month === 12);
  if (previous) return previous.endCash;
  return row.endCash - row.bankIn + row.bankOut;
}

function statusBadge(status, endCash) {
  if (endCash < 0) return '<span class="badge b-warn">부족</span>';
  if (status === "실제") return '<span class="badge b-done">실제</span>';
  if (status === "진행") return '<span class="badge b-plan">진행</span>';
  if (status === "예정") return '<span class="badge b-ok">예정</span>';
  if (status === "예상") return '<span class="badge b-hold">예상</span>';
  return "";
}

function yearButtons(years) {
  return `<div class="toolbar">${years
    .map(
      (year) =>
        `<button type="button" class="btn ${year === state.year ? "btn-p" : "btn-g"}" data-year="${year}">${year}</button>`
    )
    .join("")}</div>`;
}

function chartSvg(rows) {
  const net = rows.map((row) => row.bankIn - row.bankOut);
  const close = rows.map((row) => row.endCash);
  const width = 980;
  const height = 280;
  const padBox = { l: 78, r: 24, t: 16, b: 34 };
  const slot = (width - padBox.l - padBox.r) / 12;
  const values = net.concat(close, [0]);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const y = (value) => padBox.t + ((max - value) / span) * (height - padBox.t - padBox.b);
  let bars = "";
  let line = "";
  let dots = "";
  let labels = "";
  rows.forEach((row, index) => {
    const x = padBox.l + index * slot;
    const barHeight = Math.abs(y(net[index]) - y(0));
    bars += `<rect x="${x + slot * 0.18}" y="${Math.min(y(net[index]), y(0))}" width="${slot * 0.42}" height="${Math.max(barHeight, 1)}" fill="${net[index] >= 0 ? "#0E8A5F" : "#D64545"}" opacity="0.75" rx="2"></rect>`;
    const cx = x + slot * 0.5;
    const cy = y(close[index]);
    line += `${index ? "L" : "M"}${cx} ${cy} `;
    dots += `<circle cx="${cx}" cy="${cy}" r="3.2" fill="#2B5FAD"></circle>`;
    labels += `<text x="${cx}" y="${height - 10}" font-size="10" fill="#4A5A72" text-anchor="middle">${String(row.year).slice(2)}-${pad(row.month)}</text>`;
  });
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" style="min-width:min(720px,140vw)" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="현금흐름 차트">
    <line x1="${padBox.l}" x2="${width - padBox.r}" y1="${y(0)}" y2="${y(0)}" stroke="#C9D2DF"></line>
    ${bars}<path d="${line}" fill="none" stroke="#2B5FAD" stroke-width="2.2"></path>${dots}${labels}
    <text x="${padBox.l - 6}" y="${y(max) + 8}" font-size="10" fill="#4A5A72" text-anchor="end">${fmt(max)}</text>
    <text x="${padBox.l - 6}" y="${y(0) + 4}" font-size="10" fill="#4A5A72" text-anchor="end">0</text>
    <text x="${padBox.l - 6}" y="${y(min)}" font-size="10" fill="#4A5A72" text-anchor="end">${min < 0 ? fmt(min) : ""}</text>
  </svg>`;
}

function renderDashboard(data, rows) {
  const opening = rows.map((_, index) => openingCash(data, rows, index));
  const net = rows.map((row) => row.bankIn - row.bankOut);
  const yearSales = rows.reduce((sum, row) => sum + row.sales, 0);
  const endCash = rows[rows.length - 1].endCash;
  const minCash = Math.min(...rows.map((row) => row.endCash));
  const avgNet = net.reduce((sum, value) => sum + value, 0) / 12;
  const depletion = data.depletion
    ? `${data.depletion.year}년 ${data.depletion.month}월 ${data.depletion.day}일께`
    : "표시 기간 이후";
  const plans = (data.plans || [])
    .map((plan) => {
      const vat = Math.round(plan.supply * 0.1);
      return `<div class="form-grid">
        <div class="fld"><label>입금 예정일</label><input readonly value="${esc(plan.date)}"></div>
        <div class="fld"><label>공급가(원)</label><input readonly value="${fmt(plan.supply)}"></div>
        <div class="fld"><label>부가세(원)</label><input readonly value="${fmt(vat)}"></div>
        <div class="fld"><label>총액(원)</label><input readonly value="${fmt(plan.supply + vat)}"></div>
      </div>`;
    })
    .join("");
  return `
    <div class="kpis">
      <div class="kpi"><div class="k">${esc(data.asOf)} 통장 잔고</div><div class="v">${fmt(data.cashNow)}원</div></div>
      <div class="kpi"><div class="k">${state.year} 매출 공급가액</div><div class="v pos">${fmt(yearSales)}원</div></div>
      <div class="kpi"><div class="k">12월말 현금</div><div class="v ${endCash < 0 ? "neg" : ""}">${fmt(endCash)}원</div></div>
      <div class="kpi"><div class="k">연중 최저 현금</div><div class="v ${minCash < 0 ? "neg" : ""}">${fmt(minCash)}원</div></div>
      <div class="kpi"><div class="k">월평균 순현금흐름</div><div class="v ${avgNet < 0 ? "neg" : "pos"}">${fmt(avgNet)}원</div></div>
      <div class="kpi"><div class="k">잔고가 닿는 때</div><div class="v ${data.depletion ? "neg" : ""}">${esc(depletion)}</div></div>
    </div>
    <div class="cf-card"><h2>월별 순현금흐름 · 기말현금 추이</h2>
      <p class="cf-note">막대: 월 순현금흐름(통장 입금−통장 출금) / 선: 기말 현금. 기초 ${fmt(opening[0])}원.</p>
      <div class="chart-wrap">${chartSvg(rows)}</div>
    </div>
    <div class="cf-card"><h2>월별 현금 잔액 요약</h2>
      <div class="tbl-wrap"><table class="cf">
        <tr><th style="text-align:center">월</th><th class="num">기초현금</th><th class="num">수입</th><th class="num">지출</th>
            <th class="num">순현금흐름</th><th class="num">기말현금</th><th style="text-align:center">상태</th></tr>
        ${rows
          .map(
            (row, index) => `<tr>
            <td style="text-align:center">${ym(row.year, row.month)}</td>
            <td class="num">${fmt(opening[index])}</td>
            <td class="${cls(row.bankIn)}">${fmt(row.bankIn)}</td>
            <td class="${cls(-row.bankOut)}">${fmt(-row.bankOut)}</td>
            <td class="${cls(net[index])}">${fmt(net[index])}</td>
            <td class="num" style="font-weight:700">${fmt(row.endCash)}</td>
            <td style="text-align:center">${statusBadge(row.status, row.endCash)}</td>
          </tr>`
          )
          .join("")}
      </table></div>
    </div>
    <div class="cf-card">
      <h2>예정 매출 <span class="file-tag">data/plans.json</span></h2>
      <p class="cf-note">금액은 공급가액입니다. 통장 입금은 부가세 10%를 더한 총액이고, 부가세는 1월·4월·7월·10월에 납부합니다.</p>
      ${plans || '<p class="empty">예정 매출이 없습니다.</p>'}
    </div>
    <div class="cf-card"><h2>계산</h2>
      <ul class="assumptions">${(data.assumptions || []).map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
      <p class="cf-note">월 지출 예상 ${fmt(data.baseExpense)}원.</p>
    </div>`;
}

function matrixRow(label, values, klass) {
  const total = values.reduce((sum, value) => sum + value, 0);
  return `<tr class="${klass || ""}"><td class="sticky-col">${label}</td>
    ${values.map((value) => `<td class="${cls(value)}">${value ? fmt(value) : "0"}</td>`).join("")}
    <td class="${cls(total)}" style="font-weight:700">${fmt(total)}</td></tr>`;
}

function renderCashflow(data, rows) {
  const opening = rows.map((_, index) => openingCash(data, rows, index));
  const inflow = rows.map((row) => row.bankIn);
  const outflow = rows.map((row) => -row.bankOut);
  const sales = rows.map((row) => row.sales);
  const purchase = rows.map((row) => -row.purchase);
  const card = rows.map((row) => -row.card);
  const net = rows.map((row) => row.bankIn - row.bankOut);
  const close = rows.map((row) => row.endCash);
  const blanks = rows.map(() => "");
  const section = (title) =>
    `<tr class="row-sec"><td class="sticky-col">${title}</td>${blanks.map(() => "<td></td>").join("")}<td></td></tr>`;
  return `
    <div class="cf-card">
      <h2>Cashflow — 월별 현금흐름 12개월 전망</h2>
      <p class="cf-note">자비스 원장과 예정 매출로 집계합니다. 지출은 음수로 표시합니다. 카드 대금은 사용 다음 달 통장 출금이고, 부가세는 1·4·7·10월 통장 출금에 포함됩니다. 매출·매입·카드는 발생 기준 참고 금액입니다.</p>
      <div class="tbl-wrap" style="max-height:72vh; overflow:auto;">
      <table class="cf">
        <tr><th class="sticky-col" style="z-index:2">구분</th>${rows
          .map((row) => `<th class="num">${ym(row.year, row.month)}</th>`)
          .join("")}<th class="num" style="text-align:center">합계</th></tr>
        ${matrixRow("기초 현금", opening, "row-sum")}
        ${section("영업 현금유입")}
        ${matrixRow("통장 입금", inflow)}
        ${matrixRow("영업 현금유입 합계", inflow, "row-sum")}
        ${section("영업 현금유출")}
        ${matrixRow("통장 출금", outflow)}
        ${matrixRow("영업 현금유출 합계", outflow, "row-sum")}
        ${section("발생 기준 참고")}
        ${matrixRow("매출 공급가액", sales)}
        ${matrixRow("매입", purchase)}
        ${matrixRow("카드 지출", card)}
        ${matrixRow("월 순현금흐름", net, "row-sum")}
        ${matrixRow("기말 현금", close, "row-final")}
      </table></div>
    </div>`;
}

function renderCards(data) {
  const mix = data.cardMix || [];
  const total = mix.reduce((sum, row) => sum + row.amount, 0) || 1;
  const body = mix.length
    ? mix
        .map(
          (row) => `<tr>
            <td>${esc(row.name)}</td>
            <td class="num" style="font-weight:700">${fmt(row.amount)}</td>
            <td class="num">${((row.amount / total) * 100).toFixed(1)}%</td>
          </tr>`
        )
        .join("")
    : '<tr><td colspan="3" class="empty">카드 구성이 없습니다.</td></tr>';
  return `
    <div class="cf-card">
      <h2>${esc(data.cardMixMonth || "")} 카드 구성 <span class="file-tag">자비스 카드매입</span></h2>
      <p class="cf-note">지난달 승인 금액입니다. 취소는 제외하고, 해외 결제는 원화 환산 금액을 씁니다.</p>
      <div class="tbl-wrap"><table class="cf">
        <tr><th>분류</th><th class="num">금액</th><th class="num">비중</th></tr>
        ${body}
        <tr class="row-sum"><td class="sticky-col">합계</td><td class="num">${fmt(mix.reduce((sum, row) => sum + row.amount, 0))}</td><td class="num">100%</td></tr>
      </table></div>
    </div>`;
}

function render(data) {
  const years = [...new Set(data.rows.map((row) => row.year))];
  if (!years.includes(state.year)) {
    const asOfYear = Number(String(data.asOf).slice(0, 4));
    state.year = years.includes(asOfYear) ? asOfYear : years[0];
  }
  const updated = String(data.updatedAt || "").replace("T", " ").replace("+09:00", " KST");
  const root = document.getElementById("cfApp");
  root.innerHTML = `
    <div class="cf-head"><h1>TWOHANDS Cashflow</h1><span class="sub">12개월 현금흐름 전망 · 자비스 ${esc(data.asOf)}</span>
      <span class="sub" id="syncBadge" style="margin-left:auto">갱신 ${esc(updated)}</span></div>
    <div class="cf-tabs">${TABS.map(
      ([key, label]) =>
        `<button type="button" class="cf-tab ${state.tab === key ? "on" : ""}" data-tab="${key}">${label}</button>`
    ).join("")}</div>
    <div class="cf-body" id="tabBody"></div>`;
  root.querySelectorAll(".cf-tab").forEach((button) => {
    button.onclick = () => {
      state.tab = button.dataset.tab;
      render(data);
    };
  });
  const rows = rowsForYear(data, state.year);
  const body = document.getElementById("tabBody");
  const view =
    state.tab === "cashflow"
      ? renderCashflow(data, rows)
      : state.tab === "cards"
        ? renderCards(data)
        : renderDashboard(data, rows);
  body.innerHTML = yearButtons(years) + view;
  body.querySelectorAll("[data-year]").forEach((button) => {
    button.onclick = () => {
      state.year = Number(button.dataset.year);
      render(data);
    };
  });
}

async function loadData() {
  let lastError = null;
  for (const url of DATA_CANDIDATES) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) continue;
      return await response.json();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("cashflow.json을 찾지 못했습니다");
}

loadData()
  .then(render)
  .catch((error) => {
    document.getElementById("cfApp").innerHTML = `<p class="empty">숫자를 불러오지 못했습니다. ${esc(error.message)}</p>`;
  });
