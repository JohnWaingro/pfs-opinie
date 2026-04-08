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

DB_PATH = os.environ.get('DB_PATH', 'testimonials.db')
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'pfs2026')

app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # 12 MB (2x pliki po 5 MB + overhead)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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
                photo_filename  TEXT,
                logo_filename   TEXT,
                status          TEXT DEFAULT 'pending',
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # migracja dla starszych baz
        try:
            conn.execute('ALTER TABLE testimonials ADD COLUMN logo_filename TEXT')
        except Exception:
            pass


# Inicjalizacja bazy przy starcie (dziala rowniez z gunicorn)
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
    name = request.form.get('name', '').strip()
    company = request.form.get('company', '').strip()
    job_title = request.form.get('job_title', '').strip()
    text = request.form.get('text', '').strip()
    rating = request.form.get('rating', '5')

    if not name or not text:
        flash('Imie i opinia sa wymagane.', 'error')
        return redirect(url_for('form'))

    try:
        rating = int(rating)
        rating = max(1, min(5, rating))
    except ValueError:
        rating = 5

    def save_upload(field_name):
        f = request.files.get(field_name)
        if f and f.filename and allowed_file(f.filename):
            ext = secure_filename(f.filename).rsplit('.', 1)[1].lower()
            fname = f"{uuid.uuid4().hex}.{ext}"
            f.save(os.path.join(UPLOAD_FOLDER, fname))
            return fname
        return None

    photo_filename = save_upload('photo')
    logo_filename = save_upload('logo')

    with get_db() as conn:
        conn.execute(
            '''INSERT INTO testimonials (name, company, job_title, text, rating, photo_filename, logo_filename)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (name, company, job_title, text, rating, photo_filename, logo_filename)
        )

    return render_template('success.html', name=name)


# ---------------------------------------------------------------------------
# Public API (for widget)
# ---------------------------------------------------------------------------

@app.route('/api/testimonials')
def api_testimonials():
    with get_db() as conn:
        rows = conn.execute(
            '''SELECT id, name, company, job_title, text, rating, photo_filename, created_at
               FROM testimonials WHERE status = "approved"
               ORDER BY created_at DESC'''
        ).fetchall()

    result = []
    for row in rows:
        t = dict(row)
        t['photo_url'] = (
            url_for('static', filename=f"uploads/{t['photo_filename']}", _external=True)
            if t.get('photo_filename') else None
        )
        t['logo_url'] = (
            url_for('static', filename=f"uploads/{t['logo_filename']}", _external=True)
            if t.get('logo_filename') else None
        )
        del t['photo_filename']
        del t['logo_filename']
        result.append(t)

    resp = jsonify(result)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


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
            'SELECT * FROM testimonials WHERE status = ? ORDER BY created_at DESC',
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
        counts=counts
    )


@app.route('/admin/action/<int:tid>', methods=['POST'])
@login_required
def admin_action(tid):
    action = request.form.get('action')
    if action in ('approved', 'rejected', 'pending'):
        with get_db() as conn:
            conn.execute('UPDATE testimonials SET status = ? WHERE id = ?', (action, tid))
    return redirect(request.referrer or url_for('admin_panel'))


@app.route('/admin/delete/<int:tid>', methods=['POST'])
@login_required
def admin_delete(tid):
    with get_db() as conn:
        row = conn.execute(
            'SELECT photo_filename FROM testimonials WHERE id = ?', (tid,)
        ).fetchone()
        if row and row['photo_filename']:
            try:
                os.remove(os.path.join(UPLOAD_FOLDER, row['photo_filename']))
            except FileNotFoundError:
                pass
        conn.execute('DELETE FROM testimonials WHERE id = ?', (tid,))
    return redirect(url_for('admin_panel'))


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True, port=5050)
