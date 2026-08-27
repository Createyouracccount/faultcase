# faultcase

[![verify](https://github.com/Createyouracccount/faultcase/actions/workflows/verify.yml/badge.svg)](https://github.com/Createyouracccount/faultcase/actions/workflows/verify.yml)
[![PyPI](https://img.shields.io/pypi/v/faultcase)](https://pypi.org/project/faultcase/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Turn API support tickets into runnable failure-reproduction bundles with
deterministic verification.**

Feed it a customer ticket + error log + SDK versions. Get back an artifact an
engineer can run — not a chatbot answer:

> Before the patch, the customer's exact failure reproduces 3/3 with a frozen
> failure signature. After the patch, it passes 3/3. A verifier — not a human —
> decides, by exit code.

Built for support/SDK engineers at API companies who live with "cannot
reproduce" tickets — and for agent builders who need contamination-free,
machine-scored reproduction cases (see
[the case set](#the-case-set) as a blind eval harness).

![faultcase demo — ticket in, verified repro bundle out](demo.gif)

*Real execution, nothing staged: ticket → crash reproduced under
`--network none` → one-line patch → `faultcase-verify` VERIFIED.
Deterministically re-renderable via [demo.tape](demo.tape).*

## What a bundle looks like

```text
repro/
  Dockerfile              # digest-pinned base, offline-reproducible
  requirements.lock       # hash-locked dependencies (uv)
  .python-version         # the interpreter IS part of the bug surface
  app/                    # customer code, reconstructed + scripted mock server
  failing_test.py         # fails pre-patch with the exact failure signature
  fixture.json            # mock response script (the only network authority)
  failure_signature.json  # exception type + message regex + stack frames
analysis/
  likely_root_causes.md   # every claim cites evidence
fix/
  candidate.patch         # the fix
  verification.json       # machine evidence: 3/3 fail pre, 3/3 pass post
```

## Verify it yourself — Docker only, no API key

Don't take "VERIFIED" from prose. The case bundles live in this repo (not in
the PyPI package), so clone first; Docker is the only other requirement
(~3 minutes, most of it the image build):

```bash
git clone https://github.com/Createyouracccount/faultcase && cd faultcase
pip install .

# exit 0 = VERIFIED: pre-patch fails 3/3 with the frozen signature,
# post-patch passes 3/3 (exit 1 = failed, 2 = infra error)
faultcase-verify cases/gc2-urllib3-retry-method-whitelist --runner docker
```

The exact same checks re-run from scratch in
[public CI](https://github.com/Createyouracccount/faultcase/actions/workflows/verify.yml)
on every push and weekly — the badge above is the live verdict, and every run's
logs are public. Prefer raw docker commands over the CLI?
[samples/gc2-sample](samples/gc2-sample) walks the same bundle with nothing but
`docker build` / `docker run`.

## Other verifier modes

```bash
# same-bug scoring against a reference signature, plus change coverage
faultcase-verify path/to/bundle --against golden_signature.json --coverage

# run the full pipeline: customer inputs -> bundle (or a missing-info list)
faultcase-run cases/gc2-urllib3-retry-method-whitelist/input -o out/ \
  --adapter claude-cli --runner docker
```

The full `faultcase-run` pipeline additionally needs the
[Claude Code CLI](https://claude.com/claude-code); the venv runner
(`--runner venv`) needs [uv](https://docs.astral.sh/uv/), which provisions the
bundle's pinned interpreter for version-gated bugs.

## Principles

1. **No reproduction, no root-cause claim.** If the inputs are insufficient,
   the pipeline refuses to guess and emits `missing_info.json` — a precise
   list of what to collect and how (an abstain-first judge, separate from the
   generator, decides upfront).
2. **The patch cannot cheat.** The verifier hard-rejects any patch touching
   the test, fixture, or signature, and `--coverage` requires the test to
   actually execute the lines the patch adds.
3. **Determinism by construction.** Digest-pinned images, hash-locked
   dependencies, scripted mocks as the only network authority,
   `--network none` at run time. Even hangs are evidence: a watchdog freezes
   the blocked stack into a comparable signature.

## The case set

Every reproducible case is grounded in a real, public bug and verified on
both runners (Docker and a uv-provisioned venv):

| Case | Failure family | Grounded in |
|------|----------------|-------------|
| [GC-1](cases/gc1-webhook-hmac-reserialized-body) | Webhook HMAC broken by body re-serialization | [stripe-python #424](https://github.com/stripe/stripe-python/issues/424) |
| [GC-2](cases/gc2-urllib3-retry-method-whitelist) | Version-gated retry semantics (explodes only on a real retry) | [urllib3 #2092](https://github.com/urllib3/urllib3/issues/2092) |
| [GC-3](cases/gc3-fromisoformat-zulu-suffix) | Runtime-version datetime parsing (the interpreter pin IS the bug) | [cpython #80010](https://github.com/python/cpython/issues/80010) |
| [GC-4](cases/gc4-idle-drop-read-hang) | Silent hang: no timeout + stalled connection | the classic dropped keep-alive |
| [NR-1](cases/nr1-intermittent-hang-no-logs) | Insufficient evidence → refuse + missing-info list | — |

Each case ships the customer-side `input/` (ticket, log, versions, snippet)
separately from the golden `repro/` + `fix/`, so the set doubles as a blind
evaluation harness for reproduction agents: score an agent's bundle with
`faultcase-verify --against` (did it reproduce the *same* bug, not just any
bug?).

## Try it on a real ticket

Send one anonymized ticket (symptoms + log + versions, secrets stripped) and
get a runnable bundle back — open an issue or reach out. If it can't be
reproduced from what you send, you get a precise missing-info list instead of
guesses.

## Scope

Cases are Python today. The contract itself — frozen failure signature,
scripted mock as the only network authority, 3x-fail/3x-pass verification,
exit-code verdict — is language-agnostic: a Node or Go case needs a
Dockerfile, a failing test, and a signature, not a new verifier.

## License

MIT

---

<details>
<summary>한국어 요약</summary>

**API 지원 티켓을 실행 가능한 장애 재현 번들로 바꾼다 — 결정적 검증과 함께.**

고객 티켓 + 오류 로그 + SDK 버전을 넣으면, 챗봇 답변이 아니라 엔지니어가 실행할 수
있는 artifact가 나온다: 패치 전에는 고객의 실패가 동일한 시그니처로 3/3 재현되고,
패치 후에는 3/3 통과한다. 판정은 사람이 아니라 verifier가 exit code로 한다.

원칙: (1) 재현 없으면 원인 주장 금지 — 정보 부족 시 추측 대신 누락 정보 목록 출력,
(2) 패치는 반칙 불가 — 테스트·fixture·시그니처 수정 하드 리젝 + change-coverage,
(3) 구조적 결정성 — digest 고정, hash-lock, 스크립트된 mock, `--network none`.
hang조차 워치독이 블록 스택을 캡처해 비교 가능한 시그니처가 된다.

</details>
