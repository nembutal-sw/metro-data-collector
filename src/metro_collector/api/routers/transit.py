from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from math import ceil, cos, radians
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from metro_collector.api.dependencies import get_database, require_public_api_key
from metro_collector.api.odsay_compat import (
    build_odsay_path_response,
    build_odsay_point_response,
    coordinate_distance_m,
    station_metadata_by_name,
)
from metro_collector.config import get_settings
from metro_collector.db import Database
from metro_collector.repositories.query import TransitQueryRepository
from metro_collector.routing.schedule_route import (
    ForwardScheduleRouter,
    ScheduleConnection,
    ScheduleJourney,
    TransferRule,
)
from metro_collector.routing.service_time import to_datetime
from metro_collector.routing.travel_time import (
    normalize_station_name,
)

router = APIRouter(prefix="/api/v1", tags=["transit"])
odsay_router = APIRouter(prefix="/odsay/v1/api", tags=["transit"])

type WalkingMode = Literal["standard", "slow", "accessible"]


@dataclass(frozen=True, slots=True)
class _TravelTimeCalculation:
    journey: ScheduleJourney
    service_date: date
    local_departure: datetime


@router.get("/stats")
async def stats(database: Database = Depends(get_database)) -> dict[str, Any]:
    async with database.connection() as connection:
        return await TransitQueryRepository.platform_stats(connection)


@router.get("/api-usage")
async def api_usage(database: Database = Depends(get_database)) -> list[dict[str, Any]]:
    settings = get_settings()
    today = datetime.now(tz=settings.timezone).date()
    budgets = {
        "DATA_GO_KR": settings.data_go_kr_daily_request_budget,
        "KRIC": settings.kric_daily_request_budget,
        "SEOUL_OPEN_DATA": settings.seoul_open_data_daily_request_budget,
    }
    async with database.connection() as connection:
        rows = await TransitQueryRepository.api_request_usage(connection, usage_date=today)
    by_provider = {str(row["provider"]): row for row in rows}
    result: list[dict[str, Any]] = []
    for provider, budget in budgets.items():
        row = by_provider.get(provider, {})
        used = int(row.get("request_count", 0))
        result.append(
            {
                "provider": provider,
                "usage_date": today,
                "request_count": used,
                "daily_budget": budget,
                "remaining_count": max(0, budget - used),
                "last_requested_at": row.get("last_requested_at"),
                "blocked_until": row.get("blocked_until"),
                "last_status": row.get("last_status"),
            }
        )
    return result


@router.get("/operators")
async def operators(database: Database = Depends(get_database)) -> list[dict[str, Any]]:
    async with database.connection() as connection:
        return await TransitQueryRepository.list_operators(connection)


@router.get("/lines")
async def lines(database: Database = Depends(get_database)) -> list[dict[str, Any]]:
    async with database.connection() as connection:
        return await TransitQueryRepository.list_lines(connection)


@router.get("/stations")
async def stations(
    q: str | None = None,
    line_code: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    database: Database = Depends(get_database),
) -> list[dict[str, Any]]:
    normalized_query = normalize_station_name(q) if q else None
    async with database.connection() as connection:
        return await TransitQueryRepository.list_stations(
            connection,
            query=normalized_query,
            line_code=line_code,
            limit=limit,
            offset=offset,
        )


async def _nearby_station_rows(
    *,
    latitude: float,
    longitude: float,
    radius_m: int,
    database: Database,
) -> list[dict[str, Any]]:
    latitude_delta = radius_m / 111_320
    longitude_delta = radius_m / (111_320 * max(0.01, abs(cos(radians(latitude)))))
    async with database.connection() as connection:
        candidates = await TransitQueryRepository.nearby_station_candidates(
            connection,
            minimum_latitude=latitude - latitude_delta,
            maximum_latitude=latitude + latitude_delta,
            minimum_longitude=longitude - longitude_delta,
            maximum_longitude=longitude + longitude_delta,
        )
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        station_latitude = float(candidate["latitude"])
        station_longitude = float(candidate["longitude"])
        distance = coordinate_distance_m(
            latitude,
            longitude,
            station_latitude,
            station_longitude,
        )
        if distance > radius_m:
            continue
        row = dict(candidate)
        row["latitude"] = station_latitude
        row["longitude"] = station_longitude
        row["distance_m"] = distance
        result.append(row)
    return sorted(result, key=lambda row: (row["distance_m"], row["name_ko"]))


