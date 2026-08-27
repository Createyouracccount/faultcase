#!/usr/bin/env python3
"""Golden failing test for gc3-fromisoformat-zulu-suffix.

Exit 0: scenario passes (expected only after candidate.patch is applied).
Exit 1: scenario fails — observed_signature.json is written for the verifier.
Exit 2: harness error (never conflated with a scenario failure).

The mock API serves an order whose created_at carries the ISO-8601 ``Z``
suffix. Correct client code must parse it to an aware UTC datetime. On the
bundle's pinned Python 3.10 runtime, unpatched code raises ValueError.
"""
import json
import os
import sys
import traceback

BUNDLE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BUNDLE)

from app import client  # noqa: E402
from app.mock_server import start_mock  # noqa: E402


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
    try:
        with open(os.path.join(BUNDLE, "fixture.json")) as f:
            fixture = json.load(f)
        server, port = start_mock(fixture)
    except Exception:
        traceback.print_exc()
        return 2

    try:
        order = client.fetch_order(f"http://127.0.0.1:{port}", "ord_1001")
    except Exception as exc:
        out_path = os.environ.get(
            "FAULTCASE_OBSERVED",
            os.path.join(os.getcwd(), "observed_signature.json"),
        )
        with open(out_path, "w") as f:
            json.dump(observed_signature(exc), f, indent=2)
        traceback.print_exc()
        return 1
    finally:
        server.shutdown()

    parsed = order["created_at"]
    expected_iso = fixture["expected_created_at_iso"]
    if parsed.isoformat() != expected_iso:
        print(f"FAIL: created_at parsed to {parsed.isoformat()!r}, expected {expected_iso!r}")
        return 1
    print("OK: Z-suffixed timestamp parsed to an aware UTC datetime")
    return 0


if __name__ == "__main__":
    sys.exit(main())
