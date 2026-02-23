"""
Generates sample_metadata.json — a complete HR domain metadata file
showing both auto-parse (sql/body_sql) and explicit lineage[] approaches.
Run: python generate_sample_json.py
"""
import sqlite3, json, re, os

DB  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hr.db')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample_metadata.json')

conn = sqlite3.connect(DB)

# ── Tables ────────────────────────────────────────────────────
excluded = {'sqlite_sequence', 'stored_procedures'}
tables = []
for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
    if name in excluded:
        continue
    rows = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
    cols = [{'name': r[1], 'data_type': r[2] or 'TEXT', 'is_pk': bool(r[5])} for r in rows]
    tables.append({'name': name, 'columns': cols})

# ── Views (real SQL from sqlite_master) ───────────────────────
views = []
for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='view'"):
    rows = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
    cols = [{'name': r[1], 'data_type': r[2] or 'ANY', 'is_pk': False} for r in rows]
    views.append({'name': name, 'sql': sql, 'columns': cols})

# ── Stored Procedures (real body_sql) ─────────────────────────
sps = []
for name, body in conn.execute("SELECT name, body_sql FROM stored_procedures"):
    m = re.search(r'\bSELECT\b(.*?)\bFROM\b', body, re.IGNORECASE | re.DOTALL)
    cols = []
    if m:
        for part in re.split(r',(?![^(]*\))', m.group(1)):
            part = part.strip()
            if not part:
                continue
            am = re.search(r'\bAS\s+(\w+)\s*$', part, re.IGNORECASE)
            cname = am.group(1) if am else (re.findall(r'\b(\w+)\b', part) or ['col'])[-1]
            cols.append({'name': cname.lower(), 'data_type': 'ANY', 'is_pk': False})
    sps.append({'name': name, 'body_sql': body, 'columns': cols})

conn.close()

