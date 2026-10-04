// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Promotion: CSV route (no SQL Server). File written by python -m src.powerbi.run_phase7 --extract
let
    Source = Csv.Document(File.Contents(ModelFolder & "\promotion.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"promotion_key", Int64.Type},
        {"promotion_id", type text},
        {"promotion_name", type text},
        {"promotion_type", type text},
        {"promotion_category", type text},
        {"start_date", type date},
        {"end_date", type date},
        {"duration_days", Int64.Type},
        {"min_discount_pct", type number},
        {"max_discount_pct", type number},
        {"member_type", type text},
        {"is_unknown", Int64.Type}
    }, "en-US")
in
    Typed
