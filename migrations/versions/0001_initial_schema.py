"""Create the versioned transit data schema.

Revision ID: 0001
Revises: None
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        CREATE TYPE coverage_status AS ENUM (
            'FULL_STATIC', 'ROUTE_QUERY_ONLY', 'REALTIME_ONLY', 'PARTIAL', 'UNAVAILABLE'
        );
        CREATE TYPE source_kind AS ENUM (
            'OPEN_API', 'PUBLIC_DATASET', 'DOWNLOAD_FILE', 'GTFS', 'OFFICIAL_WEB',
            'OPERATOR_REQUEST'
        );
        CREATE TYPE source_access_status AS ENUM (
            'ENABLED', 'DISABLED_ROBOTS', 'DISABLED_TERMS', 'DISABLED_TECHNICAL',
            'PENDING_KEY', 'PENDING_REVIEW'
        );
        CREATE TYPE operator_role AS ENUM (
            'OWNER', 'AUTHORITY', 'CONCESSIONAIRE', 'CARRIER', 'OPERATOR', 'MAINTAINER'
        );
        CREATE TYPE timetable_state AS ENUM (
            'STAGED', 'VALIDATED', 'ACTIVE', 'RETIRED', 'FAILED'
        );
        CREATE TYPE sync_job_status AS ENUM (
            'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED_UNCHANGED', 'CANCELLED'
        );
        CREATE TYPE quality_severity AS ENUM ('INFO', 'WARNING', 'ERROR', 'FATAL');
        CREATE TYPE service_exception_type AS ENUM ('ADDED', 'REMOVED');
        CREATE TYPE identifier_entity_type AS ENUM ('OPERATOR', 'LINE', 'STATION', 'LINE_STATION');

        CREATE TABLE transit_operator (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(64) NOT NULL UNIQUE,
            name_ko varchar(200) NOT NULL,
            name_en varchar(200),
            website_url text,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE subway_line (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(64) NOT NULL UNIQUE,
            name_ko varchar(200) NOT NULL,
            name_en varchar(200),
            color varchar(7),
            transport_mode varchar(32) NOT NULL DEFAULT 'METRO',
            active boolean NOT NULL DEFAULT true,
            opened_on date,
            closed_on date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$')
        );

        CREATE TABLE line_operator_role (
            line_id uuid NOT NULL REFERENCES subway_line(id),
            operator_id uuid NOT NULL REFERENCES transit_operator(id),
            role operator_role NOT NULL,
            valid_from date,
            valid_to date,
            notes text,
            PRIMARY KEY (line_id, operator_id, role, valid_from)
        );

        CREATE TABLE station (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            canonical_code varchar(64) NOT NULL UNIQUE,
            name_ko varchar(200) NOT NULL,
            name_en varchar(200),
            latitude numeric(9,6),
            longitude numeric(9,6),
            active boolean NOT NULL DEFAULT true,
            opened_on date,
            closed_on date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
            CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180)
        );

        CREATE TABLE station_alias (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            station_id uuid NOT NULL REFERENCES station(id) ON DELETE CASCADE,
            alias varchar(200) NOT NULL,
            language varchar(16) NOT NULL DEFAULT 'ko',
            normalized_alias varchar(200) NOT NULL,
            UNIQUE (station_id, alias, language)
        );

        CREATE TABLE line_station (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            line_id uuid NOT NULL REFERENCES subway_line(id),
            station_id uuid NOT NULL REFERENCES station(id),
            station_code varchar(64) NOT NULL,
            sequence numeric(8,3) NOT NULL,
            distance_from_start_m integer,
            platform_code varchar(64),
            active boolean NOT NULL DEFAULT true,
            valid_from date,
            valid_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (line_id, station_code),
            CHECK (distance_from_start_m IS NULL OR distance_from_start_m >= 0)
        );

        CREATE TABLE transfer_connection (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            from_line_station_id uuid NOT NULL REFERENCES line_station(id),
            to_line_station_id uuid NOT NULL REFERENCES line_station(id),
            minimum_transfer_seconds integer NOT NULL,
            distance_m integer,
            bidirectional boolean NOT NULL DEFAULT false,
            accessibility_notes text,
            valid_from date,
            valid_to date,
            source_url text,
            UNIQUE (from_line_station_id, to_line_station_id, valid_from),
            CHECK (from_line_station_id <> to_line_station_id),
            CHECK (minimum_transfer_seconds > 0),
            CHECK (distance_m IS NULL OR distance_m >= 0)
        );

        CREATE TABLE source_registry (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code varchar(100) NOT NULL UNIQUE,
            name varchar(200) NOT NULL,
            operator_id uuid REFERENCES transit_operator(id),
            kind source_kind NOT NULL,
            coverage coverage_status NOT NULL,
            access_status source_access_status NOT NULL DEFAULT 'ENABLED',
            base_url text NOT NULL,
            schedule_cron varchar(100),
            expected_update_interval interval,
            stores_raw_artifact boolean NOT NULL DEFAULT true,
            uses_private_api boolean NOT NULL DEFAULT false,
            robots_checked_at timestamptz,
            terms_checked_at timestamptz,
            last_inspected_at timestamptz,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE source_license (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
            license_name varchar(200),
            license_url text,
            attribution_text text,
            commercial_use_allowed boolean,
            modification_allowed boolean,
            redistribution_allowed boolean,
            raw_storage_allowed boolean,
            terms_unspecified boolean NOT NULL DEFAULT false,
            effective_from date,
            effective_to date,
            checked_at timestamptz NOT NULL,
            evidence_hash char(64),
            notes text
        );

        CREATE TABLE source_identifier (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_id uuid NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
            entity_type identifier_entity_type NOT NULL,
            entity_id uuid NOT NULL,
            external_code varchar(200) NOT NULL,
            external_name varchar(300),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (source_id, entity_type, external_code)
        );

        CREATE TABLE service_calendar (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            service_code varchar(100) NOT NULL UNIQUE,
            description varchar(300),
            monday boolean NOT NULL,
            tuesday boolean NOT NULL,
            wednesday boolean NOT NULL,
            thursday boolean NOT NULL,
            friday boolean NOT NULL,
            saturday boolean NOT NULL,
            sunday boolean NOT NULL,
            start_date date NOT NULL,
            end_date date NOT NULL,
            CHECK (start_date <= end_date)
        );

        CREATE TABLE service_exception (
            service_id uuid NOT NULL REFERENCES service_calendar(id) ON DELETE CASCADE,
            service_date date NOT NULL,
            exception_type service_exception_type NOT NULL,
            source_id uuid REFERENCES source_registry(id),
            notes text,
            PRIMARY KEY (service_id, service_date)
        );

        CREATE TABLE timetable_version (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid NOT NULL REFERENCES source_registry(id),
            version_code varchar(200) NOT NULL,
            state timetable_state NOT NULL DEFAULT 'STAGED',
            effective_from date NOT NULL,
            effective_to date,
            collected_at timestamptz NOT NULL,
            source_updated_at timestamptz,
            checksum char(64) NOT NULL,
            row_count bigint NOT NULL DEFAULT 0,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_id, version_code),
            UNIQUE (source_id, checksum),
            CHECK (effective_to IS NULL OR effective_from <= effective_to),
            CHECK (row_count >= 0)
        );

        CREATE TABLE trip (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            timetable_version_id uuid NOT NULL REFERENCES timetable_version(id) ON DELETE CASCADE,
            line_id uuid NOT NULL REFERENCES subway_line(id),
            service_id uuid NOT NULL REFERENCES service_calendar(id),
            trip_code varchar(200) NOT NULL,
            train_number varchar(100),
            direction varchar(32) NOT NULL,
            origin_line_station_id uuid NOT NULL REFERENCES line_station(id),
            destination_line_station_id uuid NOT NULL REFERENCES line_station(id),
            express_type varchar(64) NOT NULL DEFAULT 'LOCAL',
            block_code varchar(100),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (timetable_version_id, trip_code)
        );

        CREATE TABLE stop_time (
            timetable_version_id uuid NOT NULL REFERENCES timetable_version(id) ON DELETE CASCADE,
            trip_id uuid NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
            line_station_id uuid NOT NULL REFERENCES line_station(id),
            stop_sequence smallint NOT NULL,
            arrival_sec integer,
            departure_sec integer,
            pickup_allowed boolean NOT NULL DEFAULT true,
            dropoff_allowed boolean NOT NULL DEFAULT true,
            pass_through boolean NOT NULL DEFAULT false,
            source_row_number integer,
            PRIMARY KEY (timetable_version_id, trip_id, stop_sequence),
            CHECK (stop_sequence > 0),
            CHECK (arrival_sec IS NULL OR arrival_sec >= 0),
            CHECK (departure_sec IS NULL OR departure_sec >= 0),
            CHECK (arrival_sec IS NULL OR departure_sec IS NULL OR arrival_sec <= departure_sec)
        ) PARTITION BY HASH (timetable_version_id);

        CREATE TABLE stop_time_p0 PARTITION OF stop_time FOR VALUES WITH (MODULUS 8, REMAINDER 0);
        CREATE TABLE stop_time_p1 PARTITION OF stop_time FOR VALUES WITH (MODULUS 8, REMAINDER 1);
        CREATE TABLE stop_time_p2 PARTITION OF stop_time FOR VALUES WITH (MODULUS 8, REMAINDER 2);
        CREATE TABLE stop_time_p3 PARTITION OF stop_time FOR VALUES WITH (MODULUS 8, REMAINDER 3);
        CREATE TABLE stop_time_p4 PARTITION OF stop_time FOR VALUES WITH (MODULUS 8, REMAINDER 4);
        CREATE TABLE stop_time_p5 PARTITION OF stop_time FOR VALUES WITH (MODULUS 8, REMAINDER 5);
        CREATE TABLE stop_time_p6 PARTITION OF stop_time FOR VALUES WITH (MODULUS 8, REMAINDER 6);
        CREATE TABLE stop_time_p7 PARTITION OF stop_time FOR VALUES WITH (MODULUS 8, REMAINDER 7);

        CREATE TABLE timetable_activation (
            source_id uuid NOT NULL REFERENCES source_registry(id),
            line_id uuid NOT NULL REFERENCES subway_line(id),
            timetable_version_id uuid NOT NULL REFERENCES timetable_version(id),
            activated_at timestamptz NOT NULL DEFAULT now(),
            activated_by varchar(100) NOT NULL,
            PRIMARY KEY (source_id, line_id)
        );

        CREATE TABLE route_path (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            timetable_version_id uuid NOT NULL REFERENCES timetable_version(id) ON DELETE CASCADE,
            origin_station_id uuid NOT NULL REFERENCES station(id),
            destination_station_id uuid NOT NULL REFERENCES station(id),
            service_date date NOT NULL,
            query_bucket_sec integer NOT NULL,
            arrive_by boolean NOT NULL DEFAULT false,
            path_data jsonb NOT NULL,
            total_seconds integer NOT NULL,
            transfer_count smallint NOT NULL,
            expires_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (
                timetable_version_id, origin_station_id, destination_station_id,
                service_date, query_bucket_sec, arrive_by
            ),
            CHECK (query_bucket_sec >= 0),
            CHECK (total_seconds >= 0),
            CHECK (transfer_count >= 0)
        );

        CREATE TABLE realtime_train_position (
            id bigint GENERATED ALWAYS AS IDENTITY,
            source_id uuid NOT NULL REFERENCES source_registry(id),
            line_id uuid NOT NULL REFERENCES subway_line(id),
            external_train_id varchar(200) NOT NULL,
            observed_at timestamptz NOT NULL,
            line_station_id uuid REFERENCES line_station(id),
            next_line_station_id uuid REFERENCES line_station(id),
            direction varchar(32),
            status varchar(64),
            raw_payload jsonb,
            PRIMARY KEY (id, observed_at)
        ) PARTITION BY RANGE (observed_at);

        CREATE TABLE realtime_train_position_default
            PARTITION OF realtime_train_position DEFAULT;

        CREATE TABLE service_alert (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid NOT NULL REFERENCES source_registry(id),
            external_alert_id varchar(200) NOT NULL,
            alert_type varchar(100) NOT NULL,
            severity varchar(32),
            title text NOT NULL,
            description text,
            starts_at timestamptz NOT NULL,
            ends_at timestamptz,
            published_at timestamptz,
            updated_at timestamptz,
            active boolean NOT NULL DEFAULT true,
            raw_payload jsonb,
            UNIQUE (source_id, external_alert_id),
            CHECK (ends_at IS NULL OR starts_at <= ends_at)
        );

        CREATE TABLE service_alert_target (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            alert_id uuid NOT NULL REFERENCES service_alert(id) ON DELETE CASCADE,
            line_id uuid REFERENCES subway_line(id),
            station_id uuid REFERENCES station(id),
            trip_id uuid REFERENCES trip(id),
            UNIQUE NULLS NOT DISTINCT (alert_id, line_id, station_id, trip_id),
            CHECK (num_nonnulls(line_id, station_id, trip_id) >= 1)
        );

        CREATE TABLE source_artifact (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid NOT NULL REFERENCES source_registry(id),
            timetable_version_id uuid REFERENCES timetable_version(id),
            source_url text NOT NULL,
            retrieved_at timestamptz NOT NULL,
            http_status smallint,
            etag text,
            last_modified text,
            content_type varchar(200),
            content_length bigint,
            checksum char(64) NOT NULL,
            storage_path text,
            response_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (source_id, checksum),
            CHECK (content_length IS NULL OR content_length >= 0)
        );

        CREATE TABLE ingest_batch (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid NOT NULL REFERENCES source_registry(id),
            timetable_version_id uuid REFERENCES timetable_version(id),
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            parsed_rows bigint NOT NULL DEFAULT 0,
            accepted_rows bigint NOT NULL DEFAULT 0,
            rejected_rows bigint NOT NULL DEFAULT 0,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CHECK (parsed_rows >= 0 AND accepted_rows >= 0 AND rejected_rows >= 0)
        );

        CREATE TABLE sync_job (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id uuid NOT NULL REFERENCES source_registry(id),
            status sync_job_status NOT NULL DEFAULT 'PENDING',
            trigger_type varchar(32) NOT NULL,
            requested_by varchar(200),
            idempotency_key varchar(300) NOT NULL UNIQUE,
            started_at timestamptz,
            finished_at timestamptz,
            collected_count bigint NOT NULL DEFAULT 0,
            inserted_count bigint NOT NULL DEFAULT 0,
            error_count integer NOT NULL DEFAULT 0,
            artifact_checksum char(64),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (collected_count >= 0 AND inserted_count >= 0 AND error_count >= 0)
        );

        CREATE TABLE sync_job_error (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            sync_job_id uuid NOT NULL REFERENCES sync_job(id) ON DELETE CASCADE,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            stage varchar(64) NOT NULL,
            error_code varchar(100),
            message text NOT NULL,
            retryable boolean NOT NULL DEFAULT false,
            context jsonb NOT NULL DEFAULT '{}'::jsonb
        );

        CREATE TABLE data_quality_result (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            timetable_version_id uuid NOT NULL REFERENCES timetable_version(id) ON DELETE CASCADE,
            rule_code varchar(100) NOT NULL,
            severity quality_severity NOT NULL,
            passed boolean NOT NULL,
            affected_count bigint NOT NULL DEFAULT 0,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            checked_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (timetable_version_id, rule_code),
            CHECK (affected_count >= 0)
        );

        CREATE INDEX idx_station_name_ko ON station (name_ko);
        CREATE INDEX idx_station_alias_normalized ON station_alias (normalized_alias);
        CREATE INDEX idx_line_station_station ON line_station (station_id);
        CREATE INDEX idx_line_station_order ON line_station (line_id, sequence);
        CREATE INDEX idx_transfer_from ON transfer_connection (from_line_station_id);
        CREATE INDEX idx_transfer_to ON transfer_connection (to_line_station_id);
        CREATE INDEX idx_trip_version_line_service
            ON trip (timetable_version_id, line_id, service_id);
        CREATE INDEX idx_stop_time_station_departure
            ON stop_time (line_station_id, departure_sec);
        CREATE INDEX idx_stop_time_version_trip
            ON stop_time (timetable_version_id, trip_id, stop_sequence);
        CREATE INDEX idx_realtime_current
            ON realtime_train_position (line_id, external_train_id, observed_at DESC);
        CREATE INDEX idx_service_alert_active_period
            ON service_alert (active, starts_at, ends_at);
        CREATE INDEX idx_sync_job_source_created ON sync_job (source_id, created_at DESC);
        CREATE INDEX idx_quality_version_passed ON data_quality_result (timetable_version_id, passed);

        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_transit_operator_updated_at
            BEFORE UPDATE ON transit_operator FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_subway_line_updated_at
            BEFORE UPDATE ON subway_line FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_station_updated_at
            BEFORE UPDATE ON station FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_line_station_updated_at
            BEFORE UPDATE ON line_station FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        CREATE TRIGGER trg_source_registry_updated_at
            BEFORE UPDATE ON source_registry FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP FUNCTION IF EXISTS set_updated_at() CASCADE;
        DROP TABLE IF EXISTS data_quality_result CASCADE;
        DROP TABLE IF EXISTS sync_job_error CASCADE;
        DROP TABLE IF EXISTS sync_job CASCADE;
        DROP TABLE IF EXISTS ingest_batch CASCADE;
        DROP TABLE IF EXISTS source_artifact CASCADE;
        DROP TABLE IF EXISTS service_alert_target CASCADE;
        DROP TABLE IF EXISTS service_alert CASCADE;
        DROP TABLE IF EXISTS realtime_train_position CASCADE;
        DROP TABLE IF EXISTS route_path CASCADE;
        DROP TABLE IF EXISTS timetable_activation CASCADE;
        DROP TABLE IF EXISTS stop_time CASCADE;
        DROP TABLE IF EXISTS trip CASCADE;
        DROP TABLE IF EXISTS timetable_version CASCADE;
        DROP TABLE IF EXISTS service_exception CASCADE;
        DROP TABLE IF EXISTS service_calendar CASCADE;
        DROP TABLE IF EXISTS source_identifier CASCADE;
        DROP TABLE IF EXISTS source_license CASCADE;
        DROP TABLE IF EXISTS source_registry CASCADE;
        DROP TABLE IF EXISTS transfer_connection CASCADE;
        DROP TABLE IF EXISTS line_station CASCADE;
        DROP TABLE IF EXISTS station_alias CASCADE;
        DROP TABLE IF EXISTS station CASCADE;
        DROP TABLE IF EXISTS line_operator_role CASCADE;
        DROP TABLE IF EXISTS subway_line CASCADE;
        DROP TABLE IF EXISTS transit_operator CASCADE;
        DROP TYPE IF EXISTS identifier_entity_type;
        DROP TYPE IF EXISTS service_exception_type;
        DROP TYPE IF EXISTS quality_severity;
        DROP TYPE IF EXISTS sync_job_status;
        DROP TYPE IF EXISTS timetable_state;
        DROP TYPE IF EXISTS operator_role;
        DROP TYPE IF EXISTS source_access_status;
        DROP TYPE IF EXISTS source_kind;
        DROP TYPE IF EXISTS coverage_status;
        """
    )
