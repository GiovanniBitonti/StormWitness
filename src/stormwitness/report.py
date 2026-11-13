"""Render a self-contained, printable one-page HTML weather context report.

No web framework, templates dependency, remote styles, or client JavaScript.
All external strings are HTML-escaped before interpolation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from stormwitness import __version__
from stormwitness.postcodes import PostcodeLocation
from stormwitness.review import ReviewThresholds, assess_weather
from stormwitness.weather import HistoricalWeather, HISTORICAL_MODEL, TIMEZONE


def _e(text: object) -> str:
    return escape(str(text), quote=True)


def _metric(value: float | None, unit: str) -> str:
    if value is None:
        return '<span class="unavailable">Not available</span>'
    return f"{value:,.1f}<small>{_e(unit)}</small>"


def _comparison(met: bool | None) -> str:
    if met is None:
        return "Insufficient data"
    return "Trigger met" if met else "Below trigger"


def render_report(
    location: PostcodeLocation,
    weather: HistoricalWeather,
    thresholds: ReviewThresholds,
    *,
    generated_at: datetime | None = None,
) -> str:
    """Produce a complete offline HTML file, with no side effects.

    `generated_at` is injectable for deterministic testing and auditability.
    """
    now = generated_at if generated_at is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("generated_at must be a timezone-aware datetime")
    now_utc = now.astimezone(timezone.utc)
    assessment = assess_weather(weather, thresholds)
    when = weather.incident_date.strftime("%d %B %Y")
    postcode = _e(location.postcode)
    outcome = "YES — further weather review suggested" if assessment.review_suggested else "NO — illustrative triggers not met"
    state_class = "incomplete" if assessment.data_incomplete else ("attention" if assessment.review_suggested else "below")
    state_tag = "INCOMPLETE DATA" if assessment.data_incomplete else ("REVIEW SUGGESTED" if assessment.review_suggested else "NO TRIGGERS MET")
    gust = _metric(weather.daily_max_gust_kmh, "km/h")
    rain = _metric(weather.daily_rain_sum_mm, "mm")
    # All externally provided values are escaped, including the reason string.
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>StormWitness | {postcode} | {_e(weather.incident_date.isoformat())}</title>
<style>
  :root {{ color-scheme: light; --navy:#122b40; --ink:#203446; --muted:#607286;
    --line:#dce4ea; --paper:#fff; --pale:#f4f7fa; --teal:#087c83; }}
  * {{ box-sizing:border-box; }}
  html {{ background:#e8eef2; }}
  body {{ margin:0; color:var(--ink); font:13px/1.46 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; }}
  .sheet {{ background:var(--paper); width:min(100%,800px); margin:24px auto; padding:30px 36px 25px;
    box-shadow:0 14px 40px rgba(19,41,56,.12); }}
  .brandline {{ display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--line);
    padding-bottom:14px; gap:16px; }}
  .brand {{ display:flex; align-items:center; gap:10px; color:var(--navy); font-size:16px; letter-spacing:.065em; font-weight:800; }}
  .brandmark {{ display:grid; place-items:center; width:32px; height:32px; background:var(--navy); color:white;
    font-size:18px; border-radius:7px; font-weight:800; }}
  .descriptor {{ font-size:10px; font-weight:700; letter-spacing:.13em; color:var(--muted); text-align:right; }}
  .intro {{ padding:19px 0 13px; display:flex; justify-content:space-between; align-items:end; gap:18px; }}
  .eyebrow {{ font-size:10px; font-weight:800; letter-spacing:.15em; color:var(--teal); text-transform:uppercase; }}
  h1 {{ margin:3px 0 5px; font-size:25px; line-height:1.12; letter-spacing:-.035em; color:var(--navy); }}
  .subline {{ margin:0; color:var(--muted); font-size:12px; }}
  .incident {{ min-width:156px; text-align:right; }}
  .incident strong {{ display:block; font-size:14px; color:var(--navy); }}
  .incident span {{ display:block; font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.09em; }}
  .decision {{ background:#fff5e9; border-left:4px solid #bf7513; border-radius:5px; padding:13px 16px; margin:11px 0 19px; }}
  .decision.below {{ background:#eaf5f2; border-color:#0c7c72; }}
  .decision.incomplete {{ background:#fff0e9; border-color:#b6573e; }}
  .decision .tag {{ font-size:10px; letter-spacing:.14em; font-weight:800; color:#935c14; }}
  .decision.below .tag {{ color:#096c63; }}
  .decision.incomplete .tag {{ color:#9f4b35; }}
  .decision h2 {{ margin:3px 0 3px; font-size:17px; line-height:1.3; color:var(--navy); }}
  .decision p {{ margin:0; color:#4e5862; font-size:11px; }}
  .section-title {{ margin:0 0 10px; display:flex; align-items:center; justify-content:space-between;
    color:var(--navy); font-size:13px; letter-spacing:.015em; font-weight:800; }}
  .section-title small {{ color:var(--muted); font-weight:500; font-size:10px; }}
  .metrics {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
  .metric {{ border:1px solid var(--line); border-radius:7px; padding:15px 17px 13px; break-inside:avoid; }}
  .metric .label {{ font-size:11px; font-weight:700; color:var(--muted); }}
  .metric .figure {{ font-size:28px; letter-spacing:-.055em; color:var(--navy); font-weight:800; line-height:1.35; margin-top:1px; }}
  .metric .figure small {{ font-size:12px; letter-spacing:0; margin-left:6px; font-weight:600; color:var(--muted); }}
  .metric .unavailable {{ font-size:17px; letter-spacing:0; }}
  .metric .rule {{ margin-top:9px; border-top:1px solid var(--line); padding-top:9px; font-size:11px; color:var(--muted); }}
  .metric .rule strong {{ color:var(--ink); }}
  .metric .result {{ font-size:10px; color:var(--teal); font-weight:800; margin-top:4px; }}
  .metric .result.alert {{ color:#a35e0f; }}
  .context {{ border:1px solid var(--line); border-radius:6px; padding:12px 15px; margin-top:16px; background:var(--pale); }}
  .context h3 {{ margin:0 0 4px; font-size:12px; color:var(--navy); }}
  .context p {{ margin:0; font-size:11px; color:#4d5d6b; }}
  .detail {{ margin-top:17px; padding-top:11px; border-top:1px solid var(--line); break-inside:avoid; }}
  .facts {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:11px 22px; }}
  .fact .key {{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }}
  .fact .value {{ font-size:11px; color:var(--ink); font-weight:700; overflow-wrap:anywhere; }}
  .notes {{ margin-top:17px; padding:12px 14px; border:1px solid #d5e3e4; background:#f2f8f8; border-radius:5px;
    break-inside:avoid; }}
  .notes strong {{ display:block; font-size:11px; color:#17666c; margin-bottom:3px; }}
  .notes p {{ margin:0; color:#425860; font-size:10.5px; line-height:1.45; }}
  .foot {{ border-top:1px solid var(--line); margin-top:17px; padding-top:11px; display:flex;
    justify-content:space-between; gap:18px; font-size:9px; color:var(--muted); }}
  .foot div {{ max-width:70%; }}
  .foot a {{ color:#315a71; text-decoration:none; }}
  .foot .id {{ text-align:right; flex:0 0 auto; }}
  @page {{ size:A4; margin:11mm; }}
  @media print {{
    html {{ background:white; }}
    body {{ font-size:11px; print-color-adjust:exact; -webkit-print-color-adjust:exact; }}
    .sheet {{ width:auto; max-width:none; margin:0; padding:0; box-shadow:none; }}
    .brandline {{ padding-bottom:10px; }}
    .intro {{ padding:13px 0 10px; }}
    .decision {{ margin:7px 0 13px; padding:10px 13px; }}
    .metric {{ padding:11px 14px; }}
    .context {{ margin-top:12px; padding:9px 12px; }}
    .detail {{ margin-top:12px; padding-top:9px; }}
    .notes {{ margin-top:12px; padding:10px 12px; }}
    .foot {{ margin-top:12px; }}
  }}
  @media (max-width:550px) {{
    .sheet {{ margin:0; padding:18px; }}
    .intro {{ align-items:start; }}
    h1 {{ font-size:21px; }}
    .metrics {{ gap:8px; }}
    .metric {{ padding:11px; }}
    .metric .figure {{ font-size:23px; }}
    .facts {{ gap:8px; }}
  }}
</style>
</head>
<body>
<main class="sheet" aria-label="StormWitness weather context report">
  <header class="brandline">
    <div class="brand"><div class="brandmark" aria-hidden="true">S</div> STORMWITNESS</div>
    <div class="descriptor">CLAIMS SUPPORT / WEATHER CONTEXT</div>
  </header>
  <section class="intro">
    <div><div class="eyebrow">Historical weather summary</div>
      <h1>Weather context report</h1>
      <p class="subline">UK postcode <strong>{postcode}</strong> &nbsp;·&nbsp; {_e(when)}</p></div>
    <div class="incident"><span>Incident date</span><strong>{_e(when)}</strong><span>UK local calendar day</span></div>
  </section>
  <section class="decision {state_class}" aria-label="Illustrative review outcome">
    <div class="tag">{state_tag} · ILLUSTRATIVE ONLY</div>
    <h2>{_e(outcome)}</h2>
    <p>{_e(assessment.reason)}</p>
  </section>
  <section aria-label="Modelled daily metrics">
    <h2 class="section-title">Daily weather indicators <small>ECMWF IFS · modelled estimates</small></h2>
    <div class="metrics">
      <article class="metric"><div class="label">Maximum 10 m wind gust</div>
        <div class="figure">{gust}</div>
        <div class="rule">Illustrative trigger <strong>≥ {thresholds.wind_gust_kmh:g} km/h</strong></div>
        <div class="result{' alert' if assessment.wind_trigger_met else ''}">{_comparison(assessment.wind_trigger_met)}</div>
      </article>
      <article class="metric"><div class="label">Total daily rainfall</div>
        <div class="figure">{rain}</div>
        <div class="rule">Illustrative trigger <strong>≥ {thresholds.rain_sum_mm:g} mm</strong></div>
        <div class="result{' alert' if assessment.rain_trigger_met else ''}">{_comparison(assessment.rain_trigger_met)}</div>
      </article>
    </div>
  </section>
  <section class="context" aria-label="Interpretation">
    <h3>How to use this result</h3>
    <p>The review flag identifies illustrative weather conditions for possible follow-up. A threshold being met does not establish damage; a threshold not being met does not exclude it. A handler must consider other evidence and claim-specific circumstances.</p>
  </section>
  <section class="detail" aria-label="Location and model provenance">
    <h2 class="section-title">Location &amp; data provenance</h2>
    <div class="facts">
      <div class="fact"><div class="key">Postcode location · Postcodes.io</div><div class="value">{location.latitude:.5f}, {location.longitude:.5f} (approx.)</div></div>
      <div class="fact"><div class="key">Weather model grid cell · Open-Meteo</div><div class="value">{weather.grid_latitude:.5f}, {weather.grid_longitude:.5f}</div></div>
      <div class="fact"><div class="key">Source &amp; model</div><div class="value">Open-Meteo Historical API · {_e(HISTORICAL_MODEL)}</div></div>
      <div class="fact"><div class="key">Coverage &amp; completeness</div><div class="value">{len(weather.hourly)} hours; {weather.missing_gust_hours} missing gust, {weather.missing_rain_hours} missing rain</div></div>
      <div class="fact"><div class="key">Weather calendar &amp; units</div><div class="value">{_e(TIMEZONE)} · km/h wind gust · mm rainfall</div></div>
      <div class="fact"><div class="key">Report generated (UTC)</div><div class="value">{_e(now_utc.strftime('%d %b %Y, %H:%M UTC'))}</div></div>
    </div>
  </section>
  <aside class="notes" aria-label="Evidence limitations">
    <strong>Important limitation — weather context, not proof of damage</strong>
    <p>These are historical gridded model estimates, not observations at the insured property. The postcode and weather grid-cell positions are approximate and may differ. The data cannot establish damage, causation, policy cover or claim validity. Rainfall is rain only (not snowfall); figures describe the selected UK calendar day.</p>
  </aside>
  <footer class="foot">
    <div><strong>Data attribution:</strong> Postcodes.io (<a href="https://postcodes.io">postcodes.io</a>) · Open-Meteo Historical Weather API (<a href="https://open-meteo.com">open-meteo.com</a>). Local evaluation only; review commercial-use terms before operational deployment.</div>
    <div class="id">StormWitness v{_e(__version__)}<br>Rules schema v{thresholds.schema_version}<br>One-day context report</div>
  </footer>
</main>
</body>
</html>
'''
