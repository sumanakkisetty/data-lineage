"""
Run this once to create hr.db with HR domain tables, views, and stored procedure metadata.
Usage: python setup_db.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hr.db')

SCHEMA = """
PRAGMA foreign_keys = OFF;

CREATE TABLE regions (
    region_id   INTEGER PRIMARY KEY,
    region_name TEXT NOT NULL
);

CREATE TABLE countries (
    country_id   TEXT PRIMARY KEY,
    country_name TEXT NOT NULL,
    region_id    INTEGER NOT NULL
);

CREATE TABLE locations (
    location_id    INTEGER PRIMARY KEY,
    street_address TEXT,
    postal_code    TEXT,
    city           TEXT NOT NULL,
    state_province TEXT,
    country_id     TEXT NOT NULL
);

CREATE TABLE departments (
    department_id   INTEGER PRIMARY KEY,
    department_name TEXT NOT NULL,
    manager_id      INTEGER,
    location_id     INTEGER
);

CREATE TABLE jobs (
    job_id     TEXT PRIMARY KEY,
    job_title  TEXT NOT NULL,
    min_salary REAL NOT NULL,
    max_salary REAL NOT NULL
);

CREATE TABLE employees (
    employee_id    INTEGER PRIMARY KEY,
    first_name     TEXT,
    last_name      TEXT NOT NULL,
    email          TEXT NOT NULL,
    phone_number   TEXT,
    hire_date      TEXT NOT NULL,
    job_id         TEXT NOT NULL,
    salary         REAL NOT NULL,
    commission_pct REAL,
    manager_id     INTEGER,
    department_id  INTEGER
);

CREATE TABLE job_history (
    employee_id   INTEGER NOT NULL,
    start_date    TEXT NOT NULL,
    end_date      TEXT NOT NULL,
    job_id        TEXT NOT NULL,
    department_id INTEGER,
    PRIMARY KEY (employee_id, start_date)
);

