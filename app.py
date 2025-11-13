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
def load_user(user Fid):
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

    # TABLES
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

    # ADMIN
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        hashed = bcrypt.hashpw(b'admin', bcrypt.gensalt())
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ('admin', hashed, 'admin'))

    # DUMMY DATA
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
                    (client_id, debtor_business_type, debtor_business_name, debtor_first, debtor_last, phone, email, postcode, status, substatus, next_action_date, interest_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    client_id, debtor_type, business, first, last,
                    f"07{random.randint(100,999)} {random.randint(100000,999999)}",
                    f"{first.lower()}.{last.lower()}@example.com",
                    f"SW1A {random.randint(1,9)}AA",
                    random.choice(statuses),
                    random.choice(["Awaiting Docs", "In Court", "Payment Plan", None]),
                    next_action,
                    float(clients[client_ids.index(client_id)][6])
                ))
                case_id = c.lastrowid

                for _ in range(random.randint(3,7)):
                    typ = random.choice(["Invoice", "Payment", "Charge", "Interest"])
                    amount = round(random.uniform(50, 1500), 2)
                    days_ago = random.randint(1, 180)
                    tx_date = (datetime.now() - timedelta(days=days_ago)).strftime('%Y-%m-%d')
                    c.execute('''
                        INSERT INTO money (case_id, type, amount, created_by, transaction_date, note)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (case_id, typ, amount, 1, tx_date, f"{typ} entry" if random.random() > 0.5 else None))

                for _ in range(random.randint(2,5)):
                    note_type = random.choice(["General", "Inbound Call", "Outbound Call", "Dispute"])
                    note_text = random.choice([
                        "Customer called to discuss balance",
                        "Sent reminder letter",
                        "Payment plan agreed",
                        "Dispute raised – awaiting proof",
                        "Left voicemail"
                    ])
                    note_date = (datetime.now() - timedelta(days=random.randint(1, 120))).strftime('%Y-%m-%d %H:%M:%S')
                    c.execute('''
                        INSERT INTO notes (case_id, type, created_by, note, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (case_id, note_type, 1, note_text, note_date))

    db.commit()
    db.close()

# RUN ONCE AT STARTUP
init_db()

# === LOGIN / LOGOUT ===
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

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# === FORMS ===
@app.route('/add_client', methods=['POST'])
@login_required
def add_client():
    data = request.form
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO clients 
        (business_type, business_name, contact_first, contact_last, phone, email, street, street2, city, postcode, country, bacs_details, custom1, custom2, custom3, default_interest_rate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data['business_type'], data['business_name'], data.get('contact_first'), data.get('contact_last'),
        data.get('phone'), data.get('email'), data.get('street'), data.get('street2'),
        data.get('city'), data.get('postcode'), data.get('country'), data.get('bacs_details'),
        data.get('custom1'), data.get('custom2'), data.get('custom3'), float(data.get('default_interest_rate', 0))
    ))
    db.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_case', methods=['POST'])
@login_required
def add_case():
    data = request.form
    db = get_db()
    c = db.cursor()
    client_id = int(data['client_id'])
    c.execute("SELECT default_interest_rate FROM clients WHERE id = ?", (client_id,))
    client = c.fetchone()
    interest_rate = client['default_interest_rate'] if client else 0.0
    next_action = data.get('next_action_date')
    c.execute('''
        INSERT INTO cases 
        (client_id, debtor_business_type, debtor_business_name, debtor_first, debtor_last, phone, email, street, street2, city, postcode, country, status, substatus, next_action_date, custom1, custom2, custom3, interest_rate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        client_id, data['debtor_business_type'], data.get('debtor_business_name'),
        data.get('debtor_first'), data.get('debtor_last'), data.get('phone'), data.get('email'),
        data.get('street'), data.get('street2'), data.get('city'), data.get('postcode'), data.get('country'),
        data.get('status', 'Open'), data.get('substatus'), next_action, data.get('custom1'), data.get('custom2'), data.get('custom3'), interest_rate
    ))
    db.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    data = request.form
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO money (case_id, type, amount, created_by, note)
        VALUES (?, ?, ?, ?, ?)
    ''', (data['case_id'], data['type'], float(data['amount']), current_user.id, data.get('note')))
    db.commit()
    return redirect(url_for('dashboard', case_id=data['case_id']))

