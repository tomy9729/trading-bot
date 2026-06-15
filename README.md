# VWAP 거래량 돌파 자동매매 봇

한국투자증권 Open API 기반 Python 자동매매 봇입니다. 프로그램은 24시간 실행할 수 있지만 실제 주문은 국내장과 미국장 정규장 시간, 그리고 설정된 신규 진입 시간대에서만 시도합니다. 별도 웹 대시보드는 없고, 주문/체결/잔고 결과는 증권사 앱에서 확인하는 구조입니다.

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
MAX_POSITION_COUNT=1
DAILY_MAX_LOSS_RATE=-2.0
DAILY_MAX_LOSS_AMOUNT=20000
```

전략, 리스크, 관심종목은 [config.yaml](/C:/Users/tomy9/OneDrive/Desktop/toy/tra/trading-bot/config.yaml)에서 관리합니다. 기본값은 국내장 활성화, 미국장 비활성화입니다.

## 실행

API 연결 점검:

```bash
python main.py --mode dry-run --market domestic --symbol 005930
python main.py --mode dry-run --market us --symbol AAPL --quote-exchange NAS --exchange NASD
```

자동매매 루프 실행:

```bash
python main.py --mode monitor --interval-seconds 60
```

`DRY_RUN=true`이면 판단과 주문 예정 로그만 남기고 실제 주문은 보내지 않습니다. `DRY_RUN=false`이면 조건 충족 시 실제 주문 API를 호출할 수 있습니다.

## 매수 기준

아래 조건을 모두 만족할 때만 매수합니다.

- WatchlistManager가 현재 감시 가능한 종목으로 허용함
- 현재가가 VWAP 위에 있음
- VWAP 위에서 `vwap_hold_candles`개 이상 유지
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

국내 신규 진입 허용 시간 기본값:

- `09:10~11:00`
- `13:30~14:40`

미국 신규 진입 허용 시간 기본값:

- 정규장 시작 15분 후부터
- 정규장 마감 30분 전까지

## 매도 기준

아래 조건 중 하나라도 만족하면 매도합니다.

- 매수가 대비 `stop_loss_percent` 이하 손실
- 현재가가 VWAP 아래로 이탈
- 매수 후 `stale_position_minutes`가 지났고 수익률이 `stale_position_min_profit_percent` 미만
- 돌파 후 거래량 감소
- 시장 방향 프록시가 급락으로 전환
- `take_profit_percent` 도달 시 50% 분할 익절
- 1차 익절 후 잔량 손절 기준을 `break_even_stop_percent`로 상향
- `second_take_profit_percent` 도달 시 잔량 청산
- 국내장은 장 마감 `force_sell_before_close_minutes`분 전 강제청산

국내장은 시장가 주문을 사용합니다. 미국장은 지정가 주문을 사용하며 자동 루프에서는 현재가를 주문 가격으로 사용합니다.

미국장 자동 수량 계산은 원화 금액 기준입니다.

- 한국시간 `22:30~05:00` 정규장 구간에서만 주문 허용
- 프리마켓/애프터마켓 주문 금지
- `risk.us_order_amount_krw`를 1회 매수 원화 한도로 사용, 기본 `20,000원`
- `risk.us_total_test_capital_krw`로 전체 테스트 자금 제한, 기본 `100,000원`
- `risk.us_max_symbol_exposure_krw`로 1종목 최대 투입금 제한, 기본 `50,000원`
- `risk.max_daily_loss` 도달 시 신규 주문 중단, 기본 `5,000원`
- `us_order_amount_krw / us_assumed_usd_krw_rate`에서 `us_fee_buffer_rate`를 차감해 USD 주문 가능 금액을 계산
- KIS 해외주식 매수가능금액 조회 결과와 비교해 주문 가능 달러를 넘지 않음
- `us_order_mode: fractional_amount`이면 소수점 수량을 계산
- `FORCE_QUANTITY`가 있으면 테스트용 강제 수량이 우선
- 현재 공식 샘플에서 확인한 해외주식 주문은 수량/단가 기반 일반 주문입니다. 소수점 실주문 엔드포인트가 확인되지 않아, `us_fractional_order_enabled: false` 상태에서는 live 소수점 주문을 차단합니다. dry-run에서는 소수점 계산 결과를 로그로 검증할 수 있습니다.

## 감시 종목 선정

전 종목을 무제한 감시하지 않습니다. 자동매매 루프는 먼저 WatchlistManager로 감시 가능한 종목을 갱신하고, 그 목록에 포함된 종목만 신규 매수 후보로 평가합니다. 보유 종목은 감시 목록에서 빠져도 청산 로직을 계속 유지합니다.

국내장 기본값:

- `volume-rank` API를 거래금액순으로 조회
- 당일 거래대금 상위 50개 후보 사용
- KIS 순위 API 제외코드로 위험/관리/정지 계열 종목을 최대한 제외
- 현재가가 `min_price` 미만이면 제외
- 호가 스프레드가 `max_spread_rate` 초과면 제외
- 최우선 매수/매도 호가 잔량 금액이 `min_orderbook_depth` 미만이면 제외
- 기본 갱신 주기: 180초

미국장 기본값:

- 전체 종목 스캔을 하지 않음
- 첫 실전 단계에서는 고유동성 ETF만 사용
- 기본 감시: `SPY`, `QQQ`, `SOXX`, `SMH`, `XLK`, `VOO`
- 선택 감시: `NVDA`, `AAPL`, `MSFT`
- `use_optional_symbols: true`일 때 선택 감시 종목 추가
- 정규장 밖이면 신규 매수 후보에서 제외
- 스프레드가 `max_spread_rate` 초과면 제외

감시 목록 변경과 제외 사유는 로그에 남습니다. 예: `wide_spread`, `low_orderbook_depth`, `low_price`, `outside_regular_market`, `watchlist_check_failed`.

## 구현 메모

현재 1차 구현에서 체결강도와 시장 지수 방향은 별도 실시간 체결강도/지수 API가 아니라 분봉 기반 프록시로 계산합니다. 구조는 `MarketFilter`, `SymbolFilter`, `EntrySignal`, `ExitSignal`, `RiskManager`로 분리되어 있어 이후 KOSPI/KOSDAQ, QQQ/SPY, 실제 체결강도 API로 교체할 수 있습니다.

VI 직후 10분 제외, 급등 뉴스 직후 과열 제외, 실제 관리/투자경고/거래정지 상세 판정은 현재 KIS 순위 API의 제외코드와 watchlist 제외 사유 구조를 통해 확장 가능하게 분리되어 있습니다. 별도 실시간 장운영정보/뉴스 API를 연결하면 WatchlistManager의 제외 조건으로 추가할 수 있습니다.

KIS 접근토큰은 `.kis_token_cache.json`에 로컬 캐시됩니다. 이 파일은 민감한 토큰을 포함하므로 Git에 포함하지 않습니다.

## 테스트

```bash
pytest
```

## 주의사항

이 프로그램은 실제 매수/매도 주문을 실행할 수 있습니다.  
API 키와 계좌번호는 절대 Git에 커밋하지 마십시오.  
처음 실행 시 반드시 `DRY_RUN=true`로 하루 이상 동작을 확인하십시오.  
실주문 테스트는 `FORCE_QUANTITY=1`로 시작하십시오.  
자동매매 손실 책임은 사용자에게 있습니다.
