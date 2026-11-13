"""Two independent offline API requests in a single weather CLI invocation."""

import json

import httpx

from stormwitness import cli
from test_weather import good_response


def postcode_ok():
    return {
        "status": 200,
        "result": {"postcode": "SW1A 1AA", "latitude": 51.50101, "longitude": -0.141563},
    }


def test_weather_command_makes_two_requests_and_keeps_lookup_intact(monkeypatch, capsys):
    requests = []

    def handler(req):
        requests.append(req)
        if req.url.host == "api.postcodes.io":
            return httpx.Response(200, json=postcode_ok())
        if req.url.host == "archive-api.open-meteo.com":
            assert req.url.params["latitude"] == "51.50101"
            assert req.url.params["longitude"] == "-0.141563"
            return httpx.Response(200, json=good_response())
        raise AssertionError("Unexpected service")

    class OfflineClient(httpx.Client):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr(cli.httpx, "Client", OfflineClient)
    assert cli.main(["weather", "SW1A 1AA", "2023-11-02"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    data = json.loads(out)
    assert [request.url.host for request in requests] == ["api.postcodes.io", "archive-api.open-meteo.com"]
    assert data["postcode_lookup"]["latitude"] == 51.50101
    assert data["historical_weather"]["model"] == "ecmwf_ifs"
    assert data["historical_weather"]["daily"]["rain_sum_mm"] == 4.8
    assert len(data["historical_weather"]["hourly"]) == 24
    assert data["interpretation"].startswith("Modelled context")


def test_invalid_date_does_not_call_either_api(monkeypatch, capsys):
    def no_network(_):
        raise AssertionError("Invalid date should not access external APIs")

    class OfflineClient(httpx.Client):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(no_network)
            super().__init__(**kwargs)

    monkeypatch.setattr(cli.httpx, "Client", OfflineClient)
    assert cli.main(["weather", "SW1A 1AA", "2023-02-29"]) == 2
    assert "Input error" in capsys.readouterr().err


def test_rate_limited_weather_returns_nonzero_without_json(monkeypatch, capsys):
    def handler(req):
        if req.url.host == "api.postcodes.io":
            return httpx.Response(200, json=postcode_ok())
        return httpx.Response(429, headers={"Retry-After": "60"})

    class OfflineClient(httpx.Client):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr(cli.httpx, "Client", OfflineClient)
    assert cli.main(["weather", "SW1A 1AA", "2023-11-02"]) == 3
    out, err = capsys.readouterr()
    assert out == ""
    assert "HTTP 429" in err
    assert "60 seconds" in err
