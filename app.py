import hmac
import os
import uuid
import sqlite3
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, session, flash, send_from_directory, abort
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

app = Flask(__name__)

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if os.environ.get('FLASK_ENV') == 'development' or app.testing:
        SECRET_KEY = 'dev-only-not-for-production'
    else:
        raise RuntimeError('SECRET_KEY env var is required in production')
app.secret_key = SECRET_KEY

_IS_DEV = os.environ.get('FLASK_ENV') == 'development'
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=not _IS_DEV,
)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    raise RuntimeError('ADMIN_PASSWORD env var is required')

DATA_DIR = (
    os.environ.get('DATA_DIR')
    or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
    or (os.path.dirname(os.environ['DB_PATH'])
        if os.environ.get('DB_PATH') and os.path.isabs(os.environ['DB_PATH'])
        else '.')
)
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.environ.get('DB_PATH', os.path.join(DATA_DIR, 'testimonials.db'))
UPLOAD_FOLDER = os.path.join(DATA_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_UPLOAD_MB = 5
app.config['MAX_CONTENT_LENGTH'] = (MAX_UPLOAD_MB + 1) * 1024 * 1024

LOCAL_TZ = ZoneInfo('Europe/Warsaw')

MIN_NAME_LEN = 3
MIN_TEXT_LEN = 2
MAX_NAME_LEN = 100
MAX_TEXT_LEN = 800

CATEGORIES = {
    'sady':       'Sądy i trybunały',
    'szpitale':   'Szpitale i placówki medyczne',
    'urzedy':     'Urzędy i instytucje publiczne',
    'kancelarie': 'Kancelarie prawne',
    'inne':       'Pozostałe',
}

# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

csrf = CSRFProtect(app)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri='memory://',
)

# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

@app.after_request
def add_security_headers(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'DENY')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    return resp

# ---------------------------------------------------------------------------
# Jinja filters
# ---------------------------------------------------------------------------

