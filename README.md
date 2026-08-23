# Metro Data Collector

수도권 도시철도의 공식 정적 시간표, 역·노선, 환승, 실시간 위치와 운행 알림을
버전별로 수집·검증·보관하고 막차 경로 계산에 제공하는 독립 플랫폼입니다.

## 구성

- Python 3.12+, FastAPI, psycopg 3
- PostgreSQL 17, Alembic
- 스트리밍 CSV 파서와 PostgreSQL `COPY`
- 역방향 Connection Scan Algorithm 기반 도착 마감·막차 계산 코어
- Nginx 정적 운영 대시보드와 API 역프록시
- Docker Compose: `db`, `migrate`, `api`, `worker`, `web`

## 시작하기

1. `.env.example`을 참고해 서버의 `/docker/metro/.env`에 `ADMIN_API_KEY`,
   `PUBLIC_API_KEY_HASHES`와 외부 수집 API 키를 입력합니다.
2. 서울 전체 시간표 수집을 사용할 때는 현재 공식 파일의 직접 다운로드 주소를
   `SEOUL_TIMETABLE_DOWNLOAD_URL`에 입력합니다.
3. 서버에서 프로젝트 디렉터리로 이동해 `docker compose up --build -d`를 실행합니다.
4. `http://localhost:8080`에서 대시보드를, `http://localhost:8080/docs`에서 API 문서를 확인합니다.

ODsay v1.8 형태의 JSON 경로 조회:

```bash
curl --get \
  -H "X-API-Key: <발급받은_API_키>" \
  --data-urlencode "origin=강남" \
  --data-urlencode "destination=서울역" \
  --data-urlencode "departure_at=2026-08-23T09:00:00+09:00" \
  http://localhost:8080/odsay/v1/api/searchPubTransPathT
```

입력은 확정된 역명이며 `강남`과 `강남역`을 모두 허용합니다. 호출 전
`GET /api/v1/stations?q=강남`으로 등록 역명을 검색할 수 있습니다. 응답 필드와
ODsay 호환 범위는 [`docs/odsay-compatible-api.md`](docs/odsay-compatible-api.md)를 참고하세요.

좌표 기반 주변 역 조회:

```bash
curl --get \
  -H "X-API-Key: <발급받은_API_키>" \
  --data-urlencode "x=127.0276" \
  --data-urlencode "y=37.4979" \
  --data-urlencode "radius=1000" \
  --data-urlencode "stationClass=2" \
  http://localhost:8080/odsay/v1/api/pointSearch
```

공식 좌표 XLSX는 API 키 없이 수집하며, 거리값이 필요한 클라이언트는
`GET /api/v1/stations/nearby`를 사용할 수 있습니다.

관리자 수동 동기화 요청 예시:

```bash
curl -X POST \
  -H "X-Admin-API-Key: <ADMIN_API_KEY>" \
  http://localhost:8080/api/v1/admin/sync/SEOUL_OPEN_DATA_FULL_TIMETABLE
```

## 개발 검증

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check src tests migrations
.venv/bin/mypy src
```

Windows에서는 `.venv/bin` 대신 `.venv/Scripts`를 사용합니다.

Docker Compose의 `migrate`, `api`, `worker`는 서버 호스트의 `/docker/metro/.env`를
컨테이너 `/app/.env`에 읽기 전용으로 마운트합니다. 프로젝트 루트 `.env`는 로컬 개발용이며
Docker 배포에는 주입되지 않습니다. 서버 파일은 `chmod 600 /docker/metro/.env`로 보호합니다.
컨테이너의 비특권 사용자에는 읽기 전용 ACL만 추가합니다.
현재 서버의 Compose 파일은
`/home/sw6725_admin/metro-data-collector/docker-compose.yml`에 있습니다.

## 안전 원칙

- 수집 실패 또는 품질검사 실패 시 현재 활성 버전을 교체하지 않습니다.
- 명시적 금지 조건이 없는 공식 공개 페이지는 기본 활성화합니다.
- robots 차단, 이용조건의 명시적 금지, 로그인·WAF 우회, 비공개 API 사용은 허용하지 않습니다.
- API 키와 전체 원본 응답을 로그에 남기지 않습니다.
- 외부 API 호출은 DB에 일일 사용량을 예약한 뒤 수행하며, 재시도도 요청 건수에
  포함합니다. `429 Retry-After` 동안은 공급자 단위로 추가 호출을 차단합니다.
- 공개 CSV/XLSX 다운로드를 우선해 인증 API의 일일 호출량을 보존합니다.
- 커밋과 원격 저장소 Push는 별도 지시가 있을 때만 수행합니다.

상세 설계는 [`docs/architecture.md`](docs/architecture.md)부터 확인하세요.
