// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_driver_attribution: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_driver_attribution.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"sort_order", Int64.Type},
        {"driver_id", type text},
        {"component", type text},
        {"waterfall_label", type text},
        {"driver", type text},
        {"amount_eur", type number},
        {"share_of_change", type number},
        {"overlap_removed_eur", type number},
        {"evidence_level", type text},
        {"evidence_display", type text},
        {"figure_type", type text},
        {"basis", type text}
    }, "en-US")
in
    Typed
