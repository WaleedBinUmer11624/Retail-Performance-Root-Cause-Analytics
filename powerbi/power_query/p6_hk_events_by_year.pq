// Parameters (Home > Transform data > Manage parameters):
//   ServerName   (Text)  e.g. localhost
//   DatabaseName (Text)  BrightwaterRetail
//   ModelFolder  (Text)  full path of data\powerbi (CSV route only)
//   AnalyticsFolder (Text) full path of powerbi\data

// p6_hk_events_by_year: validated Phase 5/6 table (see powerbi/data/extract_manifest.csv). Disconnected: no relationships.
let
    Source = Csv.Document(File.Contents(AnalyticsFolder & "\p6_hk_events_by_year.csv"),
                          [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"retail_year", Int64.Type},
        {"events", Int64.Type},
        {"promo_period_revenue", type number},
        {"baseline_revenue", type number},
        {"incremental_revenue", type number},
        {"post_dip_revenue", type number},
        {"discount_cost", type number},
        {"incremental_promo_margin", type number},
        {"uplift_pct", type number},
        {"nonpromo_ratio_no_promo_weeks", type number},
        {"nonpromo_ratio_promo_weeks", type number},
        {"cannibalised_revenue", type number},
        {"store_weeks_with_promo_share", type number},
        {"net_programme_revenue", type number}
    }, "en-US")
in
    Typed
