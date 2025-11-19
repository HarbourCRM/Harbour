# =============================================================================
#  EXTENSIONS - SHARED STUFF USED BY THE WHOLE APP
#  • Database connection (get_db / close_db)
#  • Jinja filters: money formatting and date formatting
#  • Imported in app.py and used everywhere
#  DO NOT TOUCH unless you know what you're doing
# =============================================================================

import os
from flask import g
import psycopg
from psycopg.rows import dict_row
from datetime import datetime

DATABASE_URL = os.environ['DATABASE_URL']

def get_db():
    if 'db' not in g:
        g.db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# =============================================================================
#  JINJA FILTERS - USED IN TEMPLATES FOR £ AND DATES
# =============================================================================

def money(value):
    if value is None or value == '':
        return "£0.00"
    try:
        return f"£{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)

def format_date(date_obj):
    if not date_obj:
        return ''
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.strptime(date_obj, '%Y-%m-%d').date()
        except:
            return date_obj
    return date_obj.strftime('%d/%m/%Y')
