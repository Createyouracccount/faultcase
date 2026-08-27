"""Deterministic evidence extraction: secret scrubbing, traceback parsing,
version parsing. No LLM involved — everything here is mechanically citable."""
import re

SECRET_PATTERNS = [
    # provider key shapes; deliberately loose suffixes — bundles are shared artifacts
    re.compile(r"\b(sk|pk|rk)_(live|test)_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[=:]\s*\S{8,}"),
]

TRACEBACK_HEADER = "Traceback (most recent call last):"
FRAME_RE = re.compile(r'\s*File "(?P<path>[^"]+)", line \d+, in (?P<func>\S+)')
EXC_RE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Interrupt|Exit|Timeout|StopIteration))(?:: (?P<msg>.*))?$")
VERSION_RE = re.compile(r"^\s*(?P<pkg>[A-Za-z0-9_.-]+)==(?P<ver>[A-Za-z0-9_.!+-]+)\s*$")
PYTHON_RE = re.compile(r"(?i)\bpython\s+(?P<ver>\d+\.\d+(?:\.\d+)?)")


def scrub(text):
    """Redact secret-shaped tokens. Bundles are designed to be shared."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def module_hint(path):
    """Best-effort dotted module from a file path. site-packages paths give
    real module names; app paths give the basename as a hint."""
    path = path.replace("\\", "/")
    if "site-packages/" in path:
        tail = path.split("site-packages/")[-1]
        return tail[:-3].replace("/", ".") if tail.endswith(".py") else tail
    base = path.rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".py") else base


def parse_traceback(log_text):
    """Parse the LAST traceback block in a log. Returns None or
    {exception_type, message, frames: [[module_hint, function], ...]}."""
    lines = log_text.splitlines()
    starts = [i for i, ln in enumerate(lines) if TRACEBACK_HEADER in ln]
    if not starts:
        return None
    block = lines[starts[-1]:]
    frames = []
    exc = None
    for ln in block[1:]:
        m = FRAME_RE.match(ln)
        if m:
            frames.append([module_hint(m.group("path")), m.group("func")])
            continue
        m = EXC_RE.match(ln.strip())
        if m and not ln.startswith(" "):
            exc = m
            break
    if exc is None:
        return None
    return {
        "exception_type": exc.group("type"),
        "message": exc.group("msg") or "",
        "frames": frames,
    }


def parse_versions(text):
    """Extract pkg==ver pins and python version mentions."""
    packages, pythons = {}, []
    for ln in text.splitlines():
        m = VERSION_RE.match(ln)
        if m:
            packages[m.group("pkg").lower()] = m.group("ver")
            continue
        m = PYTHON_RE.search(ln)
        if m:
            pythons.append(m.group("ver"))
    return {"packages": packages, "python": pythons}
