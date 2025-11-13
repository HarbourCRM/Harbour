from flask import Flask, render_template, request, redirect, url_for, flash, g, jsonify, send_file, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
import bcrypt
import os
from datetime import date, datetime, timedelta
import random
from io import BytesIO
from weasyprint import HTML
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side

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

# === INIT DB ===
def init_db():
    db = sqlite3.connect(DB)
    c = db.cursor()

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

    # ADMIN
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        hashed = bcrypt.hashpw(b'admin', bcrypt.gensalt())
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ('admin', hashed, 'admin'))

    db.commit()
    db.close()

# === ROUTES ===
@app.route('/add_client', methods=['POST'])
@login_required
def add_client():
    db = get_db()
    c = db.cursor()
    data = (
        request.form['business_type'],
        request.form['business_name'],
        request.form.get('contact_first'),
        request.form.get('contact_last'),
        request.form.get('phone'),
        request.form.get('email'),
        request.form.get('bacs_details'),
        float(request.form.get('default_interest_rate', 0))
    )
    c.execute('''
        INSERT INTO clients (business_type, business_name, contact_first, contact_last, phone, email, bacs_details, default_interest_rate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', data)
    db.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_case', methods=['POST'])
@login_required
def add_case():
    db = get_db()
    c = db.cursor()
    data = (
        request.form['client_id'],
        request.form['debtor_business_type'],
        request.form.get('debtor_business_name'),
        request.form.get('debtor_first'),
        request.form.get('debtor_last'),
        request.form.get('phone'),
        request.form.get('email')
    )
    c.execute('''
        INSERT INTO cases (client_id, debtor_business_type, debtor_business_name, debtor_first, debtor_last, phone, email)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', data)
    db.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_note', methods=['POST'])
@login_required
def add_note():
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO notes (case_id, type, created_by, note)
        VALUES (?, ?, ?, ?)
    ''', (request.form['case_id'], request.form['note_type'], current_user.id, request.form['note']))
    db.commit()
    return redirect(url_for('dashboard', case_id=request.form['case_id']))

@app.route('/add_money', methods=['POST'])
@login_required
def add_money():
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO money (case_id, type, amount, created_by, note)
        VALUES (?, ?, ?, ?, ?)
    ''', (request.form['case_id'], request.form['type'], float(request.form['amount']), current_user.id, request.form.get('note')))
    db.commit()
    return redirect(url_for('dashboard', case_id=request.form['case_id']))

@app.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    field = request.args.get('field')
    mode = request.args.get('mode', 'contains')
    db = get_db()
    c = db.cursor()

    if not q:
        return jsonify([])

    sql = """
        SELECT c.id as client_code, c.business_name as client, 
               COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor,
               s.id as case_id, s.postcode, s.email, s.phone
        FROM cases s
        JOIN clients c ON s.client_id = c.id
        WHERE 
    """
    params = []

    if field == 'client_name':
        sql += "c.business_name LIKE ?"
    elif field == 'debtor_name':
        sql += "(s.debtor_first LIKE ? OR s.debtor_last LIKE ? OR s.debtor_business_name LIKE ?)"
        params = [f"%{q}%"] * 3
    else:
        sql += f"s.{field} LIKE ?"
        params = [f"%{q}%" if mode == 'contains' else q]

    c.execute(sql, params)
    results = [dict(row) for row in c.fetchall()]
    return jsonify(results)

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

    wb = Workbook()
    ws = wb.active
    ws.title = "Client Report"

    headers = ["Case ID", "Debtor", "Invoice", "Payment", "Charge", "Interest", "Balance"]
    ws.append(headers)

    thin = Side(border_style="thin")
    for row in ws[1:1]:
        for cell in row:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")

    for case_id, d in cases.items():
        balance = d['Invoice'] + d['Charge'] + d['Interest'] - d['Payment']
        ws.append([case_id, d['debtor'], d['Invoice'], d['Payment'], d['Charge'], d['Interest'], balance])

    grand = {t: sum(c[t] for c in cases.values()) for t in ['Invoice','Payment','Charge','Interest']}
    grand_balance = grand['Invoice'] + grand['Charge'] + grand['Interest'] - grand['Payment']
    ws.append(["TOTALS", "", grand['Invoice'], grand['Payment'], grand['Charge'], grand['Interest'], grand_balance])

    for row in ws.iter_rows():
        for cell in row:
            cell.border = Border(top=thin, left=thin, right=thin, bottom=thin)

    output = BytesIO()
    wb.save(output)
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
            <td>£{d['Invoice']:,.2f}</td>
            <td>£{d['Payment']:,.2f}</td>
            <td>£{d['Charge']:,.2f}</td>
            <td>£{d['Interest']:,.2f}</td>
            <td>£{balance:,.2f}</td>
        </tr>
        """
    grand = {t: sum(c[t] for c in cases.values()) for t in ['Invoice','Payment','Charge','Interest']}
    grand_balance = grand['Invoice'] + grand['Charge'] + grand['Interest'] - grand['Payment']
    html += f"""
        <tr style="font-weight:bold; background:#eee;">
            <td colspan="2">TOTALS</td>
            <td>£{grand['Invoice']:,.2f}</td>
            <td>£{grand['Payment']:,.2f}</td>
            <td>£{grand['Charge']:,.2f}</td>
            <td>£{grand['Interest']:,.2f}</td>
            <td>£{grand_balance:,.2f}</td>
        </tr>
    </table>
    """

    pdf = HTML(string=html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=report_client_{client_code}.pdf'
    return response

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

    balance_str = f"£{balance:,.2f}"

    return render_template('dashboard.html',
                           clients=clients,
                           all_cases=all_cases,
                           selected_case=selected_case,
                           case_client=case_client,
                           client_cases=client_cases,
                           notes=notes,
                           transactions=transactions,
                           balance=balance_str,
                           totals=totals)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        db = get_db()
        c = db.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        if user and bcrypt.checkpw(password, user['password_hash']):
            login_user(User(user['id'], user['username'], user['role']))
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/report')
@login_required
def report():
    return render_template('report.html')

# === CRITICAL: Recreate DB on every deploy ===
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True)

