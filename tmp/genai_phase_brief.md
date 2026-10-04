# GenAI phase brief (Phase 11): preamble plus original brief

## CURRENT STATE (verified by CP1 audit, 2026-10-03)
- Phases 1-10 complete and frozen. 9 protected hash groups recorded in tmp\protected_hash_baseline.txt.
- The Power BI PBIP renders all 12 pages in Desktop. Do NOT touch powerbi\ in this phase.
- Phase 10 selected model: B2_seasonal_naive; forecast CSVs in powerbi\forecast_data\.
- SQL Server: localhost, database BrightwaterRetail, Windows Authentication, ODBC Driver 18.
  There is NO username or password; never invent one. SQL access must be read-only.
- CP1 findings: experimental\ai_layer\ exists and is empty. src\analyst\ already contains a core analyst
  prototype (question parsing, evidence packaging, allowlisted SELECT-template SQL guard).
  Python 3.14.5 in .venv; no LLM or vector-store packages; no .env or .env.example.

## ADDITIONAL HARD RULES (on top of the brief below)
1. EVALUATION ASSETS ARE OFF-LIMITS: never read, index, embed, retrieve or cite
   config\_hidden_scenario.yaml, any _scenario_answer_key*, any _planted_issues_log*, anything under
   evaluation\, or any calibration file. Enforce this in code with a path denylist in every retriever,
   tool and artifact resolver (including any reuse of src\analyst), and add a test proving these paths
   can never be loaded or indexed.
2. Build the AI layer in experimental\ai_layer\. REUSE src\analyst (SQL guard, evidence packaging)
   through imports instead of duplicating it. Do not modify src\analyst unless a change is strictly
   needed; if so, report it first.
3. Mock/offline mode first. No test may require an API key or network. Provide .env.example only.
4. Keep dependencies light and compatible with Python 3.14. Prefer no vector database at first
   (for example a simple local TF-IDF or keyword index); make embeddings optional and configurable.
5. No em dashes in any file you write.
6. Work in checkpoints and STOP after each one with a short report (long runs time out):
   CP1 = sections 0-1 (pre-flight audit; read-only). Already done; just add anything sections 0-1
         require that the first audit missed.
   CP2 = sections 3-8 (schema, provider abstraction, tools, retrieval, provenance)
   CP3 = sections 6, 9-13 and 15-16 (grounding, confidence, modes, forecast, guardrails, mock, logging)
   CP4 = sections 17-18 (evaluation suite and tests; existing suite rerun, one command at a time)
   CP5 = sections 19-20 and 22 (documentation, reproducibility, Power BI boundary), then the
         section 27 final report.
   Section 21 (UI) only after CP5 passes and only if I approve.
7. Run the protected hash check at the end of every checkpoint.

----- ORIGINAL GENAI BRIEF FOLLOWS -----

Continue development of my existing end-to-end project:

PROJECT:
Retail Performance Root Cause Analytics

PROJECT ROOT:
E:\Retail_Performance_Root_Cause_Analytics

We are now starting the previously deferred GENERATIVE AI / LLM PHASE.

This phase was intentionally postponed while Phases 1–10 and the Power BI
dashboard were being completed.

IMPORTANT:
Do not rebuild the analytics project.
Do not replace validated statistical/analytical logic.
Do not modify governed/frozen outputs.
The Generative AI layer must sit ON TOP of the existing analytical evidence
and provide grounded explanations, investigation assistance, and executive
summaries.

Treat this as a production-quality portfolio implementation, not a toy
chatbot or simple API wrapper.

======================================================================
0. PRE-FLIGHT GATE: DO THIS BEFORE IMPLEMENTATION
======================================================================

First audit the repository and establish the actual current state.

Inspect at minimum:

E:\Retail_Performance_Root_Cause_Analytics\

including:

data\
sql\
src\
reports\
tests\
powerbi\
config\
docs\
tmp\

and any manifests, README files, configuration files, requirements,
environment templates, validation outputs, Phase 1–10 artifacts, and
Generative AI files already present.

Do NOT assume this prompt's filenames/counts are authoritative if the
repository differs.

Before creating anything, determine:

1. Which phases are complete.
2. Which files are frozen/governed.
3. Which analytical outputs are authoritative.
4. Current SQL Server architecture and connection mechanism.
5. Current Python environment/dependencies.
6. Existing Phase 6 root-cause artifacts.
7. Existing Phase 10 forecasting artifacts.
8. Existing Power BI semantic-model structure.
9. Whether any Generative AI/RAG code already exists.
10. Whether tests already define requirements for this phase.

