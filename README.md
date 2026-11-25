# 투핸즈 현금흐름

주식회사 투핸즈의 농협 법인통장과 카드 사용액을 읽어 월별 현금흐름을 보여주는 페이지입니다.

페이지: https://raw.githack.com/dusohn/twohands/main/site/index.html

화면은 dusohn/Cashflow와 같은 헤더, Dashboard·Cashflow·Cards 탭, 표 양식입니다. 숫자는 `main`의 `data/cashflow.json`을 읽습니다.

통장 잔액과 통장 입출금은 `data/bank_nh.json`입니다. 농협 법인통장(NH더퍼스트기업통장, 끝자리 6481) 빠른조회만 넣습니다. 계좌번호 전체, 비밀번호, 사업자번호는 저장하지 않습니다. 카드 사용액만 자비스에서 읽습니다. 자비스를 읽지 못하면 `data/cashflow.json`에 마지막으로 저장한 카드 금액을 유지하고 통장은 그대로 갱신합니다. 자비스가 다시 붙어도 통장 숫자는 자비스로 바꾸지 않습니다.

예정 매출과 예정 지출은 화면에서 날짜와 공급가액을 입력한 뒤 저장하면 `data/plans.json`의 `sales`, `expenses`에 기록됩니다. 매일 갱신해도 그 파일은 유지됩니다. `data/vat_settled.json`에 적힌 신고월의 매출 부가세도 갱신 때 유지됩니다. 2026년 7–9월분은 10월 통장 출금 3,542,780원으로 이미 납부해서, 공급가액의 10%를 그 위에 다시 빼지 않습니다. 지출은 공급가액입니다. 그 달 통장 출금은 공급가액에 부가세 10%를 더한 금액이고, 매입세액은 1·4·7·10월 납부액에서 빼지 않습니다. 이미 지난 달의 예정 지출은 다시 반영하지 않습니다. 통장에 찍힌 입금이 예정 매출의 공급가액에 부가세 10%를 더한 금액과 같으면, 그 매출은 이미 들어온 것으로 보고 같은 금액을 다시 더하지 않습니다.

`data/statement.json`은 2026년 11월에 자비스가 멈춰 있을 때 적어 둔 현대카드 내역입니다. 갱신 스크립트는 이 파일을 읽지 않습니다. 그 카드 금액은 이미 `data/cashflow.json`에 있고, 자비스를 읽지 못하는 동안 그 값을 유지합니다.

로컬 화면은 `python3 scripts/serve_site.py`로 엽니다. 공개 페이지에서 저장하면 GitHub 이슈 창이 열리고, 그 이슈를 제출하면 Actions가 저장소 secret `TWOHANDS_TOCKEN`을 읽어 `data/plans.json`에 기록합니다. 토큰은 페이지에 넣지 않습니다. 이 secret에는 Contents 읽기 및 쓰기 권한이 있는 GitHub 토큰을 넣습니다.

## 통장 파일

매일 아침 한국시간 06:40 무렵, 다른 컴퓨터가 농협 기업뱅킹 빠른조회를 읽어 `data/bank_nh.json`을 `main`에 커밋합니다. 07:00 갱신 전에 그 커밋이 들어와 있어야 합니다. 파일에 들어 있는 달은 그 달 거래의 전체이고, 빠져 있는 달은 이미 게시된 통장 숫자를 유지합니다. 조회한 달에 거래가 없으면 `transactions`는 빈 목록입니다. 같은 거래가 두 번 있으면 한 번만 셉니다. 순서는 상관없습니다.

```json
{
  "account": "****6481",
  "queriedAt": "2026-11-25T13:43:24+09:00",
  "balance": 88114537,
  "available": 88114537,
  "transactions": [
    {
      "datetime": "2026-11-18T20:03:16+09:00",
      "deposit": 61600000,
      "withdrawal": 0,
      "balanceAfter": 88114537,
      "description": "E-하나은행",
      "memo": "(주)더린킨"
    }
  ]
}
```

`account`는 별과 끝 네 자리만 허용합니다. `queriedAt`과 `datetime`은 시간대가 있는 ISO 8601입니다. 금액은 원 단위 정수입니다. `balance`가 현재 통장 잔액이고, `available`은 출금가능액입니다. 화면의 거래 이름은 `memo`이고, 비어 있으면 `description`을 씁니다. 적요에 카드가 들어 있는 출금은 카드 대금으로, 부가세가 들어 있는 출금은 부가세 납부로 집계합니다.

## 매일 07:00 갱신

GitHub Actions에는 예약이 없습니다. grok-bot이 한국시간 07:00에 `refresh-cashflow.yml`을 `workflow_dispatch`로 실행합니다. 그 워크플로가 `data/bank_nh.json`의 통장과 자비스의 카드 사용액을 읽어 `data/cashflow.json`을 다시 씁니다. 자비스 응답이 비어 있거나 로그인에 실패해도 워크플로는 멈추지 않습니다. 그때는 저장된 카드 금액으로 통장만 갱신합니다. 워크플로 파일은 기본 브랜치에 있어야 합니다.

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
