# faultcase

Turn API support tickets into **runnable failure reproduction bundles** with
deterministic verification.

Feed it a customer ticket + error log + SDK versions. Get back an artifact an
engineer can run — not a chatbot answer:

```text
repro/
  Dockerfile              # digest-pinned, offline-reproducible environment
  requirements.lock       # hash-locked dependencies
  failing_test.py         # fails with the customer's exact failure signature
  fixture.json            # scripted mock server (the only network authority)
  failure_signature.json  # exception type + message regex + stack frames
analysis/
  likely_root_causes.md   # every claim cites evidence
fix/
  candidate.patch         # the fix
  verification.json       # machine evidence: 3/3 fail pre-patch, 3/3 pass post
```

## Install

```bash
pip install faultcase
```

## Verify a bundle

```bash
faultcase-verify path/to/bundle --runner docker
# exit 0: verified (pre-patch fails 3x with matching signature, post-patch passes 3x)
# exit 1: verification failed
# exit 2: infrastructure error (never conflated with a scenario failure)
```

`--against golden_signature.json` additionally checks that the bundle
reproduces the *same* bug as a reference signature.

## Run the pipeline

```bash
faultcase-run path/to/input -o out/ --adapter claude-cli --runner docker
# input/: customer_ticket.md, error.log, sdk_version.txt, code_snippet.py (optional)
```

If the inputs are insufficient to reproduce deterministically, the pipeline
refuses to guess and emits `missing_info.json` — a precise list of what to
collect and how.

## Principles

1. No reproduction, no root-cause claim.
2. The patch must not touch the test, fixture, or signature (anti-gaming).
3. Scored on artifact executability, not answer fluency.
