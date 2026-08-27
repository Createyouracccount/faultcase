#!/usr/bin/env python3
"""Golden failing test for gc1-webhook-hmac-reserialized-body.

Exit 0: scenario passes (expected only after candidate.patch is applied).
Exit 1: scenario fails — observed_signature.json is written for the verifier.
Exit 2: harness error (never conflated with a scenario failure).

This test plays the webhook SENDER: it signs a raw body with the local test
secret using Stripe's v1 scheme (HMAC-SHA256 over "{t}.{raw_body}") and POSTs
it to the customer's Flask app via the test client — zero network. The raw
body deliberately contains non-canonical JSON (double spaces), which any
parse-then-re-dump round trip is guaranteed to alter. Signing happens at test
runtime, so the 300s timestamp tolerance never bites: no clock dependence.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import traceback

BUNDLE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BUNDLE)

from app.webhook_app import WEBHOOK_SECRET, app  # noqa: E402

RAW_BODY = (
    b'{"id": "evt_faultcase_1",  "object": "event",'
    b'  "api_version": "2023-10-16",'
    b'  "type": "payment_intent.succeeded",'
    b'  "data": {"object": {"id": "pi_1001",  "object": "payment_intent",'
    b'  "amount": 4200,  "currency": "usd"}}}'
)


def sign(raw_body, secret):
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode() + raw_body
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def observed_signature(exc):
    frames = []
    for frame, _lineno in traceback.walk_tb(exc.__traceback__):
        module = frame.f_globals.get("__name__", "?")
        frames.append([module, frame.f_code.co_name])
    exc_type = type(exc)
    if exc_type.__module__ in (None, "builtins"):
        type_name = exc_type.__qualname__
    else:
        type_name = f"{exc_type.__module__}.{exc_type.__qualname__}"
    return {
        "exception_type": type_name,
        "message": str(exc),
        "frames": frames,
        "python": sys.version.split()[0],
    }


def main():
    app.testing = True  # unhandled view exceptions propagate to the sender
    client = app.test_client()
    header = sign(RAW_BODY, WEBHOOK_SECRET)

    try:
        resp = client.post(
            "/webhook",
            data=RAW_BODY,
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": header,
            },
        )
    except Exception as exc:
        out_path = os.environ.get(
            "FAULTCASE_OBSERVED",
            os.path.join(os.getcwd(), "observed_signature.json"),
        )
        with open(out_path, "w") as f:
            json.dump(observed_signature(exc), f, indent=2)
        traceback.print_exc()
        return 1

    if resp.status_code != 200:
        print(f"FAIL: webhook returned {resp.status_code}: {resp.get_data(as_text=True)!r}")
        return 1
    body = resp.get_json()
    if body.get("type") != "payment_intent.succeeded":
        print(f"FAIL: unexpected response body: {body!r}")
        return 1
    print("OK: signed webhook with non-canonical body verified and processed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
