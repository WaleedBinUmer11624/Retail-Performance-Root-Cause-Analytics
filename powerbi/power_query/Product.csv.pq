// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Product: CSV route (no SQL Server). File written by python -m src.powerbi.run_phase7 --extract
let
    Source = Csv.Document(File.Contents(ModelFolder & "\product.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"product_key", Int64.Type},
        {"product_id", type text},
        {"product_name", type text},
        {"product_label", type text},
        {"category", type text},
        {"subcategory", type text},
        {"brand", type text},
        {"supplier_id", type text},
        {"supplier_name", type text},
        {"list_price", Currency.Type},
        {"product_status", type text},
        {"is_unknown", Int64.Type}
    }, "en-US")
in
    Typed
