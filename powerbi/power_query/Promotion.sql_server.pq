// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Promotion: SQL Server route (recommended). Import mode.
let
    Source = Sql.Database(ServerName, DatabaseName),
    Data = Source{[Schema = "pbi", Item = "dim_promotion"]}[Data],
    Typed = Table.TransformColumnTypes(Data, {
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
    })
in
    Typed
