"""
Column Lineage Diagram - Flask Application
Run: python app.py  (after running setup_db.py once)
"""
import os, re, json, sqlite3, time
from datetime import datetime
from flask import Flask, jsonify, request, render_template, Response

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hr.db')

# ── Connection Registry ───────────────────────────────────────
# Each entry: { type, label, path|connector }
CONNECTIONS = {
    'hr': {'type': 'sqlite', 'label': 'HR Domain (SQLite)', 'path': DB_PATH}
}


# ─────────────────────────────────────────────────────────────
# CONNECTORS
# ─────────────────────────────────────────────────────────────

class SqliteConnector:
    def __init__(self, path):
        self.path = path

    def test(self):
        conn = sqlite3.connect(self.path)
        conn.execute('SELECT 1')
        conn.close()

    def get_all_objects(self):
        conn = sqlite3.connect(self.path)
        try:
            return _sqlite_get_all_objects(conn)
        finally:
            conn.close()


class SqlServerConnector:
    def __init__(self, server, port, database, username, password, schema='dbo', auth_type='sql'):
        self.server   = server
        self.port     = int(port)
        self.database = database
        self.username = username
        self.password = password
        self.schema   = schema
        self.auth_type = auth_type

    def _cs(self):
        try:
            import pyodbc
        except ImportError:
            raise RuntimeError('pyodbc not installed. Run: pip install pyodbc')
        drivers = [d for d in pyodbc.drivers() if 'SQL Server' in d]
        driver  = drivers[-1] if drivers else 'SQL Server'
        cs = f'DRIVER={{{driver}}};SERVER={self.server},{self.port};DATABASE={self.database};'
        if self.auth_type == 'windows':
            cs += 'Trusted_Connection=yes;'
        else:
            cs += f'UID={self.username};PWD={self.password};'
        return cs

    def test(self):
        import pyodbc
        c = pyodbc.connect(self._cs(), timeout=8)
        c.close()

    def get_all_objects(self):
        import pyodbc
        conn = pyodbc.connect(self._cs())
        try:
            sch = self.schema
            # Tables + columns
            rows = conn.execute("""
                SELECT t.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE,
                    CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END
                FROM INFORMATION_SCHEMA.TABLES t
                JOIN INFORMATION_SCHEMA.COLUMNS c
                    ON t.TABLE_NAME=c.TABLE_NAME AND t.TABLE_SCHEMA=c.TABLE_SCHEMA
                LEFT JOIN (
                    SELECT ku.TABLE_NAME, ku.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                        ON tc.CONSTRAINT_NAME=ku.CONSTRAINT_NAME AND tc.TABLE_SCHEMA=ku.TABLE_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE='PRIMARY KEY'
                ) pk ON c.TABLE_NAME=pk.TABLE_NAME AND c.COLUMN_NAME=pk.COLUMN_NAME
                WHERE t.TABLE_TYPE='BASE TABLE' AND t.TABLE_SCHEMA=?
                ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION""", sch).fetchall()

            tables_d = {}
            for tname, cname, dtype, is_pk in rows:
                tables_d.setdefault(tname, []).append(
                    {'name': cname.lower(), 'data_type': dtype, 'is_pk': bool(is_pk)})
            tables = [{'name': k,'type':'table','columns':v,'sql':None} for k,v in tables_d.items()]

            # Views
            vrows = conn.execute("""
                SELECT v.TABLE_NAME, m.definition
                FROM INFORMATION_SCHEMA.VIEWS v
                JOIN sys.sql_modules m ON m.object_id=OBJECT_ID(v.TABLE_SCHEMA+'.'+v.TABLE_NAME)
                WHERE v.TABLE_SCHEMA=?""", sch).fetchall()
            views = []
            for vname, vdef in vrows:
                try:
                    vcols = conn.execute("""
                        SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME=? AND TABLE_SCHEMA=? ORDER BY ORDINAL_POSITION""",
                        vname, sch).fetchall()
                    cols = [{'name': r[0].lower(),'data_type':r[1],'is_pk':False} for r in vcols]
                except Exception:
                    cols = extract_output_columns_from_sql(vdef or '')
                views.append({'name':vname,'type':'view','columns':cols,'sql':vdef})

            # Stored procedures
            sprows = conn.execute("""
                SELECT p.name, m.definition FROM sys.procedures p
                JOIN sys.sql_modules m ON m.object_id=p.object_id
                WHERE SCHEMA_NAME(p.schema_id)=? ORDER BY p.name""", sch).fetchall()
            sps = [{'name':n,'type':'procedure',
                    'columns':extract_output_columns_from_sql(d or ''),'sql':d}
                   for n,d in sprows]

            return {'tables':tables,'views':views,'stored_procedures':sps}
        finally:
            conn.close()


