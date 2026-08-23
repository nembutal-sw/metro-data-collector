from __future__ import annotations

import math
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Any, Literal

from metro_collector.routing.schedule_route import RideLeg, ScheduleJourney, TransferLeg

type WalkingMode = Literal["standard", "slow", "accessible"]


# ODsay LAB v1.8 subway line type codes. Unknown or future platform lines use 0.
SUBWAY_LINE_TYPE: dict[str, int] = {
    "SEOUL_1": 1,
    "SEOUL_2": 2,
    "SEOUL_3": 3,
    "SEOUL_4": 4,
    "SEOUL_5": 5,
    "SEOUL_6": 6,
    "SEOUL_7": 7,
    "SEOUL_8": 8,
    "SEOUL_9": 9,
    "INCHEON_1": 21,
    "INCHEON_2": 22,
    "GTX_A": 91,
    "AREX": 101,
    "GYEONGUI_JUNGANG": 104,
    "EVERLINE": 107,
    "GYEONGCHUN": 108,
    "SHINBUNDANG": 109,
    "UIJEONGBU_LRT": 110,
    "GYEONGGANG": 112,
    "UI_SINSEOL": 113,
    "SEOHAE": 114,
    "GIMPO_GOLD": 115,
    "SUIN_BUNDANG": 116,
    "SILLIM": 117,
}


@dataclass(frozen=True, slots=True)
class StationMetadata:
    source_id: str
    canonical_code: str
    name: str
    latitude: float | None
    longitude: float | None


def station_metadata_by_name(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, StationMetadata]:
    result: dict[str, StationMetadata] = {}
    for row in rows:
        name = str(row["name_ko"])
        result[name] = StationMetadata(
            source_id=str(row["id"]),
            canonical_code=str(row["canonical_code"]),
            name=name,
            latitude=_optional_float(row.get("latitude")),
            longitude=_optional_float(row.get("longitude")),
        )
    return result


def build_odsay_path_response(
    journey: ScheduleJourney,
    stations: Mapping[str, StationMetadata],
    *,
    walking_mode: WalkingMode,
) -> dict[str, Any]:
    """Map one schedule-based subway journey to ODsay v1.8's urban path shape.

    The response intentionally contains one subway path because the platform currently
    computes the earliest-arrival route only. Platform-local station IDs are stable
    integers but are not ODsay's proprietary station IDs.
    """

    ride_legs = [leg for leg in journey.legs if isinstance(leg, RideLeg)]
    transfer_legs = [leg for leg in journey.legs if isinstance(leg, TransferLeg)]
    traffic_distance = sum(_station_path_distance(leg.stations, stations) for leg in ride_legs)
    walk_distances = {
        index: _estimated_walk_distance(leg.walking_seconds, walking_mode)
        for index, leg in enumerate(transfer_legs)
    }
    total_walk = sum(walk_distances.values())
    waits = [journey.initial_wait_seconds]
    waits.extend(leg.waiting_seconds for leg in transfer_legs)

    sub_paths: list[dict[str, Any]] = [
        {"trafficType": 3, "distance": 0, "sectionTime": 0}
    ]
    transfer_index = 0
    next_wait_seconds = journey.initial_wait_seconds
    for leg in journey.legs:
        if isinstance(leg, RideLeg):
            sub_paths.append(
                _ride_sub_path(
                    leg,
                    stations,
                    interval_seconds=next_wait_seconds,
                )
            )
            next_wait_seconds = 0
            continue
        distance = walk_distances[transfer_index]
        transfer_index += 1
        sub_paths.append(
            {
                "trafficType": 3,
                "distance": distance,
                "sectionTime": _minutes(leg.walking_seconds + leg.buffer_seconds),
            }
        )
        next_wait_seconds = leg.waiting_seconds
    sub_paths.append({"trafficType": 3, "distance": 0, "sectionTime": 0})

    origin = stations.get(journey.origin_station)
    destination = stations.get(journey.destination_station)
    total_station_count = sum(leg.station_count for leg in ride_legs)
    result = {
        "searchType": 0,
        "outTrafficCheck": 0,
        "busCount": 0,
        "subwayCount": 1,
        "subwayBusCount": 0,
        "pointDistance": _distance_between(origin, destination),
        "startRadius": 0,
        "endRadius": 0,
        "path": [
            {
                "pathType": 1,
                "info": {
                    "trafficDistance": traffic_distance,
                    "totalWalk": total_walk,
                    "totalTime": _minutes(journey.total_seconds),
                    "payment": None,
                    "busTransitCount": 0,
                    "subwayTransitCount": journey.transfer_count,
                    "mapObj": "",
                    "firstStartStation": journey.origin_station,
                    "lastEndStation": journey.destination_station,
                    "totalStationCount": total_station_count,
                    "busStationCount": 0,
                    "subwayStationCount": total_station_count,
                    "totalDistance": traffic_distance + total_walk,
                    "checkIntervalTime": 30,
                    "checkIntervalTimeOverYn": (
                        "Y" if any(wait > 30 * 60 for wait in waits) else "N"
                    ),
                    "totalIntervalTime": _minutes(sum(waits)),
                },
                "subPath": sub_paths,
            }
        ],
    }
    return {"result": result}


