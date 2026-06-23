# Current Project Structure

## 1. 전체 폴더 구조

현재 root는 `C:\Users\tomy9\OneDrive\Desktop\toy\trading-bot`이다.

```text
trading-bot/
  .env                  # 로컬 실행용 민감 설정. 문서화/커밋 대상 아님
  .env.example          # 환경 변수 예시
  .gitignore
  .kis_token_cache.json # KIS 토큰 캐시. 커밋 대상 아님
  config.yaml           # 비밀값이 아닌 봇 설정
  main.py               # CLI 진입점
  README.md
  requirements.txt

  docs/
    Roadmap.md
    current-project-structure.md
    dashboard-api-contract.md

  apps/
    bot/
      app.py
    api/
      app.py
      dependencies.py
      routers/
        dashboard.py
      services/
        dashboard_query_service.py
    web/
      README.md

  logs/                 # 런타임 로그 저장 위치. 커밋 대상 아님
    monitor_stdout_*.log
    monitor_stderr_*.log
    trade_YYYYMMDD.log
    trade_events_YYYYMMDD.jsonl

  reports/
    README.md
    .gitkeep
    YYYY-MM-DD-daily-trading-report.md

  src/
    broker/
      kis_account.py
      kis_auth.py
      kis_client.py
      kis_market.py
      kis_order.py
    config/
      bot_config.py
      env.py
      strategy_config.py
    db/
      connection.py
      query_repository.py
      repository.py
      schema.py
    domain/
      market_data.py
      order.py
      position.py
      signal.py
    logs/
      trade_logger.py
    report/
      daily_report.py
      missed_trade_analyzer.py
      report_analyzer.py
      report_parser.py
      report_writer.py
      simulated_trade_calculator.py
    services/
      order_execution_service.py
      trading_account_service.py
      trading_order_service.py
    risk/
      risk_manager.py
    runner/
      auto_trading_state.py
      auto_trading_runner.py
      dry_run_runner.py
      live_runner.py
      market_hours.py
    strategy/
      advanced_signals.py
      indicators.py
      market_snapshot_builder.py
      vwap_entry_rule.py
      vwap_volume_breakout.py
    watchlist/
      watchlist_manager.py

  tests/
    test_auto_trading_runner.py
    test_bot_config.py
    test_dry_run.py
    test_kis_client.py
    test_market_hours.py
    test_report.py
    test_risk_manager.py
    test_strategy_buy.py
    test_strategy_sell.py
    test_trade_logger.py
    test_trading_repository.py
    test_watchlist_manager.py
```

`.venv/`, `.pytest_cache/`, `__pycache__/`, `logs/`, `data/`, `*.db`, `.env*`, `.kis_token_cache.json`은 `.gitignore`에 포함되어 있다. 단, `.env.example`, `reports/README.md`, `reports/.gitkeep`은 예외로 추적된다.

## 2. 주요 실행 흐름

CLI 호환 진입점은 root `main.py`이고 실제 애플리케이션 조립은 `apps/bot/app.py`의 `main()`이다.

```text
python main.py [--mode dry-run|live|monitor|test-order|test-buy|test-sell]
python main.py report [--date today|YYYY-MM-DD] [--save] [--log-path PATH]
```

일반 실행 흐름:

```text
main.py
  -> apps/bot/app.py
  -> load_settings()                 # src/config/env.py, .env / process env
  -> load_bot_config()               # src/config/bot_config.py, config.yaml
  -> TradingRepository()             # src/db/repository.py, data/trading.db 초기화
  -> KisClient(settings)
  -> KisMarket / KisAccount / KisOrder
  -> TradingOrderService
  -> WatchlistManager
  -> DryRunRunner / LiveRunner / AutoTradingRunner
```

모드별 동작:

- `dry-run`: `LiveRunner.health_check()`로 현재가, 호가, 주문가능금액, 잔고 조회를 확인한다. 주문은 넣지 않는다.
- `live`: `DRY_RUN=false`일 때만 `LiveRunner.health_check()`를 수행한다.
- `monitor`: `AutoTradingRunner.run_forever(interval_seconds)`로 자동매매 루프를 실행한다.
- `test-order`, `test-buy`: `DryRunRunner.test_buy()`를 통해 `TradingOrderService.buy_market()` 경로를 호출한다.
- `test-sell`: `DryRunRunner.test_sell()`을 통해 `TradingOrderService.sell_market()` 경로를 호출한다.
- `report`: `src/report/daily_report.py`의 `run_report_command()`로 로그 기반 일일 리포트를 생성한다.

