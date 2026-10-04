// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_et_episodes: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_et_episodes.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"supplier_name", type text},
        {"retail_year", Int64.Type},
        {"episodes", Int64.Type},
        {"mean_weeks_out", type number},
        {"median_weeks_out", type number},
        {"max_weeks_out", Int64.Type},
        {"share_4plus_weeks", type number},
        {"full_weeks_out", Int64.Type}
    }, "en-US")
in
    Typed
