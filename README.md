# 투핸즈 현금흐름

주식회사 투핸즈의 자비스 원장을 읽어 월별 현금흐름을 보여주는 페이지입니다.

페이지: https://raw.githack.com/dusohn/twohands/main/site/index.html

화면은 dusohn/Cashflow와 같은 헤더, Dashboard·Cashflow·Cards 탭, 표 양식입니다. 숫자는 `main`의 `data/cashflow.json`을 읽습니다.

자비스에서 읽은 최신 숫자는 `data/cashflow.json`입니다. 예정 매출과 예정 지출은 화면에서 날짜와 공급가액을 입력한 뒤 저장하면 `data/plans.json`의 `sales`, `expenses`에 기록됩니다. 매일 갱신해도 그 파일은 유지됩니다. `data/vat_settled.json`에 적힌 신고월의 매출 부가세도 갱신 때 유지됩니다. 2026년 7–9월분은 10월 통장 출금 3,542,780원으로 이미 납부해서, 공급가액의 10%를 그 위에 다시 빼지 않습니다. 지출은 공급가액입니다. 그 달 통장 출금은 공급가액에 부가세 10%를 더한 금액이고, 매입세액은 1·4·7·10월 납부액에서 빼지 않습니다. 이미 지난 달의 예정 지출은 다시 반영하지 않습니다. 계좌번호와 카드번호는 저장하지 않습니다.

로컬 화면은 `python3 scripts/serve_site.py`로 엽니다. 공개 페이지에서 저장하면 GitHub 이슈 창이 열리고, 그 이슈를 제출하면 Actions가 저장소 secret `TWOHANDS_TOCKEN`을 읽어 `data/plans.json`에 기록합니다. 토큰은 페이지에 넣지 않습니다. 이 secret에는 Contents 읽기 및 쓰기 권한이 있는 GitHub 토큰을 넣습니다.

## 매일 07:00 갱신

GitHub Actions에는 예약이 없습니다. grok-bot이 한국시간 07:00에 `refresh-cashflow.yml`을 `workflow_dispatch`로 실행합니다. 그 워크플로가 자비스에 로그인해서 `data/cashflow.json`을 다시 씁니다. 워크플로 파일은 기본 브랜치에 있어야 합니다.

grok-bot 스케줄은 UTC `0 22 * * *`입니다. 봇의 GitHub 연결에 Actions 쓰기 권한이 있어야 합니다.

```ts
import { defineSchedule } from "@cursor/bdk/schedules";

export default defineSchedule({
  cron: "0 22 * * *",
  async run({ host }) {
    const octokit = await host.github.getOctokit();
    await octokit.rest.actions.createWorkflowDispatch({
      owner: "dusohn",
      repo: "twohands",
      workflow_id: "refresh-cashflow.yml",
      ref: "main",
    });
  },
});
```

저장소 Actions 비밀에 다음 두 값을 넣어야 합니다.

- `JOBIS_EMAIL`
- `JOBIS_PASSWORD`

Actions 권한은 워크플로가 `data/cashflow.json`을 푸시할 수 있게 읽기 및 쓰기여야 합니다.
