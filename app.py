from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, random, string
from functools import wraps
from datetime import timedelta, date
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'meydan-gizli-anahtar-degistir-2024')
app.permanent_session_lifetime = timedelta(days=30)
DB = 'meydan.db'

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123456'

SMTP_SERVER   = 'smtp.gmail.com'
SMTP_PORT     = 587
SMTP_USER     = 'eemrahkus@gmail.com'
SMTP_PASSWORD = 'kqwv jvrb axks ipid'
NOTIFY_EMAIL  = 'eemrahkus@gmail.com'

FLAG_LABELS = {
    'safsata':    'Safsata',
    'bilim_disi': 'Bilim Dışı',
    'asılsız':    'Asılsız',
    'kaynaksız':  'Kaynaksız',
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

    # Eski tabloları temizle ve sıfırdan oluştur
    conn.executescript('''
        DROP TABLE IF EXISTS flags;
        DROP TABLE IF EXISTS votes;
        DROP TABLE IF EXISTS nodes;
        DROP TABLE IF EXISTS topics;
        DROP TABLE IF EXISTS activity_log;
        DROP TABLE IF EXISTS site_content;
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS haykir_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            content TEXT NOT NULL,
            font_size INTEGER DEFAULT 16,
            color TEXT DEFAULT '#ffffff',
            direction INTEGER DEFAULT 0,
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
    ''')

    # Admin kullanici
    conn.execute(
        "INSERT INTO users (username, email, password, is_admin) VALUES (?,?,?,1)",
        [ADMIN_USERNAME, NOTIFY_EMAIL, generate_password_hash(ADMIN_PASSWORD)]
    )

    # Hakkında
    conn.execute(
        "INSERT INTO site_content (key, title, body) VALUES (?,?,?)",
        ['about', 'Meydan Hakkında',
         'Meydan Nedir?\n'
         '─────────────\n'
         'Meydan, fikirlerin mantıksal çerçevede çarpıştığı, yapılandırılmış bir dijital tartışma platformudur.\n'
         'Geleneksel forum ve sosyal medya platformlarından farklı olarak Meydan, her tartışmayı bir "ağaç" '
         'yapısı altında organize eder. Her fikir Çünkü ile desteklenir, Fakat ile itiraz edilir, '
         'Lakin ile koşullu olarak kabul edilir.\n\n'
         'Misyonumuz\n'
         '──────────\n'
         'Dijital dünyada nitelikli düşünce alışverişini teşvik etmek. Kısa ve provoke edici paylaşımların '
         'hâkim olduğu bir ortamda, Meydan derinlemesine analiz ve saygılı tartışmayı ön plana çıkarmayı hedefler.\n\n'
         'Nasıl Çalışır?\n'
         '──────────────\n'
         '1. Bir kullanıcı "Başlık" (önerme/iddia) oluşturur.\n'
         '2. Diğer kullanıcılar bu başlığa üç farklı şekilde yanıt verir:\n'
         '   • Çünkü — Başlığı destekleyen argümanlar sunar.\n'
         '   • Fakat — Başlığa itiraz eder ve karşıt görüş belirtir.\n'
         '   • Lakin — Başlığa belirli koşullar altında katılır.\n'
         '3. Bu cevaplar da alt dallara ayrılarak derinleşir.\n'
         '4. Her düğüm topluluk tarafından oy alır.\n\n'
         'Platform Özellikleri\n'
         '────────────────────\n'
         '• Üç Görünüm Modu: Klasik (yatay ağaç), Kolay Mod (liste) ve Ağaç (dikey dallanma).\n'
         '• Oylama Sistemi: Her argüman topluluk tarafından yukarı veya aşağı oy alabilir.\n'
         '• Bildirme (Flag) Sistemi: Uygunsuz içerikler altı farklı kategoride bildirilebilir.\n'
         '• Tema Desteği: 7 farklı tema ile platformu kişiselleştirebilirsiniz.\n'
         '• Kullanıcı Profilleri: Her kullanıcının tartışma ve cevap geçmişi görüntülenebilir.\n'
         '• Admin Onay Sistemi: Yeni tartışmalar admin onayından geçerek yayımlanır.\n\n'
         'İçerik Politikası\n'
         '──────────────────\n'
         'Meydan, ifade özgürlüğüne saygılı ancak sorumlu bir tartışma ortamı sunar. Hakaret, nefret söylemi, '
         'spam ve yasadışı içerikler kesinlikle yasaktır. Platform yönetimi, topluluk kalitesini korumak '
         'için gerekli gördüğü müdahaleleri yapma hakkını saklı tutar.\n\n'
         'İletişim\n'
         '────────\n'
         'Sorularınız, önerileriniz veya işbirliği talepleriniz için admin paneli üzerinden '
         'bizimle iletişime geçebilirsiniz.']
    )

    # SSS
    conn.execute(
        "INSERT INTO site_content (key, title, body) VALUES (?,?,?)",
        ['faq', 'Sıkça Sorulan Sorular',
         'Genel\n'
         '─────\n\n'
         'S: Meydan nedir ve nasıl çalışır?\n'
         'C: Meydan, fikirlerin Çünkü, Fakat ve Lakin dallarıyla yapılandırıldığı bir tartışma platformudur. '
         'Bir kullanıcı bir iddia atar, diğerleri bu iddiayı destekler, itiraz eder veya koşullu olarak katılır. '
         'Tüm tartışmalar ağaç yapısı altında organize edilir.\n\n'
         'S: Üye olmak ücretsiz mi?\n'
         'C: Evet, Meydan tamamen ücretsizdir. Kayıt olmak için bir kullanıcı adı, e-posta adresi ve şifre yeterlidir.\n\n'
         'S: Tartışma nasıl başlatılır?\n'
         'C: Ana sayfadaki "Yeni Tartışma Başlat" alanına iddianızı yazıp "Başlat" butonuna tıklayın. '
         'Tartışmanız admin onayından geçtikten sonra yayımlanacaktır.\n\n'
         'S: Çünkü, Fakat, Lakin ne anlama gelir?\n'
         'C: Bunlar Meydan\'ın üç temel etkileşim türüdür:\n'
         '   • Çünkü (Yeşil): Başlığı destekleyen argüman sunar. "Bu doğru çünkü..." şeklinde düşünün.\n'
         '   • Fakat (Kırmızı): Başlığa itiraz eder. "Bu doğru olabilir ama..." şeklinde düşünün.\n'
         '   • Lakin (Sarı): Başlığa belirli koşullar altında katılır. "Katılıyorum, ancak..." şeklinde düşünün.\n\n'
         'S: Cevaplara da cevap verilebilir mi?\n'
         'C: Evet! Her Çünkü, Fakat veya Lakin cevabına tekrar Çünkü, Fakat veya Lakin ile yanıt '
         'verebilirsiniz. Böylece tartışmalar dallanarak derinleşir.\n\n'
         'Hesap\n'
         '─────\n\n'
         'S: Şifremi unuttum, ne yapmalıyım?\n'
         'C: Giriş sayfasındaki "Şifremi Unuttum" bağlantısına tıklayın. Kayıtlı e-posta adresinizi girin, '
         'yeni 6 haneli bir şifre e-posta adresinize gönderilecektir. Giriş yaptıktan sonra şifrenizi '
         'değiştirmenizi öneririz.\n\n'
         'S: Hesabımı nasıl silebilirim?\n'
         'C: Hesap silme işlemi için admin ile iletişime geçmeniz gerekmektedir.\n\n'
         'S: Kullanıcı adımı değiştirebilir miyim?\n'
         'C: Hayır, kullanıcı adı kayıt sırasında belirlenir ve değiştirilemez.\n\n'
         'Tartışma Kuralları\n'
         '──────────────────\n\n'
         'S: Neler paylaşabilirim?\n'
         'C: Topluluk kurallarına uygun, mantıksal çerçevede argümanlar paylaşabilirsiniz. '
         'Her yanıtınız Çünkü, Fakat veya Lakin kategorisinden biri olmalıdır.\n\n'
         'S: Bildirme (Flag) sistemi nasıl çalışır?\n'
         'C: Her tartışmaya veya cevaba "🚩 Bildir" butonu ile aşağıdaki kategorilerde bildirim yapabilirsiniz:\n'
         '   • Safsata: Mantıksal hata içeren argümanlar\n'
         '   • Bilim Dışı: Bilimsel dayanağı olmayan iddialar\n'
         '   • Asılsız: Doğrulanmamış veya yanlış bilgi\n'
         '   • Kaynaksız: Kaynak gösterilmeyen iddialar\n'
         '   • Hakaret: Kişisel saldırı veya aşağılama\n'
         '   • Spam: Reklam veya alakasız içerik\n\n'
         'S: Oylama nasıl çalışır?\n'
         'C: Her tartışmaya ve cevaba oy verebilirsiniz. 👍 yukarı oy (katılıyorum), 👎 aşağı oy '
         '(katılmıyorum) anlamına gelir. Aynı oyu tekrar tıklarsanız oyunuz geri alınır.\n\n'
         'Teknik\n'
         '──────\n\n'
         'S: Görünüm modları nedir?\n'
         'C: Tartışma sayfasında üç farklı görünüm seçebilirsiniz:\n'
         '   • Klasik: Düğümlerin yatay olarak dallandığı geleneksel ağaç görünümü\n'
         '   • Kolay Mod: Düğümlerin listede sıralandığı sade görünüm\n'
         '   • Ağaç: Düğümlerin yukarıdan aşağıya doğru dallandığı dikey ağaç görünümü\n\n'
         'S: Tema nasıl değiştirilir?\n'
         'C: Sağ üst köşedeki tema seçici butonuna tıklayarak 7 farklı tema arasından '
         'seçim yapabilirsiniz: Varsayılan, Karikatür, Windows XP, Windows 98, Doğa, Terminal ve Pastel.\n\n'
         'S: Mobilde kullanabilir miyim?\n'
         'C: Evet, Meydan mobil uyumludur. Mobilde ek olarak Kolay Mod görünümünü kullanarak '
         'daha rahat okuma yapabilirsiniz.']
    )

    # pik_balance sütunu (mevcut DB'ler icin)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN pik_balance INTEGER DEFAULT 50")
    except:
        pass

    conn.commit()
    conn.close()
    print("[DB] Veritabani basariyla olusturuldu.")



# ═══════════════════════════════════════════════════════════════════════════════
#  E-POSTA
# ═══════════════════════════════════════════════════════════════════════════════

def send_email(to_email, subject, text_body, html_body=''):
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[EMAIL] SMTP yapilandirilmamis. -> {to_email}")
        return False

    def _send():
        try:
            msg = MIMEMultipart('alternative')
            msg['From']    = SMTP_USER
            msg['To']      = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
            if html_body:
                msg.attach(MIMEText(html_body, 'html', 'utf-8'))
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
            print(f"[EMAIL] Gonderildi -> {to_email}")
        except Exception as e:
            print(f"[EMAIL] Hata: {e}")

    threading.Thread(target=_send, daemon=True).start()
    return True


def send_notification_email(topic_title, username, topic_id):
    text = (f"Meydan - Yeni Tartisma Bildirimi\n\n"
            f"Baslik: {topic_title}\nKullanici: @{username}\nID: {topic_id}\n\n"
            f"Admin Panel: http://localhost:8071/admin")
    html = f"""<div style="font-family:monospace;max-width:520px;margin:0 auto;background:#13151a;border-radius:16px;padding:32px;color:#e8e6e1;">
<h2 style="color:#8b5cf6;">Yeni Tartisma</h2>
<p style="color:#6b6f7a;">{topic_title}</p>
<p style="color:#6b6f7a;">@{username} #{topic_id}</p>
<a href="http://localhost:8071/admin" style="display:inline-block;background:#8b5cf6;color:#fff;padding:12px 24px;border-radius:10px;text-decoration:none;">Admin Panel</a></div>"""
    send_email(NOTIFY_EMAIL, f'[Meydan] Yeni Tartisma: {topic_title}', text, html)


# ═══════════════════════════════════════════════════════════════════════════════
#  ISLEM GUNLUGU
# ═══════════════════════════════════════════════════════════════════════════════

def log_activity(user_id, username, action, detail='', target_type=None, target_id=None):
    try:
        db = get_db()
        db.execute(
            'INSERT INTO activity_log (user_id,username,action,detail,target_type,target_id) VALUES (?,?,?,?,?,?)',
            [user_id, username, action, detail, target_type, target_id]
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"[LOG] Hata: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

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
            flash('Hesabiniz engellenmistir.')
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
    rows = db.execute(
        "SELECT value, COUNT(*) as c FROM votes WHERE target_type=? AND target_id=? GROUP BY value",
        [target_type, target_id]
    ).fetchall()
    up = down = 0
    for r in rows:
        if r['value'] == 1:
            up = r['c']
        else:
            down = r['c']
    return up, down


def get_user_vote(db, user_id, target_type, target_id):
    r = db.execute(
        "SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?",
        [user_id, target_type, target_id]
    ).fetchone()
    return r['value'] if r else 0


def get_flags(db, target_type, target_id):
    rows = db.execute(
        "SELECT label, COUNT(*) as c FROM flags WHERE target_type=? AND target_id=? GROUP BY label",
        [target_type, target_id]
    ).fetchall()
    return {r['label']: r['c'] for r in rows}

def award_pik(user_id, amount):
    """Kullaniciya pik ver veya al."""
    if not user_id:
        return
    db = get_db()
    db.execute('UPDATE users SET pik_balance = MAX(0, pik_balance + ?) WHERE id=?', [amount, user_id])
    db.commit()
    db.close()


@app.context_processor
def inject_pik():
    """Tum sablolarda pik_balance kullanilabilir."""
    if 'user_id' in session:
        try:
            db = get_db()
            u = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()
            db.close()
            return {'pik_balance': u['pik_balance'] if u else 0}
        except:
            return {'pik_balance': 0}
    return {'pik_balance': 0}

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
        td['up'] = up
        td['down'] = down
        td['user_vote'] = get_user_vote(db, session['user_id'], 'topic', t['id'])
        td['flags'] = get_flags(db, 'topic', t['id'])
        result.append(td)

    pending_count = 0
    if session.get('is_admin'):
        pending_count = db.execute("SELECT COUNT(*) FROM topics WHERE status='pending'").fetchone()[0]
    db.close()
    return render_template('home.html', topics=result, pending_count=pending_count, flag_labels=FLAG_LABELS)


# ═══════════════════════════════════════════════════════════════════════════════
#  VOTE & FLAG
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/vote', methods=['POST'])
@login_required
def vote():
    target_type = request.form.get('target_type')
    target_id   = int(request.form.get('target_id', 0))
    value       = int(request.form.get('value', 0))
    next_url    = request.form.get('next', '/')
    if target_type not in ('topic', 'node') or value not in (1, -1):
        return redirect(next_url)
    db = get_db()
    existing = db.execute(
        "SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?",
        [session['user_id'], target_type, target_id]
    ).fetchone()

    # Icerik sahibini bul (pik icin)
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
            # Ayni oy → toggle kapat
            db.execute("DELETE FROM votes WHERE user_id=? AND target_type=? AND target_id=?",
                       [session['user_id'], target_type, target_id])
            # Yukari oy kaldirildi → -5 pik
            if value == 1 and owner_id and owner_id != session['user_id']:
                db.execute('UPDATE users SET pik_balance = MAX(0, pik_balance - 5) WHERE id=?', [owner_id])
        else:
            # Zit oy → degistir
            db.execute("UPDATE votes SET value=? WHERE user_id=? AND target_type=? AND target_id=?",
                       [value, session['user_id'], target_type, target_id])
            # Down→Up: +5 pik, Up→Down: -5 pik
            if value == 1 and owner_id and owner_id != session['user_id']:
                db.execute('UPDATE users SET pik_balance = pik_balance + 5 WHERE id=?', [owner_id])
            elif value == -1 and old_val == 1 and owner_id and owner_id != session['user_id']:
                db.execute('UPDATE users SET pik_balance = MAX(0, pik_balance - 5) WHERE id=?', [owner_id])
    else:
        # Yeni oy
        db.execute("INSERT INTO votes (user_id,target_type,target_id,value) VALUES (?,?,?,?)",
                   [session['user_id'], target_type, target_id, value])
        # Yeni yukari oy → +5 pik
        if value == 1 and owner_id and owner_id != session['user_id']:
            db.execute('UPDATE users SET pik_balance = pik_balance + 5 WHERE id=?', [owner_id])

    db.commit()
    db.close()
    return redirect(next_url)



@app.route('/flag', methods=['POST'])
@login_required
def flag():
    target_type = request.form.get('target_type')
    target_id   = int(request.form.get('target_id', 0))
    label       = request.form.get('label', '')
    next_url    = request.form.get('next', '/')
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
    db.commit()
    tid = cur.lastrowid
    db.close()
    log_activity(session['user_id'], session['username'], 'new_topic', f'Baslik: {title}', 'topic', tid)
    if not session.get('is_admin'):
        send_notification_email(title, session['username'], tid)
        flash('Tartismaniz admin onayina gonderildi.')
        return redirect(url_for('home'))
    return redirect(url_for('topic', topic_id=tid))


@app.route('/topic/<int:topic_id>')
@login_required
def topic(topic_id):
    db = get_db()
    t = db.execute(
        'SELECT t.*, u.username FROM topics t JOIN users u ON t.user_id=u.id WHERE t.id=?',
        [topic_id]
    ).fetchone()
    if not t:
        db.close()
        return redirect(url_for('home'))
    if t['status'] != 'approved' and not session.get('is_admin'):
        db.close()
        flash('Bu tartisma henuz onaylanmamis.')
        return redirect(url_for('home'))

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
        nd['up'] = up
        nd['down'] = down
        nd['user_vote'] = get_user_vote(db, session['user_id'], 'node', n['id'])
        nd['flags'] = get_flags(db, 'node', n['id'])
        nodes.append(nd)
        node_map[nd['id']] = nd

    topic_dict = dict(t)
    for n in nodes:
        depth = 0
        pid = n.get('parent_id')
        while pid and pid in node_map:
            depth += 1
            pid = node_map[pid].get('parent_id')
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
                           topic_flags=topic_flags, flag_labels=FLAG_LABELS)


@app.route('/topic/<int:topic_id>/reply', methods=['POST'])
@login_required
def add_reply(topic_id):
    db = get_db()
    t = db.execute('SELECT status, user_id FROM topics WHERE id=?', [topic_id]).fetchone()
    if not t or t['status'] != 'approved':
        db.close()
        return redirect(url_for('home'))
    raw = request.form.get('parent_id', '').strip()
    parent_id = int(raw) if raw.isdigit() else None
    node_type = request.form.get('type', '').strip()
    text = request.form.get('text', '').strip()
    if text and node_type in ('cunku', 'fakat', 'lakin'):
        cur = db.execute(
            'INSERT INTO nodes (topic_id,parent_id,type,text,user_id) VALUES (?,?,?,?,?)',
            [topic_id, parent_id, node_type, text, session['user_id']]
        )
        db.commit()
        log_activity(session['user_id'], session['username'], 'new_reply',
                     f'Tur:{node_type}, Metin:{text[:100]}', 'node', cur.lastrowid)

        # Pik odulu: icerik sahibine +1 pik
        if parent_id:
            parent_node = db.execute('SELECT user_id FROM nodes WHERE id=?', [parent_id]).fetchone()
            if parent_node and parent_node['user_id'] != session['user_id']:
                db.execute('UPDATE users SET pik_balance = pik_balance + 1 WHERE id=?',
                           [parent_node['user_id']])
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
        node_ids = [r['id'] for r in db.execute('SELECT id FROM nodes WHERE topic_id=?', [topic_id]).fetchall()]
        for nid in node_ids:
            db.execute('DELETE FROM votes WHERE target_type="node" AND target_id=?', [nid])
            db.execute('DELETE FROM flags WHERE target_type="node" AND target_id=?', [nid])
        db.execute('DELETE FROM nodes WHERE topic_id=?', [topic_id])
        db.execute('DELETE FROM votes WHERE target_type="topic" AND target_id=?', [topic_id])
        db.execute('DELETE FROM flags WHERE target_type="topic" AND target_id=?', [topic_id])
        db.execute('DELETE FROM topics WHERE id=?', [topic_id])
        db.commit()
        log_activity(session['user_id'], session['username'], 'delete_topic',
                     f'Topic #{topic_id}', 'topic', topic_id)
    db.close()
    return redirect(url_for('home'))

@app.route('/node/<int:node_id>/delete', methods=['POST'])
@login_required
def delete_node(node_id):
    db = get_db()
    node = db.execute('SELECT * FROM nodes WHERE id=?', [node_id]).fetchone()
    if not node:
        db.close()
        return redirect(url_for('home'))
    topic_id = node['topic_id']
    if node['user_id'] == session['user_id'] or session.get('is_admin'):
        def del_tree(nid):
            for c in db.execute('SELECT id FROM nodes WHERE parent_id=?', [nid]).fetchall():
                del_tree(c['id'])
            db.execute('DELETE FROM votes WHERE target_type="node" AND target_id=?', [nid])
            db.execute('DELETE FROM flags WHERE target_type="node" AND target_id=?', [nid])
            db.execute('DELETE FROM nodes WHERE id=?', [nid])
        del_tree(node_id)
        db.commit()
        log_activity(session['user_id'], session['username'], 'delete_node',
                     f'Node #{node_id}', 'node', node_id)
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
        log_activity(session['user_id'], session['username'], 'edit_node',
                     f'Node #{node_id}', 'node', node_id)
    topic_id = node['topic_id'] if node else 1
    db.close()
    return redirect(url_for('topic', topic_id=topic_id))


# ═══════════════════════════════════════════════════════════════════════════════
#  PROFIL
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/profile/<username>')
@login_required
def profile(username):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username=?', [username]).fetchone()
    if not user:
        db.close()
        return redirect(url_for('home'))

    uid = user['id']

    topics = db.execute('''
        SELECT t.id, t.title, t.created_at, t.status,
               COUNT(CASE WHEN n.type='cunku' THEN 1 END) as cunku_count,
               COUNT(CASE WHEN n.type='fakat' THEN 1 END) as fakat_count,
               COUNT(CASE WHEN n.type='lakin' THEN 1 END) as lakin_count
        FROM topics t LEFT JOIN nodes n ON n.topic_id = t.id
        WHERE t.user_id=? AND t.status='approved'
        GROUP BY t.id ORDER BY t.created_at DESC
    ''', [uid]).fetchall()

    topic_list = []
    for t in topics:
        td = dict(t)
        up, down = get_vote_counts(db, 'topic', t['id'])
        td['up'] = up
        td['down'] = down
        topic_list.append(td)

    replies = db.execute('''
        SELECT n.id, n.type, n.text, n.created_at, t.id as topic_id, t.title as topic_title
        FROM nodes n JOIN topics t ON n.topic_id = t.id
        WHERE n.user_id=? AND t.status='approved'
        ORDER BY n.created_at DESC LIMIT 50
    ''', [uid]).fetchall()

    reply_list = []
    for r in replies:
        rd = dict(r)
        up, down = get_vote_counts(db, 'node', r['id'])
        rd['up'] = up
        rd['down'] = down
        reply_list.append(rd)

    stats = {
        'topic_count': len(topic_list),
        'reply_count': db.execute('SELECT COUNT(*) FROM nodes WHERE user_id=?', [uid]).fetchone()[0],
        'cunku_count': db.execute("SELECT COUNT(*) FROM nodes WHERE user_id=? AND type='cunku'", [uid]).fetchone()[0],
        'fakat_count': db.execute("SELECT COUNT(*) FROM nodes WHERE user_id=? AND type='fakat'", [uid]).fetchone()[0],
        'lakin_count': db.execute("SELECT COUNT(*) FROM nodes WHERE user_id=? AND type='lakin'", [uid]).fetchone()[0],
    }

    db.close()
    return render_template('profile.html', profile_user=dict(user), topics=topic_list,
                           replies=reply_list, stats=stats, flag_labels=FLAG_LABELS)


# ═══════════════════════════════════════════════════════════════════════════════
#  HAKKINDA
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/about')
@login_required
def about():
    db = get_db()
    items = db.execute('SELECT * FROM site_content ORDER BY id').fetchall()
    db.close()
    return render_template('about.html', items=[dict(i) for i in items])


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    db = get_db()
    users      = db.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    pending    = db.execute('''SELECT t.*, u.username FROM topics t JOIN users u ON t.user_id=u.id
                               WHERE t.status='pending' ORDER BY t.created_at DESC''').fetchall()
    all_topics = db.execute('''SELECT t.*, u.username FROM topics t JOIN users u ON t.user_id=u.id
                               ORDER BY t.created_at DESC''').fetchall()
    activity   = db.execute('SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 300').fetchall()
    site_items = db.execute('SELECT * FROM site_content ORDER BY id').fetchall()
    db.close()
    return render_template('admin.html',
                           users=[dict(u) for u in users],
                           pending=[dict(p) for p in pending],
                           all_topics=[dict(t) for t in all_topics],
                           activity=[dict(a) for a in activity],
                           site_items=[dict(s) for s in site_items])


@app.route('/admin/site-content/<int:item_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_site_content(item_id):
    title = request.form.get('title', '').strip()
    body  = request.form.get('body', '').strip()
    db = get_db()
    db.execute('UPDATE site_content SET title=?, body=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
               [title, body, item_id])
    db.commit()
    db.close()
    log_activity(session['user_id'], session['username'], 'edit_site_content', f'Item #{item_id}')
    flash('Icerik guncellendi.')
    return redirect(url_for('admin_panel'))


@app.route('/admin/site-content/add', methods=['POST'])
@login_required
@admin_required
def add_site_content():
    key   = request.form.get('key', '').strip().replace(' ', '_').lower()
    title = request.form.get('title', '').strip()
    body  = request.form.get('body', '').strip()
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
    db.commit()
    db.close()
    return redirect(url_for('admin_panel'))


@app.route('/admin/topic/<int:topic_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_topic(topic_id):
    db = get_db()
    db.execute("UPDATE topics SET status='approved' WHERE id=?", [topic_id])
    db.commit()
    db.close()
    log_activity(session['user_id'], session['username'], 'approve_topic',
                 f'Topic #{topic_id}', 'topic', topic_id)
    flash('Tartisma onaylandi.')
    return redirect(request.referrer or url_for('admin_panel'))


@app.route('/admin/topic/<int:topic_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_topic(topic_id):
    db = get_db()
    db.execute("UPDATE topics SET status='rejected' WHERE id=?", [topic_id])
    db.commit()
    db.close()
    log_activity(session['user_id'], session['username'], 'reject_topic',
                 f'Topic #{topic_id}', 'topic', topic_id)
    flash('Tartisma reddedildi.')
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
        log_activity(session['user_id'], session['username'], 'ban_user',
                     f'Engellenen: @{u["username"]}', 'user', user_id)
        flash('Kullanici engellendi.')
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
        log_activity(session['user_id'], session['username'], 'unban_user',
                     f'Engeli kaldirilan: @{u["username"]}', 'user', user_id)
    db.close()
    flash('Kullanici engeli kaldirildi.')
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
        db.execute('DELETE FROM users WHERE id=?', [user_id])
        db.commit()
        log_activity(session['user_id'], session['username'], 'delete_user',
                     f'Silinen: @{uname}', 'user', user_id)
        flash('Kullanici silindi.')
    db.close()
    return redirect(url_for('admin_panel'))

# ═══════════════════════════════════════════════════════════════════════════════
#  HAYKIR
# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
#  HAYKIR
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/haykir')
@login_required
def haykir():
    db = get_db()
    days = db.execute(
        "SELECT DISTINCT day FROM haykir_entries ORDER BY day DESC"
    ).fetchall()
    db.close()
    today_str = date.today().isoformat()
    return render_template('haykir.html', days=[d['day'] for d in days], today=today_str)


@app.route('/haykir/api/entries')
@login_required
def haykir_entries_api():
    try:
        db = get_db()
        rows = db.execute('''
            SELECT h.*, u.username FROM haykir_entries h
            JOIN users u ON h.user_id = u.id
            ORDER BY h.day, h.created_at
        ''').fetchall()
        db.close()
        entries = {}
        for r in rows:
            d = r['day']
            if d not in entries:
                entries[d] = []
            entries[d].append({
                'id': r['id'], 'x': r['x'], 'y': r['y'],
                'content': r['content'], 'font_size': r['font_size'],
                'color': r['color'], 'direction': r['direction'],
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
        if not data:
            return jsonify({'error': 'Veri yok'}), 400
        content = data.get('content', '').strip()
        if not content or len(content) > 200:
            return jsonify({'error': 'Gecersiz metin'}), 400
        x = float(data.get('x', 0))
        y = float(data.get('y', 0))
        font_size = max(7, min(100, int(data.get('font_size', 16))))
        color = data.get('color', '#ffffff')
        direction = int(data.get('direction', 0))
        today_str = date.today().isoformat()

        db = get_db()
        db.execute(
            'INSERT INTO haykir_entries (user_id, day, x, y, content, font_size, color, direction) VALUES (?,?,?,?,?,?,?,?)',
            [session['user_id'], today_str, x, y, content, font_size, color, direction]
        )
        db.commit()
        db.close()
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
            db.close()
            return jsonify({'error': 'Yetkiniz yok'}), 403
        content = data.get('content', entry['content']).strip()
        if not content or len(content) > 200:
            db.close()
            return jsonify({'error': 'Gecersiz metin'}), 400
        font_size = max(7, min(100, int(data.get('font_size', entry['font_size']))))
        color = data.get('color', entry['color'])
        direction = int(data.get('direction', entry['direction']))
        db.execute('UPDATE haykir_entries SET content=?, font_size=?, color=?, direction=? WHERE id=?',
                   [content, font_size, color, direction, entry_id])
        db.commit()
        db.close()
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
            db.close()
            return jsonify({'error': 'Yetkiniz yok'}), 403
        db.execute('DELETE FROM haykir_entries WHERE id=?', [entry_id])
        db.commit()
        db.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/haykir/move', methods=['POST'])
@login_required
def haykir_move():
    try:
        data = request.get_json()
        entry_id = int(data.get('id', 0))
        x = float(data.get('x', 0))
        y = float(data.get('y', 0))
        db = get_db()
        entry = db.execute('SELECT * FROM haykir_entries WHERE id=?', [entry_id]).fetchone()
        if not entry or entry['user_id'] != session['user_id']:
            db.close()
            return jsonify({'error': 'Yetkiniz yok'}), 403
        db.execute('UPDATE haykir_entries SET x=?, y=? WHERE id=?', [x, y, entry_id])
        db.commit()
        db.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# ═══════════════════════════════════════════════════════════════════════════════
#  PIKPIK
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
#  PIKPIK
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/pikpik')
@login_required
def pikpik():
    db = get_db()
    u = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()
    db.close()
    balance = u['pik_balance'] if u else 0
    return render_template('pikpik.html', pik_balance=balance)


@app.route('/pikpik/api/pixels')
@login_required
def pikpik_pixels_api():
    try:
        db = get_db()
        rows = db.execute('''
            SELECT p.x, p.y, p.color, u.username, p.user_id
            FROM pikpik_pixels p JOIN users u ON p.user_id = u.id
        ''').fetchall()
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
        if not data:
            return jsonify({'error': 'Veri yok'}), 400
        x = int(data.get('x', -1))
        y = int(data.get('y', -1))
        color = data.get('color', '#000000')
        if x < 0 or y < 0 or x >= 100 or y >= 100:
            return jsonify({'error': 'Gecersiz koordinat'}), 400

        db = get_db()
        u = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()
        if not u:
            db.close()
            return jsonify({'error': 'Kullanici bulunamadi'}), 400

        existing = db.execute('SELECT user_id FROM pikpik_pixels WHERE x=? AND y=?', [x, y]).fetchone()

        # KENDI PIKSELI → SIL (pik kontrolu yok, her zaman iade)
        if existing and existing['user_id'] == session['user_id']:
            db.execute('DELETE FROM pikpik_pixels WHERE x=? AND y=?', [x, y])
            db.execute('UPDATE users SET pik_balance = pik_balance + 1 WHERE id=?', [session['user_id']])
            db.commit()
            new_bal = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()['pik_balance']
            db.close()
            return jsonify({'ok': True, 'action': 'removed', 'balance': new_bal})

        # YENI PIKSEL veya baskasinin pikseli → pik kontrolu
        if u['pik_balance'] < 1:
            db.close()
            return jsonify({'error': 'Yeterli pik yok', 'balance': u['pik_balance']}), 400

        db.execute('UPDATE users SET pik_balance = pik_balance - 1 WHERE id=?', [session['user_id']])
        if existing:
            db.execute('UPDATE pikpik_pixels SET user_id=?, color=? WHERE x=? AND y=?',
                       [session['user_id'], color, x, y])
        else:
            db.execute('INSERT INTO pikpik_pixels (user_id, x, y, color) VALUES (?,?,?,?)',
                       [session['user_id'], x, y, color])
        db.commit()
        new_bal = db.execute('SELECT pik_balance FROM users WHERE id=?', [session['user_id']]).fetchone()['pik_balance']
        db.close()
        return jsonify({'ok': True, 'action': 'placed', 'balance': new_bal})
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


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('home'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=?', [username]).fetchone()
        db.close()
        if user and check_password_hash(user['password'], password):
            if user['is_banned']:
                error = 'Hesabiniz engellenmistir.'
            else:
                session.permanent = True
                session['user_id']  = user['id']
                session['username'] = user['username']
                session['is_admin'] = bool(user['is_admin'])
                log_activity(user['id'], user['username'], 'login', 'Giris yapildi')
                return redirect(url_for('home'))
        else:
            error = 'Kullanici adi veya sifre hatali.'
    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('home'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        agreed   = request.form.get('agreed')
        if not username or not password or not email:
            error = 'Tum alanlari doldurun.'
        elif not agreed:
            error = 'Uyelik sozlesmesini kabul etmelisiniz.'
        elif len(username) < 3:
            error = 'Kullanici adi en az 3 karakter olmali.'
        elif len(password) < 6:
            error = 'Sifre en az 6 karakter olmali.'
        elif password != confirm:
            error = 'Sifrelesmiyor.'
        else:
            db = get_db()
            try:
                db.execute('INSERT INTO users (username, email, password) VALUES (?,?,?)',
                           [username, email, generate_password_hash(password)])
                db.commit()
                db.close()
                log_activity(None, username, 'register', 'Yeni kullanici kaydi')
                flash('Kayit basarili! Giris yapabilirsiniz.')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                db.close()
                error = 'Bu kullanici adi veya e-posta zaten alinmis.'
    return render_template('register.html', error=error)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    error = None
    success = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            error = 'E-posta adresinizi girin.'
        else:
            db = get_db()
            user = db.execute('SELECT * FROM users WHERE email=?', [email]).fetchone()
            if user:
                new_pass = ''.join(random.choices(string.digits, k=6))
                db.execute('UPDATE users SET password=? WHERE id=?',
                           [generate_password_hash(new_pass), user['id']])
                db.commit()
                text = (f"Meydan - Sifre Sifirlama\n\n"
                        f"Yeni sifreniz: {new_pass}\n\n"
                        f"Giris yaptiktan sonra sifrenizi degistirmenizi oneririz.")
                html = f"""<div style="font-family:monospace;max-width:480px;margin:0 auto;background:#13151a;border-radius:16px;padding:32px;color:#e8e6e1;">
<h2 style="color:#8b5cf6;">Sifre Sifirlama</h2>
<p style="color:#6b6f7a;">Merhaba @{user['username']},</p>
<p style="color:#6b6f7a;">Yeni sifreniz:</p>
<div style="background:#1a1d24;border:1px solid #2a2e38;border-radius:12px;padding:18px;text-align:center;margin:18px 0;">
<span style="font-size:28px;font-weight:800;letter-spacing:6px;color:#2ecc71;">{new_pass}</span>
</div>
<p style="color:#6b6f7a;font-size:12px;">Giris yaptiktan sonra sifrenizi degistirmenizi oneririz.</p>
<a href="http://localhost:8071/login" style="display:inline-block;background:#8b5cf6;color:#fff;padding:12px 24px;border-radius:10px;text-decoration:none;">Giris Yap</a></div>"""
                send_email(email, '[Meydan] Yeni Sifreniz', text, html)
                log_activity(user['id'], user['username'], 'forgot_password', 'Sifre sifirlandi')
                success = 'Yeni sifreniz e-posta adresinize gonderildi. Gelen kutunuzu kontrol edin.'
            else:
                error = 'Bu e-posta adresiyle kayitli bir hesap bulunamadi.'
            db.close()
    return render_template('forgot_password.html', error=error, success=success)


@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_activity(session.get('user_id'), session.get('username'), 'logout', 'Cikis yapildi')
    session.clear()
    return redirect(url_for('login'))


# ═══════════════════════════════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    init_db()
    print("\n🚀  Meydan Platformu baslatiliyor...")
    port = 8071
    try:
        print(f"📍  http://localhost:{port}")
        app.run(debug=False, host='0.0.0.0', port=port)
    except OSError:
        app.run(debug=False, host='0.0.0.0', port=8072)
