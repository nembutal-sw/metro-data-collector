"""Register keyless KRIC standard timetable downloads for private operators.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE source_registry source
        SET name=input.name,
            kind='DOWNLOAD_FILE',
            coverage='FULL_STATIC',
            access_status='ENABLED',
            base_url='https://openapi.kric.go.kr/rips/M_01_01/intro.do?lcd=A',
            expected_update_interval=interval '1 day',
            stores_raw_artifact=true,
            uses_private_api=false,
            terms_checked_at='2026-08-23',
            last_inspected_at='2026-08-23',
            metadata=source.metadata || jsonb_build_object(
                'provider', '국가철도공단 철도산업정보센터',
                'dataset_type', '표준데이터 운행정보',
                'dataset_id', input.dataset_id,
                'line_code', input.line_code,
                'download_url_env', input.download_url_env,
                'key_required', false,
                'dataset_as_of', input.dataset_as_of
            )
        FROM (VALUES
            ('KORAIL_METRO_TIMETABLE', '코레일 수도권 광역전철 표준데이터 운행정보', 6,
             'MULTI', 'KRIC_KORAIL_TIMETABLE_DOWNLOAD_URL', '2026-05-31'),
            ('AREX_TIMETABLE', '공항철도 표준데이터 운행정보', 7, 'AREX',
             'KRIC_AREX_TIMETABLE_DOWNLOAD_URL', '2025-12-31'),
            ('SHINBUNDANG_WEB', '신분당선 표준데이터 운행정보', 15, 'SHINBUNDANG',
             'KRIC_SHINBUNDANG_TIMETABLE_DOWNLOAD_URL', '2026-06-18'),
            ('UI_SINSEOL_WEB', '우이신설선 표준데이터 운행정보', 911, 'UI_SINSEOL',
             'KRIC_UI_SINSEOL_TIMETABLE_DOWNLOAD_URL', '2022-05-30'),
            ('SILLIM_WEB', '신림선 표준데이터 운행정보', 1221, 'SILLIM',
             'KRIC_SILLIM_TIMETABLE_DOWNLOAD_URL', '2025-09-23'),
            ('GIMPO_GOLD_WEB', '김포골드라인 표준데이터 운행정보', 903, 'GIMPO_GOLD',
             'KRIC_GIMPO_GOLD_TIMETABLE_DOWNLOAD_URL', '2026-06-16'),
            ('UIJEONGBU_WEB', '의정부경전철 표준데이터 운행정보', 17, 'UIJEONGBU_LRT',
             'KRIC_UIJEONGBU_TIMETABLE_DOWNLOAD_URL', '2023-09-06')
        ) AS input(code, name, dataset_id, line_code, download_url_env, dataset_as_of)
        WHERE source.code=input.code;

        UPDATE source_license license
        SET attribution_text='국가철도공단 철도산업정보센터 및 해당 운영기관',
            raw_storage_allowed=true,
            checked_at='2026-08-23',
            notes='KRIC 표준데이터 공개 파일. 별도 이용조건이 명시되지 않아 기본 활성화 정책 적용'
        FROM source_registry source
        WHERE license.source_id=source.id
          AND source.code IN (
              'AREX_TIMETABLE', 'SHINBUNDANG_WEB', 'UI_SINSEOL_WEB',
              'SILLIM_WEB', 'GIMPO_GOLD_WEB', 'UIJEONGBU_WEB'
          );

        INSERT INTO source_license (
            source_id, attribution_text, terms_unspecified, checked_at,
            commercial_use_allowed, modification_allowed, redistribution_allowed,
            raw_storage_allowed, notes
        )
        SELECT source.id, '국가철도공단 철도산업정보센터 및 한국철도공사',
               true, '2026-08-23', NULL, NULL, NULL, true,
               'KRIC 표준데이터 공개 파일. 별도 이용조건이 명시되지 않아 기본 활성화 정책 적용'
        FROM source_registry source
        WHERE source.code='KORAIL_METRO_TIMETABLE'
          AND NOT EXISTS (
              SELECT 1 FROM source_license license WHERE license.source_id=source.id
          );
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE source_registry
        SET metadata=metadata - 'provider' - 'dataset_type' - 'dataset_id' - 'line_code'
                     - 'download_url_env' - 'key_required' - 'dataset_as_of'
        WHERE code IN (
            'AREX_TIMETABLE', 'SHINBUNDANG_WEB', 'UI_SINSEOL_WEB',
            'SILLIM_WEB', 'GIMPO_GOLD_WEB', 'UIJEONGBU_WEB',
            'KORAIL_METRO_TIMETABLE'
        );
        """
    )
