// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Returns: CSV route (no SQL Server). File written by python -m src.powerbi.run_phase7 --extract
let
    Source = Csv.Document(File.Contents(ModelFolder & "\returns.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"return_id", type text},
        {"return_date_key", Int64.Type},
        {"store_key", Int64.Type},
        {"product_key", Int64.Type},
        {"original_sale_date_key", Int64.Type},
        {"return_quantity", Int64.Type},
        {"refund_value", Currency.Type},
        {"restock_cost_credit", Currency.Type},
        {"return_reason", type text},
        {"is_restockable", Int64.Type},
        {"is_linked_to_sale", Int64.Type},
        {"sale_promotion_status", type text}
    }, "en-US")
in
    Typed
