# MeetBack 연동

MeetBack은 이 프로젝트 DB에 직접 접속하지 않고 내부 REST API를 호출합니다.

## 권장 흐름

1. `/api/v1/stations`에서 사용자의 역 입력을 canonical station ID로 변환
2. 모임 종료 후보시각, 출발·도착 도보시간, 안전 여유를 계산
3. `/api/v1/routes/last-train` 호출
4. 결과의 `timetable_basis_date`, 출처, 신뢰도, 미지원 구간을 사용자 화면에 표시

초기에는 MeetBack이 지도 API로 구한 도보 초를 요청에 넣습니다. 향후 이 서비스가
도보 경로를 직접 계산할 때만 `KAKAO_MOBILITY_REST_API_KEY` 등을 활성화합니다.

## 오류 처리

- `404`: 활성 시간표 또는 해당 경로 없음
- `503`: DB나 필수 원천 구성 불가
- 미지원 구간: 전체 요청 실패로 숨기지 않고 응답 필드로 노출
- 외부 원천 장애: 저장된 현재 활성 버전으로 계속 계산

내부 네트워크에서는 Nginx의 `/api/v1` 주소를 사용하고 관리자 동기화 경로는
MeetBack 일반 애플리케이션 키와 분리합니다.

