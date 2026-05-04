import os
import sqlite3
from datetime import datetime, timedelta, date
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g, get_flashed_messages
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ══════ AYARLAR ══════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, 'meydan.db')
app.secret_key = os.environ.get('SECRET_KEY', 'teziskelesi-cok-gizli-anahtar-2024')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ══════ DB YARDIMCILAR ══════
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        theme TEXT DEFAULT 'dark',
        pik_balance INTEGER DEFAULT 50,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL,
        parent_id INTEGER,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (topic_id) REFERENCES topics(id),
        FOREIGN KEY (parent_id) REFERENCES nodes(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        value INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, target_type, target_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS flags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        label TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, target_type, target_id, label)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS site_content (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS haykir_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        x REAL DEFAULT 100,
        y REAL DEFAULT 100,
        content TEXT NOT NULL,
        font_size INTEGER DEFAULT 28,
        color TEXT DEFAULT '#ffffff',
        direction INTEGER DEFAULT 0,
        font_family TEXT DEFAULT 'Syne',
        effect TEXT DEFAULT 'none',
        shadow TEXT DEFAULT 'none',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS pikpik_pixels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        x INTEGER NOT NULL,
        y INTEGER NOT NULL,
        color TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(x, y),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS pikpik_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_start TEXT NOT NULL,
        week_end TEXT NOT NULL,
        next_reset TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS pikpik_archives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_start TEXT NOT NULL,
        week_end TEXT NOT NULL,
        pixel_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        detail TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Varsayılan site_content
    defaults = [
        ('hakkinda', 'Tezİskelesi Nedir?',
         'Tezİskelesi, fikirlerin özgürce çarpıştığı bir dijital tartışma platformudur.\n\n'
         'Burada herkes bir iddia atabilir, ardından diğerleri:\n'
         '• Zira ile destekleyebilir\n'
         '• Gelgelelim ile itiraz edebilir\n'
         '• Yalnız ile koşullu katılabilir\n\n'
         'Fikirler dallanır, büyür ve herkesin görmesi için bir ağaç yapısında sergilenir.'),
        ('kurallar', 'Topluluk Kuralları',
         '1. Saygılı olun — eleştiri fikre, kişiye değil.\n'
         '2. Argümanlarınızı mantıksal çerçevede sunun.\n'
         '3. Hakaret, tehdit ve nefret söylemi yasaktır.\n'
         '4. Spam ve reklam içerikleri silinir.\n'
         '5. Telif hakkı ihlali yapmayın.'),
    ]
    for key, title, body in defaults:
        c.execute('INSERT OR IGNORE INTO site_content (key, title, body) VALUES (?,?,?)',
                  (key, title, body))

    # Admin kullanıcısı yoksa oluştur
    admin = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not admin:
        c.execute('INSERT INTO users (username, email, password, is_admin) VALUES (?,?,?,?)',
                  ('admin', 'admin@teziskelesi.com',
                   generate_password_hash('admin123'), 1))

    # PikPik schedule yoksa oluştur
    sched = c.execute("SELECT id FROM pikpik_schedules").fetchone()
    if not sched:
        today = date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        reset = datetime.combine(end + timedelta(days=1), datetime.min.time())
        c.execute('INSERT INTO pikpik_schedules (week_start, week_end, next_reset) VALUES (?,?,?)',
                  (start.isoformat(), end.isoformat(), reset.isoformat()))

    conn.commit()
    conn.close()

# ══════ DECORATORS ══════
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Lütfen giriş yapın.')
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Admin yetkisi gerekli.')
            return redirect('/')
        return f(*args, **kwargs)
    return decorated

def not_banned(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('user_id'):
            db = get_db()
            u = db.execute('SELECT is_banned FROM users WHERE id=?',
                           [session['user_id']]).fetchone()
            if u and u['is_banned']:
                session.clear()
                flash('Hesabınız engellenmiş.')
                return redirect('/login')
        return f(*args, **kwargs)
    return decorated

# ══════ CONTEXT ══════
@app.context_processor
def inject_globals():
    ctx = {'theme': 'dark', 'pik_balance': 0, 'pending_count': 0}
    if session.get('user_id'):
        db = get_db()
        u = db.execute('SELECT theme, pik_balance FROM users WHERE id=?',
                       [session['user_id']]).fetchone()
        if u:
            ctx['theme'] = u['theme'] or 'dark'
            ctx['pik_balance'] = u['pik_balance'] or 0
        if session.get('is_admin'):
            ctx['pending_count'] = db.execute(
                "SELECT COUNT(*) FROM topics WHERE status='pending'"
            ).fetchone()[0]
    return ctx

# ══════ LOG ══════
def log_activity(action, detail=None):
    try:
        db = get_db()
        uid = session.get('user_id')
        db.execute('INSERT INTO activity_log (user_id, action, detail) VALUES (?,?,?)',
                   [uid, action, detail])
        db.commit()
    except:
        pass

# ══════ HELPERS ══════
FLAG_LABELS = {
    'spam': 'Spam',
    'hakaret': 'Hakaret',
    'tehdit': 'Tehdit',
    'yaniltici': 'Yanıltıcı',
    'diger': 'Diğer'
}

def get_vote_counts(target_type, target_id):
    db = get_db()
    up = db.execute('SELECT COUNT(*) FROM votes WHERE target_type=? AND target_id=? AND value=1',
                    [target_type, target_id]).fetchone()[0]
    down = db.execute('SELECT COUNT(*) FROM votes WHERE target_type=? AND target_id=? AND value=-1',
                      [target_type, target_id]).fetchone()[0]
    return up, down

def get_user_vote(target_type, target_id):
    if not session.get('user_id'):
        return 0
    db = get_db()
    v = db.execute('SELECT value FROM votes WHERE user_id=? AND target_type=? AND target_id=?',
                   [session['user_id'], target_type, target_id]).fetchone()
    return v['value'] if v else 0

def get_flags(target_type, target_id):
    db = get_db()
    rows = db.execute('SELECT label, COUNT(*) as cnt FROM flags WHERE target_type=? AND target_id=? GROUP BY label',
                      [target_type, target_id]).fetchall()
    return {r['label']: r['cnt'] for r in rows}

def build_tree(topic_id):
    db = get_db()
    nodes = db.execute('''
        SELECT n.*, u.username FROM nodes n
        JOIN users u ON n.user_id=u.id
        WHERE n.topic_id=? ORDER BY n.created_at ASC
    ''', [topic_id]).fetchall()

    node_map = {}
    roots = []
    for n in nodes:
        nd = dict(n)
        nd['up'], nd['down'] = get_vote_counts('node', n['id'])
        nd['user_vote'] = get_user_vote('node', n['id'])
        nd['flags'] = get_flags('node', n['id'])
        nd['children'] = []
        node_map[n['id']] = nd

    for n in node_map.values():
        if n['parent_id'] and n['parent_id'] in node_map:
            node_map[n['parent_id']]['children'].append(n)
        else:
            roots.append(n)
    return roots, list(node_map.values())


# ══════════════════════════════════════
#   AUTH ROUTES
# ══════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect('/')
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=?', [username]).fetchone()
        if user and check_password_hash(user['password'], password):
            if user['is_banned']:
                return render_template('login.html', error='Hesabınız engellenmiş.')
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])
            log_activity('login', f'{username} giriş yaptı')
            return redirect('/')
        return render_template('login.html', error='Kullanıcı adı veya şifre hatalı.')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect('/')
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        agreed = request.form.get('agreed')

        if not agreed:
            return render_template('register.html', error='Üyelik sözleşmesini kabul etmelisiniz.')
        if len(username) < 3:
            return render_template('register.html', error='Kullanıcı adı en az 3 karakter olmalı.')
        if len(password) < 6:
            return render_template('register.html', error='Şifre en az 6 karakter olmalı.')
        if password != confirm:
            return render_template('register.html', error='Şifreler eşleşmiyor.')

        db = get_db()
        exists = db.execute('SELECT id FROM users WHERE username=?', [username]).fetchone()
        if exists:
            return render_template('register.html', error='Bu kullanıcı adı alınmış.')

        db.execute('INSERT INTO users (username, email, password) VALUES (?,?,?)',
                   [username, email, generate_password_hash(password)])
        db.commit()
        log_activity('register', f'{username} kayıt oldu')
        flash('Kayıt başarılı! Giriş yapabilirsiniz.')
        return redirect('/login')
    return render_template('register.html')

