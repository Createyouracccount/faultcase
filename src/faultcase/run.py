"""faultcase run — the reproduction pipeline CLI (v0).

    faultcase-run <input_dir> -o <out_dir> [--adapter claude-cli|manual]
                  [--runner docker|venv] [--max-repairs 5]

Stages (docs/03_pipeline.md): intake(scrub) -> evidence -> gate ->
synthesize(LLM adapter) -> verify -> emit.

Exit codes:
  0  bundle produced and VERIFIED
  1  bundle produced but verification failed
  2  infrastructure error
  3  NOT_REPRODUCIBLE — missing_info.json emitted instead of a bundle
  4  manual adapter: workspace prepared, awaiting an agent (not a failure)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

from . import verify as verify_mod
from .evidence import parse_traceback, parse_versions, scrub

INPUT_FILES = ["customer_ticket.md", "error.log", "sdk_version.txt", "code_snippet.py"]

PROTOCOL = """You are faultcase pipeline v0 — a blind API-failure reproduction agent.

Workspace: {workspace}

STRICT RULE: work ONLY inside this workspace. Network use allowed only for the
PyPI JSON API (package hashes), pip installs into a venv inside the workspace,
and docker if a specific runtime version is required to exhibit the bug.

Read first: input/* (customer-provided), analysis/evidence.json (mechanically
extracted traceback/version evidence), and bundle_spec.md (bundle layout,
failure_signature comparator schema, determinism rules, patch rules, and the
missing_info.json schema).

Task: diagnose the failure and build a reproduction bundle at attempt/ per
bundle_spec.md: attempt/repro/{{Dockerfile, requirements.lock (hash-locked),
app/, failing_test.py, fixture.json, failure_signature.json}} and
attempt/fix/{{candidate.patch (a/ b/ paths relative to attempt/), patch_target}}.
The failing test must exit 1 pre-patch, writing observed signature JSON (keys:
exception_type, message, frames [[module, function], ...], python) to
$FAULTCASE_OBSERVED, and exit 0 post-patch. The bundle must run fully offline
(scripted in-process mock as the only network authority; for webhook scenarios
the test itself may act as the signed sender).

Also write attempt/analysis/likely_root_causes.md: the root cause with every
claim citing evidence (traceback line, version pin, doc reference). No
uncited assertions.

Self-verify: cd {workspace} && PYTHONPATH=faultcase-src python3 -m \
faultcase.verify attempt --runner {runner} --json — iterate until result
VERIFIED (exit 0) or {max_repairs} distinct repair attempts. The patch must
not touch failing_test.py, fixture.json, failure_signature.json, or the
Dockerfile. Choose the runner that can actually exhibit the bug (the venv
runner uses the host interpreter).

Determinism kit: the test environment must set PYTHONHASHSEED=0 and TZ=UTC and
seed any randomness explicitly. When the bug involves clocks (token expiry,
timestamp tolerance, backoff), remove wall-clock dependence: pin timestamps in
fixtures, sign at test runtime, or freeze time with the time-machine library
(add it hash-locked to requirements.lock if used). The 3x invariant must never
depend on when the test runs.

Fallback strategy (AssertFlip): if after {half_repairs} attempts your failing
test still does not fail with the intended signature, invert the approach —
first write a script that PASSES by asserting the buggy behavior occurs
(exits 0 exactly when the bug manifests), confirm it passes, then invert the
exit logic (manifestation -> exit 1, writing the captured signature) to obtain
the failing test. Generating a passing assertion of observed behavior and
flipping it is empirically more reliable than writing a failing test directly.

If the inputs are insufficient to reproduce deterministically, do NOT fake a
bundle — write attempt/missing_info.json per the schema in bundle_spec.md
(reproducible:false, missing[] with kind/why/how_to_collect from the
controlled vocabulary, guesses only in hypotheses[]). Note: an upstream judge
already deemed these inputs sufficient, so declaring NOT_REPRODUCIBLE now
requires naming the specific evidence that turned out to be missing.

When done, print exactly one line starting with FAULTCASE_VERDICT: followed by
VERIFIED, FAILED, or NOT_REPRODUCIBLE.
"""

JUDGE_PROMPT = """You are the faultcase abstain-first judge — a gatekeeper
SEPARATE from the reproduction agent. Decide whether the inputs below contain
enough evidence to attempt a deterministic reproduction. Judge only; never try
to fix or diagnose the bug.

Rubric — answer proceed only if ALL three hold:
1. SIGNATURE EXTRACTABLE: a Python traceback (exception type + frames), OR
   equivalent failure evidence such as a stack dump of a hung process
   (py-spy/faulthandler output counts), possibly inside the ticket text.
2. ENVIRONMENT PINNABLE: interpreter and/or package versions are given, enough
   to hash-lock a reproduction environment.
3. TRIGGER DESCRIBED: the inputs say (or clearly imply) what condition makes
   the failure happen (an endpoint, a status code, an idle period, a payload).

If any criterion fails, abstain and list what is missing using ONLY these
kinds: error_traceback | sdk_versions | runtime_version | request_payload |
response_body | timing_config | retry_config | network_topology |
reproduction_frequency | code_snippet | credentials_scope.

Mechanical pre-checks already flagged (may be wrong — the evidence can live in
the ticket text; re-judge them yourself): {draft_missing}

INPUTS
------
{inputs}
------

Reply with EXACTLY one JSON object and nothing else:
{{"verdict": "proceed"|"abstain", "missing": [{{"kind": "...", "why": "...",
"how_to_collect": "..."}}], "rationale": "<one sentence>"}}
"""


def stage_intake(input_dir, workspace):
    os.makedirs(os.path.join(workspace, "input"), exist_ok=True)
    present = []
    for name in INPUT_FILES:
        src = os.path.join(input_dir, name)
        if os.path.exists(src):
            with open(src, errors="replace") as f:
                content = scrub(f.read())
            with open(os.path.join(workspace, "input", name), "w") as f:
                f.write(content)
            present.append(name)
    return present


def stage_evidence(workspace, present):
    evidence = {"inputs_present": present, "traceback": None, "versions": None}
    log_path = os.path.join(workspace, "input", "error.log")
    if os.path.exists(log_path):
        evidence["traceback"] = parse_traceback(open(log_path).read())
    ver_path = os.path.join(workspace, "input", "sdk_version.txt")
    if os.path.exists(ver_path):
        evidence["versions"] = parse_versions(open(ver_path).read())
    os.makedirs(os.path.join(workspace, "analysis"), exist_ok=True)
    with open(os.path.join(workspace, "analysis", "evidence.json"), "w") as f:
        json.dump(evidence, f, indent=2)
    return evidence


def stage_gate(evidence):
    """Mechanical reproducibility gate. Returns (proceed, draft_missing).
    The LLM stage may still declare NOT_REPRODUCIBLE later — this gate only
    catches inputs that are insufficient on their face."""
    missing = []
    if evidence["traceback"] is None:
        missing.append({
            "kind": "error_traceback",
            "why": "no parseable traceback in the provided inputs; a failure signature cannot be frozen without the exception type and frames",
            "how_to_collect": "capture the full traceback or a stack dump (py-spy/faulthandler) at failure time",
        })
    if not evidence["versions"] or not evidence["versions"]["packages"]:
        missing.append({
            "kind": "sdk_versions",
            "why": "no package pins provided; the reproduction environment cannot be hash-locked",
            "how_to_collect": "run `pip freeze` in the failing environment and attach the output",
        })
    if "code_snippet.py" not in evidence["inputs_present"]:
        missing.append({
            "kind": "code_snippet",
            "why": "no customer code provided; the call path cannot be reconstructed beyond the traceback",
            "how_to_collect": "attach the code path performing the failing call (client setup and call site, secrets redacted)",
        })
    # proceed only when a signature can be frozen AND an environment pinned
    proceed = evidence["traceback"] is not None and bool(
        evidence["versions"] and evidence["versions"]["packages"])
    return proceed, missing


def stage_judge(workspace, draft_missing, timeout):
    """Abstain-first gate: a judge LLM call, separate from the generator,
    decides upfront whether reproduction should even be attempted (the
    dual-LLM 'Abstain and Validate' pattern). Returns the parsed verdict."""
    chunks = []
    input_dir = os.path.join(workspace, "input")
    for name in INPUT_FILES:
        path = os.path.join(input_dir, name)
        if os.path.exists(path):
            with open(path, errors="replace") as f:
                chunks.append(f"### {name}\n{f.read()[:6000]}")
    evidence_path = os.path.join(workspace, "analysis", "evidence.json")
    if os.path.exists(evidence_path):
        chunks.append("### evidence.json (mechanical extraction)\n"
                      + open(evidence_path).read()[:3000])

    prompt = JUDGE_PROMPT.format(
        draft_missing=json.dumps([m["kind"] for m in draft_missing]),
        inputs="\n\n".join(chunks),
    )
    result = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", ""],
        capture_output=True, text=True, timeout=timeout,
    )
    raw = result.stdout.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if result.returncode != 0 or start == -1 or end <= start:
        raise RuntimeError(f"judge call failed: {raw[-500:]}")
    verdict = json.loads(raw[start:end + 1])
    with open(os.path.join(workspace, "judge.json"), "w") as f:
        json.dump(verdict, f, indent=2)
    return verdict


def prepare_workspace(workspace, spec_path):
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(workspace, "faultcase-src", "faultcase")
    shutil.copytree(pkg_dir, dst, ignore=shutil.ignore_patterns("__pycache__"),
                    dirs_exist_ok=True)
    shutil.copy(spec_path, os.path.join(workspace, "bundle_spec.md"))
    os.makedirs(os.path.join(workspace, "attempt"), exist_ok=True)


def adapter_claude_cli(workspace, prompt, timeout):
    result = subprocess.run(
        ["claude", "-p", prompt, "--permission-mode", "acceptEdits",
         "--allowedTools", "Bash Read Write Edit Glob Grep WebFetch"],
        cwd=workspace, capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


def default_spec_path():
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.normpath(os.path.join(here, "..", "..", "docs", "02_design.md"))
    return candidate if os.path.exists(candidate) else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="faultcase-run")
    parser.add_argument("input_dir")
    parser.add_argument("-o", "--out", required=True, help="output directory")
    parser.add_argument("--adapter", choices=["claude-cli", "manual"],
                        default="claude-cli")
    parser.add_argument("--runner", choices=["docker", "venv"], default="docker")
    parser.add_argument("--max-repairs", type=int, default=5)
    parser.add_argument("--spec", default=None, help="bundle spec markdown path")
    parser.add_argument("--adapter-timeout", type=int, default=1800)
    parser.add_argument("--stop-after", choices=["judge"], default=None,
                        help="stop after the named stage (testing/inspection)")
    args = parser.parse_args(argv)

    spec_path = args.spec or default_spec_path()
    if spec_path is None:
        print("INFRA ERROR: bundle spec not found; pass --spec", file=sys.stderr)
        return 2

    workspace = os.path.abspath(args.out)
    os.makedirs(workspace, exist_ok=True)

    present = stage_intake(os.path.abspath(args.input_dir), workspace)
    if "customer_ticket.md" not in present:
        print("INFRA ERROR: customer_ticket.md is required", file=sys.stderr)
        return 2
    evidence = stage_evidence(workspace, present)
    proceed, draft_missing = stage_gate(evidence)

    if args.adapter == "claude-cli":
        # Abstain-first: a separate judge decides, with the mechanical draft
        # as advisory input only — evidence may live in the ticket text (e.g.
        # a py-spy dump of a hang), which the mechanical gate cannot see.
        try:
            verdict = stage_judge(workspace, draft_missing,
                                  timeout=args.adapter_timeout)
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            print(f"INFRA ERROR: judge stage failed: {exc}", file=sys.stderr)
            return 2
        if args.stop_after == "judge":
            print(f"judge verdict: {verdict.get('verdict')} — "
                  f"{verdict.get('rationale', '')}")
            return 0
        if verdict.get("verdict") != "proceed":
            out = {"reproducible": False,
                   "missing": verdict.get("missing", draft_missing),
                   "hypotheses": [],
                   "judge_rationale": verdict.get("rationale", "")}
            with open(os.path.join(workspace, "missing_info.json"), "w") as f:
                json.dump(out, f, indent=2)
            print("NOT_REPRODUCIBLE (judge) — missing_info.json written")
            return 3
    elif not proceed:  # manual adapter: mechanical gate only
        out = {"reproducible": False, "missing": draft_missing,
               "hypotheses": [],
               "note": "mechanical gate (manual adapter: no judge available)"}
        with open(os.path.join(workspace, "missing_info.json"), "w") as f:
            json.dump(out, f, indent=2)
        print("NOT_REPRODUCIBLE (mechanical gate) — missing_info.json written")
        return 3

    prepare_workspace(workspace, spec_path)
    prompt = PROTOCOL.format(workspace=workspace, runner=args.runner,
                             max_repairs=args.max_repairs,
                             half_repairs=max(2, args.max_repairs // 2))
    with open(os.path.join(workspace, "PROMPT.md"), "w") as f:
        f.write(prompt)

    if args.adapter == "manual":
        print(f"workspace prepared: {workspace} (attach an agent to PROMPT.md)")
        return 4

    try:
        code, output = adapter_claude_cli(workspace, prompt, args.adapter_timeout)
    except subprocess.TimeoutExpired:
        print("INFRA ERROR: adapter timed out", file=sys.stderr)
        return 2
    with open(os.path.join(workspace, "adapter_output.log"), "w") as f:
        f.write(output)

    attempt = os.path.join(workspace, "attempt")
    if os.path.exists(os.path.join(attempt, "missing_info.json")):
        print("NOT_REPRODUCIBLE (agent) — attempt/missing_info.json written")
        return 3

    # trust but verify: the pipeline re-runs verification itself
    try:
        vcode, report = verify_mod.verify(attempt, runner_name=args.runner)
    except verify_mod.InfraError as exc:
        print(f"INFRA ERROR: {exc}", file=sys.stderr)
        return 2
    with open(os.path.join(workspace, "verification.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(f"pipeline result: {report['result']}")
    return 0 if vcode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
