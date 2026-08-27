"""Order sync client, reconstructed from the customer's integration code.

The customer follows a 2020-era ops runbook that forces POST retries via an
explicit whitelist on a Retry subclass. On urllib3 1.26.x the deprecated
``method_whitelist`` kwarg still works at construction time, so this code
passes review and smoke tests — it only breaks when a retry actually fires.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class LegacyRetry(Retry):
    """Retry policy that also retries POSTs, per the ops runbook."""

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


def fetch_orders(base_url):
    session = make_session()
    resp = session.get(f"{base_url}/orders", timeout=10)
    resp.raise_for_status()
    return resp.json()["orders"]
