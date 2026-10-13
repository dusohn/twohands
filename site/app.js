const LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const PUBLISHED = [
  "https://raw.githubusercontent.com/dusohn/twohands/main/data/cashflow.json",
  "https://raw.githubusercontent.com/dusohn/twohands/cursor/cashflow-page-64ed/data/cashflow.json",
];
const DATA_CANDIDATES = LOCAL
  ? ["../data/cashflow.json", "./cashflow.json", ...PUBLISHED]
  : [...PUBLISHED, "../data/cashflow.json", "./cashflow.json"];

const won = (value) => {
  const sign = value < 0 ? "-" : "";
  return `${sign}${Math.abs(Math.round(value)).toLocaleString("ko-KR")}원`;
};

const man = (value) => Math.round(value / 10000);

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

function render(data) {
  const years = [...new Set(data.rows.map((row) => row.year))];
  const initial = years.includes(new Date(data.asOf).getUTCFullYear())
    ? new Date(data.asOf).getUTCFullYear()
    : years[0];
  const state = { year: initial };

  document.getElementById("meta").innerHTML = `
    <p>자비스 기준일 ${data.asOf}</p>
    <p>갱신 ${data.updatedAt.replace("T", " ").replace("+09:00", " KST")}</p>
    <p>매일 07:00 KST에 다시 읽습니다</p>
  `;

  const app = document.getElementById("app");
  app.innerHTML = `
    <div class="toolbar">
      <div class="years" id="years"></div>
    </div>
    <section class="stats" id="stats"></section>
    <section class="panel">
      <h2 id="balance-title"></h2>
      <div class="chart" id="balance"></div>
      <p class="caption">세로축은 만원. 0원 아래는 잔고가 부족한 달입니다.</p>
    </section>
    <section class="panel">
      <h2 id="flow-title"></h2>
      <div class="chart" id="flow"></div>
      <p class="caption">초록 막대는 매출 공급가액, 갈색 막대는 매입과 카드 지출의 합입니다. 단위는 만원.</p>
    </section>
    <section class="panel">
      <h2 id="table-title"></h2>
      <div class="table-wrap" id="table"></div>
    </section>
    <section class="panel">
      <h2>${data.cardMixMonth} 카드 구성</h2>
      <div class="table-wrap" id="mix"></div>
    </section>
    <section class="assumptions">
      <h2>계산</h2>
      <ul>${(data.assumptions || []).map((item) => `<li>${item}</li>`).join("")}</ul>
      <p>월 지출 예상 ${won(data.baseExpense)}. 예정 매출은 data/plans.json에 있습니다.</p>
    </section>
  `;

  const yearBox = document.getElementById("years");
  const draw = () => {
    yearBox.innerHTML = years
      .map(
        (year) =>
          `<button type="button" aria-pressed="${year === state.year}" data-year="${year}">${year}</button>`
      )
      .join("");
    yearBox.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        state.year = Number(button.dataset.year);
        draw();
      });
    });
    const rows = data.rows.filter((row) => row.year === state.year);
    drawStats(data, rows);
    document.getElementById("balance-title").textContent = `${state.year}년 월말 통장 잔고`;
    document.getElementById("flow-title").textContent = `${state.year}년 매출과 지출`;
    document.getElementById("table-title").textContent = `${state.year}년 1–12월`;
    document.getElementById("balance").innerHTML = lineChart(rows);
    document.getElementById("flow").innerHTML = barChart(rows);
    document.getElementById("table").innerHTML = monthTable(rows);
  };
  draw();
  document.getElementById("mix").innerHTML = mixTable(data);
}

function drawStats(data, rows) {
  const yearSales = rows.reduce((sum, row) => sum + row.sales, 0);
  const yearEnd = rows.length ? rows[rows.length - 1].endCash : 0;
  const depletion = data.depletion
    ? `${data.depletion.year}년 ${data.depletion.month}월 ${data.depletion.day}일께`
    : "표시 기간 이후";
  document.getElementById("stats").innerHTML = `
    <div class="stat"><span>${data.asOf} 통장 잔고</span><strong>${won(data.cashNow)}</strong></div>
    <div class="stat good"><span>선택 연도 매출 공급가액</span><strong>${won(yearSales)}</strong></div>
    <div class="stat"><span>선택 연도 12월말 잔고</span><strong>${won(yearEnd)}</strong></div>
    <div class="stat danger"><span>잔고가 닿는 때</span><strong>${depletion}</strong></div>
  `;
}

