# Trading Bot Roadmap

## 1. Project Goal

이 프로젝트의 방향은 기존 개별주 단타 자동매매 봇에서 `KOSPI 공포탐욕지수 기반 KODEX 200 ETF 자동매매 봇`으로 변경한다.

목표는 초단타 수익 극대화가 아니라 KOSPI 시장의 공포/탐욕 상태를 수치화하고, KODEX 200 ETF를 감정 없이 분할매수·보유·일부매도하는 자동화 시스템을 구축하는 것이다.

```text
KOSPI 공포탐욕지수 계산
→ 시장 상태 분류
→ KODEX 200 ETF 매매 판단
→ 리포트 / paper trading / 소액 실전 자동매매
```

초기 매매 대상은 `069500` KODEX 200만 둔다.

## 2. Development Principles

- 현재 시장 범위는 국내장(KRX)으로 한정한다.
- 초기 전략 범위는 KODEX 200 ETF 비중 조절이다.
- 개별주 단타 전략으로 돌아가지 않는다.
- 레버리지 ETF, 인버스 ETF, 고빈도 매매, 초단타 매매는 초기 범위에서 제외한다.
- VKOSPI는 핵심 공포 지표로 사용한다.
- VKOSPI 수집 실패 시 봇이 멈추지 않도록 KOSPI 20일 실현변동성 proxy를 사용한다.
- proxy 사용 여부는 DB, 리포트, 로그에 표시한다.
- 초기에는 실전 자동주문보다 데이터 수집, 지표 계산, 리포트, paper trading 검증을 우선한다.
- 데이터 수집 실패 또는 점수 계산 실패 시 매매하지 않는다.
- 하루 주문 횟수와 현금 사용 비율을 보수적으로 제한한다.

## 3. Current Baseline

현재 저장소에는 다음 기반이 있다.

- 한국투자증권 국내장 시세, 주문, 계좌, 잔고, 미체결, 체결 API 연동
- KOSPI/KOSDAQ/KOSPI200 지수 현재가, 시간 차트, 일봉 차트 조회
- VKOSPI fallback fetcher
- 주문, 체결, 포지션, 계좌 스냅샷, 봇 이벤트 SQLite 저장
- 로그와 DB를 이용한 일일 매매 리포트
- FastAPI 기반 read-only 대시보드 API 기초
- `src/broker`, `src/runner`, `src/strategy`, `src/risk`, `src/db`, `src/report` 단위의 기본 코드 분리

KIS 국내업종 API에서 `VKOSPI`, `603`, `205`, `0205`는 모두 0.0 또는 빈 응답이었다. 따라서 VKOSPI는 KIS 밖 fallback fetcher를 사용한다.

## 4. Version Roadmap

### v0.8 - 데이터 기반 구조 정리

목표:

- 기존 KIS 연동 구조 유지
- KOSPI/KOSDAQ/KOSPI200 지수 수집 안정화
- VKOSPI fallback fetcher 추가
- 테스트 코드 보강

완료된 내용:

- `src/broker/vkospi_fetcher.py` 추가
- `tests/test_vkospi_fetcher.py` 추가
- Naver `KSVKOSPI` fallback 테스트
- Naver `VKOSPI` fallback 테스트
- Investing.com `KOSPI Volatility` fallback 테스트
- timeout, 1회 retry, 30초 cache 추가
- `tests/test_vkospi_fetcher.py`, `tests/test_kis_market.py` 기준 `7 passed`

### v0.9 - KOSPI 공포탐욕지수 계산기

목표:

- `FearGreedCalculator` 추가
- VKOSPI 기반 공포 점수 계산
- KOSPI 20일 수익률 계산
- KOSPI 60일 이동평균 이격도 계산
- KOSPI 20일 실현변동성 proxy 계산
- 상승/하락 종목 비율 반영
- 거래대금 변화율 반영
- 최종 `fear_greed_score` 산출
- `fear_greed_level` 분류

산출물:

- `src/strategy/fear_greed_calculator.py`
- `tests/test_fear_greed_calculator.py`

### v1.0 - 리포트 및 대시보드 기초

목표:

- 장중/장마감 공포탐욕 리포트 생성
- `market_sentiment_snapshots` 저장
- VKOSPI 실측값/proxy 여부 표시
- KOSPI 공포탐욕 점수 추이 확인

산출물:

- 일일 markdown 리포트
- DB 저장 구조
- README 업데이트
- ROADMAP 업데이트

### v1.1 - KODEX 200 매매 시그널

목표:

- KODEX 200 전용 매매 판단기 추가
- 공포탐욕 점수별 매수/보유/매도 판단
- 하루 주문 횟수 제한
- 동일 구간 반복 매수 방지
- 매매 차단 사유 기록

산출물:

- `src/strategy/kodex200_signal.py`
- `tests/test_kodex200_signal.py`
- `etf_trade_signals` 저장

### v1.2 - Paper Trading

목표:

- 실제 주문 없이 KODEX 200 가상 매매 수행
- 매수/매도 판단 로그 저장
- 가상 수익률 계산
- MDD 계산
- 거래 횟수 계산
- 단순 buy & hold와 비교

중요 비교 대상:

- KODEX 200 Buy & Hold
- 공포탐욕 기반 KODEX 200 전략

### v1.3 - 소액 실전 자동매매

목표:

- KODEX 200만 소액 실전 매매
- 하루 최대 1회 주문
- 현금 비중 제한
- 데이터 오류 시 주문 차단
- VKOSPI/proxy 상태 리포트 표시

초기 제한:

- 개별주 매매 금지
- 레버리지 ETF 금지
- 인버스 ETF 금지
- 하루 다중 매매 금지
- 몰빵 금지

### v2.0 - 확장 검토

v2 이후에만 검토할 항목:

- KODEX 레버리지
- KODEX 인버스
- TIGER 200
- KOSDAQ150 ETF
- 섹터 ETF
- 개별주 스윙
- 뉴스 기반 보조 지표
- 대시보드 고도화

v2 전까지는 개별주 단타 전략으로 돌아가지 않는다. 현재 프로젝트의 핵심은 KOSPI 공포탐욕지수 기반 ETF 비중 조절이다.

## 5. Test Plan

기존 테스트 유지:

```bash
.venv\Scripts\python.exe -m pytest tests\test_vkospi_fetcher.py tests\test_kis_market.py
```

신규 테스트 추가 예정:

```bash
.venv\Scripts\python.exe -m pytest tests\test_fear_greed_calculator.py
.venv\Scripts\python.exe -m pytest tests\test_kodex200_signal.py
```

테스트 기준:

- VKOSPI 수집 실패 시 fallback 동작 확인
- Investing.com 파싱 실패 시 예외 처리 확인
- 30초 cache 동작 확인
- 공포탐욕 점수 0~100 범위 보장
- VKOSPI 실측값/proxy 구분 확인
- 점수 구간별 level 분류 확인
- 매매 차단 조건 확인
- 데이터 누락 시 `trade_allowed=false` 확인

## 6. Not Now

현재 단계에서 하지 않을 것:

- 개별주 단타 매매
- 테마주 매매
- 뉴스 기반 급등주 매매
- 레버리지 ETF
- 인버스 ETF
- 고빈도 매매
- 초단타 매매
- 과도한 통계 및 집계 테이블
- 처음부터 PostgreSQL 운영 환경 구축
- 현재 동작하는 코드를 근거 없이 대규모 재배치
