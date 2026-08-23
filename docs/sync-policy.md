# 동기화 정책

## 주기

- 정적 시간표·역·노선: 하루 1회 변경 확인
- 운행 알림: 구현 단계에서 1분 주기
- 실시간 위치: 조회 수요가 있을 때 짧은 TTL로 수집
- 공휴일: 매년 다음 연도 자료 동기화

## 네트워크

- `ETag`, `If-Modified-Since`, SHA-256 체크섬으로 중복 방지
- 기본 30초 timeout, 지수 백오프 재시도
- 원천별 낮은 요청량과 식별 가능한 User-Agent
- 로그인, CAPTCHA, WAF, robots 차단 우회 금지

## 멱등성과 장애

- `source + checksum` 유일 제약
- 작업별 idempotency key
- 원천별 PostgreSQL advisory lock
- 워커 다중 실행 시 `FOR UPDATE SKIP LOCKED`
- 실패 시 활성 시간표와 원본 버전 보존

