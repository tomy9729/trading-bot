# Trading Bot App

국내장 자동매매 프로세스의 조립과 CLI 실행을 담당한다.

루트 `main.py`는 기존 실행 명령 호환을 위해 `apps.bot.app.main`을 호출한다.

```bash
python main.py --mode monitor --interval-seconds 60
```

bot 전용 코드:

- `src/broker`
- `src/runner`
- `src/risk`
- `src/strategy`
- `src/services`
- `src/watchlist`

대시보드 API는 bot runtime module을 import하지 않고 SQLite read model만 사용한다.