SECURITY:
Never hard-code, print, commit, or expose SQL passwords, API keys, tokens,
connection secrets, or other credentials.

If credentials already exist in the repository, do not reproduce their
values in reports/logs. Use environment variables/configuration references.

Create a baseline inventory before writing files.

======================================================================
1. ENTRY CONDITION
======================================================================

Check whether the current Power BI PBIP work is structurally stable.

Current PBIP location:

E:\Retail_Performance_Root_Cause_Analytics\
powerbi\Brightwater_Executive_Dashboard\
Brightwater_Executive_Dashboard.pbip

Do NOT spend this phase redesigning Power BI.

If the PBIP still has a parser/structural error, report it as an independent
known issue, but continue with the Generative AI phase IF the underlying
governed analytical datasets are valid and the AI implementation does not
depend on the PBIP being open.

Do not modify PBIP/TMDL merely to start the AI phase.

======================================================================
2. OBJECTIVE
======================================================================

Build a production-ready Generative AI analytics assistant for the Retail
Performance Root Cause Analytics project.

The assistant should help an analyst/executive ask natural-language
questions such as:

"Why did revenue decline?"

"Which stores contributed most to the decline?"

"Was the decline caused by demand, availability, pricing, promotions,
returns, or another factor?"

"What evidence supports that conclusion?"

"Which products were most affected?"

"Which stores should be investigated?"

"How much revenue was potentially lost because of stockouts?"

"What happened during the identified incident period?"

"What does the Phase 6 evidence matrix show?"

"What are the main drivers of the revenue bridge?"

"What does the forecast show for the next 13 weeks?"

"Which forecast model was selected and why?"

"What are the main risks or uncertainties?"

"Summarise the situation for an executive."

The system must answer from VERIFIED PROJECT EVIDENCE.

It must NOT invent business facts.

======================================================================
3. ARCHITECTURE
======================================================================

Design a modular architecture broadly following:

USER QUESTION
      |
      v
QUERY / INTENT LAYER
      |
      v
RETRIEVAL + ANALYTICS TOOL LAYER
      |
      +---- Structured project evidence
      +---- SQL queries where appropriate
      +---- Governed Phase outputs
      +---- Metadata / metric definitions
      |
      v
EVIDENCE ASSEMBLY
      |
      v
LLM
      |
      v
GROUNDED RESPONSE
      |
      +---- Answer
      +---- Evidence
      +---- Source/provenance
      +---- Confidence / limitations
      +---- Suggested investigation

Do not let the LLM become the calculation engine.

Python/SQL/governed analytical outputs should calculate facts.

The LLM should primarily:
- interpret questions
- select appropriate evidence/tools
- synthesize results
- explain analytical findings
- communicate uncertainty
- generate executive narratives

======================================================================
4. RAG / EVIDENCE LAYER
======================================================================

Implement retrieval over appropriate project documentation and analytical
evidence.

First inventory the actual available artifacts.

Potential evidence may include:

Phase 5 revenue bridge outputs
Phase 6 root-cause evidence
driver attribution
evidence matrix
cluster analysis
onset analysis
stockout analysis
supplier analysis
investigation tables
scenario/sensitivity analysis
returns analysis
promotion analysis
store/product analysis
Phase 10 forecasts
forecast intervals
forecast model comparison
methodology/validation documentation

Do not blindly embed every file.

Classify sources into:

A. structured analytical data
B. textual methodology/documentation
C. metadata/metric definitions
D. validation/evidence artifacts

Use deterministic querying for structured facts whenever practical.

Use vector/semantic retrieval primarily where it adds value for textual
evidence and documentation.

If embeddings are implemented, keep the provider/model configurable.

Do not hard-wire the architecture to one commercial provider.

======================================================================
5. ANALYTICS TOOLS
======================================================================

Create a controlled tool layer so the assistant can retrieve factual
analytical evidence.

Potential tools/functions include, subject to what actually exists in the
repository:

get_revenue_summary()
get_revenue_bridge()
get_driver_attribution()
get_evidence_matrix()
get_store_performance()
get_product_performance()
get_stockout_analysis()
get_returns_analysis()
get_promotion_analysis()
get_cluster_analysis()
get_supplier_analysis()
get_investigation_evidence()
get_forecast()
get_forecast_intervals()
get_forecast_model_comparison()
get_metric_definition()