@app.route('/add_note', methods=['POST'])
@login_required
def add_note():
    data = request.form
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO notes (case_id, type, created_by, note)
        VALUES (?, ?, ?, ?)
    ''', (data['case_id'], data['type'], current_user.id, data['note']))
    db.commit()
    return redirect(url_for('dashboard', case_id=data['case_id']))

# === SEARCH ===
@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '').strip()
    field = request.args.get('field', 'debtor_first').strip()
    mode = request.args.get('mode', 'contains')

    if not query:
        return jsonify([])

    db = get_db()
    c = db.cursor()

    field_map = {
        'debtor_name': "(s.debtor_first || ' ' || s.debtor_last)",
        'postcode': "s.postcode",
        'email': "s.email",
        'phone': "s.phone",
        'client_name': "c.business_name",
        'client_code': "c.id"
    }
    col = field_map.get(field, "s.debtor_first")

    operator = '=' if mode == 'is' else 'LIKE'
    param = query if mode == 'is' else f'%{query}%'

    sql = f"""
        SELECT s.id as case_id, c.business_name, c.id as client_code,
               s.debtor_first, s.debtor_last, s.debtor_business_name,
               s.postcode, s.email, s.phone
        FROM cases s
        JOIN clients c ON s.client_id = c.id
        WHERE {col} {operator} ?
        ORDER BY c.business_name, s.id
        LIMIT 50
    """
    c.execute(sql, (param,))
    results = c.fetchall()
    db.close()

    return jsonify([{
        'case_id': r['case_id'],
        'client': r['business_name'],
        'client_code': r['client_code'],
        'debtor': r['debtor_business_name'] or f"{r['debtor_first']} {r['debtor_last']}",
        'postcode': r['postcode'] or '',
        'email': r['email'] or '',
        'phone': r['phone'] or ''
    } for r in results])

# === CLIENT SEARCH (NO DUPES) ===
@app.route('/client_search')
@login_required
def client_search():
    query = request.args.get('q', '').strip()
    field = request.args.get('field', 'business_name').strip()
    mode = request.args.get('mode', 'contains')

    if not query:
        return jsonify([])

    db = get_db()
    c = db.cursor()

    field_map = {
        'client_name': "business_name",
        'client_code': "id"
    }
    col = field_map.get(field, "business_name")

    operator = '=' if mode == 'is' else 'LIKE'
    param = query if mode == 'is' else f'%{query}%'

    sql = f"""
        SELECT DISTINCT id, business_name
        FROM clients
        WHERE {col} {operator} ?
        ORDER BY business_name
        LIMIT 10
    """
    c.execute(sql, (param,))
    results = c.fetchall()
    db.close()

    return jsonify([{
        'id': r['id'],
        'name': r['business_name']
    } for r in results])

# === API ENDPOINTS ===
@app.route('/api/generate_key', methods=['POST'])
@login_required
def generate_api_key():
    db = get_db()
    c = db.cursor()
    key = str(uuid.uuid4())
    c.execute("INSERT INTO api_keys (client_id, key, name) VALUES (?, ?, ?)",
              (current_user.id, key, "New Key"))
    db.commit()
    return jsonify({"key": key})

@app.route('/api/keys')
@login_required
def list_api_keys():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id, name FROM api_keys WHERE client_id = ? AND active = 1", (current_user.id,))
    return jsonify([{"id": r['id'], "name": r['name']} for r in c.fetchall()])

@app.route('/api/revoke_key/<int:key_id>', methods=['POST'])
@login_required
def revoke_key(key_id):
    db = get_db()
    c = db.cursor()
    c.execute("UPDATE api_keys SET active = 0 WHERE id = ? AND client_id = ?", (key_id, current_user.id))
    db.commit()
    return jsonify({"status": "revoked"})

# === DEBTOR LANDING ===
@app.route('/api/landing/<token>', methods=['GET'])
def debtor_landing(token):
    db = get_db()
    c = db.cursor()
    c.execute("""
        SELECT c.id, c.debtor_first, c.debtor_last, c.debtor_business_name,
               SUM(CASE WHEN m.type = 'Invoice' THEN m.amount ELSE 0 END) as invoice,
               SUM(CASE WHEN m.type = 'Payment' THEN m.amount ELSE 0 END) as payment
        FROM debtor_tokens t
        JOIN cases c ON t.case_id = c.id
        LEFT JOIN money m ON c.id = m.case_id
        WHERE t.token = ? AND t.expires_at > datetime('now')
        GROUP BY c.id
    """, (token,))
    case = c.fetchone()
    if not case:
        return jsonify({"error": "Invalid or expired link"}), 404

    balance = (case['invoice'] or 0) - (case['payment'] or 0)
    return jsonify({
        "debtor": case['debtor_business_name'] or f"{case['debtor_first']} {case['debtor_last']}",
        "balance": round(balance, 2),
        "payment_url": url_for('api.payment_page', token=token, _external=True)
    })

# === PAYMENT PAGE ===
@app.route('/api/pay/<token>', methods=['GET'])
def payment_page(token):
    return jsonify({"message": "Payment integration coming soon", "token": token})

# === WEBHOOK: PAYMENT ===
@app.route('/api/webhook/payment', methods=['POST'])
def payment_webhook():
    data = request.json
    case_id = data.get('case_id')
    amount = data.get('amount')
    if case_id and amount:
        db = get_db()
        c = db.cursor()
        c.execute("INSERT INTO money (case_id, type, amount, created_by, note) VALUES (?, 'Payment', ?, 0, 'API Payment')",
                  (case_id, amount))
        db.commit()
    return jsonify({"status": "received"})

# === SEND SMS ===
@app.route('/api/send/sms', methods=['POST'])
def send_sms():
    auth = request.headers.get('Authorization')
    if not auth or not auth.startswith('Bearer '):
        return jsonify({"error": "Missing API key"}), 401
    key = auth.split(' ')[1]
    db = get_db()
    c = db.cursor()
    c.execute("SELECT client_id FROM api_keys WHERE key = ? AND active = 1", (key,))
    row = c.fetchone()
    if not row:
        return jsonify({"error": "Invalid API key"}), 401
    client_id = row['client_id']

    data = request.json
    phone = data.get('phone')
    message = data.get('message')
    if not phone or not message:
        return jsonify({"error": "Missing phone or message"}), 400

    c.execute("INSERT INTO outbound_logs (client_id, type, recipient, message) VALUES (?, 'sms', ?, ?)",
              (client_id, phone, message))
    db.commit()
    return jsonify({"status": "queued", "to": phone})

# === SEND EMAIL ===
@app.route('/api/send/email', methods=['POST'])
def send_email():
    auth = request.headers.get('Authorization')
    if not auth or not auth.startswith('Bearer '):
        return jsonify({"error": "Missing API key"}), 401
    key = auth.split(' ')[1]
    db = get_db()
    c = db.cursor()
    c.execute("SELECT client_id FROM api_keys WHERE key = ? AND active = 1", (key,))
    row = c.fetchone()
    if not row:
        return jsonify({"error": "Invalid API key"}), 401
    client_id = row['client_id']

    data = request.json
    email = data.get('email')
    subject = data.get('subject')
    body = data.get('body')
    if not all([email, subject, body]):
        return jsonify({"error": "Missing fields"}), 400

    c.execute("INSERT INTO outbound_logs (client_id, type, recipient, message) VALUES (?, 'email', ?, ?)",
              (client_id, email, f"{subject}\n\n{body}"))
    db.commit()
    return jsonify({"status": "queued", "to": email})

# === AI VOICE CALL ===
@app.route('/api/call/start', methods=['POST'])
def start_call():
    auth = request.headers.get('Authorization')
    if not auth or not auth.startswith('Bearer '):
        return jsonify({"error": "Missing API key"}), 401
    key = auth.split(' ')[1]
    db = get_db()
    c = db.cursor()
    c.execute("SELECT client_id FROM api_keys WHERE key = ? AND active = 1", (key,))
    row = c.fetchone()
    if not row:
        return jsonify({"error": "Invalid API key"}), 401
    client_id = row['client_id']

    data = request.json
    phone = data.get('phone')
    script = data.get('script')
    if not phone or not script:
        return jsonify({"error": "Missing phone or script"}), 400

    c.execute("INSERT INTO outbound_logs (client_id, type, recipient, message) VALUES (?, 'call', ?, ?)",
              (client_id, phone, script))
    db.commit()
    return jsonify({"status": "queued", "call_id": str(uuid.uuid4())})

# === REPORTS ===
@app.route('/report')
@login_required
def report():
    client_code = request.args.get('client_code', '').strip()
    db = get_db()
    c = db.cursor()

    if not client_code:
        return render_template('report.html', report_html='', client_code='')

    c.execute("SELECT id, business_name FROM clients WHERE id = ?", (client_code,))
    client = c.fetchone()
    if not client:
        return render_template('report.html', report_html='<p>Client not found.</p>', client_code=client_code)

    c.execute("""
        SELECT s.id as case_id, s.debtor_business_name, s.debtor_first, s.debtor_last,
               m.type, m.amount
        FROM cases s
        LEFT JOIN money m ON s.id = m.case_id
        WHERE s.client_id = ?
        ORDER BY s.id, m.transaction_date
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
    <h2>Client Report: {client['business_name']} (ID: {client['id']})</h2>
    <table border="1" style="width:100%; border-collapse:collapse; font-family:Arial; font-size:14px;">
        <tr style="background:#f5f5f5;">
            <th>Case ID</th><th>Debtor</th><th>Invoice</th><th>Payment</th><th>Charge</th><th>Interest</th><th>Balance</th>
        </tr>
    """
    grand = {'Invoice': 0, 'Payment': 0, 'Charge': 0, 'Interest': 0}
    for case_id, data in cases.items():
        balance = data['Invoice'] + data['Charge'] + data['Interest'] - data['Payment']
        html += f"""
        <tr>
            <td>{case_id}</td>
            <td>{data['debtor']}</td>
            <td>£{data['Invoice']:.2f}</td>
            <td>£{data['Payment']:.2f}</td>
            <td>£{data['Charge']:.2f}</td>
            <td>£{data['Interest']:.2f}</td>
            <td>£{balance:.2f}</td>
        </tr>
        """
        for t in ['Invoice', 'Payment', 'Charge', 'Interest']:
            grand[t] += data[t]

    grand_balance = grand['Invoice'] + grand['Charge'] + grand['Interest'] - grand['Payment']
    html += f"""
        <tr style="font-weight:bold; background:#eef;">
            <td colspan="2">TOTALS</td>
            <td>£{grand['Invoice']:.2f}</td>
            <td>£{grand['Payment']:.2f}</td>
            <td>£{grand['Charge']:.2f}</td>
            <td>£{grand['Interest']:.2f}</td>
            <td>£{grand_balance:.2f}</td>
        </tr>
    </table>
    """
    return render_template('report.html', report_html=html, client_code=client_code)

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
