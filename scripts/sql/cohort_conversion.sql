-- Per-user 30-day window, not a calendar month. Unobserved windows yield NULL.
WITH cohort AS (
    SELECT u.id, u.registered_at,
           u.registered_at + INTERVAL '30 days' <= :reference_date AS observed,
           EXISTS (
               SELECT 1 FROM analytics.orders AS o
               WHERE o.user_id = u.id AND o.status = 'completed'
                 AND o.created_at >= u.registered_at
                 AND o.created_at < u.registered_at + INTERVAL '30 days'
           ) AS converted
    FROM analytics.users AS u
    WHERE u.registered_at >= :start AND u.registered_at < :end
)
SELECT COUNT(*) AS cohort_users,
       COUNT(*) FILTER (WHERE converted AND observed) AS converted_users,
       BOOL_AND(observed) AS fully_observed,
       CASE WHEN BOOL_AND(observed)
           THEN COUNT(*) FILTER (WHERE converted)::numeric / NULLIF(COUNT(*), 0)
           ELSE NULL END AS conversion_rate
FROM cohort;