@app.route('/logout')
def logout():
    log_activity('logout', f'{session.get("username")} çıkış yaptı')
    session.clear()
    return redirect('/login')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        flash('Eğer kayıtlı bir e-posta adresi varsa, sıfırlama bağlantısı gönderildi.')
        log_activity('forgot_password', email)
        return redirect('/login')
    return render_template('forgot_password.html') if os.path.exists(
        os.path.join(BASE_DIR, 'templates', 'forgot_password.html')) else redirect('/login')


# ══════════════════════════════════════
#   ANA SAYFA
# ══════════════════════════════════════

@app.route('/')
@login_required
@not_banned
def home():
    db = get_db()
    topics = db.execute('''
        SELECT t.*, u.username,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='cunku') as cunku_count,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='fakat') as fakat_count,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='lakin') as lakin_count,
            (SELECT COUNT(*) FROM votes WHERE target_type='topic' AND target_id=t.id AND value=1) as up,
            (SELECT COUNT(*) FROM votes WHERE target_type='topic' AND target_id=t.id AND value=-1) as down
        FROM topics t JOIN users u ON t.user_id=u.id
        WHERE t.status='approved' OR t.user_id=?
        ORDER BY t.created_at DESC
    ''', [session['user_id']]).fetchall()

    enriched = []
    for t in topics:
        td = dict(t)
        td['user_vote'] = get_user_vote('topic', t['id'])
        td['flags'] = get_flags('topic', t['id'])
        enriched.append(td)

    pending_count = db.execute("SELECT COUNT(*) FROM topics WHERE status='pending'").fetchone()[0]
    return render_template('home.html', topics=enriched, pending_count=pending_count,
                           flag_labels=FLAG_LABELS)

