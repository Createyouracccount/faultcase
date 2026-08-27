# Snippet the customer attached to ticket #4977 (webhook endpoint, secrets
# redacted by faultcase intake scrubbing).
import json
import os

import stripe
from flask import Flask, request

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

app = Flask(__name__)


@app.post("/webhook")
def webhook():
    payload = json.dumps(request.get_json()).encode("utf-8")
    sig_header = request.headers["Stripe-Signature"]
    event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    return {"received": True, "type": event["type"]}
