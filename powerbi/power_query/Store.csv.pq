// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Store: CSV route (no SQL Server). File written by python -m src.powerbi.run_phase7 --extract
let
    Source = Csv.Document(File.Contents(ModelFolder & "\store.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"store_key", Int64.Type},
        {"store_id", type text},
        {"store_name", type text},
        {"store_label", type text},
        {"town", type text},
        {"county", type text},
        {"region", type text},
        {"store_format", type text},
        {"floor_area_m2", Int64.Type},
        {"open_date", type date},
        {"weekly_trading_hours", Int64.Type},
        {"is_unknown", Int64.Type}
    }, "en-US")
in
    Typed
