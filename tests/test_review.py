"""Illustrative rules and config validation; no requests to external APIs."""

from dataclasses import replace
from datetime import date
import json

import pytest

from stormwitness.review import (
    ReviewConfigError,
    ReviewThresholds,
    assess_weather,
    load_thresholds,
)
from stormwitness.weather import HistoricalWeather


def sample_weather(**overrides):
    base = HistoricalWeather(
        incident_date=date(2023, 11, 2), requested_latitude=51.50101,
        requested_longitude=-0.141563, grid_latitude=51.493847,
        grid_longitude=-0.1630249, daily_max_gust_kmh=70.2,
        daily_rain_sum_mm=17.9, hourly=(), missing_gust_hours=0,
        missing_rain_hours=0,
    )
    return replace(base, **overrides)


def test_default_review_thresholds_are_explicit_and_versioned():
    assert load_thresholds() == ReviewThresholds(65.0, 20.0, 1)


def test_config_read_from_json(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"schema_version": 1, "wind_gust_kmh": 80, "rain_sum_mm": 35}), encoding="utf-8")
    assert load_thresholds(p) == ReviewThresholds(80.0, 35.0, 1)


@pytest.mark.parametrize("config", [
    {}, [], "not a config", {"schema_version": 1, "wind_gust_kmh": 65},
    {"schema_version": 1, "wind_gust_kmh": 65, "rain_sum_mm": 20, "extra": 1},
    {"schema_version": 2, "wind_gust_kmh": 65, "rain_sum_mm": 20},
    {"schema_version": True, "wind_gust_kmh": 65, "rain_sum_mm": 20},
    {"schema_version": 1, "wind_gust_kmh": 0, "rain_sum_mm": 20},
    {"schema_version": 1, "wind_gust_kmh": -2, "rain_sum_mm": 20},
    {"schema_version": 1, "wind_gust_kmh": True, "rain_sum_mm": 20},
    {"schema_version": 1, "wind_gust_kmh": "65", "rain_sum_mm": 20},
    {"schema_version": 1, "wind_gust_kmh": float("nan"), "rain_sum_mm": 20},
    {"schema_version": 1, "wind_gust_kmh": 65, "rain_sum_mm": float("inf")},
])
def test_bad_configs_fail_closed(tmp_path, config):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ReviewConfigError):
        load_thresholds(p)


@pytest.mark.parametrize("duplicate", ["schema_version", "wind_gust_kmh", "rain_sum_mm"])
def test_duplicate_json_threshold_keys_are_rejected(tmp_path, duplicate):
    config = '{"schema_version":1,"wind_gust_kmh":65,"rain_sum_mm":20}'
    # JSON permits duplicate names syntactically; they must not silently override thresholds.
    config = config[:-1] + f',"{duplicate}":999}}'
    p = tmp_path / "duplicate.json"
    p.write_text(config, encoding="utf-8")
    with pytest.raises(ReviewConfigError, match="Duplicate"):
        load_thresholds(p)


def test_bad_utf8_oversized_invalid_json_and_missing_config(tmp_path):
    p = tmp_path / "config.json"
    for content in (b"\xff", b"{", b"x" * 4097):
        p.write_bytes(content)
        with pytest.raises(ReviewConfigError):
            load_thresholds(p)
    with pytest.raises(ReviewConfigError):
        load_thresholds(tmp_path / "not-there.json")


def test_live_example_triggers_review_on_gust_only():
    result = assess_weather(sample_weather(), load_thresholds())
    assert (result.review_suggested, result.wind_trigger_met, result.rain_trigger_met) == (True, True, False)
    assert not result.data_incomplete


def test_comparisons_inclusive_at_threshold():
    result = assess_weather(sample_weather(daily_max_gust_kmh=65, daily_rain_sum_mm=20), load_thresholds())
    assert result.wind_trigger_met and result.rain_trigger_met


def test_below_both_thresholds_does_not_prove_safety():
    result = assess_weather(sample_weather(daily_max_gust_kmh=40, daily_rain_sum_mm=3), load_thresholds())
    assert not result.review_suggested
    assert not result.wind_trigger_met and not result.rain_trigger_met
    assert "does not rule out" in result.reason


@pytest.mark.parametrize("overrides", [
    {"daily_max_gust_kmh": None}, {"daily_rain_sum_mm": None},
    {"daily_max_gust_kmh": None, "daily_rain_sum_mm": None},
    {"missing_gust_hours": 1}, {"missing_rain_hours": 3},
])
def test_incomplete_data_always_prompts_manual_review(overrides):
    result = assess_weather(sample_weather(**({"daily_max_gust_kmh": 40, "daily_rain_sum_mm": 3} | overrides)), load_thresholds())
    assert result.review_suggested and result.data_incomplete
    assert "manual" in result.reason


def test_missing_is_not_treated_as_zero():
    result = assess_weather(sample_weather(daily_max_gust_kmh=None, daily_rain_sum_mm=3), load_thresholds())
    assert result.wind_trigger_met is None
    assert result.rain_trigger_met is False
