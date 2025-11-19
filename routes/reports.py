# =============================================================================
#  REPORTS ROUTES
#  • Export client data to Excel
#  • Export client data to PDF
#  These are the "Report" button features
# =============================================================================

from flask import Blueprint, request, send_file, make_response
from flask_login import login_required
from extensions import get_db
import pandas as pd
from io import BytesIO
from weasyprint import HTML

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/export_excel')
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
        SELECT s.id as case_id,
               COALESCE(s.debtor_business_name, s.debtor_first || ' ' || s.debtor_last) as debtor,
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
            cases[case_id] = {'debtor': r['debtor'], 'Invoice': 0, 'Payment': 0, 'Charge': 0, 'Interest': 0}
        if r['type']:
            cases[case_id][r['type']] += r['amount']

    df = pd.DataFrame.from_dict(cases, orient='index')
    df = df.reset_index().rename(columns={'index': 'Case ID', 'debtor': 'Debtor'})
    df['Balance'] = df['Invoice'] + df['Charge'] + df['Interest'] - df['Payment']

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name=f"report_client_{client_code}.xlsx", as_attachment=True)


@reports_bp.route('/export_pdf')
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

    html = f"<h1>Client Report: {client['business_name']} (ID: {client['id']})</h1>"
    html += "<table border='1' style='width:100%; border-collapse:collapse; font-family:Arial; font-size:12px;'><tr style='background:#ddd;'><th>Case ID</th><th>Debtor</th><th>Invoice</th><th>Payment</th><th>Charge</th><th>Interest</th><th>Balance</th></tr>"
    for case_id, d in cases.items():
        balance = d['Invoice'] + d['Charge'] + d['Interest'] - d['Payment']
        html += "<tr><td>" + str(case_id) + "</td><td>" + str(d['debtor']) + "</td>"
        html += "<td>" + format(d['Invoice'], ".2f") + "</td>"
        html += "<td>" + format(d['Payment'], ".2f") + "</td>"
        html += "<td>" + format(d['Charge'], ".2f") + "</td>"
        html += "<td>" + format(d['Interest'], ".2f") + "</td>"
        html += "<td>" + format(balance, ".2f") + "</td></tr>"

    grand = {t: sum(c[t] for c in cases.values()) for t in ['Invoice','Payment','Charge','Interest']}
    grand_balance = grand['Invoice'] + grand['Charge'] + grand['Interest'] - grand['Payment']
    html += "<tr style='font-weight:bold; background:#eee;'><td colspan='2'>TOTALS</td>"
    html += "<td>" + format(grand['Invoice'], ".2f") + "</td>"
    html += "<td>" + format(grand['Payment'], ".2f") + "</td>"
    html += "<td>" + format(grand['Charge'], ".2f") + "</td>"
    html += "<td>" + format(grand['Interest'], ".2f") + "</td>"
    html += "<td>" + format(grand_balance, ".2f") + "</td></tr></table>"

    pdf = HTML(string=html).write_pdf()
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=report_client_{client_code}.pdf'
    return response