@app.route('/topic/new', methods=['POST'])
@login_required
@not_banned
def new_topic():
    title = request.form.get('title', '').strip()
    if not title:
        flash('Başlık boş olamaz.')
        return redirect('/')
    db = get_db()
    status = 'approved' if session.get('is_admin') else 'pending'
    db.execute('INSERT INTO topics (user_id, title, status) VALUES (?,?,?)',
               [session['user_id'], title, status])
    db.commit()
    log_activity('new_topic', title)
    flash('Tartışma oluşturuldu!' if status == 'approved' else 'Tartışma admin onayı bekliyor.')
    return redirect('/')


# ══════════════════════════════════════
#   TARTIŞMA DETAY
# ══════════════════════════════════════

@app.route('/topic/<int:tid>')
@login_required
@not_banned
def topic_detail(tid):
    db = get_db()
    topic = db.execute('SELECT t.*, u.username FROM topics t JOIN users u ON t.user_id=u.id WHERE t.id=?',
                       [tid]).fetchone()
    if not topic:
        flash('Tartışma bulunamadı.')
        return redirect('/')

    tree, flat_nodes = build_tree(tid)
    topic_up, topic_down = get_vote_counts('topic', tid)
    topic_user_vote = get_user_vote('topic', tid)
    topic_flags = get_flags('topic', tid)

    # Kolay mod için düz liste
    for n in flat_nodes:
        if n['parent_id']:
            parent = db.execute('SELECT text, type FROM nodes WHERE id=?',
                                [n['parent_id']]).fetchone()
            n['parent_text'] = parent['text'][:60] if parent else ''
            n['parent_type'] = parent['type'] if parent else ''
        else:
            n['parent_text'] = ''
            n['parent_type'] = ''
        n['depth'] = 0
        pid = n['parent_id']
        while pid:
            n['depth'] += 1
            p = db.execute('SELECT parent_id FROM nodes WHERE id=?', [pid]).fetchone()
            pid = p['parent_id'] if p else None

    return render_template('topic.html', topic=topic, tree=tree, nodes=flat_nodes,
                           topic_up=topic_up, topic_down=topic_down,
                           topic_user_vote=topic_user_vote, topic_flags=topic_flags,
                           current_user_id=session['user_id'], flag_labels=FLAG_LABELS)

@app.route('/topic/<int:tid>/reply', methods=['POST'])
@login_required
@not_banned
def reply_topic(tid):
    parent_id = request.form.get('parent_id') or None
    rtype = request.form.get('type', 'cunku')
    text = request.form.get('text', '').strip()
    if not text:
        flash('Cevap boş olamaz.')
        return redirect(f'/topic/{tid}')
    if rtype not in ('cunku', 'fakat', 'lakin'):
        rtype = 'cunku'
    db = get_db()
    db.execute('INSERT INTO nodes (topic_id, parent_id, user_id, type, text) VALUES (?,?,?,?,?)',
               [tid, parent_id if parent_id else None, session['user_id'], rtype, text])
    db.commit()
    log_activity('new_reply', f'Topic #{tid}: {text[:50]}')
    return redirect(f'/topic/{tid}')

