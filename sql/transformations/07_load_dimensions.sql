/* =====================================================================
   07  Load dimensions from staging
   ---------------------------------------------------------------------
   Source: stg.* (the approved Phase 3 curated files, loaded as text).
   Re-runnable: facts are emptied first (they reference the dimensions),
   then dimensions are reloaded in dependency order.

   Surrogate keys are deterministic: ROW_NUMBER() over the natural key.
   UNKNOWN members use key -1 (and promotion key 0 = "No promotion").
   ===================================================================== */

SET NOCOUNT ON;
TRUNCATE TABLE dw.fact_sales;               -- facts: no foreign key points at them, so TRUNCATE is allowed
TRUNCATE TABLE dw.fact_returns;
TRUNCATE TABLE dw.fact_inventory;
TRUNCATE TABLE dw.fact_targets;
TRUNCATE TABLE dw.fact_promotion_coverage;
DELETE FROM dw.dim_date;                    -- dimensions are referenced: DELETE
DELETE FROM dw.dim_retail_week;
DELETE FROM dw.dim_store;
DELETE FROM dw.dim_product;
DELETE FROM dw.dim_promotion;
GO

/* ---------------------------------------------------------------- dim_retail_week */
SET NOCOUNT ON;
INSERT INTO dw.dim_retail_week (retail_week_key, retail_year, retail_week, retail_week_label, week_start_date,
                                week_end_date, days_in_week, retail_half, is_comparable_week, prior_year_week_key, is_unknown)
VALUES (-1, NULL, NULL, N'Unknown', NULL, NULL, NULL, NULL, 0, NULL, 1);

INSERT INTO dw.dim_retail_week (retail_week_key, retail_year, retail_week, retail_week_label, week_start_date,
                                week_end_date, days_in_week, retail_half, is_comparable_week, prior_year_week_key, is_unknown)
SELECT CAST(w.retail_year AS INT) * 100 + w.retail_week,
       w.retail_year,
       w.retail_week,
       CONCAT(w.retail_year, N'-W', RIGHT(CONCAT(N'0', w.retail_week), 2)),
       w.week_start_date,
       w.week_end_date,
       w.days_in_week,
       w.retail_half,
       CASE WHEN w.days_in_week = 7 AND w.retail_year IN (2024, 2025) THEN 1 ELSE 0 END,
       (CAST(w.retail_year AS INT) - 1) * 100 + w.retail_week,
       0
FROM (
    SELECT d.retail_year, d.retail_week,
           MIN(d.calendar_date) AS week_start_date,
           MAX(d.calendar_date) AS week_end_date,
           COUNT(*)             AS days_in_week,
           MAX(d.retail_half)   AS retail_half
    FROM (
        SELECT TRY_CONVERT(SMALLINT, retail_year) AS retail_year,
               TRY_CONVERT(TINYINT, retail_week)  AS retail_week,
               TRY_CONVERT(DATE, [date])          AS calendar_date,
               retail_half
        FROM stg.dim_date
    ) AS d
    GROUP BY d.retail_year, d.retail_week
) AS w;
GO

/* ---------------------------------------------------------------- dim_date */
SET NOCOUNT ON;
INSERT INTO dw.dim_date (date_key, calendar_date, day_of_week, day_name, is_weekend, calendar_month, month_name, year_month,
                         calendar_quarter, calendar_year, retail_year, retail_week, retail_week_key, retail_week_start,
                         retail_half, is_bank_holiday, holiday_name, is_trading_day, same_day_last_year,
                         same_day_last_year_key, is_unknown)
VALUES (-1, NULL, NULL, N'Unknown', NULL, NULL, N'Unknown', NULL, NULL, NULL, NULL, NULL, -1, NULL, NULL, NULL, NULL,
        NULL, NULL, NULL, 1);

