from flask import Flask, render_template, request, redirect, url_for, flash, g, jsonify, send_file, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
import bcrypt
import os
from datetime import date, datetime, timedelta
import random
import pandas as pd
from io import BytesIO
from weasyprint import HTML
import uuid

app = Flask(__name__)
app.secret_key = 'supersecretkey'
DB = 'crm.db'

login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    return User(row[0], row[1], row[2]) if row else None

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def format_date(date_str):
    if not date_str:
        return ''
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return d.strftime('%d/%m/%Y')
    except:
        return date_str

def init_db():
    db = sqlite3.connect(DB)
    c = db.cursor()

    # === TABLES ===
    c.execute('''
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY,
        business_type TEXT NOT NULL,
        business_name TEXT NOT NULL,
        contact_first TEXT,
        contact_last TEXT,
        phone TEXT,
        email TEXT,
        street TEXT,
        street2 TEXT,
        city TEXT,
        postcode TEXT,
        country TEXT,
        bacs_details TEXT,
        custom1 TEXT,
        custom2 TEXT,
        custom3 TEXT,
        default_interest_rate REAL DEFAULT 0.0
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS cases (
        id INTEGER PRIMARY KEY,
        client_id INTEGER NOT NULL,
        debtor_business_type TEXT,
        debtor_business_name TEXT,
        debtor_first TEXT,
        debtor_last TEXT,
        phone TEXT,
        email TEXT,
        street TEXT,
        street2 TEXT,
        city TEXT,
        postcode TEXT,
        country TEXT,
        status TEXT DEFAULT 'Open',
        substatus TEXT,
        next_action_date TEXT,
        open_date TEXT DEFAULT (date('now')),
        custom1 TEXT,
        custom2 TEXT,
        custom3 TEXT,
        interest_rate REAL,
        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash BLOB NOT NULL,
        role TEXT DEFAULT 'user'
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS money (
        id INTEGER PRIMARY KEY,
        case_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        transaction_date TEXT DEFAULT (date('now')),
        created_by INTEGER NOT NULL,
        note TEXT,
        recoverable INTEGER DEFAULT 0,
        billable INTEGER DEFAULT 0,
        FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY,
        case_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        created_by INTEGER NOT NULL,
        note TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY,
        client_id INTEGER NOT NULL,
        key TEXT UNIQUE NOT NULL,
        name TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (client_id) REFERENCES clients(id)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS debtor_tokens (
        id INTEGER PRIMARY KEY,
        case_id INTEGER NOT NULL,
        token TEXT UNIQUE NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (case_id) REFERENCES cases(id)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS outbound_logs (
        id INTEGER PRIMARY KEY,
        client_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        recipient TEXT NOT NULL,
        message TEXT,
        status TEXT DEFAULT 'queued',
        created_at TEXT DEFAULT (datetime('now'))
    )
    ''')

    # === ADD NEW COLUMNS (safe on every start) ===
    try:
        c.execute("ALTER TABLE money ADD COLUMN recoverable INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE money ADD COLUMN billable INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # === ADMIN USER: helmadmin / helmadmin ===
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        hashed = bcrypt.hashpw(b'helmadmin', bcrypt.gensalt())
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ('helmadmin', hashed, 'admin'))

    # === DUMMY DATA ===
    c.execute("SELECT COUNT(*) FROM clients")
    if c.fetchone()[0] == 0:
        print("INSERTING DUMMY DATA...")
        clients = [
            ("Limited", "Acme Corp", "John", "Doe", "01234 567890", "john@acme.com", "8.5"),
            ("Sole Trader", "Bob's Plumbing", "Bob", "Smith", "07700 900123", "bob@plumb.co.uk", "7.0"),
            ("Partnership", "Green & Co", "Sarah", "Green", "020 7946 0001", "sarah@green.co", "6.5"),
            ("Individual", "Freelance Designs", "Alex", "Taylor", "07890 123456", "alex@design.com", "9.0"),
            ("Limited", "Tech Solutions Ltd", "Mike", "Brown", "0113 496 0002", "mike@techsol.co.uk", "8.0")
        ]
        client_ids = []
        for cl in clients:
            c.execute('''
                INSERT INTO clients (business_type, business_name, contact_first, contact_last, phone, email, default_interest_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', cl)
            client_ids.append(c.lastrowid)

        debtor_types = ["Individual", "Sole Trader", "Limited", "Partnership"]
        statuses = ["Open", "On Hold", "Closed"]
        for client_id in client_ids:
            for i in range(5):
                debtor_type = random.choice(debtor_types)
                first = random.choice(["Emma", "James", "Olivia", "Liam", "Noah", "Ava"])
                last = random.choice(["Wilson", "Davis", "Martinez", "Lee", "Clark", "Walker"])
                business = f"{first} {last} Ltd" if debtor_type in ["Limited", "Partnership"] else None
                next_action = (datetime.now() + timedelta(days=random.randint(1, 30))).strftime('%Y-%m-%d')
                c.execute('''
                    INSERT INTO cases 
                    (client_id, debtor_business_type, debtor_business_name, debtor_first, debtor_last,
                     phone, email, status, substatus, next_action_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (client_id, debtor_type, business, first, last,
                      f"07{random.randint(100,999)} {random.randint(100000,999999)}",
                      f"{first.lower()}.{last.lower()}@example.com",
                      random.choice(statuses),
                      random.choice(["Awaiting Docs", "In Court", None]),
                      next_action))
                case_id = c.lastrowid
                for _ in range(random.randint(1,4)):
                    typ = random.choice(["Invoice","Payment","Charge","Interest"])
                    amt = round(random.uniform(100,5000),2)
                    c.execute("INSERT INTO money (case_id, type, amount, created_by) VALUES (?,?,?,1)",
                              (case_id, typ, amt))
                for _ in range(random.randint(0,3)):
                    note_type = random.choice(["General","Inbound Call","Outbound Call"])
                    c.execute("INSERT INTO notes (case_id, type, note, created_by) VALUES (?,?,?,1)",
                              (case_id, note_type, f"Sample {note_type.lower()} note"))

    db.commit()
    db.close()

# === CALL init_db ON STARTUP ===
init_db()

# === ROUTES ===

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        c = db.cursor()
        c.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        if user and bcrypt.checkpw(password.encode(), user['password_hash']):
            login_user(User(user['id'], user['username'], user['role']))
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/add_client', methods=['POST'])
@login_required
def add_client():
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO clients (business_type, business_name, contact_first, contact_last, phone, email, bacs_details, default_interest_rate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        request.form['business_type'],
        request.form['business_name'],
        request.form['contact_first'],
        request.form['contact_last'],
        request.form['phone'],
        request.form['email'],
        request.form['bacs_details'],
        request.form.get('default_interest_rate', 0)
    ))
    db.commit()
    flash('Client added')
    return redirect(url_for('dashboard'))

