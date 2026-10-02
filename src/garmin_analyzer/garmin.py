"""The only module that talks to the Garmin library.

Everything else uses GarminSession, so the library can be replaced without
touching the collector. See ADR 9: an account is linked by a person signing in
in their own browser; this module only exchanges the resulting ticket for
tokens. It never signs in with credentials, as Garmin blocks scripted sign-ins
and bans the IP address they come from.
"""

import re
from typing import Any, Self
from urllib.parse import urlencode

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
    HTTPError,
)

SSO_EMBED = "https://sso.garmin.com/sso/embed"
SIGN_IN_URL = "https://sso.garmin.com/sso/signin?" + urlencode(
    {
        "id": "gauth-widget",
        "embedWidget": "true",
        "gauthHost": SSO_EMBED,
        "service": SSO_EMBED,
        "source": SSO_EMBED,
        "redirectAfterAccountLoginUrl": SSO_EMBED,
        "redirectAfterAccountCreationUrl": SSO_EMBED,
    }
)
TICKET = re.compile(r"ST-[A-Za-z0-9-]+")


class LinkError(Exception):
    """The pasted address held no usable ticket, or Garmin refused it."""


class RelinkRequired(Exception):
    """Garmin no longer accepts the stored tokens; the user has to link again."""


class GarminError(Exception):
    """A request to Garmin failed; other requests may still work."""


class RateLimited(GarminError):
    """Garmin asked us to slow down. Stop and try again later."""


def extract_ticket(pasted: str) -> str:
    """Find the single-use ticket in the address copied after signing in."""
    match = TICKET.search(pasted)
    if match is None:
        raise LinkError("no ticket found; paste the full address shown after signing in")
    return match.group(0)


class GarminSession:
    """An authenticated connection to one Garmin account."""

    def __init__(self, api: Garmin) -> None:
        self.api = api

    @classmethod
    def from_ticket(cls, pasted: str) -> Self:
        """Link an account: exchange the ticket from a browser sign-in for tokens."""
        ticket = extract_ticket(pasted)
        exchange = Garmin()
        try:
            # Private in the library: the call its own widget login ends with.
            exchange.client._exchange_service_ticket(ticket, service_url=SSO_EMBED)
        except (GarminConnectAuthenticationError, GarminConnectConnectionError) as error:
            raise LinkError(
                "Garmin refused the ticket; it may have expired or been used already"
            ) from error
        return cls.from_tokens(exchange.client.dumps())

    @classmethod
    def from_tokens(cls, tokens: str) -> Self:
        """Resume from stored tokens. The library refreshes them when they are due."""
        # No credentials are passed, so the library cannot fall back to a
        # scripted sign-in when the tokens are rejected; it raises instead.
        api = Garmin()
        try:
            api.login(tokenstore=tokens)
        except GarminConnectAuthenticationError as error:
            raise RelinkRequired(str(error)) from error
        return cls(api)

    def tokens(self) -> str:
        """The current tokens as JSON.

        A refresh can replace the refresh token, so store this again after
        every use of the session.
        """
        tokens: str = self.api.client.dumps()
        return tokens

    def call(self, method: str, *args: Any) -> Any:
        """Call a read method of the library, such as get_sleep_data."""
        if not method.startswith(("get_", "count_", "download_")):
            raise ValueError(f"{method} is not a read method")
        try:
            return getattr(self.api, method)(*args)
        except GarminConnectAuthenticationError as error:
            raise RelinkRequired(str(error)) from error
        except GarminConnectTooManyRequestsError as error:
            raise RateLimited(str(error)) from error
        except (GarminConnectConnectionError, HTTPError) as error:
            raise GarminError(str(error)) from error

    def download_original(self, activity_id: str) -> bytes:
        """The recording of an activity as the device uploaded it, in an archive."""
        content: bytes = self.call(
            "download_activity", activity_id, Garmin.ActivityDownloadFormat.ORIGINAL
        )
        return content
