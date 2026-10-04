"""SQL safety: the model never sees or emits SQL.

Every statement the evidence layer can run is a named template registered here, written against
allowlisted mart/dw objects, built with bound parameters, and checked again immediately before
execution. A generated string that does not match a registered template cannot reach the database,
and even a registered template is re-validated, so a bug in this module fails closed.

Inputs: a template name, bound parameters and the configured statement policy and allowlists.
Output: the query result as a DataFrame, or SqlPolicyError before anything reaches the database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SELECT_ONLY = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SqlPolicyError(ValueError):
    """Raised for any attempt to run something outside the allowlist."""


@dataclass(frozen=True)
class QueryTemplate:
    """A named, parameterised SELECT and the objects it may touch."""
    name: str
    sql: str
    objects: tuple[str, ...]
    parameters: dict[str, str] = field(default_factory=dict)
    description: str = ""


TEMPLATES: dict[str, QueryTemplate] = {}


def register(name: str, sql: str, objects: tuple[str, ...], parameters: dict[str, str],
             description: str = "") -> QueryTemplate:
    """Add a template to the registry; only registered templates can ever run."""
    template = QueryTemplate(name=name, sql=sql.strip(), objects=objects,
                             parameters=parameters, description=description)
    TEMPLATES[name] = template
    return template


def _tokens(sql: str) -> set[str]:
    return {word.upper() for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql)}


def _table_references(sql: str) -> set[str]:
    found = set()
    for match in re.finditer(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w]*\.[A-Za-z_][\w]*)", sql, re.IGNORECASE):
        found.add(match.group(1))
    return found


def _statement_count(sql: str) -> int:
    stripped = re.sub(r"'[^']*'", "''", sql)
    return len([part for part in stripped.split(";") if part.strip()])


def validate_sql(sql: str, policy: dict, allowed_objects: set[str], allowed_dimensions: set[str]) -> None:
    """Re-check a rendered statement. Raises SqlPolicyError rather than trusting the template."""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlPolicyError("Empty statement")
    if not SELECT_ONLY.match(sql):
        raise SqlPolicyError("Only a single SELECT statement is permitted")
    if _statement_count(sql) != 1:
        raise SqlPolicyError("Multi-statement execution is not permitted")
    if ";" in sql.strip().rstrip(";"):
        raise SqlPolicyError("Statement terminator found inside the query")
    if "--" in sql or "/*" in sql:
        raise SqlPolicyError("Comments are not permitted in generated SQL")
    tokens = _tokens(sql)
    for keyword in policy["forbidden_keywords"]:
        if str(keyword).upper() in tokens:
            raise SqlPolicyError(f"Forbidden keyword in statement: {keyword}")
    allowed_verbs = {verb.upper() for verb in policy["allowed_verbs"]}
    verbs = tokens & {"SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "CREATE",
                      "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE"}
    if not verbs or not verbs <= allowed_verbs:
        raise SqlPolicyError(f"Statement verb not permitted: {sorted(verbs)}")
    referenced = _table_references(sql)
    permitted = {name.lower() for name in allowed_objects | allowed_dimensions}
    for name in referenced:
        if name.lower() not in permitted:
            raise SqlPolicyError(f"Object is not on the Phase 11 allowlist: {name}")


def render(template: QueryTemplate, params: dict, policy: dict, allowed_objects: set[str],
           allowed_dimensions: set[str]) -> str:
    """Bind values, never interpolate them, then re-validate the finished statement."""
    unknown = set(params) - set(template.parameters)
    if unknown:
        raise SqlPolicyError(f"Unknown parameters for {template.name}: {sorted(unknown)}")
    for name, kind in template.parameters.items():
        if name not in params:
            raise SqlPolicyError(f"Missing parameter for {template.name}: {name}")
        value = params[name]
        if kind == "identifier":
            if not isinstance(value, str) or not IDENTIFIER.match(value):
                raise SqlPolicyError(f"Parameter {name} must be a bare identifier")
            params = {**params, name: value}
        elif kind == "int":
            if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).lstrip("-").isdigit():
                raise SqlPolicyError(f"Parameter {name} must be an integer")
            params = {**params, name: str(int(value))}
        elif kind == "date":
            if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                raise SqlPolicyError(f"Parameter {name} must be an ISO date")
        else:
            raise SqlPolicyError(f"Unsupported parameter kind for {name}: {kind}")
    sql = template.sql
    for name, kind in template.parameters.items():
        value = params[name]
        if kind == "identifier":
            literal = f"'{value}'"
        elif kind == "int":
            literal = str(int(value))
        else:
            literal = f"'{value}'"
        sql = sql.replace("{" + name + "}", literal)
    if "{" in sql or "}" in sql:
        raise SqlPolicyError(f"Unbound parameter remains in {template.name}")
    validate_sql(sql, policy, allowed_objects, allowed_dimensions)
    return sql


def execute(engine, template_name: str, params: dict, policy: dict, allowed_objects: set[str],
            allowed_dimensions: set[str]):
    """The only path from the analyst to the database."""
    template = TEMPLATES.get(template_name)
    if template is None:
        raise SqlPolicyError(f"No registered query template named {template_name}")
    if engine is None:
        raise SqlPolicyError("No database engine available; the analyst may not fall back to its own arithmetic")
    validate_sql(template.sql, policy, allowed_objects, allowed_dimensions)
    rendered = render(template, params, policy, allowed_objects, allowed_dimensions)
    return engine.query(rendered)


# ============================================================================= registered templates
WEEK_STORE_KPI = """
SELECT w.retail_week_label, w.week_start_date, w.retail_year, w.retail_week, w.retail_half,
       p.store_id, p.net_revenue, p.target_net_revenue, p.variance_to_target, p.target_achievement_pct,
       p.sales_revenue, p.returns_value, p.transactions, p.units_sold, p.aov, p.upt, p.asp
