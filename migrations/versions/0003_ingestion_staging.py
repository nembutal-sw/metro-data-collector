"""Add the unlogged streaming-ingestion staging table.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        CREATE UNLOGGED TABLE ingest_stop_time_stage (
            batch_id uuid NOT NULL REFERENCES ingest_batch(id) ON DELETE CASCADE,
            line_code varchar(64) NOT NULL,
            station_code varchar(64) NOT NULL,
            station_name varchar(200) NOT NULL,
            service_code varchar(100) NOT NULL,
            direction varchar(32) NOT NULL,
            trip_code varchar(200) NOT NULL,
            train_number varchar(100),
            stop_sequence smallint NOT NULL,
            arrival_sec integer,
            departure_sec integer,
            origin_name varchar(200),
            destination_name varchar(200),
            express_type varchar(64) NOT NULL,
            source_row_number integer
        );

        CREATE INDEX idx_ingest_stop_time_stage_batch_trip
            ON ingest_stop_time_stage (batch_id, trip_code, stop_sequence);
        CREATE INDEX idx_ingest_stop_time_stage_batch_station
            ON ingest_stop_time_stage (batch_id, line_code, station_code);
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS ingest_stop_time_stage")