@app.route('/topic/<int:tid>/delete', methods=['POST'])
@login_required
def delete_topic(tid):
    db = get_db()
    t = db.execute('SELECT user_id FROM topics WHERE id=?', [tid]).fetchone()
    if not t or (t['user_id'] != session['user_id'] and not session.get('is_admin')):
        flash('Yetkiniz yok.')
        return redirect('/')
    db.execute('DELETE FROM nodes WHERE topic_id=?', [tid])
    db.execute('DELETE FROM topics WHERE id=?', [tid])
    db.commit()
    log_activity('delete_topic', f'Topic #{tid}')
    flash('Tartışma silindi.')
    return redirect('/')

@app.route('/node/<int:nid>/edit', methods=['POST'])
@login_required
def edit_node(nid):
    db = get_db()
    n = db.execute('SELECT * FROM nodes WHERE id=?', [nid]).fetchone()
    if not n or (n['user_id'] != session['user_id'] and not session.get('is_admin')):
        flash('Yetkiniz yok.')
        return redirect('/')
    text = request.form.get('text', '').strip()
    if text:
        db.execute('UPDATE nodes SET text=? WHERE id=?', [text, nid])
        db.commit()
        log_activity('edit_node', f'Node #{nid}')
    return redirect(f'/topic/{n["topic_id"]}')

@app.route('/node/<int:nid>/delete', methods=['POST'])
@login_required
def delete_node(nid):
    db = get_db()
    n = db.execute('SELECT * FROM nodes WHERE id=?', [nid]).fetchone()
    if not n or (n['user_id'] != session['user_id'] and not session.get('is_admin')):
        flash('Yetkiniz yok.')
        return redirect('/')
    tid = n['topic_id']
    db.execute('DELETE FROM nodes WHERE id=?', [nid])
    db.commit()
    log_activity('delete_node', f'Node #{nid}')
    return redirect(f'/topic/{tid}')


# ══════════════════════════════════════
#   OYLAMA
# ══════════════════════════════════════

@app.route('/vote', methods=['POST'])
@login_required
@not_banned
def vote():
    target_type = request.form.get('target_type')
    target_id = int(request.form.get('target_id', 0))
    value = int(request.form.get('value', 0))
    nxt = request.form.get('next', '/')

    if target_type not in ('topic', 'node') or value not in (1, -1):
        return redirect(nxt)

    db = get_db()
    existing = db.execute('SELECT id, value FROM votes WHERE user_id=? AND target_type=? AND target_id=?',
                          [session['user_id'], target_type, target_id]).fetchone()
    if existing:
        if existing['value'] == value:
            db.execute('DELETE FROM votes WHERE id=?', [existing['id']])
        else:
            db.execute('UPDATE votes SET value=? WHERE id=?', [value, existing['id']])
    else:
        db.execute('INSERT INTO votes (user_id, target_type, target_id, value) VALUES (?,?,?,?)',
                   [session['user_id'], target_type, target_id, value])
    db.commit()
    return redirect(nxt)


# ══════════════════════════════════════
#   BAYRAKLAMA
# ══════════════════════════════════════

@app.route('/flag', methods=['POST'])
@login_required
@not_banned
def flag():
    target_type = request.form.get('target_type')
    target_id = int(request.form.get('target_id', 0))
    label = request.form.get('label', 'diger')
    nxt = request.form.get('next', '/')

    if target_type not in ('topic', 'node') or label not in FLAG_LABELS:
        return redirect(nxt)

    db = get_db()
    try:
        db.execute('INSERT INTO flags (user_id, target_type, target_id, label) VALUES (?,?,?,?)',
                   [session['user_id'], target_type, target_id, label])
        db.commit()
        flash('Bildirim gönderildi.')
    except sqlite3.IntegrityError:
        flash('Zaten bildirdiniz.')
    return redirect(nxt)


# ══════════════════════════════════════
#   PROFİL
# ══════════════════════════════════════

