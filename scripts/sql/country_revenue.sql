SELECT u.country, COUNT(*) AS completed_orders, SUM(o.amount) AS revenue
FROM analytics.orders AS o
JOIN analytics.users AS u ON u.id = o.user_id
WHERE o.status = 'completed' AND o.created_at >= :start AND o.created_at < :end
GROUP BY u.country
ORDER BY u.country;
