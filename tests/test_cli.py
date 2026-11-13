"""CLI tests patch lookup rather than making external HTTP requests."""

import json

from stormwitness import cli
from stormwitness.postcodes import PostcodeLocation, PostcodeNotFoundError


def test_cli_lookup_success(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "lookup_postcode",
        lambda postcode, *, client: PostcodeLocation("SW1A 1AA", 51.501, -0.141),
    )
    assert cli.main(["lookup", "SW1A 1AA"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    payload = json.loads(out)
    assert payload["postcode"] == "SW1A 1AA"
    assert payload["location_precision"] == "approximate postcode location"


def test_cli_lookup_not_found(monkeypatch, capsys):
    def not_found(postcode, *, client):
        raise PostcodeNotFoundError("not found")

    monkeypatch.setattr(cli, "lookup_postcode", not_found)
    assert cli.main(["lookup", "ZZ99 9ZZ"]) == 2
    assert "Input error" in capsys.readouterr().err
