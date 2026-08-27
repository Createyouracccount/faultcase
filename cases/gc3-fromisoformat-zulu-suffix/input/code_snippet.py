# Snippet the customer attached to ticket #5107. Paths and secrets redacted
# by faultcase intake scrubbing.
from datetime import datetime

import requests


def fetch_order(base_url, order_id):
    resp = requests.get(f"{base_url}/orders/{order_id}", timeout=10)
    resp.raise_for_status()
    order = resp.json()["order"]
    order["created_at"] = datetime.fromisoformat(order["created_at"])
    return order