Prefer explicit, deterministic interfaces.

Validate inputs.

Return structured outputs.

Do NOT give the LLM unrestricted arbitrary SQL execution.

If natural-language-to-SQL functionality is implemented, make it
read-only and heavily constrained:
- SELECT only
- approved schemas/tables only
- row/result limits
- query validation
- timeout
- no DDL
- no DML
- no stored-procedure execution
- no filesystem commands
- no credential exposure

======================================================================
6. GROUNDING AND ANTI-HALLUCINATION
======================================================================

This is a mandatory production requirement.

Every substantive business conclusion should be traceable to retrieved
project evidence.

The assistant must distinguish:

OBSERVED FACT
CALCULATED RESULT
MODEL/STATISTICAL EVIDENCE
INFERENCE
FORECAST
LIMITATION

Never turn correlation into causation automatically.

If Phase 6 evidence supports association rather than causal identification,
say so.

If evidence is insufficient, answer explicitly:

"Insufficient evidence to determine this from the available project data."

Do not manufacture:
- percentages
- revenue values
- store names
- products
- dates
- drivers
- forecast values
- confidence levels

If a requested fact is unavailable, say so.

======================================================================
7. RESPONSE CONTRACT
======================================================================

Design a structured response schema.

A useful response should contain fields equivalent to:

answer
executive_summary
evidence
sources
confidence
limitations
recommended_follow_up

Where appropriate include:

metric
value
comparison_period
driver
contribution
store
product
date_range
forecast_horizon

The exact schema can be improved during implementation.

It must be machine-readable and suitable for later integration with an
application or Power BI.

======================================================================
8. SOURCE PROVENANCE
======================================================================

Implement explicit provenance.

For each retrieved fact, retain enough metadata to identify its origin,
for example:

source_file
table
record/filter
metric
phase
generated_at
retrieval_method

Responses should be capable of showing statements such as:

Source:
Phase 6 driver attribution

Source:
Phase 6 evidence matrix

Source:
Phase 10 forecast output

Do not expose internal secrets or irrelevant filesystem details to
end users.

======================================================================
9. CONFIDENCE / EVIDENCE STRENGTH
======================================================================

Do NOT let the LLM invent a confidence percentage.

If the project already contains governed evidence-strength logic, use it.

Otherwise use transparent categories based on deterministic rules, such as:

Strong evidence
Moderate evidence
Limited evidence
Insufficient evidence

Document exactly how these categories are derived.

If no defensible confidence mechanism exists, state limitations instead of
fabricating confidence.

======================================================================
10. EXECUTIVE ANALYTICS MODE
======================================================================

Provide an executive-summary capability.

Example question:

"Give me the executive summary of the revenue decline."

A good response should explain:

WHAT happened
WHEN it happened
WHERE it was concentrated
WHICH drivers have supporting evidence
HOW LARGE the impact was, where quantified
WHAT evidence supports the finding
WHAT remains uncertain
WHAT should be investigated next

Keep executive summaries concise but evidence-based.

======================================================================
11. ANALYST INVESTIGATION MODE
======================================================================

Also support deeper analytical investigation.

Example:

"Show me the evidence that stockouts contributed to the decline."

The response should retrieve relevant analytical evidence and explain:

observed pattern
affected stores/products
timing
estimated impact if governed
supporting analyses
alternative explanations
limitations

This mode can be more detailed than Executive mode.

======================================================================
12. FORECASTING INTEGRATION
======================================================================

Integrate Phase 10 without changing its validated forecasting logic.

Use existing forecast artifacts.

The assistant should be able to explain:

selected model
forecast horizon
point forecasts
prediction intervals
model comparison
forecast limitations

Clearly label forecasts as forecasts, not actual results.

Do not regenerate or silently alter Phase 10 modelling unless the repository
explicitly requires it.

======================================================================
13. PROMPT-INJECTION / DATA-SAFETY DEFENCES
======================================================================

Because this is a RAG/agent system, implement basic defensive controls.

Retrieved project text must be treated as DATA, not system instructions.

The assistant must not obey instructions embedded in retrieved documents
that attempt to:

override system behavior
reveal secrets
execute arbitrary code
change access controls
delete/modify files
ignore grounding requirements

