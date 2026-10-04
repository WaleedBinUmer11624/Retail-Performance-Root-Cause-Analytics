"""Phase 6: root-cause investigation and causal diagnostics.

Builds on the frozen Phase 5 diagnosis. Reads only the governed Phase 4 model (mart.*, dw.*), the
Phase 5 diagnostic views (diag.*) and its own views (rca.*), plus the Phase 4/5 hand-off files listed in
config/rca_config.yaml. Evaluation-only assets are refused (src/rca/access.py) and tested.

Modules
    access          whitelist, Phase 1-5 freeze, model, SQL runner, data loading
    stats           change points, difference-in-differences, bootstrap and permutation helpers
    store_cluster   S03/S04/S05 investigation with matched controls
    electronics     Electronics & Tech decline, stock-out episodes, supplier comparison
    returns_rca     Faulty-return concentration by product, supplier, store, cohort and lag
    promotions_rca  Home & Kitchen promotion counterfactuals
    overlap         driver overlap matrix and the mutually exclusive attribution
    scenarios       analytical counterfactual scenarios (not forecasts)
    sensitivity     alternative assumptions for every estimate
    evidence        root-cause evidence matrix (BRD evidence levels)
    figures, report, run_phase6
"""
