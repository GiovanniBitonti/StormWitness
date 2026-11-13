"""End-to-end report command through two mocked independent HTTP endpoints."""

import json

import httpx

from stormwitness import cli
from test_weather import good_response
from test_weather_cli import postcode_ok


def offline_client(monkeypatch, requests):
    def handler(req):
        requests.append(req)
        if req.url.host == "api.postcodes.io":
            return httpx.Response(200, json=postcode_ok())
        if req.url.host == "archive-api.open-meteo.com":
            return httpx.Response(200, json=good_response())
        raise AssertionError(f"Unexpected host: {req.url.host}")

    class Client(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cli.httpx, "Client", Client)


def test_report_command_makes_two_api_requests_and_writes_html(monkeypatch, tmp_path, capsys):
    requests = []
    offline_client(monkeypatch, requests)
    path = tmp_path / "StormWitness.html"
    status = cli.main(["report", "SW1A 1AA", "2023-11-02", "--output", str(path)])
    assert status == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "Report created:" in out
    assert [r.url.host for r in requests] == ["api.postcodes.io", "archive-api.open-meteo.com"]
    assert path.is_file()
    html = path.read_text(encoding="utf-8")
    assert "SW1A 1AA" in html and "Weather context report" in html
    assert "4.8" in html and "ECMWF IFS" in html


def test_existing_output_is_never_overwritten_or_requested(monkeypatch, tmp_path, capsys):
    requests = []
    offline_client(monkeypatch, requests)
    path = tmp_path / "existing.html"
    path.write_text("important", encoding="utf-8")
    assert cli.main(["report", "SW1A 1AA", "2023-11-02", "--output", str(path)]) == 4
    assert path.read_text() == "important"
    assert requests == []
    assert "already exists" in capsys.readouterr().err


def test_invalid_config_fails_before_api_calls(monkeypatch, tmp_path, capsys):
    requests = []
    offline_client(monkeypatch, requests)
    config = tmp_path / "bad.json"
    config.write_text('{"schema_version": 2, "wind_gust_kmh": 65, "rain_sum_mm": 20}')
    assert cli.main(["report", "SW1A 1AA", "2023-11-02", "--config", str(config)]) == 2
    assert requests == []
    assert "schema_version" in capsys.readouterr().err


def test_invalid_date_fails_before_api_calls(monkeypatch, tmp_path):
    requests = []
    offline_client(monkeypatch, requests)
    assert cli.main(["report", "SW1A 1AA", "2023-02-29", "--output", str(tmp_path / "r.html")]) == 2
    assert requests == []


def test_custom_thresholds_change_result_not_weather(monkeypatch, tmp_path):
    requests = []
    offline_client(monkeypatch, requests)
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"schema_version": 1, "wind_gust_kmh": 90, "rain_sum_mm": 90}))
    output = tmp_path / "custom.html"
    assert cli.main(["report", "SW1A 1AA", "2023-11-02", "--config", str(p), "--output", str(output)]) == 0
    html = output.read_text()
    assert "NO — illustrative triggers not met" in html
    assert "90 km/h" in html and "90 mm" in html
    assert len(requests) == 2


def test_weather_rate_limit_leaves_no_html(monkeypatch, tmp_path, capsys):
    def handler(req):
        if req.url.host == "api.postcodes.io":
            return httpx.Response(200, json=postcode_ok())
        return httpx.Response(429)

    class Client(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cli.httpx, "Client", Client)
    p = tmp_path / "not-created.html"
    assert cli.main(["report", "SW1A 1AA", "2023-11-02", "--output", str(p)]) == 3
    out, err = capsys.readouterr()
    assert out == "" and "rate limit" in err
    assert not p.exists()


def test_output_failure_returns_error_without_crashing(monkeypatch, tmp_path, capsys):
    requests = []
    offline_client(monkeypatch, requests)
    p = tmp_path / "does-not-exist" / "report.html"
    assert cli.main(["report", "SW1A 1AA", "2023-11-02", "--output", str(p)]) == 4
    assert "Output error:" in capsys.readouterr().err
    assert not p.exists()
