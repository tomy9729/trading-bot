# Dashboard API

v0.9에서 분리된 read-only FastAPI 애플리케이션이다. 자동매매 프로세스와 동일한 SQLite DB를 읽지만 주문 API나 전략 변경 기능은 제공하지 않는다.

## 실행

프로젝트 루트에서 실행한다.

```bash
uvicorn apps.api.app:app --host 127.0.0.1 --port 8000 --reload
```

주요 엔드포인트:

- `GET /api/v1/health`
- `GET /api/v1/positions`
- `GET /api/v1/events?trade_date=YYYY-MM-DD&limit=200`
- `GET /api/v1/orders?trade_date=YYYY-MM-DD`
- `GET /api/v1/executions?trade_date=YYYY-MM-DD`
- `GET /api/v1/account-summary`

API는 조회 전용이며, 자동매매 프로세스와 독립적으로 실행한다.
