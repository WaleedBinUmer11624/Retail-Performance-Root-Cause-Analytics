// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_et_range_distribution: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_et_range_distribution.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"supplier_name", type text},
        {"sku_status", type text},
        {"skus_py", type number},
        {"skus_cy", type number},
        {"ranged_cells_py", type number},
        {"ranged_cells_cy", type number},
        {"sales_py", type number},
        {"sales_cy", type number},
        {"sales_change", type number},
        {"distribution_effect", type number},
        {"rate_effect", type number}
    }, "en-US")
in
    Typed