@router.get(
    "/stations/nearby",
    summary="위도·경도 기준 가까운 도시철도역 조회",
    description=(
        "WGS84 위도·경도와 반경을 받아 같은 이름의 환승역을 하나로 묶고 "
        "직선거리(distance_m) 순으로 반환합니다. ODsay 호환 응답이 아니라 "
        "거리·좌표 출처·데이터 기준일을 추가한 플랫폼 네이티브 JSON입니다."
    ),
    responses={
        401: {"description": "소비자 API 키 누락 또는 오류"},
        422: {"description": "좌표·반경·결과 개수의 형식 또는 범위 오류"},
    },
)
async def nearby_stations(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_m: int = Query(default=1000, ge=1, le=20_000),
    limit: int = Query(default=10, ge=1, le=50),
    api_consumer: str = Depends(require_public_api_key),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    del api_consumer
    rows = await _nearby_station_rows(
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        database=database,
    )
    grouped: dict[str, dict[str, Any]] = {}
    line_keys: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        key = normalize_station_name(str(row["name_ko"])).casefold()
        if key not in grouped:
            grouped[key] = {
                "id": row["id"],
                "name_ko": row["name_ko"],
                "name_en": row["name_en"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "distance_m": row["distance_m"],
                "coordinate_source_code": row["coordinate_source_code"],
                "coordinate_source_name": row["coordinate_source_name"],
                "coordinate_basis_date": row["coordinate_basis_date"],
                "lines": [],
            }
            line_keys[key] = set()
        for line in row.get("lines") or ():
            line_key = (str(line["line_code"]), str(line["station_code"]))
            if line_key in line_keys[key]:
                continue
            line_keys[key].add(line_key)
            grouped[key]["lines"].append(line)
    stations_result = list(grouped.values())[:limit]
    return {
        "query": {
            "latitude": latitude,
            "longitude": longitude,
            "radius_m": radius_m,
            "limit": limit,
        },
        "count": len(stations_result),
        "stations": stations_result,
    }


@odsay_router.get(
    "/pointSearch",
    response_model=None,
    operation_id="odsay_point_search_get",
    summary="ODsay v1 형태의 반경 내 지하철역 조회",
    description=(
        "ODsay pointSearch와 같은 x=경도, y=위도, radius, stationClass 요청 및 "
        "result.count/result.station[] JSON 구조를 제공합니다. stationClass=2, "
        "lang=0, output=json만 지원하며 버스·기차·터미널·공항·항만, 다국어와 "
        "XML은 제공되지 않습니다. stationID는 ODsay ID가 아닌 로컬 ID입니다."
    ),
    responses={
        400: {
            "description": "지원하지 않는 ODsay 옵션",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "-8",
                            "message": "현재 stationClass=2만 지원합니다.",
                        }
                    }
                }
            },
        },
        401: {"description": "소비자 API 키 누락 또는 오류"},
    },
)
@odsay_router.post(
    "/pointSearch",
    response_model=None,
    operation_id="odsay_point_search_post",
    summary="ODsay v1 형태의 반경 내 지하철역 조회",
    description=(
        "GET과 동일하며 모든 입력은 쿼리 파라미터로 전달합니다. "
        "stationClass=2, lang=0, output=json만 지원합니다."
    ),
)
async def odsay_point_search(
    x: float = Query(ge=-180, le=180, description="경도(WGS84)"),
    y: float = Query(ge=-90, le=90, description="위도(WGS84)"),
    radius: int = Query(
        default=250,
        ge=1,
        le=20_000,
        description="검색 반경(미터). 기본 250, 최대 20,000",
    ),
    station_class: str = Query(
        default="2",
        alias="stationClass",
        description="ODsay 분류값. 현재 2(지하철역)만 지원",
    ),
    lang: int = Query(default=0, description="언어. 현재 0(국문)만 지원"),
    output: str = Query(default="json", description="응답 형식. 현재 json만 지원"),
    api_consumer: str = Depends(require_public_api_key),
    database: Database = Depends(get_database),
) -> dict[str, Any] | JSONResponse:
    del api_consumer
    unsupported: list[str] = []
    if station_class != "2":
        unsupported.append("stationClass=2")
    if lang != 0:
        unsupported.append("lang=0")
    if output.casefold() != "json":
        unsupported.append("output=json")
    if unsupported:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": "-8",
                    "message": f"현재 {', '.join(unsupported)}만 지원합니다.",
                }
            },
        )
    rows = await _nearby_station_rows(
        latitude=y,
        longitude=x,
        radius_m=radius,
        database=database,
    )
    return build_odsay_point_response(rows)


