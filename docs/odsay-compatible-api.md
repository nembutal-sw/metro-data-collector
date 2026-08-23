# ODsay v1.8 호환 경로 API

플랫폼의 시간표 기반 최단 도착 경로를 ODsay `searchPubTransPathT`의 도시 내
JSON 구조인 `result.path[].info/subPath[]`로 변환해 제공합니다.

좌표 기반 주변 역 조회는 ODsay `pointSearch`와 같은 요청·응답 구조로 제공합니다.

## 요청

```http
GET /odsay/v1/api/searchPubTransPathT?origin=강남&destination=서울역&departure_at=2026-08-23T09:00:00%2B09:00
X-API-Key: <발급받은_API_키>
```

`X-API-Key` 헤더가 필요합니다. 헤더를 설정할 수 없는 ODsay 호환 클라이언트는
`apiKey=<발급키>` 쿼리를 사용할 수 있지만, URL과 접근 로그에 키가 남을 수 있으므로
헤더 방식을 권장합니다. 서버에는 원문이 아닌 SHA-256 해시만 저장합니다.

GET과 POST를 모두 지원하지만 입력값은 쿼리 문자열로 받습니다. `origin`과
`destination`에는 부분 검색어가 아닌 확정된 역명을 전달해야 합니다. DB가
`강남`으로 관리하는 역은 `강남`과 `강남역`을 모두 허용합니다. 앞뒤·중간 공백과
마지막 `역` 한 글자는 정규화하지만 `강`, `강남역 2호선`처럼 일부 이름이나 노선이
붙은 값은 경로 입력으로 사용할 수 없습니다. 호출 전
`GET /api/v1/stations?q=강남`으로 실제 등록 이름과 노선을 확인하는 방식을 권장합니다.

| 파라미터 | 필수 | 설명 |
|---|---:|---|
| `origin` | Y | 출발역명 |
| `destination` | Y | 도착역명 |
| `departure_at` | N | ISO 8601 출발 기준 시각, 생략 시 현재 서울 시각 |
| `walking_mode` | N | `standard`, `slow`, `accessible` |
| `transfer_seconds` | N | 역별 환승값이 없을 때 적용할 초 단위 기본값 |
| `transfer_buffer_seconds` | N | 환승 안전 여유시간 |
| `output` | N | `json`만 지원 |
| `apiKey` | 조건부 | `X-API-Key` 헤더를 사용하지 못할 때 전달하는 소비자 키 |

## 응답 매핑

- 지하철 경로: `pathType=1`
- 승차 구간: `subPath[].trafficType=1`
- 환승 보행: `subPath[].trafficType=3`
- 환승 횟수: `info.subwayTransitCount`
- 전체 소요시간: `info.totalTime` (분, 최초 열차 대기 포함)
- 실제 열차 대기 합: `info.totalIntervalTime` (분)
- 노선 코드는 ODsay 공식 지하철 노선 타입표와 같은 값을 사용합니다.

현재 계산하지 않는 운임은 `payment=null`, ODsay 지도 보간점 식별자인
`mapObj`는 빈 문자열로 반환합니다. `stationID`는 정수 형태의 플랫폼 로컬
식별자이며 ODsay 고유 역 ID가 아닙니다. 역 좌표가 없으면 좌표와
`pointDistance`는 `null`이고, 거리값을 임의의 좌표로 만들지 않습니다.

검색 결과가 없으면 HTTP 404와 다음 JSON을 반환합니다.

```json
{
  "error": {
    "code": "-99",
    "message": "검색결과가 없습니다."
  }
}
```

정확한 열차별 출발·도착 시각과 환승 보행/대기 세부값이 필요한 내부
클라이언트는 기존 `/api/v1/travel-time` 응답을 사용합니다.

## 좌표 기반 주변 역 조회

```http
GET /odsay/v1/api/pointSearch?x=127.0276&y=37.4979&radius=1000&stationClass=2&apiKey=<발급키>
```

`x`는 경도, `y`는 위도이며 WGS84 십진도 좌표를 사용합니다. `radius`는 미터
단위로 기본값 250, 허용 범위는 1~20,000입니다. 현재 `stationClass=2`,
`lang=0`, `output=json`만 지원합니다. GET과 POST를 모두 사용할 수 있습니다.

응답은 `result.count`와 `result.station[]` 아래에 `stationClass`, `stationName`,
플랫폼 로컬 `stationID`, `type`, `laneName`, `laneCity`, `x`, `y`를 반환합니다.
ODsay 호환 구조에는 조회 기준점과의 거리 필드가 없으므로 별도 필드를 추가하지
않습니다.

