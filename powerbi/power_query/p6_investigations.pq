// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_investigations: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_investigations.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"priority", Int64.Type},
        {"topic", type text},
        {"driver_id", type text},
        {"evidence_level", type text},
        {"known", type text},
        {"unknown", type text},
        {"why_it_matters", type text},
        {"slice_of_decline_eur", type number},
        {"data_required", type text},
        {"proposed_owner", type text},
        {"owner_note", type text}
    }, "en-US")
in
    Typed
