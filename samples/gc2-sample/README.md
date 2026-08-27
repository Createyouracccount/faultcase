# faultcase sample bundle — urllib3 retry crash (real bug: urllib3 #2092)

This is what faultcase returns when you send it a support ticket. Everything
here was generated from the ticket in `original_ticket/` — read that first:
a customer's nightly order sync started crashing with a confusing `ValueError`
after the vendor's API had a 502 incident. "Is this your bug or ours?"

The bundle answers with executable evidence: **customer-code bug, latent since
2020, triggered by the vendor's 502s.** One-line fix, machine-verified.

## What's inside

```text
original_ticket/   what the customer sent (ticket, error.log, versions, snippet)
repro/
  Dockerfile              digest-pinned python:3.11-slim — offline-reproducible
  requirements.lock       hash-locked deps (requests 2.31.0, urllib3 1.26.18)
  app/client.py           customer code, reconstructed
  app/mock_server.py      scripted mock API: answers 502, 502, then 200
  failing_test.py         fails pre-patch with the customer's exact signature
  failure_signature.json  exception type + message regex + stack frames
fix/
  candidate.patch         method_whitelist -> allowed_methods (one line)
  patch_target            customer_code
```

## Run it (Docker required)

Reproduce the customer's crash — three times, identically:

```bash
cd repro
docker build -t faultcase-sample .
docker run --rm --network none faultcase-sample   # exits 1: the exact ValueError
```

Expected output (every run, identically — this is the frozen signature):

```text
Traceback (most recent call last):
  File "/bundle/failing_test.py", line 51, in main
    orders = client.fetch_orders(f"http://127.0.0.1:{port}")
  File "/bundle/app/client.py", line 35, in fetch_orders
    resp = session.get(f"{base_url}/orders", timeout=10)
  ...
  File "/usr/local/lib/python3.11/site-packages/urllib3/connectionpool.py", line 884, in urlopen
    retries = retries.increment(method, url, response=response, _pool=self)
  File "/usr/local/lib/python3.11/site-packages/urllib3/util/retry.py", line 338, in new
    return type(self)(**params)
  File "/bundle/app/client.py", line 18, in __init__
    super().__init__(*args, **kwargs)
  File "/usr/local/lib/python3.11/site-packages/urllib3/util/retry.py", line 265, in __init__
    raise ValueError(
ValueError: Using both 'allowed_methods' and 'method_whitelist' together is not allowed. Instead only use 'allowed_methods'
```

Apply the fix and watch the same scenario pass:

```bash
cd ..
git apply fix/candidate.patch     # or: patch -p1 < fix/candidate.patch
cd repro
docker build -t faultcase-sample-fixed .
docker run --rm --network none faultcase-sample-fixed   # exits 0: orders fetched
```

Or let the verifier do the full protocol (3x pre-patch fail with signature
match, 3x post-patch pass, exit code = verdict):

```bash
pip install faultcase
faultcase-verify . --runner docker
```

## Why this beats a written answer

- The failing test IS the diagnosis — `Retry.new()` re-constructs the policy
  passing `allowed_methods`, the customer's subclass injects the deprecated
  `method_whitelist`, urllib3 raises. Staging never crashed because staging
  never returned a 502.
- The mock server scripts the trigger (502, 502, 200) — no real API, no
  credentials, no flakiness. `--network none` proves it.
- The patch can't cheat: the verifier rejects any patch that touches the test,
  fixture, or signature.

Want one of these for a real ticket from your queue? Send an anonymized
ticket + error log + SDK versions — bundle back within 48h. If it can't be
reproduced from what you send, you get a precise missing-info list, not
guesses.