INSERT INTO dw.dim_date (date_key, calendar_date, day_of_week, day_name, is_weekend, calendar_month, month_name, year_month,
                         calendar_quarter, calendar_year, retail_year, retail_week, retail_week_key, retail_week_start,
                         retail_half, is_bank_holiday, holiday_name, is_trading_day, same_day_last_year,
                         same_day_last_year_key, is_unknown)
SELECT TRY_CONVERT(INT, s.date_key),
       TRY_CONVERT(DATE, s.[date]),
       TRY_CONVERT(TINYINT, s.day_of_week),
       s.day_name,
       CASE WHEN s.is_weekend = N'True' THEN 1 ELSE 0 END,
       TRY_CONVERT(TINYINT, s.calendar_month),
       s.month_name,
       TRY_CONVERT(INT, s.calendar_year) * 100 + TRY_CONVERT(INT, s.calendar_month),
       TRY_CONVERT(TINYINT, s.calendar_quarter),
       TRY_CONVERT(SMALLINT, s.calendar_year),
       TRY_CONVERT(SMALLINT, s.retail_year),
       TRY_CONVERT(TINYINT, s.retail_week),
       TRY_CONVERT(INT, s.retail_year) * 100 + TRY_CONVERT(INT, s.retail_week),
       TRY_CONVERT(DATE, s.retail_week_start),
       s.retail_half,
       CASE WHEN s.is_bank_holiday = N'True' THEN 1 ELSE 0 END,
       s.holiday_name,
       CASE WHEN s.is_trading_day = N'True' THEN 1 ELSE 0 END,
       TRY_CONVERT(DATE, s.same_day_last_year),
       TRY_CONVERT(INT, REPLACE(s.same_day_last_year, N'-', N'')),
       0
FROM stg.dim_date AS s;
GO

/* ---------------------------------------------------------------- dim_store */
SET NOCOUNT ON;
INSERT INTO dw.dim_store (store_key, store_id, store_name, town, county, region, store_format, floor_area_m2, open_date,
                          manager_name, headcount_fte, weekly_trading_hours, latitude, longitude, is_unknown, source_row)
VALUES (-1, N'UNKNOWN', N'Unknown store', NULL, NULL, N'Unknown', N'Unknown', NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, NULL);

INSERT INTO dw.dim_store (store_key, store_id, store_name, town, county, region, store_format, floor_area_m2, open_date,
                          manager_name, headcount_fte, weekly_trading_hours, latitude, longitude, is_unknown, source_row)
SELECT ROW_NUMBER() OVER (ORDER BY s.store_id),
       s.store_id,
       s.store_name,
       s.town,
       s.county,
       s.region,
       s.store_format,
       TRY_CONVERT(INT, s.floor_area_m2),
       TRY_CONVERT(DATE, s.open_date),
       s.manager_name,
       TRY_CONVERT(DECIMAL(6,1), s.headcount_fte),
       TRY_CONVERT(SMALLINT, s.weekly_trading_hours),
       TRY_CONVERT(DECIMAL(9,4), s.latitude),
       TRY_CONVERT(DECIMAL(9,4), s.longitude),
       0,
       TRY_CONVERT(INT, s.source_row)
FROM stg.dim_store AS s;
GO

/* ---------------------------------------------------------------- dim_product */
-- The curated UNKNOWN product (created by Phase 3 for unidentifiable sales
-- lines) becomes member -1; real products are numbered from 1.
SET NOCOUNT ON;
INSERT INTO dw.dim_product (product_key, product_id, product_name, category, subcategory, brand, supplier_id, supplier_name,
                            list_price, unit_cost, launch_date, discontinued_date, product_status, is_unknown, source_row)
