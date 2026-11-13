"""Report renderer: output safety, provenance, review outcome and offline HTML."""

from datetime import datetime, timezone
from html.parser import HTMLParser

import pytest

from stormwitness import __version__
from stormwitness.postcodes import PostcodeLocation
from stormwitness.report import render_report
from stormwitness.review import ReviewThresholds
from test_review import sample_weather


class HTMLInspect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.append((tag, dict(attrs)))


def build_html(**overrides):
    return render_report(
        PostcodeLocation("SW1A 1AA", 51.50101, -0.141563),
        sample_weather(**overrides), ReviewThresholds(),
        generated_at=datetime(2026, 11, 12, 21, 0, tzinfo=timezone.utc),
    )


def test_report_includes_actual_user_shared_metrics_and_illustrative_result():
    html = build_html()
    for expected in (
        "SW1A 1AA", "02 November 2023", "70.2", "17.9", "65 km/h", "20 mm",
        "YES — further weather review suggested", "Trigger met", "Below trigger",
        "Postcodes.io", "Open-Meteo Historical API", "ecmwf_ifs", "Europe/London",
        "51.50101, -0.14156", "51.49385, -0.16302", "12 Nov 2026, 21:00 UTC",
        f"StormWitness v{__version__}", "Rules schema v1", "not proof of damage",
        "not observations at the insured property", "illustrative", "claim validity",
    ):
        assert expected in html


def test_report_is_complete_self_contained_html():
    html = build_html()
    parsed = HTMLInspect()
    parsed.feed(html)
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert parsed.tags.count("html") == 1
    assert parsed.tags.count("main") == 1
    assert parsed.tags.count("style") == 1
    assert "@page" in html and "size:A4" in html
    assert "script" not in parsed.tags
    assert "iframe" not in parsed.tags
    assert "link" not in parsed.tags  # No CDN dependencies
    assert all(tag != "img" for tag in parsed.tags)
    assert all(not any(key.lower().startswith("on") for key in attrs) for _, attrs in parsed.attrs)
    assert len(html) < 20000


def test_html_escapes_untrusted_postcode():
    html = render_report(
        PostcodeLocation('<img src=x onerror="alert(1)">', 51.5, -0.14),
        sample_weather(), ReviewThresholds(),
        generated_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
    )
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert '<img src=x onerror="alert(1)">' not in html


def test_missing_values_render_as_missing_and_incomplete_status():
    html = build_html(daily_max_gust_kmh=None, daily_rain_sum_mm=None, missing_gust_hours=3)
    assert html.count("Not available") == 2
    assert "INCOMPLETE DATA" in html
    assert "manual weather review" in html
    assert "Insufficient data" in html
    assert "3 missing gust" in html


def test_below_threshold_makes_no_claim_of_safety():
    html = build_html(daily_max_gust_kmh=30, daily_rain_sum_mm=1)
    assert "NO — illustrative triggers not met" in html
    assert "does not rule out severe local weather or damage" in html


def test_naive_generated_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        render_report(
            PostcodeLocation("SW1A 1AA", 51.5, -0.1), sample_weather(),
            ReviewThresholds(), generated_at=datetime(2026, 11, 12),
        )


def test_utc_timestamp_converts_from_offset():
    from datetime import timedelta
    html = render_report(
        PostcodeLocation("SW1A 1AA", 51.5, -0.1), sample_weather(),
        ReviewThresholds(),
        generated_at=datetime(2026, 7, 1, 15, 5, tzinfo=timezone(timedelta(hours=1))),
    )
    assert "01 Jul 2026, 14:05 UTC" in html
