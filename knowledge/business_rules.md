# Synthetic demo business rules

## Dataset and time anchor

Dataset version: synthetic-v1. Random seed: 20261001. Reference date:
**2026-10-01T00:00:00Z**. All data is synthetic and covers July through September
2026. No production data, personal names, or emails are used.

The seed creates 10,000 users, 20,000 orders, 80,000 events, and 3,000 subscriptions.
The reference date is visible in README and `GET /demo`; it is the exclusive
observation cutoff, not the current server date. `/demo` describes the configured
dataset and does not establish that seed data has been loaded. Use the explicit
verification command to check loaded data.

## Relative periods

Resolve relative dates against the reference date in UTC:

- Last month: September 2026, `[2026-09-01, 2026-10-01)`.
- Last week: the previous complete Monday-to-Monday week,
  `[2026-09-21, 2026-09-28)`.
- A rolling seven-day window is different from last calendar week; ask which
  window is intended when wording is ambiguous.

All period ends are exclusive. State the period, segment, and denominator in
answers. See metrics.md for revenue, ARPU, ARPPU, conversion, and churn.

## Deliberately generated scenarios

Germany completed-order counts decrease from 2,000 in August to 560 in September.
Germany revenue decreases from 153,041.95 EUR to 42,992.93 EUR. Other countries
have different purchase counts and amounts. These differences are generated for
testing segment contributions, not evidence of real customer behavior.

September subscription churn is 20% for basic, 10% for pro, and 4% for enterprise,
each with a denominator of 950 subscriptions active at the start boundary.
There are 1,000 subscriptions per plan initially; 50 per plan were cancelled in
August and are outside September's starting cohort.

There are nonpaying active users, repeated purchases, repeated sessions, refunded
orders, and cancelled orders. June has no data and provides an empty-period case.

## Limits of interpretation

Breakdowns can quantify which segments contributed to a revenue change. They
cannot establish why users changed behavior: the dataset has no experiment,
pricing-change history, marketing attribution, or causal model.

Order revenue and subscription churn are separate metrics. The seed does not
model subscription billing, MRR, trials, renewals, historical country changes,
taxes, exchange rates, or partial refunds. Do not invent unsupported metrics.

## Reproducibility

The generator assigns stable IDs and uses a local random generator independent
of global random state. `scripts/reference_values.json` records the fingerprint
and independent reference values. Repeating seed on matching data leaves it
unchanged. Differing analytics data requires an explicit `--replace`; replacement
is transactional and affects only the four synthetic business tables.

Changing the generator or time anchor requires a reviewed dataset version and
updated independent references. Do not update expected results from SQL merely
to hide a failing metric check.