class JsonConnector:
    def __init__(self, data):
        self.data = data

    def test(self):
        if 'tables' not in self.data and 'lineage' not in self.data:
            raise ValueError('JSON must contain "tables" and/or "lineage" keys')

    def get_all_objects(self):
        def norm_cols(cols):
            return [{'name': c['name'].lower(),
                     'data_type': c.get('data_type','ANY'),
                     'is_pk': c.get('is_pk',False)} for c in cols]

        tables = [{'name':t['name'],'type':'table',
                   'columns':norm_cols(t.get('columns',[])),'sql':None}
                  for t in self.data.get('tables',[])]

        views = []
        for v in self.data.get('views',[]):
            cols = norm_cols(v['columns']) if v.get('columns') \
                   else extract_output_columns_from_sql(v.get('sql','') or '')
            views.append({'name':v['name'],'type':'view','columns':cols,'sql':v.get('sql')})

        sps = []
        for sp in self.data.get('stored_procedures',[]):
            cols = norm_cols(sp['columns']) if sp.get('columns') \
                   else extract_output_columns_from_sql(sp.get('body_sql','') or '')
            sps.append({'name':sp['name'],'type':'procedure','columns':cols,'sql':sp.get('body_sql')})

        return {'tables':tables,'views':views,'stored_procedures':sps}

    def get_explicit_lineage(self):
        return self.data.get('lineage', [])


# ─────────────────────────────────────────────────────────────
# SQLITE METADATA READER
# ─────────────────────────────────────────────────────────────

def get_table_columns(conn, name):
    rows = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
    return [{'name': r[1].lower(), 'data_type': r[2] or 'TEXT', 'is_pk': bool(r[5])} for r in rows]


def extract_output_columns_from_sql(sql):
    m = re.search(r'\bSELECT\b(.*?)\bFROM\b', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    cols = []
    for part in _split_csv(m.group(1)):
        part = part.strip()
        if not part or part == '*':
            continue
        alias_m = re.search(r'\bAS\s+(\w+)\s*$', part, re.IGNORECASE)
        name = alias_m.group(1).lower() if alias_m else (re.findall(r'\b(\w+)\b', part) or ['col'])[-1].lower()
        cols.append({'name': name, 'data_type': 'ANY', 'is_pk': False})
    return cols


def _sqlite_get_all_objects(conn):
    excluded = {'sqlite_sequence', 'stored_procedures'}
    tbl_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    tables = [{'name': n, 'type': 'table', 'columns': get_table_columns(conn, n), 'sql': None}
              for (n,) in tbl_rows if n not in excluded]

    view_rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='view'").fetchall()
    views = [{'name': n, 'type': 'view', 'columns': get_table_columns(conn, n), 'sql': s}
             for n, s in view_rows]

    sps = []
    try:
        for n, body, *_ in conn.execute(
                "SELECT name, body_sql FROM stored_procedures").fetchall():
            sps.append({'name': n, 'type': 'procedure',
                        'columns': extract_output_columns_from_sql(body), 'sql': body})
    except Exception:
        pass

    return {'tables': tables, 'views': views, 'stored_procedures': sps}


# ─────────────────────────────────────────────────────────────
# SQL PARSER
# ─────────────────────────────────────────────────────────────

def _split_csv(text):
    parts, depth, buf = [], 0, []
    for ch in text:
        if ch == '(':
            depth += 1; buf.append(ch)
        elif ch == ')':
            depth = max(0, depth-1); buf.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf)); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf))
    return parts


