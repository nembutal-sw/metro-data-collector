# 아키텍처

## 선택 근거

시간표 플랫폼은 CPU 연산보다 다양한 공식 파일·HTML 파싱과 대량 적재 비중이 높습니다.
Python은 CSV, XLSX, HTML, PDF/OCR 데이터 처리가 빠르고, 경로 계산은 배열 기반 CSA로
분리할 수 있어 전체 개발·운영 효율이 가장 높습니다. 초기부터 별도 Rust/Go 서비스를
두지 않으며 실제 프로파일링으로 병목이 확인된 부분만 확장합니다.

## 런타임

운영 시크릿과 수집 URL은 서버 호스트의 `/docker/metro/.env`에 보관한다. Compose의
`migrate`, `api`, `worker`는 이 파일을 컨테이너 `/app/.env`로 읽기 전용 bind mount한다.
따라서 이미지와 프로젝트 배포 디렉터리에는 운영 키가 포함되지 않는다.

```text
Nginx web ── /api ──> FastAPI API ──> PostgreSQL
                         │                 ▲
                         │                 │
                     sync queue        sync worker
                                           │
                                  official APIs/files/web
```

- `web`: 정적 대시보드 제공, `/api`와 `/health` 역프록시
- `api`: 읽기 API와 인증된 동기화 작업 등록
- `worker`: 원천 점검, 조건부 다운로드, 파싱, 검증, 활성화
- `migrate`: API 기동 전에 Alembic 마이그레이션 실행
- `db`: 버전별 시간표와 운영 이력 보관

## 패키지 경계

- `collectors`: 원천별 HTTP 접근과 스트리밍 파서
- `domain`: 프레임워크 독립 타입과 수집 정책
- `ingestion`: staging, 품질 게이트, 원자적 활성화
- `quality`: 원천 공통 검사
- `routing`: 서비스일 시각과 CSA
- `repositories`: 명시적 PostgreSQL 쿼리
- `api`: 조회 및 운영 HTTP 인터페이스

## 활성화 트랜잭션

원천별 advisory lock을 획득하고 다음 작업을 하나의 트랜잭션에서 처리합니다.

1. 체크섬 중복 확인
2. 새 시간표 버전과 ingest batch 생성
3. `COPY`로 unlogged staging 적재
4. 원천·DB 품질검사
5. 정규화 테이블 물질화
6. `timetable_activation` 포인터 교체
7. 이전 활성 버전 `RETIRED` 처리

검사 실패 버전은 `FAILED`로 기록하고 활성 포인터는 변경하지 않습니다.
