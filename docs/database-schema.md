# 데이터베이스 스키마

## 기준정보

- `transit_operator`: 운영 관련 법인·기관
- `subway_line`: 이용자에게 보이는 운행 서비스
- `line_operator_role`: 소유·사업시행·운송·관리운영 역할
- `station`: 물리 역 복합체
- `station_alias`: 검색용 다국어·구명칭
- `line_station`: 노선별 승강장·정차점과 순서
- `source_identifier`: 원천별 역·노선 코드
- `transfer_connection`: 방향성 환승 보행 연결

## 시간표

- `service_calendar`, `service_exception`: 요일과 공휴일·임시 예외
- `timetable_version`: 체크섬과 적용 기간을 가진 불변 버전
- `trip`: 열차번호, 방향, 기종점, 완급
- `stop_time`: 서비스일 누적 초 단위 도착·출발
- `timetable_activation`: 노선·원천별 현재 활성 포인터
- `route_path`: 계산 결과 캐시

`stop_time`은 시간표 버전 UUID를 기준으로 8개 해시 파티션을 사용합니다.
`24:10`, `25:05`는 각각 87,000초, 90,300초로 저장합니다.

## 원천·운영

- `source_registry`, `source_license`, `source_artifact`
- `sync_job`, `sync_job_error`, `ingest_batch`
- `data_quality_result`
- `realtime_train_position`, `service_alert`, `service_alert_target`

전체 정의와 제약조건은 `migrations/versions/0001_initial_schema.py`를 기준으로 합니다.

