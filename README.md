# VWAP 거래량 돌파 자동매매 봇

한국투자증권 Open API 기반 Python 자동매매 봇입니다. 현재 버전은 국내장(KRX) 실전 자동매매를 대상으로 하며, 별도 웹 대시보드는 없습니다. 주문, 체결, 잔고 결과는 증권사 앱과 로컬 로그/리포트로 확인하는 구조입니다.

## 현재 지원 기능

- 국내장(KRX) 시세 조회
- 국내장(KRX) 주문 처리
- 국내장(KRX) 계좌/잔고 조회
- 거래대금 순위 기반 국내장 관심종목 갱신
- VWAP/거래량 돌파 기반 매수 조건 평가
- 손절, 익절, VWAP 이탈, 장 마감 전 강제 청산 조건 평가
- 일일 손실 제한, 일일 거래 횟수 제한, 동시 보유 종목 수 제한
- 거래 로그 기록
- 일일 매매 리포트 생성

## 지원 시장

현재 버전은 국내장(KRX) 실전 자동매매만 지원합니다.

미국장(NASDAQ/NYSE)은 현재 지원하지 않으며, 미국장 소수점 자동매매도 현재 프로젝트 범위에서 제외합니다.

미국장 지원은 향후 필요 시 별도 기능으로 검토합니다.

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 설정

민감정보는 `.env`에만 입력합니다. `.env`는 Git에 포함하지 않습니다.

```env
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCOUNT_NO=
KIS_ACCOUNT_PRODUCT_CODE=
KIS_IS_MOCK=false

DRY_RUN=true
FORCE_QUANTITY=
MAX_ORDER_AMOUNT=100000
MAX_BUY_AMOUNT_PER_TRADE=500000
MAX_POSITION_COUNT=1
DAILY_MAX_LOSS_RATE=-2.0
DAILY_MAX_LOSS_AMOUNT=20000
MAX_UPPER_WICK_PERCENT=45.0
VWAP_ENTRY_PRICE_RATIO=1.0
KIS_MIN_REQUEST_INTERVAL_SECONDS=0.5
KIS_RATE_LIMIT_RETRY_SECONDS=1.0
KIS_RATE_LIMIT_MAX_ATTEMPTS=3
```

전략, 리스크, 관심종목은 [config.yaml](config.yaml)에서 관리합니다.

자동매매의 종목별 1회 최대 매수 금액은 `risk.max_buy_amount_per_trade`로 설정합니다. `.env`에 `MAX_BUY_AMOUNT_PER_TRADE`를 지정하면 `config.yaml` 값보다 우선합니다. 예를 들어 `500000`은 한 종목당 최대 50만 원 범위에서 현재가와 주문 가능 현금에 맞춰 정수 수량을 계산합니다. 변경한 환경변수는 봇을 재시작해야 적용됩니다.

## 실행 방법

API 연결과 계좌/시세 조회 확인:

```bash
python main.py --mode dry-run --symbol 005930
```

자동매매 루프 실행:

```bash
python main.py --mode monitor --interval-seconds 60
```

테스트 주문:

```bash
python main.py --mode test-buy --symbol 005930 --quantity 1
python main.py --mode test-sell --symbol 005930 --quantity 1
```

`DRY_RUN=true`이면 판단과 주문 예정 로그만 남기고 실제 주문은 보내지 않습니다. `DRY_RUN=false`이면 조건 충족 시 실제 주문 API를 호출할 수 있습니다.

## 매수 기준

아래 조건을 모두 만족할 때 신규 매수를 검토합니다.

- WatchlistManager가 현재 감시 가능한 종목으로 허용
- 현재가가 VWAP에 `VWAP_ENTRY_PRICE_RATIO`를 곱한 기준보다 위에 있음
- VWAP 위에서 `vwap_hold_candles` 이상 유지
- 최근 1분 거래량이 직전 `volume_lookback_minutes`분 평균 거래량의 `volume_multiplier`배 이상
- 현재가가 직전 박스권 상단, 기본 직전 5분 고점, 돌파
- 직전 캔들이 급락 캔들이 아님
- 윗꼬리 비율이 `max_upper_wick_percent` 이하
- 체결강도 프록시가 `min_execution_strength` 이상
- 호가 스프레드가 `max_spread_percent` 이하
- 시장 방향 프록시가 급락 상태가 아님
- 거래량이 3개 캔들 연속 감소 중이 아님
- 동일 종목을 보유 중이지 않음
- 종목별 일일 진입 횟수가 `max_daily_trade_count` 미만
- 청산 후 `reentry_cooldown_minutes` 이내가 아님
- 중복 주문 락이 걸려 있지 않음
- 일일 손실 제한에 도달하지 않음

