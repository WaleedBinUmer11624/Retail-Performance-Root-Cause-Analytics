// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_et_sku_stockouts: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_et_sku_stockouts.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"product_id", type text},
        {"supplier_name", type text},
        {"cells_py", type number},
        {"cells_cy", type number},
        {"out_py", type number},
        {"out_cy", type number},
        {"full_py", type number},
        {"full_cy", type number},
        {"revenue_py", type number},
        {"revenue_cy", type number},
        {"units_py", type number},
        {"units_cy", type number},
        {"est_lost_sales_eur_py", type number},
        {"est_lost_sales_eur_cy", type number},
        {"est_lost_sales_upper_eur_py", type number},
        {"est_lost_sales_upper_eur_cy", type number},
        {"oos_rate_py", type number},
        {"oos_rate_cy", type number},
        {"oos_rate_change_pp", type number},
        {"lost_primary_change", type number},
        {"prior_year_revenue_rank", Int64.Type},
        {"high_seller", type logical}
    }, "en-US")
in
    Typed