FROM mart.v_performance_store_week AS p
JOIN dw.dim_retail_week AS w ON w.retail_week_key = p.retail_week_key
WHERE p.store_id = {store_id}
  AND w.retail_week_key BETWEEN {from_week_key} AND {to_week_key}
ORDER BY w.week_start_date
"""

ESTATE_KPI = """
SELECT w.retail_year, w.retail_half AS period, p.net_revenue, p.sales_revenue, p.returns_value,
       p.transactions, p.units_sold, p.aov, p.asp
FROM mart.v_kpi_estate_period AS p
JOIN dw.dim_retail_week AS w ON w.retail_year = p.retail_year AND w.retail_half = p.period
WHERE p.period <> N'FY'
GROUP BY w.retail_year, w.retail_half, p.net_revenue, p.sales_revenue, p.returns_value,
         p.transactions, p.units_sold, p.aov, p.asp
ORDER BY w.retail_year, p.period
"""

CATEGORY_KPI = """
SELECT p.category, p.retail_year, p.period, p.net_revenue, p.net_revenue_py, p.net_revenue_yoy_pct,
       p.sales_revenue, p.returns_value, p.asp, p.return_rate_value, p.promo_revenue_share
FROM mart.v_kpi_category_period AS p
WHERE p.period <> N'FY'
ORDER BY p.category, p.retail_year, p.period
"""

STORE_PERIOD_KPI = """
SELECT p.store_id, p.store_name, p.region, p.store_format, p.retail_year, p.period, p.net_revenue,
       p.target_net_revenue, p.target_achievement_pct, p.transactions, p.units_sold, p.aov, p.asp,
       p.return_rate_value, p.promo_revenue_share
FROM mart.v_kpi_store_period AS p
WHERE p.period <> N'FY'
ORDER BY p.store_id, p.retail_year, p.period
"""

STORE_WEEK_AVAILABILITY = """
SELECT w.retail_week_label, w.week_start_date, a.store_id, a.stock_availability, a.ranged_cells,
       a.in_stock_cells, a.closing_stock_units
FROM mart.v_availability_store_week AS a
JOIN dw.dim_retail_week AS w ON w.retail_week_key = a.retail_week_key
WHERE a.store_id = {store_id}
  AND a.retail_week_key BETWEEN {from_week_key} AND {to_week_key}
ORDER BY w.week_start_date
"""

STORE_WEEK_RETURNS = """
SELECT w.retail_week_label, w.week_start_date, r.store_id, SUM(r.returns_value) AS returns_value,
       SUM(r.returned_units) AS returned_units, SUM(r.return_lines) AS return_lines
