# Dashboard API Contract

## 목적

자동매매 프로세스와 웹 대시보드를 분리하고, 대시보드는 SQLite DB를 직접 읽지 않고 read-only FastAPI를 통해 조회한다.

## 실행 경계

```text
Bot process
  -> KIS API
  -> SQLite write

Dashboard API
  -> TradingQueryRepository
  -> SQLite read-only connection
  -> JSON response

Vue dashboard
  -> Dashboard API
```

대시보드 API 장애는 자동매매 프로세스에 영향을 주지 않아야 한다.

Dashboard API는 schema 초기화와 쓰기 메서드가 없는 `TradingQueryRepository`만 사용한다.

## API

### `GET /api/v1/positions`

현재 수량이 1 이상인 포지션을 반환한다. broker 원본 payload는 노출하지 않는다.

### `GET /api/v1/events`

지정 거래일의 최신 봇 이벤트를 반환한다.

Query:

- `trade_date`: `YYYY-MM-DD`, 생략 시 오늘
- `limit`: `1~1000`, 기본값 `200`

### `GET /api/v1/orders`

지정 거래일의 주문 요청과 상태를 반환한다.

### `GET /api/v1/executions`

지정 거래일의 실제 체결과 거래비용·실현손익을 반환한다.

### `GET /api/v1/account-summary`

가장 최근 계좌 스냅샷을 반환한다.

## 현재 제한

- 인증과 외부 공개는 아직 지원하지 않는다.
- 주문, 설정 변경, 봇 제어 API는 제공하지 않는다.
- WebSocket은 도입하지 않고 초기에는 polling을 사용한다.
- Vue 프로젝트 생성은 v1.1 범위로 유지한다.
