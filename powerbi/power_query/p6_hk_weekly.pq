// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_hk_weekly: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_hk_weekly.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"retail_week", Int64.Type},
        {"sales_revenue_cy", type number},
        {"sales_revenue_py", type number},
        {"counterfactual_m1", type number},
        {"promo_coverage_cy", type number},
        {"promo_coverage_py", type number},
        {"discount_depth_cy", type number},
        {"discount_depth_py", type number}
    }, "en-US")
in
    Typed