`monitor` 모드의 핵심 루프:

```text
AutoTradingRunner.run_forever()
  -> run_once()
    -> _reset_daily_state_if_needed()
    -> _recover_startup_state()       # 최초 1회: 잔고, 미체결, 당일 체결, 실현손익 복구
    -> _run_domestic_cycle()
      -> _sync_domestic_positions()   # KIS 잔고 조회 + positions DB upsert
      -> _sync_domestic_executions()  # KIS 당일 체결 조회 + executions DB insert
      -> WatchlistManager.refresh("KR")
      -> 종목별 snapshot 생성
      -> 보유 종목이면 매도 판단
      -> 미보유 종목이면 매수 판단
      -> OrderExecutionService
        -> TradingOrderService
          -> KisOrder.buy_market() / sell_market()
```

## 3. 주요 파일별 역할

### Root

- `main.py`: 기존 실행 명령을 유지하는 호환 진입점.
- `config.yaml`: 장 운영 시간, 진입 가능 시간대, 전략 파라미터, 리스크 설정, watchlist 설정을 담는다.
- `requirements.txt`: bot 의존성과 FastAPI, Uvicorn, HTTPX 테스트 의존성을 정의한다.
- `.env.example`: 필요한 환경 변수 형식을 보여주는 예시 파일이다. 실제 `.env` 값은 문서화하지 않는다.

### `apps/bot`

- `app.py`: 설정, KIS broker, repository, service, runner를 조립하고 CLI mode를 실행한다.

### `apps/api`

- `app.py`: read-only FastAPI 애플리케이션 생성과 router 등록.
- `routers/dashboard.py`: 현재 포지션, 이벤트, 주문, 체결, 계좌 요약 HTTP API.
- `services/dashboard_query_service.py`: DB row에서 원본 broker payload를 제외하고 대시보드 응답으로 변환.
- `dependencies.py`: read-only SQLite `TradingQueryRepository` dependency 생성.

### `apps/web`

현재 Vue 코드는 없고 v1.1 Dashboard MVP의 화면 범위와 기술 후보만 문서화되어 있다.

### `src/broker`

- `kis_client.py`: KIS 공통 HTTP 클라이언트. 인증 토큰 헤더, hashkey, 요청 throttle, rate limit 재시도, auth error 재시도를 처리한다.
- `kis_auth.py`: KIS OAuth token 발급 및 `.kis_token_cache.json` 캐시 관리.
- `kis_market.py`: 국내 주식 현재가, 호가, 분봉, 거래대금 순위 API 래퍼.
- `kis_account.py`: 잔고, 주문 가능 현금, 미체결 주문, 당일 체결, 일일 실현손익 API 래퍼.
- `kis_order.py`: 시장가 매수/매도 KIS API 호출, dry-run 분기, 장 시간 검증만 담당한다.

### `src/runner`

- `auto_trading_runner.py`: 자동매매 cycle, 전략 평가, 상태 전환 순서를 조정한다.
- `auto_trading_state.py`: 포지션, 주문 lock, 일일 손실, safe mode 등 mutable runtime state.
- `live_runner.py`: 주문 없이 KIS 연결 상태를 확인하는 health check runner.
- `dry_run_runner.py`: 테스트 매수/매도 호출과 주문 수량 계산 helper.
- `market_hours.py`: 한국 정규장 및 신규 매수 가능 시간 체크.

### `src/services`

- `trading_account_service.py`: 시작 상태 복구, 잔고·체결 동기화, DB persistence, 계좌 스냅샷, 불확실 주문 재확인.
- `order_execution_service.py`: 매수·매도 실행, 주문 lock 정리, 체결 후 로컬 포지션 갱신.
- `trading_order_service.py`: 주문 이벤트와 `orders` 상태 저장을 조정하고 `KisOrder`를 호출한다.

### `src/strategy`

