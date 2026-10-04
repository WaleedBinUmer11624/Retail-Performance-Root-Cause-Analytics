// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_et_supplier_comparison: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_et_supplier_comparison.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"supplier_name", type text},
        {"skus_py", Int64.Type},
        {"skus_cy", Int64.Type},
        {"ranged_cells_py", Int64.Type},
        {"ranged_cells_cy", Int64.Type},
        {"out_cells_py", Int64.Type},
        {"out_cells_cy", Int64.Type},
        {"full_week_out_cells_py", Int64.Type},
        {"full_week_out_cells_cy", Int64.Type},
        {"sales_revenue_py", type number},
        {"sales_revenue_cy", type number},
        {"est_lost_sales_eur_py", type number},
        {"est_lost_sales_eur_cy", type number},
        {"est_lost_sales_upper_eur_py", type number},
        {"est_lost_sales_upper_eur_cy", type number},
        {"availability_py", type number},
        {"availability_cy", type number},
        {"availability_change_pp", type number},
        {"lost_primary_change", type number},
        {"lost_upper_change", type number},
        {"sales_change", type number},
        {"share_of_lost_primary_change", type number}
    }, "en-US")
in
    Typed
