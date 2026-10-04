// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_cluster_did: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_cluster_did.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"control_group", type text},
        {"outcome", type text},
        {"did_log", type number},
        {"did_pct", type number},
        {"pre_gap_mean_log", type number},
        {"post_gap_mean_log", type number},
        {"pre_trend_slope", type number},
        {"pre_trend_p", type number},
        {"ratio_did_actual", type number},
        {"ratio_did_counterfactual", type number},
        {"ratio_did_excess", type number},
        {"control_yoy", type number},
        {"pre_gap_ratio", type number}
    }, "en-US")
in
    Typed
