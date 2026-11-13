# StormWitness — increment history and final review (12 November 2026)

## Increment 1 — postcode lookup (v0.1.0)

Added a small Python CLI, typed Postcodes.io adapter with injectable HTTPX client, finite timeout, strict response validation, offline pytest tests, versioning and an executable README. The user independently verified Python 3.12.16, 28 passing tests and successful live postcode lookup on a Mac. Coordinates are approximations, not premises locations.

## Increment 2 — historical weather (v0.2.0)

Added independent Open-Meteo integration using `ecmwf_ifs` (explicit historical model), hourly 10 m gust/rain and provider daily gust/rain totals. Validates dates, 23/24/25-hour UK days, Unix timestamps, unit metadata, grid coordinates, missingness, rate limits and HTTP failures. No retry or silent model fallback. The user confirmed 88 passing tests and real API values for 2023-11-02: 70.2 km/h peak gust, 17.9 mm daily rain and 24 complete hourly records.

## Increment 3 — illustrative review and HTML (v0.3.0)

Added versioned whole-file JSON threshold configuration, deterministic comparison of provider daily values, incomplete-data review rule, escaped offline single-file A4 HTML, explicit limitations, and exclusive output creation to avoid overwrites. The user reported 127 tests passed and **successful HTML generation** on a Mac. Scope stayed limited to a single calendar day without claim-level decisions or stored customer information.

## Increment 4 — release audit and documentation (v0.4.0)

Source audit of CLI, Postcodes.io and Open-Meteo adapters, review rules, HTML and tests. Reproduced and corrected two defects: (1) huge JSON numeric coordinates caused an uncaught `OverflowError`; (2) duplicate JSON threshold keys silently overrode values. Four additional offline test cases added (131 total passing in Python 3.13.5 authoring environment). Added root-generated-HTML and macOS metadata exclusions to `.gitignore`; refreshed README, status record, complete user-prompt transcript and technical write-up. The application commands, API request shape, review thresholds and report renderer have not changed.

Release verification complete: StormWitness v0.4.0 was successfully installed and tested on macOS with Python 3.12. All 131 automated tests passed, and the live HTML report was generated successfully.

## Assumptions and trade-offs

1. Evaluation/non-commercial prototype; no right to use the Open-Meteo free service for a commercial insurance workflow is presumed.
2. Current postcode approximation and 9 km model grid are **not** an insured-property measurement; historical postcode position could differ.
3. One completed UK date is intentionally simpler than a multi-day or timed storm event, but may miss overnight or adjacent-day conditions.
4. Strict units, timestamp and schema validation prevent silent data mismatches. Missing values trigger review instead of zero-fill; malformed responses abort the report.
5. Provider daily aggregations are authoritative for displayed daily figures; hourly rows support completeness and timestamps. No reaggregation/approximate substitution.
6. Controlled config requires explicit finite positive values and unique keys; illustrative defaults (65 km/h, 20 mm) are not industry standards.
7. No network retry/fallback, account, database, commercial deployment or claims decision: intentionally bounded, deterministic and offline-testable.
