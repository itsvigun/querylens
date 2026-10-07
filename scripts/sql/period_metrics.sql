-- UTC half-open window [start, end); one row even for an empty period.
WITH purchases AS (
    SELECT COALESCE(SUM(amount), 0) AS revenue,
           COUNT(*) AS completed_orders,
           COUNT(DISTINCT user_id) AS paying_users
    FROM analytics.orders
    WHERE status = 'completed' AND created_at >= :start AND created_at < :end
), activity AS (
    SELECT COUNT(DISTINCT user_id) AS active_users
    FROM analytics.events
    WHERE event_type = 'session' AND created_at >= :start AND created_at < :end
)
SELECT revenue, completed_orders, paying_users, active_users,
       revenue / NULLIF(active_users, 0) AS arpu,
       revenue / NULLIF(paying_users, 0) AS arppu
FROM purchases CROSS JOIN activity;