def build_odsay_point_response(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Map nearby platform stations to ODsay v1 pointSearch's subway shape."""

    stations: list[dict[str, Any]] = []
    for row in rows:
        for line in row.get("lines") or ():
            line_code = str(line["line_code"])
            stations.append(
                {
                    "stationClass": 2,
                    "stationName": str(row["name_ko"]),
                    "stationID": local_station_id(f"{row['id']}:{line_code}"),
                    "type": SUBWAY_LINE_TYPE.get(line_code, 0),
                    "laneName": str(line["line_name"]),
                    "laneCity": "수도권",
                    "x": _optional_float(row.get("longitude")),
                    "y": _optional_float(row.get("latitude")),
                    "arsID": "",
                    "ebid": "",
                    "nonstopStation": 0,
                }
            )
    return {"result": {"count": len(stations), "station": stations}}


def coordinate_distance_m(
    latitude: float,
    longitude: float,
    target_latitude: float,
    target_longitude: float,
) -> int:
    radius_m = 6_371_008.8
    lat1 = math.radians(latitude)
    lat2 = math.radians(target_latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(target_longitude - longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return round(2 * radius_m * math.asin(math.sqrt(min(1.0, haversine))))


def local_station_id(value: str) -> int:
    result = zlib.crc32(value.encode("utf-8")) & 0x7FFFFFFF
    return result or 1


def _ride_sub_path(
    leg: RideLeg,
    stations: Mapping[str, StationMetadata],
    *,
    interval_seconds: int,
) -> dict[str, Any]:
    start = stations.get(leg.from_station)
    end = stations.get(leg.to_station)
    return {
        "trafficType": 1,
        "distance": _station_path_distance(leg.stations, stations),
        "sectionTime": _minutes(leg.duration_seconds),
        "stationCount": leg.station_count,
        "lane": [
            {
                "name": leg.line_name,
                "subwayCode": SUBWAY_LINE_TYPE.get(leg.line_code, 0),
                "subwayCityCode": 1000,
            }
        ],
        "intervalTime": _minutes(interval_seconds),
        "startName": leg.from_station,
        "startX": start.longitude if start else None,
        "startY": start.latitude if start else None,
        "endName": leg.to_station,
        "endX": end.longitude if end else None,
        "endY": end.latitude if end else None,
        "way": leg.destination or leg.direction,
        "wayCode": _way_code(leg.direction),
        "door": "-2--2",
        "startID": _station_id(start, leg.from_station),
        "endID": _station_id(end, leg.to_station),
        "passStopList": {
            "stations": [
                _pass_station(index, name, stations.get(name))
                for index, name in enumerate(leg.stations)
            ]
        },
    }


def _pass_station(
    index: int,
    name: str,
    station: StationMetadata | None,
) -> dict[str, Any]:
    return {
        "index": index,
        "stationID": _station_id(station, name),
        "stationName": name,
        "x": str(station.longitude) if station and station.longitude is not None else "",
        "y": str(station.latitude) if station and station.latitude is not None else "",
    }


def _station_id(station: StationMetadata | None, fallback: str) -> int:
    # ODsay uses integer IDs. This compatibility API exposes a deterministic local ID
    # without copying or claiming ODsay's proprietary identifier namespace.
    source = station.source_id if station else fallback
    return local_station_id(source)


def _station_path_distance(
    names: Sequence[str],
    stations: Mapping[str, StationMetadata],
) -> int:
    distance = 0.0
    for first_name, second_name in pairwise(names):
        first = stations.get(first_name)
        second = stations.get(second_name)
        pair_distance = _distance_between(first, second)
        if pair_distance is not None:
            distance += pair_distance
    return round(distance)


def _distance_between(
    first: StationMetadata | None,
    second: StationMetadata | None,
) -> int | None:
    if (
        first is None
        or second is None
        or first.latitude is None
        or first.longitude is None
        or second.latitude is None
        or second.longitude is None
    ):
        return None
    return coordinate_distance_m(
        first.latitude,
        first.longitude,
        second.latitude,
        second.longitude,
    )


def _estimated_walk_distance(seconds: int, walking_mode: WalkingMode) -> int:
    meters_per_second = {
        "standard": 1.2,
        "slow": 0.8,
        "accessible": 0.8,
    }[walking_mode]
    return round(seconds * meters_per_second)


def _way_code(direction: str) -> int:
    normalized = direction.upper()
    return 1 if normalized in {"UP", "UPBOUND", "상행", "상선"} else 2


def _minutes(seconds: int) -> int:
    return math.ceil(seconds / 60)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)
