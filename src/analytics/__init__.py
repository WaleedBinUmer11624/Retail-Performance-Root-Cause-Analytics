"""Phase 5: exploratory business analysis and diagnostic analytics.

Reads ONLY the Phase 4 governed model (built from the frozen Phase 3 curated data) plus the Phase 4
reconciliation benchmark. Evaluation-only assets are refused by model_access and checked by tests.

Modules
    model_access       input whitelist, freeze manifest, model engine, diagnostic SQL runner
    period_comparison  H2 week alignment, headline KPIs, weekly trend profile, headline reconciliation
    contribution       YoY, contribution (pp), share of decline, Shapley revenue bridge
    diagnostics        returns, availability and estimated lost sales, promotions, targets, associations
    evidence           BRD 6.2 evidence levels and the investigation shortlist
    figures            report charts
    reporting          executive summary and validation report
    run_phase5         the command-line runner
"""
