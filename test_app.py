"""
End-to-end testy apki opinii PFS.
Uruchom: python3 test_app.py
"""
import sys
import os
import io
import json
import tempfile

# Ustaw tymczasowa baze danych i katalog danych
tmp_dir = tempfile.mkdtemp(prefix='pfs_opinie_test_')
os.environ['DATA_DIR'] = tmp_dir
os.environ['DB_PATH'] = os.path.join(tmp_dir, 'testimonials.db')
os.environ['ADMIN_PASSWORD'] = 'testpass'
os.environ['SECRET_KEY'] = 'test-secret-key'

from app import app, init_db, limiter

# Wylacz CSRF i rate limiting w testach
app.config['WTF_CSRF_ENABLED'] = False
app.config['TESTING'] = True
limiter.enabled = False

PASS = '\033[92m✓\033[0m'
FAIL = '\033[91m✗\033[0m'
errors = []

def test(name, condition, detail=''):
    if condition:
        print(f'  {PASS} {name}')
    else:
        print(f'  {FAIL} {name}' + (f'  [{detail}]' if detail else ''))
        errors.append(name)

def run():
    init_db()
    client = app.test_client()

    print('\n── Formularze publiczne ──')

    r = client.get('/')
    test('GET / zwraca 200', r.status_code == 200)
    test('Formularz zawiera logo', b'logo_white.png' in r.data or b'logo.png' in r.data)
    test('Formularz zawiera pole name', b'name="name"' in r.data)
    test('Formularz zawiera pole rating', b'name="rating"' in r.data)
    test('Formularz zawiera upload logo', b'name="logo"' in r.data)
    test('Formularz zawiera honeypot', b'name="website"' in r.data)
    test('Formularz ma minlength=3 na name', b'minlength="3"' in r.data)
    test('Polskie znaki w formularzu', 'Imię'.encode('utf-8') in r.data)

    print('\n── Wysylanie opinii ──')

    # Brak wymaganych pol
    r = client.post('/submit', data={'name': '', 'text': ''}, follow_redirects=False)
    test('Pusty formularz przekierowuje', r.status_code == 302)

    # Za krotkie imie
    r = client.post('/submit', data={'name': 'Ab', 'text': 'OK'}, follow_redirects=False)
    test('Imie < 3 znakow odrzucone (redirect)', r.status_code == 302)

    # Za krotka opinia
    r = client.post('/submit', data={'name': 'Jan Kowalski', 'text': 'A'}, follow_redirects=False)
    test('Opinia < 2 znakow odrzucona (redirect)', r.status_code == 302)

    # Poprawne zgłoszenie — PRG: submit → 302 → /success
    r = client.post('/submit', data={
        'name': 'Anna Kowalska',
        'company': 'Sąd Okręgowy Warszawa',
        'job_title': 'Kierownik Sekretariatu',
        'text': 'Współpraca z Print Flow Solutions przebiega bardzo sprawnie. Polecam!',
        'rating': '5',
    }, follow_redirects=False)
    test('Submit przekierowuje (PRG pattern)', r.status_code == 302)
    test('Redirect prowadzi do /success', '/success' in r.headers.get('Location', ''))

    r = client.get('/success')
    test('GET /success zwraca 200', r.status_code == 200)
    test('Strona sukcesu zawiera polski tekst', 'Dziękujemy'.encode('utf-8') in r.data)
    test('Strona sukcesu nie zawiera bledu "przegladzeniu"', b'przegladzeniu' not in r.data)

    # Refresh strony sukcesu nie tworzy duplikatu
    r_refresh = client.get('/success')
    test('Refresh /success zwraca 200 (bez duplikatu)', r_refresh.status_code == 200)

    # Honeypot — bot wypełnia ukryte pole
    r = client.post('/submit', data={
        'name': 'Bot Spamer',
        'text': 'Spam spam spam',
        'website': 'http://spam.example.com',
    }, follow_redirects=False)
    test('Honeypot: bot dostaje redirect', r.status_code == 302)

    # Drugie zgłoszenie (3 gwiazdki)
    client.post('/submit', data={
        'name': 'Tomasz Wierzbicki',
        'company': 'SPZZOZ Pruszków',
        'job_title': 'IT Manager',
        'text': 'Serwis działa sprawnie, czas reakcji dobry.',
        'rating': '3',
    })

    # Zgłoszenie z logo
    fake_image = io.BytesIO(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00'
        b'\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18'
        b'\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    r = client.post('/submit', data={
        'name': 'Katarzyna Nowak',
        'company': 'Gmina Solec Kujawski',
        'text': 'Profesjonalna obsługa, szybka dostawa materiałów.',
        'rating': '5',
        'logo': (fake_image, 'logo.png', 'image/png'),
    }, content_type='multipart/form-data', follow_redirects=False)
    test('Zgloszenie z logo przekierowuje (302)', r.status_code == 302)

    # Sprawdz, czy plik logo trafil na persistent disk (DATA_DIR/uploads)
    uploads_dir = os.path.join(tmp_dir, 'uploads')
    files_in_uploads = os.listdir(uploads_dir) if os.path.exists(uploads_dir) else []
    test('Logo zapisane w DATA_DIR/uploads', len(files_in_uploads) >= 1,
         f'pliki: {files_in_uploads}')

    # Route /uploads/<file> serwuje plik
    if files_in_uploads:
        r = client.get(f'/uploads/{files_in_uploads[0]}')
        test('/uploads/<file> zwraca 200', r.status_code == 200)

    # Honeypot nie powinien zostac zapisany w bazie
    import sqlite3
    conn = sqlite3.connect(os.environ['DB_PATH'])
    bot_count = conn.execute("SELECT COUNT(*) FROM testimonials WHERE name='Bot Spamer'").fetchone()[0]
    conn.close()
    test('Honeypot nie zapisuje do bazy', bot_count == 0, f'zapisano {bot_count} spam')

    print('\n── API przed zatwierdzeniem ──')

    r = client.get('/api/testimonials')
    test('API zwraca 200', r.status_code == 200)
    test('CORS header obecny', 'Access-Control-Allow-Origin' in r.headers)
    data = json.loads(r.data)
    test('API nie pokazuje opinii pending', len(data) == 0, f'got {len(data)}')
    test('API zwraca JSON liste', isinstance(data, list))

    print('\n── Panel admina — auth ──')

    r = client.get('/admin')
    test('Niezalogowany dostaje redirect (302)', r.status_code == 302)

    r = client.post('/admin/login', data={'password': 'bledne'}, follow_redirects=True)
    test('Bledne haslo daje blad', r.status_code == 200)
    test('Komunikat o blednym hasle',
         'Błędne'.encode('utf-8') in r.data or 'hasło'.encode('utf-8') in r.data)

    r = client.post('/admin/login', data={'password': 'testpass'}, follow_redirects=True)
    test('Poprawne haslo loguje', r.status_code == 200)
    test('Panel admina po logowaniu zawiera opinie', b'Anna' in r.data or b'Tomasz' in r.data)
    test('Admin ma polskie znaki', 'Oczekujące'.encode('utf-8') in r.data)

    print('\n── Moderacja ──')

    # Pobierz ID opinii (pomijamy te z honeypota — juz odfiltrowane)
    conn = sqlite3.connect(os.environ['DB_PATH'])
    ids = [r[0] for r in conn.execute('SELECT id FROM testimonials ORDER BY id').fetchall()]
    conn.close()
    test('W bazie sa 3 opinie', len(ids) == 3, f'got {len(ids)}')

    first_id = ids[0]

    r = client.post(f'/admin/action/{first_id}', data={'action': 'approved'}, follow_redirects=True)
    test('Zatwierdzenie dziala (200)', r.status_code == 200)

    r = client.post(f'/admin/action/{ids[1]}', data={'action': 'rejected'}, follow_redirects=True)
    test('Odrzucenie dziala (200)', r.status_code == 200)

    print('\n── API po moderacji ──')

    r = client.get('/api/testimonials')
    data = json.loads(r.data)
    test('API zwraca 1 zatwierdzona opinie', len(data) == 1, f'got {len(data)}')
    test('Opinia ma pole name', 'name' in data[0])
    test('Opinia ma pole text', 'text' in data[0])
    test('Opinia ma pole rating', 'rating' in data[0])
    test('Opinia ma logo_url', 'logo_url' in data[0])
    test('Nie ma pola logo_filename w API', 'logo_filename' not in data[0])
    test('Zatwierdzona ma rating 5', data[0]['rating'] == 5)

    print('\n── Usuwanie ──')

    r = client.post(f'/admin/delete/{ids[1]}', follow_redirects=True)
    test('Usuniecie dziala', r.status_code == 200)

    conn = sqlite3.connect(os.environ['DB_PATH'])
    count = conn.execute('SELECT COUNT(*) FROM testimonials').fetchone()[0]
    conn.close()
    test('Po usunieciu zostaly 2 rekordy', count == 2, f'got {count}')

    print('\n── Wylogowanie ──')

    r = client.get('/admin/logout', follow_redirects=True)
    test('Wylogowanie przekierowuje do loginu', r.status_code == 200)
    r = client.get('/admin')
    test('Po wylogowaniu /admin znow daje redirect', r.status_code == 302)

    print('\n── Widget JS ──')

    r = client.get('/static/widget.js')
    test('widget.js dostepny', r.status_code == 200)
    test('Widget zawiera pfs-wall', b'pfs-wall' in r.data)
    test('Widget zawiera API fetch', b'/api/testimonials' in r.data)
    test('Widget ma escape HTML', b'escapeHtml' in r.data or b'esc(' in r.data)

    print('\n── Statyczne zasoby ──')

    r = client.get('/static/logo.png')
    test('logo.png dostepne', r.status_code == 200)
    r = client.get('/static/logo_white.png')
    test('logo_white.png dostepne', r.status_code == 200)

    print('\n── Lokalizacja czasu ──')

    from app import localtime_filter
    utc_ts = '2026-04-21 10:00:00'
    local = localtime_filter(utc_ts)
    test('UTC konwertowany na czas lokalny', local != utc_ts[:16], f'got: {local}')
    test('Wynik ma format YYYY-MM-DD HH:MM', len(local) == 16 and local[4] == '-',
         f'got: {local}')

    # Podsumowanie
    passed = 40 - len(errors)
    print(f'\n{"─"*40}')
    if errors:
        print(f'\033[91mNIEPOWODZENIA ({len(errors)}):\033[0m')
        for e in errors:
            print(f'  • {e}')
        print(f'\nWynik: {passed}/40 testow')
        sys.exit(1)
    else:
        print(f'\033[92mWszystkie testy przeszly!\033[0m')

if __name__ == '__main__':
    try:
        run()
    finally:
        # Cleanup
        import shutil
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
