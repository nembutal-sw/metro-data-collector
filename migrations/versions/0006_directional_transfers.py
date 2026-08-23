"""Add directional and accessibility-aware transfer metadata.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        ALTER TABLE transfer_connection
            ADD COLUMN from_direction varchar(32),
            ADD COLUMN to_direction varchar(32),
            ADD COLUMN accessible_transfer_seconds integer,
            ADD COLUMN source_type varchar(32) NOT NULL DEFAULT 'DEFAULT_ESTIMATE',
            ADD COLUMN verified_at timestamptz,
            ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

        ALTER TABLE transfer_connection
            DROP CONSTRAINT transfer_connection_from_line_station_id_to_line_station_id_key;

        ALTER TABLE transfer_connection
            ADD CONSTRAINT transfer_connection_accessible_seconds_check
                CHECK (
                    accessible_transfer_seconds IS NULL
                    OR accessible_transfer_seconds > 0
                ),
            ADD CONSTRAINT transfer_connection_source_type_check
                CHECK (
                    source_type IN ('DEFAULT_ESTIMATE', 'OFFICIAL', 'MEASURED', 'MANUAL')
                );

        CREATE UNIQUE INDEX uq_transfer_connection_directional
            ON transfer_connection (
                from_line_station_id,
                to_line_station_id,
                COALESCE(from_direction, '*'),
                COALESCE(to_direction, '*'),
                COALESCE(valid_from, '-infinity'::date)
            );

        CREATE INDEX idx_transfer_station_directions
            ON transfer_connection (
                from_line_station_id, from_direction,
                to_line_station_id, to_direction
            );

        WITH station_lines AS (
            SELECT
                ls.id AS line_station_id,
                ls.line_id,
                regexp_replace(s.name_ko, '역$', '') AS station_name
            FROM line_station ls
            JOIN station s ON s.id=ls.station_id
            WHERE ls.active AND s.active
        )
        INSERT INTO transfer_connection (
            from_line_station_id,
            to_line_station_id,
            minimum_transfer_seconds,
            bidirectional,
            source_type,
            metadata
        )
        SELECT
            origin.line_station_id,
            destination.line_station_id,
            300,
            false,
            'DEFAULT_ESTIMATE',
            jsonb_build_object(
                'reason', 'same normalized station name on different active lines',
                'station_name', origin.station_name
            )
        FROM station_lines origin
        JOIN station_lines destination
          ON destination.station_name=origin.station_name
         AND destination.line_id<>origin.line_id
         AND destination.line_station_id<>origin.line_station_id
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP INDEX IF EXISTS idx_transfer_station_directions;
        DROP INDEX IF EXISTS uq_transfer_connection_directional;

        ALTER TABLE transfer_connection
            DROP CONSTRAINT IF EXISTS transfer_connection_source_type_check,
            DROP CONSTRAINT IF EXISTS transfer_connection_accessible_seconds_check,
            DROP COLUMN IF EXISTS metadata,
            DROP COLUMN IF EXISTS verified_at,
            DROP COLUMN IF EXISTS source_type,
            DROP COLUMN IF EXISTS accessible_transfer_seconds,
            DROP COLUMN IF EXISTS to_direction,
            DROP COLUMN IF EXISTS from_direction;

        ALTER TABLE transfer_connection
            ADD CONSTRAINT transfer_connection_from_line_station_id_to_line_station_id_key
            UNIQUE (from_line_station_id, to_line_station_id, valid_from);
        """
    )