class LineageParser:
    def __init__(self, catalog):
        self.catalog = {k.lower(): [c.lower() for c in v] for k, v in catalog.items()}

    def parse(self, target_name, sql_text):
        sql = self._normalize(sql_text)
        alias_map = self._build_alias_map(sql)
        columns   = self._extract_columns(sql)
        edges, seen = [], set()
        for col in columns:
            for src_table, src_col in self._resolve(col['refs'], alias_map):
                key = (src_table, src_col, target_name, col['alias'])
                if key not in seen:
                    seen.add(key)
                    edges.append({'source_node': src_table, 'source_column': src_col,
                                  'target_node': target_name, 'target_column': col['alias'],
                                  'edge_type': col['type']})
        return edges

    def _normalize(self, sql):
        sql = re.sub(r'^\s*CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+\w+\s+AS\s*', '', sql, flags=re.IGNORECASE)
        return sql.strip().rstrip(';')

    def _build_alias_map(self, sql):
        alias_map = {}
        for m in re.finditer(r'(?:FROM|JOIN)\s+(\w+)(?:\s+AS\s+(\w+)|\s+(\w+))?', sql, re.IGNORECASE):
            table = m.group(1).lower()
            if table in self.catalog:
                alias = (m.group(2) or m.group(3) or m.group(1)).lower()
                alias_map[alias] = table
        return alias_map

    def _extract_columns(self, sql):
        m = re.search(r'\bSELECT\b(.*?)\bFROM\b', sql, re.IGNORECASE | re.DOTALL)
        if not m:
            return []
        columns = []
        for part in _split_csv(m.group(1)):
            part = part.strip()
            if not part:
                continue
            am = re.search(r'\bAS\s+(\w+)\s*$', part, re.IGNORECASE)
            if am:
                alias = am.group(1).lower(); expr = part[:am.start()].strip()
            else:
                tokens = re.findall(r'\b\w+\b', part)
                alias = tokens[-1].lower() if tokens else 'unknown'; expr = part
            eu = expr.upper()
            if re.search(r'\b(COUNT|SUM|AVG|MIN|MAX)\s*\(', eu): etype = 'aggregate'
            elif 'CASE' in eu:   etype = 'case'
            elif '||' in expr:  etype = 'concat'
            elif re.search(r'\b(ROUND|COALESCE|NVL|CAST|ABS)\s*\(', eu): etype = 'computed'
            else: etype = 'direct'
            columns.append({'alias': alias, 'refs': re.findall(r'(\w+)\.(\w+)', expr), 'type': etype})
        return columns

    def _resolve(self, refs, alias_map):
        resolved, seen = [], set()
        for alias, col in refs:
            real = alias_map.get(alias.lower())
            if real and real in self.catalog and col.lower() in self.catalog[real]:
                key = (real, col.lower())
                if key not in seen:
                    seen.add(key); resolved.append(key)
        return resolved


# ─────────────────────────────────────────────────────────────
# GRAPH BUILDER
# ─────────────────────────────────────────────────────────────

def build_graph(all_objects, edges):
    nodes = [{'id': o['name'], 'label': o['name'], 'type': o['type'],
               'columns': o['columns'], 'x': None, 'y': None}
             for o in all_objects['tables'] + all_objects['views'] + all_objects['stored_procedures']]
    edge_list = [{'id': f'e{i}', **e} for i, e in enumerate(edges)]
    return {'nodes': nodes, 'edges': edge_list}


