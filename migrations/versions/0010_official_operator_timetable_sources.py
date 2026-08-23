"""Prefer current operator timetable pages over dated KRIC copies.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE source_registry source
        SET name=input.name,
            kind=input.kind::source_kind,
            base_url=input.base_url,
            expected_update_interval=interval '1 day',
            access_status='ENABLED',
            stores_raw_artifact=true,
            uses_private_api=false,
            terms_checked_at=DATE '2026-08-23',
            last_inspected_at=DATE '2026-08-23',
            metadata=source.metadata || input.metadata
        FROM (VALUES
            (
                'AREX_TIMETABLE',
                '공항철도 공식 전체 열차시간표',
                'DOWNLOAD_FILE',
                'https://www.airportrailroad.com/train/normal/info/010/0',
                jsonb_build_object(
                    'provider', '공항철도주식회사',
                    'collection_mode', 'official_xlsx_discovery',
                    'operator_effective_from', '2025-12-29',
                    'official_file_last_modified', '2026-04-23',
                    'kric_fallback_dataset_id', 7,
                    'tls_compatibility_exception', true
                )
            ),
            (
                'UI_SINSEOL_WEB',
                '우이신설선 공식 역별 시간표',
                'OFFICIAL_WEB',
                'https://www.ui-line.com/html/intro/intro00/intro_00_01.php',
                jsonb_build_object(
                    'provider', '우이신설도시철도',
                    'collection_mode', 'station_html_bundle',
                    'official_page_verified_at', '2026-08-23',
                    'kric_fallback_dataset_id', 911,
                    'tls_compatibility_exception', true
                )
            ),
            (
                'SILLIM_WEB',
                '신림선 공식 역별 시간표',
                'OFFICIAL_WEB',
                'https://www.sillimlrt.com/kr/html/sub01/01010201.html',
                jsonb_build_object(
                    'provider', '신림선도시철도',
                    'collection_mode', 'station_html_bundle',
                    'official_page_verified_at', '2026-08-23',
                    'kric_fallback_dataset_id', 1221,
                    'tls_compatibility_exception', true
                )
            ),
            (
                'UIJEONGBU_WEB',
                '의정부경전철 공식 역별 시간표',
                'OFFICIAL_WEB',
                'https://www.ulrt.co.kr/doc/contents/information/time.php',
                jsonb_build_object(
                    'provider', '의정부경량전철주식회사',
                    'collection_mode', 'official_image_bundle_ocr',
                    'operator_effective_from', '2025-12-31',
                    'official_images_last_modified', '2025-12-31',
                    'kric_fallback_dataset_id', 17,
                    'schedule_policy', 'time_band_headway_with_published_station_times'
                )
            )
        ) AS input(code, name, kind, base_url, metadata)
        WHERE source.code=input.code;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE source_registry source
        SET name=input.name,
            kind='DOWNLOAD_FILE',
            base_url='https://openapi.kric.go.kr/rips/M_01_01/intro.do?lcd=A',
            metadata=source.metadata
                - 'collection_mode'
                - 'operator_effective_from'
                - 'official_file_last_modified'
                - 'official_images_last_modified'
                - 'official_page_verified_at'
                - 'kric_fallback_dataset_id'
                - 'tls_compatibility_exception'
                - 'schedule_policy'
        FROM (VALUES
            ('AREX_TIMETABLE', '공항철도 표준데이터 운행정보'),
            ('UI_SINSEOL_WEB', '우이신설선 표준데이터 운행정보'),
            ('SILLIM_WEB', '신림선 표준데이터 운행정보'),
            ('UIJEONGBU_WEB', '의정부경전철 표준데이터 운행정보')
        ) AS input(code, name)
        WHERE source.code=input.code;
        """
    )
