// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Targets: SQL Server route (recommended). Import mode.
let
    Source = Sql.Database(ServerName, DatabaseName),
    Data = Source{[Schema = "pbi", Item = "fact_targets"]}[Data],
    Typed = Table.TransformColumnTypes(Data, {
        {"retail_week_key", Int64.Type},
        {"store_key", Int64.Type},
        {"target_net_revenue", Currency.Type}
    })
in
    Typed
