# 투핸즈 현금흐름

주식회사 투핸즈의 자비스 원장을 읽어 월별 현금흐름을 보여주는 페이지입니다.

페이지: https://raw.githack.com/dusohn/twohands/main/site/index.html

화면은 dusohn/Cashflow와 같은 헤더, Dashboard·Cashflow·Cards 탭, 표 양식입니다. 숫자는 `main`의 `data/cashflow.json`을 읽습니다.

자비스에서 읽은 최신 숫자는 `data/cashflow.json`입니다. 예정 매출과 예정 지출은 `data/plans.json`의 `sales`, `expenses`에 있고, 매일 갱신해도 그 파일은 유지됩니다. 지출은 공급가액으로 넣습니다. 그 달 통장 출금은 공급가액에 부가세 10%를 더한 금액이고, 매입세액은 1·4·7·10월 납부액에서 빼지 않습니다. 이미 지난 달의 예정 지출은 다시 반영하지 않습니다. 계좌번호와 카드번호는 저장하지 않습니다.

```json
{ "date": "2026-12-15", "supply": 1000000, "note": "외주" }
```

## 매일 07:00 갱신

`.github/workflows/refresh-cashflow.yml`이 한국시간 07:00(UTC 22:00)에 자비스에 로그인해서 `data/cashflow.json`을 다시 씁니다. 이 일정은 기본 브랜치에 워크플로가 있어야 실행됩니다.

저장소 Actions 비밀에 다음 두 값을 넣어야 합니다.

- `JOBIS_EMAIL`
- `JOBIS_PASSWORD`

Actions 권한은 워크플로가 `data/cashflow.json`을 푸시할 수 있게 읽기 및 쓰기여야 합니다.
