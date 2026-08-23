from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import groupby

from metro_collector.collectors.base import TransitSourceCollector
from metro_collector.collectors.http import ArtifactDownloader, ConditionalRequest
from metro_collector.collectors.kric_standard import (
    KRIC_DATASET_PAGE,
    _direction,
    _normalize_trip_times,
    _ParsedStop,
    _workbook_rows,
    normalize_station_name,
    service_codes,
)
from metro_collector.collectors.seoul_open_data import parse_service_seconds
from metro_collector.config import Settings
from metro_collector.domain.enums import (
    CoverageStatus,
    SourceAccessStatus,
    SourceKind,
)
from metro_collector.domain.models import (
    ActivationResult,
    CollectedArtifact,
    CollectionResult,
    NormalizedStopTime,
    SourceMetadata,
    ValidationResult,
)
from metro_collector.exceptions import SourceFormatError
from metro_collector.quality.validators import validate_normalized_stop_times

SOURCE_CODE = "KORAIL_METRO_TIMETABLE"


@dataclass(frozen=True, slots=True)
class KorailLine:
    line_code: str
    station_order: tuple[str, ...]
    aliases: dict[str, str]


def _aliases(**values: str) -> dict[str, str]:
    return values


KORAIL_LINES: dict[str, KorailLine] = {
    "I28K1": KorailLine(
        line_code="SUIN_BUNDANG",
        station_order=(
            "청량리", "왕십리", "서울숲", "압구정로데오", "강남구청", "선정릉",
            "선릉", "한티", "도곡", "구룡", "개포동", "대모산입구", "수서",
            "복정", "가천대", "태평", "모란", "야탑", "이매", "서현", "수내",
            "정자", "미금", "오리", "죽전", "보정", "구성", "신갈", "기흥",
            "상갈", "청명", "영통", "망포", "매탄권선", "수원시청", "매교",
            "수원", "고색", "오목천", "어천", "야목", "사리", "한대앞",
            "중앙", "고잔", "초지", "안산", "신길온천", "정왕", "오이도",
            "달월", "월곶", "소래포구", "인천논현", "호구포", "남동인더스파크",
            "원인재", "연수", "송도", "인하대", "숭의", "신포", "인천",
        ),
        aliases=_aliases(
            강남구="강남구청", 로데오="압구정로데오", 남동인="남동인더스파크",
            대모산="대모산입구", 매탄권="매탄권선", 소래포="소래포구",
            수원시="수원시청", 신수원="수원", 신인천="인천", 신길온="신길온천",
            인천논="인천논현",
        ),
    ),
    "I4108": KorailLine(
        line_code="GYEONGUI_JUNGANG",
        station_order=(
            "서울", "임진강", "운천", "문산", "파주", "월롱", "금촌", "금릉",
            "운정", "야당", "탄현", "일산", "풍산", "백마", "곡산", "대곡",
            "능곡", "행신", "강매", "한국항공대", "화전", "수색",
            "디지털미디어시티", "가좌", "신촌", "홍대입구", "서강대", "공덕",
            "효창공원앞", "용산", "이촌", "서빙고", "한남", "옥수", "응봉",
            "왕십리", "청량리", "회기", "중랑", "상봉", "망우", "양원", "구리",
            "도농", "양정", "덕소", "도심", "팔당", "운길산", "양수", "신원",
            "국수", "아신", "오빈", "양평", "원덕", "용문", "지평",
        ),
        aliases=_aliases(
            디엠시="디지털미디어시티", 항공대="한국항공대", 홍대입="홍대입구",
            효창공="효창공원앞", **{"1양원": "양원", "1양정": "양정"},
        ),
    ),
    "I41WS": KorailLine(
        line_code="SEOHAE",
        station_order=(
            "일산", "풍산", "백마", "곡산", "대곡", "능곡", "김포공항", "원종",
            "부천종합운동장", "소사", "소새울", "시흥대야", "신천", "신현",
            "시흥시청", "시흥능곡", "달미", "선부", "초지", "시우", "원시",
        ),
        aliases=_aliases(
            신김포="김포공항", 부천종="부천종합운동장", 신소사="소사",
            시흥대="시흥대야", 신신천="신천", 신신현="신현", 시흥청="시흥시청",
            시흥능="시흥능곡", 신초지="초지",
        ),
    ),
    "I41K2": KorailLine(
        line_code="GYEONGCHUN",
        station_order=(
            "광운대", "청량리", "회기", "중랑", "상봉", "망우", "신내", "갈매",
            "별내", "퇴계원", "사릉", "금곡", "평내호평", "천마산", "마석",
            "대성리", "청평", "상천", "가평", "굴봉산", "백양리", "강촌",
            "김유정", "남춘천", "춘천",
        ),
        aliases=_aliases(평내호="평내호평"),
    ),
    "I41K5": KorailLine(
        line_code="GYEONGGANG",
        station_order=(
            "판교", "성남", "이매", "삼동", "경기광주", "초월", "곤지암", "도예촌",
            "이천", "부발", "세종대왕릉", "여주",
        ),
        aliases=_aliases(
            신판교="판교", 신이매="이매", 경광주="경기광주", 세종릉="세종대왕릉"
        ),
    ),
}


def _canonical_station(line: KorailLine, value: str) -> str:
    normalized = normalize_station_name(value)
    return line.aliases.get(normalized, normalized)


