from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, random, string, secrets, json
from functools import wraps
from datetime import timedelta, date, datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import time as time_mod

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'teziskelesi-gizli-anahtar-2024')
app.permanent_session_lifetime = timedelta(days=30)

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'meydan.db')

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123456'

SMTP_SERVER   = 'smtp.gmail.com'
SMTP_PORT     = 587
SMTP_USER     = 'eemrahkus@gmail.com'
SMTP_PASSWORD = 'kqwv jvrb axks ipid'
NOTIFY_EMAIL  = 'eemrahkus@gmail.com'

PLATFORM_NAME = 'Tezİskelesi'

# Görünen etiketler (DB'deki tipler aynı kalır: cunku, fakat, lakin)
TYPE_LABELS = {
    'cunku': 'Zira',
    'fakat': 'Gelgelelim',
    'lakin': 'Yalnız',
}

FLAG_LABELS = {
    'safsata':    'Safsata',
    'bilim_disi': 'Bilim Dışı',
    'asilsiz':    'Asılsız',
    'kaynaksiz':  'Kaynaksız',
    'hakaret':    'Hakaret',
    'spam':       'Spam',
}


# ═══════════════════════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()

    conn.executescript('''
        DROP TABLE IF EXISTS flags;
        DROP TABLE IF EXISTS votes;
        DROP TABLE IF EXISTS nodes;
        DROP TABLE IF EXISTS topics;
        DROP TABLE IF EXISTS activity_log;
        DROP TABLE IF EXISTS site_content;
        DROP TABLE IF EXISTS haykir_entries;
        DROP TABLE IF EXISTS pikpik_pixels;
        DROP TABLE IF EXISTS pikpik_archives;
        DROP TABLE IF EXISTS pikpik_schedule;
        DROP TABLE IF EXISTS api_tokens;
        DROP TABLE IF EXISTS users;
    ''')

    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            pik_balance INTEGER DEFAULT 50,
            theme TEXT DEFAULT 'dark',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            parent_id INTEGER,
            type TEXT NOT NULL,
            text TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES topics(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (parent_id) REFERENCES nodes(id)
        );

        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            value INTEGER NOT NULL,
            UNIQUE(user_id, target_type, target_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, target_type, target_id, label),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT NOT NULL,
            detail TEXT,
            target_type TEXT,
            target_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS site_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            title TEXT DEFAULT '',
            body TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS haykir_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            content TEXT NOT NULL,
            font_size INTEGER DEFAULT 28,
            color TEXT DEFAULT '#ffffff',
            direction INTEGER DEFAULT 0,
            font_family TEXT DEFAULT 'Syne',
            effect TEXT DEFAULT 'none',
            shadow TEXT DEFAULT 'none',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS pikpik_pixels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            color TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(x, y),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS pikpik_archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            pixel_data TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pikpik_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            next_reset TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS api_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    ''')

    conn.execute(
        "INSERT INTO users (username, email, password, is_admin) VALUES (?,?,?,1)",
        [ADMIN_USERNAME, NOTIFY_EMAIL, generate_password_hash(ADMIN_PASSWORD)]
    )

    conn.execute(
        "INSERT INTO site_content (key, title, body) VALUES (?,?,?)",
        ['about', f'{PLATFORM_NAME} Hakkında',
         f'{PLATFORM_NAME} Nedir?\n'
         '─────────────\n'
         f'{PLATFORM_NAME}, fikirlerin mantıksal çerçevede çarpıştığı, yapılandırılmış bir dijital tartışma platformudur.\n'
         f'Geleneksel forum ve sosyal medya platformlarından farklı olarak {PLATFORM_NAME}, her tartışmayı bir "ağaç" '
         'yapısı altında organize eder. Her fikir Zira ile desteklenir, Gelgelelim ile itiraz edilir, '
         'Yalnız ile koşullu olarak kabul edilir.\n\n'
         'Misyonumuz\n'
         '──────────\n'
         'Dijital dünyada nitelikli düşünce alışverişini teşvik etmek.\n\n'
         'Nasıl Çalışır?\n'
         '──────────────\n'
         '1. Bir kullanıcı "Başlık" (önerme/iddia) oluşturur.\n'
         '2. Diğer kullanıcılar bu başlığa üç farklı şekilde yanıt verir:\n'
         '   • Zira — Başlığı destekleyen argümanlar sunar.\n'
         '   • Gelgelelim — Başlığa itiraz eder ve karşıt görüş belirtir.\n'
         '   • Yalnız — Başlığa belirli koşullar altında katılır.\n'
         '3. Bu cevaplar da alt dallara ayrılarak derinleşir.\n'
         '4. Her düğüm topluluk tarafından oy alır.']
    )

    conn.execute(
        "INSERT INTO site_content (key, title, body) VALUES (?,?,?)",
        ['faq', 'Sıkça Sorulan Sorular',
         'S: Tartışma nasıl başlatılır?\nC: Ana sayfadaki "Yeni Tartışma Başlat" alanına iddianızı yazın.\n\n'
         'S: Zira, Gelgelelim, Yalnız ne anlama gelir?\nC: Zira = Destek, Gelgelelim = İtiraz, Yalnız = Koşullu katılma.\n\n'
         'S: PikPik nedir?\nC: 100x100 piksellik bir tuval üzerinde piksel boyama oyunudur.\n\n'
         'S: Haykır nedir?\nC: Duygularınızı dev harflerle haykırabildiğiniz bir canvas alanıdır.']
    )

    today = date.today()
    days_until_sunday = (6 - today.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7
    next_sunday = today + timedelta(days=days_until_sunday)
    random_hour = random.randint(0, 23)
    random_minute = random.randint(0, 59)
    reset_time = f"{next_sunday.isoformat()} {random_hour:02d}:{random_minute:02d}:00"
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_end = (today + timedelta(days=6-today.weekday())).isoformat()
    conn.execute(
        'INSERT INTO pikpik_schedule (week_start, next_reset, is_active) VALUES (?,?,1)',
        [week_start, reset_time]
    )

    conn.commit()
    conn.close()
    print(f"[DB] {PLATFORM_NAME} veritabanı başarıyla oluşturuldu.")


def migrate_db():
    conn = get_db()
    try:
        conn.execute("ALTER TABLE users ADD COLUMN theme TEXT DEFAULT 'dark'")
        conn.commit()
        print("[DB] theme kolonu eklendi.")
    except:
        pass
    try:
        conn.execute("SELECT week_start FROM pikpik_archives LIMIT 1")
    except:
        try:
            conn.executescript('''
                DROP TABLE IF EXISTS pikpik_archives;
                CREATE TABLE pikpik_archives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week_start TEXT NOT NULL,
                    week_end TEXT NOT NULL,
                    pixel_data TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            conn.commit()
        except:
            pass
    needs_recreate = False
    try:
        conn.execute("SELECT is_active FROM pikpik_schedule LIMIT 1")
    except:
        needs_recreate = True
    if needs_recreate:
        try:
            conn.executescript('''
                DROP TABLE IF EXISTS pikpik_schedule;
                CREATE TABLE pikpik_schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week_start TEXT NOT NULL,
                    next_reset TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            conn.commit()
            today = date.today()
            days_until_sunday = (6 - today.weekday()) % 7
            if days_until_sunday == 0:
                days_until_sunday = 7
            next_sunday = today + timedelta(days=days_until_sunday)
            rh = random.randint(0, 23)
            rm = random.randint(0, 59)
            reset_time = f"{next_sunday.isoformat()} {rh:02d}:{rm:02d}:00"
            week_start = (today - timedelta(days=today.weekday())).isoformat()
            conn.execute(
                'INSERT INTO pikpik_schedule (week_start, next_reset, is_active) VALUES (?,?,1)',
                [week_start, reset_time]
            )
            conn.commit()
            print(f"[DB] İlk planlama oluşturuldu: sıfırlama {reset_time}")
        except Exception as e:
            print(f"[DB] pikpik_schedule hata: {e}")
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  PIKPIK HAFTALIK DÖNGÜ
# ═══════════════════════════════════════════════════════════════════════════════

def get_current_week_info():
    db = get_db()
    schedule = db.execute(
        'SELECT * FROM pikpik_schedule WHERE is_active=1 ORDER BY id DESC LIMIT 1'
    ).fetchone()
    db.close()
    if schedule:
        return dict(schedule)
    return None


def archive_current_week():
    db = get_db()
    rows = db.execute('SELECT p.x, p.y, p.color, p.user_id FROM pikpik_pixels p').fetchall()
    pixel_data = json.dumps([{'x': r['x'], 'y': r['y'], 'color': r['color'], 'user_id': r['user_id']} for r in rows])
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_end = (today + timedelta(days=6-today.weekday())).isoformat()
    db.execute('INSERT INTO pikpik_archives (week_start, week_end, pixel_data) VALUES (?,?,?)',
               [week_start, week_end, pixel_data])
    db.execute('DELETE FROM pikpik_pixels')
    db.execute('UPDATE pikpik_schedule SET is_active=0 WHERE is_active=1')
    next_sunday = today + timedelta(days=(6 - today.weekday()) % 7)
    if next_sunday <= today:
        next_sunday = today + timedelta(days=7)
    rh = random.randint(0, 23)
    rm = random.randint(0, 59)
    reset_time = f"{next_sunday.isoformat()} {rh:02d}:{rm:02d}:00"
    db.execute('INSERT INTO pikpik_schedule (week_start, next_reset, is_active) VALUES (?,?,1)',
               [next_sunday.isoformat(), reset_time])
    db.commit()
    db.close()
    print(f"[PIKPIK] Hafta arşivlendi. Sıfırlama: {reset_time}")


def check_and_reset():
    schedule = get_current_week_info()
    if not schedule:
        return
    now = datetime.now()
    try:
        reset_time = datetime.strptime(schedule['next_reset'], '%Y-%m-%d %H:%M:%S')
    except:
        return
    if now >= reset_time:
        archive_current_week()


def pikpik_scheduler():
    while True:
        try:
            check_and_reset()
        except Exception as e:
            print(f"[PIKPIK SCHEDULER] Hata: {e}")
        time_mod.sleep(60)


# ═══════════════════════════════════════════════════════════════════════════════
#  E-POSTA
# ═══════════════════════════════════════════════════════════════════════════════

def send_email(to_email, subject, text_body, html_body=''):
    if not SMTP_USER or not SMTP_PASSWORD:
        return False
    def _send():
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = SMTP_USER
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
            if html_body:
                msg.attach(MIMEText(html_body, 'html', 'utf-8'))
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
        except Exception as e:
            print(f"[EMAIL] Hata: {e}")
    threading.Thread(target=_send, daemon=True).start()
    return True


def send_notification_email(topic_title, username, topic_id):
    text = (f"{PLATFORM_NAME} - Yeni Tartışma Bildirimi\n\n"
            f"Başlık: {topic_title}\nKullanıcı: @{username}\nID: {topic_id}\n\n"
            f"Admin Panel: http://localhost:8073/admin")
    html = f"""<div style="font-family:monospace;max-width:520px;margin:0 auto;background:#13151a;border-radius:16px;padding:32px;color:#e8e6e1;">
<h2 style="color:#8b5cf6;">Yeni Tartışma</h2>
<p style="color:#6b6f7a;">{topic_title}</p>
<p style="color:#6b6f7a;">@{username} #{topic_id}</p></div>"""
    send_email(NOTIFY_EMAIL, f'[{PLATFORM_NAME}] Yeni Tartışma: {topic_title}', text, html)


# ═══════════════════════════════════════════════════════════════════════════════
#  LOG & HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def log_activity(user_id, username, action, detail='', target_type=None, target_id=None):
    try:
        db = get_db()
        db.execute('INSERT INTO activity_log (user_id,username,action,detail,target_type,target_id) VALUES (?,?,?,?,?,?)',
                   [user_id, username, action, detail, target_type, target_id])
        db.commit()
        db.close()
    except Exception as e:
        print(f"[LOG] Hata: {e}")


def build_tree(nodes):
    node_map = {}
    for n in nodes:
        nd = dict(n) if not isinstance(n, dict) else dict(n)
        nd['children'] = []
        node_map[nd['id']] = nd
    roots = []
    for n in node_map.values():
        pid = n.get('parent_id')
        if pid and pid in node_map:
            node_map[pid]['children'].append(n)
        else:
            roots.append(n)
    return roots


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        db = get_db()
        u = db.execute('SELECT is_banned FROM users WHERE id=?', [session['user_id']]).fetchone()
        db.close()
        if u and u['is_banned']:
            session.clear()
            flash('Hesabınız engellenmiştir.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated


def get_vote_counts(db, target_type, target_id):
    rows = db.execute("SELECT value, COUNT(*) as c FROM votes WHERE target_type=? AND target_id=? GROUP BY value",
                      [target_type, target_id]).fetchall()
    up = down = 0
    for r in rows:
        if r['value'] == 1: up = r['c']
        else: down = r['c']
    return up, down


def get_user_vote(db, user_id, target_type, target_id):
    r = db.execute("SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?",
                   [user_id, target_type, target_id]).fetchone()
    return r['value'] if r else 0


def get_flags(db, target_type, target_id):
    rows = db.execute("SELECT label, COUNT(*) as c FROM flags WHERE target_type=? AND target_id=? GROUP BY label",
                      [target_type, target_id]).fetchall()
    return {r['label']: r['c'] for r in rows}


def award_pik(user_id, amount):
    if not user_id: return
    db = get_db()
    db.execute('UPDATE users SET pik_balance = MAX(0, pik_balance + ?) WHERE id=?', [amount, user_id])
    db.commit()
    db.close()


@app.context_processor
def inject_globals():
    ctx = {'platform_name': PLATFORM_NAME, 'type_labels': TYPE_LABELS}
    if 'user_id' in session:
        try:
            db = get_db()
            u = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()
            db.close()
            ctx['pik_balance'] = u['pik_balance'] if u else 0
        except:
            ctx['pik_balance'] = 0
    else:
        ctx['pik_balance'] = 0
    valid_themes = {'dark', 'karikatur', 'xp', 'win98', 'doga', 'terminal', 'pastel'}
    t = 'dark'
    if 'user_id' in session:
        try:
            db2 = get_db()
            u2 = db2.execute('SELECT theme FROM users WHERE id=?', [session['user_id']]).fetchone()
            db2.close()
            if u2 and u2['theme'] in valid_themes:
                t = u2['theme']
        except:
            pass
    ctx['theme'] = t
    return ctx


@app.route('/api/set-theme', methods=['POST'])
def api_set_theme():
    data = request.get_json(silent=True) or {}
    theme = data.get('theme', 'dark')
    valid_themes = {'dark', 'karikatur', 'xp', 'win98', 'doga', 'terminal', 'pastel'}
    if theme in valid_themes and 'user_id' in session:
        db = get_db()
        db.execute('UPDATE users SET theme=? WHERE id=?', [theme, session['user_id']])
        db.commit()
        db.close()
    return jsonify({'ok': True, 'theme': theme})


# ═══════════════════════════════════════════════════════════════════════════════
#  HOME
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
@login_required
def home():
    db = get_db()
    if session.get('is_admin'):
        status_filter = "t.status IN ('approved','pending','rejected')"
    else:
        status_filter = "t.status='approved'"

    topics = db.execute(f'''
        SELECT t.id, t.title, t.created_at, t.status, u.username, t.user_id,
               COUNT(CASE WHEN n.type='cunku' THEN 1 END) as cunku_count,
               COUNT(CASE WHEN n.type='fakat' THEN 1 END) as fakat_count,
               COUNT(CASE WHEN n.type='lakin' THEN 1 END) as lakin_count
        FROM topics t
        JOIN users u ON t.user_id = u.id
        LEFT JOIN nodes n ON n.topic_id = t.id
        WHERE {status_filter}
        GROUP BY t.id
        ORDER BY t.created_at DESC
    ''').fetchall()

    result = []
    for t in topics:
        td = dict(t)
        up, down = get_vote_counts(db, 'topic', t['id'])
        td['up'] = up; td['down'] = down
        td['user_vote'] = get_user_vote(db, session['user_id'], 'topic', t['id'])
        td['flags'] = get_flags(db, 'topic', t['id'])
        result.append(td)

    pending_count = 0
    if session.get('is_admin'):
        pending_count = db.execute("SELECT COUNT(*) FROM topics WHERE status='pending'").fetchone()[0]
    db.close()
    return render_template('home.html', topics=result, pending_count=pending_count,
                           flag_labels=FLAG_LABELS, type_labels=TYPE_LABELS)


# ═══════════════════════════════════════════════════════════════════════════════
#  VOTE & FLAG
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/vote', methods=['POST'])
@login_required
def vote():
    target_type = request.form.get('target_type')
    target_id = int(request.form.get('target_id', 0))
    value = int(request.form.get('value', 0))
    next_url = request.form.get('next', '/')
    if target_type not in ('topic', 'node') or value not in (1, -1):
        return redirect(next_url)
    db = get_db()
    existing = db.execute("SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?",
                          [session['user_id'], target_type, target_id]).fetchone()
    owner_id = None
    if target_type == 'topic':
        t = db.execute('SELECT user_id FROM topics WHERE id=?', [target_id]).fetchone()
        if t: owner_id = t['user_id']
    elif target_type == 'node':
        n = db.execute('SELECT user_id FROM nodes WHERE id=?', [target_id]).fetchone()
        if n: owner_id = n['user_id']
    if existing:
        old_val = existing['value']
        if old_val == value:
            db.execute("DELETE FROM votes WHERE user_id=? AND target_type=? AND target_id=?",
                       [session['user_id'], target_type, target_id])
            if value == 1 and owner_id and owner_id != session['user_id']:
                db.execute('UPDATE users SET pik_balance = MAX(0, pik_balance - 5) WHERE id=?', [owner_id])
        else:
            db.execute("UPDATE votes SET value=? WHERE user_id=? AND target_type=? AND target_id=?",
                       [value, session['user_id'], target_type, target_id])
            if value == 1 and owner_id and owner_id != session['user_id']:
                db.execute('UPDATE users SET pik_balance = pik_balance + 5 WHERE id=?', [owner_id])
            elif value == -1 and old_val == 1 and owner_id and owner_id != session['user_id']:
                db.execute('UPDATE users SET pik_balance = MAX(0, pik_balance - 5) WHERE id=?', [owner_id])
    else:
        db.execute("INSERT INTO votes (user_id,target_type,target_id,value) VALUES (?,?,?,?)",
                   [session['user_id'], target_type, target_id, value])
        if value == 1 and owner_id and owner_id != session['user_id']:
            db.execute('UPDATE users SET pik_balance = pik_balance + 5 WHERE id=?', [owner_id])
    db.commit(); db.close()
    return redirect(next_url)


@app.route('/flag', methods=['POST'])
@login_required
def flag():
    target_type = request.form.get('target_type')
    target_id = int(request.form.get('target_id', 0))
    label = request.form.get('label', '')
    next_url = request.form.get('next', '/')
    if target_type not in ('topic', 'node') or label not in FLAG_LABELS:
        return redirect(next_url)
    db = get_db()
    try:
        db.execute("INSERT INTO flags (user_id,target_type,target_id,label) VALUES (?,?,?,?)",
                   [session['user_id'], target_type, target_id, label])
        db.commit()
    except sqlite3.IntegrityError:
        db.execute("DELETE FROM flags WHERE user_id=? AND target_type=? AND target_id=? AND label=?",
                   [session['user_id'], target_type, target_id, label])
        db.commit()
    db.close()
    return redirect(next_url)


# ═══════════════════════════════════════════════════════════════════════════════
#  TOPIC
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/topic/new', methods=['POST'])
@login_required
def new_topic():
    title = request.form.get('title', '').strip()
    if not title:
        return redirect(url_for('home'))
    db = get_db()
    status = 'approved' if session.get('is_admin') else 'pending'
    cur = db.execute('INSERT INTO topics (user_id,title,status) VALUES (?,?,?)',
                     [session['user_id'], title, status])
    db.commit(); tid = cur.lastrowid; db.close()
    log_activity(session['user_id'], session['username'], 'new_topic', f'Baslik: {title}', 'topic', tid)
    if not session.get('is_admin'):
        send_notification_email(title, session['username'], tid)
        flash('Tartışmanız admin onayına gönderildi.')
        return redirect(url_for('home'))
    return redirect(url_for('topic', topic_id=tid))


@app.route('/topic/<int:topic_id>')
@login_required
def topic(topic_id):
    db = get_db()
    t = db.execute('SELECT t.*, u.username FROM topics t JOIN users u ON t.user_id=u.id WHERE t.id=?',
                   [topic_id]).fetchone()
    if not t:
        db.close(); return redirect(url_for('home'))
    if t['status'] != 'approved' and not session.get('is_admin'):
        db.close(); flash('Bu tartışma henüz onaylanmamış.'); return redirect(url_for('home'))

    nodes_raw = db.execute('''
        SELECT n.id, n.parent_id, n.type, n.text, n.user_id, n.created_at, u.username
        FROM nodes n JOIN users u ON n.user_id=u.id
        WHERE n.topic_id=? ORDER BY n.id
    ''', [topic_id]).fetchall()

    nodes = []
    node_map = {}
    for n in nodes_raw:
        nd = dict(n)
        up, down = get_vote_counts(db, 'node', n['id'])
        nd['up'] = up; nd['down'] = down
        nd['user_vote'] = get_user_vote(db, session['user_id'], 'node', n['id'])
        nd['flags'] = get_flags(db, 'node', n['id'])
        nodes.append(nd); node_map[nd['id']] = nd

    topic_dict = dict(t)
    for n in nodes:
        depth = 0; pid = n.get('parent_id')
        while pid and pid in node_map:
            depth += 1; pid = node_map[pid].get('parent_id')
        n['depth'] = depth
        pid = n.get('parent_id')
        if pid and pid in node_map:
            n['parent_text'] = node_map[pid]['text'][:80]
            n['parent_type'] = node_map[pid]['type']
        else:
            n['parent_text'] = topic_dict['title'][:80]
            n['parent_type'] = None

    tree = build_tree(nodes)
    topic_up, topic_down = get_vote_counts(db, 'topic', topic_id)
    topic_user_vote = get_user_vote(db, session['user_id'], 'topic', topic_id)
    topic_flags = get_flags(db, 'topic', topic_id)
    db.close()
    return render_template('topic.html',
                           topic=topic_dict, nodes=nodes, tree=tree,
                           current_user_id=session['user_id'],
                           topic_up=topic_up, topic_down=topic_down,
                           topic_user_vote=topic_user_vote,
                           topic_flags=topic_flags, flag_labels=FLAG_LABELS,
                           type_labels=TYPE_LABELS)


@app.route('/topic/<int:topic_id>/reply', methods=['POST'])
@login_required
def add_reply(topic_id):
    db = get_db()
    t = db.execute('SELECT status, user_id FROM topics WHERE id=?', [topic_id]).fetchone()
    if not t or t['status'] != 'approved':
        db.close(); return redirect(url_for('home'))
    raw = request.form.get('parent_id', '').strip()
    parent_id = int(raw) if raw.isdigit() else None
    node_type = request.form.get('type', '').strip()
    text = request.form.get('text', '').strip()
    if text and node_type in ('cunku', 'fakat', 'lakin'):
        cur = db.execute('INSERT INTO nodes (topic_id,parent_id,type,text,user_id) VALUES (?,?,?,?,?)',
                         [topic_id, parent_id, node_type, text, session['user_id']])
        db.commit()
        log_activity(session['user_id'], session['username'], 'new_reply',
                     f'Tur:{node_type}, Metin:{text[:100]}', 'node', cur.lastrowid)
        if parent_id:
            pn = db.execute('SELECT user_id FROM nodes WHERE id=?', [parent_id]).fetchone()
            if pn and pn['user_id'] != session['user_id']:
                db.execute('UPDATE users SET pik_balance = pik_balance + 1 WHERE id=?', [pn['user_id']])
                db.commit()
        else:
            if t['user_id'] != session['user_id']:
                db.execute('UPDATE users SET pik_balance = pik_balance + 1 WHERE id=?', [t['user_id']])
                db.commit()
    db.close()
    return redirect(url_for('topic', topic_id=topic_id))


@app.route('/topic/<int:topic_id>/delete', methods=['POST'])
@login_required
def delete_topic(topic_id):
    db = get_db()
    t = db.execute('SELECT user_id FROM topics WHERE id=?', [topic_id]).fetchone()
    if t and (t['user_id'] == session['user_id'] or session.get('is_admin')):
        for nid in [r['id'] for r in db.execute('SELECT id FROM nodes WHERE topic_id=?', [topic_id]).fetchall()]:
            db.execute('DELETE FROM votes WHERE target_type="node" AND target_id=?', [nid])
            db.execute('DELETE FROM flags WHERE target_type="node" AND target_id=?', [nid])
        db.execute('DELETE FROM nodes WHERE topic_id=?', [topic_id])
        db.execute('DELETE FROM votes WHERE target_type="topic" AND target_id=?', [topic_id])
        db.execute('DELETE FROM flags WHERE target_type="topic" AND target_id=?', [topic_id])
        db.execute('DELETE FROM topics WHERE id=?', [topic_id])
        db.commit()
        log_activity(session['user_id'], session['username'], 'delete_topic', f'Topic #{topic_id}', 'topic', topic_id)
    db.close()
    return redirect(url_for('home'))


@app.route('/node/<int:node_id>/delete', methods=['POST'])
@login_required
def delete_node(node_id):
    db = get_db()
    node = db.execute('SELECT * FROM nodes WHERE id=?', [node_id]).fetchone()
    if not node:
        db.close(); return redirect(url_for('home'))
    topic_id = node['topic_id']
    if node['user_id'] == session['user_id'] or session.get('is_admin'):
        def del_tree(nid):
            for c in db.execute('SELECT id FROM nodes WHERE parent_id=?', [nid]).fetchall():
                del_tree(c['id'])
            db.execute('DELETE FROM votes WHERE target_type="node" AND target_id=?', [nid])
            db.execute('DELETE FROM flags WHERE target_type="node" AND target_id=?', [nid])
            db.execute('DELETE FROM nodes WHERE id=?', [nid])
        del_tree(node_id); db.commit()
        log_activity(session['user_id'], session['username'], 'delete_node', f'Node #{node_id}', 'node', node_id)
    db.close()
    return redirect(url_for('topic', topic_id=topic_id))


@app.route('/node/<int:node_id>/edit', methods=['POST'])
@login_required
def edit_node(node_id):
    new_text = request.form.get('text', '').strip()
    db = get_db()
    node = db.execute('SELECT * FROM nodes WHERE id=?', [node_id]).fetchone()
    if node and (node['user_id'] == session['user_id'] or session.get('is_admin')) and new_text:
        db.execute('UPDATE nodes SET text=? WHERE id=?', [new_text, node_id])
        db.commit()
        log_activity(session['user_id'], session['username'], 'edit_node', f'Node #{node_id}', 'node', node_id)
    topic_id = node['topic_id'] if node else 1
    db.close()
    return redirect(url_for('topic', topic_id=topic_id))


# ═══════════════════════════════════════════════════════════════════════════════
#  PROFIL
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/profile/<username>')
def profile(username):
    conn = get_db()
    profile_user = conn.execute('SELECT * FROM users WHERE username=?', [username]).fetchone()
    if not profile_user:
        flash('Kullanıcı bulunamadı.')
        return redirect('/')

    uid = profile_user['id']
    type_labels = {'cunku': 'Zira', 'fakat': 'Gelgelelim', 'lakin': 'Yalnız'}

    # ═══ BAŞLIKLAR ═══
    topics = conn.execute('''
        SELECT t.*,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='cunku') as cunku_count,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='fakat') as fakat_count,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='lakin') as lakin_count,
            (SELECT COUNT(*) FROM votes WHERE target_type='topic' AND target_id=t.id AND value=1) as up,
            (SELECT COUNT(*) FROM votes WHERE target_type='topic' AND target_id=t.id AND value=-1) as down
        FROM topics t
        WHERE t.user_id=? AND t.status='approved'
        ORDER BY t.created_at DESC
    ''', [uid]).fetchall()

    # ═══ CEVAPLAR ═══
    replies = conn.execute('''
        SELECT n.*, t.title as topic_title, t.id as topic_id,
            (SELECT COUNT(*) FROM votes WHERE target_type='node' AND target_id=n.id AND value=1) as up,
            (SELECT COUNT(*) FROM votes WHERE target_type='node' AND target_id=n.id AND value=-1) as down
        FROM nodes n
        JOIN topics t ON n.topic_id=t.id
        WHERE n.user_id=?
        ORDER BY n.created_at DESC
    ''', [uid]).fetchall()

    # ═══ HAYKIRIŞLAR (en yeni en üstte) ═══
    haykir_entries = conn.execute('''
        SELECT * FROM haykir_entries
        WHERE user_id=?
        ORDER BY day DESC, id DESC
    ''', [uid]).fetchall()

    # ═══ PIKSELLER ═══
    pik_entries = conn.execute('''
        SELECT * FROM pikpik_pixels
        WHERE user_id=?
        ORDER BY id DESC
    ''', [uid]).fetchall()

    # ═══ İSTATİSTİKLER ═══
    stats = {
        'topic_count': len(topics),
        'reply_count': len(replies),
        'cunku_count': sum(1 for r in replies if r['type'] == 'cunku'),
        'fakat_count': sum(1 for r in replies if r['type'] == 'fakat'),
        'lakin_count': sum(1 for r in replies if r['type'] == 'lakin'),
        'haykir_count': len(haykir_entries),
        'pik_count': len(pik_entries),
    }

    return render_template('profile.html',
        profile_user=profile_user, topics=topics, replies=replies,
        haykir_entries=haykir_entries, pik_entries=pik_entries,
        stats=stats, type_labels=type_labels
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  HAKKINDA
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/about')
def about():
    conn = get_db()
    items = conn.execute('SELECT * FROM site_content ORDER BY id ASC').fetchall()
    return render_template('about.html', items=items)


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════════════════════════

# ══════ ADMIN: HAYKIRIŞ SİL ══════
@app.route('/admin/haykir/<int:eid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_haykir(eid):
    conn = get_db()
    conn.execute('DELETE FROM haykir_entries WHERE id=?', [eid])
    conn.commit()
    log_activity('delete_haykir', f'Haykırış #{eid} silindi')
    flash('Haykırış silindi.')
    return redirect('/admin')

# ══════ ADMIN: PIKPIK PİKSEL SİL ══════
@app.route('/admin/pikpik/<int:pid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_pik(pid):
    conn = get_db()
    conn.execute('DELETE FROM pikpik_pixels WHERE id=?', [pid])
    conn.commit()
    log_activity('delete_pik', f'Piksel #{pid} silindi')
    flash('Piksel silindi.')
    return redirect('/admin')

# ══════ ADMIN: TÜM PİKSELLERİ SIFIRLA ══════
@app.route('/admin/pikpik/clear', methods=['POST'])
@login_required
@admin_required
def admin_clear_pikpik():
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM pikpik_pixels').fetchone()[0]
    conn.execute('DELETE FROM pikpik_pixels')
    conn.commit()
    log_activity('clear_pikpik', f'{count} piksel sıfırlandı')
    flash(f'{count} piksel sıfırlandı.')
    return redirect('/admin')

# ══════ ADMIN PANELİ — GÜNCELLENECEK ROUTE ══════
# Mevcut /admin route'unuza şunları ekleyin:
@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    conn = get_db()

    # Mevcut veriler
    all_topics = conn.execute('SELECT t.*, u.username FROM topics t JOIN users u ON t.user_id=u.id ORDER BY t.created_at DESC').fetchall()
    users = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    pending = [t for t in all_topics if t['status'] == 'pending']
    site_items = conn.execute('SELECT * FROM site_content ORDER BY id').fetchall()
    activity = conn.execute('SELECT a.*, u.username FROM activity_log a LEFT JOIN users u ON a.user_id=u.id ORDER BY a.created_at DESC LIMIT 200').fetchall()

    # Yeni: Haykırışlar
    haykir_entries = conn.execute('''
        SELECT h.*, u.username
        FROM haykir_entries h
        JOIN users u ON h.user_id=u.id
        ORDER BY h.day DESC, h.id DESC
    ''').fetchall()

    # Yeni: PikPik pikselleri
    pik_entries = conn.execute('''
        SELECT p.*, u.username
        FROM pikpik_pixels p
        JOIN users u ON p.user_id=u.id
        ORDER BY p.id DESC
        LIMIT 500
    ''').fetchall()

    # Yeni: Sayaçlar
    haykir_count = conn.execute('SELECT COUNT(*) FROM haykir_entries').fetchone()[0]
    pik_count = conn.execute('SELECT COUNT(*) FROM pikpik_pixels').fetchone()[0]

    return render_template('admin.html',
        all_topics=all_topics, users=users, pending=pending,
        site_items=site_items, activity=activity,
        haykir_entries=haykir_entries, pik_entries=pik_entries,
        haykir_count=haykir_count, pik_count=pik_count
    )

@app.route('/admin/site-content/<int:item_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_site_content(item_id):
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    db = get_db()
    db.execute('UPDATE site_content SET title=?, body=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
               [title, body, item_id])
    db.commit(); db.close()
    log_activity(session['user_id'], session['username'], 'edit_site_content', f'Item #{item_id}')
    flash('İçerik güncellendi.')
    return redirect(url_for('admin_panel'))


@app.route('/admin/site-content/add', methods=['POST'])
@login_required
@admin_required
def add_site_content():
    key = request.form.get('key', '').strip().replace(' ', '_').lower()
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    if key and title:
        db = get_db()
        try:
            db.execute('INSERT INTO site_content (key,title,body) VALUES (?,?,?)', [key, title, body])
            db.commit()
        except sqlite3.IntegrityError:
            flash('Bu anahtar zaten var.')
        db.close()
    return redirect(url_for('admin_panel'))


@app.route('/admin/site-content/<int:item_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_site_content(item_id):
    db = get_db()
    db.execute('DELETE FROM site_content WHERE id=?', [item_id])
    db.commit(); db.close()
    return redirect(url_for('admin_panel'))


@app.route('/admin/topic/<int:topic_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_topic(topic_id):
    db = get_db()
    db.execute("UPDATE topics SET status='approved' WHERE id=?", [topic_id])
    t = db.execute('SELECT user_id FROM topics WHERE id=?', [topic_id]).fetchone()
    if t:
        db.execute('UPDATE users SET pik_balance = pik_balance + 5 WHERE id=?', [t['user_id']])
    db.commit(); db.close()
    log_activity(session['user_id'], session['username'], 'approve_topic', f'Topic #{topic_id}', 'topic', topic_id)
    flash('Tartışma onaylandı.')
    return redirect(request.referrer or url_for('admin_panel'))


@app.route('/admin/topic/<int:topic_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_topic(topic_id):
    db = get_db()
    db.execute("UPDATE topics SET status='rejected' WHERE id=?", [topic_id])
    db.commit(); db.close()
    log_activity(session['user_id'], session['username'], 'reject_topic', f'Topic #{topic_id}', 'topic', topic_id)
    flash('Tartışma reddedildi.')
    return redirect(request.referrer or url_for('admin_panel'))


@app.route('/admin/user/<int:user_id>/ban', methods=['POST'])
@login_required
@admin_required
def ban_user(user_id):
    db = get_db()
    u = db.execute('SELECT is_admin, username FROM users WHERE id=?', [user_id]).fetchone()
    if u and not u['is_admin']:
        db.execute('UPDATE users SET is_banned=1 WHERE id=?', [user_id])
        db.commit()
        log_activity(session['user_id'], session['username'], 'ban_user', f'Engellenen: @{u["username"]}', 'user', user_id)
        flash('Kullanıcı engellendi.')
    db.close()
    return redirect(url_for('admin_panel'))


@app.route('/admin/user/<int:user_id>/unban', methods=['POST'])
@login_required
@admin_required
def unban_user(user_id):
    db = get_db()
    u = db.execute('SELECT username FROM users WHERE id=?', [user_id]).fetchone()
    db.execute('UPDATE users SET is_banned=0 WHERE id=?', [user_id])
    db.commit()
    if u:
        log_activity(session['user_id'], session['username'], 'unban_user', f'Engeli kaldırılan: @{u["username"]}', 'user', user_id)
    db.close()
    flash('Kullanıcı engeli kaldırıldı.')
    return redirect(url_for('admin_panel'))


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    db = get_db()
    u = db.execute('SELECT is_admin, username FROM users WHERE id=?', [user_id]).fetchone()
    if u and not u['is_admin']:
        uname = u['username']
        db.execute('DELETE FROM votes WHERE user_id=?', [user_id])
        db.execute('DELETE FROM flags WHERE user_id=?', [user_id])
        db.execute('DELETE FROM nodes WHERE user_id=?', [user_id])
        for t in db.execute('SELECT id FROM topics WHERE user_id=?', [user_id]).fetchall():
            db.execute('DELETE FROM nodes WHERE topic_id=?', [t['id']])
            db.execute('DELETE FROM topics WHERE id=?', [t['id']])
        db.execute('DELETE FROM api_tokens WHERE user_id=?', [user_id])
        db.execute('DELETE FROM users WHERE id=?', [user_id])
        db.commit()
        log_activity(session['user_id'], session['username'], 'delete_user', f'Silinen: @{uname}', 'user', user_id)
        flash('Kullanıcı silindi.')
    db.close()
    return redirect(url_for('admin_panel'))


@app.route('/admin/pikpik/reset', methods=['POST'])
@login_required
@admin_required
def admin_pikpik_reset():
    archive_current_week()
    log_activity(session['user_id'], session['username'], 'pikpik_manual_reset', 'Manuel sıfırlama')
    flash('PikPik tuvali sıfırlandı ve arşivlendi.')
    return redirect(url_for('admin_panel'))


# ═══════════════════════════════════════════════════════════════════════════════
#  HAYKIR
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/haykir')
@login_required
def haykir():
    db = get_db()
    days = db.execute("SELECT DISTINCT day FROM haykir_entries ORDER BY day DESC").fetchall()
    db.close()
    return render_template('haykir.html', days=[d['day'] for d in days], today=date.today().isoformat())

@app.route('/haykir/api/entries')
@login_required
def haykir_entries_api():
    try:
        db = get_db()
        rows = db.execute('''SELECT h.*, u.username FROM haykir_entries h
            JOIN users u ON h.user_id = u.id ORDER BY h.day, h.created_at''').fetchall()
        db.close()
        entries = {}
        for r in rows:
            d = r['day']
            if d not in entries: entries[d] = []
            entries[d].append({
                'id': r['id'], 'x': r['x'], 'y': r['y'],
                'content': r['content'], 'font_size': r['font_size'],
                'color': r['color'], 'direction': r['direction'],
                'font_family': r['font_family'] if 'font_family' in r.keys() else 'Syne',
                'effect': r['effect'] if 'effect' in r.keys() else 'none',
                'shadow': r['shadow'] if 'shadow' in r.keys() else 'none',
                'username': r['username'], 'user_id': r['user_id']
            })
        return jsonify(entries)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/haykir/add', methods=['POST'])
@login_required
def haykir_add():
    try:
        data = request.get_json()
        if not data: return jsonify({'error': 'Veri yok'}), 400
        content = data.get('content', '').strip()
        if not content or len(content) > 200: return jsonify({'error': 'Geçersiz metin'}), 400
        db = get_db()
        db.execute('INSERT INTO haykir_entries (user_id,day,x,y,content,font_size,color,direction,font_family,effect,shadow) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   [session['user_id'], date.today().isoformat(), float(data.get('x',0)), float(data.get('y',0)),
                    content, max(7,min(100,int(data.get('font_size',28)))), data.get('color','#ffffff'),
                    int(data.get('direction',0)), data.get('font_family','Syne'),
                    data.get('effect','none'), data.get('shadow','none')])
        db.commit(); db.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/haykir/update', methods=['POST'])
@login_required
def haykir_update():
    try:
        data = request.get_json()
        entry_id = int(data.get('id', 0))
        db = get_db()
        entry = db.execute('SELECT * FROM haykir_entries WHERE id=?', [entry_id]).fetchone()
        if not entry or entry['user_id'] != session['user_id']:
            db.close(); return jsonify({'error': 'Yetkiniz yok'}), 403
        content = data.get('content', entry['content']).strip()
        if not content or len(content) > 200:
            db.close(); return jsonify({'error': 'Geçersiz metin'}), 400
        db.execute('UPDATE haykir_entries SET content=?,font_size=?,color=?,direction=?,font_family=?,effect=?,shadow=? WHERE id=?',
                   [content, max(7,min(100,int(data.get('font_size',entry['font_size'])))),
                    data.get('color',entry['color']), int(data.get('direction',entry['direction'])),
                    data.get('font_family',entry['font_family'] if 'font_family' in entry.keys() else 'Syne'),
                    data.get('effect',entry['effect'] if 'effect' in entry.keys() else 'none'),
                    data.get('shadow',entry['shadow'] if 'shadow' in entry.keys() else 'none'), entry_id])
        db.commit(); db.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/haykir/delete', methods=['POST'])
@login_required
def haykir_delete():
    try:
        data = request.get_json()
        entry_id = int(data.get('id', 0))
        db = get_db()
        entry = db.execute('SELECT * FROM haykir_entries WHERE id=?', [entry_id]).fetchone()
        if not entry or entry['user_id'] != session['user_id']:
            db.close(); return jsonify({'error': 'Yetkiniz yok'}), 403
        db.execute('DELETE FROM haykir_entries WHERE id=?', [entry_id])
        db.commit(); db.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/haykir/move', methods=['POST'])
@login_required
def haykir_move():
    try:
        data = request.get_json()
        entry_id = int(data.get('id', 0))
        db = get_db()
        entry = db.execute('SELECT * FROM haykir_entries WHERE id=?', [entry_id]).fetchone()
        if not entry or entry['user_id'] != session['user_id']:
            db.close(); return jsonify({'error': 'Yetkiniz yok'}), 403
        db.execute('UPDATE haykir_entries SET x=?, y=? WHERE id=?',
                   [float(data.get('x',0)), float(data.get('y',0)), entry_id])
        db.commit(); db.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
#  PIKPIK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/pikpik')
@login_required
def pikpik():
    db = get_db()
    u = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()
    db.close()
    return render_template('pikpik.html', pik_balance=u['pik_balance'] if u else 0, schedule=get_current_week_info())

@app.route('/pikpik/api/pixels')
@login_required
def pikpik_pixels_api():
    try:
        db = get_db()
        rows = db.execute('''SELECT p.x, p.y, p.color, u.username, p.user_id
            FROM pikpik_pixels p JOIN users u ON p.user_id = u.id''').fetchall()
        db.close()
        return jsonify([{'x': r['x'], 'y': r['y'], 'color': r['color'],
                         'username': r['username'], 'user_id': r['user_id']} for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pikpik/place', methods=['POST'])
@login_required
def pikpik_place():
    try:
        data = request.get_json()
        if not data: return jsonify({'error': 'Veri yok'}), 400
        x = int(data.get('x', -1)); y = int(data.get('y', -1))
        color = data.get('color', '#000000')
        if x < 0 or y < 0 or x >= 100 or y >= 100:
            return jsonify({'error': 'Geçersiz koordinat'}), 400
        db = get_db()
        u = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()
        if not u: db.close(); return jsonify({'error': 'Kullanıcı bulunamadı'}), 400
        existing = db.execute('SELECT user_id FROM pikpik_pixels WHERE x=? AND y=?', [x, y]).fetchone()
        if existing and existing['user_id'] == session['user_id']:
            db.execute('DELETE FROM pikpik_pixels WHERE x=? AND y=?', [x, y])
            db.execute('UPDATE users SET pik_balance = pik_balance + 1 WHERE id=?', [session['user_id']])
            db.commit()
            nb = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()['pik_balance']
            db.close()
            return jsonify({'ok': True, 'action': 'removed', 'balance': nb})
        if u['pik_balance'] < 1:
            db.close(); return jsonify({'error': 'Yeterli pik yok', 'balance': u['pik_balance']}), 400
        db.execute('UPDATE users SET pik_balance = pik_balance - 1 WHERE id=?', [session['user_id']])
        if existing:
            db.execute('UPDATE pikpik_pixels SET user_id=?, color=? WHERE x=? AND y=?', [session['user_id'], color, x, y])
        else:
            db.execute('INSERT INTO pikpik_pixels (user_id, x, y, color) VALUES (?,?,?,?)', [session['user_id'], x, y, color])
        db.commit()
        nb = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()['pik_balance']
        db.close()
        return jsonify({'ok': True, 'action': 'placed', 'balance': nb})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pikpik/balance')
@login_required
def pikpik_balance():
    try:
        db = get_db()
        u = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()
        db.close()
        return jsonify({'balance': u['pik_balance'] if u else 0})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pikpik/archives')
@login_required
def pikpik_archives():
    try:
        db = get_db()
        rows = db.execute('SELECT id, week_start, week_end, created_at FROM pikpik_archives ORDER BY id DESC').fetchall()
        db.close()
        return jsonify([{'id': r['id'], 'week_start': r['week_start'], 'week_end': r['week_end'],
                         'created_at': r['created_at']} for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pikpik/archive/<int:archive_id>')
@login_required
def pikpik_archive_detail(archive_id):
    try:
        db = get_db()
        archive = db.execute('SELECT * FROM pikpik_archives WHERE id=?', [archive_id]).fetchone()
        db.close()
        if not archive: return jsonify({'error': 'Arşiv bulunamadı'}), 404
        return jsonify({'id': archive['id'], 'week_start': archive['week_start'],
                        'week_end': archive['week_end'], 'pixels': json.loads(archive['pixel_data'])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pikpik/schedule')
@login_required
def pikpik_schedule_api():
    try:
        s = get_current_week_info()
        if s:
            return jsonify({'week_start': s['week_start'], 'next_reset': s['next_reset'], 'is_active': bool(s['is_active'])})
        return jsonify({'week_start': None, 'next_reset': None, 'is_active': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════════════════════════════════════

def get_api_user():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else request.args.get('token', '')
    if not token: return None
    db = get_db()
    row = db.execute('SELECT u.* FROM api_tokens t JOIN users u ON t.user_id = u.id WHERE t.token=?', [token]).fetchone()
    db.close()
    return row

@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=?', [username]).fetchone()
        if user and check_password_hash(user['password'], password):
            if user['is_banned']:
                db.close(); return jsonify({'error': 'Hesap engellenmiş'}), 403
            token = secrets.token_hex(32)
            db.execute('DELETE FROM api_tokens WHERE user_id=?', [user['id']])
            db.execute('INSERT INTO api_tokens (user_id, token) VALUES (?,?)', [user['id'], token])
            db.commit(); db.close()
            return jsonify({'token': token, 'user_id': user['id'], 'username': user['username'], 'is_admin': bool(user['is_admin'])})
        db.close()
        return jsonify({'error': 'Kullanıcı adı veya şifre hatalı'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/register', methods=['POST'])
def api_register():
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        if not username or not password or not email:
            return jsonify({'error': 'Tüm alanları doldurun'}), 400
        if len(username) < 3: return jsonify({'error': 'Kullanıcı adı en az 3 karakter'}), 400
        if len(password) < 6: return jsonify({'error': 'Şifre en az 6 karakter'}), 400
        db = get_db()
        try:
            db.execute('INSERT INTO users (username, email, password) VALUES (?,?,?)',
                       [username, email, generate_password_hash(password)])
            db.commit(); db.close()
            return jsonify({'ok': True, 'message': 'Kayıt başarılı'})
        except sqlite3.IntegrityError:
            db.close(); return jsonify({'error': 'Kullanıcı adı veya e-posta zaten alınmış'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/me')
def api_me():
    user = get_api_user()
    if not user: return jsonify({'error': 'Giriş yapılmamış'}), 401
    db = get_db()
    bal = db.execute('SELECT pik_balance FROM users WHERE id=?', [user['id']]).fetchone()
    db.close()
    return jsonify({'user_id': user['id'], 'username': user['username'], 'email': user['email'],
                    'is_admin': bool(user['is_admin']), 'pik_balance': bal['pik_balance'] if bal else 0})

@app.route('/api/check-token')
def api_check_token():
    user = get_api_user()
    if not user: return jsonify({'valid': False}), 401
    return jsonify({'valid': True, 'username': user['username'], 'is_admin': bool(user['is_admin'])})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    if token:
        db = get_db()
        db.execute('DELETE FROM api_tokens WHERE token=?', [token])
        db.commit(); db.close()
    return jsonify({'ok': True})

@app.route('/api/login-from-session', methods=['POST', 'GET'])
def api_login_from_session():
    if 'user_id' not in session: return jsonify({'error': 'Session yok'}), 401
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', [session['user_id']]).fetchone()
    if not user: db.close(); return jsonify({'error': 'Kullanıcı bulunamadı'}), 401
    token = secrets.token_hex(32)
    db.execute('DELETE FROM api_tokens WHERE user_id=?', [user['id']])
    db.execute('INSERT INTO api_tokens (user_id, token) VALUES (?,?)', [user['id'], token])
    db.commit(); db.close()
    return jsonify({'token': token, 'user_id': user['id'], 'username': user['username'], 'is_admin': bool(user['is_admin'])})


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: return redirect(url_for('home'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=?', [username]).fetchone()
        db.close()
        if user and check_password_hash(user['password'], password):
            if user['is_banned']:
                error = 'Hesabınız engellenmiştir.'
            else:
                session.permanent = True
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['is_admin'] = bool(user['is_admin'])
                log_activity(user['id'], user['username'], 'login', 'Giriş yapıldı')
                return redirect(url_for('home'))
        else:
            error = 'Kullanıcı adı veya şifre hatalı.'
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session: return redirect(url_for('home'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        agreed = request.form.get('agreed')
        if not username or not password or not email:
            error = 'Tüm alanları doldurun.'
        elif not agreed:
            error = 'Üyelik sözleşmesini kabul etmelisiniz.'
        elif len(username) < 3:
            error = 'Kullanıcı adı en az 3 karakter olmalı.'
        elif len(password) < 6:
            error = 'Şifre en az 6 karakter olmalı.'
        elif password != confirm:
            error = 'Şifreler eşleşmiyor.'
        else:
            db = get_db()
            try:
                db.execute('INSERT INTO users (username, email, password) VALUES (?,?,?)',
                           [username, email, generate_password_hash(password)])
                db.commit(); db.close()
                log_activity(None, username, 'register', 'Yeni kullanıcı kaydı')
                flash('Kayıt başarılı! Giriş yapabilirsiniz.')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                db.close(); error = 'Bu kullanıcı adı veya e-posta zaten alınmış.'
    return render_template('register.html', error=error)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    error = None; success = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            error = 'E-posta adresinizi girin.'
        else:
            db = get_db()
            user = db.execute('SELECT * FROM users WHERE email=?', [email]).fetchone()
            if user:
                new_pass = ''.join(random.choices(string.digits, k=6))
                db.execute('UPDATE users SET password=? WHERE id=?', [generate_password_hash(new_pass), user['id']])
                db.commit()
                text = f"{PLATFORM_NAME} - Şifre Sıfırlama\n\nYeni şifreniz: {new_pass}\n\nGiriş yaptıktan sonra şifrenizi değiştirmenizi öneririz."
                html = f"""<div style="font-family:monospace;max-width:480px;margin:0 auto;background:#13151a;border-radius:16px;padding:32px;color:#e8e6e1;">
<h2 style="color:#8b5cf6;">Şifre Sıfırlama</h2>
<p style="color:#6b6f7a;">Merhaba @{user['username']},</p>
<p style="color:#6b6f7a;">Yeni şifreniz:</p>
<div style="background:#1a1d24;border:1px solid #2a2e38;border-radius:12px;padding:18px;text-align:center;margin:18px 0;">
<span style="font-size:28px;font-weight:800;letter-spacing:6px;color:#2ecc71;">{new_pass}</span>
</div></div>"""
                send_email(email, f'[{PLATFORM_NAME}] Yeni Şifreniz', text, html)
                log_activity(user['id'], user['username'], 'forgot_password', 'Şifre sıfırlandı')
                success = 'Yeni şifreniz e-posta adresinize gönderildi.'
            else:
                error = 'Bu e-posta adresiyle kayıtlı bir hesap bulunamadı.'
            db.close()
    return render_template('forgot_password.html', error=error, success=success)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_activity(session.get('user_id'), session.get('username'), 'logout', 'Çıkış yapıldı')
    session.clear()
    return redirect(url_for('login'))


# ═══════════════════════════════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    if not os.path.exists(DB):
        init_db()
    migrate_db()
    scheduler_thread = threading.Thread(target=pikpik_scheduler, daemon=True)
    scheduler_thread.start()
    print(f"\n  {PLATFORM_NAME} başlatılıyor...")
    port = 8073
    try:
        print(f"  http://localhost:{port}")
        app.run(debug=False, host='0.0.0.0', port=port)
    except OSError:
        app.run(debug=False, host='0.0.0.0', port=8073)
