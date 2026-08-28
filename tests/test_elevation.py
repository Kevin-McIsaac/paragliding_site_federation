"""The DEM altitude lookup, driven entirely through its seams.

No test here touches the network: the live API is one batched GET whose
response shape is pinned by `saved_response`, and everything else - batching
past the 100-coordinate cap, the mapping back to coordinates, the empty
result on failure - is exercised through the injectable client and the
saved-response path.
"""

import json

import httpx
import pytest

from src.elevation import _BATCH, amsl_for_coordinates


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_coordinates_map_back_by_identity():
    def handler(request):
        params = request.url.params
        assert params.get_list("latitude") == ["-32.5", "-31.0"]
        assert params.get_list("longitude") == ["116.9", "116.7"]
        return httpx.Response(200, json={"elevation": [255.0, 436.0]})

    coords = [(-32.5, 116.9), (-31.0, 116.7)]
    assert amsl_for_coordinates(coords, client=make_client(handler)) == {
        (-32.5, 116.9): 255.0,
        (-31.0, 116.7): 436.0,
    }


def test_batches_past_the_api_limit():
    seen = []

    def handler(request):
        seen.append(len(request.url.params.get_list("latitude")))
        return httpx.Response(200, json={"elevation": [1.0] * seen[-1]})

    coords = [(-30.0 - i * 0.01, 115.0) for i in range(_BATCH + 1)]
    result = amsl_for_coordinates(coords, client=make_client(handler))

    assert seen == [_BATCH, 1]
    assert len(result) == _BATCH + 1


def test_an_api_failure_publishes_nothing():
    def handler(request):
        return httpx.Response(500)

    assert amsl_for_coordinates([(-32.5, 116.9)], client=make_client(handler)) == {}


def test_a_short_answer_is_a_failure_not_a_truncation():
    def handler(request):
        return httpx.Response(200, json={"elevation": [255.0]})

    assert amsl_for_coordinates([(-32.5, 116.9), (-31.0, 116.7)],
                                client=make_client(handler)) == {}


def test_the_offline_seam_answers_from_a_saved_response(tmp_path, monkeypatch):
    coords = [(-32.5, 116.9), (-31.0, 116.7)]
    path = tmp_path / "elevations.json"
    path.write_text(json.dumps({"-32.5,116.9": 255.0, "-31.0,116.7": 436.0}))
    monkeypatch.setenv("OPEN_METEO_ELEVATION_PATH", str(path))

    def explode(request):
        raise AssertionError("the network is not wanted when the seam is set")

    result = amsl_for_coordinates(coords, client=make_client(explode))

    assert result == {(-32.5, 116.9): 255.0, (-31.0, 116.7): 436.0}


def test_no_coordinates_means_no_call():
    def handler(request):
        raise AssertionError("no coordinates, no request")

    assert amsl_for_coordinates([], client=make_client(handler)) == {}