from flask import Flask, render_template, request, redirect, url_for, flash, g, jsonify, send_file, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
import psycopg
from psycopg.rows import dict_row
import bcrypt
from datetime import date, datetime
import pandas as pd
from io import BytesIO
from weasyprint import HTML
import uuid

app = Flask(__name__)

app.config['DEBUG'] = True
app.config['PROPAGATE_EXCEPTIONS'] = True
app.config['TRAP_HTTP_EXCEPTIONS'] = False


app.secret_key = 'supersecretkey'  # You said security later

DATABASE_URL = os.environ['DATABASE_URL']

def get_db():
    if 'db' not in g:
        g.db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def format_date(date_obj):
    if not date_obj:
        return ''
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.strptime(date_obj, '%Y-%m-%d').date()
        except:
            return date_obj
    return date_obj.strftime('%d/%m/%Y')

@app.context_processor
def utility_processor():
    return dict(format_date=format_date)

def init_db():
    conn = psycopg.connect(DATABASE_URL)
    c = conn.cursor()

    c.execute('''
    CREATE TABLE IF NOT EXISTS clients (
        id SERIAL PRIMARY KEY,
        business_type TEXT NOT NULL,
        business_name TEXT NOT NULL,
        contact_first TEXT,
        contact_last TEXT,
        phone TEXT,
        email TEXT,
        bacs_details TEXT,
        default_interest_rate REAL DEFAULT 0.0
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS cases (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        debtor_business_type TEXT,
        debtor_business_name TEXT,
        debtor_first TEXT,
        debtor_last TEXT,
        phone TEXT,
        email TEXT,
        postcode TEXT,
        status TEXT DEFAULT 'Open',
        substatus TEXT,
        next_action_date TEXT,
        open_date DATE DEFAULT CURRENT_DATE
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash BYTEA NOT NULL,
        role TEXT DEFAULT 'user'
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS money (
        id SERIAL PRIMARY KEY,
        case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        transaction_date DATE DEFAULT CURRENT_DATE,
        created_by INTEGER NOT NULL REFERENCES users(id),
        note TEXT,
        recoverable INTEGER DEFAULT 0,
        billable INTEGER DEFAULT 0
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS notes (
        id SERIAL PRIMARY KEY,
        case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        type TEXT NOT NULL,
        created_by INTEGER NOT NULL REFERENCES users(id),
        note TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS api_keys (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id),
        key TEXT UNIQUE NOT NULL,
        name TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS case_status_history (
        id SERIAL PRIMARY KEY,
        case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        old_status TEXT,
        old_substatus TEXT,
        new_status TEXT,
        new_substatus TEXT,
        changed_by INTEGER NOT NULL REFERENCES users(id),
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    for col in ['postcode', 'email', 'phone', 'status', 'substatus']:
        try:
            c.execute(f"ALTER TABLE cases ADD COLUMN IF NOT EXISTS {col} TEXT")
        except:
            pass

    c.execute("SELECT COUNT(*) FROM users WHERE username = 'helmadmin'")
    if c.fetchone()[0] == 0:
        hashed = bcrypt.hashpw(b'helmadmin', bcrypt.gensalt())
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                  ('helmadmin', hashed, 'admin'))

    conn.commit()
    conn.close()

init_db()

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
    c.execute("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
    row = c.fetchone()
    return User(row['id'], row['username'], row['role']) if row else None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        c = db.cursor()
        c.execute("SELECT id, username, password_hash, role FROM users WHERE username = %s", (username,))
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
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
        INSERT INTO cases (client_id, debtor_business_type, debtor_business_name, debtor_first, debtor_last, phone, email, postcode, next_action_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    ''', (
        request.form['client_id'],
        request.form['debtor_business_type'],
        request.form['debtor_business_name'],
        request.form['debtor_first'],
        request.form['debtor_last'],
        request.form['phone'],
        request.form['email'],
        request.form.get('postcode', ''),
        request.form['next_action_date']
    ))
    new_case_id = c.fetchone()['id']
    db.commit()
    flash('Case added')
    return redirect(url_for('dashboard', case_id=new_case_id))

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    db = get_db()
    c = db.cursor()
    trans_date = request.form.get('transaction_date') or date.today().isoformat()
    recoverable = 1 if request.form.get('recoverable') else 0
    billable = 1 if request.form.get('billable') else 0

    c.execute('''
        INSERT INTO money (case_id, type, amount, created_by, note, transaction_date, recoverable, billable)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
        VALUES (%s, %s, %s, %s)
    ''', (
        request.form['case_id'],
        request.form['type'],
        request.form['note'],
        current_user.id
    ))
    db.commit()
    return redirect(url_for('dashboard', case_id=request.form['case_id']))