@app.route('/profile/<username>')
@login_required
@not_banned
def profile(username):
    db = get_db()
    profile_user = db.execute('SELECT * FROM users WHERE username=?', [username]).fetchone()
    if not profile_user:
        flash('Kullanıcı bulunamadı.')
        return redirect('/')

    uid = profile_user['id']

    topics = db.execute('''
        SELECT t.*,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='cunku') as cunku_count,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='fakat') as fakat_count,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='lakin') as lakin_count,
            (SELECT COUNT(*) FROM votes WHERE target_type='topic' AND target_id=t.id AND value=1) as up,
            (SELECT COUNT(*) FROM votes WHERE target_type='topic' AND target_id=t.id AND value=-1) as down
        FROM topics t WHERE t.user_id=? AND t.status='approved'
        ORDER BY t.created_at DESC
    ''', [uid]).fetchall()

    replies = db.execute('''
        SELECT n.*, t.title as topic_title, t.id as topic_id,
            (SELECT COUNT(*) FROM votes WHERE target_type='node' AND target_id=n.id AND value=1) as up,
            (SELECT COUNT(*) FROM votes WHERE target_type='node' AND target_id=n.id AND value=-1) as down
        FROM nodes n JOIN topics t ON n.topic_id=t.id
        WHERE n.user_id=? ORDER BY n.created_at DESC
    ''', [uid]).fetchall()

    haykir_entries = db.execute('''
        SELECT * FROM haykir_entries WHERE user_id=?
        ORDER BY day DESC, id DESC
    ''', [uid]).fetchall()

    pik_entries = db.execute('''
        SELECT * FROM pikpik_pixels WHERE user_id=?
        ORDER BY id DESC
    ''', [uid]).fetchall()

    stats = {
        'topic_count': len(topics),
        'reply_count': len(replies),
        'cunku_count': sum(1 for r in replies if r['type'] == 'cunku'),
        'fakat_count': sum(1 for r in replies if r['type'] == 'fakat'),
        'lakin_count': sum(1 for r in replies if r['type'] == 'lakin'),
        'haykir_count': len(haykir_entries),
        'pik_count': len(pik_entries),
    }

    return render_template('profile.html', profile_user=profile_user,
                           topics=topics, replies=replies,
                           haykir_entries=haykir_entries, pik_entries=pik_entries,
                           stats=stats)


# ══════════════════════════════════════
#   HAYKIR
# ══════════════════════════════════════

@app.route('/haykir')
@login_required
@not_banned
def haykir_page():
    return render_template('haykir.html')

@app.route('/haykir/api/entries')
@login_required
def haykir_api():
    db = get_db()
    rows = db.execute('''
        SELECT h.*, u.username FROM haykir_entries h
        JOIN users u ON h.user_id=u.id
        ORDER BY h.day DESC, h.id DESC
    ''').fetchall()
    grouped = {}
    for r in rows:
        day = r['day']
        if day not in grouped:
            grouped[day] = []
        grouped[day].append({
            'id': r['id'], 'user_id': r['user_id'], 'username': r['username'],
            'content': r['content'], 'x': r['x'], 'y': r['y'],
            'font_size': r['font_size'], 'color': r['color'],
            'direction': r['direction'], 'font_family': r['font_family'],
            'effect': r['effect'], 'shadow': r['shadow']
        })
    return jsonify(grouped)

@app.route('/haykir/add', methods=['POST'])
@login_required
@not_banned
def haykir_add():
    data = request.get_json()
    if not data or not data.get('content', '').strip():
        return jsonify({'error': 'Metin boş olamaz'}), 400
    content = data['content'][:200]
    db = get_db()
    db.execute('''
        INSERT INTO haykir_entries (user_id, day, x, y, content, font_size, color, direction, font_family, effect, shadow)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    ''', [session['user_id'], date.today().isoformat(),
          data.get('x', 100), data.get('y', 100), content,
          data.get('font_size', 28), data.get('color', '#ffffff'),
          data.get('direction', 0), data.get('font_family', 'Syne'),
          data.get('effect', 'none'), data.get('shadow', 'none')])
    db.commit()
    log_activity('new_haykir', content[:50])
    return jsonify({'ok': True})

@app.route('/haykir/move', methods=['POST'])
@login_required
@not_banned
def haykir_move():
    data = request.get_json()
    db = get_db()
    entry = db.execute('SELECT user_id FROM haykir_entries WHERE id=?',
                       [data.get('id')]).fetchone()
    if not entry or entry['user_id'] != session['user_id']:
        return jsonify({'error': 'Yetkiniz yok'}), 403
    db.execute('UPDATE haykir_entries SET x=?, y=? WHERE id=?',
               [data.get('x', 0), data.get('y', 0), data['id']])
    db.commit()
    return jsonify({'ok': True})

