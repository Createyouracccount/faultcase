"""Versioned failure-signature comparison.

The comparator version lives inside failure_signature.json, so bundles are
always judged by the rules they were frozen under — new comparator versions
never silently re-judge old bundles.
"""
import re


def match_v1(expected, observed):
    """Return (matched: bool, reasons: list[str]).

    v1 rules:
    - exception_type: exact match
    - message_regex: re.search against the observed message
    - top_frames: each (module, function) pair must appear in the observed
      traceback frames as an ordered subsequence (line numbers never compared)
    """
    reasons = []

    if expected["exception_type"] != observed.get("exception_type"):
        reasons.append(
            "exception_type mismatch: expected "
            f"{expected['exception_type']!r}, observed "
            f"{observed.get('exception_type')!r}"
        )

    if not re.search(expected["message_regex"], observed.get("message", "")):
        reasons.append(
            f"message_regex {expected['message_regex']!r} not found in "
            f"observed message {observed.get('message', '')!r}"
        )

    exp_frames = [tuple(f) for f in expected.get("top_frames", [])]
    obs_iter = iter(tuple(f) for f in observed.get("frames", []))
    missing = [f for f in exp_frames if not any(f == o for o in obs_iter)]
    if missing:
        reasons.append(f"frames not found as ordered subsequence: {missing}")

    return (not reasons), reasons


def match_v2(expected, observed):
    """v2 = v1, plus module wildcards in top_frames.

    A frame ("*", "webhook") matches any module whose function is "webhook".
    Rationale (E2-GC1 finding): customer-code module names are reconstruction
    choices — two valid bundles of the same bug can name the module "server"
    vs "app.webhook_app". Cross-bundle golden scoring must anchor on library
    frames, exception type, message, and function names only.
    """
    reasons = []

    if expected["exception_type"] != observed.get("exception_type"):
        reasons.append(
            "exception_type mismatch: expected "
            f"{expected['exception_type']!r}, observed "
            f"{observed.get('exception_type')!r}"
        )

    if not re.search(expected["message_regex"], observed.get("message", "")):
        reasons.append(
            f"message_regex {expected['message_regex']!r} not found in "
            f"observed message {observed.get('message', '')!r}"
        )

    exp_frames = [tuple(f) for f in expected.get("top_frames", [])]
    obs_iter = iter(tuple(f) for f in observed.get("frames", []))

    def frame_matches(exp, obs):
        exp_mod, exp_fn = exp
        obs_mod, obs_fn = obs
        return (exp_mod == "*" or exp_mod == obs_mod) and exp_fn == obs_fn

    missing = [f for f in exp_frames
               if not any(frame_matches(f, o) for o in obs_iter)]
    if missing:
        reasons.append(f"frames not found as ordered subsequence: {missing}")

    return (not reasons), reasons


COMPARATORS = {1: match_v1, 2: match_v2}


def match(expected, observed):
    version = expected.get("comparator_version")
    comparator = COMPARATORS.get(version)
    if comparator is None:
        raise ValueError(f"unknown comparator_version: {version!r}")
    return comparator(expected, observed)
