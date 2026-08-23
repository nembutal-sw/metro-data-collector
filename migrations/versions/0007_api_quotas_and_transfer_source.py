"""Add persistent API budgets and Seoul transfer-distance source.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        CREATE TABLE external_api_request_usage (
            provider varchar(100) NOT NULL,
            usage_date date NOT NULL,
            request_count integer NOT NULL DEFAULT 0,
            last_requested_at timestamptz,
            blocked_until timestamptz,
            last_status smallint,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (provider, usage_date),
            CHECK (request_count >= 0)
        );

        CREATE INDEX idx_external_api_usage_recent
            ON external_api_request_usage (usage_date DESC, provider);

        INSERT INTO source_registry (
            code, name, operator_id, kind, coverage, access_status, base_url,
            schedule_cron, expected_update_interval, stores_raw_artifact,
            uses_private_api, terms_checked_at, last_inspected_at, metadata
        ) VALUES (
            'SEOUL_TRANSFER_DISTANCE',
            '서울교통공사 환승역 거리·소요시간',
            (SELECT id FROM transit_operator WHERE code='SEOUL_METRO'),
            'DOWNLOAD_FILE', 'PARTIAL', 'ENABLED',
            'https://www.data.go.kr/data/15044419/fileData.do',
            '20 3 * * *', interval '1 day', true, false,
            '2026-08-23', '2026-08-23',
            jsonb_build_object(
                'download_url_env', 'SEOUL_TRANSFER_DISTANCE_DOWNLOAD_URL',
                'row_count', 145,
                'walking_speed_mps', 1.2,
                'dataset_as_of', '2025-12-31'
            )
        ) ON CONFLICT (code) DO UPDATE SET
            access_status='ENABLED',
            base_url=EXCLUDED.base_url,
            metadata=source_registry.metadata || EXCLUDED.metadata;

        INSERT INTO source_license (
            source_id, license_name, attribution_text,
            commercial_use_allowed, modification_allowed,
            redistribution_allowed, raw_storage_allowed,
            terms_unspecified, checked_at, notes
        )
        SELECT id, '이용허락범위 제한 없음', '서울교통공사',
               true, true, true, true, false, '2026-08-23',
               '공공데이터포털 원본 CSV; 1.2m/s 보행속도 기준'
        FROM source_registry WHERE code='SEOUL_TRANSFER_DISTANCE';
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DELETE FROM source_license WHERE source_id=(
            SELECT id FROM source_registry WHERE code='SEOUL_TRANSFER_DISTANCE'
        );
        DELETE FROM source_artifact WHERE source_id=(
            SELECT id FROM source_registry WHERE code='SEOUL_TRANSFER_DISTANCE'
        );
        DELETE FROM source_registry WHERE code='SEOUL_TRANSFER_DISTANCE';
        DROP INDEX IF EXISTS idx_external_api_usage_recent;
        DROP TABLE IF EXISTS external_api_request_usage;
        """
    )
