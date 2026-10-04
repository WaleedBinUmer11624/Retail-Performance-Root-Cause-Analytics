/* =====================================================================
   Phase 5 diagnostics 05: transaction / basket decomposition
   ---------------------------------------------------------------------
   BRD identity:  Sales Revenue = Transactions (T) x UPT (U) x ASP (P)
                  Net Revenue   = Sales Revenue - Returns Value

   The Sales Revenue change is split with the symmetric Shapley method for
   three multiplicative factors (average of each factor's marginal effect
   over all 6 orders in which the factors can be changed). It is exact: the
   three effects add up to the Sales Revenue change with no residual, and
   no factor is favoured by being changed "first".

     effect_T = dT x [ (U0 P0 + U1 P1) / 3 + (U0 P1 + U1 P0) / 6 ]
     effect_U = dU x [ (T0 P0 + T1 P1) / 3 + (T0 P1 + T1 P0) / 6 ]
     effect_P = dP x [ (T0 U0 + T1 U1) / 3 + (T0 U1 + T1 U0) / 6 ]
     returns effect = -(Returns1 - Returns0)

   The same formula is applied per segment. Segment bridges do NOT add up to
   the estate bridge: the estate ASP and UPT also move when the sales mix
   shifts between stores. Only the net revenue change itself is additive.
   Availability and promotions are deliberately not forced into this
   identity; scripts 07 and 08 examine them as separate mechanisms.
   The Python layer recomputes every effect independently and checks it
   against these views (reports/phase5/phase5_validation_report.md).
   ===================================================================== */

-- Shapley bridge per segment (Estate, Region, Format, Store)
CREATE OR ALTER VIEW diag.v_basket_bridge_segment AS
SELECT b.segment_type, b.segment_name, b.retail_year,
       b.net_revenue_py, b.net_revenue_cy, b.sales_revenue_py, b.sales_revenue_cy, b.returns_value_py, b.returns_value_cy,
       b.t0 AS transactions_py, b.t1 AS transactions_cy, b.u0 AS upt_py, b.u1 AS upt_cy, b.p0 AS asp_py, b.p1 AS asp_cy,
       (b.t1 - b.t0) * ((b.u0 * b.p0 + b.u1 * b.p1) / 3.0 + (b.u0 * b.p1 + b.u1 * b.p0) / 6.0) AS transactions_effect,
       (b.u1 - b.u0) * ((b.t0 * b.p0 + b.t1 * b.p1) / 3.0 + (b.t0 * b.p1 + b.t1 * b.p0) / 6.0) AS upt_effect,
       (b.p1 - b.p0) * ((b.t0 * b.u0 + b.t1 * b.u1) / 3.0 + (b.t0 * b.u1 + b.t1 * b.u0) / 6.0) AS asp_effect,
       -(CAST(b.returns_value_cy AS FLOAT) - CAST(b.returns_value_py AS FLOAT))               AS returns_effect,
       CAST(b.net_revenue_cy AS FLOAT) - CAST(b.net_revenue_py AS FLOAT)                      AS net_revenue_change
FROM (
    SELECT c.segment_type, c.segment_name, c.retail_year,
           c.net_revenue_py, c.net_revenue_cy, c.sales_revenue_py, c.sales_revenue_cy, c.returns_value_py, c.returns_value_cy,
           CAST(c.transactions_py AS FLOAT) AS t0, CAST(c.transactions_cy AS FLOAT) AS t1,
           c.upt_py AS u0, c.upt_cy AS u1, c.asp_py AS p0, c.asp_cy AS p1
    FROM diag.v_segment_h2_contribution AS c
) AS b;
GO

-- Category bridge: receipts containing the category x units per such receipt x category ASP
CREATE OR ALTER VIEW diag.v_basket_bridge_category AS
SELECT b.category, b.retail_year, b.net_revenue_py, b.net_revenue_cy, b.sales_revenue_py, b.sales_revenue_cy,
       b.returns_value_py, b.returns_value_cy,
       b.t0 AS transactions_with_category_py, b.t1 AS transactions_with_category_cy,
       b.u0 AS units_per_category_transaction_py, b.u1 AS units_per_category_transaction_cy, b.p0 AS asp_py, b.p1 AS asp_cy,
       (b.t1 - b.t0) * ((b.u0 * b.p0 + b.u1 * b.p1) / 3.0 + (b.u0 * b.p1 + b.u1 * b.p0) / 6.0) AS transactions_effect,
       (b.u1 - b.u0) * ((b.t0 * b.p0 + b.t1 * b.p1) / 3.0 + (b.t0 * b.p1 + b.t1 * b.p0) / 6.0) AS upt_effect,
       (b.p1 - b.p0) * ((b.t0 * b.u0 + b.t1 * b.u1) / 3.0 + (b.t0 * b.u1 + b.t1 * b.u0) / 6.0) AS asp_effect,
       -(CAST(b.returns_value_cy AS FLOAT) - CAST(b.returns_value_py AS FLOAT))               AS returns_effect,
       CAST(b.net_revenue_cy AS FLOAT) - CAST(b.net_revenue_py AS FLOAT)                      AS net_revenue_change
FROM (
    SELECT c.category, c.retail_year, c.net_revenue_py, c.net_revenue_cy, c.sales_revenue_py, c.sales_revenue_cy,
           c.returns_value_py, c.returns_value_cy,
           CAST(c.transactions_with_category_py AS FLOAT) AS t0, CAST(c.transactions_with_category_cy AS FLOAT) AS t1,
           CAST(c.units_sold_py AS FLOAT) / NULLIF(CAST(c.transactions_with_category_py AS FLOAT), 0) AS u0,
           CAST(c.units_sold_cy AS FLOAT) / NULLIF(CAST(c.transactions_with_category_cy AS FLOAT), 0) AS u1,
           c.asp_py AS p0, c.asp_cy AS p1
    FROM diag.v_category_h2_contribution AS c
) AS b;
GO

-- Weekly basket KPIs for both periods (when did traffic, basket size or price move?)
CREATE OR ALTER VIEW diag.v_basket_week AS
SELECT w.retail_year, w.retail_week, w.h2_week_index, w.week_start_cy, w.week_start_py,
       w.transactions_py, w.transactions_cy,
       CAST(w.sales_revenue_py AS FLOAT) / NULLIF(CAST(w.transactions_py AS FLOAT), 0) AS aov_py,
       CAST(w.sales_revenue_cy AS FLOAT) / NULLIF(CAST(w.transactions_cy AS FLOAT), 0) AS aov_cy,
       CAST(w.units_sold_py AS FLOAT) / NULLIF(CAST(w.transactions_py AS FLOAT), 0)    AS upt_py,
       CAST(w.units_sold_cy AS FLOAT) / NULLIF(CAST(w.transactions_cy AS FLOAT), 0)    AS upt_cy,
       CAST(w.sales_revenue_py AS FLOAT) / NULLIF(CAST(w.units_sold_py AS FLOAT), 0)   AS asp_py,
       CAST(w.sales_revenue_cy AS FLOAT) / NULLIF(CAST(w.units_sold_cy AS FLOAT), 0)   AS asp_cy
FROM diag.v_h2_week_comparison AS w;
GO
