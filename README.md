# OKX Auto Trader

OKX 거래소 자동매매 프로그램 — **단타(스캘핑)** 와 **장타(스윙)** 전략을 지원하며, **선물(SWAP)**, **현물(SPOT)**, **선물(FUTURES)** 상품을 모두 거래할 수 있습니다.

[automatic_stock_trading](https://github.com/rosua4652-commits/automatic_stock_trading) (AIDI) 프로젝트와 유사한 구조로, AI 기술적 분석 → 자동 진입 → 손절/익절/트레일링 스탑 → 수익 실현까지 전 과정을 자동화합니다.

## 주요 기능

- **자동 시장 스캔**: OKX USDT 마켓에서 유동성·변동성 기준 후보 종목 탐색
- **AI 기술적 분석**: EMA, RSI, MACD, 거래량 분석으로 진입 점수 산출
- **단타 / 장타 전략**: 스캘핑(5분봉)과 스윙(1시간봉) 모드 전환
- **다중 상품 지원**: SWAP(무기한 선물), SPOT(현물), FUTURES(만기 선물)
- **리스크 관리**: 손절, 익절, 트레일링 스탑, 최대 포지션 수, 일일 손실 한도
- **모의투자 / 실거래**: Paper 모드로 전략 검증 후 Live 모드 전환
- **웹 대시보드**: 실시간 포트폴리오, 포지션, 매매 후보, 활동 로그

## 빠른 시작

### 1. 필수 프로그램

| 프로그램 | 버전 | 용도 |
|----------|------|------|
| Python | 3.10+ | 백엔드 서버 |
| Node.js | 18+ | 프론트엔드 빌드 |

### 2. 설정

```bash
cp .env.example .env
# .env 파일에 OKX API 키 입력
```

OKX API 키 발급: https://www.okx.com/account/my-api

- 처음에는 `OKX_FLAG=1` (데모 거래)로 테스트하세요
- API 키 권한: **Trade** (거래), **Read** (조회)

### 3. 실행

| 파일 | 설명 |
|------|------|
| `run.bat` | 서버 실행 (콘솔만) |
| `run-with-log.bat` | 서버 실행 + `logs/`에 로그 저장 |
| `restart-server.bat` | 기존 서버 종료 후 로그 모드로 재시작 |
| `stop-server.bat` | `.env`의 `OAT_PORT` 리스닝 프로세스 종료 |
| `update-zip.bat` | GitHub ZIP으로 코드 동기화 (data·.env 유지) + npm build |
| `git-pull-sync.bat` | `git pull --rebase` (원격 반영) |
| `git-push.bat` | fetch + rebase 후 push |

```bash
chmod +x run.sh
./run.sh
```

브라우저: **http://127.0.0.1:8080** (포트 변경: `.env`의 `OAT_PORT`)

로그 파일 (`run-with-log.bat` / `restart-server.bat`):
- `logs/oat-latest.log` — 최근 실행
- `logs/oat_YYYY-MM-DD.log` — 일별 누적
- `logs/oat_YYYY-MM-DD_HH-mm-ss.log` — 실행 세션별

**외부/LAN 접속** (`.env`):
```env
OAT_BIND_EXTERNAL=1
OAT_HOST=0.0.0.0
```
`run.bat` 실행 시 Windows 방화벽에 포트를 열려고 시도합니다(관리자 권한이면 자동). 다른 기기: `http://<이 PC IP>:8080` — **로그인 없음**, 공유기/인터넷에 노출 시 주의.

### 4. 개발 모드

```bash
# 백엔드
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080

# 프론트엔드 (별도 터미널)
cd frontend && npm install && npm run dev
```

## 사용 방법

1. **설정** 탭에서 API 키 입력 → "연결 테스트" 클릭
2. **모의투자** 모드에서 **단타** 또는 **장타** 선택
3. 주문 크기, 손절/익절 %, 레버리지 설정
4. **스캔** 버튼으로 AI 분석 결과 확인
5. **봇 시작** → 자동 스캔 → 조건 충족 시 자동 진입/청산
6. 전략 검증 후 **실거래** 모드로 전환

## 프로젝트 구조

```
backend/app/
├── main.py              FastAPI 서버 + API
├── config.py            환경 설정
├── models.py            데이터 모델
├── market/
│   ├── okx_client.py    OKX REST API
│   ├── data_provider.py 시세 데이터
│   ├── scanner.py       시장 스캔
│   ├── entry_analyzer.py 기술적 분석
│   └── live_exchange.py 실거래 주문
├── engine/
│   ├── trader.py        트레이딩 엔진 (핵심)
│   ├── portfolio.py     포트폴리오 관리
│   ├── exit_rules.py    청산 규칙
│   └── risk_manager.py  리스크 관리
└── storage/             설정 저장

frontend/src/            React 대시보드
```

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | /api/status | 전체 상태 |
| POST | /api/bot/start | 봇 시작 |
| POST | /api/bot/stop | 봇 중지 |
| POST | /api/scan | 즉시 스캔 |
| POST | /api/config | 설정 저장 |
| POST | /api/order/close | 포지션 청산 |
| POST | /api/order/close-all | 전량 청산 |
| WS | /ws | 실시간 업데이트 |

## 주의사항

- **실거래 전 반드시 모의투자(데모) 모드에서 충분히 테스트하세요**
- 암호화폐 선물 거래는 높은 리스크를 수반합니다
- 레버리지 사용 시 손실이 원금을 초과할 수 있습니다
- 이 프로그램은 투자 조언이 아니며, 모든 투자 결정과 손실은 사용자 본인의 책임입니다

## 라이선스

MIT License
