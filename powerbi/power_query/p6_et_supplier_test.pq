// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_et_supplier_test: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_et_supplier_test.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"supplier", type text},
        {"metric", type text},
        {"supplier_skus", Int64.Type},
        {"other_skus", Int64.Type},
        {"supplier_mean", type number},
        {"other_mean", type number},
        {"difference", type number},
        {"ci_low", type number},
        {"ci_high", type number},
        {"permutation_p_two_sided", type number},
        {"leave_one_sku_out_min", type number},
        {"leave_one_sku_out_max", type number},
        {"supplier_median", type number},
        {"other_median", type number},
        {"supplier_skus_worse_than_other_median", Int64.Type},
        {"variant", type text}
    }, "en-US")
in
    Typed
