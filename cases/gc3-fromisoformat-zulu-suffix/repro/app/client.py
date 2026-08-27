"""Order detail client, reconstructed from the customer's integration code.

The vendor API emits ISO-8601 timestamps with a ``Z`` suffix (as virtually
every JSON API does). ``datetime.fromisoformat`` only learned to parse ``Z``
in Python 3.11 (cpython #80010), so this code works on the developer's laptop
and crashes in the customer's 3.10 production runtime.
"""
from datetime import datetime

import requests


def fetch_order(base_url, order_id):
    resp = requests.get(f"{base_url}/orders/{order_id}", timeout=10)
    resp.raise_for_status()
    order = resp.json()["order"]
    order["created_at"] = datetime.fromisoformat(order["created_at"])
    return order
