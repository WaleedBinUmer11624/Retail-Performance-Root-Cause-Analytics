// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_et_weekly_timeline: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_et_weekly_timeline.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"retail_week", Int64.Type},
        {"availability_category_cy", type number},
        {"availability_supplier_cy", type number},
        {"availability_other_suppliers_cy", type number},
        {"category_sales_cy", type number},
        {"supplier_sales_cy", type number},
        {"lost_primary_cy", type number},
        {"lost_upper_cy", type number},
        {"availability_category_py", type number},
        {"availability_supplier_py", type number},
        {"availability_other_suppliers_py", type number},
        {"category_sales_py", type number},
        {"supplier_sales_py", type number},
        {"lost_primary_py", type number},
        {"lost_upper_py", type number},
        {"category_sales_yoy_pct", type number},
        {"supplier_sales_yoy_pct", type number}
    }, "en-US")
in
    Typed
