# Event definitions

## Session

A `session` row represents an observed user session at `created_at` in UTC.
A user with at least one session in a period is active in that period. Repeated
sessions count once for active users. Session duration, device, and session IDs
are not modeled.

The synthetic generator creates a session at registration, a session at each
order time, and additional activity events. This ensures purchases have activity
in the same period without restricting activity to paying users.

## Checkout

A `checkout` row represents a synthetic checkout interaction. It does not prove
that an order was completed or that payment succeeded. It does not itself qualify
a user as active under the session-based active-user definition.

## Purchases and joins

Use `analytics.orders` with `status = 'completed'` for purchases, revenue,
conversion, and paying users. Neither sessions nor checkout counts substitute
for completed orders. Events have no order_id, so they cannot establish a
checkout-to-order funnel with a defined attribution window.

Each event references an existing user and is at or after registration in the
seed. Multiple events at the same timestamp are permitted and are not necessarily
duplicates. Aggregate event and order data separately before joining by user or
segment to avoid multiplying monetary values.
