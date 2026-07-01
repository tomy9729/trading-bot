# KOSPI 공포탐욕지수 기반 KODEX 200 자동매매 봇

이 프로젝트는 KOSPI 시장의 공포/탐욕 상태를 자체 지표로 계산하고, 그 결과를 바탕으로 KODEX 200 ETF의 분할매수·보유·일부매도 판단을 자동화하는 트레이딩 봇입니다. 초기 목표는 실전 자동주문보다 데이터 수집, 지표 계산, 리포트, paper trading 검증입니다.

기존 개별주 단타 전략은 초기 범위에서 제외합니다. 우선은 시장 전체 상태를 수치화하고 KOSPI200을 추종하는 `KODEX 200`만 대상으로 보수적인 매매 판단을 수행합니다.

## 프로젝트 방향

핵심 흐름은 다음과 같습니다.

```text
KOSPI 공포탐욕지수 계산
→ 시장 상태 분류
→ KODEX 200 ETF 매매 판단
→ 리포트 / paper trading / 소액 실전 자동매매
```

초기 매매 대상:

- `069500` KODEX 200

초기 제외 범위:

- 개별주 매매
- 테마주/뉴스 기반 급등주 매매
- 레버리지 ETF
- 인버스 ETF
- 고빈도/초단타 매매

세부 개발 단계와 현재 우선순위는 [Trading Bot Roadmap](docs/Roadmap.md)에서 관리합니다.

## 현재 구현된 기반

- 한국투자증권 Open API 기반 국내장 시세, 주문, 계좌, 잔고 조회
- KOSPI/KOSDAQ/KOSPI200 지수 현재가, 시간 차트, 일봉 차트 조회
- VKOSPI fallback fetcher
  - Naver `KSVKOSPI`
  - Naver `VKOSPI`
  - Investing.com `KOSPI Volatility`
- VKOSPI 수집 timeout, 1회 retry, 30초 cache
- 주문, 체결, 현재 포지션, 계좌 스냅샷, 봇 이벤트 SQLite 저장
- 일일 매매 리포트 생성
- FastAPI 기반 read-only 대시보드 API 기초

KIS 국내업종 API에서는 `VKOSPI`, `603`, `205`, `0205`가 모두 0.0 또는 빈 응답이어서 VKOSPI 수집에 사용하지 않습니다. 현재 VKOSPI는 KIS 밖 fallback 수집기를 사용합니다.

## 공포탐욕지수 방향

공포탐욕지수는 0~100점으로 계산합니다.

| 점수 | 상태 |
| ---: | --- |
| 0~20 | 극단적 공포 |
| 21~35 | 공포 |
| 36~55 | 중립 |
| 56~75 | 탐욕 |
| 76~100 | 극단적 탐욕 |

초기 구성 지표:

- VKOSPI
- KOSPI 20일 수익률
- KOSPI 60일 이동평균 이격도
- 상승 종목 수 / 하락 종목 수 비율
- 거래대금 변화율
- KOSPI200 추세

VKOSPI는 핵심 공포 지표로 사용합니다. 다만 수집 실패 시 봇이 멈추지 않도록 다음 단계에서 KOSPI 20일 실현변동성 proxy를 추가합니다. proxy 사용 여부는 DB, 리포트, 로그에 표시해야 합니다.

## KODEX 200 판단 초안

| 점수 | 상태 | 행동 |
| ---: | --- | --- |
| 0~20 | 극단적 공포 | 현금의 30% 분할매수 |
| 21~35 | 공포 | 현금의 15% 분할매수 |
| 36~55 | 중립 | 보유 또는 소액 매수 |
| 56~75 | 탐욕 | 신규 매수 중단 |
| 76~100 | 극단적 탐욕 | 보유 ETF 일부 매도 |

초기 원칙:

- 전액 매수 금지
- 항상 현금 일부 보유
- 하루 최대 1회 주문
- 동일 구간 반복 매수 방지
- 데이터 수집 또는 점수 계산 실패 시 매매 금지

초기 판단 시점 후보:

- 09:10 장초반
- 10:30 장중
- 14:50 종가 전

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
MAX_UPPER_WICK_PERCENT=45.0
VWAP_ENTRY_PRICE_RATIO=1.0
KIS_MIN_REQUEST_INTERVAL_SECONDS=0.5
KIS_RATE_LIMIT_RETRY_SECONDS=1.0
KIS_RATE_LIMIT_MAX_ATTEMPTS=3
```

전략, 리스크, 감시 대상 설정은 [config.yaml](config.yaml)에서 관리합니다.

## 실행 방법

API 연결과 계좌/시세 조회 확인:

```bash
python main.py --mode dry-run --symbol 069500
```

자동매매 루프 실행:

```bash
python main.py --mode monitor --interval-seconds 60
```

주문 없이 증권사 상태를 다시 조회해 DB와 런타임 상태를 복구:

```bash
python main.py --mode recover
```

대시보드 read-only API 실행:

```bash
uvicorn apps.api.app:app --host 127.0.0.1 --port 8000 --reload
```

`DRY_RUN=true`이면 판단과 주문 예정 로그만 남기고 실제 주문은 보내지 않습니다. `DRY_RUN=false`이면 조건 충족 시 실제 주문 API를 호출할 수 있습니다.

## 리포트

일일 매매 리포트 생성:

```bash
python main.py report --date today --save
python main.py report --date 2026-06-16 --save
```

향후 공포탐욕 리포트에는 다음 항목을 추가합니다.

- KOSPI 공포탐욕 점수와 상태
- VKOSPI 값, 출처, 실측 여부
- KOSPI/KOSPI200 현재값
- 20일 수익률, 60일 이격도, 20일 실현변동성
- 상승/하락 종목 비율
- 거래대금 변화율
- KODEX 200 매매 판단과 차단 사유

## 테스트

```bash
pytest
```

VKOSPI/KIS 지수 수집 관련 테스트:

```bash
.venv\Scripts\python.exe -m pytest tests\test_vkospi_fetcher.py tests\test_kis_market.py
```

현재 검증 결과:

```text
7 passed
```

## 주의사항

이 프로그램은 실제 매수/매도 주문을 실행할 수 있습니다.

API 키와 계좌번호는 Git에 커밋하지 마십시오.

처음 실행할 때는 반드시 `DRY_RUN=true`로 하루 이상 동작을 확인하십시오.

실주문 테스트는 `FORCE_QUANTITY=1`처럼 작은 수량으로 시작하십시오.

자동매매 손실 책임은 사용자에게 있습니다.
