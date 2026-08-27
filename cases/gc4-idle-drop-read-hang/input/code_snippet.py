# Snippet the customer attached to ticket #5230 follow-up (paths and secrets
# redacted by faultcase intake scrubbing).
import requests


def fetch_report(base_url):
    resp = requests.get(f"{base_url}/reports/daily")
    resp.raise_for_status()
    return resp.json()["report"]