FROM mart.v_returns_analysis AS r
JOIN dw.dim_retail_week AS w ON w.retail_week_key = r.retail_week_key
WHERE r.store_id = {store_id}
  AND r.retail_week_key BETWEEN {from_week_key} AND {to_week_key}
GROUP BY w.retail_week_label, w.week_start_date, r.store_id
ORDER BY w.week_start_date
"""

WEEK_SUMMARY = """
SELECT w.retail_week_key, w.retail_week_label, w.week_start_date, w.retail_year, w.retail_week
FROM dw.dim_retail_week AS w
WHERE w.retail_week_key BETWEEN {from_week_key} AND {to_week_key}
  AND w.retail_week_key > 0
ORDER BY w.week_start_date
"""

STORE_DIMENSION = """
SELECT s.store_id, s.store_name, s.region, s.store_format
FROM dw.dim_store AS s
WHERE s.store_key > 0
ORDER BY s.store_id
"""

CATEGORY_DIMENSION = """
SELECT d.category, COUNT(*) AS products
FROM dw.dim_product AS d
WHERE d.product_key > 0
GROUP BY d.category
ORDER BY d.category
"""

SUPPLIER_DIMENSION = """
SELECT d.supplier_name, COUNT(*) AS products
FROM dw.dim_product AS d
WHERE d.product_key > 0
GROUP BY d.supplier_name
ORDER BY d.supplier_name
"""

PERFORMANCE_CATEGORY_WEEK = """
SELECT w.retail_week_label, w.week_start_date, c.category, c.net_revenue, c.net_revenue_change,
       c.sales_revenue, c.returns_value, c.transactions, c.units_sold, c.gross_margin
FROM mart.v_performance_category_week AS c
JOIN dw.dim_retail_week AS w ON w.retail_week_key = c.retail_week_key
WHERE c.retail_week_key BETWEEN {from_week_key} AND {to_week_key}
ORDER BY w.week_start_date, c.net_revenue_change
"""

register("week_store_kpi", WEEK_STORE_KPI, ("mart.v_performance_store_week", "dw.dim_retail_week"),
         {"store_id": "identifier", "from_week_key": "int", "to_week_key": "int"},
         "Weekly KPI and target variance for one store over a retail-week window.")
register("estate_kpi", ESTATE_KPI, ("mart.v_kpi_estate_period", "dw.dim_retail_week"), {},
         "Estate KPI by retail year and half.")
register("category_kpi", CATEGORY_KPI, ("mart.v_kpi_category_period",), {},
         "Category KPI by retail year and half, including the governed YoY.")
register("store_period_kpi", STORE_PERIOD_KPI, ("mart.v_kpi_store_period",), {},
         "Store KPI by retail year and half, including target achievement.")
register("store_week_availability", STORE_WEEK_AVAILABILITY,
         ("mart.v_availability_store_week", "dw.dim_retail_week"),
         {"store_id": "identifier", "from_week_key": "int", "to_week_key": "int"},
         "Stock availability for one store over a retail-week window.")
register("store_week_returns", STORE_WEEK_RETURNS, ("mart.v_returns_analysis", "dw.dim_retail_week"),
         {"store_id": "identifier", "from_week_key": "int", "to_week_key": "int"},
         "Returns value and units for one store over a retail-week window.")
register("week_summary", WEEK_SUMMARY, ("dw.dim_retail_week",),
         {"from_week_key": "int", "to_week_key": "int"}, "Retail week calendar for a window.")
register("store_dimension", STORE_DIMENSION, ("dw.dim_store",), {}, "Trading store dimension.")
register("category_dimension", CATEGORY_DIMENSION, ("dw.dim_product",), {}, "Category dimension.")
register("supplier_dimension", SUPPLIER_DIMENSION, ("dw.dim_product",), {}, "Supplier dimension.")
register("performance_category_week", PERFORMANCE_CATEGORY_WEEK,
         ("mart.v_performance_category_week", "dw.dim_retail_week"),
         {"from_week_key": "int", "to_week_key": "int"},
         "Category net revenue and change for a retail-week window.")
