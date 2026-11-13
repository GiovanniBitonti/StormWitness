"""Open-Meteo Historical Weather adapter: one UK local calendar day.

Contract verified against Open-Meteo's public Historical Weather API docs on
2026-11-12. No network work happens at import time; the caller injects HTTPX.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
import re
from zoneinfo import ZoneInfo

import httpx

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_MODEL = "ecmwf_ifs"  # Both rain + 10 m gusts; available from 2017.
TIMEZONE = "Europe/London"
LOCAL_ZONE = ZoneInfo(TIMEZONE)
FIRST_SUPPORTED_DAY = date(2017, 1, 1)
HOURLY_FIELDS = "wind_gusts_10m,rain"
DAILY_FIELDS = "wind_gusts_10m_max,rain_sum"


class WeatherError(Exception):
    """Base exception for this adapter."""


class InvalidIncidentDateError(WeatherError):
    """The incident date is malformed or outside the supported period."""


class WeatherServiceError(WeatherError):
    """Open-Meteo could not process the request."""


class WeatherRateLimitError(WeatherServiceError):
    """Open-Meteo returned HTTP 429; no automatic retry is attempted."""

    def __init__(self, retry_after_seconds: int | None) -> None:
        self.retry_after_seconds = retry_after_seconds
        detail = (
            f"; retry after {retry_after_seconds} seconds"
            if retry_after_seconds is not None
            else "; retry later"
        )
        super().__init__(f"Open-Meteo rate limit (HTTP 429){detail}")


class WeatherDataError(WeatherError):
    """A successful HTTP response contains invalid or unavailable data."""


@dataclass(frozen=True, slots=True)
class HourlyWeather:
    timestamp_utc: datetime  # Aware UTC instant; never a naive local timestamp.
    wind_gust_kmh: float | None
    rain_mm: float | None  # Rain accumulated during the preceding hour.


@dataclass(frozen=True, slots=True)
class HistoricalWeather:
    incident_date: date
    requested_latitude: float
    requested_longitude: float
    grid_latitude: float
    grid_longitude: float
    daily_max_gust_kmh: float | None
    daily_rain_sum_mm: float | None
    hourly: tuple[HourlyWeather, ...]
    missing_gust_hours: int
    missing_rain_hours: int


def parse_incident_date(value: str, *, today: date | None = None) -> date:
    """A completed UK calendar day, not a 24-hour interval from an event time."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise InvalidIncidentDateError("Incident date must be YYYY-MM-DD")
    try:
        requested = date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidIncidentDateError("Incident date is not a valid calendar day") from exc
    current_day = today if today is not None else datetime.now(LOCAL_ZONE).date()
    if requested < FIRST_SUPPORTED_DAY:
        raise InvalidIncidentDateError("ECMWF IFS historical data starts in 2017")
    if requested >= current_day:
        raise InvalidIncidentDateError("Choose a completed historical UK calendar day")
    return requested


def _number(value: object, field: str, *, minimum: float = 0, maximum: float = math.inf) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeatherDataError(f"Missing or invalid {field}")
    try:
        result = float(value)
    except OverflowError as exc:
        raise WeatherDataError(f"Missing or invalid {field}") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise WeatherDataError(f"Missing or invalid {field}")
    return result


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None  # Preserve missing data; never substitute zero.
    return _number(value, field)


def _epoch(value: object, field: str) -> int:
    # Open-Meteo returns integral UNIX seconds with timeformat=unixtime.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeatherDataError(f"Invalid {field} timestamp")
    try:
        if not math.isfinite(value) or int(value) != value:
            raise WeatherDataError(f"Invalid {field} timestamp")
        result = int(value)
        # Ensure untrusted timestamps are within datetime's supported range.
        datetime.fromtimestamp(result, tz=timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise WeatherDataError(f"Invalid {field} timestamp") from exc
    return result


def _expected_hours(day: date) -> tuple[int, ...]:
    """23, 24 or 25 elapsed hours across the UK midnight-to-midnight interval."""
    start = datetime.combine(day, datetime.min.time(), LOCAL_ZONE).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), LOCAL_ZONE).astimezone(timezone.utc)
    return tuple(range(int(start.timestamp()), int(end.timestamp()), 3600))


