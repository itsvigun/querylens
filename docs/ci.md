# Continuous integration

[Documentation index](README.md)

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on pushes and pull
requests, with read-only repository permissions, no persisted checkout credentials,
job timeouts and cancellation of superseded runs. It pins action commit SHAs,
uv 0.12.23, Python 3.14.8, the dependency lock and the existing pgvector image.

| Job | Checks |
|---|---|
| `offline` | Locked install/lock check, Ruff lint/format, JavaScript syntax, offline tests |
| `postgres` | Fresh PostgreSQL/pgvector service, migrations, roles, deterministic seed, control values, schema drift, integration tests and twenty-case offline evaluation |
| `browser` | Optional browser dependency group, pinned Playwright Chromium installation, eighteen browser tests with labeled offline answers |

The PostgreSQL service is isolated per job. Its checked-in CI passwords are public
**disposable test credentials** for that service, not account or deployment
secrets. `OPENAI_API_KEY` is explicitly empty; no GitHub provider-key secret is
referenced. No live verification/evaluation command runs in CI. Browser tests
start their own local stub server and need no PostgreSQL or API key.

The evaluation step writes `artifacts/evaluation.json`, then uploads only that
file as `offline-postgres-evaluation`, retained fourteen days. An `always()` upload
can preserve a report with failed cases; setup failure before report creation is
reported by the failed step. No `.env`, plan, request transcripts or live reports
are uploaded. The report is labeled scripted/stub and cannot establish semantic
model accuracy.

For equivalent local checks, use [testing](testing.md) after [setup](setup.md).
Hosted CI is verified separately from local runs; see the dated
[verification record](verification.md#stage-7) for the exact tested snapshot/run.
The workflow starts on any pushed branch, allowing checks before merging into main.

Action choices were checked against the primary
[checkout](https://github.com/actions/checkout),
[setup-uv](https://github.com/astral-sh/setup-uv), and
[upload-artifact](https://github.com/actions/upload-artifact) repositories, and
[GitHub's service-container guide](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).
Review action releases and rerun CI when upgrading their pinned revisions.