@app.route('/add_case', methods=['POST'])
@login_required
def add_case():
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO cases (client_id, debtor_business_type, debtor_business_name, debtor_first, debtor_last, phone, email, next_action_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        request.form['client_id'],
        request.form['debtor_business_type'],
        request.form['debtor_business_name'],
        request.form['debtor_first'],
        request.form['debtor_last'],
        request.form['phone'],
        request.form['email'],
        request.form['next_action_date']
    ))
    db.commit()
    flash('Case added')
    return redirect(url_for('dashboard'))

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    db = get_db()
    c = db.cursor()
    trans_date = request.form.get('transaction_date') or date.today().isoformat()
    recoverable = 1 if request.form.get('recoverable') else 0
    billable = 1 if request.form.get('billable') else 0

    c.execute('''
        INSERT INTO money (case_id, type, amount, created_by, note,
                           transaction_date, recoverable, billable)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        request.form['case_id'],
        request.form['type'],
        request.form['amount'],
        current_user.id,
        request.form.get('note', ''),
        trans_date,
        recoverable,
        billable
    ))
    db.commit()
    return redirect(url_for('dashboard', case_id=request.form['case_id']))

@app.route('/add_note', methods=['POST'])
@login_required
def add_note():
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO notes (case_id, type, note, created_by)
        VALUES (?, ?, ?, ?)
    ''', (
        request.form['case_id'],
        request.form['type'],
        request.form['note'],
        current_user.id
    ))
    db.commit()
    return redirect(url_for('dashboard', case_id=request.form['case_id']))