def fetch_historical_weather(
    latitude: float,
    longitude: float,
    incident_date: str,
    *,
    client: httpx.Client,
) -> HistoricalWeather:
    """Fetch IFS hourly gust/rain and provider daily aggregates in one GET.

    No retries: each command issues at most one Postcodes.io GET and one
    Open-Meteo GET. JSON schemas and measurement units are checked explicitly.
    """
    day = parse_incident_date(incident_date)
    lat = _number(latitude, "latitude", minimum=-90, maximum=90)
    lon = _number(longitude, "longitude", minimum=-180, maximum=180)
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": day.isoformat(),
        "end_date": day.isoformat(),
        "models": HISTORICAL_MODEL,
        "hourly": HOURLY_FIELDS,
        "daily": DAILY_FIELDS,
        "timezone": TIMEZONE,
        "timeformat": "unixtime",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    try:
        response = client.get(ARCHIVE_URL, params=params)
    except httpx.TimeoutException as exc:
        raise WeatherServiceError("Open-Meteo request timed out") from exc
    except httpx.RequestError as exc:
        raise WeatherServiceError("Could not reach Open-Meteo") from exc

    if response.status_code == 429:
        raw = response.headers.get("Retry-After", "")
        delay = int(raw) if raw.isascii() and raw.isdecimal() and 0 <= int(raw) <= 86400 else None
        raise WeatherRateLimitError(delay)
    if response.status_code != 200:
        raise WeatherServiceError(f"Open-Meteo returned HTTP {response.status_code}")

    try:
        body = response.json()
    except (ValueError, UnicodeError) as exc:
        raise WeatherDataError("Open-Meteo returned invalid JSON") from exc
    if not isinstance(body, dict) or body.get("error") is True:
        raise WeatherDataError("Open-Meteo returned an error or unexpected JSON object")
    if body.get("timezone") != TIMEZONE:
        raise WeatherDataError("Open-Meteo returned an unexpected timezone")
    offset = body.get("utc_offset_seconds")
    if isinstance(offset, bool) or not isinstance(offset, int) or not -43200 <= offset <= 50400:
        raise WeatherDataError("Open-Meteo returned an invalid UTC offset")

    grid_lat = _number(body.get("latitude"), "grid latitude", minimum=-90, maximum=90)
    grid_lon = _number(body.get("longitude"), "grid longitude", minimum=-180, maximum=180)
    hourly, units = body.get("hourly"), body.get("hourly_units")
    daily, daily_units = body.get("daily"), body.get("daily_units")
    if any(not isinstance(part, dict) for part in (hourly, units, daily, daily_units)):
        raise WeatherDataError("Open-Meteo omitted hourly/daily data or unit metadata")
    for field, unit in (("wind_gusts_10m", "km/h"), ("rain", "mm")):
        if units.get(field) != unit:
            raise WeatherDataError(f"Unexpected unit for hourly {field}")
    for field, unit in (("wind_gusts_10m_max", "km/h"), ("rain_sum", "mm")):
        if daily_units.get(field) != unit:
            raise WeatherDataError(f"Unexpected unit for daily {field}")

    expected = _expected_hours(day)
    times = hourly.get("time")
    gusts = hourly.get("wind_gusts_10m")
    rain = hourly.get("rain")
    if any(not isinstance(series, list) for series in (times, gusts, rain)):
        raise WeatherDataError("Open-Meteo omitted a required hourly series")
    if not (len(times) == len(gusts) == len(rain) == len(expected)):
        raise WeatherDataError("Incomplete or misaligned hourly data arrays")
    epochs = tuple(_epoch(value, "hourly") for value in times)
    if epochs != expected:
        raise WeatherDataError("Hourly timestamps do not cover the requested UK calendar day")
    hours = tuple(
        HourlyWeather(
            timestamp_utc=datetime.fromtimestamp(epoch, tz=timezone.utc),
            wind_gust_kmh=_optional_number(gust, "hourly wind gust"),
            rain_mm=_optional_number(rainfall, "hourly rain"),
        )
        for epoch, gust, rainfall in zip(epochs, gusts, rain, strict=True)
    )

    daily_dates = daily.get("time")
    day_gusts = daily.get("wind_gusts_10m_max")
    day_rain = daily.get("rain_sum")
    if any(not isinstance(series, list) or len(series) != 1 for series in (daily_dates, day_gusts, day_rain)):
        raise WeatherDataError("Incomplete or misaligned daily data arrays")
    # Open-Meteo documents offset-adjustment for daily UNIX timestamps.
    local_calendar_date = datetime.fromtimestamp(
        _epoch(daily_dates[0], "daily") + offset, tz=timezone.utc
    ).date()
    if local_calendar_date != day:
        raise WeatherDataError("Open-Meteo daily date does not match incident date")
    return HistoricalWeather(
        incident_date=day,
        requested_latitude=lat,
        requested_longitude=lon,
        grid_latitude=grid_lat,
        grid_longitude=grid_lon,
        daily_max_gust_kmh=_optional_number(day_gusts[0], "daily maximum gust"),
        daily_rain_sum_mm=_optional_number(day_rain[0], "daily rain sum"),
        hourly=hours,
        missing_gust_hours=sum(hour.wind_gust_kmh is None for hour in hours),
        missing_rain_hours=sum(hour.rain_mm is None for hour in hours),
    )
