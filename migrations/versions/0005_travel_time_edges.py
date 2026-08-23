"""Add precomputed representative travel-time edges.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        CREATE TABLE travel_time_edge (
            timetable_version_id uuid NOT NULL
                REFERENCES timetable_version(id) ON DELETE CASCADE,
            line_id uuid NOT NULL REFERENCES subway_line(id),
            from_line_station_id uuid NOT NULL REFERENCES line_station(id),
            to_line_station_id uuid NOT NULL REFERENCES line_station(id),
            travel_seconds integer NOT NULL,
            sample_count integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (
                timetable_version_id, line_id,
                from_line_station_id, to_line_station_id
            ),
            CHECK (from_line_station_id <> to_line_station_id),
            CHECK (travel_seconds > 0),
            CHECK (sample_count > 0)
        );

        CREATE INDEX idx_travel_time_edge_active_lookup
            ON travel_time_edge (timetable_version_id, line_id);

        WITH ordered AS (
            SELECT
                t.timetable_version_id,
                t.line_id,
                st.line_station_id AS from_line_station_id,
                COALESCE(st.departure_sec, st.arrival_sec) AS departure_sec,
                lead(st.line_station_id) OVER (
                    PARTITION BY t.id ORDER BY st.stop_sequence
                ) AS to_line_station_id,
                lead(COALESCE(st.arrival_sec, st.departure_sec)) OVER (
                    PARTITION BY t.id ORDER BY st.stop_sequence
                ) AS next_arrival_sec
            FROM trip t
            JOIN timetable_version version ON version.id=t.timetable_version_id
            JOIN stop_time st
              ON st.timetable_version_id=t.timetable_version_id AND st.trip_id=t.id
            WHERE version.state='ACTIVE'
        ), valid_edges AS (
            SELECT *, next_arrival_sec - departure_sec AS travel_seconds
            FROM ordered
            WHERE to_line_station_id IS NOT NULL
              AND to_line_station_id <> from_line_station_id
              AND departure_sec IS NOT NULL
              AND next_arrival_sec > departure_sec
              AND next_arrival_sec - departure_sec BETWEEN 30 AND 7200
        )
        INSERT INTO travel_time_edge (
            timetable_version_id, line_id, from_line_station_id,
            to_line_station_id, travel_seconds, sample_count
        )
        SELECT
            timetable_version_id,
            line_id,
            from_line_station_id,
            to_line_station_id,
            percentile_disc(0.5) WITHIN GROUP (ORDER BY travel_seconds)::integer,
            count(*)::integer
        FROM valid_edges
        GROUP BY timetable_version_id, line_id, from_line_station_id, to_line_station_id;
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS travel_time_edge")