# ── Explicit lineage entries ───────────────────────────────────
# This demonstrates the manual lineage[] approach alongside the auto-parse sql fields.
# When both sql AND lineage[] are present the app merges both sets of edges.
explicit_lineage = [
    # employees → v_employee_details
    {"source_object": "employees", "source_column": "employee_id",   "target_object": "v_employee_details", "target_column": "employee_id",        "edge_type": "direct"},
    {"source_object": "employees", "source_column": "first_name",    "target_object": "v_employee_details", "target_column": "first_name",         "edge_type": "direct"},
    {"source_object": "employees", "source_column": "last_name",     "target_object": "v_employee_details", "target_column": "last_name",          "edge_type": "direct"},
    {"source_object": "employees", "source_column": "first_name",    "target_object": "v_employee_details", "target_column": "full_name",          "edge_type": "concat"},
    {"source_object": "employees", "source_column": "last_name",     "target_object": "v_employee_details", "target_column": "full_name",          "edge_type": "concat"},
    {"source_object": "employees", "source_column": "email",         "target_object": "v_employee_details", "target_column": "email",              "edge_type": "direct"},
    {"source_object": "employees", "source_column": "hire_date",     "target_object": "v_employee_details", "target_column": "hire_date",          "edge_type": "direct"},
    {"source_object": "employees", "source_column": "salary",        "target_object": "v_employee_details", "target_column": "salary",             "edge_type": "direct"},
    {"source_object": "employees", "source_column": "commission_pct","target_object": "v_employee_details", "target_column": "commission_pct",     "edge_type": "direct"},
    {"source_object": "employees", "source_column": "salary",        "target_object": "v_employee_details", "target_column": "total_compensation", "edge_type": "computed"},
    {"source_object": "employees", "source_column": "commission_pct","target_object": "v_employee_details", "target_column": "total_compensation", "edge_type": "computed"},
    {"source_object": "jobs",       "source_column": "job_title",    "target_object": "v_employee_details", "target_column": "job_title",          "edge_type": "direct"},
    {"source_object": "departments","source_column": "department_name","target_object":"v_employee_details", "target_column": "department_name",    "edge_type": "direct"},
    {"source_object": "locations",  "source_column": "city",         "target_object": "v_employee_details", "target_column": "work_city",          "edge_type": "direct"},
    {"source_object": "locations",  "source_column": "country_id",   "target_object": "v_employee_details", "target_column": "work_country",       "edge_type": "direct"},
    # employees + jobs → v_salary_grades
    {"source_object": "employees", "source_column": "employee_id",   "target_object": "v_salary_grades", "target_column": "employee_id",           "edge_type": "direct"},
    {"source_object": "employees", "source_column": "last_name",     "target_object": "v_salary_grades", "target_column": "last_name",             "edge_type": "direct"},
    {"source_object": "employees", "source_column": "salary",        "target_object": "v_salary_grades", "target_column": "current_salary",        "edge_type": "direct"},
    {"source_object": "jobs",      "source_column": "min_salary",    "target_object": "v_salary_grades", "target_column": "grade_min",             "edge_type": "direct"},
    {"source_object": "jobs",      "source_column": "max_salary",    "target_object": "v_salary_grades", "target_column": "grade_max",             "edge_type": "direct"},
    {"source_object": "employees", "source_column": "salary",        "target_object": "v_salary_grades", "target_column": "salary_pct_of_range",   "edge_type": "computed"},
    {"source_object": "jobs",      "source_column": "min_salary",    "target_object": "v_salary_grades", "target_column": "salary_pct_of_range",   "edge_type": "computed"},
    {"source_object": "jobs",      "source_column": "max_salary",    "target_object": "v_salary_grades", "target_column": "salary_pct_of_range",   "edge_type": "computed"},
    {"source_object": "employees", "source_column": "salary",        "target_object": "v_salary_grades", "target_column": "salary_band",           "edge_type": "case"},
    {"source_object": "jobs",      "source_column": "min_salary",    "target_object": "v_salary_grades", "target_column": "salary_band",           "edge_type": "case"},
    {"source_object": "jobs",      "source_column": "max_salary",    "target_object": "v_salary_grades", "target_column": "salary_band",           "edge_type": "case"},
    {"source_object": "jobs",      "source_column": "job_title",     "target_object": "v_salary_grades", "target_column": "job_title",             "edge_type": "direct"},
    # departments + locations + countries + regions → v_department_headcount
    {"source_object": "departments","source_column": "department_id",  "target_object": "v_department_headcount", "target_column": "department_id",  "edge_type": "direct"},
    {"source_object": "departments","source_column": "department_name","target_object": "v_department_headcount", "target_column": "department_name","edge_type": "direct"},
    {"source_object": "locations",  "source_column": "city",           "target_object": "v_department_headcount", "target_column": "city",           "edge_type": "direct"},
    {"source_object": "countries",  "source_column": "country_name",   "target_object": "v_department_headcount", "target_column": "country_name",   "edge_type": "direct"},
    {"source_object": "regions",    "source_column": "region_name",    "target_object": "v_department_headcount", "target_column": "region_name",    "edge_type": "direct"},
    {"source_object": "employees",  "source_column": "employee_id",    "target_object": "v_department_headcount", "target_column": "headcount",      "edge_type": "aggregate"},
    {"source_object": "employees",  "source_column": "salary",         "target_object": "v_department_headcount", "target_column": "avg_salary",     "edge_type": "aggregate"},
    {"source_object": "employees",  "source_column": "salary",         "target_object": "v_department_headcount", "target_column": "min_salary",     "edge_type": "aggregate"},
    {"source_object": "employees",  "source_column": "salary",         "target_object": "v_department_headcount", "target_column": "max_salary",     "edge_type": "aggregate"},
    {"source_object": "employees",  "source_column": "salary",         "target_object": "v_department_headcount", "target_column": "total_payroll",  "edge_type": "aggregate"},
    # v_employee_details + v_salary_grades → v_high_earners  (MULTI-HOP!)
    {"source_object": "v_employee_details", "source_column": "employee_id",        "target_object": "v_high_earners", "target_column": "employee_id",        "edge_type": "direct"},
    {"source_object": "v_employee_details", "source_column": "full_name",           "target_object": "v_high_earners", "target_column": "full_name",           "edge_type": "direct"},
    {"source_object": "v_employee_details", "source_column": "job_title",           "target_object": "v_high_earners", "target_column": "job_title",           "edge_type": "direct"},
    {"source_object": "v_employee_details", "source_column": "department_name",     "target_object": "v_high_earners", "target_column": "department_name",     "edge_type": "direct"},
    {"source_object": "v_employee_details", "source_column": "work_city",           "target_object": "v_high_earners", "target_column": "work_city",           "edge_type": "direct"},
    {"source_object": "v_employee_details", "source_column": "salary",              "target_object": "v_high_earners", "target_column": "salary",              "edge_type": "direct"},
    {"source_object": "v_employee_details", "source_column": "salary",              "target_object": "v_high_earners", "target_column": "annual_salary",       "edge_type": "computed"},
    {"source_object": "v_salary_grades",    "source_column": "salary_band",         "target_object": "v_high_earners", "target_column": "salary_band",         "edge_type": "direct"},
    {"source_object": "v_salary_grades",    "source_column": "grade_max",           "target_object": "v_high_earners", "target_column": "grade_max",           "edge_type": "direct"},
    {"source_object": "v_salary_grades",    "source_column": "salary_pct_of_range", "target_object": "v_high_earners", "target_column": "salary_pct_of_range", "edge_type": "direct"},
]

# ── Assemble ──────────────────────────────────────────────────
sample = {
    "_readme": {
        "title": "HR Domain — Column Lineage Metadata",
        "modes": {
            "auto_parse": "Views/SPs have real sql/body_sql — lineage is extracted automatically",
            "explicit":   "lineage[] array provides hand-crafted edges (merged with auto-parsed ones)",
            "json_only":  "Remove sql/body_sql fields and use only lineage[] for pure explicit mode"
        },
        "edge_types": ["direct", "computed", "aggregate", "concat", "case"]
    },
    "database_name": "HR Domain (JSON Metadata)",
    "tables": tables,
    "views":  views,
    "stored_procedures": sps,
    "lineage": explicit_lineage
}

with open(OUT, 'w') as f:
    json.dump(sample, f, indent=2)

size_kb = os.path.getsize(OUT) / 1024
print(f"Generated: {OUT}")
print(f"  Tables  : {len(tables)}")
print(f"  Views   : {len(views)}  (with real SQL for auto-parse)")
print(f"  SPs     : {len(sps)}  (with real body_sql)")
print(f"  Explicit lineage edges: {len(explicit_lineage)}")
print(f"  File size: {size_kb:.1f} KB")