@app.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    field = request.args.get('field')
    mode = request.args.get('mode', 'contains')
    if not q or field not in ['debtor_name', 'client_name', 'postcode', 'email', 'phone']:
        return jsonify([])
    db = get_db()
    c = db.cursor()
    like = f"%{q}%" if mode == 'contains' else q
    sql = f'''
        SELECT c.id as client_id, c.business_name as client, s.id as case_id,
               COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor,
               s.postcode, s.email, s.phone, c.id as client_code
        FROM cases s
        JOIN clients c ON s.client_id = c.id
        WHERE {'s.debtor_business_name' if field == 'debtor_name' else 'c.business_name' if field == 'client_name' else 's.' + field} LIKE ?
        ORDER BY c.business_name, s.id
        LIMIT 50
    '''
    c.execute(sql, (like,))
    results = [dict(row) for row in c.fetchall()]
    return jsonify(results)

@app.route('/client_search')
@login_required
def client_search():
    q = request.args.get('q', '').strip()
    field = request.args.get('field')
    mode = request.args.get('mode', 'contains')
    if not q or field not in ['client_name', 'client_code']:
        return jsonify([])
    db = get_db()
    c = db.cursor()
    like = f"%{q}%" if mode == 'contains' else q
    if field == 'client_code':
        sql = "SELECT id, business_name as name FROM clients WHERE id = ?"
        c.execute(sql, (q if mode == 'is' else like,))
    else:
        sql = "SELECT id, business_name as name FROM clients WHERE business_name LIKE ? ORDER BY business_name LIMIT 20"
        c.execute(sql, (like,))
    results = [{'id': r['id'], 'name': r['name']} for r in c.fetchall()]
    return jsonify(results)

@app.route('/report')
@login_required
def report():
    client_code = request.args.get('client_code')
    report_html = ''
    if client_code:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT id, business_name FROM clients WHERE id = ?", (client_code,))
        client = c.fetchone()
        if client:
            c.execute("""
                SELECT s.id as case_id, s.debtor_business_name, s.debtor_first, s.debtor_last,
                       m.type, m.amount
                FROM cases s
                LEFT JOIN money m ON s.id = m.case_id
                WHERE s.client_id = ?
            """, (client_code,))
            rows = c.fetchall()
            cases = {}
            for r in rows:
                case_id = r['case_id']
                if case_id not in cases:
                    debtor = r['debtor_business_name'] or f"{r['debtor_first']} {r['debtor_last']}"
                    cases[case_id] = {'debtor': debtor, 'Invoice': 0, 'Payment': 0, 'Charge': 0, 'Interest': 0}
                if r['type']:
                    cases[case_id][r['type']] += r['amount']
            html = f"<h2>Client: {client['business_name']} (ID: {client['id']})</h2><table border='1' style='width:100%; border-collapse:collapse; font-family:Arial; font-size:12px;'><tr style='background:#ddd;'><th>Case ID</th><th>Debtor</th><th>Invoice</th><th>Payment</th><th>Charge</th><th>Interest</th><th>Balance</th></tr>"
            for case_id, d in cases.items():
                balance = d['Invoice'] + d['Charge'] + d['Interest'] - d['Payment']
                html += f"<tr><td>{case_id}</td><td>{d['debtor']}</td><td>£{d['Invoice']:.2f}</td><td>£{d['Payment']:.2f}</td><td>£{d['Charge']:.2f}</td><td>£{d['Interest']:.2f}</td><td>£{balance:.2f}</td></tr>"
            grand = {t: sum(c[t] for c in cases.values()) for t in ['Invoice','Payment','Charge','Interest']}
            grand_balance = grand['Invoice'] + grand['Charge'] + grand['Interest'] - grand['Payment']
            html += f"<tr style='font-weight:bold; background:#eee;'><td colspan='2'>TOTALS</td><td>£{grand['Invoice']:.2f}</td><td>£{grand['Payment']:.2f}</td><td>£{grand['Charge']:.2f}</td><td>£{grand['Interest']:.2f}</td><td>£{grand_balance:.2f}</td></tr></table>"
            report_html = html
    return render_template('report.html', report_html=report_html, client_code=client_code)

