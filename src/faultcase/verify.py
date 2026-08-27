"""faultcase verifier — deterministic bundle verification.

Contract (frozen in docs/02_design.md):
  exit 0  bundle verified (pre-patch fails 3x with matching signature,
          post-patch passes 3x)
  exit 1  verification failed
  exit 2  infrastructure error — never conflated with a scenario failure

Runners:
  docker  build digest-pinned image, run each attempt in a fresh container
          with --network none (the mock server inside is the only network)
  venv    fallback for hosts without a Docker daemon; hash-locked install
          into a throwaway virtualenv. Docker remains the Gate 0 authority.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv as venv_mod

from .comparator import match

COVERAGE_PIN = "coverage==7.6.10"

REQUIRED_FILES = [
    "repro/Dockerfile",
    "repro/requirements.lock",
    "repro/failing_test.py",
    "repro/fixture.json",
    "repro/failure_signature.json",
    "fix/candidate.patch",
    "fix/patch_target",
]
# The patch may touch customer code (repro/app/**) and, for dependency_pin,
# repro/requirements.lock — never the test, fixture, signature, or Dockerfile.
PROTECTED_PATHS = {
    "repro/failing_test.py",
    "repro/fixture.json",
    "repro/failure_signature.json",
    "repro/Dockerfile",
}
PATCH_TARGETS = {"customer_code", "dependency_pin", "server_contract"}
RUN_TIMEOUT = 180


class InfraError(Exception):
    pass


def sh(cmd, cwd=None, timeout=None, env=None):
    return subprocess.run(
        cmd, cwd=cwd, timeout=timeout, env=env,
        capture_output=True, text=True,
    )


def patch_touched_paths(patch_text):
    paths = set()
    for line in patch_text.splitlines():
        for prefix in ("--- a/", "+++ b/"):
            if line.startswith(prefix):
                paths.add(line[len(prefix):].split("\t")[0])
    return paths


def static_checks(bundle):
    problems = []
    for rel in REQUIRED_FILES:
        if not os.path.exists(os.path.join(bundle, rel)):
            problems.append(f"missing required file: {rel}")
    if problems:
        return None, None, problems

    with open(os.path.join(bundle, "repro/failure_signature.json")) as f:
        signature = json.load(f)
    if not isinstance(signature.get("comparator_version"), int):
        problems.append("failure_signature.json lacks integer comparator_version")

    patch_target = open(os.path.join(bundle, "fix/patch_target")).read().strip()
    if patch_target not in PATCH_TARGETS:
        problems.append(f"invalid patch_target: {patch_target!r}")

    patch_text = open(os.path.join(bundle, "fix/candidate.patch")).read()
    touched = patch_touched_paths(patch_text)
    bad = touched & PROTECTED_PATHS
    if bad:
        problems.append(f"patch touches protected files (anti-gaming reject): {sorted(bad)}")
    if patch_target != "dependency_pin" and "repro/requirements.lock" in touched:
        problems.append("patch edits requirements.lock but patch_target is not dependency_pin")

    check = sh(["git", "apply", "--check", "fix/candidate.patch"], cwd=bundle)
    if check.returncode != 0:
        problems.append(f"git apply --check failed: {check.stderr.strip()}")

    return signature, patch_target, problems


def copy_bundle(bundle, workdir, name):
    dest = os.path.join(workdir, name)
    shutil.copytree(bundle, dest, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    return dest


def apply_patch(bundle_copy):
    result = sh(["git", "apply", "fix/candidate.patch"], cwd=bundle_copy)
    if result.returncode != 0:
        raise InfraError(f"git apply failed on copy: {result.stderr.strip()}")


class VenvRunner:
    name = "venv"

    def __init__(self, workdir):
        self.workdir = workdir
        self.python = None

    @staticmethod
    def _required_python(bundle_copy):
        path = os.path.join(bundle_copy, "repro", ".python-version")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return f.read().strip() or None

    def prepare(self, bundle_copy):
        venv_dir = os.path.join(self.workdir, "venv")
        if os.path.exists(venv_dir):
            shutil.rmtree(venv_dir)

        required = self._required_python(bundle_copy)
        uv = shutil.which("uv")
        repro_dir = os.path.join(bundle_copy, "repro")

        if uv:
            # uv provisions the bundle's pinned interpreter itself, so even
            # version-gated bugs (e.g. a 3.10-only failure) verify in a venv.
            cmd = [uv, "venv", venv_dir]
            if required:
                cmd += ["--python", required]
            created = sh(cmd, timeout=600)
            if created.returncode != 0:
                raise InfraError(f"uv venv failed: {created.stderr.strip()[-2000:]}")
            self.python = os.path.join(venv_dir, "bin", "python")
            install = sh(
                [uv, "pip", "install", "--python", self.python, "--quiet",
                 "--no-deps", "--require-hashes", "-r", "requirements.lock"],
                cwd=repro_dir, timeout=600,
            )
        else:
            host = f"{sys.version_info.major}.{sys.version_info.minor}"
            if required and not required.startswith(host):
                raise InfraError(
                    f"bundle pins python {required} but host has {host} and uv "
                    "is not installed — use --runner docker or install uv"
                )
            venv_mod.EnvBuilder(with_pip=True).create(venv_dir)
            self.python = os.path.join(venv_dir, "bin", "python")
            install = sh(
                [self.python, "-m", "pip", "install", "--quiet",
                 "--require-hashes", "--no-deps", "-r", "requirements.lock"],
                cwd=repro_dir, timeout=600,
            )
        if install.returncode != 0:
            raise InfraError(f"dependency install failed: {install.stderr.strip()[-2000:]}")

    def run_once(self, bundle_copy, observed_path):
        env = dict(os.environ, FAULTCASE_OBSERVED=observed_path,
                   PYTHONHASHSEED="0", TZ="UTC")
        try:
            result = sh([self.python, "failing_test.py"],
                        cwd=os.path.join(bundle_copy, "repro"),
                        timeout=RUN_TIMEOUT, env=env)
        except subprocess.TimeoutExpired:
            return "TIMEOUT", ""
        return result.returncode, result.stdout + result.stderr


class DockerRunner:
    name = "docker"

    def __init__(self, workdir, case_id):
        self.workdir = workdir
        self.tag_base = f"faultcase-{case_id}"

    def _docker_ok(self):
        probe = sh(["docker", "version", "--format", "{{.Server.Version}}"])
        return probe.returncode == 0

    def _pull_base_image(self, bundle_copy):
        """Pre-pull the digest-pinned base so the build timeout measures the
        build, not the network. A first pull can dwarf the build itself."""
        dockerfile = os.path.join(bundle_copy, "repro", "Dockerfile")
        with open(dockerfile) as f:
            first = f.readline().strip()
        if not first.startswith("FROM "):
            raise InfraError(f"Dockerfile does not start with FROM: {first!r}")
        image = first.split()[1]
        try:
            pull = sh(["docker", "pull", image], timeout=1800)
        except subprocess.TimeoutExpired:
            raise InfraError(f"docker pull timed out (1800s): {image}")
        if pull.returncode != 0:
            raise InfraError(f"docker pull failed: {pull.stderr.strip()[-2000:]}")

    def prepare(self, bundle_copy, phase="pre"):
        if not self._docker_ok():
            raise InfraError("docker daemon unavailable")
        if phase == "pre":
            self._pull_base_image(bundle_copy)
        self.tag = f"{self.tag_base}-{phase}"
        build = None
        for attempt in (1, 2):  # one retry on infra flake
            try:
                build = sh(["docker", "build", "-t", self.tag, "."],
                           cwd=os.path.join(bundle_copy, "repro"), timeout=900)
            except subprocess.TimeoutExpired:
                continue
            if build.returncode == 0:
                return
        if build is None:
            raise InfraError("docker build timed out twice (900s each)")
        raise InfraError(f"docker build failed: {build.stderr.strip()[-2000:]}")

    def run_once(self, bundle_copy, observed_path):
        outdir = os.path.dirname(observed_path)
        os.makedirs(outdir, exist_ok=True)
        # The bundle image runs as its own non-root user, whose uid need not
        # match the host user owning this directory (Linux bind mounts map
        # uids 1:1; Docker Desktop on macOS masks the mismatch).
        os.chmod(outdir, 0o777)
        try:
            result = sh(
                ["docker", "run", "--rm", "--network", "none",
                 "-v", f"{outdir}:/out",
                 "-e", "FAULTCASE_OBSERVED=/out/observed_signature.json",
                 self.tag],
                timeout=RUN_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return "TIMEOUT", ""
        container_observed = os.path.join(outdir, "observed_signature.json")
        if os.path.exists(container_observed) and container_observed != observed_path:
            shutil.move(container_observed, observed_path)
        return result.returncode, result.stdout + result.stderr


def patch_changed_lines(patch_text):
    """Map each patched file to the new-file line numbers its patch adds."""
    changed = {}
    current = None
    new_line = None
    for line in patch_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[len("+++ b/"):].split("\t")[0]
            changed.setdefault(current, set())
            new_line = None
        elif line.startswith("@@") and current is not None:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            new_line = int(m.group(1)) if m else None
        elif current is not None and new_line is not None:
            if line.startswith("+") and not line.startswith("+++"):
                changed[current].add(new_line)
                new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                pass  # old-file line: consumes no new-file line number
            else:
                new_line += 1
    return {path: lines for path, lines in changed.items() if lines}


def change_coverage_check(runner, post_copy, workdir, patch_text):
    """SWT-bench-style change coverage: the test must actually execute the
    lines the patch introduced — an independent 'same bug' factor beyond
    signature matching."""
    targets = {p: l for p, l in patch_changed_lines(patch_text).items()
               if p.startswith("repro/")}
    if not targets:
        return {"status": "n/a", "reason": "patch adds no repro/ source lines"}

    uv = shutil.which("uv")
    if uv:
        inst = sh([uv, "pip", "install", "--python", runner.python, "--quiet",
                   "--no-deps", COVERAGE_PIN], timeout=300)
    else:
        inst = sh([runner.python, "-m", "pip", "install", "--quiet",
                   COVERAGE_PIN], timeout=300)
    if inst.returncode != 0:
        raise InfraError(f"coverage install failed: {inst.stderr.strip()[-500:]}")

    repro_dir = os.path.join(post_copy, "repro")
    data_file = os.path.join(workdir, ".coverage")
    cov_json = os.path.join(workdir, "coverage.json")
    env = dict(os.environ, PYTHONHASHSEED="0", TZ="UTC",
               FAULTCASE_OBSERVED=os.path.join(workdir, "cov_observed.json"))
    run1 = sh([runner.python, "-m", "coverage", "run",
               "--data-file", data_file, "failing_test.py"],
              cwd=repro_dir, timeout=RUN_TIMEOUT, env=env)
    if run1.returncode != 0:
        return {"status": "failed",
                "reason": f"post-patch run under coverage exited {run1.returncode}"}
    rep = sh([runner.python, "-m", "coverage", "json",
              "--data-file", data_file, "-o", cov_json],
             cwd=repro_dir, timeout=120)
    if rep.returncode != 0:
        raise InfraError(f"coverage json failed: {rep.stderr.strip()[-500:]}")

    files = json.load(open(cov_json)).get("files", {})
    result = {"status": "ok", "files": {},
              "executed_changed_lines": 0, "total_changed_lines": 0}
    for rel, lines in targets.items():
        sub = rel[len("repro/"):]
        executed = set()
        for key, info in files.items():
            if key.endswith(sub):
                executed = set(info.get("executed_lines", []))
                break
        hit = lines & executed
        result["files"][rel] = {"changed_lines": len(lines),
                                "executed": len(hit)}
        result["executed_changed_lines"] += len(hit)
        result["total_changed_lines"] += len(lines)
    if result["executed_changed_lines"] == 0:
        result["status"] = "not_covered"
    return result


def run_phase(runner, bundle_copy, workdir, phase, runs, signature=None,
              against=None):
    """phase 'pre': every run must exit 1 with a matching signature.
    phase 'post': every run must exit 0.
    `against`: optional golden signature — pre-run observations must match it
    too (did the bundle reproduce the SAME bug, not just some bug)."""
    records = []
    ok = True
    for i in range(runs):
        observed_path = os.path.join(workdir, f"{phase}_observed_{i}.json")
        if os.path.exists(observed_path):
            os.remove(observed_path)
        exit_code, output = runner.run_once(bundle_copy, observed_path)
        record = {"run": i + 1, "exit": exit_code}
        if exit_code == "TIMEOUT":
            record["verdict"] = "TIMEOUT"  # a hang never counts as a match
            ok = False
        elif phase == "pre":
            if exit_code != 1:
                record["verdict"] = f"expected exit 1, got {exit_code}"
                ok = False
            elif not os.path.exists(observed_path):
                record["verdict"] = "no observed_signature.json emitted"
                ok = False
            else:
                with open(observed_path) as f:
                    observed = json.load(f)
                matched, reasons = match(signature, observed)
                record["signature_match"] = matched
                if not matched:
                    record["mismatch_reasons"] = reasons
                    ok = False
                if against is not None:
                    g_matched, g_reasons = match(against, observed)
                    record["golden_match"] = g_matched
                    if not g_matched:
                        record["golden_mismatch_reasons"] = g_reasons
                        ok = False
        else:
            if exit_code != 0:
                record["verdict"] = f"expected exit 0, got {exit_code}"
                record["output_tail"] = output[-1500:]
                ok = False
        records.append(record)
    return ok, records


def verify(bundle, runner_name="docker", runs=3, against_path=None,
           coverage=False):
    bundle = os.path.abspath(bundle)
    signature, patch_target, problems = static_checks(bundle)
    against = None
    if against_path is not None:
        with open(against_path) as f:
            against = json.load(f)
    report = {
        # basenames only: verification.json ships inside the bundle, so it
        # must never leak the author's local directory layout
        "bundle": os.path.basename(os.path.normpath(bundle)),
        "runner": runner_name,
        "runs_per_phase": runs,
        "static_problems": problems,
    }
    if against_path is not None:
        report["against"] = os.path.basename(os.path.normpath(against_path))
    if problems:
        report["result"] = "FAILED_STATIC"
        return 1, report
    report["comparator_version"] = signature["comparator_version"]
    report["patch_target"] = patch_target

    with tempfile.TemporaryDirectory(prefix="faultcase-") as workdir:
        case_id = signature.get("case_id", os.path.basename(bundle))

        pre_copy = copy_bundle(bundle, workdir, "pre")
        if runner_name == "docker":
            runner = DockerRunner(workdir, case_id)
            runner.prepare(pre_copy, phase="pre")
        else:
            runner = VenvRunner(workdir)
            runner.prepare(pre_copy)

        pre_ok, pre_records = run_phase(runner, pre_copy, workdir, "pre", runs,
                                        signature=signature, against=against)
        report["pre"] = pre_records
        if not pre_ok:
            golden_missed = any(r.get("golden_match") is False for r in pre_records)
            report["result"] = ("FAILED_GOLDEN_MISMATCH" if golden_missed
                                else "FAILED_PRE")
            return 1, report

        if patch_target == "server_contract":
            report["not_patchable"] = True
            report["result"] = "VERIFIED_REPRO_ONLY"
            return 0, report

        post_copy = copy_bundle(bundle, workdir, "post")
        apply_patch(post_copy)
        if patch_target == "dependency_pin":
            # the one sanctioned environment change: rebuild from patched lockfile
            if runner_name == "docker":
                runner.prepare(post_copy, phase="post")
            else:
                runner.prepare(post_copy)
        elif runner_name == "docker":
            runner.prepare(post_copy, phase="post")

        post_ok, post_records = run_phase(runner, post_copy, workdir, "post", runs)
        report["post"] = post_records
        if not post_ok:
            report["result"] = "FAILED_POST"
            return 1, report

        if coverage:
            if runner_name != "venv":
                report["change_coverage"] = {
                    "status": "n/a",
                    "reason": "change coverage runs on the venv runner only (v1)"}
            elif patch_target != "customer_code":
                report["change_coverage"] = {
                    "status": "n/a", "reason": f"patch_target {patch_target}"}
            else:
                patch_text = open(os.path.join(bundle, "fix/candidate.patch")).read()
                cc = change_coverage_check(runner, post_copy, workdir, patch_text)
                report["change_coverage"] = cc
                if cc["status"] in ("not_covered", "failed"):
                    report["result"] = "FAILED_CHANGE_COVERAGE"
                    return 1, report

        report["result"] = "VERIFIED"
        return 0, report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="faultcase-verify")
    parser.add_argument("bundle", help="path to a case bundle directory")
    parser.add_argument("--runner", choices=["docker", "venv"], default="docker")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--against", metavar="GOLDEN_SIGNATURE_JSON",
                        help="also require pre-patch failures to match this "
                             "golden signature (same-bug scoring)")
    parser.add_argument("--coverage", action="store_true",
                        help="require the test to execute at least one line "
                             "the patch adds (change-coverage factor; venv "
                             "runner, customer_code patches)")
    parser.add_argument("--json", action="store_true", help="print full report as JSON")
    args = parser.parse_args(argv)

    try:
        code, report = verify(args.bundle, runner_name=args.runner,
                              runs=args.runs, against_path=args.against,
                              coverage=args.coverage)
    except InfraError as exc:
        print(f"INFRA ERROR: {exc}", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired as exc:
        print(f"INFRA ERROR: unhandled timeout: {exc}", file=sys.stderr)
        return 2

    verification_path = os.path.join(args.bundle, "fix", "verification.json")
    with open(verification_path, "w") as f:
        json.dump(report, f, indent=2)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['result']}  (runner={report['runner']}, "
              f"report written to {verification_path})")
    return code


if __name__ == "__main__":
    sys.exit(main())
