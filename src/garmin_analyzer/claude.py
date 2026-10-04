"""Asking Claude for a report. The only module that imports the Anthropic library.

Nothing here reads the database or knows a user: it gets a key, the
instructions and the figures as text, and gives back what Claude wrote. Neither
the figures nor the key are ever logged. See ADR 21.
"""

import logging
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

MAX_TOKENS = 16_000
# A report takes up to a minute or two; the page waits for it without a request open.
# Twice this, for the second try, stays under coach.PENDING_TIMEOUT.
TIMEOUT_SECONDS = 300
# Lets Anthropic answer with another model when the one asked for declines.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeError(Exception):
    """No report came back. The message is a sentence for the page, without a full stop."""

    # Whether Anthropic charges for the request all the same.
    billed = False


class Unusable(ClaudeError):
    """Claude answered, so the request is paid for, but not with a report."""

    billed = True


class PlannedDay(BaseModel):
    day: str = Field(description="The weekday and date, such as Monday 5 October")
    session: str = Field(description="What to do: the sport, how long and how hard, or rest")
    reason: str = Field(description="One sentence on why this fits the day")


class Report(BaseModel):
    """What Claude is asked to answer with. Stored as it is and shown as text."""

    summary: str = Field(description="Two or three sentences: how things stand right now")
    recovery: str = Field(description="Sleep, HRV, resting heart rate, stress and body battery")
    training: str = Field(description="Load, how the weeks were filled, fitness and its trend")
    goals: str = Field(description="Each weekly goal and each event to come, and how it looks")
    week: list[PlannedDay] = Field(description="The seven days from tomorrow, one entry a day")
    watch: list[str] = Field(description="Things to keep an eye on, if any; may be empty")


@dataclass(frozen=True)
class Written:
    report: Report
    # The model that answered, which can be another one than was asked for.
    model: str
    input_tokens: int
    output_tokens: int


def make_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=1)


def write_report(api_key: str, model: str, system: str, figures: str) -> Written:
    """Have Claude write a report on the figures. Raises ClaudeError when it does not."""
    client = make_client(api_key)
    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": figures}],
            output_format=Report,
            output_config={"effort": "medium"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError, anthropic.PermissionDeniedError:
        raise ClaudeError("Anthropic does not accept the API key") from None
    except anthropic.RateLimitError:
        raise ClaudeError(
            "Anthropic takes no more requests for this API key right now; try again later"
        ) from None
    except anthropic.BadRequestError as error:
        # Says what was wrong with the request, such as a model that does not
        # exist; it does not repeat what was sent.
        log.warning("Anthropic refused a request for a report: %s", error.message)
        if "credit balance" in error.message:
            raise ClaudeError("the Anthropic account of this API key has no credit left") from None
        raise ClaudeError("Anthropic refused the request") from None
    except anthropic.NotFoundError as error:
        log.warning("Anthropic does not know what was asked for: %s", error.message)
        raise ClaudeError("Anthropic does not know the model this instance asks for") from None
    except anthropic.APIStatusError as error:
        raise ClaudeError(f"Anthropic could not answer (status {error.status_code})") from None
    except anthropic.APIConnectionError:
        raise ClaudeError("Anthropic could not be reached") from None
    except ValueError:
        # An answer that was cut off or is not in the shape asked for.
        raise Unusable("the answer of Claude could not be read") from None
    if response.stop_reason == "refusal":
        raise Unusable("Claude declined to write a report on these figures")
    report = response.parsed_output
    if response.stop_reason == "max_tokens" or report is None:
        raise Unusable("the answer of Claude could not be read")
    return Written(
        report, response.model, response.usage.input_tokens, response.usage.output_tokens
    )
