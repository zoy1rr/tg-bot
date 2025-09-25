


import os
import json
import time
import threading
import random
import traceback
import sqlite3
from datetime import datetime, timedelta
from urllib import request, parse, error
import os

import os
from dotenv import load_dotenv

load_dotenv()  # .env faylni yuklaydi

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "0") or "0")


DATA_DIR = "database"
DB_PATH = os.path.join(DATA_DIR, "database.db")
FILE_LOCK = threading.Lock()  
DB_LOCK = threading.Lock()



DEFAULT_CONFIG = {
    "bot_token": BOT_TOKEN or "",
    "admins": [int(os.getenv("SUPER_ADMIN_ID", "0"))],
    "required_channels": [],
    "last_update_id": None
}

USERS_FILE = os.path.join(DATA_DIR, "users.json")
QUESTIONS_FILE = os.path.join(DATA_DIR, "questions.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOG_FILE = os.path.join(DATA_DIR, "log.json")
BACKUP_FILE = os.path.join(DATA_DIR, "backup.json")

LBL_NEXT = "Keyingi savol"
LBL_MAIN = "Bosh menyu"
LBL_BACK = "🔙 Orqaga"
LBL_ADMIN = "🛠 Admin panel"

conn = None
cursor = None

def init_db():
    global conn, cursor
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    # Create tables
    with DB_LOCK:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT,
                entry TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT,
                data TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY,
                added_at TEXT,
                added_by INTEGER
            )
        """)
        conn.commit()

    for k, v in DEFAULT_CONFIG.items():
        if get_config(k) is None:
            set_config(k, v)

    try:
        if not db_is_admin(SUPER_ADMIN_ID):
            db_add_admin(SUPER_ADMIN_ID, added_by=SUPER_ADMIN_ID)
            append_log(f"SUPER_ADMIN {SUPER_ADMIN_ID} auto-added to admins table.")
    except Exception:
        pass

def get_config(key):
    with DB_LOCK:
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
    if not row:
        return None
    val = row[0]
    try:
        return json.loads(val)
    except Exception:
        return val

def set_config(key, value):
    sval = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else json.dumps(value)
    with DB_LOCK:
        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, sval))
        conn.commit()

def db_get_admins():
    """Return list of admin IDs (ints)."""
    with DB_LOCK:
        cursor.execute("SELECT admin_id FROM admins ORDER BY admin_id ASC")
        rows = cursor.fetchall()
    return [int(r[0]) for r in rows]

def db_add_admin(admin_id, added_by=None):
    ts = datetime.utcnow().isoformat() + "Z"
    with DB_LOCK:
        try:
            cursor.execute("INSERT OR REPLACE INTO admins (admin_id, added_at, added_by) VALUES (?, ?, ?)",
                           (int(admin_id), ts, int(added_by) if added_by is not None else None))
            conn.commit()
            append_log(f"Admin {admin_id} added by {added_by}")
            return True
        except Exception:
            return False

def db_remove_admin(admin_id):
    with DB_LOCK:
        cursor.execute("DELETE FROM admins WHERE admin_id = ?", (int(admin_id),))
        conn.commit()
        append_log(f"Admin {admin_id} removed")
        return cursor.rowcount > 0

def db_is_admin(user_id):
    try:
        a = int(user_id)
    except Exception:
        return False
    with DB_LOCK:
        cursor.execute("SELECT 1 FROM admins WHERE admin_id = ? LIMIT 1", (a,))
        row = cursor.fetchone()
    return bool(row)

def db_get_all_users_as_dict():
    """Return dict of users keyed by string user_id to mimic old JSON structure."""
    with DB_LOCK:
        cursor.execute("SELECT user_id, data FROM users")
        rows = cursor.fetchall()
    users = {}
    for uid, data in rows:
        try:
            uobj = json.loads(data)
        except Exception:
            uobj = {}
        users[str(uid)] = uobj
    return users

def db_save_user_obj(user_obj):
    uid = int(user_obj["id"])
    data = json.dumps(user_obj, ensure_ascii=False)
    with DB_LOCK:
        cursor.execute("INSERT OR REPLACE INTO users (user_id, data) VALUES (?, ?)", (uid, data))
        conn.commit()

def db_get_user(user_id):
    with DB_LOCK:
        cursor.execute("SELECT data FROM users WHERE user_id = ?", (int(user_id),))
        row = cursor.fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None

def db_delete_user(user_id):
    with DB_LOCK:
        cursor.execute("DELETE FROM users WHERE user_id = ?", (int(user_id),))
        conn.commit()

def db_get_all_questions_as_list():
    with DB_LOCK:
        cursor.execute("SELECT id, data FROM questions ORDER BY id ASC")
        rows = cursor.fetchall()
    qs = []
    for qid, data in rows:
        try:
            qobj = json.loads(data)
        except Exception:
            qobj = {}
        qobj["id"] = qid
        qs.append(qobj)
    return qs

def db_add_question_obj(qobj):
    data = json.dumps(qobj, ensure_ascii=False)
    with DB_LOCK:
        cursor.execute("INSERT INTO questions (data) VALUES (?)", (data,))
        conn.commit()
        qid = cursor.lastrowid
    return qid

def db_delete_question_by_id(qid):
    with DB_LOCK:
        cursor.execute("DELETE FROM questions WHERE id = ?", (int(qid),))
        conn.commit()
        return cursor.rowcount > 0

def db_update_question_id_in_store(qid, qobj):
    data = json.dumps(qobj, ensure_ascii=False)
    with DB_LOCK:
        cursor.execute("UPDATE questions SET data = ? WHERE id = ?", (data, int(qid)))
        conn.commit()

def append_log(entry):
    ts = datetime.utcnow().isoformat() + "Z"
    with DB_LOCK:
        cursor.execute("INSERT INTO logs (time, entry) VALUES (?, ?)", (ts, entry))
        conn.commit()

def get_all_logs():
    with DB_LOCK:
        cursor.execute("SELECT time, entry FROM logs ORDER BY id ASC")
        rows = cursor.fetchall()
    return [{"time": r[0], "entry": r[1]} for r in rows]

def save_backup_snapshot():
    try:
        users = db_get_all_users_as_dict()
        questions = db_get_all_questions_as_list()
        cfg = {}
        with DB_LOCK:
            cursor.execute("SELECT key, value FROM config")
            for k, v in cursor.fetchall():
                try:
                    cfg[k] = json.loads(v)
                except Exception:
                    cfg[k] = v
        data = {
            "users": users,
            "questions": questions,
            "config": cfg,
            "logs": get_all_logs(),
            "time": datetime.utcnow().isoformat() + "Z"
        }
        with DB_LOCK:
            cursor.execute("INSERT INTO backups (time, data) VALUES (?, ?)",
                           (datetime.utcnow().isoformat() + "Z", json.dumps(data, ensure_ascii=False)))
            conn.commit()
        append_log("Auto backup completed")
        notify_admins("Auto backup yaratildi ✅")
    except Exception as e:
        append_log("Backup failed: " + str(e))

def load_json(path):
    """Compatibility wrapper: returns the same structures as old JSON files."""
    if path == USERS_FILE:
        return db_get_all_users_as_dict()
    if path == QUESTIONS_FILE:
        return db_get_all_questions_as_list()
    if path == CONFIG_FILE:
        cfg = {}
        with DB_LOCK:
            cursor.execute("SELECT key, value FROM config")
            rows = cursor.fetchall()
        for k, v in rows:
            try:
                cfg[k] = json.loads(v)
            except Exception:
                cfg[k] = v
        return cfg
    if path == LOG_FILE:
        return get_all_logs()
    if path == BACKUP_FILE:
        with DB_LOCK:
            cursor.execute("SELECT data FROM backups ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0])
        except Exception:
            return {}
    try:
        with FILE_LOCK:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return None

def save_json(path, data):
    """Compatibility wrapper: writes to DB when path corresponds to our replaced JSONs."""
    if path == USERS_FILE:
        if not isinstance(data, dict):
            return
        with DB_LOCK:
            cursor.execute("DELETE FROM users")
            for sid, uobj in data.items():
                try:
                    uid = int(sid)
                except Exception:
                    uid = int(uobj.get("id", 0))
                ud = json.dumps(uobj, ensure_ascii=False)
                cursor.execute("INSERT OR REPLACE INTO users (user_id, data) VALUES (?, ?)", (uid, ud))
            conn.commit()
        return
    if path == QUESTIONS_FILE:
        if not isinstance(data, list):
            return
        with DB_LOCK:
            cursor.execute("DELETE FROM questions")
            for q in data:
                qcopy = dict(q)
                qid = qcopy.pop("id", None)
                dq = json.dumps(qcopy, ensure_ascii=False)
                cursor.execute("INSERT INTO questions (data) VALUES (?)", (dq,))
            conn.commit()
        return
    if path == CONFIG_FILE:
        if not isinstance(data, dict):
            return
        with DB_LOCK:
            cursor.execute("DELETE FROM config")
            for k, v in data.items():
                cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))
            conn.commit()
        return
    if path == LOG_FILE:
        if not isinstance(data, list):
            return
        with DB_LOCK:
            cursor.execute("DELETE FROM logs")
            for entry in data:
                t = entry.get("time", datetime.utcnow().isoformat() + "Z")
                e = entry.get("entry", "")
                cursor.execute("INSERT INTO logs (time, entry) VALUES (?, ?)", (t, e))
            conn.commit()
        return
    if path == BACKUP_FILE:
        with DB_LOCK:
            cursor.execute("INSERT INTO backups (time, data) VALUES (?, ?)", (datetime.utcnow().isoformat() + "Z", json.dumps(data, ensure_ascii=False)))
            conn.commit()
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

BOT_TOKEN = None
API_URL = None

def get_token():
    cfg = load_json(CONFIG_FILE) or DEFAULT_CONFIG
    return (cfg.get("bot_token", DEFAULT_CONFIG["bot_token"]) or "").strip()

def api_request_json(method, payload):
    """ Send POST request with JSON body to Telegram Bot API. Returns parsed JSON response or {'ok': False, 'error': ...}. """
    url = f"{API_URL}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            try:
                return json.loads(text)
            except Exception:
                return {"ok": False, "error": "Invalid JSON response"}
    except error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")
            return json.loads(body)
        except Exception:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def send_message(chat_id, text, reply_markup=None, parse_mode="HTML", disable_web_page_preview=True):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return api_request_json("sendMessage", payload)

def send_photo(chat_id, photo_file_id, caption=None, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "photo": photo_file_id}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return api_request_json("sendPhoto", payload)

def answer_callback(callback_query_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
    if text is not None:
        payload["text"] = text
    return api_request_json("answerCallbackQuery", payload)

def delete_message(chat_id, message_id):
    payload = {"chat_id": chat_id, "message_id": message_id}
    return api_request_json("deleteMessage", payload)

def get_updates(offset=None, timeout=30):
    payload = {"timeout": timeout}
    if offset:
        payload["offset"] = offset
    return api_request_json("getUpdates", payload)

def get_chat_member(chat_id, user_id):
    payload = {"chat_id": chat_id, "user_id": user_id}
    return api_request_json("getChatMember", payload)

def main_reply_keyboard(is_admin=False):
    buttons = [
        [{"text": "🔎 Savol-javobni boshlash"}],
        [{"text": "📝 Imtihonni boshlash"}],
        [{"text": "📊 Statistikam"}, {"text": "🏆 Top-10"}],
        [{"text": "🔄 Savollarni qayta boshlash"}]
    ]
    if is_admin:
        buttons.append([{"text": LBL_ADMIN}])
    return {"keyboard": buttons, "resize_keyboard": True}

def quiz_reply_keyboard():
    return {"keyboard": [[{"text": LBL_NEXT}, {"text": LBL_MAIN}]], "resize_keyboard": True}

def admin_panel_keyboard():
    kb = [
        [{"text": "➕ Savol qo‘shish"}, {"text": "🗑 Savol o‘chirish"}],
        [{"text": "📈 Umumiy statistika"}, {"text": "📣 Foydalanuvchilarga xabar"}],
        [{"text": "🚫 Ban berish"}, {"text": "✅ Bandan olish"}],
        [{"text": "🔗 Majburiy kanal qo‘shish"}, {"text": "❌ Majburiy kanalni o‘chirish"}],
        [{"text": "♻️ Barcha foydalanuvchilar uchun savollarni tiklash"}],
        [{"text": LBL_MAIN}]
    ]
    return {"keyboard": kb, "resize_keyboard": True}

def yes_no_inline(yes_text="Ha", no_text="Yoʻq"):
    return {"inline_keyboard": [[{"text": yes_text, "callback_data": "confirm_yes"}, {"text": no_text, "callback_data": "confirm_no"}]]}

def options_inline_markup(question_obj):
    kb = []
    for optk in ("A", "B", "C", "D"):
        opt_text = question_obj.get("options", {}).get(optk, "")
        label = f"{optk}. {opt_text}"
        cb = f"ans|{question_obj['id']}|{optk}"
        kb.append([{"text": label, "callback_data": cb}])
    return {"inline_keyboard": kb}

def get_user(user_id):
    return db_get_user(user_id)

def save_user_obj(user_obj):
    db_save_user_obj(user_obj)

def ensure_user_exists(from_user):
    """
    If the user does not exist, create and notify admins about new subscriber.
    Returns the user object (existing or newly created).
    """
    users = db_get_all_users_as_dict()
    uid = str(from_user["id"])
    if uid not in users:
        uobj = {
            "id": from_user["id"],
            "username": from_user.get("username"),
            "first_name": from_user.get("first_name"),
            "banned": False,
            "correct": 0,
            "incorrect": 0,
            "exams_taken": 0,
            "exams_passed": 0,
            "exams_failed": 0,
            "answered_questions": 0,
            "state": None,
            "temp": {},
            "exam": None,
            "asked_questions": [],
            "last_question_message_id": None
        }
        db_save_user_obj(uobj)
        append_log(f"New user created: {uobj['id']}")
        try:
            notify_admins(f"🆕 Yangi foydalanuvchi qoʻshildi!\n\nID: <code>{uobj['id']}</code>\nIsmi: {uobj.get('first_name') or '-'}\nUsername: @{uobj.get('username') or '-'}")
        except Exception:
            pass
        return uobj
    else:
        return users[uid]

def add_question(qobj):
    qid = db_add_question_obj(qobj)
    append_log(f"Admin {qobj.get('added_by')} added question id {qid}")
    return qid

def delete_question_by_id(qid):
    ok = db_delete_question_by_id(qid)
    if not ok:
        return False
    users = db_get_all_users_as_dict()
    changed_any = False
    for uid, u in users.items():
        changed = False
        if "asked_questions" in u and qid in u["asked_questions"]:
            u["asked_questions"] = [x for x in u["asked_questions"] if x != qid]
            changed = True
        if u.get("exam") and qid in u["exam"].get("qids", []):
            u["exam"]["qids"] = [x for x in u["exam"]["qids"] if x != qid]
            u["exam"]["total"] = len(u["exam"]["qids"])
            changed = True
        if changed:
            db_save_user_obj(u)
            changed_any = True
    append_log(f"Question {qid} deleted by admin")
    return True

def normalize_channel_token(s):
    if not s:
        return s
    s = s.strip()
    if s.startswith("https://t.me/"):
        s = s.replace("https://t.me/", "")
    if s.startswith("http://t.me/"):
        s = s.replace("http://t.me/", "")
    if s.startswith("t.me/"):
        s = s.replace("t.me/", "")
    if s.startswith("@"):
        return s
    return "@" + s

def is_user_subscribed_all(user_id):
    cfg = load_json(CONFIG_FILE) or DEFAULT_CONFIG
    channels = cfg.get("required_channels", []) or []
    if not channels:
        return True, []
    not_subscribed = []
    for ch in channels:
        chn = normalize_channel_token(ch)
        try:
            res = get_chat_member(chn, user_id)
            if not res.get("ok"):
                not_subscribed.append(chn)
            else:
                status = res["result"].get("status")
                if status not in ("creator", "administrator", "member", "restricted"):
                    not_subscribed.append(chn)
        except Exception:
            not_subscribed.append(chn)
    return (len(not_subscribed) == 0), not_subscribed

def make_subscription_prompt(not_subscribed):
    keys = []
    for ch in not_subscribed:
        uname = ch
        if uname.startswith("@"):
            url = f"https://t.me/{uname[1:]}"
        else:
            url = f"https://t.me/{uname}"
        keys.append([{"text": f"📣 Kanalga o'tish", "url": url}])
    keys.append([{"text": "✅ Men obuna bo'ldim", "callback_data": "check_subs"}])
    return {"inline_keyboard": keys}

def send_question(chat_id, question_obj, mode="practice", user_obj=None):
    """ Sends a question text or photo with inline option buttons. Stores message_id into user_obj['last_question_message_id'] for deletion later. """
    reply_markup = options_inline_markup(question_obj)
    caption = question_obj.get("text", "")
    photo = question_obj.get("image_file_id") or question_obj.get("image_file")  
    sent = None
    try:
        if photo:
            sent = send_photo(chat_id, photo, caption=caption, reply_markup=reply_markup)
        else:
            sent = send_message(chat_id, caption, reply_markup=reply_markup)
    except Exception as e:
        append_log("send_question error: " + str(e))
        sent = None
    try:
        if user_obj is not None:
            if mode == "practice":
                uq = user_obj.get("asked_questions", [])
                if question_obj["id"] not in uq:
                    uq.append(question_obj["id"])
                user_obj["asked_questions"] = uq
            if isinstance(sent, dict) and sent.get("ok") and sent.get("result"):
                msg = sent["result"]
                msg_id = msg.get("message_id")
                user_obj["last_question_message_id"] = msg_id
                save_user_obj(user_obj)
    except Exception:
        pass
    return sent

def record_answer(user_obj, correct):
    if correct:
        user_obj["correct"] = user_obj.get("correct", 0) + 1
    else:
        user_obj["incorrect"] = user_obj.get("incorrect", 0) + 1
    user_obj["answered_questions"] = user_obj.get("answered_questions", 0) + 1
    save_user_obj(user_obj)

def start_exam_for_user(user_obj):
    questions = load_json(QUESTIONS_FILE) or []
    if len(questions) < 20:
        return False, "Imtihon uchun yetarli savol yo'q (kamida 20 ta kerak)."
    qsample = random.sample(questions, 20)
    exam = {
        "qids": [q["id"] for q in qsample],
        "index": 0,
        "errors": 0,
        "start_time": time.time(),
        "max_errors": 2,
        "total": 20
    }
    user_obj["exam"] = exam
    user_obj["state"] = "exam"
    save_user_obj(user_obj)
    append_log(f"User {user_obj['id']} started exam")
    return True, exam

def process_exam_answer(user_obj, qid, chosen_opt):
    exam = user_obj.get("exam")
    if not exam:
        return "Imtihon topilmadi."
    questions = load_json(QUESTIONS_FILE) or []
    q = next((x for x in questions if x.get("id") == qid), None)
    if not q:
        return "Savol topilmadi."
    elapsed = time.time() - exam["start_time"]
    if elapsed > 25 * 60:
        user_obj["exams_taken"] = user_obj.get("exams_taken", 0) + 1
        user_obj["exams_failed"] = user_obj.get("exams_failed", 0) + 1
        user_obj["exam"] = None
        user_obj["state"] = None
        save_user_obj(user_obj)
        append_log(f"User {user_obj['id']} exam failed by timeout")
        return "Vaqt tugadi — imtihondan o‘ta olmadingiz."
    correct = (chosen_opt == q["answer"])
    if not correct:
        exam["errors"] += 1
    record_answer(user_obj, correct)
    exam["index"] += 1
    user_obj["exam"] = exam
    save_user_obj(user_obj)
    if exam["errors"] > exam["max_errors"]:
        user_obj["exams_taken"] = user_obj.get("exams_taken", 0) + 1
        user_obj["exams_failed"] = user_obj.get("exams_failed", 0) + 1
        user_obj["exam"] = None
        user_obj["state"] = None
        save_user_obj(user_obj)
        append_log(f"User {user_obj['id']} exam failed by errors")
        return "Siz maksimal xatoga yetdingiz — Imtihondan o‘ta olmadingiz."
    if exam["index"] >= exam["total"]:
        user_obj["exams_taken"] = user_obj.get("exams_taken", 0) + 1
        user_obj["exams_passed"] = user_obj.get("exams_passed", 0) + 1
        user_obj["exam"] = None
        user_obj["state"] = None
        save_user_obj(user_obj)
        append_log(f"User {user_obj['id']} exam passed")
        return "Tabriklaymiz, imtihondan o‘tdingiz! 🎉"
    else:
        save_user_obj(user_obj)
        return None

def start_practice_for_user(user_obj):
    user_obj["state"] = "practice"
    user_obj["temp"] = {"last_qid": None}
    if "asked_questions" not in user_obj:
        user_obj["asked_questions"] = []
    save_user_obj(user_obj)

def next_practice_question(user_obj):
    questions = load_json(QUESTIONS_FILE) or []
    if not questions:
        return None, "Hozircha savollar mavjud emas."
    asked = set(user_obj.get("asked_questions", []) or [])
    available = [q for q in questions if q.get("id") not in asked]
    if not available:
        return None, "📚 Siz barcha savollarga javob berdingiz! Agar xohlasangiz savollarni qayta boshlashingiz mumkin (🔄 Savollarni qayta boshlash)."
    q = random.choice(available)
    user_obj["temp"]["last_qid"] = q["id"]
    save_user_obj(user_obj)
    return q, None

def broadcast_message(text):
    users = db_get_all_users_as_dict()
    cnt = 0
    for uid, u in users.items():
        if u.get("banned"):
            continue
        try:
            send_message(u["id"], text)
            cnt += 1
        except Exception as e:
            append_log(f"Broadcast send error to {uid}: {e}")
            pass
    append_log(f"Broadcast sent to {cnt} users")
    return cnt

def notify_admins(text):
    """Notify all admins from admins table."""
    admin_ids = db_get_admins()
    for aid in admin_ids:
        try:
            send_message(aid, text)
        except Exception:
            pass

def auto_backup_worker():
    while True:
        try:
            now = datetime.now()
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            time.sleep(wait_seconds + 1)
            save_backup_snapshot()
        except Exception as e:
            append_log("Backup failed in worker: " + str(e))
        time.sleep(60)

def format_user_stats(u):
    return (f"👤 ID: <code>{u['id']}</code>\n"
            f"🧑‍💻 Username: @{u.get('username') if u.get('username') else '—'}\n"
            f"📝 To‘g‘ri javoblar: {u.get('correct',0)}\n"
            f"❌ Noto‘g‘ri javoblar: {u.get('incorrect',0)}\n"
            f"📚 Imtihonlar: {u.get('exams_taken',0)}\n"
            f"✅ O‘tganlar: {u.get('exams_passed',0)}\n"
            f"❌ O‘ta olmaganlar: {u.get('exams_failed',0)}\n"
            )

def format_top10():
    users = db_get_all_users_as_dict() or {}
    lst = list(users.values())
    lst.sort(key=lambda x: x.get("answered_questions", 0), reverse=True)
    top = lst[:10]
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top):
        med = medals[i] if i < 3 else f"{i+1}."
        name = f"@{u['username']}" if u.get("username") else (u.get("first_name") or str(u["id"]))
        lines.append(f"{med} {name} — {u.get('answered_questions',0)} ta javob")
    if not lines:
        return "Hozircha foydalanuvchilar yo'q."
    return "🏆 Top-10 reyting:\n\n" + "\n".join(lines)

def handle_update(update):
    try:
        if "message" in update:
            msg = update["message"]
            chat_id = msg["chat"]["id"]
            from_user = msg.get("from", {})
            text = msg.get("text", "") or ""
            ensure_user_exists(from_user)
            user_obj = get_user(from_user["id"])
            if user_obj is None:
                user_obj = ensure_user_exists(from_user)

            if user_obj.get("banned"):
                return

            cfg_tmp = load_json(CONFIG_FILE) or DEFAULT_CONFIG
            if cfg_tmp.get("bot_token", "").startswith("PUT_YOUR") or not cfg_tmp.get("bot_token"):
                if db_is_admin(from_user["id"]):
                    send_message(from_user["id"], "⚠️ Iltimos DB ichidagi 'bot_token' ga tokeningizni qo'ying va qayta ishga tushiring.")
                return

            # /start
            if text.startswith("/start"):
                send_message(chat_id, "Assalomu alaykum! Avto test botimizga xush kelibsiz! 🌟\n" \
                "" \
                "Bu bot orqali siz:\n" \
                "- 📚 Avtomobil texnikasi bo‘yicha bilimlaringizni sinab ko‘rishingiz,\n" \
                "- 🏆 Testlar orqali reytingingizni oshirishingiz,\n" \
                "- 🎯 Har bir to‘g‘ri javob bilan malakangizni oshirishingiz mumkin.\n" \
                "\n\n" \
                "Admin: @Z_ruziqulovv", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                return

            # subscription check
            subscribed, not_sub = is_user_subscribed_all(from_user["id"])
            if not subscribed:
                kb = make_subscription_prompt(not_sub)
                send_message(chat_id, "Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:", reply_markup=kb)
                return

            # Admin panel shortcut
            if text == LBL_ADMIN:
                if db_is_admin(from_user["id"]):
                    send_message(chat_id, "🛠 Admin panelga xush kelibsiz.", reply_markup=admin_panel_keyboard())
                else:
                    send_message(chat_id, "⛔ Siz admin emassiz.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                return

            # Admin-specific flows
            if db_is_admin(from_user["id"]):
                state = user_obj.get("state")

                # BACK and MAIN handling
                if text == LBL_BACK:
                    user_obj["state"] = None
                    user_obj["temp"] = {}
                    save_user_obj(user_obj)
                    send_message(chat_id, "🔙 Bekor qilindi. Admin panelga qaytildi.", reply_markup=admin_panel_keyboard())
                    return
                if text == LBL_MAIN:
                    user_obj["state"] = None
                    user_obj["temp"] = {}
                    save_user_obj(user_obj)
                    send_message(chat_id, "Asosiy menyuga qaytdingiz.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                    return

                # Multi-step admin flows
                if state and isinstance(state, str) and state.startswith("admin_"):
                    # Add question flow: admin_add_image -> admin_add_text -> admin_add_optA... -> admin_add_answer
                    if state == "admin_add_image":
                        if "photo" in msg:
                            photos = msg.get("photo", [])
                            if photos:
                                user_obj["temp"]["image_file_id"] = photos[-1]["file_id"]
                        elif text.strip().lower() == "skip" or text.strip().lower() == "skip":
                            user_obj["temp"]["image_file_id"] = None
                        else:
                            user_obj["temp"]["image_file_id"] = None
                        user_obj["state"] = "admin_add_text"
                        save_user_obj(user_obj)
                        send_message(chat_id, "Endi savol matnini yuboring:", reply_markup=admin_panel_keyboard())
                        return
                    if state == "admin_add_text":
                        if not text:
                            send_message(chat_id, "Iltimos, savol matnini yuboring.", reply_markup=admin_panel_keyboard())
                            return
                        user_obj["temp"]["text"] = text
                        user_obj["state"] = "admin_add_optA"
                        save_user_obj(user_obj)
                        send_message(chat_id, "Variant A ni yuboring:", reply_markup=admin_panel_keyboard())
                        return
                    if state == "admin_add_optA":
                        if not text:
                            send_message(chat_id, "Iltimos, A variantini yuboring.", reply_markup=admin_panel_keyboard())
                            return
                        user_obj["temp"]["A"] = text
                        user_obj["state"] = "admin_add_optB"
                        save_user_obj(user_obj)
                        send_message(chat_id, "Variant B ni yuboring:", reply_markup=admin_panel_keyboard())
                        return
                    if state == "admin_add_optB":
                        if not text:
                            send_message(chat_id, "Iltimos, B variantini yuboring.", reply_markup=admin_panel_keyboard())
                            return
                        user_obj["temp"]["B"] = text
                        user_obj["state"] = "admin_add_optC"
                        save_user_obj(user_obj)
                        send_message(chat_id, "Variant C ni yuboring:", reply_markup=admin_panel_keyboard())
                        return
                    if state == "admin_add_optC":
                        if not text:
                            send_message(chat_id, "Iltimos, C variantini yuboring.", reply_markup=admin_panel_keyboard())
                            return
                        user_obj["temp"]["C"] = text
                        user_obj["state"] = "admin_add_optD"
                        save_user_obj(user_obj)
                        send_message(chat_id, "Variant D ni yuboring:", reply_markup=admin_panel_keyboard())
                        return
                    if state == "admin_add_optD":
                        if not text:
                            send_message(chat_id, "Iltimos, D variantini yuboring.", reply_markup=admin_panel_keyboard())
                            return
                        user_obj["temp"]["D"] = text
                        user_obj["state"] = "admin_add_answer"
                        save_user_obj(user_obj)
                        send_message(chat_id, "To‘g‘ri javobni belgilang (A/B/C/D):", reply_markup=admin_panel_keyboard())
                        return
                    if state == "admin_add_answer":
                        if not text or text.strip().upper() not in ("A", "B", "C", "D"):
                            send_message(chat_id, "Iltimos, to‘g‘ri javob sifatida A, B, C yoki D ni yuboring.", reply_markup=admin_panel_keyboard())
                            return
                        ans = text.strip().upper()
                        qobj = {
                            "text": user_obj["temp"].get("text"),
                            "options": {
                                "A": user_obj["temp"].get("A"),
                                "B": user_obj["temp"].get("B"),
                                "C": user_obj["temp"].get("C"),
                                "D": user_obj["temp"].get("D")
                            },
                            "answer": ans,
                            "image_file_id": user_obj["temp"].get("image_file_id"),
                            "added_by": user_obj["id"],
                            "added_at": datetime.utcnow().isoformat() + "Z"
                        }
                        qid = add_question(qobj)
                        user_obj["state"] = None
                        user_obj["temp"] = {}
                        save_user_obj(user_obj)
                        send_message(chat_id, f"✅ Savol bazaga qo‘shildi (ID: {qid}).", reply_markup=admin_panel_keyboard())
                        return

                    # Delete question
                    if state == "admin_delete_wait_id":
                        if not text or not text.strip().isdigit():
                            send_message(chat_id, "Iltimos, haqiqiy ID raqamini yuboring.", reply_markup=admin_panel_keyboard())
                            return
                        qid = int(text.strip())
                        ok = delete_question_by_id(qid)
                        user_obj["state"] = None
                        save_user_obj(user_obj)
                        if ok:
                            send_message(chat_id, f"✅ Savol (ID: {qid}) o‘chirildi.", reply_markup=admin_panel_keyboard())
                        else:
                            send_message(chat_id, f"❌ Savol topilmadi (ID: {qid}).", reply_markup=admin_panel_keyboard())
                        return

                    # Broadcast
                    if state == "admin_broadcast_wait_text":
                        cnt = broadcast_message(text)
                        user_obj["state"] = None
                        save_user_obj(user_obj)
                        send_message(chat_id, f"Xabar {cnt} ta foydalanuvchiga yuborildi.", reply_markup=admin_panel_keyboard())
                        return

                    # Ban
                    if state == "admin_ban_wait_id":
                        target = text.strip()
                        users = db_get_all_users_as_dict()
                        target_user = None
                        if target.startswith("@"):
                            for u in users.values():
                                if u.get("username") and ("@" + u.get("username")) == target:
                                    target_user = u
                                    break
                        else:
                            if target.isdigit() and target in users:
                                target_user = users[target]
                        if not target_user:
                            # create minimal banned user if numeric id given
                            if target.isdigit():
                                users[target] = {
                                    "id": int(target),
                                    "username": None,
                                    "first_name": None,
                                    "banned": True,
                                    "correct": 0,
                                    "incorrect": 0,
                                    "exams_taken": 0,
                                    "exams_passed": 0,
                                    "exams_failed": 0,
                                    "answered_questions": 0,
                                    "state": None,
                                    "temp": {},
                                    "exam": None,
                                    "asked_questions": []
                                }
                                save_json(USERS_FILE, users)
                                append_log(f"Admin {user_obj['id']} banned user {target}")
                                user_obj["state"] = None
                                save_user_obj(user_obj)
                                send_message(chat_id, f"✅ Foydalanuvchi ID {target} banlandi.", reply_markup=admin_panel_keyboard())
                                return
                            send_message(chat_id, "Foydalanuvchi topilmadi.", reply_markup=admin_panel_keyboard())
                            return
                        target_user["banned"] = True
                        save_user_obj(target_user)
                        append_log(f"Admin {user_obj['id']} banned user {target_user['id']}")
                        user_obj["state"] = None
                        save_user_obj(user_obj)
                        send_message(chat_id, f"✅ @{target_user.get('username') or target_user['id']} banlandi.", reply_markup=admin_panel_keyboard())
                        return

                    # Unban
                    if state == "admin_unban_wait_id":
                        target = text.strip()
                        users = db_get_all_users_as_dict()
                        target_user = None
                        if target.startswith("@"):
                            for u in users.values():
                                if u.get("username") and ("@" + u.get("username")) == target:
                                    target_user = u
                                    break
                        else:
                            if target.isdigit() and target in users:
                                target_user = users[target]
                        if not target_user:
                            send_message(chat_id, "Foydalanuvchi topilmadi.", reply_markup=admin_panel_keyboard())
                            return
                        target_user["banned"] = False
                        save_user_obj(target_user)
                        append_log(f"Admin {user_obj['id']} unbanned user {target_user['id']}")
                        user_obj["state"] = None
                        save_user_obj(user_obj)
                        send_message(chat_id, f"✅ @{target_user.get('username') or target_user['id']} bandan olinadi.", reply_markup=admin_panel_keyboard())
                        return

                    # Add required channel
                    if state == "admin_add_channel_wait":
                        ch = text.strip()
                        chn = normalize_channel_token(ch)
                        cfg = load_json(CONFIG_FILE) or DEFAULT_CONFIG
                        channels = cfg.get("required_channels", []) or []
                        if chn not in channels:
                            channels.append(chn)
                            cfg["required_channels"] = channels
                            save_json(CONFIG_FILE, cfg)
                            append_log(f"Admin {user_obj['id']} added required channel {chn}")
                            send_message(chat_id, f"✅ {chn} majburiy kanallar ro‘yxatiga qo‘shildi.", reply_markup=admin_panel_keyboard())
                        else:
                            send_message(chat_id, f"{chn} allaqachon mavjud.", reply_markup=admin_panel_keyboard())
                        user_obj["state"] = None
                        save_user_obj(user_obj)
                        return

                    # Remove required channel
                    if state == "admin_del_channel_wait":
                        ch = text.strip()
                        chn = normalize_channel_token(ch)
                        cfg = load_json(CONFIG_FILE) or DEFAULT_CONFIG
                        channels = cfg.get("required_channels", []) or []
                        if chn in channels:
                            channels.remove(chn)
                            cfg["required_channels"] = channels
                            save_json(CONFIG_FILE, cfg)
                            append_log(f"Admin {user_obj['id']} removed required channel {chn}")
                            send_message(chat_id, f"✅ {chn} o‘chirildi.", reply_markup=admin_panel_keyboard())
                        else:
                            send_message(chat_id, f"{chn} topilmadi.", reply_markup=admin_panel_keyboard())
                        user_obj["state"] = None
                        save_user_obj(user_obj)
                        return

                    # fallback admin state reset
                    user_obj["state"] = None
                    user_obj["temp"] = {}
                    save_user_obj(user_obj)
                    send_message(chat_id, "Admin holati bekor qilindi.", reply_markup=admin_panel_keyboard())
                    return

                # No admin state active: accept admin commands
                if text == "➕ Savol qo‘shish":
                    user_obj["state"] = "admin_add_image"
                    user_obj["temp"] = {}
                    save_user_obj(user_obj)
                    send_message(chat_id, "Iltimos, agar rasm qo‘shmoqchi bo‘lsangiz, rasm yuboring. Agar rasm yo‘q bo‘lsa 'Skip' deb yozing.", reply_markup=admin_panel_keyboard())
                    return
                if text == "🗑 Savol o‘chirish":
                    questions = load_json(QUESTIONS_FILE) or []
                    if not questions:
                        send_message(chat_id, "Savollar bazasi bo‘sh.", reply_markup=admin_panel_keyboard())
                        return
                    msg_txt = "Savollarning birinchi 30 tasi:\n\n"
                    for q in questions[:30]:
                        short = q.get("text", "")[:60].replace("\n", " ")
                        msg_txt += f"ID {q['id']}: {short}\n"
                    msg_txt += "\nO‘chirish uchun: ID raqamini yuboring (masalan: 12)"
                    user_obj["state"] = "admin_delete_wait_id"
                    save_user_obj(user_obj)
                    send_message(chat_id, msg_txt, reply_markup=admin_panel_keyboard())
                    return
                if text == "📣 Foydalanuvchilarga xabar":
                    user_obj["state"] = "admin_broadcast_wait_text"
                    save_user_obj(user_obj)
                    send_message(chat_id, "Yuboriladigan xabar matnini yuboring:", reply_markup=admin_panel_keyboard())
                    return
                if text == "🚫 Ban berish":
                    user_obj["state"] = "admin_ban_wait_id"
                    save_user_obj(user_obj)
                    send_message(chat_id, "Ban berish uchun foydalanuvchi ID yoki username yuboring (masalan: 7062038221 yoki @Avto_imtihon_uz):", reply_markup=admin_panel_keyboard())
                    return
                if text == "✅ Bandan olish":
                    user_obj["state"] = "admin_unban_wait_id"
                    save_user_obj(user_obj)
                    send_message(chat_id, "Bandan olish uchun foydalanuvchi ID yoki username yuboring:", reply_markup=admin_panel_keyboard())
                    return
                if text == "🔗 Majburiy kanal qo‘shish":
                    user_obj["state"] = "admin_add_channel_wait"
                    save_user_obj(user_obj)
                    send_message(chat_id, "Kanal username yoki t.me linkini yuboring (masalan: @Avto_imtihon_uz yoki https://t.me/Avto_imtihon_uz):", reply_markup=admin_panel_keyboard())
                    return
                if text == "❌ Majburiy kanalni o‘chirish":
                    cfg = load_json(CONFIG_FILE) or DEFAULT_CONFIG
                    channels = cfg.get("required_channels", []) or []
                    if not channels:
                        send_message(chat_id, "Hech qanday majburiy kanal qo‘shilmagan.", reply_markup=admin_panel_keyboard())
                        return
                    msg = "Majburiy kanallar:\n"
                    for ch in channels:
                        msg += f"{ch}\n"
                    msg += "\nO‘chirish uchun kanal username (masalan: @kanal) ni yuboring:"
                    user_obj["state"] = "admin_del_channel_wait"
                    save_user_obj(user_obj)
                    send_message(chat_id, msg, reply_markup=admin_panel_keyboard())
                    return
                if text == "📈 Umumiy statistika":
                    users = db_get_all_users_as_dict() or {}
                    total = len(users)
                    exams = sum(u.get("exams_taken", 0) for u in users.values())
                    passed = sum(u.get("exams_passed", 0) for u in users.values())
                    failed = sum(u.get("exams_failed", 0) for u in users.values())
                    active = sum(1 for u in users.values() if not u.get("banned"))
                    top = format_top10()
                    msg = (f"📊 Umumiy statistika:\n\n"
                           f"👥 Foydalanuvchilar: {total}\n"
                           f"🧾 Imtihonlar jami: {exams}\n"
                           f"✅ O‘tganlar: {passed}\n"
                           f"❌ O‘ta olmaganlar: {failed}\n"
                           f"🌐 Faol foydalanuvchilar: {active}\n\n{top}")
                    send_message(chat_id, msg, reply_markup=admin_panel_keyboard())
                    return
                if text == "♻️ Barcha foydalanuvchilar uchun savollarni tiklash":
                    users = db_get_all_users_as_dict() or {}
                    for uid, u in users.items():
                        u["asked_questions"] = []
                        save_user_obj(u)
                    append_log(f"Admin {user_obj['id']} reset all asked_questions")
                    send_message(chat_id, "✅ Barcha foydalanuvchilarning savollar tarixi tiklandi.", reply_markup=admin_panel_keyboard())
                    return

                # Additional admin management commands (only SUPER_ADMIN can add/remove admins)
                if text and text.lower().startswith("/addadmin"):
                    # format: /addadmin 123456789
                    parts = text.split()
                    if int(from_user["id"]) != SUPER_ADMIN_ID:
                        send_message(chat_id, "Bu amaliyotni faqat Super Admin bajarishi mumkin.")
                        return
                    if len(parts) != 2 or not parts[1].isdigit():
                        send_message(chat_id, "Foydalanish: /addadmin <user_id>")
                        return
                    target_id = int(parts[1])
                    ok = db_add_admin(target_id, added_by=from_user["id"])
                    if ok:
                        send_message(chat_id, f"✅ Admin qo'shildi: {target_id}", reply_markup=admin_panel_keyboard())
                    else:
                        send_message(chat_id, f"❌ Admin qo'shishda xatolik: {target_id}", reply_markup=admin_panel_keyboard())
                    return
                if text and text.lower().startswith("/deladmin"):
                    parts = text.split()
                    if int(from_user["id"]) != SUPER_ADMIN_ID:
                        send_message(chat_id, "Bu amaliyotni faqat Super Admin bajarishi mumkin.")
                        return
                    if len(parts) != 2 or not parts[1].isdigit():
                        send_message(chat_id, "Foydalanish: /deladmin <user_id>")
                        return
                    target_id = int(parts[1])
                    ok = db_remove_admin(target_id)
                    if ok:
                        send_message(chat_id, f"✅ Admin o'chirildi: {target_id}", reply_markup=admin_panel_keyboard())
                    else:
                        send_message(chat_id, f"❌ Admin topilmadi: {target_id}", reply_markup=admin_panel_keyboard())
                    return

            # Non-admin / user flows
            # Keyingi savol
            if text == LBL_NEXT:
                if user_obj.get("state") == "practice":
                    qn, err = next_practice_question(user_obj)
                    if err:
                        send_message(chat_id, err, reply_markup=quiz_reply_keyboard())
                    else:
                        send_question(chat_id, qn, mode="practice", user_obj=user_obj)
                elif user_obj.get("state") == "exam":
                    exam = user_obj.get("exam")
                    if not exam:
                        send_message(chat_id, "Imtihon holati topilmadi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                        return
                    next_index = exam["index"]
                    questions = load_json(QUESTIONS_FILE) or []
                    if next_index >= len(exam["qids"]):
                        send_message(chat_id, "Imtihon savollari tugadi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                        return
                    qid2 = exam["qids"][next_index]
                    q2 = next((x for x in questions if x.get("id") == qid2), None)
                    if q2:
                        send_question(chat_id, q2, mode="exam", user_obj=user_obj)
                    else:
                        send_message(chat_id, "Keyingi savol topilmadi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                else:
                    send_message(chat_id, "Iltimos, avval 'Savol-javobni boshlash' yoki 'Imtihonni boshlash' tugmasini bosing.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                return

            # Bosh menyu
            if text == LBL_MAIN:
                user_obj["state"] = None
                user_obj["temp"] = {}
                save_user_obj(user_obj)
                send_message(chat_id, "Asosiy menyuga qaytdingiz.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                return

            # Start practice
            if text == "🔎 Savol-javobni boshlash":
                start_practice_for_user(user_obj)
                q, err = next_practice_question(user_obj)
                if err:
                    send_message(chat_id, err, reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                else:
                    send_message(chat_id, "Savollar boshlandi. Variantlardan birini tanlang:", reply_markup=quiz_reply_keyboard())
                    send_question(chat_id, q, mode="practice", user_obj=user_obj)
                return

            # Start exam
            if text == "📝 Imtihonni boshlash":
                ok, res = start_exam_for_user(user_obj)
                if not ok:
                    send_message(chat_id, res, reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                else:
                    exam = res
                    qid = exam["qids"][0]
                    questions = load_json(QUESTIONS_FILE) or []
                    q = next((x for x in questions if x["id"] == qid), None)
                    if q:
                        send_message(chat_id, "Imtihon boshlandi. Yaxshi omad!", reply_markup=quiz_reply_keyboard())
                        send_question(chat_id, q, mode="exam", user_obj=user_obj)
                    else:
                        send_message(chat_id, "Savol topilmadi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                return

            if text == "📊 Statistikam":
                send_message(chat_id, format_user_stats(user_obj), reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                return

            if text == "🏆 Top-10":
                send_message(chat_id, format_top10(), reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                return

            if text == "🔄 Savollarni qayta boshlash":
                user_obj["asked_questions"] = []
                save_user_obj(user_obj)
                send_message(chat_id, "✅ Sizning savollar tarixi tiklandi. Endi savollar boshidan chiqadi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                return

            # Fallback
            send_message(chat_id, "Iltimos, menyudan tugmani tanlang.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))

        # Callback queries (inline buttons)
        elif "callback_query" in update:
            cb = update["callback_query"]
            cid = cb["id"]
            from_user = cb.get("from", {})
            data = cb.get("data", "") or ""
            message = cb.get("message", {}) or {}
            chat_id = message.get("chat", {}).get("id", from_user.get("id"))
            message_id = message.get("message_id")
            ensure_user_exists(from_user)
            user_obj = get_user(from_user["id"])
            if user_obj is None:
                user_obj = ensure_user_exists(from_user)

            # check_subs
            if data == "check_subs":
                subscribed, not_sub = is_user_subscribed_all(from_user["id"])
                if subscribed:
                    answer_callback(cid, text="✅ Obuna tekshirildi.", show_alert=False)
                    send_message(chat_id, "✅ Siz barcha majburiy kanallarga obuna bo‘lgansiz. Endi bot ishlaydi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                    append_log(f"User {from_user['id']} passed subscription check")
                else:
                    answer_callback(cid, text="⚠️ Hali ham obuna emassiz.", show_alert=False)
                    send_message(chat_id, "⚠️ Siz hali ham ba'zi kanallarga obuna bo‘lmagansiz.", reply_markup=make_subscription_prompt(not_sub))
                return

            # Answers: ans|qid|opt
            if data and data.startswith("ans|"):
                parts = data.split("|")
                if len(parts) != 3:
                    answer_callback(cid, text="Callback ma'lumotlari noto'g'ri.", show_alert=False)
                    return
                _, qid_s, opt = parts
                try:
                    qid = int(qid_s)
                except Exception:
                    answer_callback(cid, text="Xato: savol identifikatori noto'g'ri.", show_alert=False)
                    return
                questions = load_json(QUESTIONS_FILE) or []
                q = next((x for x in questions if x.get("id") == qid), None)
                if not q:
                    answer_callback(cid, text="Savol topilmadi.", show_alert=False)
                    return
                correct = (opt == q["answer"])
                try:
                    if correct:
                        answer_callback(cid, text="✅ To'g'ri javob!", show_alert=True)
                    else:
                        answer_callback(cid, text=f"❌ Noto'g'ri. To'g'ri javob: {q['answer']}", show_alert=True)
                except Exception as e:
                    append_log(f"answer_callback error: {e}")

                try:
                    if message_id:
                        delete_message(chat_id, message_id)
                    if user_obj.get("last_question_message_id"):
                        try:
                            delete_message(chat_id, user_obj.get("last_question_message_id"))
                        except Exception:
                            pass
                        user_obj["last_question_message_id"] = None
                        save_user_obj(user_obj)
                except Exception:
                    pass

                # If in practice
                if user_obj.get("state") == "practice":
                    record_answer(user_obj, correct)
                    qn, err = next_practice_question(user_obj)
                    if err:
                        send_message(chat_id, err, reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                    else:
                        send_message(chat_id, "Keyingi savol:", reply_markup=quiz_reply_keyboard())
                        send_question(chat_id, qn, mode="practice", user_obj=user_obj)
                    return

                # If in exam
                elif user_obj.get("state") == "exam":
                    res = process_exam_answer(user_obj, qid, opt)
                    if res is None:
                        exam = user_obj.get("exam")
                        if not exam:
                            send_message(chat_id, "Imtihon holati topilmadi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                            return
                        next_index = exam["index"]
                        if next_index >= len(exam["qids"]):
                            send_message(chat_id, "Imtihon savollari tugadi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                            return
                        qid2 = exam["qids"][next_index]
                        q2 = next((x for x in questions if x.get("id") == qid2), None)
                        if q2:
                            send_message(chat_id, "Keyingi savol:", reply_markup=quiz_reply_keyboard())
                            send_question(chat_id, q2, mode="exam", user_obj=user_obj)
                            return
                        else:
                            send_message(chat_id, "Keyingi savol topilmadi.", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                            return
                    else:
                        send_message(chat_id, res, reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                        try:
                            if "imtihondan o‘tdingiz" in (res or "").lower() or "o‘tdingiz" in (res or "").lower():
                                notify_admins(f"Foydalanuvchi @{user_obj.get('username') or user_obj['id']} imtihondan o‘tdi.")
                        except Exception:
                            pass
                        return

                # fallback: treat as practice
                else:
                    record_answer(user_obj, correct)
                    qn, err = next_practice_question(user_obj)
                    if err:
                        send_message(chat_id, err, reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                    else:
                        send_message(chat_id, "Keyingi savol:", reply_markup=main_reply_keyboard(is_admin=db_is_admin(from_user["id"])))
                        send_question(chat_id, qn, mode="practice", user_obj=user_obj)
                    return

    except Exception as e:
        try:
            append_log("Update handler error: " + str(e) + "\n" + traceback.format_exc())
        except Exception:
            pass

# -------------------- MAIN LOOP --------------------
def run_bot():
    init_db()
    global BOT_TOKEN, API_URL
    cfg = load_json(CONFIG_FILE) or DEFAULT_CONFIG
    BOT_TOKEN = (cfg.get("bot_token") or "").strip()
    if not BOT_TOKEN or BOT_TOKEN.startswith("PUT_YOUR"):
        print("⚠️ Iltimos DB ichidagi 'bot_token' ga bot tokeningizni qo'ying va qayta ishga tushiring.")
        print("Masalan: set_config('bot_token', '123456:ABC-DEF...')  # yoki save_json(CONFIG_FILE, { ... })")
        print("Hozirgi config:", cfg)
        return
    API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
    print("Bot ishga tushdi...")
    append_log("Bot ishga tushdi")

    # start backup thread
    t = threading.Thread(target=auto_backup_worker, daemon=True)
    t.start()

    # main polling loop using getUpdates
    last_update = cfg.get("last_update_id")
    if last_update is None:
        last_update = 0

    while True:
        try:
            updates = get_updates(offset=last_update + 1, timeout=30)
            if not updates or not updates.get("ok"):
                time.sleep(1)
                continue
            for upd in updates.get("result", []):
                last_update = max(last_update, upd["update_id"])
                try:
                    cfg = load_json(CONFIG_FILE) or DEFAULT_CONFIG
                    cfg["last_update_id"] = last_update
                    save_json(CONFIG_FILE, cfg)
                except Exception:
                    pass
                handle_update(upd)
        except Exception as e:
            append_log("Main loop error: " + str(e) + "\n" + traceback.format_exc())
            time.sleep(2)

if __name__ == "__main__":
    run_bot()