@router.get("/travel-time")
async def travel_time(
    origin: str = Query(min_length=1, max_length=100),
    destination: str = Query(min_length=1, max_length=100),
    departure_at: datetime | None = Query(default=None),
    walking_mode: WalkingMode = Query(default="standard"),
    transfer_seconds: int = Query(default=300, ge=0, le=1800),
    transfer_buffer_seconds: int = Query(default=30, ge=0, le=600),
    api_consumer: str = Depends(require_public_api_key),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    del api_consumer
    calculation = await _calculate_travel_time(
        origin=origin,
        destination=destination,
        departure_at=departure_at,
        walking_mode=walking_mode,
        transfer_seconds=transfer_seconds,
        transfer_buffer_seconds=transfer_buffer_seconds,
        database=database,
    )
    if calculation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="요청한 출발 시각 이후 운행 시간표에서 경로를 찾지 못했습니다.",
        )
    journey = calculation.journey
    service_date = calculation.service_date
    local_departure = calculation.local_departure
    settings = get_settings()
    response = asdict(journey)
    response["service_date"] = service_date.isoformat()
    response["requested_departure_at"] = local_departure.isoformat()
    response["departure_at"] = to_datetime(
        service_date, journey.departure_sec, settings.timezone
    ).isoformat()
    response["arrival_at"] = to_datetime(
        service_date, journey.arrival_sec, settings.timezone
    ).isoformat()
    response["duration_minutes"] = ceil(journey.total_seconds / 60)
    response["walking_mode"] = walking_mode
    response["basis"] = (
        "활성 정적 시간표의 실제 열차 시각과 방향별 환승 최소 보행시간을 반영"
    )
    for leg in response["legs"]:
        if leg["kind"] == "RIDE":
            leg["departure_at"] = to_datetime(
                service_date, leg["departure_sec"], settings.timezone
            ).isoformat()
            leg["arrival_at"] = to_datetime(
                service_date, leg["arrival_sec"], settings.timezone
            ).isoformat()
        else:
            leg["arrival_at"] = to_datetime(
                service_date, leg["arrival_sec"], settings.timezone
            ).isoformat()
            leg["ready_at"] = to_datetime(
                service_date, leg["ready_sec"], settings.timezone
            ).isoformat()
            leg["departure_at"] = to_datetime(
                service_date, leg["departure_sec"], settings.timezone
            ).isoformat()
    return response


@odsay_router.get(
    "/searchPubTransPathT",
    response_model=None,
    operation_id="odsay_public_transit_path_get",
    summary="ODsay v1.8 형태의 시간표 기반 지하철 경로 조회",
    responses={
        404: {
            "description": "검색 결과 없음",
            "content": {
                "application/json": {
                    "example": {"error": {"code": "-99", "message": "검색결과가 없습니다."}}
                }
            },
        }
    },
)
@odsay_router.post(
    "/searchPubTransPathT",
    response_model=None,
    operation_id="odsay_public_transit_path_post",
    summary="ODsay v1.8 형태의 시간표 기반 지하철 경로 조회",
)
async def odsay_public_transit_path(
    origin: str = Query(min_length=1, max_length=100, description="확정된 출발역명"),
    destination: str = Query(min_length=1, max_length=100, description="확정된 도착역명"),
    departure_at: datetime | None = Query(default=None),
    walking_mode: WalkingMode = Query(default="standard"),
    transfer_seconds: int = Query(default=300, ge=0, le=1800),
    transfer_buffer_seconds: int = Query(default=30, ge=0, le=600),
    output: Literal["json"] = Query(default="json"),
    api_consumer: str = Depends(require_public_api_key),
    database: Database = Depends(get_database),
) -> dict[str, Any] | JSONResponse:
    del output, api_consumer  # JSON is the only supported representation.
    calculation = await _calculate_travel_time(
        origin=origin,
        destination=destination,
        departure_at=departure_at,
        walking_mode=walking_mode,
        transfer_seconds=transfer_seconds,
        transfer_buffer_seconds=transfer_buffer_seconds,
        database=database,
    )
    if calculation is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "-99", "message": "검색결과가 없습니다."}},
        )
    station_names = list(dict.fromkeys(calculation.journey.stations))
    async with database.connection() as connection:
        rows = await TransitQueryRepository.station_metadata_by_names(
            connection,
            station_names=station_names,
        )
    return build_odsay_path_response(
        calculation.journey,
        station_metadata_by_name(rows),
        walking_mode=walking_mode,
    )