def _station_code(line: KorailLine, station_name: str) -> str:
    try:
        return f"K{line.station_order.index(station_name) + 1:03d}"
    except ValueError as error:
        raise SourceFormatError(f"Unknown Korail station: {station_name!r}") from error


def _group_key(item: tuple[int, dict[str, str]]) -> tuple[str, str, str, str, str]:
    _, row = item
    return (
        row.get("line_number", ""),
        row.get("train_number", ""),
        row.get("service", ""),
        row.get("origin", ""),
        row.get("destination", ""),
    )


def _parse_time(value: str) -> int | None:
    text = value.strip()
    if not text or text == ":":
        return None
    return parse_service_seconds(text)


def _iter_trip(
    key: tuple[str, str, str, str, str],
    rows: Sequence[tuple[int, dict[str, str]]],
) -> Iterator[NormalizedStopTime]:
    line_number, train_number, raw_service, raw_origin, raw_destination = key
    line = KORAIL_LINES[line_number]
    stops = [
        _ParsedStop(
            source_code=str(row_number),
            station_name=_canonical_station(line, row.get("stations", "")),
            arrival_sec=_parse_time(row.get("arrivals", "")),
            departure_sec=_parse_time(row.get("departures", "")),
        )
        for row_number, row in rows
        if row.get("stations", "").strip()
    ]
    if len(stops) < 2:
        return
    _normalize_trip_times(stops, fallback_segment_seconds=120)
    direction = _direction(stops, line.station_order)
    first_row_number, first_row = rows[0]
    operation_type = first_row.get("operation_type", "").upper()
    express_type = (
        "EXPRESS" if any(label in operation_type for label in ("급행", "직통", "EXPRESS")) else "LOCAL"
    )
    origin = _canonical_station(line, raw_origin) or stops[0].station_name
    destination = _canonical_station(line, raw_destination) or stops[-1].station_name
    for service_code in service_codes(raw_service):
        trip_code = (
            f"{line.line_code}:{service_code}:{direction}:{train_number}:{first_row_number}"
        )
        for sequence, stop in enumerate(stops, start=1):
            yield NormalizedStopTime(
                line_code=line.line_code,
                station_code=_station_code(line, stop.station_name),
                station_name=stop.station_name,
                service_code=service_code,
                direction=direction,
                trip_code=trip_code,
                train_number=train_number,
                stop_sequence=sequence,
                arrival_sec=stop.arrival_sec,
                departure_sec=stop.departure_sec,
                origin_name=origin,
                destination_name=destination,
                express_type=express_type,
                source_row_number=int(stop.source_code),
            )


def iter_korail_workbook(artifact: CollectedArtifact) -> Iterator[NormalizedStopTime]:
    for key, group in groupby(_workbook_rows(artifact.path), key=_group_key):
        if key[0] not in KORAIL_LINES:
            continue
        rows = list(group)
        try:
            yield from _iter_trip(key, rows)
        except (KeyError, ValueError) as error:
            raise SourceFormatError(
                f"Invalid Korail trip at source row {rows[0][0] if rows else 'unknown'}: {error}"
            ) from error


class KorailKricTimetableCollector(TransitSourceCollector):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._downloader = ArtifactDownloader(
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            timezone=settings.timezone,
        )

    async def inspect(self) -> SourceMetadata:
        return SourceMetadata(
            code=SOURCE_CODE,
            name="코레일 수도권 광역전철 표준데이터 운행정보",
            kind=SourceKind.DOWNLOAD_FILE,
            coverage=CoverageStatus.FULL_STATIC,
            access_status=SourceAccessStatus.ENABLED,
            base_url=KRIC_DATASET_PAGE,
            stores_raw_artifact=True,
            uses_private_api=False,
            notes="KRIC dataset id=6; 수도권 경의중앙·수인분당·경춘·경강·서해선만 선별",
        )

    async def collect(self, previous: CollectedArtifact | None = None) -> CollectionResult | None:
        today = datetime.now(tz=self._settings.timezone).date()
        artifact = await self._downloader.download(
            source_code=SOURCE_CODE,
            url=self._settings.kric_korail_timetable_download_url,
            recorded_url=KRIC_DATASET_PAGE,
            destination=(
                self._settings.raw_data_dir / SOURCE_CODE / f"kric-6-{today.isoformat()}.xlsx"
            ),
            conditional=ConditionalRequest(
                etag=previous.etag if previous else None,
                last_modified=previous.last_modified if previous else None,
            ),
        )
        if artifact is None or (previous and previous.checksum == artifact.checksum):
            return None
        return CollectionResult(artifact=artifact, effective_from=date(2026, 5, 31))

    def iter_records(self, artifact: CollectedArtifact) -> Iterator[NormalizedStopTime]:
        yield from iter_korail_workbook(artifact)

    async def validate(self, artifact: CollectedArtifact) -> ValidationResult:
        return validate_normalized_stop_times(
            self.iter_records(artifact),
            required_line_codes={line.line_code for line in KORAIL_LINES.values()},
        )

    async def activate(self, version_id: str) -> ActivationResult:
        return ActivationResult(
            activated=False,
            version_id=version_id,
            reason="Activation is transactionally performed by TimetableIngestionService",
        )
