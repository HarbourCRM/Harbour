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

    # Admin user
    c.execute("SELECT COUNT(*) FROM users WHERE username = 'helmadmin'")
    if c.fetchone()[0] == 0:
        print("Creating admin: helmadmin")
        hashed = bcrypt.hashpw(b'helmadmin', bcrypt.gensalt())
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                  ('helmadmin', hashed, 'admin'))

    # Fix missing columns for search
    for col in ['postcode', 'email', 'phone']:
        try:
            c.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
        except:
            pass

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

# === ROUTES (search fixed) ===
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
        col = f"s.{field}"

    sql = f"""
        SELECT c.id as client_id, c.business_name as client, s.id as case_id,
               {col} as search_field,
               COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor,
               s.postcode, s.email, s.phone, c.id as client_code
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
        except ValueError:
            return jsonify([])
    else:
        like = f"%{q}%"
        c.execute("SELECT id, business_name as name FROM clients WHERE business_name ILIKE %s ORDER BY business_name LIMIT 20", (like,))

    results = [{'id': r['id'], 'name': r['name']} for r in c.fetchall()]
    return jsonify(results)

# === REST OF YOUR ROUTES (unchanged) ===
# (add_client, add_case, add_transaction, add_note, report, export_excel, export_pdf, API routes, edit/delete, dashboard)

# ... [keep all the rest of your existing routes exactly as they are]

# DASHBOARD (last route)
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    # ... [your existing dashboard code]
    pass

if __name__ == '__main__':
    app.run(debug=True)
