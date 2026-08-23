from __future__ import annotations

from datetime import date
from typing import Any

from metro_collector.db import DbConnection


class TransitQueryRepository:
    @staticmethod
    async def api_request_usage(
        connection: DbConnection,
        *,
        usage_date: date,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT provider, usage_date, request_count, last_requested_at,
                   blocked_until, last_status
            FROM external_api_request_usage
            WHERE usage_date=%s
            ORDER BY provider
            """,
            (usage_date,),
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def platform_stats(connection: DbConnection) -> dict[str, Any]:
        cursor = await connection.execute(
            """
            SELECT
                (SELECT count(*) FROM subway_line WHERE active) AS line_count,
                (SELECT count(*) FROM station WHERE active) AS station_count,
                (SELECT count(*) FROM source_registry) AS source_count,
                (SELECT count(*) FROM source_registry WHERE access_status='ENABLED')
                    AS enabled_source_count,
                (SELECT count(*) FROM timetable_version WHERE state='ACTIVE')
                    AS active_version_count,
                (SELECT count(*) FROM trip) AS trip_count,
                (SELECT count(*) FROM stop_time) AS stop_time_count,
                (SELECT max(finished_at) FROM sync_job WHERE status='SUCCEEDED') AS last_sync_at
            """
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Platform statistics query returned no row")
        return dict(row)

    @staticmethod
    async def list_operators(connection: DbConnection) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT id::text, code, name_ko, name_en, website_url, active
            FROM transit_operator
            WHERE active
            ORDER BY name_ko
            """
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def list_lines(connection: DbConnection) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT l.id::text, l.code, l.name_ko, l.name_en, l.color, l.transport_mode,
                   COALESCE(
                       jsonb_agg(
                           jsonb_build_object('code', o.code, 'name', o.name_ko, 'role', r.role)
                           ORDER BY o.name_ko
                       ) FILTER (WHERE o.id IS NOT NULL),
                       '[]'::jsonb
                   ) AS operators
            FROM subway_line l
            LEFT JOIN line_operator_role r ON r.line_id = l.id
                AND (r.valid_to IS NULL OR r.valid_to >= CURRENT_DATE)
            LEFT JOIN transit_operator o ON o.id = r.operator_id
            WHERE l.active
            GROUP BY l.id
            ORDER BY l.name_ko
            """
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def list_stations(
        connection: DbConnection,
        *,
        query: str | None,
        line_code: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT s.id::text, s.canonical_code, s.name_ko, s.name_en,
                   s.latitude, s.longitude, s.coordinate_basis_date,
                   coordinate_source.code AS coordinate_source_code,
                   coordinate_source.name AS coordinate_source_name,
                   jsonb_agg(DISTINCT jsonb_build_object(
                       'line_code', l.code,
                       'line_name', l.name_ko,
                       'station_code', ls.station_code,
                       'sequence', ls.sequence
                   )) AS lines
            FROM station s
            JOIN line_station ls ON ls.station_id = s.id AND ls.active
            JOIN subway_line l ON l.id = ls.line_id AND l.active
            LEFT JOIN source_registry coordinate_source
              ON coordinate_source.id=s.coordinate_source_id
            WHERE s.active
              AND (%(query)s::text IS NULL
                   OR regexp_replace(s.name_ko, '역$', '')
                        ILIKE '%%' || %(query)s::text || '%%'
                   OR s.name_en ILIKE '%%' || %(query)s::text || '%%')
              AND (%(line_code)s::text IS NULL OR l.code = %(line_code)s::text)
            GROUP BY s.id, coordinate_source.code, coordinate_source.name
            ORDER BY
                CASE
                    WHEN %(query)s::text IS NULL THEN 0
                    WHEN regexp_replace(s.name_ko, '역$', '')
                         ILIKE %(query)s::text || '%%' THEN 0
                    WHEN s.name_en ILIKE %(query)s::text || '%%' THEN 0
                    ELSE 1
                END,
                s.name_ko,
                s.canonical_code
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"query": query, "line_code": line_code, "limit": limit, "offset": offset},
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def nearby_station_candidates(
        connection: DbConnection,
        *,
        minimum_latitude: float,
        maximum_latitude: float,
        minimum_longitude: float,
        maximum_longitude: float,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT s.id::text, s.canonical_code, s.name_ko, s.name_en,
                   s.latitude, s.longitude, s.coordinate_basis_date,
                   coordinate_source.code AS coordinate_source_code,
                   coordinate_source.name AS coordinate_source_name,
                   jsonb_agg(DISTINCT jsonb_build_object(
                       'line_code', line.code,
                       'line_name', line.name_ko,
                       'station_code', line_station.station_code,
                       'sequence', line_station.sequence
                   )) AS lines
            FROM station s
            JOIN line_station ON line_station.station_id=s.id AND line_station.active
            JOIN subway_line line ON line.id=line_station.line_id AND line.active
            LEFT JOIN source_registry coordinate_source
              ON coordinate_source.id=s.coordinate_source_id
            WHERE s.active
              AND s.latitude BETWEEN %(minimum_latitude)s AND %(maximum_latitude)s
              AND s.longitude BETWEEN %(minimum_longitude)s AND %(maximum_longitude)s
            GROUP BY s.id, coordinate_source.code, coordinate_source.name
            ORDER BY s.name_ko, s.canonical_code
            """,
            {
                "minimum_latitude": minimum_latitude,
                "maximum_latitude": maximum_latitude,
                "minimum_longitude": minimum_longitude,
                "maximum_longitude": maximum_longitude,
            },
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def station_metadata_by_names(
        connection: DbConnection,
        *,
        station_names: list[str],
    ) -> list[dict[str, Any]]:
        if not station_names:
            return []
        cursor = await connection.execute(
            """
            SELECT DISTINCT ON (s.name_ko)
                   s.id::text, s.canonical_code, s.name_ko,
                   s.latitude, s.longitude
            FROM station s
            WHERE s.active
              AND s.name_ko = ANY(%(station_names)s::text[])
            ORDER BY s.name_ko, s.updated_at DESC, s.id
            """,
            {"station_names": station_names},
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def list_travel_time_edges(
        connection: DbConnection,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT
                edge.from_line_station_id::text AS from_stop,
                edge.to_line_station_id::text AS to_stop,
                origin.name_ko AS from_name,
                destination.name_ko AS to_name,
                line.code AS line_code,
                line.name_ko AS line_name,
                edge.travel_seconds,
                edge.sample_count
            FROM travel_time_edge edge
            JOIN timetable_activation active
              ON active.timetable_version_id=edge.timetable_version_id
             AND active.line_id=edge.line_id
            JOIN subway_line line ON line.id=edge.line_id
            JOIN line_station origin_line_station
              ON origin_line_station.id=edge.from_line_station_id
            JOIN station origin ON origin.id=origin_line_station.station_id
            JOIN line_station destination_line_station
              ON destination_line_station.id=edge.to_line_station_id
            JOIN station destination ON destination.id=destination_line_station.station_id
            ORDER BY line.code, origin.name_ko, destination.name_ko
            """
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def list_schedule_connections(
        connection: DbConnection,
        *,
        service_date: date,
        departure_sec: int,
        horizon_seconds: int = 21_600,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            WITH active_trips AS (
                SELECT
                    t.id,
                    t.timetable_version_id,
                    t.trip_code,
                    t.train_number,
                    t.direction,
                    t.destination_line_station_id,
                    l.code AS line_code,
                    l.name_ko AS line_name
                FROM trip t
                JOIN subway_line l ON l.id=t.line_id
                JOIN service_calendar sc ON sc.id=t.service_id
                JOIN timetable_version tv ON tv.id=t.timetable_version_id
                JOIN timetable_activation ta
                  ON ta.timetable_version_id=t.timetable_version_id
                 AND ta.line_id=t.line_id
                WHERE tv.state='ACTIVE'
                  AND tv.effective_from <= %(service_date)s::date
                  AND (tv.effective_to IS NULL OR tv.effective_to >= %(service_date)s::date)
                  AND (
                    EXISTS (
                        SELECT 1 FROM service_exception added
                        WHERE added.service_id=sc.id
                          AND added.service_date=%(service_date)s::date
                          AND added.exception_type='ADDED'
                    )
                    OR (
                        CASE EXTRACT(ISODOW FROM %(service_date)s::date)
                          WHEN 1 THEN sc.monday WHEN 2 THEN sc.tuesday
                          WHEN 3 THEN sc.wednesday WHEN 4 THEN sc.thursday
                          WHEN 5 THEN sc.friday WHEN 6 THEN sc.saturday
                          WHEN 7 THEN sc.sunday
                        END
                        AND NOT EXISTS (
                            SELECT 1 FROM service_exception removed
                            WHERE removed.service_id=sc.id
                              AND removed.service_date=%(service_date)s::date
                              AND removed.exception_type='REMOVED'
                        )
                    )
                  )
            ), ordered AS (
                SELECT
                    trip.*,
                    st.line_station_id AS departure_stop,
                    COALESCE(st.departure_sec, st.arrival_sec) AS departure_sec,
                    lead(st.line_station_id) OVER (
                        PARTITION BY trip.id ORDER BY st.stop_sequence
                    ) AS arrival_stop,
                    lead(COALESCE(st.arrival_sec, st.departure_sec)) OVER (
                        PARTITION BY trip.id ORDER BY st.stop_sequence
                    ) AS arrival_sec
                FROM active_trips trip
                JOIN stop_time st
                  ON st.timetable_version_id=trip.timetable_version_id
                 AND st.trip_id=trip.id
            )
            SELECT
                ordered.departure_stop::text,
                ordered.arrival_stop::text,
                departure_station.name_ko AS departure_station,
                arrival_station.name_ko AS arrival_station,
                ordered.departure_sec,
                ordered.arrival_sec,
                ordered.id::text AS trip_id,
                ordered.trip_code,
                ordered.train_number,
                ordered.line_code,
                ordered.line_name,
                ordered.direction,
                destination_station.name_ko AS destination
            FROM ordered
            JOIN line_station departure_ls ON departure_ls.id=ordered.departure_stop
            JOIN station departure_station ON departure_station.id=departure_ls.station_id
            JOIN line_station arrival_ls ON arrival_ls.id=ordered.arrival_stop
            JOIN station arrival_station ON arrival_station.id=arrival_ls.station_id
            JOIN line_station destination_ls
              ON destination_ls.id=ordered.destination_line_station_id
            JOIN station destination_station ON destination_station.id=destination_ls.station_id
            WHERE ordered.departure_sec >= %(departure_sec)s
              AND ordered.departure_sec <= %(horizon_end_sec)s
              AND ordered.arrival_sec >= ordered.departure_sec
              AND ordered.arrival_stop<>ordered.departure_stop
            ORDER BY ordered.departure_sec, ordered.arrival_sec, ordered.id
            """,
            {
                "service_date": service_date,
                "departure_sec": departure_sec,
                "horizon_end_sec": departure_sec + horizon_seconds,
            },
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def list_transfer_rules(
        connection: DbConnection,
        *,
        service_date: date,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT
                from_line_station_id::text AS from_stop,
                to_line_station_id::text AS to_stop,
                from_direction,
                to_direction,
                minimum_transfer_seconds,
                accessible_transfer_seconds,
                source_type
            FROM transfer_connection
            WHERE (valid_from IS NULL OR valid_from <= %(service_date)s::date)
              AND (valid_to IS NULL OR valid_to >= %(service_date)s::date)
            ORDER BY from_line_station_id, to_line_station_id,
                     from_direction NULLS LAST, to_direction NULLS LAST
            """,
            {"service_date": service_date},
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def station_timetable(
        connection: DbConnection,
        *,
        station_id: str,
        service_date: date,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT l.code AS line_code, l.name_ko AS line_name, t.trip_code, t.train_number,
                   t.direction, t.express_type, st.arrival_sec, st.departure_sec,
                   destination.name_ko AS destination_name,
                   tv.effective_from, tv.effective_to, sr.name AS source_name,
                   tv.checksum AS timetable_checksum
            FROM station s
            JOIN line_station ls ON ls.station_id = s.id
            JOIN stop_time st ON st.line_station_id = ls.id
            JOIN trip t ON t.id = st.trip_id
            JOIN subway_line l ON l.id = t.line_id
            JOIN service_calendar sc ON sc.id = t.service_id
            JOIN timetable_version tv ON tv.id = t.timetable_version_id
            JOIN source_registry sr ON sr.id = tv.source_id
            JOIN timetable_activation ta
              ON ta.timetable_version_id = tv.id AND ta.line_id = l.id
            JOIN line_station destination_ls ON destination_ls.id = t.destination_line_station_id
            JOIN station destination ON destination.id = destination_ls.station_id
            WHERE s.id = %(station_id)s::uuid
              AND tv.effective_from <= %(service_date)s
              AND (tv.effective_to IS NULL OR tv.effective_to >= %(service_date)s)
              AND (
                CASE EXTRACT(ISODOW FROM %(service_date)s::date)
                  WHEN 1 THEN sc.monday WHEN 2 THEN sc.tuesday WHEN 3 THEN sc.wednesday
                  WHEN 4 THEN sc.thursday WHEN 5 THEN sc.friday WHEN 6 THEN sc.saturday
                  WHEN 7 THEN sc.sunday
                END
              )
              AND NOT EXISTS (
                  SELECT 1 FROM service_exception se
                  WHERE se.service_id = sc.id AND se.service_date = %(service_date)s
                    AND se.exception_type = 'REMOVED'
              )
            ORDER BY COALESCE(st.departure_sec, st.arrival_sec), l.code, t.trip_code
            """,
            {"station_id": station_id, "service_date": service_date},
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def source_coverage(connection: DbConnection) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT sr.id::text, sr.code, sr.name, sr.kind, sr.coverage, sr.access_status,
                   sr.base_url, sr.schedule_cron, sr.last_inspected_at,
                   sr.stores_raw_artifact, sr.uses_private_api,
                   sl.license_name, sl.commercial_use_allowed, sl.modification_allowed,
                   sl.redistribution_allowed, sl.raw_storage_allowed, sl.terms_unspecified,
                   sl.checked_at AS license_checked_at
            FROM source_registry sr
            LEFT JOIN LATERAL (
                SELECT * FROM source_license candidate
                WHERE candidate.source_id = sr.id
                ORDER BY checked_at DESC LIMIT 1
            ) sl ON true
            ORDER BY sr.code
            """
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def service_alerts(connection: DbConnection) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT id::text, external_alert_id, alert_type, severity, title, description,
                   starts_at, ends_at, published_at, updated_at
            FROM service_alert
            WHERE active AND starts_at <= now() AND (ends_at IS NULL OR ends_at >= now())
            ORDER BY COALESCE(updated_at, published_at, starts_at) DESC
            """
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def cached_route(
        connection: DbConnection,
        *,
        origin_station_id: str,
        destination_station_id: str,
        service_date: date,
        query_bucket_sec: int,
        arrive_by: bool,
    ) -> dict[str, Any] | None:
        cursor = await connection.execute(
            """
            SELECT rp.id::text, rp.path_data, rp.total_seconds, rp.transfer_count,
                   rp.service_date, rp.query_bucket_sec, rp.arrive_by,
                   tv.effective_from AS timetable_basis_date,
                   sr.name AS source_name, tv.checksum AS timetable_checksum
            FROM route_path rp
            JOIN timetable_version tv ON tv.id = rp.timetable_version_id
            JOIN source_registry sr ON sr.id = tv.source_id
            WHERE rp.origin_station_id = %(origin)s::uuid
              AND rp.destination_station_id = %(destination)s::uuid
              AND rp.service_date = %(service_date)s
              AND rp.query_bucket_sec = %(query_bucket_sec)s
              AND rp.arrive_by = %(arrive_by)s
              AND (rp.expires_at IS NULL OR rp.expires_at > now())
            ORDER BY rp.created_at DESC
            LIMIT 1
            """,
            {
                "origin": origin_station_id,
                "destination": destination_station_id,
                "service_date": service_date,
                "query_bucket_sec": query_bucket_sec,
                "arrive_by": arrive_by,
            },
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
