# Python 3.14 Compatibility Audit

**Status:** Compatibility validated for available code; full-project validation blocked by missing assets  
**Target:** CPython 3.14.x, Windows x64  
**Audit date:** 2026-09-29

## Scope and Change Control

The read-only inventory covered 100 Python files: 85 under `src/` and 15 under `tests/`. All parsed and compiled under the current Python 3.14.7 interpreter. `pytest.ini` is the only test configuration found; no `pyproject.toml`, `setup.cfg`, `setup.py`, `tox.ini`, or `noxfile.py` is present. The existing documented runtime floor is Python 3.11+ in `docs/01_business_requirements.md`; it is preserved.

Potential changes identified before editing:

- `requirements.txt`: add direct packages imported by project code/tests but absent from the dependency file.
- This audit document: record the compatibility findings and verification.
- `.venv`: recreate as a clean, isolated Python 3.14 environment.
- No analytical Python source, business logic, KPI definition, finding, evidence classification, frozen output, data, or report was identified for modification.

The `src/analytics`, `src/data_quality`, and `src/etl` directories have no Python source files in this checkout. `src.analytics.run_phase5` and `src.data_quality.core` cannot be resolved, although tests and later phases import them. This is an incomplete-project blocker, not a Python 3.14 porting issue. No code or artifacts will be restored as part of this compatibility task.

## Python Porting Review

Reviewed the official Python 3.12, 3.13, and 3.14 What's New/porting guidance, focusing on removed APIs and modules, invalid escape sequences, typing/annotation behavior, `datetime`, `pathlib`, multiprocessing, and changed runtime semantics. Static searches found no use in the inventoried source/tests of relevant removed APIs (including `distutils`, `imp`, removed `ast` aliases, `asyncio` child watchers, or `asyncio.get_event_loop()`). All 100 source/test Python files compile under Python 3.14.5 with zero compile warnings. Imports of the available source files show no Python 3.14 deprecation warnings; 26 module imports fail only because required `src.analytics` files are absent.

- https://docs.python.org/3.12/whatsnew/3.12.html
- https://docs.python.org/3.13/whatsnew/3.13.html
- https://docs.python.org/3.14/whatsnew/3.14.html

## Dependency Compatibility

The prior requirements used lower bounds, not exact pins. A clean Python 3.14.5 venv resolved and installed all requirements successfully. Every listed compatible package below imported in that venv. No existing lower bound was found to require an incompatible pinned release.

| Package | Old requirement | Python 3.14 compatible? | New requirement if needed | Reason |
|---|---|---|---|---|
| numpy | `>=1.26` | Yes, selected 2.5.3 imports on CPython 3.14 | No change | Existing minimum is unpinned; resolver selects a compatible release. |
| pandas | `>=2.2` | Yes, selected 3.0.6 imports on CPython 3.14 | No change | Existing minimum is unpinned; resolver selects a compatible release. |
| scipy | Not declared | Yes, selected 1.18.1 imports on CPython 3.14 | `>=1.18.1` | Used by `src/rca/returns_rca.py`; declare this existing direct dependency. |
| scikit-learn | Not declared | Not applicable | No change | Not imported by inventoried project source/tests. |
| statsmodels | Not declared | Not applicable | No change | Not imported by inventoried project source/tests. |
| SQLAlchemy | `>=2.0` | Yes, selected 2.1.1 imports on CPython 3.14 | No change | Existing minimum is unpinned. |
| pyodbc | `>=5.0` | Yes, selected 5.3.0 imports on CPython 3.14 | No change | CPython 3.14 native module imports; Driver 18 is registered. |
| PyYAML | `>=6.0` | Yes, selected 6.0.3 imports on CPython 3.14 | No change | Existing minimum is unpinned. |
| pytest | `>=8.0` | Yes, selected 9.1.1 imports on CPython 3.14 | No change | Existing minimum is unpinned. |
| matplotlib | Not declared | Yes, selected 3.11.2 imports on CPython 3.14 | `>=3.11.2` | Used by project figure modules; declare this existing direct dependency. |
| duckdb | Not declared | Yes, selected 1.5.6 imports on CPython 3.14 | `>=1.5.6` | Used by the SQL model and phase tests; declare this existing direct dependency. |
| sqlglot | Not declared | Yes, selected 30.20.0 imports on CPython 3.14 | `>=30.20.0` | Used by SQL dialect handling/tests; declare this existing direct dependency. |

The four additions use minimum versions already present in the Python 3.14 environment rather than introducing unrelated upgrades. The clean-venv install succeeded and `pip check` reported `No broken requirements found.`

## Validation Record

- Python/venv: Python 3.14.5; executable is `.venv/Scripts/python.exe`; isolated project venv recreated from the installed CPython 3.14 interpreter.
- Packaging: pip 26.2.1; clean requirements installation passed; `pip check` passed.
- Important dependencies: NumPy 2.5.3, pandas 3.0.6, SciPy 1.18.1, SQLAlchemy 2.1.1, pyodbc 5.3.0, PyYAML 6.0.3, pytest 9.1.1, matplotlib 3.11.2, DuckDB 1.5.6, and SQLGlot 30.20.0 all imported successfully.
- ODBC/SQL: Microsoft ODBC Driver 18 is listed; `MSSQLSERVER` reported RUNNING; Windows-authenticated, read-only `SELECT @@SERVERNAME, DB_NAME()` against `localhost`/`master` succeeded.
- Compile/warnings: all 100 source/test Python files compile; zero compile warnings and zero warnings during the available-module import smoke test.
- Focused tests: Phase 10 framework 26 passed; Phase 10 plus generator unit tests 35 passed; selected additional Phase 2/6 tests yielded 40 passed, 18 skipped; four isolated Phase 6 tests passed. The 18 skips are sample-data tests gated on missing generated sample sales files.
- Phase 10 dry-run: configuration and five registered models validated; data gate remained BLOCKED on the absent weekly Phase 5 input and Phase 5-9 freeze manifests. No production forecast was run.
- Broader non-slow suite: after excluding `test_phase2_full_data.py` and `test_phase3_pipeline.py` to avoid evaluation-only reads, pytest reported 58 passed, 61 skipped, 39 failed, 4 collection errors, and 2 deselected in 6.76 seconds. Failures/errors are from absent project modules/assets: `src.analytics`, `src.data_quality`, Phase 4 constraint SQL, Phase 5-7 configs/manifests/Power BI assets, and frozen reports. They are not Python 3.14 or dependency failures.
- Evaluation-only contents: not read. `test_phase2_full_data.py` and `test_phase3_pipeline.py` were excluded; slow generator tests were deselected because they load the hidden scenario.
- Analytical outputs: not modified. Full numerical regression remains pending because governed Phase 1-9 inputs and frozen dependency assets are unavailable in this checkout.
- Packaging emitted four non-fatal pip cache deserialization warnings during tool upgrade; dependency installation and `pip check` succeeded. Pytest and compile/import warning counts were zero.

## Conclusion

The available framework and dependencies are compatible with CPython 3.14.5. Whole-project compatibility cannot be certified in this partial checkout: missing analytical/data-quality source packages and governed/frozen assets prevent the complete historical tests from collecting or passing. Restore only verified approved project assets before repeating full regression validation; do not regenerate or substitute analytical outputs as part of this compatibility migration.
