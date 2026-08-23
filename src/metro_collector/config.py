from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_timezone: str = "Asia/Seoul"
    log_level: str = "INFO"

    database_url: SecretStr = SecretStr("postgresql://metro:metro@localhost:5432/metro")
    admin_api_key: SecretStr | None = None
    public_api_key_hashes: SecretStr | None = None
    seoul_open_data_api_key: SecretStr | None = None
    seoul_subway_realtime_api_key: SecretStr | None = None
    data_go_kr_service_key: SecretStr | None = None
    kric_api_key: SecretStr | None = None
    kakao_mobility_rest_api_key: SecretStr | None = None

    raw_data_dir: Path = Path("data/raw")
    staging_data_dir: Path = Path("data/staging")
    http_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    http_max_retries: int = Field(default=3, ge=0, le=10)
    external_api_min_interval_seconds: float = Field(default=0.25, ge=0, le=60)
    data_go_kr_daily_request_budget: int = Field(default=9000, gt=0, le=1_000_000)
    kric_daily_request_budget: int = Field(default=900, gt=0, le=1_000_000)
    seoul_open_data_daily_request_budget: int = Field(default=900, gt=0, le=1_000_000)
    seoul_timetable_download_url: str | None = None
    seoul_timetable_effective_from: date = date(2026, 6, 16)
    incheon_1_weekday_up_url: str | None = None
    incheon_1_weekday_down_url: str | None = None
    incheon_1_holiday_up_url: str | None = None
    incheon_1_holiday_down_url: str | None = None
    incheon_2_weekday_up_url: str | None = None
    incheon_2_weekday_down_url: str | None = None
    incheon_2_holiday_up_url: str | None = None
    incheon_2_holiday_down_url: str | None = None
    incheon_timetable_effective_from: date = date(2025, 6, 28)
    seoul_transfer_distance_download_url: str | None = (
        "https://www.data.go.kr/cmm/cmm/fileDownload.do?"
        "atchFileId=FILE_000000003619893&fileDetailSn=1&insertDataPrcus=N"
    )
    seoul_transfer_distance_effective_from: date = date(2025, 12, 31)
    kric_station_coordinates_download_url: str = (
        "https://openapi.kric.go.kr/rips/dataset/download.file?"
        "type=filedata&id=32&operation=1"
    )
    kric_arex_timetable_download_url: str = (
        "https://openapi.kric.go.kr/rips/dataset/download.file?"
        "type=filedata&id=7&operation=1"
    )
    kric_shinbundang_timetable_download_url: str = (
        "https://openapi.kric.go.kr/rips/dataset/download.file?"
        "type=filedata&id=15&operation=1"
    )
    kric_ui_sinseol_timetable_download_url: str = (
        "https://openapi.kric.go.kr/rips/dataset/download.file?"
        "type=filedata&id=911&operation=1"
    )
    kric_sillim_timetable_download_url: str = (
        "https://openapi.kric.go.kr/rips/dataset/download.file?"
        "type=filedata&id=1221&operation=1"
    )
    kric_gimpo_gold_timetable_download_url: str = (
        "https://openapi.kric.go.kr/rips/dataset/download.file?"
        "type=filedata&id=903&operation=1"
    )
    kric_uijeongbu_timetable_download_url: str = (
        "https://openapi.kric.go.kr/rips/dataset/download.file?"
        "type=filedata&id=17&operation=1"
    )
    kric_korail_timetable_download_url: str = (
        "https://openapi.kric.go.kr/rips/dataset/download.file?"
        "type=filedata&id=6&operation=1"
    )
    arex_official_timetable_page_url: str = (
        "https://www.airportrailroad.com/train/normal/info/010/0"
    )
    arex_official_timetable_download_url: str | None = None
    arex_official_timetable_effective_from: date = date(2025, 12, 29)
    ui_sinseol_official_page_template: str = (
        "https://www.ui-line.com/html/intro/intro00/intro_00_{station:02d}.php?pGubn=T2"
    )
    ui_sinseol_official_effective_from: date = date(2022, 5, 30)
    sillim_official_page_template: str = (
        "https://www.sillimlrt.com/kr/html/sub01/010102{station:02d}.html"
    )
    sillim_official_effective_from: date = date(2025, 9, 23)
    uijeongbu_official_timetable_page_url: str = (
        "https://www.ulrt.co.kr/doc/contents/information/time.php"
    )
    uijeongbu_official_effective_from: date = date(2025, 12, 31)

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def public_api_key_hash_values(self) -> tuple[str, ...]:
        configured = self.public_api_key_hashes
        if configured is None:
            return ()
        return tuple(
            value.strip().casefold()
            for value in configured.get_secret_value().split(",")
            if value.strip()
        )

    def ensure_data_directories(self) -> None:
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        self.staging_data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
