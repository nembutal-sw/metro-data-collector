import asyncio
import json

from fastapi.responses import JSONResponse

from metro_collector.api.app import app
from metro_collector.api.routers.transit import odsay_point_search


def test_odsay_compatibility_route_registers_get_and_post() -> None:
    path = "/odsay/v1/api/searchPubTransPathT"
    operations = app.openapi()["paths"][path]

    assert {"get", "post"}.issubset(operations)
    assert operations["get"]["operationId"] == "odsay_public_transit_path_get"
    assert operations["post"]["operationId"] == "odsay_public_transit_path_post"
    assert "/api/v1/odsay/v1/api/searchPubTransPathT" not in app.openapi()["paths"]


def test_nearby_station_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/api/v1/stations/nearby"]
    assert {"get", "post"}.issubset(paths["/odsay/v1/api/pointSearch"])
    assert (
        paths["/odsay/v1/api/pointSearch"]["get"]["operationId"]
        == "odsay_point_search_get"
    )


def test_nearby_station_openapi_explains_odsay_compatibility_limits() -> None:
    paths = app.openapi()["paths"]
    point_search = paths["/odsay/v1/api/pointSearch"]["get"]
    native_nearby = paths["/api/v1/stations/nearby"]["get"]

    assert "stationClass=2" in point_search["description"]
    assert "XML은 제공되지 않습니다" in point_search["description"]
    assert (
        point_search["responses"]["400"]["content"]["application/json"]["example"][
            "error"
        ]["code"]
        == "-8"
    )
    assert "distance_m" in native_nearby["description"]


def test_point_search_rejects_unsupported_odsay_options_before_database_query() -> None:
    response = asyncio.run(
        odsay_point_search(
            x=127.0276,
            y=37.4979,
            radius=1000,
            station_class="1:2",
            lang=1,
            output="xml",
            api_consumer="test",
            database=None,  # type: ignore[arg-type]
        )
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    payload = json.loads(response.body)
    assert payload["error"]["code"] == "-8"
    assert "stationClass=2" in payload["error"]["message"]
    assert "lang=0" in payload["error"]["message"]
    assert "output=json" in payload["error"]["message"]
