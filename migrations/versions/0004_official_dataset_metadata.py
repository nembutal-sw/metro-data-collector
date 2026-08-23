"""Record the verified public-data dataset pages.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE source_registry
        SET base_url='https://www.data.go.kr/data/15098251/fileData.do',
            last_inspected_at='2026-08-23',
            metadata=metadata || jsonb_build_object(
                'dataset_page', 'https://www.data.go.kr/data/15098251/fileData.do',
                'download_url_env', 'SEOUL_TIMETABLE_DOWNLOAD_URL'
            )
        WHERE code='SEOUL_OPEN_DATA_FULL_TIMETABLE';

        UPDATE source_registry
        SET last_inspected_at='2026-08-23',
            metadata=metadata || jsonb_build_object(
                'dataset_pages', jsonb_build_array(
                    'https://www.data.go.kr/data/15051203/fileData.do',
                    'https://www.data.go.kr/data/15051204/fileData.do',
                    'https://www.data.go.kr/data/15051205/fileData.do',
                    'https://www.data.go.kr/data/15051206/fileData.do'
                )
            )
        WHERE code='INCHEON_1_TIMETABLE';

        UPDATE source_registry
        SET last_inspected_at='2026-08-23',
            metadata=metadata || jsonb_build_object(
                'dataset_pages', jsonb_build_array(
                    'https://www.data.go.kr/data/15051210/fileData.do',
                    'https://www.data.go.kr/data/15051208/fileData.do',
                    'https://www.data.go.kr/data/15051209/fileData.do',
                    'https://www.data.go.kr/data/15051207/fileData.do'
                )
            )
        WHERE code='INCHEON_2_TIMETABLE';

        UPDATE source_license
        SET attribution_text='서울교통공사',
            notes='공공데이터포털 원본 파일; 출처 표시 필요',
            checked_at='2026-08-23'
        WHERE source_id=(
            SELECT id FROM source_registry WHERE code='SEOUL_OPEN_DATA_FULL_TIMETABLE'
        );
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        UPDATE source_registry
        SET base_url='https://data.seoul.go.kr/dataList/OA-22522/L/1/datasetView.do',
            metadata=metadata - 'dataset_page' - 'download_url_env'
        WHERE code='SEOUL_OPEN_DATA_FULL_TIMETABLE';

        UPDATE source_registry
        SET metadata=metadata - 'dataset_pages'
        WHERE code IN ('INCHEON_1_TIMETABLE', 'INCHEON_2_TIMETABLE');

        UPDATE source_license
        SET attribution_text='서울 열린데이터광장',
            notes='출처 표시 필요'
        WHERE source_id=(
            SELECT id FROM source_registry WHERE code='SEOUL_OPEN_DATA_FULL_TIMETABLE'
        );
        """
    )
