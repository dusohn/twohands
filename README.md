# 투핸즈 현금흐름

주식회사 투핸즈의 자비스 원장을 읽어 월별 현금흐름을 보여주는 페이지입니다.

페이지: https://rawcdn.githack.com/dusohn/twohands/2526f650e13dea028dbb833d0d161cc66f30275c/site/index.html

숫자는 `data/cashflow.json`에서 읽습니다. 기본 브랜치에 올라간 뒤에는 매일 아침 그 파일을 다시 받습니다.

자비스에서 읽은 최신 숫자는 `data/cashflow.json`입니다. 예정 매출은 `data/plans.json`에 있고, 매일 갱신해도 그 파일은 유지됩니다. 계좌번호와 카드번호는 저장하지 않습니다.

## 매일 07:00 갱신

`.github/workflows/refresh-cashflow.yml`이 한국시간 07:00(UTC 22:00)에 자비스에 로그인해서 `data/cashflow.json`을 다시 씁니다. 이 일정은 기본 브랜치에 워크플로가 있어야 실행됩니다.

저장소 Actions 비밀에 다음 두 값을 넣어야 합니다.

- `JOBIS_EMAIL`
- `JOBIS_PASSWORD`

Actions 권한은 워크플로가 `data/cashflow.json`을 푸시할 수 있게 읽기 및 쓰기여야 합니다.