SELECT CASE WHEN s.product_id = N'UNKNOWN' THEN -1
            ELSE ROW_NUMBER() OVER (PARTITION BY CASE WHEN s.product_id = N'UNKNOWN' THEN 1 ELSE 0 END
                                    ORDER BY s.product_id) END,
       s.product_id,
       s.product_name,
       s.category,
       s.subcategory,
       s.brand,
       s.supplier_id,
       s.supplier_name,
       TRY_CONVERT(DECIMAL(10,2), s.list_price),
       TRY_CONVERT(DECIMAL(10,2), s.unit_cost),
       TRY_CONVERT(DATE, s.launch_date),
       TRY_CONVERT(DATE, s.discontinued_date),
       s.status,
       CASE WHEN s.product_id = N'UNKNOWN' THEN 1 ELSE 0 END,
       TRY_CONVERT(INT, s.source_row)
FROM stg.dim_product AS s;

-- Guard: the UNKNOWN member must exist even if a future curated file has no UNKNOWN product row.
INSERT INTO dw.dim_product (product_key, product_id, product_name, category, subcategory, brand, supplier_id, supplier_name,
                            list_price, unit_cost, launch_date, discontinued_date, product_status, is_unknown, source_row)
SELECT -1, N'UNKNOWN', N'Unknown product', N'Unknown', N'Unknown', N'Unknown', N'UNKNOWN', N'Unknown supplier',
       NULL, NULL, NULL, NULL, N'Unknown', 1, NULL
WHERE NOT EXISTS (SELECT 1 FROM dw.dim_product WHERE product_key = -1);
GO

/* ---------------------------------------------------------------- dim_promotion */
-- Header per promotion_id from the promotion scope file; category comes
-- from the covered products (a promotion event is run per category).
SET NOCOUNT ON;
INSERT INTO dw.dim_promotion (promotion_key, promotion_id, promotion_name, promotion_type, promotion_category, start_date,
                              end_date, duration_days, min_discount_pct, max_discount_pct, stores_covered, products_covered,
                              member_type, is_unknown)
VALUES (0,  N'NONE',    N'No promotion',      N'None',    N'None',    NULL, NULL, NULL, NULL, NULL, NULL, NULL, N'No promotion', 0),
       (-1, N'UNKNOWN', N'Unknown promotion', N'Unknown', N'Unknown', NULL, NULL, NULL, NULL, NULL, NULL, NULL, N'Unknown',      1);

INSERT INTO dw.dim_promotion (promotion_key, promotion_id, promotion_name, promotion_type, promotion_category, start_date,
                              end_date, duration_days, min_discount_pct, max_discount_pct, stores_covered, products_covered,
                              member_type, is_unknown)
SELECT ROW_NUMBER() OVER (ORDER BY h.promotion_id),
       h.promotion_id,
       h.promotion_name,
       h.promotion_type,
       h.promotion_category,
       h.start_date,
       h.end_date,
       DATEDIFF(day, h.start_date, h.end_date) + 1,
       h.min_discount_pct,
       h.max_discount_pct,
       h.stores_covered,
       h.products_covered,
       N'Promotion',
       0
FROM (
    SELECT p.promotion_id,
           MAX(p.promotion_name)                              AS promotion_name,
           MAX(p.promotion_type)                              AS promotion_type,
           CASE WHEN COUNT(DISTINCT dp.category) = 1 THEN MAX(dp.category) ELSE N'Mixed' END AS promotion_category,
           MIN(TRY_CONVERT(DATE, p.start_date))               AS start_date,
           MAX(TRY_CONVERT(DATE, p.end_date))                 AS end_date,
           MIN(TRY_CONVERT(DECIMAL(5,4), p.discount_pct))     AS min_discount_pct,
           MAX(TRY_CONVERT(DECIMAL(5,4), p.discount_pct))     AS max_discount_pct,
           COUNT(DISTINCT p.store_id)                         AS stores_covered,
           COUNT(DISTINCT p.product_id)                       AS products_covered
    FROM stg.fact_promotions AS p
    LEFT JOIN dw.dim_product AS dp ON dp.product_id = p.product_id
    GROUP BY p.promotion_id
) AS h;
GO