def _run_lineage(conn_id):
    conf = CONNECTIONS.get(conn_id)
    if not conf:
        return None, f'Unknown connection: {conn_id}'
    try:
        ctype = conf['type']
        if ctype == 'sqlite':
            conn = sqlite3.connect(conf['path'])
            try:
                all_objects = _sqlite_get_all_objects(conn)
            finally:
                conn.close()
        elif ctype == 'sqlserver':
            all_objects = conf['connector'].get_all_objects()
        elif ctype == 'json':
            all_objects = conf['connector'].get_all_objects()
            explicit = conf['connector'].get_explicit_lineage()
            if explicit:
                edges = [{'source_node': e.get('source_object', e.get('source_node','')),
                          'source_column': e.get('source_column','').lower(),
                          'target_node': e.get('target_object', e.get('target_node','')),
                          'target_column': e.get('target_column','').lower(),
                          'edge_type': e.get('edge_type','direct')} for e in explicit]
                return {'graph': build_graph(all_objects, edges), 'warnings': []}, None
        else:
            return None, f'Unknown connection type: {ctype}'

        catalog = {o['name']: [c['name'] for c in o['columns']]
                   for o in all_objects['tables'] + all_objects['views']}
        parser = LineageParser(catalog)
        all_edges, warnings = [], []
        for obj in all_objects['views'] + all_objects['stored_procedures']:
            if obj.get('sql'):
                try:
                    all_edges.extend(parser.parse(obj['name'], obj['sql']))
                except Exception as ex:
                    warnings.append(f"{obj['name']}: {str(ex)}")
        return {'graph': build_graph(all_objects, all_edges), 'warnings': warnings}, None
    except Exception as e:
        return None, str(e)


# ─────────────────────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/databases')
def list_databases():
    return jsonify({'databases': [
        {'id': k, 'label': v['label'], 'type': v['type']}
        for k, v in CONNECTIONS.items()
    ]})


@app.route('/api/lineage')
def get_lineage():
    conn_id = request.args.get('db', 'hr')
    result, err = _run_lineage(conn_id)
    if err:
        return jsonify({'error': err}), 400
    return jsonify({
        'graph': result['graph'],
        'metadata': {
            'database': conn_id,
            'generated_at': datetime.utcnow().isoformat(),
            'parse_warnings': result['warnings'],
            'node_count': len(result['graph']['nodes']),
            'edge_count': len(result['graph']['edges'])
        }
    })


@app.route('/api/connect', methods=['POST'])
def add_connection():
    data     = request.json or {}
    ctype    = data.get('type')
    label    = data.get('label', 'Unnamed Connection').strip() or 'Unnamed Connection'
    test_only = data.get('test_only', False)

    try:
        if ctype == 'sqlite':
            path = data.get('path', '').strip()
            if not path:
                return jsonify({'error': 'File path is required'}), 400
            if not os.path.exists(path):
                return jsonify({'error': f'File not found: {path}'}), 400
            connector = SqliteConnector(path)
            connector.test()
            if not test_only:
                cid = f'sqlite_{int(time.time())}'
                CONNECTIONS[cid] = {'type': 'sqlite', 'label': label, 'path': path}
                return jsonify({'success': True, 'id': cid, 'label': label})

        elif ctype == 'sqlserver':
            required = ['server', 'database']
            missing  = [f for f in required if not data.get(f, '').strip()]
            if missing:
                return jsonify({'error': f'Required: {", ".join(missing)}'}), 400
            connector = SqlServerConnector(
                server=data['server'].strip(), port=data.get('port', 1433),
                database=data['database'].strip(), username=data.get('username','').strip(),
                password=data.get('password',''), schema=data.get('schema','dbo').strip(),
                auth_type=data.get('auth_type','sql'))
            connector.test()
            if not test_only:
                cid = f'ss_{int(time.time())}'
                CONNECTIONS[cid] = {'type': 'sqlserver', 'label': label, 'connector': connector}
                return jsonify({'success': True, 'id': cid, 'label': label})

        else:
            return jsonify({'error': f'Unknown type: {ctype}'}), 400

        return jsonify({'success': True, 'message': 'Connection successful'})

    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/upload-json', methods=['POST'])
