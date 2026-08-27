"""Stripe webhook receiver, reconstructed from the customer's Flask service.

The customer verifies webhook signatures over ``json.dumps(request.get_json())``
— the *re-serialized* body. Stripe signs the raw bytes it sent; any whitespace,
key-order, or encoding difference introduced by the parse/re-dump round trip
makes the HMAC mismatch (stripe-python #424; documented cause in Stripe's
webhook signature docs).
"""
import json
import os

import stripe
from flask import Flask, request

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "whsec_faultcase_local_test")

app = Flask(__name__)


@app.post("/webhook")
def webhook():
    payload = json.dumps(request.get_json()).encode("utf-8")
    sig_header = request.headers["Stripe-Signature"]
    event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    return {"received": True, "type": event["type"]}
