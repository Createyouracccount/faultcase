"""Report export client, reconstructed from the customer's integration code.

The customer calls the vendor's report endpoint with no timeout. When the
connection stalls after the request is written (idle keep-alive dropped by a
middlebox, or a stalled upstream), ``requests`` blocks in ``socket.recv``
forever — nothing is thrown, the worker just never comes back.
"""
import requests


def fetch_report(base_url):
    resp = requests.get(f"{base_url}/reports/daily")
    resp.raise_for_status()
    return resp.json()["report"]
