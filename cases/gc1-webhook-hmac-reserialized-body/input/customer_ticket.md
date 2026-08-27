# Ticket #4977 — Webhook signature verification always fails in our Flask app

**Product**: Payments webhooks (Python SDK)
**Severity**: High — we are missing payment events in production

Hello,

we cannot get webhook signature verification to work. Every single webhook
you send us fails with:

```
SignatureVerificationError: No signatures found matching the expected signature for payload
```

We copied the verification snippet from your docs. Our endpoint secret is
correct — we triple-checked it in the dashboard, regenerated it once, same
result. Test events from the CLI fail the same way.

We're on Flask. The relevant code is attached. We parse the JSON body and
pass it to `construct_event` together with the `Stripe-Signature` header.

Two questions:
1. Is your signature header being computed over something other than the JSON
   event? Your docs say HMAC-SHA256 over the payload.
2. Could this be a bug in the Python SDK version we use?

Currently we had to disable signature verification entirely (we know, bad) to
stop losing events. Please advise urgently.