CREATE TABLE stored_procedures (
    sp_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    parameters  TEXT,
    body_sql    TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

VIEWS = [
    """CREATE VIEW v_employee_details AS
SELECT
    e.employee_id                                            AS employee_id,
    e.first_name                                             AS first_name,
    e.last_name                                              AS last_name,
    e.first_name || ' ' || e.last_name                       AS full_name,
    e.email                                                  AS email,
    e.hire_date                                              AS hire_date,
    e.salary                                                 AS salary,
    e.commission_pct                                         AS commission_pct,
    ROUND(e.salary * (1 + COALESCE(e.commission_pct, 0)), 2) AS total_compensation,
    j.job_title                                              AS job_title,
    d.department_name                                        AS department_name,
    l.city                                                   AS work_city,
    l.country_id                                             AS work_country
FROM employees   e
JOIN jobs        j ON e.job_id        = j.job_id
JOIN departments d ON e.department_id = d.department_id
JOIN locations   l ON d.location_id   = l.location_id""",

    """CREATE VIEW v_salary_grades AS
SELECT
    e.employee_id                                                AS employee_id,
    e.last_name                                                  AS last_name,
    e.salary                                                     AS current_salary,
    j.min_salary                                                 AS grade_min,
    j.max_salary                                                 AS grade_max,
    ROUND((e.salary - j.min_salary) / (j.max_salary - j.min_salary) * 100, 1) AS salary_pct_of_range,
    CASE
        WHEN e.salary < j.min_salary * 1.1 THEN 'Low'
        WHEN e.salary > j.max_salary * 0.9 THEN 'High'
        ELSE 'Mid'
    END                                                          AS salary_band,
    j.job_title                                                  AS job_title
FROM employees e
JOIN jobs      j ON e.job_id = j.job_id""",

    """CREATE VIEW v_department_headcount AS
SELECT
    d.department_id                  AS department_id,
    d.department_name                AS department_name,
    l.city                           AS city,
    c.country_name                   AS country_name,
    r.region_name                    AS region_name,
    COUNT(e.employee_id)             AS headcount,
    ROUND(AVG(e.salary), 2)          AS avg_salary,
    MIN(e.salary)                    AS min_salary,
    MAX(e.salary)                    AS max_salary,
    SUM(e.salary)                    AS total_payroll
FROM departments d
JOIN locations   l ON d.location_id   = l.location_id
JOIN countries   c ON l.country_id    = c.country_id
JOIN regions     r ON c.region_id     = r.region_id
LEFT JOIN employees e ON e.department_id = d.department_id
GROUP BY d.department_id, d.department_name, l.city, c.country_name, r.region_name""",

    """CREATE VIEW v_high_earners AS
SELECT
    ved.employee_id            AS employee_id,
    ved.full_name              AS full_name,
    ved.job_title              AS job_title,
    ved.department_name        AS department_name,
    ved.work_city              AS work_city,
    ved.salary                 AS salary,
    sg.salary_band             AS salary_band,
    sg.grade_max               AS grade_max,
    sg.salary_pct_of_range     AS salary_pct_of_range,
    ROUND(ved.salary * 12, 2)  AS annual_salary
FROM v_employee_details ved
JOIN v_salary_grades    sg  ON ved.employee_id = sg.employee_id
WHERE sg.salary_band = 'High'"""
]

SP_DATA = [
    (
        'sp_get_employee_report',
        'Full employee details with salary grading for a given department',
        '[{"name":"p_dept_id","type":"INTEGER"}]',
        """SELECT
    e.employee_id                                             AS employee_id,
    e.first_name                                              AS first_name,
    e.last_name                                               AS last_name,
    e.email                                                   AS email,
    e.salary                                                  AS salary,
    e.commission_pct                                          AS commission_pct,
    ROUND(e.salary * (1 + COALESCE(e.commission_pct, 0)), 2)  AS total_compensation,
    j.job_title                                               AS job_title,
    j.min_salary                                              AS job_min_salary,
    j.max_salary                                              AS job_max_salary,
    d.department_name                                         AS department_name,
    l.city                                                    AS city,
    l.country_id                                              AS country_id,
    CASE
        WHEN e.salary < j.min_salary * 1.1 THEN 'Low'
        WHEN e.salary > j.max_salary * 0.9 THEN 'High'
        ELSE 'Mid'
    END                                                       AS salary_band
FROM employees   e
JOIN jobs        j ON e.job_id        = j.job_id
JOIN departments d ON e.department_id = d.department_id
JOIN locations   l ON d.location_id   = l.location_id
WHERE d.department_id = :p_dept_id"""
    ),
    (
        'sp_department_summary',
        'Aggregates headcount and payroll stats per department filtered by region',
        '[{"name":"p_region_id","type":"INTEGER"}]',
        """SELECT
    d.department_id               AS department_id,
    d.department_name             AS department_name,
    r.region_name                 AS region_name,
    c.country_name                AS country_name,
    l.city                        AS city,
    COUNT(DISTINCT e.employee_id) AS headcount,
    COUNT(DISTINCT e.job_id)      AS distinct_jobs,
    ROUND(AVG(e.salary), 2)       AS avg_salary,
    SUM(e.salary)                 AS total_payroll,
    MIN(e.hire_date)              AS earliest_hire,
    MAX(e.hire_date)              AS latest_hire
FROM departments d
JOIN locations   l ON d.location_id   = l.location_id
JOIN countries   c ON l.country_id    = c.country_id
JOIN regions     r ON c.region_id     = r.region_id
LEFT JOIN employees e ON e.department_id = d.department_id
WHERE r.region_id = :p_region_id
GROUP BY d.department_id, d.department_name, r.region_name, c.country_name, l.city"""
    )
]

SEED = """
INSERT INTO regions VALUES
    (1,'Americas'),(2,'Europe'),(3,'Middle East & Africa'),(4,'Asia Pacific');

INSERT INTO countries VALUES
    ('US','United States',1),('CA','Canada',1),
    ('GB','United Kingdom',2),('DE','Germany',2),('FR','France',2),
    ('AU','Australia',4),('IN','India',4),('SG','Singapore',4),
    ('AE','United Arab Emirates',3),('ZA','South Africa',3);

INSERT INTO locations VALUES
    (1,'2004 Charade Rd','98199','Seattle','WA','US'),
    (2,'8204 Arthur St',NULL,'London',NULL,'GB'),
    (3,'Schwanthalerstr. 7031','80925','Munich',NULL,'DE'),
    (4,'12-98 Victoria Street','2901','Sydney','NSW','AU'),
    (5,'2011 Interiors Blvd','99236','Bangalore',NULL,'IN'),
    (6,'2007 Zagora St',NULL,'Dubai',NULL,'AE'),
    (7,'147 Spadina Ave','M5V 2L7','Toronto','ON','CA');

INSERT INTO jobs VALUES
    ('AD_PRES','President',20000,40000),
    ('AD_VP','Administration Vice President',15000,30000),
    ('IT_MAN','IT Manager',8000,18000),
    ('IT_PROG','Programmer',4000,10000),
    ('FI_MGR','Finance Manager',8200,16000),
    ('FI_ACCOUNT','Accountant',4200,9000),
    ('SA_MAN','Sales Manager',10000,20000),
    ('SA_REP','Sales Representative',6000,12000),
    ('HR_REP','Human Resources Representative',4000,9000),
    ('MK_MAN','Marketing Manager',9000,15000);

INSERT INTO departments VALUES
    (10,'Executive',100,1),
    (20,'IT',103,1),
    (30,'Finance',108,1),
    (40,'Sales',145,2),
    (50,'Human Resources',205,3),
    (60,'Marketing',201,4),
    (70,'Operations',114,5);

INSERT INTO employees VALUES
    (100,'Steven','King','SKING','515.123.4567','2003-06-17','AD_PRES',24000,NULL,NULL,10),
    (101,'Neena','Kochhar','NKOCHHAR','515.123.4568','2005-09-21','AD_VP',17000,NULL,100,10),
    (102,'Lex','De Haan','LDEHAAN','515.123.4569','2001-01-13','AD_VP',17000,NULL,100,10),
    (103,'Alexander','Hunold','AHUNOLD','590.423.4567','2006-01-03','IT_MAN',9000,NULL,102,20),
    (104,'Bruce','Ernst','BERNST','590.423.4568','2007-05-21','IT_PROG',6000,NULL,103,20),
    (105,'Diana','Lorentz','DLORENTZ','590.423.5567','2007-02-07','IT_PROG',4200,NULL,103,20),
    (106,'Valli','Pataballa','VPATABAL','590.423.4560','2006-02-05','IT_PROG',4800,NULL,103,20),
    (107,'David','Austin','DAUSTIN','590.423.4569','2005-06-25','IT_PROG',4800,NULL,103,20),
    (108,'Nancy','Greenberg','NGREENBE','515.124.4569','2002-08-17','FI_MGR',12008,NULL,101,30),
    (109,'Daniel','Faviet','DFAVIET','515.124.4169','2002-08-16','FI_ACCOUNT',9000,NULL,108,30),
    (110,'John','Chen','JCHEN','515.124.4269','2005-09-28','FI_ACCOUNT',8200,NULL,108,30),
    (111,'Ismael','Sciarra','ISCIARRA','515.124.4369','2005-09-30','FI_ACCOUNT',7700,NULL,108,30),
    (114,'Den','Raphaely','DRAPHEAL','515.127.4561','2002-12-07','IT_MAN',11000,NULL,100,70),
    (145,'John','Russell','JRUSSEL','011.44.1344.429268','2004-10-01','SA_MAN',14000,0.4,100,40),
    (146,'Karen','Partners','KPARTNER','011.44.1344.467268','2005-01-05','SA_MAN',13500,0.3,100,40),
    (150,'Peter','Tucker','PTUCKER','011.44.1344.129268','2005-01-30','SA_REP',10000,0.3,145,40),
    (151,'David','Bernstein','DBERNSTE','011.44.1344.345268','2005-03-24','SA_REP',9500,0.25,145,40),
    (201,'Michael','Hartstein','MHARTSTE','515.123.5555','2004-02-17','MK_MAN',13000,NULL,100,60),
    (202,'Pat','Fay','PFAY','603.123.6666','2005-08-17','MK_MAN',6000,NULL,201,60),
    (205,'Shelley','Higgins','SHIGGINS','515.123.8080','2002-06-07','HR_REP',12008,NULL,101,50);

INSERT INTO job_history VALUES
    (101,'2001-09-21','2005-10-27','IT_PROG',20),
    (101,'2005-10-28','2006-03-15','SA_MAN',40),
    (102,'1993-01-13','2001-07-24','IT_PROG',20),
    (114,'1998-03-24','2006-12-31','SA_REP',40),
    (145,'2000-01-01','2004-09-30','SA_REP',40),
    (150,'2003-01-01','2005-12-31','SA_REP',40);
"""


def setup():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript(SCHEMA)
    print("Schema created.")

    for view_sql in VIEWS:
        cur.execute(view_sql)
    print(f"Created {len(VIEWS)} views.")

    cur.executemany(
        "INSERT INTO stored_procedures (name, description, parameters, body_sql) VALUES (?,?,?,?)",
        SP_DATA
    )
    print(f"Inserted {len(SP_DATA)} stored procedures.")

    cur.executescript(SEED)
    print("Seed data inserted.")

    conn.commit()

    # Summary
    for tbl in ['regions','countries','locations','departments','jobs','employees','job_history']:
        count = cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {count} rows")

    conn.close()
    print(f"\nDatabase ready: {DB_PATH}")


if __name__ == '__main__':
    setup()
