# AI-assisted development workflow

ProcureDelta was developed with AI coding assistants used as implementation and review tools. The assistant is not treated as a completion oracle.

## What an agent may do

- inspect an issue or incomplete requirement and propose a concrete implementation
- edit backend, frontend, tests, migrations, and documentation on a feature branch
- add regression cases for failures found during implementation
- inspect CI and release artifacts and revise the patch when a gate fails
- summarize a decision and its measured limitations

## What an agent may not decide by itself

- claim an external integration was exercised when no credential or live run exists
- convert synthetic regression results into production-capacity claims
- add secrets to source control or artifacts
- create billable cloud resources or make paid provider calls without explicit opt-in
- call work complete because one test passed

## Acceptance path

A substantive change follows this path:

1. isolate the work on a feature branch
2. compare the diff against the intended product/operational contract
3. run frontend and backend static checks and tests
4. run the isolated Docker release contract when the change touches runtime behavior
5. inspect failure logs instead of retrying blindly
6. repeat the relevant integration gate after a fix
7. merge through a pull request only after the current head is green
8. verify the merge commit on main again

The release contract includes real containers, PostgreSQL, Redis/ARQ, migrations, readiness,
browser E2E, queue scale, query-plan checks, and local HTTP load. It is intentionally separate
from claims about hosted LLMs, public-source live traffic, or cloud operation.

## Evidence rule

Every public claim should be one of:

- **measured** — a reproducible artifact exists for the stated scope
- **contract-tested** — the boundary/behavior is exercised without claiming an external service ran
- **not_run** — credentials, provider access, or production context were not supplied
- **limitation** — the evidence does not generalize beyond its test population

Examples in this repository:

- Korean OCR is measured on a frozen synthetic `kor+eng` regression set.
- Hosted LLM quality is unvalidated until the manual workflow produces a valid measured artifact.
  The first Claude attempt failed with HTTP errors; a green Actions badge alone is insufficient.
- The Render Blueprint is contract-tested deployment readiness, not proof of live backend operation.

## External-cost boundary

The normal push/PR CI does not make paid LLM calls. Hosted evaluation exists only as the
manual `Hosted LLM Evaluation` workflow and requires the repository secret
`PROCURE_DELTA_LLM_API_KEY`.

The normal CI also does not sync `render.yaml` or create cloud resources.

This separation keeps AI-assisted iteration fast while making the final evidence independently
checkable from repository state and artifacts.
