# api.py
from flask import Blueprint, jsonify, request, abort, url_for
from flask_login import login_required, current_user
import jwt
import uuid
from datetime import datetime, timedelta
from app import get_db  # Import from main app

api = Blueprint('api', __name__, url_prefix='/api')

# === API KEY AUTH ===
def require_api_key(f):
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization')
        if not auth or not auth.startswith('Bearer '):
            abort(401, description="Missing API key")
        key = auth.split(' ')[1]
        db = get_db()
        c = db.cursor()
        c.execute("SELECT client_id FROM api_keys WHERE key = ? AND active = 1", (key,))
        row = c.fetchone()
        if not row:
            abort(401, description="Invalid API key")
        request.client_id = row['client_id']
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

# === GENERATE DEBTOR LINK ===
@api.route('/case/<int:case_id>/link', methods=['POST'])
@login_required
def generate_debtor_link(case_id):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id, client_id FROM cases WHERE id = ? AND client_id = ?", (case_id, current_user.id))
    case = c.fetchone()
    if not case:
        abort(404, description="Case not found")

    token = str(uuid.uuid4())
    expires = datetime.utcnow() + timedelta(days=30)
    c.execute("INSERT INTO debtor_tokens (case_id, token, expires_at) VALUES (?, ?, ?)",
              (case_id, token, expires))
    db.commit()

    link = url_for('api.debtor_landing', token=token, _external=True)
    return jsonify({"link": link, "expires": expires.isoformat()})

# === DEBTOR LANDING PAGE ===
@api.route('/landing/<token>', methods=['GET'])
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
        abort(404, description="Link expired or invalid")

    balance = (case['invoice'] or 0) - (case['payment'] or 0)
    return jsonify({
        "debtor": case['debtor_business_name'] or f"{case['debtor

_ first]} {case['debtor_last']}",
        "balance": round(balance, 2),
        "payment_url": url_for('api.payment_page', token=token, _external=True)
    })

# === PAYMENT PAGE ===
@api.route('/pay/<token>', methods=['GET'])
def payment_page(token):
    # In future: render Stripe/PayPal checkout
    return jsonify({"message": "Payment integration coming soon", "token": token})

# === WEBHOOK: PAYMENT RECEIVED ===
@api.route('/webhook/payment', methods=['POST'])
def payment_webhook():
    data = request.json
    # Validate signature later
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
@api.route('/send/sms', methods=['POST'])
@require_api_key
def send_sms():
    data = request.json
    phone = data.get('phone')
    message = data.get('message')
    if not phone or not message:
        abort(400, description="Missing phone or message")
    # Log for now
    db = get_db()
    c = db.cursor()
    c.execute("INSERT INTO outbound_logs (client_id, type, to, message) VALUES (?, 'sms', ?, ?)",
              (request.client_id, phone, message))
    db.commit()
    return jsonify({"status": "queued", "to": phone})

# === SEND EMAIL ===
@api.route('/send/email', methods=['POST'])
@require_api_key
def send_email():
    data = request.json
    email = data.get('email')
    subject = data.get('subject')
    body = data.get('body')
    if not all([email, subject, body]):
        abort(400, description="Missing fields")
    db = get_db()
    c = db.cursor()
    c.execute("INSERT INTO outbound_logs (client_id, type, to, message) VALUES (?, 'email', ?, ?)",
              (request.client_id, email, f"{subject}\n\n{body}"))
    db.commit()
    return jsonify({"status": "queued", "to": email})

# === AI VOICE CALL ===
@api.route('/call/start', methods=['POST'])
@require_api_key
def start_call():
    data = request.json
    phone = data.get('phone')
    script = data.get('script')
    if not phone or not script:
        abort(400)
    db = get_db()
    c = db.cursor()
    c.execute("INSERT INTO outbound_logs (client_id, type, to, message) VALUES (?, 'call', ?, ?)",
              (request.client_id, phone, script))
    db.commit()
    return jsonify({"status": "queued", "call_id": str(uuid.uuid4())})