Separate:
system instructions
user question
retrieved evidence

Validate tool arguments independently of LLM text.

======================================================================
14. PROVIDER ABSTRACTION
======================================================================

Build a clean LLM-provider abstraction.

Configuration should support changing:

LLM provider
model ID
API endpoint/base URL where applicable
temperature
max tokens
embedding provider/model

through environment/configuration rather than rewriting application logic.

Use something conceptually equivalent to:

.env.example

but NEVER place real credentials in tracked files.

If the repository already has a configuration standard, follow it instead.

======================================================================
15. LOCAL / MOCK MODE
======================================================================

The project must remain testable even when no paid LLM API key is available.

Implement a deterministic/mock testing path so:

retrieval
tool execution
evidence assembly
schema validation
grounding checks

can be tested without making paid API requests.

Do not make unit tests depend on external API availability.

======================================================================
16. OBSERVABILITY
======================================================================

Add useful logging without logging secrets.

Capture where appropriate:

request ID
question category
retrieved source IDs
tool calls
latency
errors
model/provider
token usage if available

Never log:

API keys
SQL passwords
authentication tokens
complete connection strings containing secrets

======================================================================
17. EVALUATION SUITE
======================================================================

Create a proper GenAI evaluation suite.

Build a set of representative questions based on ACTUAL project evidence.

Include categories such as:

Revenue
Margin
Stores
Products
Stockouts
Returns
Promotions
Root causes
Evidence
Forecasting
Methodology
Unsupported questions

Evaluate at minimum:

retrieval relevance
groundedness
factual consistency
source attribution
unsupported-claim handling
tool selection
response schema validity

Include adversarial cases such as:

"Invent a reason even if there is no evidence."

Expected behavior:
Refuse to fabricate and explain that evidence is insufficient.

Also test prompt-injection attempts in retrieved content/user questions.

======================================================================
18. TESTING
======================================================================

Create unit/integration tests appropriate to the implemented architecture.

Test at least:

configuration loading
retrieval
source metadata
analytics tools
input validation
read-only SQL controls if SQL querying is used
response schema
grounding
unsupported questions
forecast retrieval
provider abstraction
mock mode
prompt-injection defenses

Run the existing project test suite as well.

Do NOT "fix" unrelated historical tests by changing governed artifacts.

Separate:

NEW FAILURES CAUSED BY THIS PHASE

from:

PRE-EXISTING FAILURES

======================================================================
19. DOCUMENTATION
======================================================================

Create/update documentation explaining:

Generative AI architecture
RAG strategy
tool architecture
data/evidence sources
grounding strategy
security controls
provider configuration
local setup
testing
evaluation
limitations
example questions

Include a simple architecture diagram in Mermaid if Markdown documentation
is used.

Document the distinction between:

analytics engine = source of quantitative truth

and

LLM = interpretation/explanation interface

======================================================================
20. REPRODUCIBILITY
======================================================================

The phase must be reproducible.

Pin/add dependencies according to the project's existing dependency
management approach.

Avoid unnecessary heavyweight frameworks.

Prefer transparent components over excessive abstraction.

Use deterministic settings where appropriate for tests.

======================================================================
21. OPTIONAL USER INTERFACE
======================================================================

ONLY after the backend, grounding and evaluation tests are working:

If no suitable UI already exists, create a lightweight analyst interface.

A small Streamlit application is acceptable if it fits the repository.

Potential UI:

Retail Performance AI Analyst

Question input

Answer

Executive Summary

Evidence

Sources

Confidence / Evidence Strength

Limitations

Suggested Follow-up Questions

Do NOT prioritize visual polish over correctness.

The backend must remain usable independently from the UI.

======================================================================
22. POWER BI INTEGRATION
======================================================================

Do NOT directly modify the current PBIP during the initial AI build.

Instead create a clean integration boundary that could later support:

Power BI
Streamlit
REST API
another front end

If an AI-generated executive narrative can eventually be exposed to
Power BI, document the proposed integration but do not destabilize the
current dashboard.

======================================================================
23. PRODUCTION-QUALITY EXPECTATIONS
======================================================================

Code should have:

clear module boundaries
type hints where appropriate
docstrings for public functions
structured exceptions
configuration separation
no duplicated business logic
no hard-coded machine-specific assumptions unless existing architecture
requires them
no secrets in source
deterministic tests
meaningful logging

