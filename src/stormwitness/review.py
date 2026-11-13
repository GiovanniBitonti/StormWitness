"""Small, explicit, non-evidential review rules for weather context.

The thresholds are **illustrative**, not insurer policy, causation criteria,
meteorological warnings, or an acceptance/rejection decision.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from stormwitness.weather import HistoricalWeather

CONFIG_SCHEMA_VERSION = 1
MAX_CONFIG_BYTES = 4096
DEFAULT_WIND_GUST_KMH = 65.0
DEFAULT_RAIN_SUM_MM = 20.0


class ReviewConfigError(ValueError):
    """A user-supplied illustrative threshold config is unusable."""


@dataclass(frozen=True, slots=True)
class ReviewThresholds:
    wind_gust_kmh: float = DEFAULT_WIND_GUST_KMH
    rain_sum_mm: float = DEFAULT_RAIN_SUM_MM
    schema_version: int = CONFIG_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ReviewAssessment:
    review_suggested: bool
    data_incomplete: bool
    wind_trigger_met: bool | None
    rain_trigger_met: bool | None
    reason: str


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ReviewConfigError(f"{name} must be a positive number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ReviewConfigError(f"{name} must be a finite positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ReviewConfigError(f"{name} must be a finite positive number")
    return number


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous JSON objects instead of silently using the last value."""
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ReviewConfigError(f"Duplicate threshold config field: {key}")
        fields[key] = value
    return fields


def load_thresholds(path: str | Path | None = None) -> ReviewThresholds:
    """Return versioned defaults or an explicit whole-file JSON replacement.

    A complete config, rather than a partial override, avoids hidden fallback
    rules. Reject unknown fields and versions to prevent accidental misuse.
    """
    if path is None:
        return ReviewThresholds()
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        raise ReviewConfigError(f"Cannot read threshold config: {exc}") from exc
    if len(data) > MAX_CONFIG_BYTES:
        raise ReviewConfigError("Threshold config is too large (maximum 4096 bytes)")
    try:
        config = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)
    except ReviewConfigError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise ReviewConfigError("Threshold config must be valid UTF-8 JSON") from exc
    required = {"schema_version", "wind_gust_kmh", "rain_sum_mm"}
    if not isinstance(config, dict) or set(config) != required:
        raise ReviewConfigError("Threshold config must contain exactly: schema_version, wind_gust_kmh, rain_sum_mm")
    version = config["schema_version"]
    if type(version) is not int or version != CONFIG_SCHEMA_VERSION:
        raise ReviewConfigError(f"Unsupported threshold schema_version: {version!r} (expected 1)")
    return ReviewThresholds(
        wind_gust_kmh=_positive_number(config["wind_gust_kmh"], "wind_gust_kmh"),
        rain_sum_mm=_positive_number(config["rain_sum_mm"], "rain_sum_mm"),
    )


def assess_weather(weather: HistoricalWeather, thresholds: ReviewThresholds) -> ReviewAssessment:
    """Threshold comparisons use inclusive >= and **daily** provider values.

    Missing daily readings or hourly gaps prompt a review, never an automatic
    reassurance. This is a triage flag, not an assessment of claim validity.
    """
    gust = weather.daily_max_gust_kmh
    rain = weather.daily_rain_sum_mm
    wind_met = None if gust is None else gust >= thresholds.wind_gust_kmh
    rain_met = None if rain is None else rain >= thresholds.rain_sum_mm
    incomplete = (
        gust is None
        or rain is None
        or weather.missing_gust_hours > 0
        or weather.missing_rain_hours > 0
    )
    triggered = wind_met is True or rain_met is True
    if incomplete:
        reason = "Incomplete weather data; further manual weather review is suggested."
    elif triggered:
        reason = "At least one illustrative weather threshold was met; further weather review is suggested."
    else:
        reason = "Neither illustrative threshold was met; this does not rule out severe local weather or damage."
    return ReviewAssessment(
        review_suggested=incomplete or triggered,
        data_incomplete=incomplete,
        wind_trigger_met=wind_met,
        rain_trigger_met=rain_met,
        reason=reason,
    )
