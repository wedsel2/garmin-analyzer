"""Tests for the wrapper around the Anthropic library. Nothing here reaches Anthropic:
the library gets a transport that answers from the test."""

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from garmin_analyzer import claude
from garmin_analyzer.claude import ClaudeError

KEY = "sk-ant-test"
REPORT = {
    "summary": "You are doing fine.",
    "recovery": "Sleep is steady.",
    "training": "Load is in range.",
    "goals": "On track.",
    "week": [{"day": "Monday 5 October", "session": "Rest", "reason": "After a long run."}],
    "watch": [],
}

Handler = Callable[[httpx2.Request], httpx2.Response]


def message(text: str, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}] if text else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 340},
    }


def failure(status: int, kind: str, text: str) -> httpx2.Response:
    return httpx2.Response(status, json={"type": "error", "error": {"type": kind, "message": text}})


@pytest.fixture
def answer(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[httpx2.Request]]:
    """Make Anthropic answer with what a handler gives; returns the requests it got."""

    def install(handler: Handler) -> list[httpx2.Request]:
        requests: list[httpx2.Request] = []

        def handle(request: httpx2.Request) -> httpx2.Response:
            requests.append(request)
            return handler(request)

        def make_client(api_key: str) -> anthropic.Anthropic:
            return anthropic.Anthropic(
                api_key=api_key,
                max_retries=0,
                http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handle)),
            )

        monkeypatch.setattr(claude, "make_client", make_client)
        return requests

    return install


def test_a_report_comes_back_in_the_shape_asked_for(
    answer: Callable[[Handler], list[httpx2.Request]],
) -> None:
    requests = answer(lambda request: httpx2.Response(200, json=message(json.dumps(REPORT))))

    written = claude.write_report(KEY, "claude-opus-5-5", "Be a coach.", "The figures.")

    assert written.report.summary == "You are doing fine."
    assert written.report.week[0].session == "Rest"
    assert (written.model, written.input_tokens, written.output_tokens) == (
        "claude-opus-5-5",
        1200,
        340,
    )
    [request] = requests
    assert request.headers["x-api-key"] == KEY
    assert claude.FALLBACK_BETA in request.headers["anthropic-beta"]
    body = json.loads(request.content)
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "Be a coach."
    assert body["messages"] == [{"role": "user", "content": "The figures."}]
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize(
    ("response", "sentence"),
    [
        (failure(401, "authentication_error", "invalid x-api-key"), "does not accept the API key"),
        (failure(403, "permission_error", "not allowed"), "does not accept the API key"),
        (failure(429, "rate_limit_error", "slow down"), "no more requests"),
        (
            failure(400, "invalid_request_error", "Your credit balance is too low"),
            "no credit left",
        ),
        (failure(400, "invalid_request_error", "model: no such model"), "refused the request"),
        (failure(404, "not_found_error", "model: claude-opus-9"), "does not know the model"),
        (failure(529, "overloaded_error", "busy"), "could not answer \\(status 529\\)"),
        (httpx2.Response(200, json=message("", "refusal")), "declined"),
        (httpx2.Response(200, json=message('{"summary": "cut', "max_tokens")), "could not be read"),
        (httpx2.Response(200, json=message('{"summary": "only this"}')), "could not be read"),
    ],
)
def test_no_report_gives_a_sentence_for_the_page(
    answer: Callable[[Handler], list[httpx2.Request]], response: httpx2.Response, sentence: str
) -> None:
    answer(lambda request: response)

    with pytest.raises(ClaudeError, match=sentence):
        claude.write_report(KEY, "claude-opus-5-5", "Be a coach.", "The figures.")


@pytest.mark.parametrize(
    ("response", "billed"),
    [
        (failure(401, "authentication_error", "invalid x-api-key"), False),
        (httpx2.Response(200, json=message("", "refusal")), True),
        (httpx2.Response(200, json=message('{"summary": "cut', "max_tokens")), True),
    ],
)
def test_only_an_answer_is_paid_for(
    answer: Callable[[Handler], list[httpx2.Request]], response: httpx2.Response, billed: bool
) -> None:
    answer(lambda request: response)

    with pytest.raises(ClaudeError) as raised:
        claude.write_report(KEY, "claude-opus-5-5", "Be a coach.", "The figures.")

    assert raised.value.billed is billed


def test_an_unreachable_anthropic_is_said_so(
    answer: Callable[[Handler], list[httpx2.Request]],
) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    answer(refuse)

    with pytest.raises(ClaudeError, match="could not be reached"):
        claude.write_report(KEY, "claude-opus-5-5", "Be a coach.", "The figures.")


def test_the_client_waits_long_enough_and_tries_twice() -> None:
    client = claude.make_client(KEY)

    assert client.timeout == claude.TIMEOUT_SECONDS
    assert client.max_retries == 1
