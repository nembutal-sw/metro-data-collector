from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from itertools import count

DEFAULT_TRANSFER_SECONDS = 5 * 60


def normalize_station_name(value: str) -> str:
    normalized = "".join(value.strip().split()).casefold()
    if len(normalized) > 1 and normalized.endswith("역"):
        normalized = normalized[:-1]
    return normalized


@dataclass(frozen=True, slots=True)
class TravelTimeEdge:
    from_stop: str
    to_stop: str
    from_name: str
    to_name: str
    line_code: str
    line_name: str
    duration_sec: int

    def __post_init__(self) -> None:
        if self.duration_sec <= 0:
            raise ValueError("Travel-time edges must have a positive duration")


@dataclass(frozen=True, slots=True)
class TravelTimeLeg:
    line_code: str
    line_name: str
    from_station: str
    to_station: str
    duration_seconds: int
    station_count: int


@dataclass(frozen=True, slots=True)
class TravelTimeEstimate:
    origin_station: str
    destination_station: str
    total_seconds: int
    transfer_count: int
    transfer_seconds: int
    stations: tuple[str, ...]
    legs: tuple[TravelTimeLeg, ...]


@dataclass(frozen=True, slots=True)
class _PathStep:
    kind: str
    from_stop: str
    to_stop: str
    duration_sec: int
    edge: TravelTimeEdge | None = None


def estimate_travel_time(
    edges: list[TravelTimeEdge],
    *,
    origin: str,
    destination: str,
    transfer_seconds: int = DEFAULT_TRANSFER_SECONDS,
) -> TravelTimeEstimate | None:
    if transfer_seconds < 0:
        raise ValueError("Transfer duration cannot be negative")
    origin_key = normalize_station_name(origin)
    destination_key = normalize_station_name(destination)
    if not origin_key or not destination_key:
        return None

    adjacency: defaultdict[str, list[TravelTimeEdge]] = defaultdict(list)
    stops_by_name: defaultdict[str, set[str]] = defaultdict(set)
    stop_name: dict[str, str] = {}
    stop_line: dict[str, str] = {}
    for edge in edges:
        adjacency[edge.from_stop].append(edge)
        stops_by_name[normalize_station_name(edge.from_name)].add(edge.from_stop)
        stops_by_name[normalize_station_name(edge.to_name)].add(edge.to_stop)
        stop_name[edge.from_stop] = edge.from_name
        stop_name[edge.to_stop] = edge.to_name
        stop_line[edge.from_stop] = edge.line_code
        stop_line[edge.to_stop] = edge.line_code

    origins = stops_by_name.get(origin_key, set())
    destinations = stops_by_name.get(destination_key, set())
    if not origins or not destinations:
        return None
    if origin_key == destination_key:
        display_name = stop_name[next(iter(origins))]
        return TravelTimeEstimate(
            origin_station=display_name,
            destination_station=display_name,
            total_seconds=0,
            transfer_count=0,
            transfer_seconds=transfer_seconds,
            stations=(display_name,),
            legs=(),
        )

    distances: dict[str, tuple[int, int]] = {}
    previous: dict[str, _PathStep] = {}
    queue: list[tuple[int, int, int, str]] = []
    sequence = count()
    for stop in origins:
        distances[stop] = (0, 0)
        heapq.heappush(queue, (0, 0, next(sequence), stop))

    destination_stop: str | None = None
    while queue:
        elapsed, transfers, _, current = heapq.heappop(queue)
        if distances.get(current) != (elapsed, transfers):
            continue
        if current in destinations:
            destination_stop = current
            break

        for edge in adjacency.get(current, []):
            candidate = (elapsed + edge.duration_sec, transfers)
            if candidate >= distances.get(edge.to_stop, (2**63 - 1, 2**31 - 1)):
                continue
            distances[edge.to_stop] = candidate
            previous[edge.to_stop] = _PathStep(
                kind="RIDE",
                from_stop=current,
                to_stop=edge.to_stop,
                duration_sec=edge.duration_sec,
                edge=edge,
            )
            heapq.heappush(queue, (*candidate, next(sequence), edge.to_stop))

        current_name_key = normalize_station_name(stop_name[current])
        for transfer_stop in stops_by_name[current_name_key]:
            if transfer_stop == current or stop_line[transfer_stop] == stop_line[current]:
                continue
            candidate = (elapsed + transfer_seconds, transfers + 1)
            if candidate >= distances.get(transfer_stop, (2**63 - 1, 2**31 - 1)):
                continue
            distances[transfer_stop] = candidate
            previous[transfer_stop] = _PathStep(
                kind="TRANSFER",
                from_stop=current,
                to_stop=transfer_stop,
                duration_sec=transfer_seconds,
            )
            heapq.heappush(queue, (*candidate, next(sequence), transfer_stop))

    if destination_stop is None:
        return None

    steps: list[_PathStep] = []
    current = destination_stop
    while current not in origins:
        step = previous.get(current)
        if step is None:
            return None
        steps.append(step)
        current = step.from_stop
    steps.reverse()

    legs: list[TravelTimeLeg] = []
    stations: list[str] = [stop_name[steps[0].from_stop]] if steps else []
    for step in steps:
        if step.kind == "TRANSFER":
            continue
        ride_edge = step.edge
        if ride_edge is None:
            continue
        stations.append(ride_edge.to_name)
        if legs and legs[-1].line_code == ride_edge.line_code:
            previous_leg = legs[-1]
            legs[-1] = TravelTimeLeg(
                line_code=previous_leg.line_code,
                line_name=previous_leg.line_name,
                from_station=previous_leg.from_station,
                to_station=ride_edge.to_name,
                duration_seconds=previous_leg.duration_seconds + ride_edge.duration_sec,
                station_count=previous_leg.station_count + 1,
            )
        else:
            legs.append(
                TravelTimeLeg(
                    line_code=ride_edge.line_code,
                    line_name=ride_edge.line_name,
                    from_station=ride_edge.from_name,
                    to_station=ride_edge.to_name,
                    duration_seconds=ride_edge.duration_sec,
                    station_count=1,
                )
            )

    total_seconds, transfer_count = distances[destination_stop]
    return TravelTimeEstimate(
        origin_station=stop_name[steps[0].from_stop],
        destination_station=stop_name[destination_stop],
        total_seconds=total_seconds,
        transfer_count=transfer_count,
        transfer_seconds=transfer_seconds,
        stations=tuple(stations),
        legs=tuple(legs),
    )
