# Documentation index

Design and decision documents for the Brightwater Retail performance and root-cause analytics
project, in reading order. Each document states what was decided, why, and against which governed
source. No number, evidence label or conclusion is restated here; open the document for that.

| # | Document | What it covers |
|---|---|---|
| 1 | [01_business_requirements.md](01_business_requirements.md) | Business problem, scope, stakeholders, non-functional requirements and delivery plan |
| 2 | [02_data_generation_design.md](02_data_generation_design.md) | Synthetic data generator, planting design, volume and reconciliation rules |
| 3 | [03_data_quality_design.md](03_data_quality_design.md) | Profiling, cleaning, quarantine and the validation gate |
| 4 | [04_data_model_design.md](04_data_model_design.md) | Star schema, staging and transformation layers, governed KPI views |
| 5 | [05_exploratory_analysis.md](05_exploratory_analysis.md) | Exploratory business analysis, the Shapley revenue bridge and segment diagnostics |
| 6 | [06_root_cause_analysis.md](06_root_cause_analysis.md) | Root-cause investigation, counterfactuals, statistical tests and evidence labelling |
| 7 | [07_power_bi_dashboard_design.md](07_power_bi_dashboard_design.md) | Dashboard pages, field and measure bindings, evidence display and the PBIP build |
| 8 | [08_business_action_and_decision_framework.md](08_business_action_and_decision_framework.md) | Evidence-to-action rules, decision gates, owners and prioritisation |
| 9 | [09_monitoring_early_warning.md](09_monitoring_early_warning.md) | Weekly monitoring signals, thresholds and the back-tested early-warning design |
| 10 | [10_forecasting.md](10_forecasting.md) | Rolling-origin back-test, model selection rule and 13-week forecast intervals |
| 11 | [11_genai_assistant.md](11_genai_assistant.md) | Evidence-grounded AI assistant: tools, retrieval, grounding, guardrails and limits |
| | [known_issues.md](known_issues.md) | Open findings, their status and what was or was not done about each |
| | [python_3_14_compatibility.md](python_3_14_compatibility.md) | Python 3.14 compatibility audit, scope and change control |

Dashboard page 9 (Data quality) postdates document 7, which is frozen. It is built by
`tmp/build_pbip.py` from read-only copies of the Phase 3 and Phase 9 data-quality outputs in
`powerbi/dq_data/` (folder parameter `DqFolder`) and is checked by `tmp/validate_pbip.py` section 10c.

## Appendix

| Document | Contents |
|---|---|
| [appendix/phase9_archive_comparison.csv](appendix/phase9_archive_comparison.csv) | Per-file SHA-256 comparison of the restored working tree against the Phase 9 freeze archive |

Related assets: [04_star_schema.mmd](04_star_schema.mmd) is the Mermaid source for the star schema
diagram in document 4.