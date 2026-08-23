"""Add versioned station coordinates and their official source.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE station
            ADD COLUMN coordinate_source_id uuid REFERENCES source_registry(id),
            ADD COLUMN coordinate_basis_date date,
            ADD COLUMN coordinate_updated_at timestamptz;

        CREATE INDEX idx_station_coordinates
            ON station (latitude, longitude)
            WHERE active AND latitude IS NOT NULL AND longitude IS NOT NULL;

        CREATE TABLE station_coordinate_observation (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_id uuid NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
            station_id uuid REFERENCES station(id) ON DELETE CASCADE,
            artifact_checksum char(64) NOT NULL,
            line_code varchar(64) NOT NULL,
            source_station_code varchar(100) NOT NULL,
            source_station_name varchar(200) NOT NULL,
            source_line_name varchar(200) NOT NULL,
            latitude numeric(10,7) NOT NULL,
            longitude numeric(10,7) NOT NULL,
            data_basis_date date,
            source_row_number integer,
            match_method varchar(40),
            accepted boolean NOT NULL DEFAULT false,
            rejection_reason text,
            observed_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE NULLS NOT DISTINCT (
                source_id, artifact_checksum, line_code,
                source_station_code, station_id
            ),
            CHECK (latitude BETWEEN -90 AND 90),
            CHECK (longitude BETWEEN -180 AND 180),
            CHECK (accepted OR rejection_reason IS NOT NULL)
        );

        CREATE INDEX idx_station_coordinate_observation_station
            ON station_coordinate_observation (station_id, observed_at DESC);
        CREATE INDEX idx_station_coordinate_observation_artifact
            ON station_coordinate_observation (source_id, artifact_checksum);

        INSERT INTO source_registry (
            code, name, kind, coverage, access_status, base_url,
            schedule_cron, expected_update_interval, stores_raw_artifact,
            uses_private_api, terms_checked_at, last_inspected_at, metadata
        ) VALUES (
            'KRIC_STATION_COORDINATES',
            '국가철도공단 도시·광역철도 역사 위치',
            'DOWNLOAD_FILE', 'PARTIAL', 'ENABLED',
            'https://data.kric.go.kr/rips/M_01_01/detail.do?id=32',
            '40 3 * * *', interval '1 day', true, false,
            '2026-08-23', '2026-08-23',
            jsonb_build_object(
                'provider', '국가철도공단 철도산업정보센터',
                'dataset_id', 32,
                'download_url_env', 'KRIC_STATION_COORDINATES_DOWNLOAD_URL',
                'collection_mode', 'official_public_xlsx',
                'api_key_required', false,
                'expected_minimum_records', 650,
                'minimum_match_ratio', 0.90,
                'license', '이용허락범위 제한 없음'
            )
        ) ON CONFLICT (code) DO UPDATE SET
            name=EXCLUDED.name,
            kind=EXCLUDED.kind,
            coverage=EXCLUDED.coverage,
            access_status='ENABLED',
            base_url=EXCLUDED.base_url,
            schedule_cron=EXCLUDED.schedule_cron,
            expected_update_interval=EXCLUDED.expected_update_interval,
            stores_raw_artifact=true,
            uses_private_api=false,
            metadata=source_registry.metadata || EXCLUDED.metadata;

        INSERT INTO source_license (
            source_id, license_name, attribution_text, commercial_use_allowed,
            modification_allowed, redistribution_allowed, raw_storage_allowed,
            terms_unspecified, checked_at, notes
        )
        SELECT id, '이용허락범위 제한 없음', '국가철도공단',
               true, true, true, true, false, '2026-08-23',
               '철도산업정보센터 공개 XLSX dataset id=32; API 키 불필요'
        FROM source_registry
        WHERE code='KRIC_STATION_COORDINATES'
          AND NOT EXISTS (
              SELECT 1 FROM source_license license
              WHERE license.source_id=source_registry.id
                AND license.license_name='이용허락범위 제한 없음'
          );
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DELETE FROM source_license WHERE source_id=(
            SELECT id FROM source_registry WHERE code='KRIC_STATION_COORDINATES'
        );
        DELETE FROM source_artifact WHERE source_id=(
            SELECT id FROM source_registry WHERE code='KRIC_STATION_COORDINATES'
        );
        DROP TABLE IF EXISTS station_coordinate_observation;
        DROP INDEX IF EXISTS idx_station_coordinates;
        ALTER TABLE station
            DROP COLUMN IF EXISTS coordinate_updated_at,
            DROP COLUMN IF EXISTS coordinate_basis_date,
            DROP COLUMN IF EXISTS coordinate_source_id;
        DELETE FROM source_registry WHERE code='KRIC_STATION_COORDINATES';
        """
    )
