from datetime import date
from pathlib import Path

from openpyxl import Workbook

from metro_collector.collectors.station_coordinates import iter_station_coordinates
from metro_collector.domain.models import NormalizedStationCoordinate
from metro_collector.ingestion.coordinates import (
    StationCoordinateTarget,
    match_station_coordinates,
)


def _write_workbook(path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(
        [
            "역번호",
            "역사명",
            "노선번호",
            "노선명",
            "영문역사명",
            "한자역사명",
            "환승역구분",
            "환승노선번호",
            "환승노선명",
            "역위도",
            "역경도",
            "운영기관명",
            "역사도로명주소",
            "역사전화번호",
            "데이터기준일자",
        ]
    )
    worksheet.append(
        [
            "D007",
            "강남",
            "I11D1",
            "신분당선",
            "Gangnam",
            None,
            "환승역",
            None,
            None,
            37.4973854,
            127.0278789,
            "신분당선",
            None,
            None,
            date(2026, 6, 18),
        ]
    )
    worksheet.append(
        [
            "K117",
            "청량리역",
            None,
            "경원선",
            "Cheongnyangni",
            None,
            None,
            None,
            None,
            37.5802,
            127.0468,
            "한국철도공사",
            None,
            None,
            "2026-06-18",
        ]
    )
    workbook.save(path)


def test_parses_kric_station_coordinates_and_shared_track_targets(tmp_path: Path) -> None:
    path = tmp_path / "stations.xlsx"
    _write_workbook(path)

    records = list(iter_station_coordinates(path))

    assert records[0].line_code == "SHINBUNDANG"
    assert records[0].station_name == "강남"
    assert records[0].data_basis_date == date(2026, 6, 18)
    cheongnyangni_lines = {
        record.line_code for record in records if record.station_name == "청량리"
    }
    assert cheongnyangni_lines == {
        "SEOUL_1",
        "GYEONGUI_JUNGANG",
        "GYEONGCHUN",
        "SUIN_BUNDANG",
    }


def test_matches_line_name_prefix_and_shared_station_fallback() -> None:
    records = [
        NormalizedStationCoordinate(
            line_code="INCHEON_2",
            source_line_name="인천지하철 2호선",
            source_station_code="I223",
            station_name="가정중앙시장",
            station_name_en="Gajeong Jungang Market",
            latitude=37.5172,
            longitude=126.6768,
            data_basis_date=date(2026, 6, 1),
            priority=100,
        ),
        NormalizedStationCoordinate(
            line_code="SEOUL_5",
            source_line_name="5호선",
            source_station_code="0518",
            station_name="까치산",
            station_name_en="Kkachisan",
            latitude=37.5318,
            longitude=126.8467,
            data_basis_date=date(2026, 6, 1),
            priority=100,
        ),
    ]
    targets = [
        StationCoordinateTarget("one", "INCHEON_2", "가정중앙", None, None),
        StationCoordinateTarget("two", "SEOUL_2", "까치산", None, None),
    ]

    matches, unresolved = match_station_coordinates(targets, records)

    assert not unresolved
    assert [match.method for match in matches] == [
        "LINE_NAME_PREFIX",
        "SHARED_STATION_NAME",
    ]
    assert all(match.accepted for match in matches)