@app.route('/haykir/edit', methods=['POST'])
@login_required
@not_banned
def haykir_edit():
    data = request.get_json()
    db = get_db()
    entry = db.execute('SELECT user_id FROM haykir_entries WHERE id=?',
                       [data.get('id')]).fetchone()
    if not entry or entry['user_id'] != session['user_id']:
        return jsonify({'error': 'Yetkiniz yok'}), 403
    db.execute('''
        UPDATE haykir_entries SET content=?, font_size=?, color=?, direction=?,
        font_family=?, effect=?, shadow=? WHERE id=?
    ''', [data.get('content', '')[:200], data.get('font_size', 28),
          data.get('color', '#ffffff'), data.get('direction', 0),
          data.get('font_family', 'Syne'), data.get('effect', 'none'),
          data.get('shadow', 'none'), data['id']])
    db.commit()
    log_activity('edit_haykir', f"#{data['id']}")
    return jsonify({'ok': True})

@app.route('/haykir/delete', methods=['POST'])
@login_required
@not_banned
def haykir_delete():
    data = request.get_json()
    db = get_db()
    entry = db.execute('SELECT user_id FROM haykir_entries WHERE id=?',
                       [data.get('id')]).fetchone()
    if not entry or entry['user_id'] != session['user_id']:
        return jsonify({'error': 'Yetkiniz yok'}), 403
    db.execute('DELETE FROM haykir_entries WHERE id=?', [data['id']])
    db.commit()
    log_activity('delete_haykir', f"#{data['id']}")
    return jsonify({'ok': True})


# ══════════════════════════════════════
#   PIKPIK
# ══════════════════════════════════════

@app.route('/pikpik')
@login_required
@not_banned
def pikpik_page():
    db = get_db()
    u = db.execute('SELECT pik_balance FROM users WHERE id=?',
                   [session['user_id']]).fetchone()
    return render_template('pikpik.html', pik_balance=u['pik_balance'] if u else 0)

@app.route('/pikpik/api/pixels')
@login_required
def pikpik_pixels():
    db = get_db()
    rows = db.execute('''
        SELECT p.*, u.username FROM pikpik_pixels p
        JOIN users u ON p.user_id=u.id
    ''').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/pikpik/place', methods=['POST'])
@login_required
@not_banned
def pikpik_place():
    data = request.get_json()
    x, y = data.get('x', 0), data.get('y', 0)
    color = data.get('color', '#000000')
    db = get_db()
    u = db.execute('SELECT pik_balance FROM users WHERE id=?',
                   [session['user_id']]).fetchone()

    existing = db.execute('SELECT id, user_id FROM pikpik_pixels WHERE x=? AND y=?', [x, y]).fetchone()

    if existing:
        if existing['user_id'] == session['user_id']:
            db.execute('DELETE FROM pikpik_pixels WHERE id=?', [existing['id']])
            db.execute('UPDATE users SET pik_balance=pik_balance+1 WHERE id=?',
                       [session['user_id']])
            db.commit()
            new_bal = db.execute('SELECT pik_balance FROM users WHERE id=?',
                                 [session['user_id']]).fetchone()['pik_balance']
            return jsonify({'ok': True, 'action': 'removed', 'balance': new_bal})
        else:
            return jsonify({'error': 'Bu piksel başkasına ait'}), 400

    if u['pik_balance'] <= 0:
        return jsonify({'error': 'Pik bakiyeniz yetersiz'}), 400

    try:
        db.execute('INSERT INTO pikpik_pixels (user_id, x, y, color) VALUES (?,?,?,?)',
                   [session['user_id'], x, y, color])
        db.execute('UPDATE users SET pik_balance=pik_balance-1 WHERE id=?',
                   [session['user_id']])
        db.commit()
        new_bal = db.execute('SELECT pik_balance FROM users WHERE id=?',
                             [session['user_id']]).fetchone()['pik_balance']
        return jsonify({'ok': True, 'action': 'placed', 'balance': new_bal})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Bu piksel dolu'}), 400

