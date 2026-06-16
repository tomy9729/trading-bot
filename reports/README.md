# Daily Trading Reports

이 폴더는 트레이딩봇의 일일 매매 리포트가 저장되는 위치입니다.

## 생성 명령어

오늘 날짜 보고서:

```bash
python main.py report --date today --save
```

특정 날짜 보고서:

```bash
python main.py report --date 2026-06-16 --save
```

## 파일명

```text
YYYY-MM-DD-daily-trading-report.md
```

## Git 관리

생성된 일일 매매 리포트는 개인 매매 기록을 포함할 수 있으므로 Git에 올리지 않습니다.

단, 이 README 파일과 `.gitkeep`은 Git에 포함합니다.
