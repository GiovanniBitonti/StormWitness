"""Small typed boundary around the Postcodes.io exact-postcode lookup endpoint.

No network call occurs at import time. Supplying the HTTPX client makes transport,
timeouts and retry policy the caller's responsibility and enables hermetic tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

import httpx

POSTCODES_URL = "https://api.postcodes.io/postcodes"


class PostcodeError(Exception):
    """Base class for postcode lookup failures."""


class InvalidPostcodeError(PostcodeError):
    """Input is blank or not plausible postcode text."""


class PostcodeNotFoundError(PostcodeError):
    """Postcodes.io has no record for the supplied postcode."""


class PostcodeServiceError(PostcodeError):
    """A network/HTTP error prevented a postcode lookup."""


class PostcodeDataError(PostcodeError):
    """The provider returned an unusable or unexpected response."""


@dataclass(frozen=True, slots=True)
class PostcodeLocation:
    """Approximate postcode-derived coordinates, not a property location."""

    postcode: str
    latitude: float
    longitude: float


def normalize_postcode(value: str) -> str:
    """Normalize harmless whitespace/case, but leave validity to Postcodes.io.

    A shape-only guard keeps invalid input and URL delimiters out of the request.
    It is intentionally not a full UK postcode grammar validator.
    """
    if not isinstance(value, str):
        raise InvalidPostcodeError("Postcode must be text")
    candidate = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[A-Z0-9]{5,7}", candidate, flags=re.ASCII):
        raise InvalidPostcodeError("Enter a full UK postcode (e.g. SW1A 1AA)")
    return candidate


def _coordinate(value: object, *, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise PostcodeDataError(f"Provider returned a missing or invalid {name}")
    try:
        coordinate = float(value)
    except (OverflowError, ValueError) as exc:
        raise PostcodeDataError(f"Provider returned a missing or invalid {name}") from exc
    if not math.isfinite(coordinate) or not low <= coordinate <= high:
        raise PostcodeDataError(f"Provider returned a missing or invalid {name}")
    return coordinate


def lookup_postcode(postcode: str, *, client: httpx.Client) -> PostcodeLocation:
    """Resolve one UK postcode using a real HTTPS GET via an injected client.

    There are no implicit retries (one user action -> at most one HTTP request).
    The caller should set finite timeouts on its HTTPX client.
    """
    normalized = normalize_postcode(postcode)
    try:
        response = client.get(f"{POSTCODES_URL}/{normalized}")
    except httpx.TimeoutException as exc:
        raise PostcodeServiceError("Postcodes.io request timed out") from exc
    except httpx.RequestError as exc:
        raise PostcodeServiceError("Could not reach Postcodes.io") from exc

    if response.status_code == 404:
        # Terminated postcodes may be returned in a 404 payload; do not
        # silently substitute historic locations for the incident date.
        raise PostcodeNotFoundError(f"Postcode not found: {normalized}")
    if response.status_code != 200:
        raise PostcodeServiceError(
            f"Postcodes.io returned HTTP {response.status_code}"
        )

    try:
        body = response.json()
    except (ValueError, UnicodeError) as exc:
        raise PostcodeDataError("Postcodes.io returned invalid JSON") from exc
    if not isinstance(body, dict) or body.get("status") != 200:
        raise PostcodeDataError("Postcodes.io returned an unexpected response")
    result = body.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("postcode"), str):
        raise PostcodeDataError("Postcodes.io returned an incomplete postcode result")

    try:
        returned = normalize_postcode(result["postcode"])
    except InvalidPostcodeError as exc:
        raise PostcodeDataError("Postcodes.io returned an invalid postcode") from exc
    if returned != normalized:
        raise PostcodeDataError("Postcodes.io returned a different postcode")

    latitude = _coordinate(result.get("latitude"), name="latitude", low=-90, high=90)
    longitude = _coordinate(result.get("longitude"), name="longitude", low=-180, high=180)
    # Use the provider's presentation of the postcode (usually with a space).
    return PostcodeLocation(
        postcode=result["postcode"], latitude=latitude, longitude=longitude
    )
