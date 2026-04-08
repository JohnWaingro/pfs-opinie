"""
End-to-end testy apki opinii PFS.
Uruchom: python3 test_app.py
"""
import sys
import os
import io
import json
import tempfile
import shutil

# Ustaw tymczasowa baze danych
tmp_db = tempfile.mktemp(suffix='.db')
os.environ['DB_PATH'] = tmp_db
os.environ['ADMIN_PASSWORD'] = 'testpass'

from app import app, init_db

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
    test('Formularz zawiera upload', b'name="photo"' in r.data)

    print('\n── Wysylanie opinii ──')

    # Brak wymaganych pol
    r = client.post('/submit', data={'name': '', 'text': ''}, follow_redirects=True)
    test('Pusty formularz nie zapisuje (redirect/flash)', r.status_code == 200)

    # Poprawne zgłoszenie
    r = client.post('/submit', data={
        'name': 'Anna Kowalska',
        'company': 'Sad Okregowy Warszawa',
        'job_title': 'Kierownik Sekretariatu',
        'text': 'Wspolpraca z Print Flow Solutions przebiega bardzo sprawnie. Polecam!',
        'rating': '5',
    }, follow_redirects=True)
    test('Poprawna opinia zwraca 200', r.status_code == 200)
    test('Strona sukcesu zawiera imie klienta', b'Anna' in r.data)

    # Drugie zgłoszenie (3 gwiazdki)
    client.post('/submit', data={
        'name': 'Tomasz Wierzbicki',
        'company': 'SPZZOZ Pruszkow',
        'job_title': 'IT Manager',
        'text': 'Serwis dziala sprawnie, czas reakcji dobry.',
        'rating': '3',
    })

    # Zgłoszenie z plikiem
    fake_image = io.BytesIO(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
        b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00'
        b'\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18'
        b'\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    r = client.post('/submit', data={
        'name': 'Katarzyna Nowak',
        'company': 'Gmina Solec Kujawski',
        'text': 'Profesjonalna obsluga, szybka dostawa materialow.',
        'rating': '5',
        'photo': (fake_image, 'zdjecie.png', 'image/png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    test('Zgloszenie z plikiem dziala', r.status_code == 200)

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
    test('Komunikat o blednym hasle', 'Bledne' in r.data.decode() or 'haslo' in r.data.decode().lower())

    r = client.post('/admin/login', data={'password': 'testpass'}, follow_redirects=True)
    test('Poprawne haslo loguje', r.status_code == 200)
    test('Panel admina po logowaniu zawiera opinie', b'Anna' in r.data or b'Tomasz' in r.data)

    print('\n── Moderacja ──')

    # Pobierz ID pierwszej opinii z bazy
    import sqlite3
    conn = sqlite3.connect(tmp_db)
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
    test('Opinia ma photo_url (None lub str)', 'photo_url' in data[0])
    test('Nie ma pola photo_filename w API', 'photo_filename' not in data[0])
    test('Zatwierdzona ma rating 5', data[0]['rating'] == 5)

    print('\n── Usuwanie ──')

    r = client.post(f'/admin/delete/{ids[1]}', follow_redirects=True)
    test('Usuniecie dziala', r.status_code == 200)

    import sqlite3
    conn = sqlite3.connect(tmp_db)
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

    # Podsumowanie
    total = 30
    passed = total - len(errors)
    print(f'\n{"─"*40}')
    if errors:
        print(f'\033[91mNIEPOWODZENIA ({len(errors)}):\033[0m')
        for e in errors:
            print(f'  • {e}')
        print(f'\nWynik: {passed}/{total} testow')
        sys.exit(1)
    else:
        print(f'\033[92mWszystkie testy przeszly!\033[0m  {passed}/{total}')

if __name__ == '__main__':
    try:
        run()
    finally:
        # Cleanup
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
        # Usun testowe uploady
        uploads = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
        for f in os.listdir(uploads):
            if f != '.gitkeep':
                try:
                    os.remove(os.path.join(uploads, f))
                except Exception:
                    pass
