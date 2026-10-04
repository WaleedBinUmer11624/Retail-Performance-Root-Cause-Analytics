// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Sales: SQL Server route (recommended). Import mode.
let
    Source = Sql.Database(ServerName, DatabaseName),
    Data = Source{[Schema = "pbi", Item = "fact_sales"]}[Data],
    Typed = Table.TransformColumnTypes(Data, {
        {"sales_line_id", Int64.Type},
        {"date_key", Int64.Type},
        {"store_key", Int64.Type},
        {"product_key", Int64.Type},
        {"promotion_key", Int64.Type},
        {"transaction_key", Int64.Type},
        {"quantity", Int64.Type},
        {"gross_amount", Currency.Type},
        {"discount_amount", Currency.Type},
        {"sales_revenue", Currency.Type},
        {"cost_amount", Currency.Type},
        {"is_promoted", Int64.Type}
    })
in
    Typed