function lineChart(rows) {
  const values = rows.map((row) => man(row.endCash));
  return svgFrame(rows, values, (points, y) => {
    const line = points
      .map((point, index) => `${index === 0 ? "M" : "L"}${point.x} ${y(man(point.row.endCash))}`)
      .join(" ");
    const dots = points
      .map(
        (point) =>
          `<circle cx="${point.x}" cy="${y(man(point.row.endCash))}" r="3.5" fill="${point.row.endCash < 0 ? "#8d2f2f" : "#8d4b28"}"/>`
      )
      .join("");
    return `<path d="${line}" fill="none" stroke="#1c1915" stroke-width="2"/>${dots}`;
  }, true);
}

function barChart(rows) {
  return svgFrame(rows, rows.flatMap((row) => [man(row.sales), man(row.purchase + row.card)]), (points, y) => {
    const width = 10;
    return points
      .map((point) => {
        const sales = man(point.row.sales);
        const spend = man(point.row.purchase + point.row.card);
        return `
          <rect x="${point.x - width - 1}" y="${y(sales)}" width="${width}" height="${Math.max(0, y(0) - y(sales))}" fill="#1d6b48"/>
          <rect x="${point.x + 1}" y="${y(spend)}" width="${width}" height="${Math.max(0, y(0) - y(spend))}" fill="#8d4b28"/>
        `;
      })
      .join("");
  }, false);
}

function svgFrame(rows, values, mark, showZero) {
  const width = 680;
  const height = 240;
  const pad = { l: 48, r: 12, t: 16, b: 28 };
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values, 1);
  const y = (value) => pad.t + ((max - value) / (max - min)) * (height - pad.t - pad.b);
  const step = (width - pad.l - pad.r) / Math.max(rows.length, 1);
  const points = rows.map((row, index) => ({ row, x: pad.l + step * index + step / 2 }));
  const labels = points
    .map((point) => `<text class="axis" x="${point.x}" y="${height - 8}" text-anchor="middle">${point.row.month}</text>`)
    .join("");
  const zero = showZero
    ? `<line class="zero" x1="${pad.l}" x2="${width - pad.r}" y1="${y(0)}" y2="${y(0)}"/>`
    : "";
  return `<svg viewBox="0 0 ${width} ${height}" role="img">${zero}${mark(points, y)}${labels}<text class="axis" x="4" y="14">${Math.round(max).toLocaleString("ko-KR")}</text></svg>`;
}

function monthTable(rows) {
  const body = rows
    .map((row) => {
      const klass = row.endCash < 0 ? "neg" : row.status === "예정" ? "plan" : row.status === "진행" ? "live" : "";
      return `<tr class="${klass}"><td>${row.month}월</td><td>${row.status}</td><td>${won(row.sales)}</td><td>${won(row.purchase)}</td><td>${won(row.card)}</td><td>${won(row.bankIn)}</td><td>${won(row.bankOut)}</td><td>${won(row.endCash)}</td></tr>`;
    })
    .join("");
  return `<table><thead><tr><th>월</th><th>상태</th><th>매출</th><th>매입</th><th>카드 지출</th><th>통장 입금</th><th>통장 출금</th><th>월말 잔고</th></tr></thead><tbody>${body}</tbody></table>`;
}

function mixTable(data) {
  const total = (data.cardMix || []).reduce((sum, row) => sum + row.amount, 0) || 1;
  const body = (data.cardMix || [])
    .map(
      (row) =>
        `<tr><td>${row.name}</td><td>${won(row.amount)}</td><td>${((row.amount / total) * 100).toFixed(1)}%</td></tr>`
    )
    .join("");
  return `<table class="mix"><thead><tr><th>분류</th><th>금액</th><th>비중</th></tr></thead><tbody>${body}</tbody></table>`;
}

loadData().then(render).catch((error) => {
  document.getElementById("app").innerHTML = `<p class="loading">숫자를 불러오지 못했습니다. ${error.message}</p>`;
});
