// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p5_revenue_bridge: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p5_revenue_bridge.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"step", type text},
        {"value_eur", type number},
        {"kind", type text},
        {"running_total_eur", type number},
        {"contribution_pp", type number},
        {"share_of_change", type number},
        {"method_note", type text}
    }, "en-US")
in
    Typed
