// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_faulty_by_product: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_faulty_by_product.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"product_id", type text},
        {"returned_units_py", type number},
        {"returned_units_cy", type number},
        {"returns_value_py", type number},
        {"returns_value_cy", type number},
        {"units_sold_py", type number},
        {"units_sold_cy", type number},
        {"rate_per_100_py", type number},
        {"rate_per_100_cy", type number},
        {"expected_units_cy_at_py_rate", type number},
        {"excess_units", type number},
        {"excess_value_eur", type number},
        {"p_increase", type number},
        {"value_change", type number}
    }, "en-US")
in
    Typed
