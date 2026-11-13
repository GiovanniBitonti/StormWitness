"""StormWitness CLI: postcode lookup, historical weather and offline HTML report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections.abc import Sequence

import httpx

from stormwitness import __version__
from stormwitness.report import render_report
from stormwitness.review import ReviewConfigError, load_thresholds
from stormwitness.postcodes import (
    InvalidPostcodeError,
    PostcodeDataError,
    PostcodeNotFoundError,
    PostcodeServiceError,
    lookup_postcode,
)
from stormwitness.weather import (
    LOCAL_ZONE,
    HISTORICAL_MODEL,
    TIMEZONE,
    InvalidIncidentDateError,
    WeatherDataError,
    WeatherServiceError,
    fetch_historical_weather,
    parse_incident_date,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stormwitness",
        description="Local UK postcode and historical-weather evaluation CLI with HTML reporting.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    lookup = commands.add_parser("lookup", help="Resolve an exact UK postcode (Increment 1)")
    lookup.add_argument("postcode", help='Full postcode, e.g. "SW1A 1AA"')
    weather = commands.add_parser("weather", help="Postcode + historical IFS hourly/daily weather")
    weather.add_argument("postcode", help='Full postcode, e.g. "SW1A 1AA"')
    weather.add_argument("date", help="Completed UK calendar day, YYYY-MM-DD")
    report = commands.add_parser("report", help="Generate a local one-page HTML weather context report")
    report.add_argument("postcode", help='Full postcode, e.g. "SW1A 1AA"')
    report.add_argument("date", help="Completed UK calendar day, YYYY-MM-DD")
    report.add_argument(
        "--output", default="stormwitness_report.html", metavar="FILE",
        help="Output HTML file (created only if it does not exist)",
    )
    report.add_argument(
        "--config", metavar="JSON", help="Optional versioned illustrative threshold JSON",
    )
    args = parser.parse_args(argv)

    # Reject invalid date before spending a Postcodes.io request.
    if args.command in ("weather", "report"):
        try:
            parse_incident_date(args.date)
            if args.command == "report":
                thresholds = load_thresholds(args.config)
                target = Path(args.output).expanduser()
                if target.exists():
                    print(f"Output error: file already exists: {target}", file=sys.stderr)
                    return 4
        except (InvalidIncidentDateError, ReviewConfigError) as exc:
            print(f"Input error: {exc}", file=sys.stderr)
            return 2

    try:
        with httpx.Client(
            timeout=httpx.Timeout(8.0),
            follow_redirects=False,
            headers={"User-Agent": f"StormWitness/{__version__} (local evaluation)"},
        ) as client:
            location = lookup_postcode(args.postcode, client=client)
            if args.command in ("weather", "report"):
                result = fetch_historical_weather(
                    location.latitude, location.longitude, args.date, client=client
                )
    except (InvalidPostcodeError, PostcodeNotFoundError, InvalidIncidentDateError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    except (PostcodeServiceError, PostcodeDataError) as exc:
        print(f"Lookup error: {exc}", file=sys.stderr)
        return 3
    except (WeatherServiceError, WeatherDataError) as exc:
        print(f"Weather error: {exc}", file=sys.stderr)
        return 3

    if args.command == "report":
        document = render_report(location, result, thresholds)
        created = False
        try:
            with target.open("x", encoding="utf-8") as output:
                created = True
                output.write(document)
        except OSError as exc:
            if created:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            print(f"Output error: {exc}", file=sys.stderr)
            return 4
        print(f"Report created: {target.resolve()}")
        return 0

    location_json = {
        "postcode": location.postcode,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "location_precision": "approximate postcode location",
        "source": "Postcodes.io",
    }
    if args.command == "lookup":
        print(json.dumps(location_json, indent=2))
        return 0

    payload = {
        "postcode_lookup": location_json,
        "incident_date": result.incident_date.isoformat(),
        "historical_weather": {
            "source": "Open-Meteo Historical Weather API",
            "model": HISTORICAL_MODEL,
            "timezone": TIMEZONE,
            "grid_cell": {
                "latitude": result.grid_latitude,
                "longitude": result.grid_longitude,
            },
            "daily": {
                "max_wind_gust_kmh": result.daily_max_gust_kmh,
                "rain_sum_mm": result.daily_rain_sum_mm,
            },
            "hourly_units": {"wind_gust": "km/h", "rain": "mm"},
            "hourly_rain_definition": "precipitation during the preceding hour",
            "hours_returned": len(result.hourly),
            "missing_gust_hours": result.missing_gust_hours,
            "missing_rain_hours": result.missing_rain_hours,
            "hourly": [
                {
                    "time_utc": hour.timestamp_utc.isoformat().replace("+00:00", "Z"),
                    "time_uk": hour.timestamp_utc.astimezone(LOCAL_ZONE).isoformat(timespec="minutes"),
                    "wind_gust_kmh": hour.wind_gust_kmh,
                    "rain_mm": hour.rain_mm,
                }
                for hour in result.hourly
            ],
        },
        "interpretation": "Modelled context only; not a site measurement or claims decision",
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