@app.route('/export_excel')
@login_required
def export_excel():
    client_code = request.args.get('client_code')
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id, business_name FROM clients WHERE id = ?", (client_code,))
    client = c.fetchone()
    if not client:
        return "Client not found", 404

    c.execute("""
        SELECT s.id as case_id, s.debtor_business_name, s.debtor_first, s.debtor_last,
               m.type, m.amount
        FROM cases s
        LEFT JOIN money m ON s.id = m.case_id
        WHERE s.client_id = ?
    """, (client_code,))
    rows = c.fetchall()

    cases = {}
    for r in rows:
        case_id = r['case_id']
        if case_id not in cases:
            debtor = r['debtor_business_name'] or f"{r['debtor_first']} {r['debtor_last']}"
            cases[case_id] = {'debtor': debtor, 'Invoice': 0, 'Payment': 0, 'Charge': 0, 'Interest': 0}
        if r['type']:
            cases[case_id][r['type']] += r['amount']

    data = []
    for case_id, d in cases.items():
        balance = d['Invoice'] + d['Charge'] + d['Interest'] - d['Payment']
        data.append([case_id, d['debtor'], d['Invoice'], d['Payment'], d['Charge'], d['Interest'], balance])

    df = pd.DataFrame(data, columns=['Case ID', 'Debtor', 'Invoice', 'Payment', 'Charge', 'Interest', 'Balance'])
    df.loc['Total'] = ['', 'TOTALS', df['Invoice'].sum(), df['Payment'].sum(), df['Charge'].sum(), df['Interest'].sum(), df['Balance'].sum()]

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name=f"report_client_{client_code}.xlsx", as_attachment=True)

