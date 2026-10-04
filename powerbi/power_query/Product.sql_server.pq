// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// Product: SQL Server route (recommended). Import mode.
let
    Source = Sql.Database(ServerName, DatabaseName),
    Data = Source{[Schema = "pbi", Item = "dim_product"]}[Data],
    Typed = Table.TransformColumnTypes(Data, {
        {"product_key", Int64.Type},
        {"product_id", type text},
        {"product_name", type text},
        {"product_label", type text},
        {"category", type text},
        {"subcategory", type text},
        {"brand", type text},
        {"supplier_id", type text},
        {"supplier_name", type text},
        {"list_price", Currency.Type},
        {"product_status", type text},
        {"is_unknown", Int64.Type}
    })
in
    Typed
