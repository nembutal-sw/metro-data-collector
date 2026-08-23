"""Seed the operating service scope and source registry.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        INSERT INTO transit_operator (code, name_ko, name_en, website_url) VALUES
          ('SEOUL_METRO', '서울교통공사', 'Seoul Metro', 'https://www.seoulmetro.co.kr'),
          ('KORAIL', '한국철도공사', 'KORAIL', 'https://info.korail.com'),
          ('INCHEON_TRANSIT', '인천교통공사', 'Incheon Transit Corporation', 'https://www.ictr.or.kr'),
          ('SEOUL_METRO9', '서울시메트로9호선', 'Seoul Metro Line 9 Corporation', 'https://www.metro9.co.kr'),
          ('AREX', '공항철도', 'Airport Railroad', 'https://www.airportrailroad.com'),
          ('NEOTRANS', '네오트랜스', 'NeoTrans', 'https://www.shinbundang.co.kr'),
          ('UI_OPERATOR', '우이신설도시철도·우진메트로', NULL, 'https://www.ui-line.com'),
          ('SILLIM_OPERATOR', '남서울경전철·로템에스알에스', NULL, 'https://www.sillimlrt.com'),
          ('GIMPO_GOLDLINE_SRS', '김포골드라인에스알에스', NULL, 'https://gimpogoldline.com'),
          ('UIJEONGBU_OPERATOR', '의정부경량전철·우진메트로', NULL, 'https://www.ulrt.co.kr'),
          ('YONGIN_EVERLINE_OPERATION', '용인경량전철·용인에버라인운영', NULL, 'https://www.ever-line.co.kr'),
          ('GTX_A_OPERATION', '지티엑스에이운영', 'GTX-A Operation', 'https://www.gtx-a.com');

        INSERT INTO subway_line (code, name_ko, name_en, color, transport_mode) VALUES
          ('SEOUL_1', '수도권 1호선', 'Seoul Metropolitan Subway Line 1', '#0052A4', 'METRO'),
          ('SEOUL_2', '서울 2호선', 'Seoul Subway Line 2', '#00A84D', 'METRO'),
          ('SEOUL_3', '수도권 3호선', 'Seoul Metropolitan Subway Line 3', '#EF7C1C', 'METRO'),
          ('SEOUL_4', '수도권 4호선', 'Seoul Metropolitan Subway Line 4', '#00A5DE', 'METRO'),
          ('SEOUL_5', '서울 5호선', 'Seoul Subway Line 5', '#996CAC', 'METRO'),
          ('SEOUL_6', '서울 6호선', 'Seoul Subway Line 6', '#CD7C2F', 'METRO'),
          ('SEOUL_7', '수도권 7호선', 'Seoul Metropolitan Subway Line 7', '#747F00', 'METRO'),
          ('SEOUL_8', '서울 8호선', 'Seoul Subway Line 8', '#E6186C', 'METRO'),
          ('SEOUL_9', '서울 9호선', 'Seoul Subway Line 9', '#BDB092', 'METRO'),
          ('GYEONGUI_JUNGANG', '경의·중앙선', 'Gyeongui-Jungang Line', '#77C4A3', 'COMMUTER_RAIL'),
          ('SUIN_BUNDANG', '수인·분당선', 'Suin-Bundang Line', '#F5A200', 'COMMUTER_RAIL'),
          ('GYEONGCHUN', '경춘선', 'Gyeongchun Line', '#0C8E72', 'COMMUTER_RAIL'),
          ('GYEONGGANG', '경강선', 'Gyeonggang Line', '#003DA5', 'COMMUTER_RAIL'),
          ('SEOHAE', '서해선', 'Seohae Line', '#8FC31F', 'COMMUTER_RAIL'),
          ('AREX', '공항철도', 'Airport Railroad', '#0090D2', 'AIRPORT_RAIL'),
          ('SHINBUNDANG', '신분당선', 'Shinbundang Line', '#D4003B', 'METRO'),
          ('INCHEON_1', '인천 1호선', 'Incheon Subway Line 1', '#7CA8D5', 'METRO'),
          ('INCHEON_2', '인천 2호선', 'Incheon Subway Line 2', '#ED8B00', 'METRO'),
          ('UI_SINSEOL', '우이신설선', 'Ui-Sinseol Line', '#B7C452', 'LIGHT_RAIL'),
          ('SILLIM', '신림선', 'Sillim Line', '#6789CA', 'LIGHT_RAIL'),
          ('GIMPO_GOLD', '김포골드라인', 'Gimpo Goldline', '#A17800', 'LIGHT_RAIL'),
          ('UIJEONGBU_LRT', '의정부경전철', 'Uijeongbu Light Rail', '#FDA600', 'LIGHT_RAIL'),
          ('EVERLINE', '용인 에버라인', 'Yongin EverLine', '#56AD2D', 'LIGHT_RAIL'),
          ('GTX_A', 'GTX-A', 'Great Train Express A', '#9A6292', 'EXPRESS_RAIL');

        INSERT INTO line_operator_role (line_id, operator_id, role, valid_from)
        SELECT l.id, o.id, role_name::operator_role, DATE '1900-01-01'
        FROM (VALUES
          ('SEOUL_1', 'SEOUL_METRO', 'OPERATOR'), ('SEOUL_1', 'KORAIL', 'OPERATOR'),
          ('SEOUL_2', 'SEOUL_METRO', 'OPERATOR'),
          ('SEOUL_3', 'SEOUL_METRO', 'OPERATOR'), ('SEOUL_3', 'KORAIL', 'OPERATOR'),
          ('SEOUL_4', 'SEOUL_METRO', 'OPERATOR'), ('SEOUL_4', 'KORAIL', 'OPERATOR'),
          ('SEOUL_5', 'SEOUL_METRO', 'OPERATOR'), ('SEOUL_6', 'SEOUL_METRO', 'OPERATOR'),
          ('SEOUL_7', 'SEOUL_METRO', 'OPERATOR'), ('SEOUL_7', 'INCHEON_TRANSIT', 'OPERATOR'),
          ('SEOUL_8', 'SEOUL_METRO', 'OPERATOR'),
          ('SEOUL_9', 'SEOUL_METRO9', 'OPERATOR'), ('SEOUL_9', 'SEOUL_METRO', 'OPERATOR'),
          ('GYEONGUI_JUNGANG', 'KORAIL', 'OPERATOR'), ('SUIN_BUNDANG', 'KORAIL', 'OPERATOR'),
          ('GYEONGCHUN', 'KORAIL', 'OPERATOR'), ('GYEONGGANG', 'KORAIL', 'OPERATOR'),
          ('SEOHAE', 'KORAIL', 'OPERATOR'), ('AREX', 'AREX', 'OPERATOR'),
          ('SHINBUNDANG', 'NEOTRANS', 'OPERATOR'),
          ('INCHEON_1', 'INCHEON_TRANSIT', 'OPERATOR'), ('INCHEON_2', 'INCHEON_TRANSIT', 'OPERATOR'),
          ('UI_SINSEOL', 'UI_OPERATOR', 'OPERATOR'), ('SILLIM', 'SILLIM_OPERATOR', 'OPERATOR'),
          ('GIMPO_GOLD', 'GIMPO_GOLDLINE_SRS', 'OPERATOR'),
          ('UIJEONGBU_LRT', 'UIJEONGBU_OPERATOR', 'OPERATOR'),
          ('EVERLINE', 'YONGIN_EVERLINE_OPERATION', 'OPERATOR'),
          ('GTX_A', 'GTX_A_OPERATION', 'OPERATOR')
        ) AS mapping(line_code, operator_code, role_name)
        JOIN subway_line l ON l.code = mapping.line_code
        JOIN transit_operator o ON o.code = mapping.operator_code;

        INSERT INTO service_calendar (
            service_code, description, monday, tuesday, wednesday, thursday, friday,
            saturday, sunday, start_date, end_date
        ) VALUES
          ('WEEKDAY', '평일', true, true, true, true, true, false, false, '2000-01-01', '2099-12-31'),
          ('SATURDAY', '토요일', false, false, false, false, false, true, false, '2000-01-01', '2099-12-31'),
          ('SUNDAY_HOLIDAY', '일요일·공휴일', false, false, false, false, false, false, true, '2000-01-01', '2099-12-31');

        INSERT INTO source_registry (
            code, name, operator_id, kind, coverage, access_status, base_url,
            schedule_cron, stores_raw_artifact, uses_private_api,
            robots_checked_at, terms_checked_at, last_inspected_at, metadata
        ) VALUES
          ('SEOUL_OPEN_DATA_FULL_TIMETABLE', '서울 1~9호선 전체 열차운행시각표',
           (SELECT id FROM transit_operator WHERE code='SEOUL_METRO'), 'PUBLIC_DATASET',
           'FULL_STATIC', 'ENABLED', 'https://data.seoul.go.kr/dataList/OA-22522/L/1/datasetView.do',
           '0 3 * * *', true, false, NULL, '2026-08-23', '2026-08-23', '{"lines":["SEOUL_1","SEOUL_2","SEOUL_3","SEOUL_4","SEOUL_5","SEOUL_6","SEOUL_7","SEOUL_8","SEOUL_9"]}'),
          ('KORAIL_METRO_TIMETABLE', '코레일 광역전철 시간표',
           (SELECT id FROM transit_operator WHERE code='KORAIL'), 'DOWNLOAD_FILE',
           'FULL_STATIC', 'PENDING_REVIEW', 'https://www.korail.com/ticket/reserve/train-timeTable',
           '30 3 * * *', false, false, NULL, '2026-08-23', '2026-08-23', '{}'),
          ('INCHEON_1_TIMETABLE', '인천 1호선 방향·요일별 시간표',
           (SELECT id FROM transit_operator WHERE code='INCHEON_TRANSIT'), 'PUBLIC_DATASET',
           'FULL_STATIC', 'ENABLED', 'https://www.ictr.or.kr/main/railway/guidance/timetable1_se.jsp',
           '0 4 * * *', true, false, NULL, '2026-08-23', '2026-08-23', '{}'),
          ('INCHEON_2_TIMETABLE', '인천 2호선 방향·요일별 시간표',
           (SELECT id FROM transit_operator WHERE code='INCHEON_TRANSIT'), 'PUBLIC_DATASET',
           'FULL_STATIC', 'ENABLED', 'https://www.ictr.or.kr/main/railway/guidance/timetable2_se.jsp',
           '10 4 * * *', true, false, NULL, '2026-08-23', '2026-08-23', '{}'),
          ('AREX_TIMETABLE', '공항철도 공식 열차시간표',
           (SELECT id FROM transit_operator WHERE code='AREX'), 'DOWNLOAD_FILE',
           'FULL_STATIC', 'ENABLED', 'https://www.airportrailroad.com',
           '20 4 * * *', true, false, NULL, '2026-08-23', '2026-08-23', '{}'),
          ('SHINBUNDANG_WEB', '신분당선 공식 역별 시간표',
           (SELECT id FROM transit_operator WHERE code='NEOTRANS'), 'OFFICIAL_WEB',
           'FULL_STATIC', 'ENABLED', 'https://www.shinbundang.co.kr/dxline/dxline_time_gy.jsp',
           '30 4 * * *', true, false, '2026-08-23', '2026-08-23', '2026-08-23', '{"terms_unspecified":true}'),
          ('UI_SINSEOL_WEB', '우이신설선 공식 역별 시간표',
           (SELECT id FROM transit_operator WHERE code='UI_OPERATOR'), 'OFFICIAL_WEB',
           'FULL_STATIC', 'ENABLED', 'https://www.ui-line.com/html/intro/intro00/intro_00_01.php',
           '40 4 * * *', true, false, '2026-08-23', '2026-08-23', '2026-08-23', '{"terms_unspecified":true}'),
          ('SILLIM_WEB', '신림선 공식 역별 시간표',
           (SELECT id FROM transit_operator WHERE code='SILLIM_OPERATOR'), 'OFFICIAL_WEB',
           'FULL_STATIC', 'ENABLED', 'https://sillimlrt.com/kr/html/sub01/01010201.html',
           '50 4 * * *', true, false, '2026-08-23', '2026-08-23', '2026-08-23', '{"terms_unspecified":true}'),
          ('GIMPO_GOLD_WEB', '김포골드라인 공식 시간표',
           (SELECT id FROM transit_operator WHERE code='GIMPO_GOLDLINE_SRS'), 'OFFICIAL_WEB',
           'FULL_STATIC', 'ENABLED', 'https://gimpogoldline.com/?page_id=11835',
           '0 5 * * *', true, false, '2026-08-23', '2026-08-23', '2026-08-23', '{"terms_unspecified":true}'),
          ('UIJEONGBU_WEB', '의정부경전철 공식 시간표',
           (SELECT id FROM transit_operator WHERE code='UIJEONGBU_OPERATOR'), 'OFFICIAL_WEB',
           'FULL_STATIC', 'ENABLED', 'https://www.ulrt.co.kr/doc/contents/information/time.php',
           '10 5 * * *', true, false, '2026-08-23', '2026-08-23', '2026-08-23', '{"terms_unspecified":true,"image_based":true}'),
          ('EVERLINE_WEB', '용인 에버라인 공식 운행시간',
           (SELECT id FROM transit_operator WHERE code='YONGIN_EVERLINE_OPERATION'), 'OFFICIAL_WEB',
           'PARTIAL', 'DISABLED_ROBOTS', 'https://www.ever-line.co.kr/page/?M2_IDX=28909',
           NULL, false, false, '2026-08-23', '2026-08-23', '2026-08-23', '{"robots":"User-agent: * / Disallow: /"}'),
          ('GTX_A_OFFICIAL', 'GTX-A 공식 시간표',
           (SELECT id FROM transit_operator WHERE code='GTX_A_OPERATION'), 'OFFICIAL_WEB',
           'PARTIAL', 'DISABLED_TECHNICAL', 'https://www.gtx-a.com',
           NULL, false, false, '2026-08-23', '2026-08-23', '2026-08-23', '{"reason":"automated access blocked"}'),
          ('SEOUL_REALTIME_POSITION', '서울 지하철 실시간 열차 위치',
           (SELECT id FROM transit_operator WHERE code='SEOUL_METRO'), 'OPEN_API',
           'REALTIME_ONLY', 'PENDING_KEY', 'https://data.seoul.go.kr/dataList/datasetView.do?infId=OA-12601&serviceKind=1&srvType=A',
           NULL, false, false, NULL, '2026-08-23', '2026-08-23', '{}'),
          ('SEOUL_SERVICE_ALERT', '서울 지하철 운행 알림',
           (SELECT id FROM transit_operator WHERE code='SEOUL_METRO'), 'OPEN_API',
           'REALTIME_ONLY', 'PENDING_KEY', 'https://data.seoul.go.kr/dataList/OA-22718/A/1/datasetView.do',
           NULL, false, false, NULL, '2026-08-23', '2026-08-23', '{}');

        INSERT INTO source_license (
            source_id, license_name, license_url, attribution_text, commercial_use_allowed,
            modification_allowed, redistribution_allowed, raw_storage_allowed,
            terms_unspecified, checked_at, notes
        ) VALUES
          ((SELECT id FROM source_registry WHERE code='SEOUL_OPEN_DATA_FULL_TIMETABLE'),
           '공공누리 제1유형', 'https://www.kogl.or.kr/info/licenseType1.do', '서울 열린데이터광장',
           true, true, true, true, false, '2026-08-23', '출처 표시 필요'),
          ((SELECT id FROM source_registry WHERE code='INCHEON_1_TIMETABLE'),
           '이용 제한 없음', NULL, '인천교통공사', true, true, true, true, false, '2026-08-23', NULL),
          ((SELECT id FROM source_registry WHERE code='INCHEON_2_TIMETABLE'),
           '이용 제한 없음', NULL, '인천교통공사', true, true, true, true, false, '2026-08-23', NULL);

        INSERT INTO source_license (
            source_id, attribution_text, terms_unspecified, checked_at,
            commercial_use_allowed, modification_allowed, redistribution_allowed,
            raw_storage_allowed, notes
        )
        SELECT id, name, true, '2026-08-23', NULL, NULL, NULL, NULL,
               '공식 공개 페이지이며 명시적 금지 조건이 없어 수집 기본 활성화'
        FROM source_registry
        WHERE code IN ('AREX_TIMETABLE', 'SHINBUNDANG_WEB', 'UI_SINSEOL_WEB',
                       'SILLIM_WEB', 'GIMPO_GOLD_WEB', 'UIJEONGBU_WEB');
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DELETE FROM source_license;
        DELETE FROM source_registry;
        DELETE FROM service_calendar WHERE service_code IN ('WEEKDAY','SATURDAY','SUNDAY_HOLIDAY');
        DELETE FROM line_operator_role;
        DELETE FROM subway_line;
        DELETE FROM transit_operator;
        """
    )
