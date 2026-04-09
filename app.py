import os
import uuid
from functools import wraps
from flask import (
    Flask, request, jsonify, render_template,
    redirect, url_for, session, flash
)
from werkzeug.utils import secure_filename
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')

DATA_DIR    = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '.')
DB_PATH     = os.path.join(DATA_DIR, 'testimonials.db')
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'pfs2026')

app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024  # 6 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

CATEGORIES = {
    'sady':       'Sady i trybunaly',
    'szpitale':   'Szpitale i placowki medyczne',
    'urzedy':     'Urzedy i instytucje publiczne',
    'kancelarie': 'Kancelarie prawne',
    'inne':       'Pozostale',
}

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
# Public form
# ---------------------------------------------------------------------------

@app.route('/')
def form():
    return render_template('form.html')


@app.route('/submit', methods=['POST'])
def submit():
    name      = request.form.get('name', '').strip()
    company   = request.form.get('company', '').strip()
    job_title = request.form.get('job_title', '').strip()
    text      = request.form.get('text', '').strip()
    rating    = request.form.get('rating', '5')

    if not name or not text:
        flash('Imie i opinia sa wymagane.', 'error')
        return redirect(url_for('form'))

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
            url_for('static', filename=f"uploads/{t['logo_filename']}", _external=True)
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
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_panel'))
        flash('Bledne haslo.', 'error')
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
