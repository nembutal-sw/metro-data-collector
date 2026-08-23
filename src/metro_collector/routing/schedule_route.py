from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from metro_collector.routing.travel_time import normalize_station_name

type WalkingMode = Literal["standard", "slow", "accessible"]
type PlatformId = str


@dataclass(frozen=True, slots=True)
class ScheduleConnection:
    departure_stop: str
    arrival_stop: str
    departure_station: str
    arrival_station: str
    departure_sec: int
    arrival_sec: int
    trip_id: str
    trip_code: str
    line_code: str
    line_name: str
    direction: str
    train_number: str | None = None
    destination: str | None = None

    def __post_init__(self) -> None:
        if self.departure_sec < 0 or self.arrival_sec < self.departure_sec:
            raise ValueError("A schedule connection must move forward in service time")

    @property
    def departure_platform(self) -> PlatformId:
        return _platform_id(self.departure_stop, self.direction)

    @property
    def arrival_platform(self) -> PlatformId:
        return _platform_id(self.arrival_stop, self.direction)


@dataclass(frozen=True, slots=True)
class TransferRule:
    from_stop: str
    to_stop: str
    minimum_seconds: int
    from_direction: str | None = None
    to_direction: str | None = None
    accessible_seconds: int | None = None
    source_type: str = "DEFAULT_ESTIMATE"

    def __post_init__(self) -> None:
        if self.minimum_seconds <= 0:
            raise ValueError("A transfer rule must have a positive duration")
        if self.accessible_seconds is not None and self.accessible_seconds <= 0:
            raise ValueError("An accessible transfer duration must be positive")


@dataclass(frozen=True, slots=True)
class RideLeg:
    kind: str
    line_code: str
    line_name: str
    direction: str
    trip_code: str
    train_number: str | None
    destination: str | None
    from_station: str
    to_station: str
    departure_sec: int
    arrival_sec: int
    duration_seconds: int
    station_count: int
    stations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransferLeg:
    kind: str
    station: str
    from_line_code: str
    from_line_name: str
    from_direction: str
    to_line_code: str
    to_line_name: str
    to_direction: str
    arrival_sec: int
    walking_seconds: int
    buffer_seconds: int
    ready_sec: int
    departure_sec: int
    waiting_seconds: int
    estimated: bool


type RouteLeg = RideLeg | TransferLeg


@dataclass(frozen=True, slots=True)
class ScheduleJourney:
    origin_station: str
    destination_station: str
    requested_departure_sec: int
    departure_sec: int
    arrival_sec: int
    total_seconds: int
    initial_wait_seconds: int
    in_vehicle_seconds: int
    transfer_walk_seconds: int
    transfer_buffer_seconds: int
    transfer_wait_seconds: int
    transfer_count: int
    stations: tuple[str, ...]
    legs: tuple[RouteLeg, ...]


@dataclass(frozen=True, slots=True)
class _Platform:
    stop_id: str
    station: str
    station_key: str
    line_code: str
    line_name: str
    direction: str


@dataclass(frozen=True, slots=True)
class _ConnectionStep:
    connection: ScheduleConnection


@dataclass(frozen=True, slots=True)
class _TransferStep:
    from_platform: PlatformId
    to_platform: PlatformId
    walking_seconds: int
    buffer_seconds: int
    estimated: bool


type _Predecessor = _ConnectionStep | _TransferStep


def _platform_id(stop_id: str, direction: str) -> PlatformId:
    return f"{stop_id}|{direction}"


