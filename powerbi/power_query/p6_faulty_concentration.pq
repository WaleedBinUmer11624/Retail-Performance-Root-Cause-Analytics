// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_faulty_concentration: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_faulty_concentration.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"dimension", type text},
        {"entities", Int64.Type},
        {"entities_with_increase", Int64.Type},
        {"net_increase", type number},
        {"gross_increase", type number},
        {"top_k", Int64.Type},
        {"top_k_share_of_gross", type number},
        {"top_entities", type text},
        {"hhi_of_increase", type number},
        {"entities_significant_p01", Int64.Type}
    }, "en-US")
in
    Typed
