# Column Lineage Diagram

An interactive, browser-based tool that reads database metadata — tables, views, and stored procedures — and renders a **column-level data lineage diagram** using D3.js. Built with Python (Flask) and a zero-install SQLite prototype, it lets you trace exactly how data flows from source columns through transformations to downstream objects.

Diagrams can be **exported as self-contained HTML files** that work offline and can be attached directly to Confluence pages.

---

## Table of Contents

1. [Features](#features)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Project Structure](#project-structure)
6. [Database Connectors](#database-connectors)
7. [JSON Metadata Format](#json-metadata-format)
8. [Using the Diagram](#using-the-diagram)
9. [Exporting to Confluence](#exporting-to-confluence)
10. [HR Demo Database](#hr-demo-database)
11. [Troubleshooting](#troubleshooting)

---

## Features

| Feature | Description |
|---|---|
| **Column-level lineage** | Bezier arrows connect individual columns across tables, views, and stored procedures |
| **Multi-hop tracing** | Click a column to BFS-traverse all upstream sources and downstream targets across any number of hops |
| **Sticky selection** | Click a column to pin its lineage; click again or press `Esc` to clear |
| **Lineage info bar** | Top bar shows selected column's source and target columns as clickable chips |
| **Dark / Light theme** | Toggle between themes; preference is saved in the browser |
| **Multiple connectors** | Connect to SQLite files, SQL Server, or upload a JSON metadata file |
| **Edge type colouring** | Visual distinction between direct, computed, aggregate, concat, and case edges |
| **Search / filter** | Type in the search box to hide unrelated objects instantly |
| **Zoom & pan** | Mouse scroll to zoom, drag the canvas to pan, Fit button to reset |
| **Self-contained export** | Download a single `.html` file — no server, no internet needed |

---

## Prerequisites

### Required

| Software | Minimum Version | Notes |
|---|---|---|
| **Python** | 3.9+ | [python.org/downloads](https://www.python.org/downloads/) |
| **pip** | bundled with Python | Used to install Flask |
| **Flask** | 3.0+ | Installed via pip (see below) |

> **SQLite** is bundled with Python — no separate installation needed.

### Optional (SQL Server only)

| Software | Notes |
|---|---|
| **pyodbc** | `pip install pyodbc` — only needed when connecting to SQL Server |
| **ODBC Driver for SQL Server** | Download from Microsoft: [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) |

---

## Installation

### Step 1 — Clone or download the project

Place all files in a local folder, for example `C:\SMS\Data_Lineage\`.

### Step 2 — Install Python dependencies

Open a terminal in the project folder and run:

```bash
pip install flask
```

To also enable the SQL Server connector:

```bash
pip install flask pyodbc
```

> **Tip:** Using a virtual environment is recommended to keep dependencies isolated:
> ```bash
> python -m venv .venv
> # Windows
> .venv\Scripts\activate
> # macOS / Linux
> source .venv/bin/activate
> pip install flask
> ```

### Step 3 — Set up the demo database (first time only)

This creates `hr.db` with 7 HR tables, 4 views, 2 stored procedures, and 20 seeded employees:

```bash
python setup_db.py
```

Expected output:
```
Schema created.
Created 4 views.
Inserted 2 stored procedures.
Seed data inserted.
  regions: 4 rows
  countries: 10 rows
  locations: 7 rows
  departments: 7 rows
  jobs: 10 rows
  employees: 20 rows
  job_history: 6 rows

Database ready: C:\SMS\Data_Lineage\hr.db
```

> If you need to reset the database, run `setup_db.py` again — it will drop and recreate `hr.db`.

---

## Quick Start

### Step 1 — Start the server

```bash
python app.py
```

You should see:
```
 * Running on http://127.0.0.1:5000
 * Debug mode: on
```

### Step 2 — Open the app

Open your browser and go to: **http://127.0.0.1:5000**

### Step 3 — Generate a diagram

1. The **HR Domain (SQLite)** source is pre-selected in the dropdown.
2. Click **Generate Diagram**.
3. The diagram renders with 13 nodes (7 tables + 4 views + 2 stored procedures) and their column-level edges.

### Step 4 — Explore

- **Click any column row** to pin its lineage (sources highlighted in blue, targets in green).
- **Hover edges** to see the edge type tooltip.
- **Drag nodes** to rearrange the layout.
- **Search** to filter by object or column name.
- **Scroll** to zoom in/out; drag the background to pan.
- Press **`Esc`** to clear the current selection.

---

## Project Structure

```
C:\SMS\Data_Lineage\
│
├── app.py                    # Flask application — all backend logic
├── setup_db.py               # One-time database setup script
├── requirements.txt          # Python dependencies
├── hr.db                     # SQLite demo database (created by setup_db.py)
│
├── generate_sample_json.py   # Script to regenerate sample_metadata.json
├── sample_metadata.json      # Ready-to-use JSON metadata example
│
├── templates/
│   └── index.html            # Main UI (toolbar, lineage bar, diagram canvas)
│
└── static/
    ├── css/
    │   └── diagram.css       # All styles (supports dark/light via CSS variables)
    └── js/
        └── diagram.js        # D3.js diagram engine
```

---

## Database Connectors

Click the **⚙ Connect** button in the toolbar to open the connection modal. Three connector types are available.

### SQLite

Connect to any local SQLite `.db` file.

| Field | Description |
|---|---|
| **Label** | Friendly name shown in the dropdown |
| **File path** | Absolute path to the `.db` file, e.g. `C:\data\mydb.db` |

The app reads tables from `sqlite_master`, views with their full `CREATE VIEW` SQL, and stored procedures from a `stored_procedures` metadata table (see [HR Demo Database](#hr-demo-database) for the schema).

**Test Connection** verifies the file exists and is a valid SQLite database before saving.

---

### SQL Server

> **Requires:** `pip install pyodbc` and Microsoft ODBC Driver for SQL Server installed on the machine.

| Field | Description |
|---|---|
| **Label** | Friendly name |
| **Server** | Hostname or IP, e.g. `localhost` or `192.168.1.10` |
| **Port** | Default `1433` |
| **Database** | Database name |
| **Schema** | Default `dbo` |
| **Auth type** | SQL (username + password) or Windows Authentication |
| **Username / Password** | Required for SQL auth |

The connector reads:
- Tables and columns from `INFORMATION_SCHEMA`
- View definitions from `sys.sql_modules`
- Stored procedure definitions from `sys.procedures` + `sys.sql_modules`

Column lineage is then auto-extracted by parsing the SQL definitions.

**Windows Authentication** uses the currently logged-in Windows user — no username/password needed (Trusted_Connection=yes).

---

### JSON Metadata

Upload a JSON file that describes your database objects. Useful when:
- You cannot connect directly to the database from the machine running this tool.
- You want to hand-craft lineage for a non-SQL source (e.g. ETL pipeline, API).
- You want to document lineage for objects that have no SQL (flat files, APIs).

**To upload:**
1. Click **⚙ Connect** → select the **JSON Metadata** tab.
2. Drag and drop a `.json` file onto the upload zone, or click to browse.
3. Click **Connect**.

**Download a blank template:**
Click **"Download template"** in the JSON tab to get a pre-filled template based on the HR database structure.

Or use the included example file:
```
sample_metadata.json
```
This file contains all 7 HR tables, 4 views with real SQL, 2 stored procedures, and 47 hand-crafted lineage edges.

---

## JSON Metadata Format

```jsonc
{
  "database_name": "My Database",      // shown in the dropdown label
  "tables": [
    {
      "name": "employees",
      "columns": [
        { "name": "employee_id", "data_type": "INTEGER", "is_pk": true },
        { "name": "first_name",  "data_type": "TEXT",    "is_pk": false }
      ]
    }
  ],
  "views": [
    {
      "name": "v_employee_details",
      "sql": "CREATE VIEW v_employee_details AS SELECT ...",  // optional: auto-parsed
      "columns": [
        { "name": "employee_id", "data_type": "INTEGER", "is_pk": false },
        { "name": "full_name",   "data_type": "TEXT",    "is_pk": false }
      ]
    }
  ],
  "stored_procedures": [
    {
      "name": "sp_get_report",
      "body_sql": "SELECT e.employee_id AS employee_id, ...",  // optional: auto-parsed
      "columns": []
    }
  ],
  "lineage": [
    {
      "source_object": "employees",
      "source_column": "first_name",
      "target_object": "v_employee_details",
      "target_column": "full_name",
      "edge_type": "concat"
    }
  ]
}
```

### Two Lineage Modes

| Mode | How it works |
|---|---|
| **Auto-parse** | Provide `sql` (views) or `body_sql` (SPs). The app parses `SELECT ... FROM` to extract column references automatically. |
| **Explicit** | Fill the `lineage[]` array with hand-crafted source → target edges. |
| **Both** | If `lineage[]` is non-empty the app uses it directly. If only `sql`/`body_sql` is provided it auto-parses. |

### Valid `edge_type` Values

| Type | Meaning | Visual Style |
|---|---|---|
| `direct` | Column passed through unchanged | Solid gray |
| `computed` | Derived via expression (ROUND, COALESCE, etc.) | Dashed gray |
| `aggregate` | Derived via aggregate function (COUNT, AVG, SUM) | Dotted orange |
| `concat` | Two or more columns joined as a string (`\|\|`) | Solid purple |
| `case` | Output depends on a CASE WHEN expression | Dashed blue |

---

## Using the Diagram

### Toolbar Controls

| Control | Action |
|---|---|
| **Database dropdown** | Switch between connected sources |
| **⚙ Connect** | Open the connection modal to add a new source |
| **Generate Diagram** | Fetch lineage data and render the diagram |
| **Search box** | Filter objects/columns by name; clears to show all |
| **⊙ Fit** | Reset zoom and pan to fit all nodes on screen |
| **Export HTML** | Download a self-contained HTML file |
| **☀ / ☾** | Toggle light / dark theme |

### Node Colour Coding

| Colour | Object type |
|---|---|
| Blue header | Table |
| Green header | View |
| Orange header | Stored Procedure |

### Interacting with Columns

- **Click a column row** → pins the lineage; the lineage bar at the top updates with all upstream sources and downstream targets as clickable chips.
- **Click a chip in the lineage bar** → jumps the selection to that column.
- **Click the ✕ button** in the lineage bar (or press `Esc`) → clears the selection.
- **Click the SVG background** → also clears the selection.

### Layout

Nodes are arranged in a **left-to-right DAG (Directed Acyclic Graph)** layout:
- Base tables appear on the left.
- Views that depend on tables appear in the middle.
- Views that depend on other views (multi-hop) appear further right.
- Stored procedures appear on the far right.

Drag any node to reposition it. The edges update in real time.

---

## Exporting to Confluence

1. With a diagram loaded, click **Export HTML** in the toolbar.
2. A file named `lineage_<db>_<date>.html` is downloaded automatically.
3. In Confluence, create or edit a page and use **Insert → Files and Images → Upload** to attach the HTML file.
4. Open the attached file — the diagram is fully interactive with no internet connection required.

> The exported file embeds D3.js from the CDN (`https://d3js.org/d3.v7.min.js`). The first load requires internet access to fetch D3. For a fully offline export, replace the CDN `<script>` tag in the file with an inline copy of D3.js.

---

## HR Demo Database

The `setup_db.py` script creates a complete HR domain for immediate exploration.

### Tables (7)

| Table | Description |
|---|---|
| `regions` | World regions (Americas, Europe, Asia Pacific, MEA) |
| `countries` | 10 countries linked to regions |
| `locations` | 7 office locations with city and country |
| `departments` | 7 departments with manager and location |
| `jobs` | 10 job titles with salary bands |
| `employees` | 20 employees (full HR org chart) |
| `job_history` | Historical job assignments |

### Views (4)

| View | Sources | Description |
|---|---|---|
| `v_employee_details` | employees, jobs, departments, locations | Full employee profile with computed `full_name` and `total_compensation` |
| `v_salary_grades` | employees, jobs | Salary vs job band analysis with computed `salary_pct_of_range` and `salary_band` |
| `v_department_headcount` | departments, locations, countries, regions, employees | Aggregate payroll and headcount by department |
| `v_high_earners` | **v_employee_details, v_salary_grades** | **2nd-hop view** — demonstrates multi-hop lineage |

### Multi-hop Lineage Chain

`v_high_earners` sources from two other views, creating a 2-hop chain:

```
employees.first_name  ──→  v_employee_details.full_name  ──→  v_high_earners.full_name
employees.salary      ──→  v_employee_details.salary     ──→  v_high_earners.salary
jobs.max_salary       ──→  v_salary_grades.grade_max     ──→  v_high_earners.grade_max
```

Hover over `employees.salary` after selecting it to see the full 2-hop downstream chain highlighted.

### Stored Procedures (2)

Simulated via a `stored_procedures` metadata table (SQLite has no native SP support):

| SP Name | Description |
|---|---|
| `sp_get_employee_report` | Employee details with salary grading, filtered by department |
| `sp_department_summary` | Aggregate headcount and payroll stats, filtered by region |

---

## Troubleshooting

### `python: command not found`
Ensure Python 3.9+ is installed and added to your PATH. On Windows, use `py` instead of `python`.

### `ModuleNotFoundError: No module named 'flask'`
Run `pip install flask` in the same environment where you run `python app.py`.

### `Database not found. Run: python setup_db.py`
You haven't created the demo database yet. Run:
```bash
python setup_db.py
```

### Port 5000 already in use
Either stop the other process using port 5000, or start the app on a different port:
```bash
flask run --port 5001
```
Or edit the last line of `app.py`:
```python
app.run(debug=True, port=5001)
```

### SQL Server connection fails
- Confirm `pyodbc` is installed: `pip install pyodbc`
- Confirm the Microsoft ODBC Driver for SQL Server is installed on your machine.
- Check the server address, port (default 1433), and that the SQL Server instance accepts remote connections.
- For Windows Authentication, the app must run under the Windows account that has database access.

### JSON upload fails with "JSON must contain tables and/or lineage keys"
Your JSON file must have at least one of:
- A `tables` array (even if empty)
- A `lineage` array with at least one edge

### Edges missing from the diagram (auto-parse mode)
- Make sure column references in SQL are qualified with a table alias (e.g. `e.salary`, not just `salary`).
- Bare column references without a table prefix are not resolved by the auto-parser.
- Use the explicit `lineage[]` array in the JSON format for full control over edge definitions.

### Diagram appears blank after clicking Generate
Open the browser developer console (`F12` → Console tab) and look for errors. Common causes:
- The API returned an error (check the Network tab for the `/api/lineage` response).
- The database file (`hr.db`) was deleted or moved — re-run `python setup_db.py`.

---

## License

This project is intended for internal tooling and demonstration purposes.
