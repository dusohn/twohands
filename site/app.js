const LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const LOCAL_DATA = ["../data/cashflow.json", "./cashflow.json"];
const LOCAL_PLANS = ["../data/plans.json", "./plans.json"];
let commitSha = null;

const TABS = [
  ["dashboard", "Dashboard"],
  ["cashflow", "Cashflow"],
  ["detail", "상세"],
  ["cards", "Cards"],
];

const REPO = "dusohn/twohands";
const state = {
  tab: "dashboard",
  year: null,
  detailMonth: null,
  sales: [],
  expenses: [],
  saveMessage: "",
  saveOk: false,
  saveLink: "",
};
let page = null;
let saveGeneration = 0;

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

function supplyDigits(value) {
  return String(value ?? "").replace(/[^\d]/g, "");
}

function formatSupply(value) {
  const digits = supplyDigits(value);
  if (!digits) return "";
  return fmt(Number(digits));
}

function supplyAmount(value) {
  const digits = supplyDigits(value);
  if (!digits) return 0;
  const amount = Number(digits);
  return Number.isFinite(amount) ? amount : 0;
}

function vatOf(supply) {
  return Math.round(supplyAmount(supply) * 0.1);
}

function planRow(kind, plan, dateLabel) {
  const supply = supplyAmount(plan.supply);
  const vat = vatOf(supply);
  return `<div class="form-grid plan-row" data-kind="${kind}">
    <div class="fld fld-date"><label>${dateLabel}</label><input type="date" data-field="date" value="${esc(plan.date || "")}"></div>
    <div class="fld fld-money"><label>공급가(원)</label><input data-field="supply" inputmode="numeric" value="${esc(formatSupply(plan.supply))}"></div>
    <div class="fld fld-money"><label>부가세(원)</label><input data-field="vat" readonly value="${fmt(vat)}"></div>
    <div class="fld fld-money"><label>총액(원)</label><input data-field="gross" readonly value="${fmt(supply + vat)}"></div>
    <div class="fld fld-note"><label>메모</label><input data-field="note" maxlength="80" value="${esc(plan.note || "")}"></div>
    <div class="fld"><label>&nbsp;</label><button type="button" class="btn btn-g" data-remove>삭제</button></div>
  </div>`;
}

function planEditor(kind, items, dateLabel, addLabel) {
  const rows = (items || []).map((plan) => planRow(kind, plan, dateLabel)).join("");
  return `${rows || '<p class="cf-note">입력된 항목이 없습니다.</p>'}
    <div class="plan-actions"><button type="button" class="btn btn-g" data-add="${kind}">${addLabel}</button></div>`;
}

function readKind(kind) {
  return [...document.querySelectorAll(`.plan-row[data-kind="${kind}"]`)].map((row) => ({
    date: row.querySelector('[data-field="date"]').value,
    supply: row.querySelector('[data-field="supply"]').value,
    note: row.querySelector('[data-field="note"]').value,
  }));
}

function capturePlans() {
  if (!document.querySelector(".plan-row, [data-add]")) return;
  state.sales = readKind("sales");
  state.expenses = readKind("expenses");
}

function plansIssueUrl(saved) {
  const body = [
    "이 이슈를 제출하면 예정 매출·지출이 data/plans.json에 저장됩니다.",
    "",
    "```json",
    JSON.stringify(saved, null, 2),
    "```",
  ].join("\n");
  const params = new URLSearchParams({ title: "save-plans", body });
  return `https://github.com/${REPO}/issues/new?${params}`;
}

function validDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function normalizeList(items) {
  const rows = [];
  for (const item of items) {
    const date = String(item.date || "").trim();
    const note = String(item.note || "").trim();
    const supplyText = String(item.supply ?? "").replace(/[,\s]/g, "");
    if (!date && !note && !supplyText) continue;
    if (!validDate(date)) throw new Error("날짜는 YYYY-MM-DD로 입력합니다.");
    if (!/^\d+$/.test(supplyText) || Number(supplyText) <= 0) {
      throw new Error("공급가액은 0보다 큰 정수로 입력합니다.");
    }
    if (note.length > 80) throw new Error("메모는 80자까지 입력합니다.");
    const row = { date, supply: Number(supplyText) };
    if (note) row.note = note;
    rows.push(row);
  }
  if (rows.length > 50) throw new Error("항목은 50개까지 입력합니다.");
  rows.sort((a, b) => a.date.localeCompare(b.date) || a.supply - b.supply || (a.note || "").localeCompare(b.note || ""));
  return rows;
}

function plansDocument() {
  return { sales: normalizeList(state.sales), expenses: normalizeList(state.expenses) };
}

function samePlans(left, right) {
  return JSON.stringify(normalizeList(left || [])) === JSON.stringify(normalizeList(right || []));
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
  const plans = planEditor("sales", state.sales, "입금 예정일", "매출 추가");
  const expenses = planEditor("expenses", state.expenses, "출금 예정일", "지출 추가");
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
            <td style="text-align:center"><button type="button" class="month-link" data-detail-month="${row.month}">${ym(row.year, row.month)}</button></td>
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
    <div class="cf-card" id="planEditor">
      <h2>예정 매출 <span class="file-tag">data/plans.json · sales</span></h2>
      <p class="cf-note">금액은 공급가액입니다. 통장 입금은 부가세 10%를 더한 총액이고, 부가세는 1월·4월·7월·10월에 납부합니다.</p>
      ${plans}
    </div>
    <div class="cf-card">
      <h2>예정 지출 <span class="file-tag">data/plans.json · expenses</span></h2>
      <p class="cf-note">금액은 공급가액입니다. 그 달 통장 출금은 부가세 10%를 더한 총액입니다. 매입세액은 1·4·7·10월 납부액에서 빼지 않습니다. 이미 지난 달은 다시 반영하지 않습니다.</p>
      ${expenses}
      <div class="plan-save">
        <div class="btns"><button type="button" class="btn btn-p" id="savePlans">매출·지출을 plans.json에 저장</button></div>
        <p class="cf-note save-status ${state.saveMessage ? (state.saveOk ? "ok" : "err") : ""}" id="saveStatus">${esc(state.saveMessage)}</p>
        ${state.saveLink ? `<p class="cf-note"><a href="${esc(state.saveLink)}" target="_blank" rel="noopener">GitHub에서 저장 이슈 열기</a></p>` : ""}
        <p class="cf-note">${LOCAL ? "이 화면의 저장은 data/plans.json에 바로 기록하고 현금흐름을 다시 계산합니다." : "저장하면 GitHub 창이 열립니다. 그 창에서 Submit new issue를 누르면 Actions가 secret TWOHANDS_TOCKEN을 읽어 data/plans.json에 저장합니다."}</p>
      </div>
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
      <p class="cf-note">자비스 원장과 화면에서 저장한 예정 매출, 예정 지출로 집계합니다. 지출은 음수로 표시합니다. 카드 대금은 사용 다음 달 통장 출금이고, 매출 부가세는 1·4·7·10월 통장 출금에 포함됩니다. 2026년 7–9월분은 10월 통장 출금 3,542,780원으로 이미 나갔고, 공급가액의 10%를 그 위에 다시 빼지 않습니다. 예정 지출은 그 달 통장 출금에 공급가액과 부가세 10%가 함께 나갑니다. 매출·매입·카드는 발생 기준 참고 금액입니다.</p>
      <div class="tbl-wrap" style="max-height:72vh; overflow:auto;">
      <table class="cf">
        <tr><th class="sticky-col" style="z-index:2; text-align:center">구분</th>${rows
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

function selectedDetailMonth(data) {
  if (state.detailMonth >= 1 && state.detailMonth <= 12) return state.detailMonth;
  const parts = String(data.asOf || "").split("-");
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  if (year === state.year && month >= 1 && month <= 12) return month;
  return 1;
}

function detailTable(title, lines, total, sign) {
  const body = lines.length
    ? lines
        .map(
          (line) => `<tr>
            <td>${esc(line.name)}</td>
            <td class="${cls(sign * line.amount)}">${fmt(sign * line.amount)}</td>
            <td class="detail-note">${esc(line.note || "")}</td>
          </tr>`
        )
        .join("")
    : '<tr><td colspan="3" class="empty">항목이 없습니다.</td></tr>';
  return `<div class="cf-card">
      <h2>${title}</h2>
      <div class="tbl-wrap"><table class="cf detail">
        <tr><th style="text-align:left">항목</th><th class="num">금액</th><th style="text-align:left">내용</th></tr>
        ${body}
        <tr class="row-sum"><td>합계</td><td class="${cls(sign * total)}">${fmt(sign * total)}</td><td></td></tr>
      </table></div>
    </div>`;
}

function renderDetail(data, rows) {
  const month = selectedDetailMonth(data);
  state.detailMonth = month;
  const row = rows[month - 1];
  const income = row.income || [];
  const expense = row.expense || [];
  const months = Array.from({ length: 12 }, (_, index) => index + 1);
  return `
    <div class="toolbar">${months
      .map(
        (item) =>
          `<button type="button" class="btn ${item === month ? "btn-p" : "btn-g"}" data-month="${item}">${item}월</button>`
      )
      .join("")}</div>
    <div class="cf-card">
      <h2>${row.year}년 ${row.month}월 수입·지출 ${statusBadge(row.status, row.endCash)}</h2>
      <p class="cf-note">수입은 그 달 통장 입금이고, 지출은 그 달 통장 출금입니다. 예정 매출과 예정 지출은 공급가액에 부가세 10%를 더한 총액입니다. 이미 나간 금액은 잔고에 반영되어 있습니다.</p>
      <div class="kpis">
        <div class="kpi"><div class="k">수입</div><div class="v pos">${fmt(row.bankIn)}원</div></div>
        <div class="kpi"><div class="k">지출</div><div class="v neg">${fmt(-row.bankOut)}원</div></div>
        <div class="kpi"><div class="k">순현금흐름</div><div class="v ${row.bankIn - row.bankOut < 0 ? "neg" : "pos"}">${fmt(row.bankIn - row.bankOut)}원</div></div>
        <div class="kpi"><div class="k">기말 현금</div><div class="v ${row.endCash < 0 ? "neg" : ""}">${fmt(row.endCash)}원</div></div>
      </div>
    </div>
    <div class="detail-grid">
      ${detailTable("수입", income, row.bankIn, 1)}
      ${detailTable("지출", expense, row.bankOut, -1)}
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
        <tr><th style="text-align:left">분류</th><th class="num">금액</th><th class="num">비중</th></tr>
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
      capturePlans();
      state.tab = button.dataset.tab;
      render(data);
    };
  });
  const rows = rowsForYear(data, state.year);
  const body = document.getElementById("tabBody");
  const view =
    state.tab === "cashflow"
      ? renderCashflow(data, rows)
      : state.tab === "detail"
        ? renderDetail(data, rows)
        : state.tab === "cards"
          ? renderCards(data)
          : renderDashboard(data, rows);
  body.innerHTML = yearButtons(years) + view;
  body.querySelectorAll("[data-year]").forEach((button) => {
    button.onclick = () => {
      capturePlans();
      state.year = Number(button.dataset.year);
      render(data);
    };
  });
  body.querySelectorAll("[data-month]").forEach((button) => {
    button.onclick = () => {
      state.detailMonth = Number(button.dataset.month);
      render(data);
    };
  });
  body.querySelectorAll("[data-detail-month]").forEach((button) => {
    button.onclick = () => {
      capturePlans();
      state.detailMonth = Number(button.dataset.detailMonth);
      state.tab = "detail";
      render(data);
    };
  });
  bindPlanEditor(data);
}

function bindPlanEditor(data) {
  const body = document.getElementById("tabBody");
  if (!body) return;
  body.querySelectorAll("[data-add]").forEach((button) => {
    button.onclick = () => {
      capturePlans();
      const kind = button.dataset.add;
      state[kind].push({ date: "", supply: "", note: "" });
      render(data);
    };
  });
  body.querySelectorAll("[data-remove]").forEach((button) => {
    button.onclick = () => {
      const row = button.closest(".plan-row");
      const kind = row.dataset.kind;
      const index = [...document.querySelectorAll(`.plan-row[data-kind="${kind}"]`)].indexOf(row);
      capturePlans();
      state[kind].splice(index, 1);
      render(data);
    };
  });
  body.addEventListener("input", (event) => {
    const row = event.target.closest(".plan-row");
    if (!row || event.target.dataset.field !== "supply") return;
    const input = event.target;
    const cursor = input.selectionStart ?? input.value.length;
    const digitsBefore = supplyDigits(input.value.slice(0, cursor)).length;
    const formatted = formatSupply(input.value);
    input.value = formatted;
    let next = formatted.length;
    if (digitsBefore === 0) next = 0;
    else {
      let seen = 0;
      for (let index = 0; index < formatted.length; index += 1) {
        if (/\d/.test(formatted[index])) seen += 1;
        if (seen === digitsBefore) {
          next = index + 1;
          break;
        }
      }
    }
    input.setSelectionRange(next, next);
    const supply = supplyAmount(formatted);
    const vat = vatOf(supply);
    row.querySelector('[data-field="vat"]').value = fmt(vat);
    row.querySelector('[data-field="gross"]').value = fmt(supply + vat);
  });
  const save = document.getElementById("savePlans");
  if (save) save.onclick = () => savePlans(data);
}

function applySaved(data, saved, cashflow) {
  state.sales = saved.sales.map((row) => ({ ...row }));
  state.expenses = saved.expenses.map((row) => ({ ...row }));
  if (cashflow) {
    page = cashflow;
    page.plans = saved.sales;
    page.expenses = saved.expenses;
  } else if (page) {
    page.plans = saved.sales;
    page.expenses = saved.expenses;
  }
  render(page || data);
}

async function savePlans(data) {
  capturePlans();
  const button = document.getElementById("savePlans");
  let saved;
  try {
    saved = plansDocument();
  } catch (error) {
    state.saveOk = false;
    state.saveMessage = error.message;
    render(data);
    return;
  }
  if (button) button.disabled = true;
  state.saveMessage = "저장하는 중입니다.";
  state.saveOk = true;
  const status = document.getElementById("saveStatus");
  if (status) status.textContent = state.saveMessage;
  try {
    if (LOCAL) {
      const response = await fetch("/api/plans", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(saved),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "저장하지 못했습니다.");
      state.saveOk = true;
      state.saveMessage = payload.cashflow
        ? "plans.json에 저장하고 현금흐름을 다시 계산했습니다."
        : "plans.json에 저장했습니다. 현금흐름 숫자는 다음 자비스 갱신에 반영됩니다.";
      applySaved(data, payload.plans, payload.cashflow);
      return;
    }
    await savePlansGitHub(saved);
  } catch (error) {
    state.saveOk = false;
    state.saveLink = "";
    state.saveMessage = error.message || "저장하지 못했습니다.";
    render(page || data);
  }
}

async function savePlansGitHub(saved) {
  if (page && samePlans(page.plans, saved.sales) && samePlans(page.expenses, saved.expenses)) {
    state.saveOk = true;
    state.saveLink = "";
    state.saveMessage = "plans.json과 같습니다.";
    applySaved(page, saved, null);
    return;
  }
  const url = plansIssueUrl(saved);
  const opened = window.open(url, "_blank", "noopener");
  state.saveOk = true;
  state.saveLink = opened ? "" : url;
  state.saveMessage = "열린 GitHub 창에서 Submit new issue를 누르면 secret TWOHANDS_TOCKEN으로 plans.json에 저장됩니다.";
  applySaved(page, saved, null);
  pollSavedPlans(saved, ++saveGeneration);
}

async function pollSavedPlans(saved, generation) {
  for (let attempt = 0; attempt < 24; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    if (generation !== saveGeneration) return;
    try {
      await refreshCommit();
      const plans = await loadPlans();
      if (!plans || !samePlans(plans.sales, saved.sales) || !samePlans(plans.expenses, saved.expenses)) continue;
      const fresh = await loadData();
      if (generation !== saveGeneration) return;
      const cashflowReady = fresh && samePlans(fresh.expenses, saved.expenses) && samePlans(fresh.plans, saved.sales);
      state.saveLink = "";
      state.saveOk = true;
      state.saveMessage = cashflowReady
        ? "plans.json에 저장하고 현금흐름을 다시 계산했습니다."
        : "plans.json에 저장했습니다. 현금흐름 숫자는 다음 아침 갱신에 반영됩니다.";
      applySaved(page, saved, cashflowReady ? fresh : null);
      return;
    } catch (error) {
      /* keep waiting for the Actions commit */
    }
  }
  if (generation !== saveGeneration) return;
  state.saveOk = true;
  state.saveMessage = "이슈를 제출하면 저장됩니다. 반영까지 조금 걸릴 수 있습니다.";
  const status = document.getElementById("saveStatus");
  if (status) status.textContent = state.saveMessage;
}

function remoteUrls(path) {
  const urls = [];
  if (commitSha) urls.push(`https://raw.githubusercontent.com/${REPO}/${commitSha}/${path}`);
  urls.push(`https://api.github.com/repos/${REPO}/contents/${path}?ref=main`);
  urls.push(`https://raw.githubusercontent.com/${REPO}/main/${path}`);
  return urls;
}

async function latestSha() {
  const response = await fetch(`https://api.github.com/repos/${REPO}/commits/main`, {
    cache: "no-store",
    headers: {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  if (!response.ok) return null;
  const payload = await response.json();
  return typeof payload.sha === "string" ? payload.sha : null;
}

async function refreshCommit() {
  if (LOCAL) return;
  try {
    commitSha = await latestSha();
  } catch (error) {
    commitSha = null;
  }
}

async function loadJson(candidates) {
  let lastError = null;
  for (const url of candidates) {
    try {
      const headers = url.includes("api.github.com")
        ? { Accept: "application/vnd.github.raw", "X-GitHub-Api-Version": "2022-11-28" }
        : {};
      const response = await fetch(url, { cache: "no-store", headers });
      if (!response.ok) continue;
      return await response.json();
    } catch (error) {
      lastError = error;
    }
  }
  if (lastError) throw lastError;
  return null;
}

async function loadData() {
  const urls = LOCAL ? LOCAL_DATA : remoteUrls("data/cashflow.json");
  return (await loadJson(urls)) || Promise.reject(new Error("cashflow.json을 찾지 못했습니다"));
}

async function loadPlans() {
  try {
    const urls = LOCAL ? LOCAL_PLANS : remoteUrls("data/plans.json");
    return await loadJson(urls);
  } catch (error) {
    return null;
  }
}

refreshCommit()
  .then(() => loadData())
  .then(async (data) => {
    page = data;
    const plans = await loadPlans();
    state.sales = ((plans && plans.sales) || data.plans || []).map((row) => ({ ...row }));
    state.expenses = ((plans && plans.expenses) || data.expenses || []).map((row) => ({ ...row }));
    if (plans) {
      page.plans = plans.sales || [];
      page.expenses = plans.expenses || [];
    }
    render(page);
  })
  .catch((error) => {
    document.getElementById("cfApp").innerHTML = `<p class="empty">숫자를 불러오지 못했습니다. ${esc(error.message)}</p>`;
  });
