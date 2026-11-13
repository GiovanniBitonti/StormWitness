"""Increment-2 offline tests: all HTTP goes through HTTPX MockTransport."""

from datetime import date, datetime, timezone
import json

import httpx
import pytest

from stormwitness.weather import (
    ARCHIVE_URL,
    HISTORICAL_MODEL,
    LOCAL_ZONE,
    InvalidIncidentDateError,
    WeatherDataError,
    WeatherRateLimitError,
    WeatherServiceError,
    _expected_hours,
    fetch_historical_weather,
    parse_incident_date,
)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=0.2)


def good_response(day="2023-11-02"):
    parsed = date.fromisoformat(day)
    times = _expected_hours(parsed)
    # UNIX seconds encode actual UTC instants; the daily value uses the
    # provider's documented utc_offset_seconds adjustment for local date.
    local_midnight = datetime(parsed.year, parsed.month, parsed.day, tzinfo=LOCAL_ZONE)
    utc_offset = int(local_midnight.utcoffset().total_seconds())
    return {
        "latitude": 51.5,
        "longitude": -0.125,
        "timezone": "Europe/London",
        "utc_offset_seconds": utc_offset,
        "hourly_units": {"time": "unixtime", "wind_gusts_10m": "km/h", "rain": "mm"},
        "hourly": {
            "time": list(times),
            "wind_gusts_10m": [45.0] * len(times),
            "rain": [0.2] * len(times),
        },
        "daily_units": {
            "time": "unixtime", "wind_gusts_10m_max": "km/h", "rain_sum": "mm"
        },
        "daily": {
            "time": [int(local_midnight.timestamp())],
            "wind_gusts_10m_max": [52.7],
            "rain_sum": [4.8],
        },
    }


def run(handler, date_value="2023-11-02"):
    with client(handler) as transport:
        return fetch_historical_weather(51.50101, -0.141563, date_value, client=transport)


def test_real_query_shape_and_clean_response():
    def handler(req):
        assert req.method == "GET"
        assert str(req.url).split("?")[0] == ARCHIVE_URL
        args = req.url.params
        assert args["models"] == HISTORICAL_MODEL == "ecmwf_ifs"
        assert args["latitude"] == "51.50101"
        assert args["longitude"] == "-0.141563"
        assert args["start_date"] == args["end_date"] == "2023-11-02"
        assert args["hourly"] == "wind_gusts_10m,rain"
        assert args["daily"] == "wind_gusts_10m_max,rain_sum"
        assert args["timezone"] == "Europe/London"
        assert args["timeformat"] == "unixtime"
        assert args["wind_speed_unit"] == "kmh"
        assert args["precipitation_unit"] == "mm"
        return httpx.Response(200, json=good_response())

    output = run(handler)
    assert output.requested_latitude == 51.50101
    assert output.grid_longitude == -0.125
    assert output.daily_rain_sum_mm == 4.8
    assert output.daily_max_gust_kmh == 52.7
    assert len(output.hourly) == 24
    assert output.hourly[0].timestamp_utc.tzinfo == timezone.utc
    assert output.missing_gust_hours == output.missing_rain_hours == 0


@pytest.mark.parametrize("day,count", [("2023-06-03", 24), ("2023-03-26", 23), ("2023-10-29", 25)])
def test_summer_and_dst_change_days(day, count):
    result = run(lambda _: httpx.Response(200, json=good_response(day)), date_value=day)
    assert len(result.hourly) == count
    assert all(ob.timestamp_utc.astimezone(LOCAL_ZONE).date() == date.fromisoformat(day) for ob in result.hourly)


def test_nulls_preserved_not_fabricated_as_zero():
    payload = good_response()
    payload["hourly"]["rain"][3] = None
    payload["hourly"]["wind_gusts_10m"][5] = None
    payload["daily"]["rain_sum"] = [None]
    output = run(lambda _: httpx.Response(200, json=payload))
    assert output.missing_gust_hours == 1
    assert output.missing_rain_hours == 1
    assert output.hourly[3].rain_mm is None
    assert output.hourly[5].wind_gust_kmh is None
    assert output.daily_rain_sum_mm is None
    assert output.daily_max_gust_kmh == 52.7


@pytest.mark.parametrize("bad_date", ["2023-2-02", "2023-02-29", "November 2 2023", "2023-11-02T10:00", "2016-12-31", "2100-01-01", None, "2023-11-02Z"])
def test_invalid_dates_before_any_network_calls(bad_date):
    def must_not_run(_):
        pytest.fail("Invalid date should not cause a request")

    with client(must_not_run) as transport:
        with pytest.raises(InvalidIncidentDateError):
            fetch_historical_weather(51.5, -0.1, bad_date, client=transport)


def test_today_is_rejected_using_injected_clock():
    with pytest.raises(InvalidIncidentDateError, match="completed"):
        parse_incident_date("2023-11-02", today=date(2023, 11, 2))


