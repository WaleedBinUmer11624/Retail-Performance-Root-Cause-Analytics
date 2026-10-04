// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_cluster_onset: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_cluster_onset.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"series", type text},
        {"onset_date", type text},
        {"step_shift_log", type number},
        {"step_shift_pct", type number},
        {"step_r2", type number},
        {"ramp_days", Int64.Type},
        {"ramp_start", type text},
        {"ramp_end", type text},
        {"bic_step", type number},
        {"bic_ramp", type number},
        {"bic_linear", type number},
        {"best_model", type text},
        {"abrupt", type logical}
    }, "en-US")
in
    Typed
