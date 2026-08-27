# Snippet the customer attached to ticket #4821 (their retry setup, unchanged
# since 2020). Paths and secrets redacted by faultcase intake scrubbing.
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class LegacyRetry(Retry):
    """Retry policy that also retries POSTs, per our ops runbook."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("method_whitelist", frozenset(["GET", "POST"]))
        super().__init__(*args, **kwargs)


def make_session():
    retry = LegacyRetry(
        total=3,
        backoff_factor=0,
        status_forcelist=[502, 503, 504],
    )
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