@app.route('/update_case_status', methods=['POST'])
@login_required
def update_case_status():
    case_id = request.form['case_id']
    new_status = request.form['status']
    new_substatus = request.form.get('substatus') or None

    db = get_db()
    c = db.cursor()
    c.execute("SELECT status, substatus FROM cases WHERE id = %s", (case_id,))
    old = c.fetchone()

    c.execute("UPDATE cases SET status = %s, substatus = %s WHERE id = %s",
              (new_status, new_substatus, case_id))

    c.execute('''
        INSERT INTO case_status_history 
        (case_id, old_status, old_substatus, new_status, new_substatus, changed_by)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (case_id, old['status'], old['substatus'], new_status, new_substatus, current_user.id))

    db.commit()
    return redirect(url_for('dashboard', case_id=case_id))

@app.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip().lower()
    if not q:
        return jsonify([])

    db = get_db()
    c = db.cursor()
    like = f"%{q}%"

    sql = """
        SELECT DISTINCT
            c.id as client_id, c.business_name as client_name,
            s.id as case_id,
            COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor_name,
            s.postcode, s.email, s.phone
        FROM cases s
        JOIN clients c ON s.client_id = c.id
        WHERE LOWER(c.business_name) LIKE %s
           OR LOWER(COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last)) LIKE %s
           OR LOWER(s.email || '') LIKE %s
           OR LOWER(s.phone || '') LIKE %s
           OR LOWER(s.postcode || '') LIKE %s
        ORDER BY c.business_name, s.id
        LIMIT 50
    """
    c.execute(sql, (like, like, like, like, like))
    results = [dict(row) for row in c.fetchall()]
    return jsonify(results)

@app.route('/client_search')
@login_required
def client_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    db = get_db()
    c = db.cursor()
    like = f"%{q.lower()}%"
    c.execute("SELECT id, business_name as name FROM clients WHERE LOWER(business_name) LIKE %s ORDER BY business_name LIMIT 20", (like,))
    results = [{'id': r['id'], 'name': r['name']} for r in c.fetchall()]
    return jsonify(results)

@app.route('/client/<int:client_id>')
@login_required
def client_dashboard(client_id):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
    client = c.fetchone()
    if not client:
        flash("Client not found")
        return redirect(url_for('dashboard'))

    c.execute("""
        SELECT s.*, 
               COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor_name
        FROM cases s 
        WHERE s.client_id = %s 
        ORDER BY s.open_date DESC
    """, (client_id,))
    cases = c.fetchall()

    for case in cases:
        c.execute("SELECT type, amount, recoverable FROM money WHERE case_id = %s", (case['id'],))
        balance = 0.0
        for t in c.fetchall():
            if t['type'] == 'Payment':
                balance -= t['amount']
            elif t['type'] in ['Invoice', 'Interest']:
                balance += t['amount']
            elif t['type'] == 'Charge' and t['recoverable']:
                balance += t['amount']
        case['balance'] = round(balance, 2)

    return render_template('client_dashboard.html', client=client, cases=cases)

@app.route('/report')
@login_required
def report():
    client_code = request.args.get('client_code')
    report_html = ''
    if client_code:
        db = get_db()
        c = db.cursor()
        c.execute("SELECT id, business_name FROM clients WHERE id = %s", (client_code,))
        client = c.fetchone()
        if client:
            c.execute("""
                SELECT s.id as case_id, s.debtor_business_name, s.debtor_first, s.debtor_last,
                       m.type, m.amount
                FROM cases s
                LEFT JOIN money m ON s.id = m.case_id
                WHERE s.client_id = %s
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
    c.execute("SELECT id, business_name FROM clients WHERE id = %s", (client_code,))
    client = c.fetchone()
    if not client:
        return "Client not found", 404

    c.execute("""
        SELECT s.id as case_id, s.debtor_business_name, s.debtor_first, s.debtor_last,
               m.type, m.amount
        FROM cases s
        LEFT JOIN money m ON s.id = m.case_id
        WHERE s.client_id = %s
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
    c.execute("SELECT id, business_name FROM clients WHERE id = %s", (client_code,))
    client = c.fetchone()
    if not client:
        return "Client not found", 404

    c.execute("""
        SELECT s.id as case_id, s.debtor_business_name, s.debtor_first, s.debtor_last,
               m.type, m.amount
        FROM cases s
        LEFT JOIN money m ON s.id = m.case_id
        WHERE s.client_id = %s
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

    html = f"<h1>Client Report: {client['business_name']} (ID: {client['id']})</h1><table border='1' style='width:100%; border-collapse:collapse; font-family:Arial; font-size:12px;'><tr style='background:#ddd;'><th>Case ID</th><th>Debtor</th><th>Invoice</th><th>Payment</th><th>Charge</th><th>Interest</th><th>Balance</th></tr>"
    for case_id, d in cases.items():
        balance = d['Invoice'] + d['Charge'] + d['Interest'] - d['Payment']
        html += f"<tr><td>{case_id}</td><td>{d['debtor']}</td><td>£{d['Invoice']:.2f}</td><td>£{d['Payment']:.2f}</td><td>£{d['Charge']:.2f}</td><td>£{d['Interest']:.2f}</td><td>£{balance:.2f}</td></tr>"
    grand = {t: sum(c[t] for c in cases.values()) for t in ['Invoice','Payment','Charge','Interest']}
    grand_balance = grand['Invoice'] + grand['Charge'] + grand['Interest'] - grand['Payment']
    html += f"<tr style='font-weight:bold; background:#eee;'><td colspan='2'>TOTALS</td><td>£{grand['Invoice']:.2f}</td><td>£{grand['Payment']:.2f}</td><td>£{grand['Charge']:.2f}</td><td>£{grand['Interest']:.2f}</td><td>£{grand_balance:.2f}</td></tr></table>"

    pdf = HTML(string=html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=report_client_{client_code}.pdf'
    return response

@app.route('/api/generate_key', methods=['POST'])
@login_required
def generate_key():
    db = get_db()
    c = db.cursor()
    key = str(uuid.uuid4())
    name = request.json.get('name', 'API Key')
    c.execute("INSERT INTO api_keys (client_id, key, name) VALUES (1, %s, %s)", (key, name))
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
    c.execute("UPDATE api_keys SET active = 0 WHERE id = %s", (key_id,))
    db.commit()
    return '', 204

@app.route('/edit_note', methods=['POST'])
@login_required
def edit_note():
    db = get_db()
    c = db.cursor()
    c.execute("UPDATE notes SET type = %s, note = %s WHERE id = %s", 
              (request.form['type'], request.form['note'], request.form['note_id']))
    db.commit()
    return redirect(url_for('dashboard', case_id=request.form.get('case_id') or ''))

@app.route('/delete_note/<int:note_id>', methods=['POST'])
@login_required
def delete_note(note_id):
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM notes WHERE id = %s", (note_id,))
    db.commit()
    return '', 204

@app.route('/get_transaction/<int:trans_id>')
@login_required
def get_transaction(trans_id):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM money WHERE id = %s", (trans_id,))
    t = c.fetchone()
    return jsonify(dict(t)) if t else ('', 404)

@app.route('/edit_transaction', methods=['POST'])
@login_required
def edit_transaction():
    db = get_db()
    c = db.cursor()
    recoverable = 1 if request.form.get('recoverable') else 0
    billable = 1 if request.form.get('billable') else 0
    c.execute('''
        UPDATE money SET amount = %s, note = %s, recoverable = %s, billable = %s
        WHERE id = %s
    ''', (request.form['amount'], request.form.get('note', ''), recoverable, billable, request.form['trans_id']))
    db.commit()
    return redirect(url_for('dashboard', case_id=request.form.get('case_id') or ''))

@app.route('/delete_transaction/<int:trans_id>', methods=['POST'])
@login_required
def delete_transaction(trans_id):
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM money WHERE id = %s", (trans_id,))
    db.commit()
    return '', 204

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
               COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor,
               s.open_date
        FROM cases s
        JOIN clients c ON s.client_id = c.id
        ORDER BY s.open_date DESC, s.id DESC
        LIMIT 10
    """)
    recent_cases = c.fetchall()

    selected_case = None
    case_client = None
    client_cases = []
    notes = []
    transactions = []
    status_history = []
    balance = 0.0
    totals = {'Invoice': 0, 'Payment': 0, 'Charge': 0, 'Interest': 0}
    page = int(request.args.get('page', 1))
    per_page = 15

    case_id = request.args.get('case_id')
    if case_id:
        try:
            case_id = int(case_id)
        except:
            case_id = None

        c.execute("SELECT * FROM cases WHERE id = %s", (case_id,))
        selected_case = c.fetchone()
        if selected_case:
            c.execute("SELECT * FROM clients WHERE id = %s", (selected_case['client_id'],))
            case_client = c.fetchone()

            c.execute("SELECT id, debtor_business_name, debtor_first, debtor_last FROM cases WHERE client_id = %s ORDER BY id", (selected_case['client_id'],))
            client_cases = c.fetchall()

            offset = (page - 1) * per_page
            c.execute('''
                SELECT n.*, u.username FROM notes n JOIN users u ON n.created_by = u.id 
                WHERE n.case_id = %s ORDER BY n.created_at DESC LIMIT %s OFFSET %s
            ''', (case_id, per_page, offset))
            notes = c.fetchall()

            c.execute('''
                SELECT m.*, u.username FROM money m JOIN users u ON m.created_by = u.id 
                WHERE m.case_id = %s ORDER BY m.transaction_date DESC, m.id DESC LIMIT %s OFFSET %s
            ''', (case_id, per_page, offset))
            transactions = c.fetchall()

            c.execute('''
                SELECT h.*, u.username FROM case_status_history h 
                JOIN users u ON h.changed_by = u.id 
                WHERE h.case_id = %s ORDER BY h.changed_at DESC
            ''', (case_id,))
            status_history = c.fetchall()

            for t in transactions:
                amt = float(t['amount'])
                typ = t['type']
                if typ == 'Payment':
                    balance -= amt
                elif typ in ['Invoice', 'Interest']:
                    balance += amt
                elif typ == 'Charge' and t['recoverable']:
                    balance += amt
                totals[typ] += amt

    today_str = date.today().isoformat()

    return render_template('dashboard.html',
                           clients=clients,
                           recent_cases=recent_cases,
                           selected_case=selected_case,
                           case_client=case_client,
                           client_cases=client_cases,
                           notes=notes,
                           transactions=transactions,
                           status_history=status_history,
                           balance=round(balance, 2),
                           totals={k: round(v, 2) for k, v in totals.items()},
                           today_str=today_str,
                           page=page)

if __name__ == '__main__':
    app.run(debug=True)


