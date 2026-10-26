import os
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

# The query parameter that carries an experiment unit's token to the brand's
# site, so its conversion postback can say who converted (POST /v1/conversions).
TOKEN_PARAM = "ciq_t"


def wrap_tracked_url(url: str, *, campaign_id: str, round_id: int, channel: str = "email", token: str | None = None,
                     contact_token: str | None = None) -> str:
    """The click-tracking link. `token`: an experiment unit's token (credited to
    the experiment, passed on to the brand's site); `contact_token`: the
    contact's own click token (marks them engaged; never passed on)."""
    base = os.environ["TRACK_CLICK_BASE_URL"].rstrip("/")
    tracked = f"{base}?url={quote(url, safe='')}&campaign_id={campaign_id}&round_id={round_id}&channel={channel}"
    if token:
        tracked += f"&t={token}"
    return f"{tracked}&k={contact_token}" if contact_token else tracked


def with_token(url: str, token: str) -> str:
    """The destination with the unit's token added (replacing one already there)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != TOKEN_PARAM] + [(TOKEN_PARAM, token)]
    return urlunsplit(parts._replace(query=urlencode(query)))
