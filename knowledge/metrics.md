# Metric definitions

These definitions apply to QueryLens synthetic-v1. Currency is EUR. Periods use
UTC and half-open windows: `timestamp >= start AND timestamp < end`. The demo
reference date is **2026-10-01 00:00:00 UTC**.

## Revenue

Revenue is the sum of `analytics.orders.amount` for orders with
`status = 'completed'` whose `created_at` is inside the requested period.
Refunded and cancelled orders are excluded entirely. No matching orders means
revenue is 0 EUR. Amounts use NUMERIC(12, 2), not floating point.

This is a simplified demo definition, not an accounting or net-revenue model.
Order status is the snapshot status; historical status transitions, taxes, fees,
and partial refunds are not modeled.

## Active users

Active users are distinct `user_id` values with at least one `session` event in
the requested period. Multiple sessions count once. A checkout alone does not
establish activity. The current `users.status` field does not define this metric
and does not exclude historical events.

## ARPU

ARPU = revenue / active users, both measured in the same period and segment.
The denominator includes active users who did not buy. With zero active users,
ARPU is undefined (SQL NULL), even if revenue is zero.

## ARPPU

ARPPU = revenue / distinct paying users in the same period and segment.
A paying user has at least one completed order in that period. Multiple orders
count once in the denominator. With zero paying users, ARPPU is undefined.

Do not divide either metric by all registered users. Aggregate purchases and
activity separately before combining totals to avoid multiplying revenue in an
orders-to-events join.

## Registration cohort conversion

The denominator is distinct users whose `registered_at` is in a specified cohort
window. The numerator is cohort users with at least one completed purchase in
`[registered_at, registered_at + 30 days)` for the implemented control query.
The purchase need not be in the registration calendar month.

Only fully observed windows can establish conversion. The control query returns
NULL for the rate if any cohort member's 30-day window ends after the reference
date; it reports converted users among fully observed members separately. Empty
cohorts also have undefined conversion. The August cohort is fully observed;
the September cohort is not. Another conversion window must be stated explicitly.

## Subscription churn rate

For a requested period `[start, end)`, use the subscription cohort active
immediately before `start`: `started_at < start` and `cancelled_at IS NULL OR
cancelled_at >= start`. The numerator is subscriptions in that cohort cancelled
in `[start, end)`; the denominator is all subscriptions in that cohort.

Cancellation exactly at start counts. Cancellation exactly at end does not count
in this period. Subscriptions starting at or after start are outside the cohort.
The unit is subscriptions, not users. A zero denominator means undefined churn;
the grouped control query omits plans with no cohort rather than inventing 0%.

## Control results

Trusted SQL is in `scripts/sql/`; `python -m scripts.verify_data` executes it
using dedicated read-only credentials. Checked-in values in
`scripts/reference_values.json` were calculated independently by Python loops
in `scripts/reference_metrics.py`. Money is compared exactly at two decimal
places; ratios are compared rounded to eight decimal places.

September 2026 control values:

| Metric | Value |
|---|---:|
| Revenue | 336,080.07 EUR |
| Completed orders | 4,400 |
| Active users | 9,501 |
| Paying users | 3,396 |
| ARPU | 35.37312599 EUR |
| ARPPU | 98.96350707 EUR |
| Basic subscription churn | 190 / 950 = 20% |
| Pro subscription churn | 95 / 950 = 10% |
| Enterprise subscription churn | 38 / 950 = 4% |

These are reference calculations over synthetic data. They are not LLM answers
or an evaluation of future agent accuracy.
