from pathlib import Path

import pytest

from metro_collector.collectors.seoul_transfer import (
    iter_transfer_csv,
    normalize_transfer_line,
    parse_duration_seconds,
)
from metro_collector.exceptions import SourceFormatError


def test_parse_official_transfer_csv(tmp_path: Path) -> None:
    path = tmp_path / "transfers.csv"
    path.write_text(
        "연번,호선,환승역명,환승노선,환승거리,환승소요시간\n"
        "1,1,서울역,공항철도,309,04:18\n"
        "2,2,강남,신분당선,214,02:58\n",
        encoding="cp949",
    )

    records = list(iter_transfer_csv(path))

    assert records[0].from_line_code == "SEOUL_1"
    assert records[0].to_line_code == "AREX"
    assert records[0].minimum_transfer_seconds == 258
    assert records[0].distance_m == 309
    assert records[1].to_line_code == "SHINBUNDANG"


@pytest.mark.parametrize(
    ("source", "expected"),
    [("4호선", "SEOUL_4"), ("국철", "SEOUL_1"), ("GTX-A", "GTX_A")],
)
def test_normalize_transfer_lines(source: str, expected: str) -> None:
    assert normalize_transfer_line(source) == expected


def test_invalid_transfer_values_fail_closed() -> None:
    with pytest.raises(SourceFormatError):
        normalize_transfer_line("알수없는노선")
    with pytest.raises(SourceFormatError):
        parse_duration_seconds("3분")