- `advanced_signals.py`: 현재 `AutoTradingRunner`가 사용하는 최신 매수/매도 판단 계층. `MarketFilter`, `SymbolFilter`, `EntrySignal`, `ExitSignal`이 있다.
- `market_snapshot_builder.py`: KIS 분봉 row를 `MinuteCandle`로 파싱하고, VWAP/거래량/고점/체결강도/시장 방향 등 `MarketSnapshot`을 구성한다.
- `indicators.py`: VWAP, volume multiplier 계산.
- `vwap_entry_rule.py`: VWAP 진입 기준 가격 계산.
- `vwap_volume_breakout.py`: 이전/테스트 중심 VWAP 돌파 전략 함수. 현재 자동매매 runner는 `advanced_signals.py`를 직접 사용한다.

### `src/risk`

- `risk_manager.py`: `RiskState`와 `RiskManager`. 신규 진입 가능 여부, 최대 보유 수, 일 손실, 연속 손실, safe mode, kill switch, pending/order lock, 종목별 일 진입 횟수를 판단한다.

### `src/watchlist`

- `watchlist_manager.py`: KIS 거래대금 순위 또는 config 고정 watchlist를 기반으로 KR watchlist를 관리한다. 현재가/호가 기반 필터와 제외 사유 로그를 남긴다.

### `src/domain`

- `market_data.py`: `MinuteCandle`, `MarketSnapshot`.
- `order.py`: `OrderRequest`, `OrderResult`.
- `position.py`: `Position`, `PositionState`.
- `signal.py`: `Signal`, `NO_SIGNAL`.

### `src/logs`

- `trade_logger.py`: 일반 텍스트 로그와 JSONL 이벤트 로그를 생성한다.

### `src/report`

- `daily_report.py`: report CLI command.
- `report_parser.py`: `logs/trade_YYYYMMDD.log` 또는 JSONL 이벤트를 `ReportEvent`로 파싱한다.
- `report_analyzer.py`: 실제 매수/매도 기록과 요약 통계를 만든다.
- `missed_trade_analyzer.py`: 매수하지 못한 후보를 분석한다.
- `simulated_trade_calculator.py`: 놓친 후보의 가상 수익률/손익 계산.
- `report_writer.py`: Markdown 리포트 생성 및 `reports/` 저장.

### `src/db`

- `connection.py`: 기본 DB 경로 `data/trading.db`, SQLite connection 생성.
- `schema.py`: `orders`, `executions`, `positions`, `account_snapshots`, `bot_events` 테이블과 관련 index 생성.
- `repository.py`: bot process의 DB 쓰기와 내부 리포트 조회를 제공한다. DB 저장 실패는 파일 로그에 기록하고 예외를 전파하지 않는다.
- `query_repository.py`: Dashboard API 전용 read-only 조회를 제공하며 DB나 schema를 생성하지 않는다.

### `src/config`

- `runtime_paths.py`: 프로젝트 루트 기준 DB, 로그, 리포트, 설정, dotenv, 토큰 캐시 경로를 관리한다. 각 경로는 환경변수로 override할 수 있다.

## 4. 현재 봇 관련 코드 위치

현재 봇의 주요 실행 코드는 `src/runner/auto_trading_runner.py`에 집중되어 있다.

자동매매 core:

- `src/runner/auto_trading_runner.py`
- `src/runner/market_hours.py`
- `src/runner/dry_run_runner.py`
- `src/runner/live_runner.py`

전략 판단:

- `src/strategy/advanced_signals.py`
- `src/strategy/market_snapshot_builder.py`
- `src/strategy/indicators.py`
- `src/strategy/vwap_entry_rule.py`
- `src/strategy/vwap_volume_breakout.py`

리스크:

- `src/risk/risk_manager.py`

KIS API:

- `src/broker/kis_client.py`
- `src/broker/kis_auth.py`
- `src/broker/kis_market.py`
- `src/broker/kis_account.py`
- `src/broker/kis_order.py`

watchlist:

- `src/watchlist/watchlist_manager.py`

설정:

- `src/config/env.py`
- `src/config/bot_config.py`
- `src/config/strategy_config.py`
- `config.yaml`
- `.env.example`

## 5. 로그 / 리포트 / DB 관련 구조

### 로그

`src/logs/trade_logger.py`가 `logs/` 폴더를 자동 생성한다.

- 일반 로그: `logs/trade_YYYYMMDD.log`
- 구조화 이벤트 로그: `logs/trade_events_YYYYMMDD.jsonl`
- monitor 실행 출력 로그가 별도로 존재한다: `logs/monitor_stdout_*.log`, `logs/monitor_stderr_*.log`

주요 로그 발생 지점:

- `main.py`: 시작/종료/fatal.
- `KisClient`: KIS auth retry, rate limit retry.
- `KisOrder`: broker API request, response, failure.
- `TradingOrderService`: dry-run, order requested, accepted, failed 이벤트와 DB 상태.
- `AutoTradingRunner`: buy/sell check, skip, done, startup recovery, API retry, safe mode, kill switch.
- `WatchlistManager`: watchlist refresh, watchlist exclude.
- `TradingRepository`: DB init/save failure.

### 리포트

리포트 저장 위치:

- `reports/YYYY-MM-DD-daily-trading-report.md`

리포트 생성 경로:

```text
python main.py report --date today --save
  -> src/report/daily_report.py
  -> parse_log_file()
  -> analyze_trades()
  -> analyze_missed_candidates()
  -> write_report()
```

현재 `reports/*.md`는 `.gitignore`로 제외되고, `reports/README.md`, `reports/.gitkeep`만 추적된다.

### DB

기본 SQLite DB 경로:

```text
data/trading.db
```

현재 생성 테이블:

- `orders`: 주문 요청 및 주문 상태.
- `executions`: 실제 체결 내역.
- `positions`: KIS 잔고조회 결과 기반 현재 보유 종목 캐시.
- `account_snapshots`: 계좌 자산과 일일 손익 스냅샷.
- `bot_events`: 주문, 전략 판단, 스킵, 오류 등 구조화된 봇 이벤트.

DB 저장 흐름:

```text
main.py
  -> TradingRepository()
    -> initialize_database()
      -> data/trading.db 생성
      -> orders / executions / positions 생성

TradingOrderService._market_order()
  -> insert_order(status="REQUESTED")
  -> KisOrder
    -> KIS order-cash API 호출
  -> 성공: update_order_status(status="ACCEPTED")
  -> 실패: update_order_status(status="FAILED")

AutoTradingRunner._recover_startup_state()
  -> get_balance()
  -> _persist_position_rows()
  -> get_today_executions()
  -> _persist_execution_rows()

AutoTradingRunner._run_domestic_cycle()
  -> _sync_domestic_positions()
    -> get_balance()
    -> positions upsert
  -> _sync_domestic_executions()
    -> get_today_executions()
    -> executions insert
```

DB 저장 실패는 `TradingRepository` 내부에서 `logs/trade_YYYYMMDD.log`에 남고, 봇 실행을 중단하지 않는 구조다.

## 6. 외부 API 연동 구조

현재 외부 API는 한국투자증권 KIS API가 중심이다.

공통 계층:

- `src/broker/kis_auth.py`
  - `/oauth2/tokenP` 토큰 발급.
  - `.kis_token_cache.json` 캐시.
- `src/broker/kis_client.py`
  - `get()`, `post()`, `create_hashkey()`.
  - `settings.base_url`로 실전/모의 URL 분기.
  - `tr_id` 기반 KIS 요청.

시장 데이터:

- `src/broker/kis_market.py`
  - 현재가: `/uapi/domestic-stock/v1/quotations/inquire-price`
  - 호가: `/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn`
  - 분봉: `/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice`
  - 거래대금 순위: `/uapi/domestic-stock/v1/quotations/volume-rank`

계좌/체결:

- `src/broker/kis_account.py`
  - 잔고: `/uapi/domestic-stock/v1/trading/inquire-balance`
  - 주문가능금액: `/uapi/domestic-stock/v1/trading/inquire-psbl-order`
  - 미체결 주문: `/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl`
  - 당일 체결: `/uapi/domestic-stock/v1/trading/inquire-daily-ccld`
  - 기간 손익: `/uapi/domestic-stock/v1/trading/inquire-period-trade-profit`

주문:

- `src/broker/kis_order.py`
  - 현금 주문: `/uapi/domestic-stock/v1/trading/order-cash`
  - 시장가 주문 payload 생성.
  - 모의/실전 `tr_id` 분기.
  - 장 시간 검증.

민감정보:

- 실제 API key, secret, 계좌번호는 `.env` 또는 process environment에서 읽는다.
- 이 문서에는 민감값을 포함하지 않는다.

## 7. v0.9 애플리케이션 경계

### Bot app

`apps/bot/app.py`가 자동매매 프로세스를 조립한다.

Bot 전용 범위:

- `src/broker/`
- `src/runner/`
- `src/risk/`
- `src/strategy/`
- `src/services/`
- `src/watchlist/`

### Dashboard API

`apps/api`는 HTTP 조회 계층만 담당한다.

- `TradingQueryRepository`를 통한 SQLite read-only 연결
- 현재 포지션, 이벤트, 주문, 체결, 계좌 요약 조회
- KIS broker, runner, strategy, risk, trading service를 import하지 않음
- 주문, 설정 변경, 봇 제어 endpoint를 제공하지 않음

### Web app

`apps/web`에는 v1.1 Vue Dashboard MVP의 범위만 문서화되어 있다. 실제 Vue 프로젝트는 아직 생성하지 않았다.

### 공유 범위

- `src/config/runtime_paths.py`
- `src/db/connection.py`
- `src/db/query_repository.py`
- SQLite schema contract

쓰기 repository와 schema 초기화는 bot process에서만 사용한다.

## 8. 주의해야 할 의존성 / import 관계

현재 import는 대부분 `src.*` 절대 경로를 사용한다.

핵심 의존 방향:

```text
main.py
  -> apps/bot/app.py
    -> config, db, broker, runner, services, watchlist, logs

apps/api
  -> config/runtime_paths
  -> db/connection
  -> db/query_repository

runner/auto_trading_runner.py
  -> config
  -> domain
  -> logs
  -> risk
  -> services
  -> strategy
  -> watchlist

broker/kis_order.py
  -> KisClient
  -> domain/order
  -> logs
  -> MarketHours

services/trading_order_service.py
  -> KisOrder
  -> TradingRepository
  -> trade events

services/trading_account_service.py
  -> KisAccount
  -> TradingRepository
  -> AutoTradingState

watchlist/watchlist_manager.py
  -> KisMarket
  -> BotConfig
  -> MarketHours
  -> logs

strategy/advanced_signals.py
  -> BotConfig
  -> domain
  -> RiskManager
  -> indicators / vwap_entry_rule

risk/risk_manager.py
  -> Settings
  -> strategy_config

report/*
  -> logs output
  -> BotConfig
  -> strategy/vwap_entry_rule
```

주의할 점:

- `AutoTradingRunner`는 cycle과 전략 평가 순서를 담당한다. 계좌 동기화와 주문 실행은 `src/services`로 분리되었지만, 전략 이벤트 payload 생성과 API retry/safe mode orchestration은 아직 runner에 남아 있다.
- `KisOrder`는 broker API 호출만 담당하고 `TradingOrderService`가 주문 이벤트와 DB 상태 저장을 담당한다.
- `src/risk/risk_manager.py`와 `src/strategy/vwap_volume_breakout.py`는 `src/config/strategy_config.py` 전역 상수에 의존한다. 반면 최신 자동매매 경로는 `BotConfig` dataclass를 주로 사용한다.
- `src/report/*`는 로그 포맷에 강하게 의존한다. 로그 이벤트 schema를 바꾸면 report parser도 같이 수정해야 한다.
- `src/db/repository.py`는 bot logging에 의존하지만 API는 별도 `query_repository.py`를 사용하므로 이 의존성을 가져가지 않는다.
- DB, 로그, 리포트, 설정, 토큰 캐시 경로는 `runtime_paths.py`에서 프로젝트 루트 기준으로 해석하며 환경변수 override를 지원한다.
- 일부 report 관련 문자열에 인코딩이 깨진 텍스트가 존재한다. 문서화만 했으며 수정하지 않았다.

## 9. 다음 개선 제안

v1.0 이후 구조 개선은 아래 순서로 검토한다.

1. runner의 남은 event payload 생성 책임을 검토한다.
   - strategy decision
   - risk snapshot
   - market snapshot

2. `strategy_config.py` 전역 상수와 `bot_config.py` dataclass 설정을 통합한다.
   - 현재 최신 경로와 이전 테스트/전략 경로가 서로 다른 설정 소스를 쓴다.

3. report 계층의 로그 schema 의존성을 줄인다.
   - 가능하면 `trade_events_YYYYMMDD.jsonl` schema를 표준으로 삼고 text log parsing은 fallback으로 둔다.

4. 인코딩이 깨진 report 문구를 별도 작업으로 정리한다.

5. Vue 대시보드는 `apps/api`만 호출하고 bot runtime module을 직접 참조하지 않도록 유지한다.
