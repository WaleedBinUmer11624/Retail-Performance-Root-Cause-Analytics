// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_evidence_matrix: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_evidence_matrix.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"driver_id", type text},
        {"driver", type text},
        {"candidate_driver", type text},
        {"evidence_level", type text},
        {"cause_status", type text},
        {"evidence_display", type text},
        {"evidence_strength", Int64.Type},
        {"evidence_colour", type text},
        {"observed_effect", type text},
        {"financial_impact_eur", type number},
        {"impact_pp_of_py_revenue", type number},
        {"impact_range", type text},
        {"what_we_know", type text},
        {"what_we_do_not_know", type text},
        {"confidence", type text},
        {"method", type text},
        {"additional_data_required", type text},
        {"double_counting_risk", type text},
        {"conclusion", type text},
        {"sort_order", Int64.Type}
    }, "en-US")
in
    Typed
