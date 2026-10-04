// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Store: SQL Server route (recommended). Import mode.
let
    Source = Sql.Database(ServerName, DatabaseName),
    Data = Source{[Schema = "pbi", Item = "dim_store"]}[Data],
    Typed = Table.TransformColumnTypes(Data, {
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
    })
in
    Typed