Do not create dozens of unnecessary files.

Prefer a compact, maintainable architecture.

======================================================================
24. GOVERNANCE
======================================================================

This phase must be additive.

Do not modify validated Phase 1–10 outputs merely to accommodate the LLM.

Do not modify freeze manifests to hide changes.

Do not alter validated SQL/Python/DAX business calculations.

If the AI layer identifies an inconsistency in existing governed evidence:

REPORT IT.

Do not silently correct it.

======================================================================
25. IMPLEMENTATION SEQUENCE
======================================================================

Work in this order:

1. Repository/pre-flight audit
2. Identify authoritative evidence sources
3. Define architecture
4. Define response/evidence schemas
5. Implement configuration/provider abstraction
6. Implement analytical retrieval tools
7. Implement textual/RAG retrieval where justified
8. Implement evidence assembly
9. Implement grounded LLM orchestration
10. Implement provenance
11. Implement security/guardrails
12. Implement deterministic/mock mode
13. Implement evaluation dataset
14. Implement tests
15. Run tests
16. Document architecture
17. Only then consider lightweight UI
18. Produce final validation report

Do not jump immediately into building a chatbot.

======================================================================
26. DEFINITION OF DONE
======================================================================

This phase is NOT complete merely because an LLM returns an answer.

It is complete only when:

[ ] Existing project state has been audited
[ ] Governed analytical files remain protected
[ ] Secrets are externalized
[ ] Structured analytical retrieval works
[ ] RAG retrieval works where justified
[ ] Responses are grounded in project evidence
[ ] Source provenance is available
[ ] Unsupported questions do not hallucinate answers
[ ] Forecast answers use Phase 10 artifacts
[ ] Provider/model is configurable
[ ] Mock/offline tests work
[ ] Security controls are tested
[ ] Evaluation suite passes defined acceptance criteria
[ ] Existing tests have been rerun
[ ] Documentation is complete
[ ] Reproducibility is demonstrated

======================================================================
27. FINAL REPORT
======================================================================

When implementation is complete, return:

GENAI PHASE STATUS:
PASS / PARTIAL / FAIL

PRE-FLIGHT AUDIT:
[summary]

ARCHITECTURE:
[implemented architecture]

FILES CREATED:
[exact paths]

FILES MODIFIED:
[exact paths]

GOVERNED FILES MODIFIED:
NONE
or STOP and explain

DATA SOURCES:
[actual sources used]

SQL INTEGRATION:
[implementation and security status]

RAG:
[index/retrieval implementation]

ANALYTICS TOOLS:
[list implemented tools]

LLM PROVIDER:
[abstraction/configuration]

EMBEDDINGS:
[implementation, if used]

GROUNDING:
[method]

PROVENANCE:
[method]

SECURITY:
[controls implemented]

EVALUATION:
[number of cases and results]

TESTS:
[exact passed/failed counts]

PRE-EXISTING TEST FAILURES:
[list separately]

NEW TEST FAILURES:
[list separately]

EXAMPLE QUESTIONS TESTED:
[list]

EXAMPLE GROUNDED RESPONSE:
[one representative result using real project evidence]

FORECAST INTEGRATION:
[status]

POWER BI INTEGRATION:
[status/proposed boundary]

BUSINESS LOGIC MODIFIED:
NO
If YES, explain and STOP if governed logic was affected.

FREEZE STATUS:
[results]

KNOWN LIMITATIONS:
[list]

PRODUCTION READINESS:
[what is complete and what remains]

EXACT RUN COMMAND:
[command]

EXACT TEST COMMAND:
[command]

EXACT NEXT ACTION:
[one concrete next action]

======================================================================
FINAL PRINCIPLE
======================================================================

Build an evidence-grounded AI analytics layer, not a generic chatbot.

The strongest demonstration should be:

User asks:
"Why did revenue decline?"

System retrieves the project's validated analytical evidence, uses
deterministic calculations rather than LLM arithmetic, identifies the
supported drivers, explains the evidence and uncertainty, cites provenance,
and refuses to invent conclusions unsupported by the project.

Proceed autonomously through the implementation and testing sequence.
Only stop for my input if:
- a governed/frozen artifact would need modification,
- credentials/access are genuinely required and unavailable,
- there is a destructive action,
- or there is a material architecture decision that cannot safely be
  inferred from the existing repository.