// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_hk_methods: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_hk_methods.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"sort_order", Int64.Type},
        {"method_code", type text},
        {"method", type text},
        {"effect_eur", type number},
        {"ci_low", type number},
        {"ci_high", type number},
        {"interval_type", type text},
        {"direction", type text},
        {"detail", type text}
    }, "en-US")
in
    Typed