class ForwardScheduleRouter:
    """Earliest-arrival connection scan with directional station footpaths."""

    def __init__(
        self,
        connections: list[ScheduleConnection],
        transfer_rules: list[TransferRule] | None = None,
    ) -> None:
        self._connections = sorted(connections, key=lambda item: item.departure_sec)
        self._platforms: dict[PlatformId, _Platform] = {}
        self._platforms_by_station: dict[str, set[PlatformId]] = defaultdict(set)
        self._rules: dict[tuple[str, str], list[TransferRule]] = defaultdict(list)
        for rule in transfer_rules or []:
            self._rules[(rule.from_stop, rule.to_stop)].append(rule)
        for connection in self._connections:
            self._register_platform(
                connection.departure_platform,
                connection.departure_stop,
                connection.departure_station,
                connection.line_code,
                connection.line_name,
                connection.direction,
            )
            self._register_platform(
                connection.arrival_platform,
                connection.arrival_stop,
                connection.arrival_station,
                connection.line_code,
                connection.line_name,
                connection.direction,
            )

    def earliest_arrival(
        self,
        *,
        origin: str,
        destination: str,
        departure_sec: int,
        walking_mode: WalkingMode = "standard",
        fallback_transfer_seconds: int = 300,
        transfer_buffer_seconds: int = 30,
    ) -> ScheduleJourney | None:
        if departure_sec < 0 or fallback_transfer_seconds <= 0 or transfer_buffer_seconds < 0:
            raise ValueError("Route times and transfer settings are invalid")
        if walking_mode not in ("standard", "slow", "accessible"):
            raise ValueError(f"Unsupported walking mode: {walking_mode}")

        origin_key = normalize_station_name(origin)
        destination_key = normalize_station_name(destination)
        origin_platforms = self._platforms_by_station.get(origin_key, set())
        destination_platforms = self._platforms_by_station.get(destination_key, set())
        if not origin_platforms or not destination_platforms:
            return None
        if origin_key == destination_key:
            display_name = self._platforms[next(iter(origin_platforms))].station
            return ScheduleJourney(
                origin_station=display_name,
                destination_station=display_name,
                requested_departure_sec=departure_sec,
                departure_sec=departure_sec,
                arrival_sec=departure_sec,
                total_seconds=0,
                initial_wait_seconds=0,
                in_vehicle_seconds=0,
                transfer_walk_seconds=0,
                transfer_buffer_seconds=0,
                transfer_wait_seconds=0,
                transfer_count=0,
                stations=(display_name,),
                legs=(),
            )

        earliest: dict[PlatformId, int] = {
            platform_id: departure_sec for platform_id in origin_platforms
        }
        predecessor: dict[PlatformId, _Predecessor] = {}

        for connection in self._connections:
            ready_sec = earliest.get(connection.departure_platform)
            if ready_sec is None or ready_sec > connection.departure_sec:
                continue
            if connection.arrival_sec >= earliest.get(connection.arrival_platform, 2**63 - 1):
                continue
            earliest[connection.arrival_platform] = connection.arrival_sec
            predecessor[connection.arrival_platform] = _ConnectionStep(connection)
            self._relax_transfers(
                connection.arrival_platform,
                connection.arrival_sec,
                earliest,
                predecessor,
                walking_mode=walking_mode,
                fallback_transfer_seconds=fallback_transfer_seconds,
                transfer_buffer_seconds=transfer_buffer_seconds,
            )

        reachable_destinations = [
            platform_id for platform_id in destination_platforms if platform_id in earliest
        ]
        if not reachable_destinations:
            return None
        destination_platform = min(reachable_destinations, key=earliest.__getitem__)
        steps = self._reconstruct(destination_platform, origin_platforms, predecessor)
        if not steps:
            return None
        return self._summarize(
            steps,
            requested_departure_sec=departure_sec,
            origin_station=self._platforms[steps[0].connection.departure_platform].station
            if isinstance(steps[0], _ConnectionStep)
            else self._platforms[steps[0].from_platform].station,
            destination_station=self._platforms[destination_platform].station,
        )

    def _register_platform(
        self,
        platform_id: PlatformId,
        stop_id: str,
        station: str,
        line_code: str,
        line_name: str,
        direction: str,
    ) -> None:
        platform = _Platform(
            stop_id=stop_id,
            station=station,
            station_key=normalize_station_name(station),
            line_code=line_code,
            line_name=line_name,
            direction=direction,
        )
        self._platforms[platform_id] = platform
        self._platforms_by_station[platform.station_key].add(platform_id)

    def _relax_transfers(
        self,
        from_platform_id: PlatformId,
        arrival_sec: int,
        earliest: dict[PlatformId, int],
        predecessor: dict[PlatformId, _Predecessor],
        *,
        walking_mode: WalkingMode,
        fallback_transfer_seconds: int,
        transfer_buffer_seconds: int,
    ) -> None:
        from_platform = self._platforms[from_platform_id]
        for to_platform_id in self._platforms_by_station[from_platform.station_key]:
            if to_platform_id == from_platform_id:
                continue
            to_platform = self._platforms[to_platform_id]
            walking_seconds, estimated = self._transfer_duration(
                from_platform,
                to_platform,
                walking_mode=walking_mode,
                fallback_transfer_seconds=fallback_transfer_seconds,
            )
            candidate = arrival_sec + walking_seconds + transfer_buffer_seconds
            if candidate >= earliest.get(to_platform_id, 2**63 - 1):
                continue
            earliest[to_platform_id] = candidate
            predecessor[to_platform_id] = _TransferStep(
                from_platform=from_platform_id,
                to_platform=to_platform_id,
                walking_seconds=walking_seconds,
                buffer_seconds=transfer_buffer_seconds,
                estimated=estimated,
            )

    def _transfer_duration(
        self,
        from_platform: _Platform,
        to_platform: _Platform,
        *,
        walking_mode: WalkingMode,
        fallback_transfer_seconds: int,
    ) -> tuple[int, bool]:
        matching_rules = [
            rule
            for rule in self._rules.get((from_platform.stop_id, to_platform.stop_id), [])
            if rule.from_direction in (None, from_platform.direction)
            and rule.to_direction in (None, to_platform.direction)
        ]
        if matching_rules:
            rule = max(
                matching_rules,
                key=lambda item: (
                    int(item.from_direction is not None) + int(item.to_direction is not None),
                    -item.minimum_seconds,
                ),
            )
            base_seconds = (
                rule.accessible_seconds
                if walking_mode == "accessible" and rule.accessible_seconds is not None
                else rule.minimum_seconds
            )
            multiplier = 1.5 if walking_mode == "slow" else 1.0
            if walking_mode == "accessible" and rule.accessible_seconds is None:
                multiplier = 1.75
            return round(base_seconds * multiplier), rule.source_type == "DEFAULT_ESTIMATE"

        multiplier = {"standard": 1.0, "slow": 1.5, "accessible": 1.75}[walking_mode]
        return round(fallback_transfer_seconds * multiplier), True

    @staticmethod
    def _reconstruct(
        destination_platform: PlatformId,
        origin_platforms: set[PlatformId],
        predecessor: dict[PlatformId, _Predecessor],
    ) -> list[_Predecessor]:
        steps: list[_Predecessor] = []
        current = destination_platform
        visited: set[PlatformId] = set()
        while current not in origin_platforms:
            if current in visited:
                return []
            visited.add(current)
            step = predecessor.get(current)
            if step is None:
                return []
            steps.append(step)
            if isinstance(step, _ConnectionStep):
                current = step.connection.departure_platform
            else:
                current = step.from_platform
        steps.reverse()
        return steps

    def _summarize(
        self,
        steps: list[_Predecessor],
        *,
        requested_departure_sec: int,
        origin_station: str,
        destination_station: str,
    ) -> ScheduleJourney:
        ride_groups: list[tuple[int, int, list[ScheduleConnection]]] = []
        for index, step in enumerate(steps):
            if not isinstance(step, _ConnectionStep):
                continue
            connection = step.connection
            if ride_groups and ride_groups[-1][2][-1].trip_id == connection.trip_id:
                start, _, connections = ride_groups[-1]
                connections.append(connection)
                ride_groups[-1] = (start, index, connections)
            else:
                ride_groups.append((index, index, [connection]))
        if not ride_groups:
            raise RuntimeError("A routed journey must contain at least one train connection")

        output_legs: list[RouteLeg] = []
        stations: list[str] = []
        transfer_walk_seconds = 0
        transfer_buffer_total = 0
        transfer_wait_seconds = 0

        for ride_index, (_start_index, end_index, connections) in enumerate(ride_groups):
            first = connections[0]
            last = connections[-1]
            ride_stations = [first.departure_station]
            ride_stations.extend(connection.arrival_station for connection in connections)
            if not stations:
                stations.extend(ride_stations)
            else:
                stations.extend(ride_stations[1:])
            output_legs.append(
                RideLeg(
                    kind="RIDE",
                    line_code=first.line_code,
                    line_name=first.line_name,
                    direction=first.direction,
                    trip_code=first.trip_code,
                    train_number=first.train_number,
                    destination=first.destination,
                    from_station=first.departure_station,
                    to_station=last.arrival_station,
                    departure_sec=first.departure_sec,
                    arrival_sec=last.arrival_sec,
                    duration_seconds=last.arrival_sec - first.departure_sec,
                    station_count=len(connections),
                    stations=tuple(ride_stations),
                )
            )
            if ride_index == len(ride_groups) - 1:
                continue

            next_start_index, _, next_connections = ride_groups[ride_index + 1]
            next_connection = next_connections[0]
            transfer_steps = [
                step
                for step in steps[end_index + 1 : next_start_index]
                if isinstance(step, _TransferStep)
            ]
            walking_seconds = sum(step.walking_seconds for step in transfer_steps)
            buffer_seconds = sum(step.buffer_seconds for step in transfer_steps)
            ready_sec = last.arrival_sec + walking_seconds + buffer_seconds
            waiting_seconds = max(0, next_connection.departure_sec - ready_sec)
            estimated = any(step.estimated for step in transfer_steps)
            transfer_walk_seconds += walking_seconds
            transfer_buffer_total += buffer_seconds
            transfer_wait_seconds += waiting_seconds
            output_legs.append(
                TransferLeg(
                    kind="TRANSFER",
                    station=last.arrival_station,
                    from_line_code=last.line_code,
                    from_line_name=last.line_name,
                    from_direction=last.direction,
                    to_line_code=next_connection.line_code,
                    to_line_name=next_connection.line_name,
                    to_direction=next_connection.direction,
                    arrival_sec=last.arrival_sec,
                    walking_seconds=walking_seconds,
                    buffer_seconds=buffer_seconds,
                    ready_sec=ready_sec,
                    departure_sec=next_connection.departure_sec,
                    waiting_seconds=waiting_seconds,
                    estimated=estimated,
                )
            )

        ride_legs = [leg for leg in output_legs if isinstance(leg, RideLeg)]
        first_ride = ride_legs[0]
        last_ride = ride_legs[-1]
        return ScheduleJourney(
            origin_station=origin_station,
            destination_station=destination_station,
            requested_departure_sec=requested_departure_sec,
            departure_sec=first_ride.departure_sec,
            arrival_sec=last_ride.arrival_sec,
            total_seconds=last_ride.arrival_sec - requested_departure_sec,
            initial_wait_seconds=first_ride.departure_sec - requested_departure_sec,
            in_vehicle_seconds=sum(leg.duration_seconds for leg in ride_legs),
            transfer_walk_seconds=transfer_walk_seconds,
            transfer_buffer_seconds=transfer_buffer_total,
            transfer_wait_seconds=transfer_wait_seconds,
            transfer_count=max(0, len(ride_legs) - 1),
            stations=tuple(stations),
            legs=tuple(output_legs),
        )