## 국내장 신규 진입 허용 시간

국내장 신규 진입 허용 시간 기본값은 `09:10~15:00`이다.

거래량이 부족한 종목은 시간 조건이 아니라 기존 거래량/거래대금 조건에서 필터링된다.

단, 장 시작 직후 과열 구간과 장 마감 직전 리스크를 피하기 위해 신규 진입 허용 시간은 정규장 전체가 아니라 `09:10~15:00`으로 제한한다.

### VWAP 진입 기준 조정

`PRICE_NOT_ABOVE_VWAP` 조건은 `.env`의 `VWAP_ENTRY_PRICE_RATIO`로 완화하거나 강화할 수 있습니다.

- 기본값 `1.0`: 현재가가 VWAP보다 높아야 매수 조건 통과
- 완화 예시 `0.998`: 현재가가 VWAP의 99.8%보다 높으면 통과, 약 0.2% 아래까지 허용
- 강화 예시 `1.002`: 현재가가 VWAP의 100.2%보다 높아야 통과

값을 낮추면 매수 후보가 늘 수 있고, 값을 높이면 VWAP 상단 확인을 더 엄격하게 봅니다.

## 매도 기준

아래 조건 중 하나를 만족하면 매도를 검토합니다.

- 매수가 대비 `stop_loss_percent` 이하 손실
- 현재가가 VWAP 아래로 이탈
- 매수 후 `stale_position_minutes`가 지나고 수익률이 `stale_position_min_profit_percent` 미만
- 돌파 후 거래량 감소
- 시장 방향 프록시가 급락으로 전환
- `take_profit_percent` 도달 시 50% 분할 익절
- 1차 익절 후 잔량 손절 기준을 `break_even_stop_percent`로 상향
- `second_take_profit_percent` 도달 시 잔량 청산
- 국내장 마감 `force_sell_before_close_minutes`분 전 강제 청산

국내장 주문은 시장가 주문을 사용합니다.

## 감시 종목 선정

현재 구현은 국내장 거래대금 순위 기반 감시 종목 갱신을 사용합니다.

- `volume-rank` API를 거래대금 순위로 조회
- 당일 거래대금 상위 50개 후보 사용
- KIS 순위 API 제외 코드로 위험/관리/정지 계열 종목을 최대한 제외
- 현재가가 `min_price` 미만이면 제외
- 호가 스프레드가 `max_spread_rate` 초과이면 제외
- 최우선 매수/매도 호가 잔량 금액이 `min_orderbook_depth` 미만이면 제외
- 기본 갱신 주기: 180초

감시 목록 변경과 제외 사유는 로그에 남습니다. 예: `wide_spread`, `low_orderbook_depth`, `low_price`, `watchlist_check_failed`.

## 로그/리포트

KIS 접근 토큰은 `.kis_token_cache.json`에 로컬 캐시합니다. 이 파일은 민감한 토큰을 포함하므로 Git에 포함하지 않습니다.

KIS API 호출은 `KIS_MIN_REQUEST_INTERVAL_SECONDS` 간격을 두고 전송합니다. KIS rate limit 응답 `EGW00201`, `EGW00215`가 오면 `KIS_RATE_LIMIT_RETRY_SECONDS` 기준으로 점진 대기 후 `KIS_RATE_LIMIT_MAX_ATTEMPTS` 횟수까지 재시도합니다.

일일 매매 리포트 생성:

```bash
python main.py report --date today --save
python main.py report --date 2026-06-16 --save
```

보고서는 아래 위치에 저장됩니다.

```text
/reports/YYYY-MM-DD-daily-trading-report.md
```

생성된 보고서는 개인 매매 기록을 포함할 수 있으므로 Git에 업로드하지 않습니다.

## 테스트

```bash
pytest
```

## 주의사항

이 프로그램은 실제 매수/매도 주문을 실행할 수 있습니다.

API 키와 계좌번호는 Git에 커밋하지 마십시오.

처음 실행할 때는 반드시 `DRY_RUN=true`로 하루 이상 동작을 확인하십시오.

실주문 테스트는 `FORCE_QUANTITY=1`처럼 작은 수량으로 시작하십시오.

자동매매 손실 책임은 사용자에게 있습니다.

## Roadmap

향후 개발 계획은 [docs/ROADMAP.md](docs/ROADMAP.md)에서 관리합니다.