async def _calculate_travel_time(
    *,
    origin: str,
    destination: str,
    departure_at: datetime | None,
    walking_mode: WalkingMode,
    transfer_seconds: int,
    transfer_buffer_seconds: int,
    database: Database,
) -> _TravelTimeCalculation | None:
    settings = get_settings()
    local_departure = departure_at or datetime.now(tz=settings.timezone)
    if local_departure.tzinfo is None:
        local_departure = local_departure.replace(tzinfo=settings.timezone)
    else:
        local_departure = local_departure.astimezone(settings.timezone)
    service_date = local_departure.date()
    departure_sec = (
        local_departure.hour * 3600 + local_departure.minute * 60 + local_departure.second
    )
    if local_departure.time() < time(3):
        service_date -= timedelta(days=1)
        departure_sec += 86_400

    async with database.connection() as connection:
        connection_rows = await TransitQueryRepository.list_schedule_connections(
            connection,
            service_date=service_date,
            departure_sec=departure_sec,
        )
        transfer_rows = await TransitQueryRepository.list_transfer_rules(
            connection,
            service_date=service_date,
        )
    connections = [
        ScheduleConnection(
            departure_stop=row["departure_stop"],
            arrival_stop=row["arrival_stop"],
            departure_station=row["departure_station"],
            arrival_station=row["arrival_station"],
            departure_sec=row["departure_sec"],
            arrival_sec=row["arrival_sec"],
            trip_id=row["trip_id"],
            trip_code=row["trip_code"],
            train_number=row["train_number"],
            line_code=row["line_code"],
            line_name=row["line_name"],
            direction=row["direction"],
            destination=row["destination"],
        )
        for row in connection_rows
    ]
    transfer_rules = [
        TransferRule(
            from_stop=row["from_stop"],
            to_stop=row["to_stop"],
            from_direction=row["from_direction"],
            to_direction=row["to_direction"],
            minimum_seconds=row["minimum_transfer_seconds"],
            accessible_seconds=row["accessible_transfer_seconds"],
            source_type=row["source_type"],
        )
        for row in transfer_rows
    ]
    journey = ForwardScheduleRouter(connections, transfer_rules).earliest_arrival(
        origin=origin,
        destination=destination,
        departure_sec=departure_sec,
        walking_mode=walking_mode,
        fallback_transfer_seconds=max(1, transfer_seconds),
        transfer_buffer_seconds=transfer_buffer_seconds,
    )
    if journey is None:
        return None
    return _TravelTimeCalculation(
        journey=journey,
        service_date=service_date,
        local_departure=local_departure,
    )


@router.get("/stations/{station_id}/timetable")
async def station_timetable(
    station_id: str,
    service_date: date,
    database: Database = Depends(get_database),
) -> list[dict[str, Any]]:
    async with database.connection() as connection:
        return await TransitQueryRepository.station_timetable(
            connection,
            station_id=station_id,
            service_date=service_date,
        )


@router.get("/service-alerts")
async def service_alerts(database: Database = Depends(get_database)) -> list[dict[str, Any]]:
    async with database.connection() as connection:
        return await TransitQueryRepository.service_alerts(connection)


@router.get("/sources/coverage")
async def source_coverage(database: Database = Depends(get_database)) -> list[dict[str, Any]]:
    async with database.connection() as connection:
        return await TransitQueryRepository.source_coverage(connection)


async def _cached_route(
    *,
    origin_station_id: str,
    destination_station_id: str,
    service_date: date,
    query_time_sec: int,
    arrive_by: bool,
    database: Database,
) -> dict[str, Any]:
    async with database.connection() as connection:
        route = await TransitQueryRepository.cached_route(
            connection,
            origin_station_id=origin_station_id,
            destination_station_id=destination_station_id,
            service_date=service_date,
            query_bucket_sec=query_time_sec,
            arrive_by=arrive_by,
        )
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No route is available for the requested timetable version",
        )
    return route


@router.get("/routes")
async def routes(
    origin_station_id: str,
    destination_station_id: str,
    service_date: date,
    departure_sec: int = Query(ge=0),
    api_consumer: str = Depends(require_public_api_key),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    del api_consumer
    return await _cached_route(
        origin_station_id=origin_station_id,
        destination_station_id=destination_station_id,
        service_date=service_date,
        query_time_sec=departure_sec,
        arrive_by=False,
        database=database,
    )


@router.get("/routes/last-train")
async def last_train(
    origin_station_id: str,
    destination_station_id: str,
    service_date: date,
    arrive_by_sec: int = Query(ge=0),
    access_walk_sec: int = Query(default=0, ge=0),
    egress_walk_sec: int = Query(default=0, ge=0),
    safety_margin_sec: int = Query(default=0, ge=0),
    api_consumer: str = Depends(require_public_api_key),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    del api_consumer
    route = await _cached_route(
        origin_station_id=origin_station_id,
        destination_station_id=destination_station_id,
        service_date=service_date,
        query_time_sec=arrive_by_sec,
        arrive_by=True,
        database=database,
    )
    route["request"] = {
        "access_walk_sec": access_walk_sec,
        "egress_walk_sec": egress_walk_sec,
        "safety_margin_sec": safety_margin_sec,
    }
    return route
