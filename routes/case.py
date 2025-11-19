# =============================================================================
#  CASE ROUTES - THE BIG ONE - THIS IS THE ENTIRE APP'S CORE
#  • Main dashboard ( / and /dashboard )
#  • Add case, add transaction, add note
#  • Edit / delete transaction & note
#  • Update case status
#  • Search (cases & clients)
#  • The get_transaction endpoint for the edit modal
#  THIS FILE IS DELIBERATELY HUGE BECAUSE IT'S THE MAIN WORKFLOW
#  Future dev: if you want to split this further later, go for it. For now it's all here and clearly labelled.
# =============================================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from extensions import get_db
from datetime import date

case_bp = Blueprint('case', __name__)


# ----------------------------------------------------------------------
#  SEARCH - global search box + client autocomplete
# ----------------------------------------------------------------------
@case_bp.route('/search')
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


@case_bp.route('/client_search')
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


# ----------------------------------------------------------------------
#  ADD CASE / ADD TRANSACTION / ADD NOTE
# ----------------------------------------------------------------------
@case_bp.route('/add_case', methods=['POST'])
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
    return redirect(url_for('case.dashboard', case_id=new_case_id))


@case_bp.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    db = get_db()
    c = db.cursor()
    trans_date = request.form.get('transaction_date') or date.today().isoformat()
    recoverable = 1 if request.form.get('recoverable') else 0
    billable = 1 if request.form.get('billable') else 0

    c.execute('''
        INSERT INTO money (case_id, type, amount, created_by, description, transaction_date, recoverable, billable)
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
    return redirect(url_for('case.dashboard', case_id=request.form['case_id']))


@case_bp.route('/add_note', methods=['POST'])
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
    return redirect(url_for('case.dashboard', case_id=request.form['case_id']))


# ----------------------------------------------------------------------
#  EDIT / DELETE TRANSACTION & NOTE
# ----------------------------------------------------------------------
@case_bp.route('/get_transaction/<int:trans_id>')
@login_required
def get_transaction(trans_id):
    db = get_db()
    c = db.cursor()
    c.execute("""
        SELECT id, type, amount, description, recoverable, billable
        FROM money WHERE id = %s
    """, (trans_id,))
    trans = c.fetchone()
    if not trans:
        return jsonify({}), 404
    data = dict(trans)
    data['note'] = data.get('description') or ''  # backward compat for JS
    return jsonify(data)


@case_bp.route('/edit_transaction', methods=['POST'])
@login_required
def edit_transaction():
    db = get_db()
    c = db.cursor()
    recoverable = 1 if request.form.get('recoverable') else 0
    billable = 1 if request.form.get('billable') else 0

    c.execute('''
        UPDATE money 
        SET amount = %s, description = %s, recoverable = %s, billable = %s
        WHERE id = %s
    ''', (
        request.form['amount'],
        request.form.get('note', ''),
        recoverable,
        billable,
        request.form['trans_id']
    ))
    db.commit()
    return redirect(url_for('case.dashboard', case_id=request.form.get('case_id') or ''))


@case_bp.route('/delete_transaction/<int:trans_id>', methods=['POST'])
@login_required
def delete_transaction(trans_id):
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM money WHERE id = %s", (trans_id,))
    db.commit()
    return '', 204


@case_bp.route('/edit_note', methods=['POST'])
@login_required
def edit_note():
    db = get_db()
    c = db.cursor()
    c.execute("UPDATE notes SET type = %s, note = %s WHERE id = %s", 
              (request.form['type'], request.form['note'], request.form['note_id']))
    db.commit()
    return redirect(url_for('case.dashboard', case_id=request.form.get('case_id') or ''))


@case_bp.route('/delete_note/<int:note_id>', methods=['POST'])
@login_required
def delete_note(note_id):
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM notes WHERE id = %s", (note_id,))
    db.commit()
    return '', 204


# ----------------------------------------------------------------------
# CASE STATUS UPDATE – now includes Next Action Date
# ----------------------------------------------------------------------
@case_bp.route('/update_case_status', methods=['POST'])
@login_required
def update_case_status():
    case_id = request.form['case_id']
    new_status = request.form['status']
    new_substatus = request.form.get('substatus') or None
    new_next_action_date = request.form.get('next_action_date') or None   # <-- NEW

    db = get_db()
    c = db.cursor()

    # Get current values for history
    c.execute("SELECT status, substatus, next_action_date FROM cases WHERE id = %s", (case_id,))
    old = c.fetchone()

    # Update the case (including next_action_date)
    c.execute("""
        UPDATE cases 
        SET status = %s, 
            substatus = %s, 
            next_action_date = %s 
        WHERE id = %s
    """, (new_status, new_substatus, new_next_action_date, case_id))

    # Record the change in history (only if something actually changed)
    if (old['status'] != new_status or 
        old['substatus'] != new_substatus or 
        old['next_action_date'] != new_next_action_date):
        
        c.execute('''
            INSERT INTO case_status_history 
            (case_id, old_status, old_substatus, new_status, new_substatus, changed_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (case_id, old['status'], old['substatus'], new_status, new_substatus, current_user.id))

    db.commit()
    return redirect(url_for('case.dashboard', case_id=case_id))


# ----------------------------------------------------------------------
#  MAIN DASHBOARD - THE BIG ONE
# ----------------------------------------------------------------------
@case_bp.route('/')
@case_bp.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    c = db.cursor()

    # All clients for the sidebar
    c.execute("SELECT id, business_name FROM clients ORDER BY business_name")
    clients = c.fetchall()

    # Recent cases for the "no case selected" view
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

    # Selected case logic
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
                WHERE m.case_id = %s ORDER BY m.transaction_date ASC, m.id ASC LIMIT %s OFFSET %s
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
