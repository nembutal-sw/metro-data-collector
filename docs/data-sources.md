# 공식 데이터 원천

| 코드 | 원천 | 기본 접근 |
|---|---|---|
| `SEOUL_OPEN_DATA_FULL_TIMETABLE` | [서울 1~9호선 전체 열차운행시각표](https://www.data.go.kr/data/15098251/fileData.do) | 활성·구현 |
| `KORAIL_METRO_TIMETABLE` | 코레일 광역전철 시간표 | 개별 파일 조건 검토 |
| `INCHEON_1_TIMETABLE` | [인천 1호선 평일 상행](https://www.data.go.kr/data/15051203/fileData.do) 외 방향·요일별 4개 파일 | 활성·구현 |
| `INCHEON_2_TIMETABLE` | [인천 2호선 평일 상행](https://www.data.go.kr/data/15051210/fileData.do) 외 방향·요일별 4개 파일 | 활성·구현 |
| `AREX_TIMETABLE` | [공항철도 공식 전체 열차시간표](https://www.airportrailroad.com/train/normal/info/010/0) | 활성·XLSX 자동 발견 |
| `SHINBUNDANG_WEB` | 신분당선 공식 역별 시간표 | 활성 |
| `UI_SINSEOL_WEB` | [우이신설선 공식 역별 시간표](https://www.ui-line.com/html/intro/intro00/intro_00_01.php) | 활성·HTML 변경 감지 |
| `SILLIM_WEB` | [신림선 공식 역별 시간표](https://www.sillimlrt.com/kr/html/sub01/01010201.html) | 활성·HTML 변경 감지 |
| `GIMPO_GOLD_WEB` | 김포골드라인 공식 시간표 | 활성 |
| `UIJEONGBU_WEB` | [의정부경전철 공식 역별 시간표](https://www.ulrt.co.kr/doc/contents/information/time.php) | 활성·이미지 변경 감지 및 OCR |
| `EVERLINE_WEB` | 용인 에버라인 운행 안내 | robots 전체 차단으로 비활성 |
| `GTX_A_OFFICIAL` | GTX-A 공식 홈페이지 | 자동 접근 차단으로 비활성 |
| `SEOUL_REALTIME_POSITION` | 서울 실시간 열차 위치 API | 인증키 필요 |
| `SEOUL_SERVICE_ALERT` | 서울 지하철 운행 알림 API | 인증키 필요 |
| `KRIC_STATION_COORDINATES` | [국가철도공단 도시·광역철도 역사정보](https://www.data.go.kr/data/15093755/fileData.do) | 활성·공개 XLSX·API 키 불필요 |

인천 방향·요일별 공식 데이터셋 페이지:

- 1호선: [평일 상행](https://www.data.go.kr/data/15051203/fileData.do), [평일 하행](https://www.data.go.kr/data/15051204/fileData.do), [휴일 상행](https://www.data.go.kr/data/15051205/fileData.do), [휴일 하행](https://www.data.go.kr/data/15051206/fileData.do)
- 2호선: [평일 상행](https://www.data.go.kr/data/15051210/fileData.do), [평일 하행](https://www.data.go.kr/data/15051208/fileData.do), [휴일 상행](https://www.data.go.kr/data/15051209/fileData.do), [휴일 하행](https://www.data.go.kr/data/15051207/fileData.do)

원천 URL, 마지막 확인일, 이용조건, robots 결과는 `source_registry`와
`source_license`에 버전성 이력으로 보관합니다. 현재 실제 수집·활성화가 검증된
어댑터는 서울 전체 시간표, 인천 1·2호선, 공항철도, 우이신설선, 신림선,
의정부경전철입니다.

역 좌표 원본은 역번호, 역명, 노선명, 영문 역명, 위도·경도와 데이터기준일자를
제공합니다. 수집기는 수도권 경계 밖 좌표를 제외하고 활성 역의 90% 이상이
매칭될 때만 반영합니다. 기존 좌표에서 2km를 초과해 이동하는 갱신은 차단하며,
원본 파일과 역별 `station_coordinate_observation`을 함께 보관합니다.

## 환경변수

- 선택(API 사용 시): `SEOUL_OPEN_DATA_API_KEY`, `SEOUL_SUBWAY_REALTIME_API_KEY`
- 선택(승인된 REST API 사용 시): `DATA_GO_KR_SERVICE_KEY`
- 선택: `KRIC_API_KEY`, `KAKAO_MOBILITY_REST_API_KEY`
- 내부: `ADMIN_API_KEY`
- 공식 파일 위치: `SEOUL_TIMETABLE_DOWNLOAD_URL`, `INCHEON_*_URL`

현재 서울·인천 정적 시간표는 공공데이터포털의 공개 파일 URL을 직접 사용하므로
외부 API 키가 필요하지 않습니다. 공공데이터포털 서비스키 하나를 여러 승인 서비스에
사용할 수 있지만, 각 서비스의 활용신청 승인은 별도로 필요합니다.

공항철도·우이신설선·신림선·의정부경전철은 공개된 운영기관 파일/페이지를 하루에
한 번 확인하므로 API 키와 일일 API 예산을 소비하지 않습니다. ETag·Last-Modified가
없는 페이지는 전체 묶음 SHA-256이 달라진 경우에만 새 버전을 만들고, 구조·레코드 수·
운행 시각 단조성 품질검사를 모두 통과해야 활성화합니다. 공식 페이지의 TLS 체인이
OpenSSL 기본 정책과 호환되지 않는 공항철도·우이신설선·신림선은 해당 호스트에만
TLS 호환 예외를 적용하고, 수집 결과에는 동일한 품질 게이트를 적용합니다.

정확한 발급처와 용도는 `.env.example` 주석에 기록합니다.
