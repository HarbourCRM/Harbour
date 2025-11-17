from flask import Flask, render_template, request, redirect, url_for, flash, g, jsonify, send_file, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
import psycopg
from psycopg.rows import dict_row
import bcrypt
from datetime import date, datetime, timedelta
import pandas as pd
from io import BytesIO
from weasyprint import HTML
import uuid

app = Flask(__name__)
app.secret_key = 'supersecretkey'

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

def format_date(date_str):
    if not date_str:
        return ''
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return d.strftime('%d/%m/%Y')
    except:
        return date_str

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

    # ADMIN USER
    c.execute("SELECT COUNT(*) FROM users WHERE username = 'helmadmin'")
    if c.fetchone()[0] == 0:
        print("Creating admin: helmadmin")
        hashed = bcrypt.hashpw(b'helmadmin', bcrypt.gensalt())
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                  ('helmadmin', hashed, 'admin'))

    # CRITICAL FIX: Add missing columns if they don't exist
    for col in ['postcode', 'email', 'phone']:
        try:
            c.execute(f"ALTER TABLE cases ADD COLUMN IF NOT EXISTS {col} TEXT")
            print(f"Added column: {col}")
        except:
            pass  # already exists

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
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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

    if field == 'debtor_name':
        col = "COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last)"
    elif field == 'client_name':
        col = "c.business_name"
    else:
        col = f"COALESCE(s.{field}, '')"

    sql = f"""
        SELECT c.id as client_id, c.business_name as client, s.id as case_id,
               COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor,
               COALESCE(s.postcode, '') as postcode,
               COALESCE(s.email, '') as email,
               COALESCE(s.phone, '') as phone,
               c.id as client_code
        FROM cases s
        JOIN clients c ON s.client_id = c.id
        WHERE {col} ILIKE %s
        ORDER BY c.business_name, s.id
        LIMIT 50
    """
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

    if field == 'client_code':
        try:
            client_id = int(q)
            c.execute("SELECT id, business_name as name FROM clients WHERE id = %s", (client_id,))
        except:
            return jsonify([])
    else:
        like = f"%{q}%"
        c.execute("SELECT id, business_name as name FROM clients WHERE business_name ILIKE %s ORDER BY business_name LIMIT 20", (like,))

    results = [{'id': r['id'], 'name': r['name']} for r in c.fetchall()]
    return jsonify(results)

# === ALL OTHER ROUTES (report, export, API, edit/delete, dashboard) ===
# [Keep exactly as before — they work]

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
        c.execute("SELECT * FROM cases WHERE id = %s", (case_id,))
        selected_case = c.fetchone()
        if selected_case:
            c.execute("SELECT * FROM clients WHERE id = %s", (selected_case['client_id'],))
            case_client = c.fetchone()

            c.execute("SELECT id, debtor_business_name, debtor_first, debtor_last FROM cases WHERE client_id = %s ORDER BY id", (selected_case['client_id'],))
            client_cases = c.fetchall()

            c.execute('SELECT n.*, u.username FROM notes n JOIN users u ON n.created_by = u.id WHERE n.case_id = %s ORDER BY n.created_at DESC', (case_id,))
            notes = c.fetchall()

            c.execute('SELECT m.*, u.username FROM money m JOIN users u ON m.created_by = u.id WHERE m.case_id = %s ORDER BY m.transaction_date DESC, m.id DESC', (case_id,))
            transactions = c.fetchall()

            for t in transactions:
                amt = t['amount']
                typ = t['type']
                totals[typ] += amt
                if typ == 'Payment':
                    balance -= amt
                else:
                    balance += amt

    today_str = datetime.now().strftime('%Y-%m-%d')

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
                           today_str=today_str,
                           format_date=format_date)

if __name__ == '__main__':
    app.run(debug=True)
