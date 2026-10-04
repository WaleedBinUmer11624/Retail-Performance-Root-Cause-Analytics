// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Inventory: SQL Server route (recommended). Import mode.
let
    Source = Sql.Database(ServerName, DatabaseName),
    Data = Source{[Schema = "pbi", Item = "fact_inventory"]}[Data],
    Typed = Table.TransformColumnTypes(Data, {
        {"snapshot_date_key", Int64.Type},
        {"retail_week_key", Int64.Type},
        {"store_key", Int64.Type},
        {"product_key", Int64.Type},
        {"opening_stock", Int64.Type},
        {"received_qty", Int64.Type},
        {"closing_stock", Int64.Type},
        {"is_in_stock", Int64.Type},
        {"is_full_week_stockout", Int64.Type}
    })
in
    Typed
