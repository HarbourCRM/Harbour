# =============================================================================
#  CLIENT ROUTES
#  • View a single client's dashboard (/client/<id>)
#  • Add a new client (POST /add_client)
#  This is everything specific to one client record
# =============================================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from extensions import get_db

# Blueprint for client-related pages
client_bp = Blueprint('client', __name__, url_prefix='/client')


@client_bp.route('/<int:client_id>')
@login_required
def client_dashboard(client_id):
    db = get_db()
    c = db.cursor()
    
    # Get the client
    c.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
    client = c.fetchone()
    if not client:
        flash("Client not found")
        return redirect(url_for('case.dashboard'))

    # Get all their cases
    c.execute("""
        SELECT s.*, 
               COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor_name
        FROM cases s 
        WHERE s.client_id = %s 
        ORDER BY s.open_date DESC
    """, (client_id,))
    cases = c.fetchall()

    # Calculate balance for each case
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


@client_bp.route('/add_client', methods=['POST'])
@login_required
def add_client():
    db = get_db()
    c = db.cursor()
    c.execute('''
        INSERT INTO clients 
        (business_type, business_name, contact_first, contact_last, phone, email, bacs_details, default_interest_rate)
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
    return redirect(url_for('case.dashboard'))
