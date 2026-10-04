// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Date: CSV route (no SQL Server). File written by python -m src.powerbi.run_phase7 --extract
let
    Source = Csv.Document(File.Contents(ModelFolder & "\date.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"date_key", Int64.Type},
        {"calendar_date", type date},
        {"day_of_week", Int64.Type},
        {"day_name", type text},
        {"is_weekend", Int64.Type},
        {"calendar_month", Int64.Type},
        {"month_name", type text},
        {"year_month", Int64.Type},
        {"calendar_year", Int64.Type},
        {"retail_year", Int64.Type},
        {"retail_week", Int64.Type},
        {"retail_week_key", Int64.Type},
        {"retail_week_label", type text},
        {"retail_week_start", type date},
        {"retail_half", type text},
        {"period_label", type text},
        {"period_sort", Int64.Type},
        {"is_bank_holiday", Int64.Type},
        {"is_trading_day", Int64.Type},
        {"same_day_last_year_key", Int64.Type},
        {"is_unknown", Int64.Type}
    }, "en-US")
in
    Typed
