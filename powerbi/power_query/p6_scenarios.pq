// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_scenarios: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_scenarios.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"scenario", type text},
        {"name", type text},
        {"question", type text},
        {"revenue_impact_eur", type number},
        {"range_low_eur", type number},
        {"range_high_eur", type number},
        {"margin_impact_eur", type number},
        {"assumptions", type text},
        {"confidence", type text},
        {"evidence_level", type text},
        {"robust_in_sensitivity", type logical},
        {"share_of_decline_recovered", type number}
    }, "en-US")
in
    Typed
