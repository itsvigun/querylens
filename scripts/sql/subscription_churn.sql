-- The cohort is active immediately before the start boundary.
SELECT plan, COUNT(*) AS subscriptions_at_start,
       COUNT(*) FILTER (WHERE cancelled_at >= :start AND cancelled_at < :end) AS cancellations,
       COUNT(*) FILTER (WHERE cancelled_at >= :start AND cancelled_at < :end)::numeric
           / NULLIF(COUNT(*), 0) AS churn_rate
FROM analytics.subscriptions
WHERE started_at < :start AND (cancelled_at IS NULL OR cancelled_at >= :start)
GROUP BY plan
ORDER BY plan;