@app.template_filter('localtime')
def localtime_filter(value, fmt='%Y-%m-%d %H:%M'):
    """Konwertuje UTC timestamp z SQLite na lokalny czas (Europe/Warsaw)."""
    if value is None or value == '':
        return ''
    if isinstance(value, str):
        s = value.replace('T', ' ').split('.')[0]
        try:
            dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(s, '%Y-%m-%d %H:%M')
            except ValueError:
                return value
    elif isinstance(value, datetime):
        dt = value
    else:
        return value
    dt = dt.replace(tzinfo=ZoneInfo('UTC'))
    return dt.astimezone(LOCAL_TZ).strftime(fmt)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS testimonials (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                company         TEXT,
                job_title       TEXT,
                text            TEXT NOT NULL,
                rating          INTEGER DEFAULT 5,
                logo_filename   TEXT,
                category        TEXT DEFAULT 'inne',
                status          TEXT DEFAULT 'pending',
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        for col in ['logo_filename', 'category']:
            try:
                conn.execute(f'ALTER TABLE testimonials ADD COLUMN {col} TEXT')
            except Exception:
                pass


init_db()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Uploaded files (persistent disk)
# ---------------------------------------------------------------------------

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    resp = send_from_directory(UPLOAD_FOLDER, filename)
    resp.headers['Content-Disposition'] = 'inline'
    return resp


# ---------------------------------------------------------------------------
# Public form
# ---------------------------------------------------------------------------

@app.route('/')
def form():
    return render_template('form.html')


@app.route('/submit', methods=['POST'])
@limiter.limit('3 per hour; 20 per day')
def submit():
    # Honeypot — jeśli bot wypełnił ukryte pole, udaj sukces i nic nie zapisuj.
    if request.form.get('website', '').strip():
        return redirect(url_for('success'))

    name      = request.form.get('name', '').strip()
    company   = request.form.get('company', '').strip()
    job_title = request.form.get('job_title', '').strip()
    text      = request.form.get('text', '').strip()
    rating    = request.form.get('rating', '5')

    if len(name) < MIN_NAME_LEN:
        flash(f'Imię i nazwisko musi mieć co najmniej {MIN_NAME_LEN} znaki.', 'error')
        return redirect(url_for('form'))
    if len(text) < MIN_TEXT_LEN:
        flash(f'Opinia musi mieć co najmniej {MIN_TEXT_LEN} znaki.', 'error')
        return redirect(url_for('form'))

    name      = name[:MAX_NAME_LEN]
    text      = text[:MAX_TEXT_LEN]
    company   = company[:MAX_NAME_LEN]
    job_title = job_title[:MAX_NAME_LEN]

    try:
        rating = max(1, min(5, int(rating)))
    except ValueError:
        rating = 5

    logo_filename = None
    f = request.files.get('logo')
    if f and f.filename and allowed_file(f.filename):
        ext = secure_filename(f.filename).rsplit('.', 1)[1].lower()
        logo_filename = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(UPLOAD_FOLDER, logo_filename))

    with get_db() as conn:
        conn.execute(
            '''INSERT INTO testimonials (name, company, job_title, text, rating, logo_filename)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (name, company, job_title, text, rating, logo_filename)
        )

    session['last_submitter'] = name
    return redirect(url_for('success'))


@app.route('/success')
def success():
    name = session.pop('last_submitter', None)
    return render_template('success.html', name=name)


# ---------------------------------------------------------------------------
# Public API (widget)
# ---------------------------------------------------------------------------

@app.route('/api/testimonials')
def api_testimonials():
    category = request.args.get('category')
    with get_db() as conn:
        if category:
            rows = conn.execute(
                '''SELECT id, name, company, job_title, text, rating, logo_filename, category, created_at
                   FROM testimonials WHERE status="approved" AND category=?
                   ORDER BY created_at DESC''', (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                '''SELECT id, name, company, job_title, text, rating, logo_filename, category, created_at
                   FROM testimonials WHERE status="approved"
                   ORDER BY created_at DESC'''
            ).fetchall()

    result = []
    for row in rows:
        t = dict(row)
        t['logo_url'] = (
            url_for('uploaded_file', filename=t['logo_filename'], _external=True)
            if t.get('logo_filename') else None
        )
        del t['logo_filename']
        result.append(t)

    resp = jsonify(result)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


# ---------------------------------------------------------------------------
# Prywatne strony referencji
# ---------------------------------------------------------------------------

@app.route('/referencje')
@app.route('/referencje/<category>')
def referencje(category=None):
    with get_db() as conn:
        if category and category in CATEGORIES:
            rows = conn.execute(
                '''SELECT * FROM testimonials WHERE status="approved" AND category=?
                   ORDER BY created_at DESC''', (category,)
            ).fetchall()
            cat_label = CATEGORIES[category]
        else:
            rows = conn.execute(
                'SELECT * FROM testimonials WHERE status="approved" ORDER BY created_at DESC'
            ).fetchall()
            cat_label = 'Wszystkie referencje'
            category = None

    return render_template(
        'referencje.html',
        testimonials=rows,
        categories=CATEGORIES,
        current_category=category,
        cat_label=cat_label,
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit('5 per hour', methods=['POST'])
def admin_login():
    if request.method == 'POST':
        submitted = request.form.get('password', '')
        if hmac.compare_digest(submitted, ADMIN_PASSWORD):
            session['admin'] = True
            return redirect(url_for('admin_panel'))
        flash('Błędne hasło.', 'error')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))


@app.route('/admin')
@login_required
def admin_panel():
    status_filter = request.args.get('status', 'pending')
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM testimonials WHERE status=? ORDER BY created_at DESC',
            (status_filter,)
        ).fetchall()
        counts = {
            r['status']: r['cnt']
            for r in conn.execute(
                'SELECT status, COUNT(*) as cnt FROM testimonials GROUP BY status'
            ).fetchall()
        }
    return render_template(
        'admin.html',
        testimonials=rows,
        status_filter=status_filter,
        counts=counts,
        categories=CATEGORIES,
    )


@app.route('/admin/action/<int:tid>', methods=['POST'])
@login_required
def admin_action(tid):
    action   = request.form.get('action')
    category = request.form.get('category')
    if action in ('approved', 'rejected', 'pending'):
        with get_db() as conn:
            conn.execute('UPDATE testimonials SET status=? WHERE id=?', (action, tid))
    if category and category in CATEGORIES:
        with get_db() as conn:
            conn.execute('UPDATE testimonials SET category=? WHERE id=?', (category, tid))
    return redirect(request.referrer or url_for('admin_panel'))


@app.route('/admin/delete/<int:tid>', methods=['POST'])
@login_required
def admin_delete(tid):
    with get_db() as conn:
        row = conn.execute('SELECT logo_filename FROM testimonials WHERE id=?', (tid,)).fetchone()
        if row and row['logo_filename']:
            try:
                os.remove(os.path.join(UPLOAD_FOLDER, row['logo_filename']))
            except FileNotFoundError:
                pass
        conn.execute('DELETE FROM testimonials WHERE id=?', (tid,))
    return redirect(url_for('admin_panel'))


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True, port=5050)