@pytest.mark.parametrize("bad_lat", [True, "51.5", None, float("nan"), 90.1, float("inf")])
def test_invalid_coordinate_before_http(bad_lat):
    with client(lambda _: pytest.fail("No request expected")) as transport:
        with pytest.raises(WeatherDataError):
            fetch_historical_weather(bad_lat, -0.1, "2023-11-02", client=transport)


@pytest.mark.parametrize("status", [400, 403, 404, 500, 503])
def test_http_failures(status):
    with pytest.raises(WeatherServiceError, match=str(status)):
        run(lambda _: httpx.Response(status, json={"error": True, "reason": "bad request"}))


@pytest.mark.parametrize("retry_after,expected", [("120", 120), ("not-a-number", None), ("999999", None), ("", None)])
def test_429_specific_error_and_bounded_retry_after(retry_after, expected):
    with pytest.raises(WeatherRateLimitError) as failure:
        run(lambda _: httpx.Response(429, headers={"Retry-After": retry_after}))
    assert failure.value.retry_after_seconds == expected
    assert "HTTP 429" in str(failure.value)


def test_timeout_mapped():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(WeatherServiceError, match="timed out"):
        run(handler)


def test_connection_failure_mapped():
    def handler(req):
        raise httpx.ConnectError("unreachable", request=req)

    with pytest.raises(WeatherServiceError, match="reach"):
        run(handler)


@pytest.mark.parametrize("payload", ["not json", "[]", '{"error": true, "reason": "invalid"}'])
def test_invalid_json_or_api_error(payload):
    with pytest.raises(WeatherDataError):
        run(lambda _: httpx.Response(200, text=payload))


@pytest.mark.parametrize("field,value", [("timezone", "GMT"), ("utc_offset_seconds", "3600"), ("latitude", None), ("longitude", 200.0)])
def test_bad_metadata(field, value):
    response = good_response()
    response[field] = value
    with pytest.raises(WeatherDataError):
        run(lambda _: httpx.Response(200, json=response))


@pytest.mark.parametrize("section,field,new_value", [
    ("hourly_units", "wind_gusts_10m", "mph"),
    ("hourly_units", "rain", "inch"),
    ("daily_units", "wind_gusts_10m_max", "m/s"),
    ("daily_units", "rain_sum", "inch"),
])
def test_wrong_units(section, field, new_value):
    response = good_response()
    response[section][field] = new_value
    with pytest.raises(WeatherDataError, match="unit"):
        run(lambda _: httpx.Response(200, json=response))


@pytest.mark.parametrize("field", ["time", "wind_gusts_10m", "rain"])
def test_missing_or_short_hourly_array(field):
    response = good_response()
    response["hourly"][field] = response["hourly"][field][1:]
    with pytest.raises(WeatherDataError, match="Incomplete"):
        run(lambda _: httpx.Response(200, json=response))


@pytest.mark.parametrize("field,bad", [("wind_gusts_10m", -1), ("rain", float("nan")), ("rain", "0.2"), ("rain", True)])
def test_bad_hourly_values(field, bad):
    response = good_response()
    response["hourly"][field][0] = bad
    with pytest.raises(WeatherDataError, match="hourly"):
        run(lambda _: httpx.Response(200, text=json.dumps(response)))


def test_wrong_or_repeated_hourly_timestamp():
    response = good_response()
    response["hourly"]["time"][3] = response["hourly"]["time"][2]
    with pytest.raises(WeatherDataError, match="timestamps"):
        run(lambda _: httpx.Response(200, json=response))


def test_noninteger_unix_timestamp():
    response = good_response()
    response["hourly"]["time"][0] += 0.5
    with pytest.raises(WeatherDataError, match="timestamp"):
        run(lambda _: httpx.Response(200, json=response))


def test_wrong_daily_date_and_missing_daily_values():
    response = good_response()
    response["daily"]["time"][0] -= 86400
    with pytest.raises(WeatherDataError, match="daily date"):
        run(lambda _: httpx.Response(200, json=response))


@pytest.mark.parametrize("field,bad", [("rain_sum", -0.1), ("wind_gusts_10m_max", False)])
def test_invalid_daily_numbers(field, bad):
    response = good_response()
    response["daily"][field] = [bad]
    with pytest.raises(WeatherDataError, match="daily"):
        run(lambda _: httpx.Response(200, json=response))


def test_malformed_daily_array():
    response = good_response()
    response["daily"]["time"] = []
    with pytest.raises(WeatherDataError, match="daily data"):
        run(lambda _: httpx.Response(200, json=response))


def test_extreme_timestamp_fails_as_data_error():
    response = good_response()
    response["hourly"]["time"][0] = 10**50
    with pytest.raises(WeatherDataError, match="timestamp"):
        run(lambda _: httpx.Response(200, json=response))


def test_extreme_coordinate_fails_as_data_error():
    with client(lambda _: pytest.fail("No request expected")) as transport:
        with pytest.raises(WeatherDataError, match="latitude"):
            fetch_historical_weather(10**400, -0.1, "2023-11-02", client=transport)
