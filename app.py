from flask import Flask, render_template, request, redirect, url_for, flash, g
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
import bcrypt
import os

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
    db.close()
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

def init_db():
    if not hasattr(app, 'db_initialized'):
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

        c.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
        if c.fetchone()[0] == 0:
            hashed = bcrypt.hashpw(b'admin', bcrypt.gensalt())
            c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ('admin', hashed, 'admin'))

        db.commit()
        db.close()
        app.db_initialized = True

@app.before_request
def before_request():
    init_db()

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

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    c = db.cursor()

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

            c.execute('''
                SELECT n.*, u.username FROM notes n
                JOIN users u ON n.created_by = u.id
                WHERE n.case_id = ? ORDER BY n.created_at DESC
            ''', (case_id,))
            notes = c.fetchall()

            c.execute('''
                SELECT m.*, u.username FROM money m
                JOIN users u ON m.created_by = u.id
                WHERE m.case_id = ? ORDER BY m.transaction_date DESC, m.id DESC
            ''', (case_id,))
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
                           all_cases=all_cases,
                           selected_case=selected_case,
                           case_client=case_client,
                           notes=notes,
                           transactions=transactions,
                           balance=balance,
                           totals=totals)

if __name__ == '__main__':
    app.run(debug=True)