@app.route('/export_pdf')
@login_required
def export_pdf():
    client_code = request.args.get('client_code')
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id, business_name FROM clients WHERE id = ?", (client_code,))
    client = c.fetchone()
    if not client:
        return "Client not found", 404

    c.execute("""
        SELECT s.id as case_id, s.debtor_business_name, s.debtor_first, s.debtor_last,
               m.type, m.amount
        FROM cases s
        LEFT JOIN money m ON s.id = m.case_id
        WHERE s.client_id = ?
    """, (client_code,))
    rows = c.fetchall()

    cases = {}
    for r in rows:
        case_id = r['case_id']
        if case_id not in cases:
            debtor = r['debtor_business_name'] or f"{r['debtor_first']} {r['debtor_last']}"
            cases[case_id] = {'debtor': debtor, 'Invoice': 0, 'Payment': 0, 'Charge': 0, 'Interest': 0}
        if r['type']:
            cases[case_id][r['type']] += r['amount']

    html = f"""
    <h1>Client Report: {client['business_name']} (ID: {client['id']})</h1>
    <table border="1" style="width:100%; border-collapse:collapse; font-family:Arial; font-size:12px;">
        <tr style="background:#ddd;">
            <th>Case ID</th><th>Debtor</th><th>Invoice</th><th>Payment</th><th>Charge</th><th>Interest</th><th>Balance</th>
        </tr>
    """
    for case_id, d in cases.items():
        balance = d['Invoice'] + d['Charge'] + d['Interest'] - d['Payment']
        html += f"""
        <tr>
            <td>{case_id}</td>
            <td>{d['debtor']}</td>
            <td>£{d['Invoice']:.2f}</td>
            <td>£{d['Payment']:.2f}</td>
            <td>£{d['Charge']:.2f}</td>
            <td>£{d['Interest']:.2f}</td>
            <td>£{balance:.2f}</td>
        </tr>
        """
    grand = {t: sum(c[t] for c in cases.values()) for t in ['Invoice','Payment','Charge','Interest']}
    grand_balance = grand['Invoice'] + grand['Charge'] + grand['Interest'] - grand['Payment']
    html += f"""
        <tr style="font-weight:bold; background:#eee;">
            <td colspan="2">TOTALS</td>
            <td>£{grand['Invoice']:.2f}</td>
            <td>£{grand['Payment']:.2f}</td>
            <td>£{grand['Charge']:.2f}</td>
            <td>£{grand['Interest']:.2f}</td>
            <td>£{grand_balance:.2f}</td>
        </tr>
    </table>
    """

    pdf = HTML(string=html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=report_client_{client_code}.pdf'
    return response

# === API ROUTES ===
@app.route('/api/generate_key', methods=['POST'])
@login_required
def generate_key():
    db = get_db()
    c = db.cursor()
    key = str(uuid.uuid4())
    name = request.json.get('name', 'API Key')
    c.execute("INSERT INTO api_keys (client_id, key, name) VALUES (?, ?, ?)", (1, key, name))
    db.commit()
    return jsonify({'key': key})

@app.route('/api/keys')
@login_required
def list_keys():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id, name FROM api_keys WHERE active = 1")
    return jsonify([{'id': r['id'], 'name': r['name']} for r in c.fetchall()])

@app.route('/api/revoke_key/<int:key_id>', methods=['POST'])
@login_required
def revoke_key(key_id):
    db = get_db()
    c = db.cursor()
    c.execute("UPDATE api_keys SET active = 0 WHERE id = ?", (key_id,))
    db.commit()
    return '', 204

# === DASHBOARD ===
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    c = db.cursor()

    c.execute("SELECT id, business_name FROM clients ORDER BY business_name")
    clients = c.fetchall()

    c.execute("""
        SELECT c.id as client_id, c.business_name, s.id as case_id, 
               s.debtor_business_name, s.debtor_first, s.debtor_last
        FROM clients c
        LEFT JOIN cases s ON c.id = s.client_id
        ORDER BY c.business_name, s.id
    """)
    all_cases = c.fetchall()

    selected_case = None
    case_client = None
    client_cases = []
    notes = []
    transactions = []
    balance = 0.0
    totals = {'Invoice': 0, 'Payment': 0, 'Charge': 0, 'Interest': 0}

    case_id = request.args.get('case_id')
    if case_id:
        c.execute("SELECT * FROM cases WHERE id = ?", (case_id,))
        selected_case = c.fetchone()
        if selected_case:
            c.execute("SELECT * FROM clients WHERE id = ?", (selected_case['client_id'],))
            case_client = c.fetchone()

            c.execute("SELECT id, debtor_business_name, debtor_first, debtor_last FROM cases WHERE client_id = ? ORDER BY id", (selected_case['client_id'],))
            client_cases = c.fetchall()

            c.execute('SELECT n.*, u.username FROM notes n JOIN users u ON n.created_by = u.id WHERE n.case_id = ? ORDER BY n.created_at DESC', (case_id,))
            notes = c.fetchall()

            c.execute('SELECT m.*, u.username FROM money m JOIN users u ON m.created_by = u.id WHERE m.case_id = ? ORDER BY m.transaction_date DESC, m.id DESC', (case_id,))
            transactions = c.fetchall()

            for t in transactions:
                amt = t['amount']
                typ = t['type']
                totals[typ] += amt
                if typ == 'Payment':
                    balance -= amt
                else:
                    balance += amt

    return render_template('dashboard.html',
                           clients=clients,
                           all_cases=all_cases,
                           selected_case=selected_case,
                           case_client=case_client,
                           client_cases=client_cases,
                           notes=notes,
                           transactions=transactions,
                           balance=balance,
                           totals=totals,
                           format_date=format_date)

if __name__ == '__main__':
    app.run(debug=True)
