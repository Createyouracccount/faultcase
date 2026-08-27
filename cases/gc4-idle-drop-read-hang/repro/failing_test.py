#!/usr/bin/env python3
"""Golden failing test for gc4-idle-drop-read-hang.

Exit 0: scenario passes (expected only after candidate.patch is applied).
Exit 1: scenario fails — observed_signature.json is written for the verifier.
Exit 2: harness error (never conflated with a scenario failure).

The mock stalls the first call to GET /reports/daily (connection open, zero
bytes sent — the classic silently-dropped keep-alive symptom) and serves the
report on the second call. Correct client code must bound the wait with a
timeout and retry. Unpatched code has no timeout, so the call blocks forever
in ``socket.recv``; a 10s watchdog captures the hung thread's stack and turns
the hang into a frozen, comparable failure signature ("faultcase.Hang") —
per the verifier contract, a hang must never be a silent TIMEOUT.
"""
import json
import os
import sys
import threading
import traceback

BUNDLE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BUNDLE)

from app import client  # noqa: E402
from app.mock_server import start_mock  # noqa: E402

WATCHDOG_SECONDS = 10


def hang_signature(worker_ident):
    frame = sys._current_frames().get(worker_ident)
    frames = []
    while frame is not None:  # innermost -> outermost
        module = frame.f_globals.get("__name__", "?")
        frames.append([module, frame.f_code.co_name])
        frame = frame.f_back
    frames.reverse()  # match traceback convention: outermost -> innermost
    return {
        "exception_type": "faultcase.Hang",
        "message": f"call did not return within {WATCHDOG_SECONDS}s "
                   "(hung stack captured by watchdog)",
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

    result = {}

    def call():
        try:
            result["report"] = client.fetch_report(f"http://127.0.0.1:{port}")
        except Exception as exc:  # post-patch path may raise on real defects
            result["error"] = exc

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(WATCHDOG_SECONDS)

    out_path = os.environ.get(
        "FAULTCASE_OBSERVED",
        os.path.join(os.getcwd(), "observed_signature.json"),
    )

    try:
        if worker.is_alive():
            signature = hang_signature(worker.ident)
            with open(out_path, "w") as f:
                json.dump(signature, f, indent=2)
            print("HANG reproduced: worker still blocked after "
                  f"{WATCHDOG_SECONDS}s; stack captured:")
            for module, func in signature["frames"]:
                print(f"  {module}.{func}")
            return 1

        if "error" in result:
            exc = result["error"]
            frames = []
            for frame, _lineno in traceback.walk_tb(exc.__traceback__):
                frames.append([frame.f_globals.get("__name__", "?"),
                               frame.f_code.co_name])
            exc_type = type(exc)
            type_name = (exc_type.__qualname__
                         if exc_type.__module__ in (None, "builtins")
                         else f"{exc_type.__module__}.{exc_type.__qualname__}")
            with open(out_path, "w") as f:
                json.dump({"exception_type": type_name, "message": str(exc),
                           "frames": frames,
                           "python": sys.version.split()[0]}, f, indent=2)
            print(f"FAIL: unexpected exception: {type_name}: {exc}")
            return 1

        expected = fixture["expected_report"]
        if result.get("report") != expected:
            print(f"FAIL: report mismatch: {result.get('report')!r} != {expected!r}")
            return 1
        print("OK: stalled first attempt was timed out and retried; report fetched")
        return 0
    finally:
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