@app.route('/pikpik/schedule')
@login_required
def pikpik_schedule():
    db = get_db()
    s = db.execute('SELECT * FROM pikpik_schedules ORDER BY id DESC LIMIT 1').fetchone()
    if not s:
        return jsonify({})
    return jsonify({
        'week_start': s['week_start'],
        'week_end': s['week_end'],
        'next_reset': s['next_reset']
    })

@app.route('/pikpik/archives')
@login_required
def pikpik_archives():
    db = get_db()
    rows = db.execute('SELECT * FROM pikpik_archives ORDER BY id DESC').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/pikpik/archive/<int:aid>')
@login_required
def pikpik_archive_detail(aid):
    db = get_db()
    arch = db.execute('SELECT * FROM pikpik_archives WHERE id=?', [aid]).fetchone()
    if not arch:
        return jsonify({'pixels': []})
    import json
    pixels = json.loads(arch['pixel_data']) if arch['pixel_data'] else []
    return jsonify({'pixels': pixels})


# ══════════════════════════════════════
#   ABOUT
# ══════════════════════════════════════

@app.route('/about')
@login_required
def about():
    db = get_db()
    items = db.execute('SELECT * FROM site_content ORDER BY id ASC').fetchall()
    return render_template('about.html', items=items)


# ══════════════════════════════════════
#   TEMA
# ══════════════════════════════════════

@app.route('/api/set-theme', methods=['POST'])
@login_required
def set_theme():
    data = request.get_json()
    theme = data.get('theme', 'dark')
    valid = ['dark', 'terminal', 'pastel', 'doga', 'karikatur']
    if theme not in valid:
        theme = 'dark'
    db = get_db()
    db.execute('UPDATE users SET theme=? WHERE id=?', [theme, session['user_id']])
    db.commit()
    return jsonify({'ok': True})


# ══════════════════════════════════════
#   ADMIN PANEL
# ══════════════════════════════════════

@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    db = get_db()
    all_topics = db.execute('''
        SELECT t.*, u.username,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='cunku') as cunku_count,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='fakat') as fakat_count,
            (SELECT COUNT(*) FROM nodes WHERE topic_id=t.id AND type='lakin') as lakin_count
        FROM topics t JOIN users u ON t.user_id=u.id
        ORDER BY t.created_at DESC
    ''').fetchall()

    users = db.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    pending = [t for t in all_topics if t['status'] == 'pending']
    site_items = db.execute('SELECT * FROM site_content ORDER BY id').fetchall()
    activity = db.execute('''
        SELECT a.*, u.username FROM activity_log a
        LEFT JOIN users u ON a.user_id=u.id
        ORDER BY a.created_at DESC LIMIT 200
    ''').fetchall()

    haykir_entries = db.execute('''
        SELECT h.*, u.username FROM haykir_entries h
        JOIN users u ON h.user_id=u.id ORDER BY h.day DESC, h.id DESC
    ''').fetchall()

    pik_entries = db.execute('''
        SELECT p.*, u.username FROM pikpik_pixels p
        JOIN users u ON p.user_id=u.id ORDER BY p.id DESC LIMIT 500
    ''').fetchall()

    haykir_count = db.execute('SELECT COUNT(*) FROM haykir_entries').fetchone()[0]
    pik_count = db.execute('SELECT COUNT(*) FROM pikpik_pixels').fetchone()[0]

    return render_template('admin.html',
        all_topics=all_topics, users=users, pending=pending,
        site_items=site_items, activity=activity,
        haykir_entries=haykir_entries, pik_entries=pik_entries,
        haykir_count=haykir_count, pik_count=pik_count)

@app.route('/admin/topic/<int:tid>/approve', methods=['POST'])
@login_required
@admin_required
def admin_approve_topic(tid):
    db = get_db()
    db.execute("UPDATE topics SET status='approved' WHERE id=?", [tid])
    db.commit()
    log_activity('approve_topic', f'Topic #{tid}')
    flash('Tartışma onaylandı.')
    return redirect('/admin')

@app.route('/admin/topic/<int:tid>/reject', methods=['POST'])
@login_required
@admin_required
def admin_reject_topic(tid):
    db = get_db()
    db.execute("UPDATE topics SET status='rejected' WHERE id=?", [tid])
    db.commit()
    log_activity('reject_topic', f'Topic #{tid}')
    flash('Tartışma reddedildi.')
    return redirect('/admin')