```json
{
  "result": {
    "count": 2,
    "station": [
      {
        "stationClass": 2,
        "stationName": "강남",
        "stationID": 2126536365,
        "type": 2,
        "laneName": "서울 2호선",
        "laneCity": "수도권",
        "x": 127.02795,
        "y": 37.49805,
        "arsID": "",
        "ebid": "",
        "nonstopStation": 0
      },
      {
        "stationClass": 2,
        "stationName": "강남",
        "stationID": 1306444089,
        "type": 109,
        "laneName": "신분당선",
        "laneCity": "수도권",
        "x": 127.027879,
        "y": 37.497385,
        "arsID": "",
        "ebid": "",
        "nonstopStation": 0
      }
    ]
  }
}
```

## ODsay `pointSearch` 지원 비교

비교 기준은 [ODsay 공식 Web API 레퍼런스](https://lab.odsay.com/guide/releaseReference?platform=web)의
`pointSearch` 명세입니다.

| 기능·필드 | ODsay | 이 API | 지원 상태 |
|---|---|---|---|
| GET/POST 및 `result.count/station[]` | 여러 POI를 같은 응답 구조로 조회 | 지하철역을 같은 응답 구조로 조회 | ✅ 지하철 동일 지원 |
| `x` 경도 / `y` 위도 | WGS84 좌표 | WGS84 좌표 | ✅ 동일 지원 |
| `radius` | 기본 250m | 기본 250m, 최대 20km | ⚠️ 범위 차이 |
| `stationClass=2` | 지하철역 | 지하철역 | ✅ 동일 지원 |
| `stationClass=1` | 버스정류장 | 데이터 없음 | ❌ **제공되지 않음** |
| `stationClass=3~7` | 기차역·터미널·공항·항만(7은 문서상 업데이트 예정) | 도시철도역 외 POI 데이터 없음 | ❌ **제공되지 않음** |
| 다중 클래스 `1:2` | 버스+지하철 동시 조회 | `stationClass=2`만 허용 | ❌ **제공되지 않음** |
| `lang=1~5` | 영문·일문·중문·베트남어 | `lang=0` 국문만 허용 | ❌ **제공되지 않음** |
| `output=xml` | XML 응답 | JSON만 허용 | ❌ **제공되지 않음** |
| `stationID` | ODsay 고유 ID | 플랫폼 로컬 정수 ID | ⚠️ 값 체계 다름 |
| `type/laneName/laneCity/x/y` | 노선·지역·좌표 | 같은 필드명으로 제공 | ✅ 동일 지원 |
| 다국어 역명 필드 | 제공 | 호환 응답에 없음 | ❌ **제공되지 않음** |
| `arsID/ebid` | 버스정류장 식별자 | 지하철 결과에서는 빈 문자열 | ❌ **제공되지 않음** |
| 기준점과의 거리 | 별도 필드 없음 | 네이티브 API의 `distance_m`으로 제공 | ⚠️ 자체 API 확장 |
| 데이터 원천 | ODsay 자체 데이터 | 국가철도공단 공개 좌표 | ⚠️ 검색 결과 차이 가능 |

> **제공되지 않음:** 버스정류장, 기차역·터미널·공항·항만, 다국어 응답,
> XML 출력과 ODsay 고유 `stationID`는 사용할 수 없습니다. `stationClass`,
> `lang`, `output`에 지원하지 않는 값을 보내면 HTTP 400과 오류 코드 `-8`을
> 반환합니다. 홈페이지에서는 이 항목을 빨간색으로 표시합니다.

```http
GET /odsay/v1/api/pointSearch?x=127.0276&y=37.4979&stationClass=1:2&lang=1&output=xml&apiKey=<발급키>
```

```json
{
  "error": {
    "code": "-8",
    "message": "현재 stationClass=2, lang=0, output=json만 지원합니다."
  }
}
```

거리까지 필요하면 네이티브 API를 사용합니다.

```http
GET /api/v1/stations/nearby?latitude=37.4979&longitude=127.0276&radius_m=1000&limit=10
X-API-Key: <발급받은_API_키>
```

네이티브 응답은 같은 이름의 환승역을 한 역으로 묶으며 `distance_m`, `lines[]`,
`coordinate_source_code`, `coordinate_basis_date`를 포함합니다. 좌표는 국가철도공단
도시·광역철도 역사정보 공개 XLSX에서 수집하며, 수도권 경계 밖 값과 기존 좌표에서
2km를 초과해 이동하는 갱신은 품질검사에서 제외합니다.
