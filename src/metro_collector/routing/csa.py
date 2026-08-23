from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

type StopId = str


@dataclass(frozen=True, slots=True)
class Connection:
    departure_stop: StopId
    arrival_stop: StopId
    departure_sec: int
    arrival_sec: int
    trip_id: str
    line_code: str
    train_number: str | None = None
    destination: str | None = None

    def __post_init__(self) -> None:
        if self.departure_sec < 0 or self.arrival_sec < self.departure_sec:
            raise ValueError("A connection must move forward in service time")


@dataclass(frozen=True, slots=True)
class Footpath:
    from_stop: StopId
    to_stop: StopId
    duration_sec: int

    def __post_init__(self) -> None:
        if self.duration_sec < 0:
            raise ValueError("Footpath duration cannot be negative")


@dataclass(frozen=True, slots=True)
class JourneyLeg:
    kind: str
    from_stop: StopId
    to_stop: StopId
    departure_sec: int
    arrival_sec: int
    trip_id: str | None = None
    line_code: str | None = None
    train_number: str | None = None
    destination: str | None = None


@dataclass(frozen=True, slots=True)
class Journey:
    origin: StopId
    destination: StopId
    departure_sec: int
    arrival_sec: int
    legs: tuple[JourneyLeg, ...]
    transfer_count: int


type Successor = Connection | Footpath


class ReverseConnectionScan:
    """Compute the latest feasible departure for an arrive-by query."""

    def __init__(
        self,
        connections: list[Connection],
        footpaths: list[Footpath] | None = None,
    ) -> None:
        self._connections = sorted(connections, key=lambda item: item.departure_sec, reverse=True)
        self._incoming_footpaths: dict[StopId, list[Footpath]] = defaultdict(list)
        for footpath in footpaths or []:
            self._incoming_footpaths[footpath.to_stop].append(footpath)

    def latest_departure(
        self,
        *,
        origin: StopId,
        destination: StopId,
        arrive_by_sec: int,
        access_walk_sec: int = 0,
        egress_walk_sec: int = 0,
        safety_margin_sec: int = 0,
    ) -> Journey | None:
        if min(arrive_by_sec, access_walk_sec, egress_walk_sec, safety_margin_sec) < 0:
            raise ValueError("Times and margins cannot be negative")

        target_time = arrive_by_sec - egress_walk_sec - safety_margin_sec
        latest: dict[StopId, int] = {destination: target_time}
        successor: dict[StopId, Successor] = {}
        self._relax_reverse_footpaths(destination, latest, successor)

        for connection in self._connections:
            latest_at_arrival = latest.get(connection.arrival_stop)
            if latest_at_arrival is None or connection.arrival_sec > latest_at_arrival:
                continue
            current = latest.get(connection.departure_stop, -1)
            if connection.departure_sec <= current:
                continue
            latest[connection.departure_stop] = connection.departure_sec
            successor[connection.departure_stop] = connection
            self._relax_reverse_footpaths(connection.departure_stop, latest, successor)

        platform_departure = latest.get(origin)
        if platform_departure is None or platform_departure < access_walk_sec:
            return None
        legs = self._reconstruct(origin, destination, successor, latest)
        if not legs:
            return None
        train_trips = [leg.trip_id for leg in legs if leg.kind == "TRAIN"]
        transfer_count = max(0, len(list(dict.fromkeys(train_trips))) - 1)
        return Journey(
            origin=origin,
            destination=destination,
            departure_sec=platform_departure - access_walk_sec,
            arrival_sec=legs[-1].arrival_sec + egress_walk_sec,
            legs=tuple(legs),
            transfer_count=transfer_count,
        )

    def _relax_reverse_footpaths(
        self,
        changed_stop: StopId,
        latest: dict[StopId, int],
        successor: dict[StopId, Successor],
    ) -> None:
        queue: deque[StopId] = deque([changed_stop])
        while queue:
            to_stop = queue.popleft()
            to_time = latest[to_stop]
            for footpath in self._incoming_footpaths.get(to_stop, []):
                candidate = to_time - footpath.duration_sec
                if candidate <= latest.get(footpath.from_stop, -1):
                    continue
                latest[footpath.from_stop] = candidate
                successor[footpath.from_stop] = footpath
                queue.append(footpath.from_stop)

    @staticmethod
    def _reconstruct(
        origin: StopId,
        destination: StopId,
        successor: dict[StopId, Successor],
        latest: dict[StopId, int],
    ) -> list[JourneyLeg]:
        legs: list[JourneyLeg] = []
        current = origin
        visited: set[StopId] = set()
        while current != destination:
            if current in visited or current not in successor:
                return []
            visited.add(current)
            edge = successor[current]
            if isinstance(edge, Connection):
                legs.append(
                    JourneyLeg(
                        kind="TRAIN",
                        from_stop=edge.departure_stop,
                        to_stop=edge.arrival_stop,
                        departure_sec=edge.departure_sec,
                        arrival_sec=edge.arrival_sec,
                        trip_id=edge.trip_id,
                        line_code=edge.line_code,
                        train_number=edge.train_number,
                        destination=edge.destination,
                    )
                )
                current = edge.arrival_stop
            else:
                departure_sec = max(
                    latest.get(edge.from_stop, 0),
                    legs[-1].arrival_sec if legs else 0,
                )
                legs.append(
                    JourneyLeg(
                        kind="WALK",
                        from_stop=edge.from_stop,
                        to_stop=edge.to_stop,
                        departure_sec=departure_sec,
                        arrival_sec=departure_sec + edge.duration_sec,
                    )
                )
                current = edge.to_stop
        return legs