@app.route('/admin/user/<int:uid>/ban', methods=['POST'])
@login_required
@admin_required
def admin_ban_user(uid):
    db = get_db()
    db.execute('UPDATE users SET is_banned=1 WHERE id=?', [uid])
    db.commit()
    log_activity('ban_user', f'User #{uid}')
    flash('Kullanıcı engellendi.')
    return redirect('/admin')

@app.route('/admin/user/<int:uid>/unban', methods=['POST'])
@login_required
@admin_required
def admin_unban_user(uid):
    db = get_db()
    db.execute('UPDATE users SET is_banned=0 WHERE id=?', [uid])
    db.commit()
    log_activity('unban_user', f'User #{uid}')
    flash('Engel kaldırıldı.')
    return redirect('/admin')

@app.route('/admin/user/<int:uid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(uid):
    db = get_db()
    u = db.execute('SELECT username, is_admin FROM users WHERE id=?', [uid]).fetchone()
    if u and u['is_admin']:
        flash('Admin kullanıcı silinemez.')
        return redirect('/admin')
    db.execute('DELETE FROM nodes WHERE user_id=?', [uid])
    db.execute('DELETE FROM topics WHERE user_id=?', [uid])
    db.execute('DELETE FROM haykir_entries WHERE user_id=?', [uid])
    db.execute('DELETE FROM pikpik_pixels WHERE user_id=?', [uid])
    db.execute('DELETE FROM votes WHERE user_id=?', [uid])
    db.execute('DELETE FROM flags WHERE user_id=?', [uid])
    db.execute('DELETE FROM users WHERE id=?', [uid])
    db.commit()
    log_activity('delete_user', f'{u["username"] if u else uid}')
    flash('Kullanıcı silindi.')
    return redirect('/admin')

@app.route('/admin/haykir/<int:eid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_haykir(eid):
    db = get_db()
    db.execute('DELETE FROM haykir_entries WHERE id=?', [eid])
    db.commit()
    log_activity('delete_haykir', f'Haykırış #{eid}')
    flash('Haykırış silindi.')
    return redirect('/admin')

@app.route('/admin/pikpik/<int:pid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_pik(pid):
    db = get_db()
    db.execute('DELETE FROM pikpik_pixels WHERE id=?', [pid])
    db.commit()
    log_activity('delete_pik', f'Piksel #{pid}')
    flash('Piksel silindi.')
    return redirect('/admin')

@app.route('/admin/pikpik/clear', methods=['POST'])
@login_required
@admin_required
def admin_clear_pikpik():
    db = get_db()
    count = db.execute('SELECT COUNT(*) FROM pikpik_pixels').fetchone()[0]
    db.execute('DELETE FROM pikpik_pixels')
    db.commit()
    log_activity('clear_pikpik', f'{count} piksel sıfırlandı')
    flash(f'{count} piksel sıfırlandı.')
    return redirect('/admin')

@app.route('/admin/site-content/add', methods=['POST'])
@login_required
@admin_required
def admin_add_site_content():
    key = request.form.get('key', '').strip()
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '')
    if not key or not title:
        flash('Anahtar ve başlık zorunludur.')
        return redirect('/admin')
    db = get_db()
    if db.execute('SELECT id FROM site_content WHERE key=?', [key]).fetchone():
        flash(f'"{key}" anahtarı zaten mevcut.')
        return redirect('/admin')
    db.execute('INSERT INTO site_content (key, title, body) VALUES (?,?,?)', [key, title, body])
    db.commit()
    log_activity('add_site_content', title)
    flash(f'"{title}" eklendi.')
    return redirect('/admin')

@app.route('/admin/site-content/<int:sid>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_site_content(sid):
    title = request.form.get('title', '').strip()
    body = request.form.get('body', '')
    db = get_db()
    db.execute('UPDATE site_content SET title=?, body=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
               [title, body, sid])
    db.commit()
    log_activity('edit_site_content', title)
    flash(f'"{title}" güncellendi.')
    return redirect('/admin')

@app.route('/admin/site-content/<int:sid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_site_content(sid):
    db = get_db()
    item = db.execute('SELECT title FROM site_content WHERE id=?', [sid]).fetchone()
    db.execute('DELETE FROM site_content WHERE id=?', [sid])
    db.commit()
    log_activity('delete_site_content', item['title'] if item else str(sid))
    flash('İçerik silindi.')
    return redirect('/admin')


# ══════════════════════════════════════
#   BAŞLAT
# ══════════════════════════════════════

init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