def upload_json():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    try:
        raw  = json.loads(f.read().decode('utf-8'))
    except json.JSONDecodeError as e:
        return jsonify({'error': f'Invalid JSON: {e}'}), 400

    connector = JsonConnector(raw)
    try:
        connector.test()
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    label = (request.form.get('label') or raw.get('database_name') or
             (f.filename or 'JSON Metadata').replace('.json','')).strip()
    cid   = f'json_{int(time.time())}'
    CONNECTIONS[cid] = {'type': 'json', 'label': label, 'connector': connector}
    return jsonify({'success': True, 'id': cid, 'label': label})


@app.route('/api/sample-json')
def sample_json():
    """Download a sample JSON metadata file based on the HR database."""
    conn = sqlite3.connect(DB_PATH)
    try:
        objs = _sqlite_get_all_objects(conn)
    finally:
        conn.close()

    sample = {
        'database_name': 'MyDatabase',
        '_comment': 'Provide either sql/body_sql for auto-parsing OR fill the lineage array for explicit mapping.',
        'tables': [{'name': t['name'], 'columns': t['columns']} for t in objs['tables']],
        'views':  [{'name': v['name'], 'sql': '', 'columns': v['columns']} for v in objs['views']],
        'stored_procedures': [{'name': s['name'], 'body_sql': '', 'columns': s['columns']}
                              for s in objs['stored_procedures']],
        'lineage': [
            {'source_object': 'table_name', 'source_column': 'col_name',
             'target_object': 'view_name',  'target_column': 'col_alias',
             'edge_type': 'direct'}
        ]
    }
    return Response(json.dumps(sample, indent=2), mimetype='application/json',
                    headers={'Content-Disposition': 'attachment; filename="lineage_template.json"'})


@app.route('/api/export')
def export_html():
    conn_id = request.args.get('db', 'hr')
    result, err = _run_lineage(conn_id)
    if err:
        return jsonify({'error': err}), 400

    graph      = result['graph']
    graph_json = json.dumps(graph)
    label      = CONNECTIONS.get(conn_id, {}).get('label', conn_id)

    js_path  = os.path.join(os.path.dirname(__file__), 'static', 'js', 'diagram.js')
    css_path = os.path.join(os.path.dirname(__file__), 'static', 'css', 'diagram.css')
    with open(js_path)  as f: diagram_js  = f.read()
    with open(css_path) as f: diagram_css = f.read()

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Column Lineage — {label}</title>
<style>
body {{ margin:0; font-family:system-ui,sans-serif; }}
{diagram_css}
.export-hdr {{ background:var(--bg-toolbar); color:white; padding:10px 20px;
  display:flex; align-items:center; gap:16px; border-bottom:1px solid var(--border); height:52px; }}
