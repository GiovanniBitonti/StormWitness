"""All tests here are offline: HTTPX MockTransport never contacts the API."""

import json

import httpx
import pytest

from stormwitness.postcodes import (
    InvalidPostcodeError,
    PostcodeDataError,
    PostcodeNotFoundError,
    PostcodeServiceError,
    lookup_postcode,
    normalize_postcode,
)


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=1.0)


def successful_response(*, latitude=51.501, longitude=-0.141, postcode="SW1A 1AA"):
    return {"status": 200, "result": {
        "postcode": postcode, "latitude": latitude, "longitude": longitude
    }}


@pytest.mark.parametrize("text", ["SW1A 1AA", "sw1a1aa", " SW1A\t1aa "])
def test_normalizes_input_and_reads_coordinates(text):
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == "https://api.postcodes.io/postcodes/SW1A1AA"
        return httpx.Response(200, json=successful_response())

    with make_client(handler) as client:
        location = lookup_postcode(text, client=client)
    assert location.postcode == "SW1A 1AA"
    assert (location.latitude, location.longitude) == (51.501, -0.141)


@pytest.mark.parametrize("text", ["", " ", "X", "../thing", "SW1A/1AA", "SW1A 1AA?"])
def test_rejects_invalid_input_without_http(text):
    def handler(request):
        pytest.fail("A bad postcode should not cause an HTTP request")

    with make_client(handler) as client:
        with pytest.raises(InvalidPostcodeError):
            lookup_postcode(text, client=client)


def test_404_is_not_found_even_when_terminated_data_exists():
    def handler(_):
        return httpx.Response(404, json={"status": 404, "terminated": {"postcode": "SW1A 1AA"}})

    with make_client(handler) as client:
        with pytest.raises(PostcodeNotFoundError):
            lookup_postcode("SW1A 1AA", client=client)


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_non_200_non_404_status_is_service_error(status):
    with make_client(lambda _: httpx.Response(status)) as client:
        with pytest.raises(PostcodeServiceError, match=f"HTTP {status}"):
            lookup_postcode("SW1A 1AA", client=client)


def test_network_timeout_has_clear_error():
    def handler(request):
        raise httpx.ReadTimeout("simulated", request=request)

    with make_client(handler) as client:
        with pytest.raises(PostcodeServiceError, match="timed out"):
            lookup_postcode("SW1A 1AA", client=client)


def test_network_connection_error_has_clear_error():
    def handler(request):
        raise httpx.ConnectError("simulated", request=request)

    with make_client(handler) as client:
        with pytest.raises(PostcodeServiceError, match="Could not reach"):
            lookup_postcode("SW1A 1AA", client=client)


@pytest.mark.parametrize("payload", [
    "not json",
    json.dumps({"status": 200, "result": None}),
    json.dumps({"status": 500, "result": {}}),
])
def test_unexpected_response_is_data_error(payload):
    with make_client(lambda _: httpx.Response(200, text=payload)) as client:
        with pytest.raises(PostcodeDataError):
            lookup_postcode("SW1A 1AA", client=client)


@pytest.mark.parametrize("coordinate", [None, True, "51.5", float("nan"), 100.0])
def test_invalid_coordinates_are_rejected(coordinate):
    with make_client(
        lambda _: httpx.Response(200, text=json.dumps(successful_response(latitude=coordinate)))
    ) as client:
        with pytest.raises(PostcodeDataError):
            lookup_postcode("SW1A 1AA", client=client)


def test_very_large_provider_coordinate_is_a_controlled_data_error():
    # Float conversion of an unbounded JSON integer can raise OverflowError.
    body = successful_response(latitude=10 ** 1000)
    with make_client(lambda _: httpx.Response(200, json=body)) as client:
        with pytest.raises(PostcodeDataError, match="invalid latitude"):
            lookup_postcode("SW1A 1AA", client=client)


def test_different_postcode_in_response_is_rejected():
    with make_client(
        lambda _: httpx.Response(200, json=successful_response(postcode="EC1A 1BB"))
    ) as client:
        with pytest.raises(PostcodeDataError, match="different postcode"):
            lookup_postcode("SW1A 1AA", client=client)


def test_normalize_postcode_does_not_claim_full_grammar_validation():
    assert normalize_postcode("ABCDE") == "ABCDE"
