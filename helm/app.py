from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from datetime import date, datetime
import bcrypt
import os

app = Flask(__name__)
app.secret_key = 'supersecretkey'
DB = 'crm.db'

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return User(row[0], row[1], row[2]) if row else None

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(DB):
        conn = get_db()
        c = conn.cursor()

        # Clients
        c.execute('''
        CREATE TABLE clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        # Cases
        c.execute('''
        CREATE TABLE cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        # Users
        c.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TEXT DEFAULT (datetime('now'))
        )
        ''')

        # Money
        c.execute('''
        CREATE TABLE money (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        # Notes
        c.execute('''
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
        ''')

        # Insert admin
        hashed = bcrypt.hashpw('admin'.encode('utf-8'), bcrypt.gensalt())
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                  ('admin', hashed, 'admin'))

        conn.commit()
        conn.close()

# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            login_user(User(user['id'], user['username'], user['role']))
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, business_name FROM clients ORDER BY business_name")
    clients = c.fetchall()
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

            # Notes
            c.execute('''
                SELECT n.*, u.username FROM notes n
                JOIN users u ON n.created_by = u.id
                WHERE n.case_id = ? ORDER BY n.created_at DESC
            ''', (case_id,))
            notes = c.fetchall()

            # Transactions
            c.execute('''
                SELECT m.*, u.username FROM money m
                JOIN users u ON m.created_by = u.id
                WHERE m.case_id = ? ORDER BY m.transaction_date DESC, m.id DESC
            ''', (case_id,))
            transactions = c.fetchall()

            # Balance & Totals
            for t in transactions:
                amt = t['amount']
                typ = t['type']
                totals[typ] += amt
                if typ in ['Payment']:
                    balance -= amt
                else:
                    balance += amt

    conn.close()
    return render_template('dashboard.html',
                           clients=clients,
                           selected_case=selected_case,
                           case_client=case_client,
                           notes=notes,
                           transactions=transactions,
                           balance=balance,
                           totals=totals)

# Run
if __name__ == '__main__':
    init_db()
    app.run(debug=True)