.export-hdr h1 {{ margin:0; font-size:15px; font-weight:700; }}
.export-meta  {{ font-size:11px; color:#94A3B8; }}
.export-ctrl  {{ margin-left:auto; display:flex; gap:8px; align-items:center; }}
#diagram-svg  {{ width:100vw; height:calc(100vh - 52px - 46px); display:block; }}
</style>
</head>
<body>
<div class="export-hdr">
  <h1>&#128279; Column Lineage</h1>
  <span class="export-meta">{label} &nbsp;·&nbsp; Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}
    &nbsp;·&nbsp; {len(graph['nodes'])} objects &nbsp;·&nbsp; {len(graph['edges'])} relationships</span>
  <div class="export-ctrl">
    <button class="btn-secondary" onclick="toggleTheme()" id="theme-btn">&#9728; Light</button>
    <input id="search-input" type="text" class="search-input" placeholder="Search..."
           oninput="DiagramEngine.filter(this.value)">
    <button class="btn-secondary" onclick="DiagramEngine.resetView()">&#8635; Fit</button>
  </div>
</div>
<div id="lineage-bar" class="lb-empty">
  <span class="lb-hint">&#128073; Click any column to trace its lineage</span>
  <div class="lb-content">
    <div class="lb-selected">
      <button class="lb-clear-btn" onclick="DiagramEngine.clearSelection()">&#10005;</button>
      <span class="lb-badge" id="lb-badge"></span>
      <span class="lb-obj" id="lb-obj"></span><span class="lb-dot">.</span>
      <span class="lb-col" id="lb-col"></span><span class="lb-dtype" id="lb-dtype"></span>
    </div>
    <div class="lb-divider"></div>
    <div class="lb-group"><div class="lb-group-label">&#9650; Sources</div>
      <div class="lb-chips" id="lb-sources"></div></div>
    <div class="lb-divider"></div>
    <div class="lb-group"><div class="lb-group-label">&#9660; Targets</div>
      <div class="lb-chips" id="lb-targets"></div></div>
    <div class="lb-divider"></div>
    <div class="lb-total" id="lb-total"></div>
  </div>
</div>
<svg id="diagram-svg"></svg>
<div id="tooltip" class="tooltip"></div>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const GRAPH_DATA = {graph_json};
const TYPE_COLORS = {{ table:'#1D4ED8', view:'#15803D', procedure:'#C2410C' }};
function makeChip(item) {{
  const c = document.createElement('span');
  c.className = `lb-chip lb-chip-${{item.objectType}}`;
  c.innerHTML = `<span class="lb-chip-obj">${{item.nodeId}}</span>.<strong>${{item.colName}}</strong>`;
  c.onclick = () => DiagramEngine.selectColumn(item.nodeId, item.colName);
  return c;
}}
document.addEventListener('lineage-selected', e => {{
  const {{ nodeId, colName, dataType, objectType, sources, targets, totalConnected }} = e.detail;
  const bar = document.getElementById('lineage-bar');
  bar.classList.remove('lb-empty');
  document.getElementById('lb-badge').textContent  = objectType.toUpperCase();
  document.getElementById('lb-badge').style.background = TYPE_COLORS[objectType]||'#475569';
  document.getElementById('lb-obj').textContent   = nodeId;
  document.getElementById('lb-col').textContent   = colName;
  document.getElementById('lb-dtype').textContent = dataType;
  const srcEl = document.getElementById('lb-sources'); srcEl.innerHTML='';
  (sources.length ? sources : []).forEach(s => srcEl.appendChild(makeChip(s)));
  if (!sources.length) srcEl.innerHTML='<span class="lb-chip lb-chip-none">— base column</span>';
  const tgtEl = document.getElementById('lb-targets'); tgtEl.innerHTML='';
  (targets.length ? targets : []).forEach(t => tgtEl.appendChild(makeChip(t)));
  if (!targets.length) tgtEl.innerHTML='<span class="lb-chip lb-chip-none">— no downstream</span>';
  document.getElementById('lb-total').textContent = totalConnected + ' total connected column(s)';
}});
document.addEventListener('lineage-cleared', () => {{
  document.getElementById('lineage-bar').classList.add('lb-empty');
}});
function toggleTheme() {{
  const html = document.documentElement;
  const next = html.dataset.theme === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  document.getElementById('theme-btn').textContent = next === 'dark' ? '\\u2600 Light' : '\\u263D Dark';
  DiagramEngine.reapplyColors();
}}
</script>
<script>
{diagram_js}
document.addEventListener('DOMContentLoaded', () => {{
  DiagramEngine.init('#diagram-svg', GRAPH_DATA);
  document.addEventListener('keydown', e => {{ if(e.key==='Escape') DiagramEngine.clearSelection(); }});
}});
</script>
</body>
</html>"""

    fname = f"lineage_{conn_id}_{datetime.now().strftime('%Y%m%d')}.html"
    return Response(html, mimetype='text/html',
                    headers={'Content-Disposition': f'attachment; filename="{fname}"'})


if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        print("Database not found. Run: python setup_db.py")
    else:
        app.run(debug=True, port=5000)
