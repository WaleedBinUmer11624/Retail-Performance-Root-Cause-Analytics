// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Inventory: CSV route (no SQL Server). File written by python -m src.powerbi.run_phase7 --extract
let
    Source = Csv.Document(File.Contents(ModelFolder & "\inventory.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"snapshot_date_key", Int64.Type},
        {"retail_week_key", Int64.Type},
        {"store_key", Int64.Type},
        {"product_key", Int64.Type},
        {"opening_stock", Int64.Type},
        {"received_qty", Int64.Type},
        {"closing_stock", Int64.Type},
        {"is_in_stock", Int64.Type},
        {"is_full_week_stockout", Int64.Type}
    }, "en-US")
in
    Typed
