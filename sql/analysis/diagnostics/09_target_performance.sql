/* =====================================================================
   Phase 5 diagnostics 09: target performance
   ---------------------------------------------------------------------
   BRD 5.4 / BR-08 / Q9:
     Target Achievement %       = Net Revenue / Target Revenue
     Revenue Variance to Target = Net Revenue - Target Revenue
     Target Miss Streak         = consecutive weeks below 100% of target
     Persistent underperformance: target missed in 8 or more of the last
     13 weeks (BRD Q9; threshold held in config/analytics_config.yaml and
     applied in Python; the view exposes the counts).
   Weeks without a target are excluded (neither hit nor miss) and they
   break a streak, because the week cannot be judged.
   A missed target is an OUTCOME. It says nothing about why.
   ===================================================================== */

-- Store x H2 week with a target: achievement, variance, miss flag and streak group
CREATE OR ALTER VIEW diag.v_target_store_week AS
SELECT t.*,
       t.retail_week - ROW_NUMBER() OVER (PARTITION BY t.store_key, t.retail_year, t.is_missed ORDER BY t.retail_week) AS streak_group
FROM (
    SELECT w.retail_year, w.retail_week, w.retail_week_key, w.store_key, w.store_id, w.store_name, w.region, w.store_format,
           w.net_revenue, w.target_net_revenue, w.variance_to_target, w.target_achievement_pct,
           CASE WHEN w.net_revenue < w.target_net_revenue THEN 1 ELSE 0 END AS is_missed
    FROM mart.v_performance_store_week AS w
    WHERE w.retail_week BETWEEN 27 AND 52 AND w.target_net_revenue IS NOT NULL
) AS t;
GO

-- Store x retail year (H2) summary: misses, longest streak, last-13-week misses
CREATE OR ALTER VIEW diag.v_target_store_h2 AS
SELECT a.retail_year, a.store_key, a.store_id, a.store_name, a.region, a.store_format,
       a.target_weeks, a.missed_weeks, a.net_revenue, a.target_net_revenue,
       a.net_revenue - a.target_net_revenue AS variance_to_target,
       CAST(a.net_revenue AS FLOAT) / NULLIF(CAST(a.target_net_revenue AS FLOAT), 0) AS target_achievement_pct,
       a.last13_target_weeks, a.last13_missed_weeks,
       COALESCE(s.longest_miss_streak, 0) AS longest_miss_streak
FROM (
    SELECT retail_year, store_key, store_id, store_name, region, store_format,
           COUNT(*) AS target_weeks, SUM(is_missed) AS missed_weeks,
           SUM(net_revenue) AS net_revenue, SUM(target_net_revenue) AS target_net_revenue,
           SUM(CASE WHEN retail_week >= 40 THEN 1 ELSE 0 END)        AS last13_target_weeks,
           SUM(CASE WHEN retail_week >= 40 THEN is_missed ELSE 0 END) AS last13_missed_weeks
    FROM diag.v_target_store_week
    GROUP BY retail_year, store_key, store_id, store_name, region, store_format
) AS a
LEFT JOIN (
    SELECT retail_year, store_key, MAX(streak_length) AS longest_miss_streak
    FROM (
        SELECT retail_year, store_key, streak_group, COUNT(*) AS streak_length
        FROM diag.v_target_store_week
        WHERE is_missed = 1
        GROUP BY retail_year, store_key, streak_group
    ) AS g
    GROUP BY retail_year, store_key
) AS s ON s.retail_year = a.retail_year AND s.store_key = a.store_key;
GO
