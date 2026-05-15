import hashlib, struct, xml.etree.ElementTree as ET, time, json, sqlite3
import re, uuid, os, base64, threading
import requests as http_requests
import dashscope
from dashscope import MultiModalConversation
from flask import (Flask, request, send_from_directory, session,
                   redirect, make_response, render_template, jsonify, url_for, g)
from werkzeug.security import generate_password_hash, check_password_hash
from openpyxl import Workbook
from openpyxl.styles import Font
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

load_dotenv()  # load .env file

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "xcst_v2_2026_secret")

# ── Config (from .env) ────────────────────────────────────────────
WECHAT_TOKEN           = os.environ.get("WECHAT_TOKEN", "")
WECHAT_APPID           = os.environ.get("WECHAT_APPID", "")
WECHAT_APPSECRET       = os.environ.get("WECHAT_APPSECRET", "")
WECOM_TOKEN            = os.environ.get("WECOM_TOKEN", "")
WECOM_ENCODING_AES_KEY = os.environ.get("WECOM_ENCODING_AES_KEY", "")
WECOM_CORP_ID          = os.environ.get("WECOM_CORP_ID", "")
WECOM_AGENT_ID         = int(os.environ.get("WECOM_AGENT_ID", 1000002))
WECOM_CORP_SECRET      = os.environ.get("WECOM_CORP_SECRET", "")
DASHSCOPE_API_KEY      = os.environ.get("DASHSCOPE_API_KEY", "")

dashscope.api_key = DASHSCOPE_API_KEY
DB_PATH   = "shipments.db"
EXCEL_DIR = "temp_excel"
os.makedirs(EXCEL_DIR, exist_ok=True)

# ── Template context ──────────────────────────────────────────────
@app.context_processor
def inject_globals():
    return {"now": datetime.now().strftime("%Y-%m-%d %H:%M")}

# Add fromjson filter for edits template
@app.template_filter('fromjson')
def fromjson_filter(s):
    try: return json.loads(s)
    except: return {}

# ── Database ──────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL CHECK(role IN ('admin','finance','staff')),
            display_name  TEXT DEFAULT '',
            active        INTEGER DEFAULT 1,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS shipments (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_no      TEXT,
            transfer_no      TEXT,
            salesperson      TEXT,
            customer         TEXT,
            channel          TEXT,
            destination      TEXT,
            postal_code      TEXT,
            payment_received TEXT,
            payment_slip     TEXT,
            payment_method   TEXT,
            invoiced         TEXT,
            payment_amount   TEXT,
            is_paid          TEXT,
            misc_fee         TEXT,
            remarks          TEXT,
            insurance        TEXT,
            actual_weight    TEXT,
            volume           TEXT,
            total_weight     TEXT,
            pieces           TEXT,
            ship_weight      TEXT,
            gross_profit     TEXT,
            profit_rate      TEXT,
            agent            TEXT,
            wooden_frame     TEXT,
            has_docs         TEXT,
            ship_date        TEXT,
            source           TEXT DEFAULT 'bot',
            created_by       TEXT DEFAULT 'bot',
            created_at       TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS edit_requests (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id  INTEGER NOT NULL,
            changes      TEXT NOT NULL,
            reason       TEXT,
            requested_by TEXT NOT NULL,
            reviewed_by  TEXT,
            status       TEXT DEFAULT 'pending',
            review_note  TEXT,
            reviewed_at  TEXT,
            created_at   TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT NOT NULL,
            action     TEXT NOT NULL,
            detail     TEXT,
            ip         TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS lookup_values (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            category   TEXT NOT NULL,
            value      TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            active     INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS cell_colors (
            shipment_id INTEGER NOT NULL,
            field       TEXT NOT NULL,
            color       TEXT NOT NULL,
            updated_by  TEXT,
            updated_at  TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (shipment_id, field)
        );
    """)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (username,password_hash,role,display_name) VALUES (?,?,?,?)",
            ('admin', generate_password_hash('Xcst@2026#Bwk'), 'admin', '管理员')
        )
    conn.commit(); conn.close()

def migrate_db():
    new_cols = ['transfer_no','salesperson','customer','channel','destination','postal_code',
                'payment_received','payment_slip','payment_method','invoiced','payment_amount',
                'is_paid','misc_fee','insurance','actual_weight','volume','total_weight',
                'ship_weight','gross_profit','profit_rate','agent','wooden_frame','has_docs','ship_date']
    conn = sqlite3.connect(DB_PATH)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(shipments)")}
    for col in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE shipments ADD COLUMN {col} TEXT")
    conn.commit(); conn.close()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def log_action(username, action, detail=""):
    try:
        ip = request.remote_addr if request else ""
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO audit_logs (username,action,detail,ip) VALUES (?,?,?,?)",
                     (username, action, detail, ip))
        conn.commit(); conn.close()
    except Exception: pass

# ── Auth ──────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('user'): return redirect(url_for('app_login'))
        return f(*a, **kw)
    return dec

def roles(*allowed):
    def decorator(f):
        @wraps(f)
        def dec(*a, **kw):
            if not session.get('user'): return redirect(url_for('app_login'))
            if session.get('role') not in allowed:
                return render_template('base.html', active='', page_title='错误'), 403
            return f(*a, **kw)
        return dec
    return decorator

# ── AI ────────────────────────────────────────────────────────────
PROMPT = """从图片中提取物流单据信息，只返回JSON，不要其他内容：
{"运单号":"","发货人":"","收货人":"","收货地址":"","重量":"","件数":"","货物品名":"","备注":""}
看不清楚的字段填"未显示"。"""

def extract(image_url):
    resp = MultiModalConversation.call(
        model="qwen-vl-max",
        messages=[{"role":"user","content":[{"image":image_url},{"text":PROMPT}]}]
    )
    raw = resp.output.choices[0].message.content[0]["text"]
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    text = m.group(1) if m else raw
    try: return json.loads(text)
    except: return {"运单号":"","备注":raw}

def store_shipment(d, source='bot', created_by='bot'):
    conn = sqlite3.connect(DB_PATH)
    no = (d.get("运单号") or d.get("tracking_no","")).strip()
    fields = {
        'tracking_no':      no,
        'transfer_no':      d.get("转单号","")      or d.get("transfer_no",""),
        'salesperson':      d.get("业务员","")       or d.get("salesperson",""),
        'customer':         d.get("客户公司","")     or d.get("customer","") or d.get("发货人",""),
        'channel':          d.get("渠道","")         or d.get("channel",""),
        'destination':      d.get("目的国","")       or d.get("destination","") or d.get("收货地址",""),
        'postal_code':      d.get("邮编","")         or d.get("postal_code",""),
        'payment_received': d.get("收款金额","")     or d.get("payment_received",""),
        'payment_slip':     d.get("水单","")         or d.get("payment_slip",""),
        'payment_method':   d.get("收款方式","")     or d.get("payment_method",""),
        'invoiced':         d.get("是否开票","")     or d.get("invoiced",""),
        'payment_amount':   d.get("付款金额","")     or d.get("payment_amount",""),
        'is_paid':          d.get("是否已付","")     or d.get("is_paid",""),
        'misc_fee':         d.get("杂费","")         or d.get("misc_fee",""),
        'remarks':          d.get("备注","")         or d.get("remarks",""),
        'insurance':        d.get("是否买保险","")   or d.get("insurance",""),
        'actual_weight':    d.get("实重","")         or d.get("actual_weight","") or d.get("重量",""),
        'volume':           d.get("材积","")         or d.get("volume",""),
        'total_weight':     d.get("收货总重量","")   or d.get("total_weight",""),
        'pieces':           d.get("件数","")         or d.get("pieces",""),
        'ship_weight':      d.get("出货重量","")     or d.get("ship_weight",""),
        'gross_profit':     d.get("毛利","")         or d.get("gross_profit",""),
        'profit_rate':      d.get("利率","")         or d.get("profit_rate",""),
        'agent':            d.get("代理","")         or d.get("agent",""),
        'wooden_frame':     d.get("木架","")         or d.get("wooden_frame",""),
        'has_docs':         d.get("是否单证","")     or d.get("has_docs",""),
        'ship_date':        d.get("出货日期","")     or d.get("ship_date",""),
    }
    cols = list(fields.keys()) + ['source','created_by']
    vals = list(fields.values()) + [source, created_by]
    if no and no != "未显示":
        ex = conn.execute("SELECT id FROM shipments WHERE tracking_no=?", (no,)).fetchone()
        if ex:
            sets = ",".join(f"{c}=?" for c in cols) + ",created_at=datetime('now','localtime')"
            conn.execute(f"UPDATE shipments SET {sets} WHERE id=?", vals + [ex[0]])
            conn.commit(); conn.close(); return False
    conn.execute(f"INSERT INTO shipments ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals)
    conn.commit(); conn.close()
    return True

# ── Excel ─────────────────────────────────────────────────────────
HEADERS = ["时间","原单号","转单号","业务员","客户公司","渠道","目的国","邮编",
           "收款金额","水单","收款方式","是否开票","付款金额","是否已付","杂费","备注",
           "是否买保险","实重","材积","收货总重量","件数","出货重量","毛利","利率",
           "代理","木架","是否单证","出货日期","录入人","来源"]
DB_COLS  = ["created_at","tracking_no","transfer_no","salesperson","customer","channel",
            "destination","postal_code","payment_received","payment_slip","payment_method",
            "invoiced","payment_amount","is_paid","misc_fee","remarks","insurance",
            "actual_weight","volume","total_weight","pieces","ship_weight","gross_profit",
            "profit_rate","agent","wooden_frame","has_docs","ship_date","created_by","source"]

def generate_excel(rows):
    wb = Workbook(); ws = wb.active; ws.title = "运单记录"
    ws.append(HEADERS)
    for cell in ws[1]: cell.font = Font(bold=True)
    for r in rows:
        ws.append([dict(r).get(c,"") for c in DB_COLS])
    fn = f"{uuid.uuid4().hex}.xlsx"
    wb.save(os.path.join(EXCEL_DIR, fn))
    return fn

# ── WeChat helpers ────────────────────────────────────────────────
_wt = {"token":None,"expires":0}
def get_wechat_token():
    now = time.time()
    if _wt["token"] and now < _wt["expires"]: return _wt["token"]
    r = http_requests.get(f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WECHAT_APPID}&secret={WECHAT_APPSECRET}").json()
    _wt["token"] = r.get("access_token"); _wt["expires"] = now + r.get("expires_in",7200) - 60
    return _wt["token"]
def send_wechat_msg(openid, content):
    http_requests.post(f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={get_wechat_token()}",
        json={"touser":openid,"msgtype":"text","text":{"content":content}})
def verify_wechat(token,sig,ts,nonce):
    return hashlib.sha1("".join(sorted([token,ts,nonce])).encode()).hexdigest() == sig
def xml_reply(to,frm,content):
    return f"<xml><ToUserName><![CDATA[{to}]]></ToUserName><FromUserName><![CDATA[{frm}]]></FromUserName><CreateTime>{int(time.time())}</CreateTime><MsgType><![CDATA[text]]></MsgType><Content><![CDATA[{content}]]></Content></xml>"

# ── WeCom helpers ─────────────────────────────────────────────────
class _WeCom:
    def __init__(self, token, aes_key_b64, corp_id):
        self.token = token; self.aes_key = base64.b64decode(aes_key_b64+"="); self.corp_id = corp_id
    def _sig_ok(self, sig, ts, nonce, data):
        return hashlib.sha1("".join(sorted([self.token,str(ts),str(nonce),data])).encode()).hexdigest() == sig
    def _decrypt(self, enc):
        from Crypto.Cipher import AES
        raw = base64.b64decode(enc)
        plain = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16]).decrypt(raw)
        pad = plain[-1] if isinstance(plain[-1],int) else ord(plain[-1])
        plain = plain[:-pad]
        return plain[20:20+struct.unpack(">I",plain[16:20])[0]].decode("utf-8")
    def verify_url(self, sig, ts, nonce, echostr):
        if not self._sig_ok(sig,ts,nonce,echostr): raise ValueError("bad sig")
        return self._decrypt(echostr)
    def decrypt_message(self, body, sig, ts, nonce):
        enc = ET.fromstring(body).find("Encrypt").text
        if not self._sig_ok(sig,ts,nonce,enc): raise ValueError("bad sig")
        return self._decrypt(enc)

_wecom_crypto = _WeCom(WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_CORP_ID)
_wecom_t = {"token":None,"expires":0}
def get_wecom_token():
    now = time.time()
    if _wecom_t["token"] and now < _wecom_t["expires"]: return _wecom_t["token"]
    r = http_requests.get(f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_CORP_SECRET}").json()
    _wecom_t["token"] = r.get("access_token"); _wecom_t["expires"] = now + r.get("expires_in",7200) - 60
    return _wecom_t["token"]
def wecom_send(to_user, content):
    http_requests.post(f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={get_wecom_token()}",
        json={"touser":to_user,"msgtype":"text","agentid":WECOM_AGENT_ID,"text":{"content":content}})

# ── Bot background tasks ──────────────────────────────────────────
def _bg_wechat(user_id, pic_url):
    try:
        b64 = base64.b64encode(http_requests.get(pic_url,timeout=15).content).decode()
        data = extract(f"data:image/jpeg;base64,{b64}")
        is_new = store_shipment(data, source='bot_wechat', created_by='bot')
        no = data.get("运单号") or "未识别"
        send_wechat_msg(user_id, f"{'✅ 已录入' if is_new else '🔄 已更新'}：{no}\n\n发「查询」查看详情")
    except Exception as e:
        send_wechat_msg(user_id, "❌ 识别失败，请重试"); print(f"WeChat识别失败:{e}")

def _bg_wecom(user_id, pic_url):
    try:
        b64 = base64.b64encode(http_requests.get(pic_url,timeout=15).content).decode()
        data = extract(f"data:image/jpeg;base64,{b64}")
        is_new = store_shipment(data, source='bot_wecom', created_by='bot')
        no = data.get("运单号") or "未识别"
        lines = [f"{k}：{v}" for k,v in data.items() if v and v != "未显示"]
        wecom_send(user_id, f"{'✅ 已录入' if is_new else '🔄 已更新'}：{no}\n\n" + "\n".join(lines))
    except Exception as e:
        wecom_send(user_id, "❌ 识别失败，请重试"); print(f"WeCom识别失败:{e}")

# ── Bot Routes ────────────────────────────────────────────────────
@app.route("/wechat", methods=["GET","POST"])
def wechat():
    sig=request.args.get("signature",""); ts=request.args.get("timestamp",""); nonce=request.args.get("nonce","")
    if request.method == "GET":
        return request.args.get("echostr","") if verify_wechat(WECHAT_TOKEN,sig,ts,nonce) else ("Invalid",403)
    xml=ET.fromstring(request.data); kind=xml.find("MsgType").text; frm=xml.find("FromUserName").text; to=xml.find("ToUserName").text
    if kind == "image":
        threading.Thread(target=_bg_wechat, args=(frm, xml.find("PicUrl").text), daemon=True).start()
        return xml_reply(frm, to, "⏳ 图片已收到，正在识别...\n完成后发「查询」查看结果")
    if kind == "text" and (xml.find("Content").text or "").strip() == "查询":
        conn = db()
        r = conn.execute("SELECT * FROM shipments ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        if not r: return xml_reply(frm, to, "暂无记录，请先发运单图片。")
        r = dict(r)
        lines = [f"原单号：{r['tracking_no']}", f"客户：{r['customer']}", f"目的国：{r['destination']}", f"录入：{r['created_at']}"]
        return xml_reply(frm, to, "✅ 最新运单：\n\n" + "\n".join(l for l in lines if not l.endswith("：") and not l.endswith("：None")))
    return "success"

@app.route("/wecom", methods=["GET","POST"])
def wecom():
    sig=request.args.get("msg_signature",""); ts=request.args.get("timestamp",""); nonce=request.args.get("nonce","")
    if request.method == "GET":
        try: return _wecom_crypto.verify_url(sig,ts,nonce,request.args.get("echostr",""))
        except Exception as e: print(f"WeCom验证失败:{e}"); return "Invalid",403
    try: msg_xml = _wecom_crypto.decrypt_message(request.data,sig,ts,nonce)
    except Exception as e: print(f"WeCom解密失败:{e}"); return "success"
    xml=ET.fromstring(msg_xml)
    kind = xml.find("MsgType").text  if xml.find("MsgType")  is not None else ""
    frm  = xml.find("FromUserName").text if xml.find("FromUserName") is not None else ""
    if kind == "image":
        pic_el = xml.find("PicUrl")
        if pic_el is not None and pic_el.text:
            threading.Thread(target=_bg_wecom, args=(frm, pic_el.text), daemon=True).start()
    return "success"

@app.route("/download/<filename>")
def download(filename):
    if not filename.endswith(".xlsx") or "/" in filename or ".." in filename: return "Not found",404
    return send_from_directory(EXCEL_DIR, filename, as_attachment=True, download_name="运单数据.xlsx")

# ── Auth Routes ───────────────────────────────────────────────────
@app.route("/")
def root(): return redirect(url_for('dashboard'))

@app.route("/app/login", methods=["GET","POST"])
def app_login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        conn = db()
        u = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        conn.close()
        if u and check_password_hash(u['password_hash'], password):
            session['user'] = u['username']; session['role'] = u['role']; session['display'] = u['display_name']
            log_action(username, '登录')
            return redirect(url_for('dashboard'))
        error = "用户名或密码错误"
    return render_template('login.html', error=error)

@app.route("/app/logout")
def app_logout():
    user = session.get('user','')
    if user: log_action(user, '退出')
    session.clear()
    return redirect(url_for('app_login'))

# ── Dashboard ─────────────────────────────────────────────────────
@app.route("/app/")
@login_required
def dashboard():
    role = session.get('role'); user = session.get('user')
    conn = db()
    now = datetime.now(); today = now.strftime("%Y-%m-%d"); month = now.strftime("%Y-%m")
    if role == 'staff':
        total  = conn.execute("SELECT COUNT(*) FROM shipments WHERE created_by=?", (user,)).fetchone()[0]
        today_ = conn.execute("SELECT COUNT(*) FROM shipments WHERE created_by=? AND created_at LIKE ?", (user, f"{today}%")).fetchone()[0]
        month_ = conn.execute("SELECT COUNT(*) FROM shipments WHERE created_by=? AND created_at LIKE ?", (user, f"{month}%")).fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM edit_requests WHERE requested_by=? AND status='pending'", (user,)).fetchone()[0]
        recent = conn.execute("SELECT * FROM shipments WHERE created_by=? ORDER BY id DESC LIMIT 8", (user,)).fetchall()
    else:
        total  = conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        today_ = conn.execute("SELECT COUNT(*) FROM shipments WHERE created_at LIKE ?", (f"{today}%",)).fetchone()[0]
        month_ = conn.execute("SELECT COUNT(*) FROM shipments WHERE created_at LIKE ?", (f"{month}%",)).fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM edit_requests WHERE status='pending'").fetchone()[0]
        recent = conn.execute("SELECT * FROM shipments ORDER BY id DESC LIMIT 8").fetchall()
    alerts = []
    if role == 'admin':
        for d in conn.execute("SELECT tracking_no,COUNT(*) c FROM shipments WHERE tracking_no!='' AND tracking_no IS NOT NULL GROUP BY tracking_no HAVING c>1"):
            alerts.append(f"⚠️ 原单号 <b>{d[0]}</b> 重复出现 {d[1]} 次")
    conn.close()
    return render_template('dashboard.html', active='home',
        stats={"total":total,"today":today_,"month":month_,"pending":pending},
        recent=recent, alerts=alerts)

# ── Shipments ─────────────────────────────────────────────────────
@app.route("/app/shipments")
@login_required
def shipments():
    role=session.get('role'); user=session.get('user')
    start=request.args.get('start',''); end=request.args.get('end',''); q=request.args.get('q','')
    conn=db()
    base="FROM shipments WHERE 1=1"; params=[]
    if role=='staff': base+=" AND created_by=?"; params.append(user)
    if q: base+=" AND (tracking_no LIKE ? OR transfer_no LIKE ? OR customer LIKE ?)"; params+=[f"%{q}%"]*3
    if start: base+=" AND created_at >= ?"; params.append(start)
    if end:   base+=" AND created_at <= ?"; params.append(end+" 23:59:59")
    total    = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    rows     = conn.execute(f"SELECT * {base} ORDER BY id DESC LIMIT 500", params).fetchall()
    agents   = [r[0] for r in conn.execute("SELECT value FROM lookup_values WHERE category='agent'          AND active=1 ORDER BY sort_order,id").fetchall()]
    channels = [r[0] for r in conn.execute("SELECT value FROM lookup_values WHERE category='channel'        AND active=1 ORDER BY sort_order,id").fetchall()]
    methods  = [r[0] for r in conn.execute("SELECT value FROM lookup_values WHERE category='payment_method' AND active=1 ORDER BY sort_order,id").fetchall()]
    conn.close()
    rows_json = json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)
    return render_template('shipments.html', active='shipments',
        rows_json=rows_json, total=total, q=q, start=start, end=end,
        can_export=(role in ('admin','finance')),
        can_edit_direct=(role in ('admin','finance')),
        agents=agents, channels=channels, methods=methods)

@app.route("/app/shipments/<int:sid>/edit", methods=["GET","POST"])
@roles('admin','finance')
def edit_shipment(sid):
    conn=db()
    r = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
    if not r: conn.close(); return "Not found",404
    if request.method == "POST":
        f=request.form
        fields = ['tracking_no','transfer_no','salesperson','customer','channel','destination',
                  'postal_code','payment_received','payment_slip','payment_method','invoiced',
                  'payment_amount','is_paid','misc_fee','remarks','insurance','actual_weight',
                  'volume','total_weight','pieces','ship_weight','gross_profit','profit_rate',
                  'agent','wooden_frame','has_docs','ship_date']
        sets = ",".join(f"{c}=?" for c in fields)
        vals = [f.get(c,'') for c in fields] + [sid]
        conn.execute(f"UPDATE shipments SET {sets} WHERE id=?", vals)
        conn.commit(); conn.close()
        log_action(session['user'], '直接编辑运单', f"ID:{sid}")
        return redirect(url_for('shipments'))
    r = dict(r); conn.close()
    return render_template('edit_shipment.html', active='shipments', r=r)

# ── Delete shipment (admin/finance direct) ────────────────────────
@app.route("/app/shipments/<int:sid>/delete", methods=["POST"])
@roles('admin','finance')
def delete_shipment(sid):
    conn = db()
    r = conn.execute("SELECT tracking_no FROM shipments WHERE id=?", (sid,)).fetchone()
    if r:
        conn.execute("DELETE FROM shipments WHERE id=?", (sid,))
        conn.execute("DELETE FROM edit_requests WHERE shipment_id=?", (sid,))
        conn.execute("DELETE FROM cell_colors WHERE shipment_id=?", (sid,))
        conn.commit()
        log_action(session['user'], '删除运单', f"ID:{sid} 单号:{r['tracking_no']}")
    conn.close()
    return redirect(url_for('shipments'))

# ── Request delete (staff) ────────────────────────────────────────
@app.route("/app/shipments/<int:sid>/request-delete", methods=["POST"])
@login_required
def request_delete_shipment(sid):
    reason = request.form.get('reason','').strip()
    conn = db()
    r = conn.execute("SELECT tracking_no FROM shipments WHERE id=?", (sid,)).fetchone()
    if r:
        conn.execute(
            "INSERT INTO edit_requests (shipment_id, changes, reason, requested_by) VALUES (?,?,?,?)",
            (sid, json.dumps({"__action":"delete"}, ensure_ascii=False), reason, session['user'])
        )
        conn.commit()
        log_action(session['user'], '申请删除运单', f"ID:{sid} 原因:{reason}")
    conn.close()
    return redirect(url_for('edits'))

# ── Upload ────────────────────────────────────────────────────────
@app.route("/app/upload", methods=["GET","POST"])
@login_required
def upload():
    msg=""; msg_type=""
    if request.method == "POST":
        action = request.form.get('action','')
        if action == 'manual':
            f=request.form
            data = {k: f.get(k,'') for k in ['tracking_no','transfer_no','salesperson','customer',
                'channel','destination','postal_code','payment_received','payment_slip','payment_method',
                'invoiced','payment_amount','is_paid','misc_fee','remarks','insurance','actual_weight',
                'volume','total_weight','pieces','ship_weight','gross_profit','profit_rate',
                'agent','wooden_frame','has_docs','ship_date']}
            is_new = store_shipment(data, source='web', created_by=session['user'])
            log_action(session['user'],'手动录入运单',f"原单号:{data['tracking_no']}")
            msg = f"{'✅ 已录入' if is_new else '🔄 已更新'}：{data['tracking_no'] or '（无单号）'}"; msg_type="success"
        elif action == 'image':
            file = request.files.get('image')
            if not file or not file.filename: msg="请选择图片文件"; msg_type="error"
            else:
                try:
                    b64 = base64.b64encode(file.read()).decode()
                    ext = file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else 'jpeg'
                    mime = 'image/png' if ext=='png' else 'image/jpeg'
                    data = extract(f"data:{mime};base64,{b64}")
                    is_new = store_shipment(data, source='web', created_by=session['user'])
                    log_action(session['user'],'AI上传运单',f"原单号:{data.get('运单号','')}")
                    msg = f"{'✅ 识别录入成功' if is_new else '🔄 已更新'}：{data.get('运单号','（未识别）')}"; msg_type="success"
                except Exception as e: msg=f"❌ 识别失败：{str(e)[:100]}"; msg_type="error"
    return render_template('upload.html', active='upload', msg=msg, msg_type=msg_type)

# ── Edit Requests ─────────────────────────────────────────────────
@app.route("/app/edits")
@login_required
def edits():
    role=session.get('role'); user=session.get('user')
    status_filter = request.args.get('status','pending')
    conn=db()
    if role=='staff':
        reqs = conn.execute("""SELECT er.*, s.tracking_no FROM edit_requests er
            LEFT JOIN shipments s ON s.id=er.shipment_id
            WHERE er.requested_by=? ORDER BY er.id DESC""", (user,)).fetchall()
    else:
        reqs = conn.execute("""SELECT er.*, s.tracking_no FROM edit_requests er
            LEFT JOIN shipments s ON s.id=er.shipment_id
            WHERE er.status=? ORDER BY er.id DESC""", (status_filter,)).fetchall()
    conn.close()
    return render_template('edits.html', active='edits', reqs=reqs, status_filter=status_filter)

@app.route("/app/edits/new/<int:sid>", methods=["GET","POST"])
@login_required
def new_edit_request(sid):
    conn=db()
    r = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
    if not r: conn.close(); return "Not found",404
    r=dict(r)
    if request.method == "POST":
        f=request.form; changes={}
        field_map = {'tracking_no':'原单号','transfer_no':'转单号','salesperson':'业务员',
                     'customer':'客户公司','destination':'目的国','payment_received':'收款金额',
                     'remarks':'备注','actual_weight':'实重','pieces':'件数'}
        for key,label in field_map.items():
            new_val = f.get(key,'').strip(); old_val = (r.get(key) or '').strip()
            if new_val != old_val: changes[label] = {'old':old_val,'new':new_val}
        if not changes: conn.close(); return redirect(url_for('edits'))
        conn.execute("INSERT INTO edit_requests (shipment_id,changes,reason,requested_by) VALUES (?,?,?,?)",
            (sid, json.dumps(changes,ensure_ascii=False), f.get('reason',''), session['user']))
        conn.commit(); conn.close()
        log_action(session['user'],'提交修改申请',f"ID:{sid}")
        return redirect(url_for('edits'))
    conn.close()
    return render_template('edit_shipment.html', active='edits', r=r)

@app.route("/app/edits/<int:eid>/review", methods=["POST"])
@roles('admin','finance')
def review_edit(eid):
    action=request.form.get('action','')
    conn=db()
    er = conn.execute("SELECT * FROM edit_requests WHERE id=?", (eid,)).fetchone()
    if not er or er['status']!='pending': conn.close(); return redirect(url_for('edits'))
    status='approved' if action=='approve' else 'rejected'
    conn.execute("UPDATE edit_requests SET status=?,reviewed_by=?,reviewed_at=datetime('now','localtime') WHERE id=?",
                 (status, session['user'], eid))
    if status=='approved':
        changes=json.loads(er['changes'])
        if changes.get('__action') == 'delete':
            # approved delete request — remove the shipment
            r = conn.execute("SELECT tracking_no FROM shipments WHERE id=?", (er['shipment_id'],)).fetchone()
            conn.execute("DELETE FROM shipments WHERE id=?", (er['shipment_id'],))
            conn.execute("DELETE FROM cell_colors WHERE shipment_id=?", (er['shipment_id'],))
            log_action(session['user'], '批准删除运单',
                       f"ID:{er['shipment_id']} 单号:{r['tracking_no'] if r else ''}")
        else:
            field_map={'原单号':'tracking_no','转单号':'transfer_no','业务员':'salesperson',
                       '客户公司':'customer','目的国':'destination','收款金额':'payment_received',
                       '备注':'remarks','实重':'actual_weight','件数':'pieces'}
            for label,vals in changes.items():
                col=field_map.get(label)
                if col: conn.execute(f"UPDATE shipments SET {col}=? WHERE id=?", (vals['new'],er['shipment_id']))
    conn.commit(); conn.close()
    log_action(session['user'],f"{'批准' if status=='approved' else '驳回'}修改申请",f"ID:{eid}")
    return redirect(url_for('edits'))

# ── Export ────────────────────────────────────────────────────────
@app.route("/app/export")
@roles('admin','finance')
def export():
    range_type=request.args.get('range','all')
    now=datetime.now(); conn=db()
    if range_type=='today':
        rows=conn.execute("SELECT * FROM shipments WHERE created_at LIKE ? ORDER BY id", (f"{now.strftime('%Y-%m-%d')}%",)).fetchall()
    elif range_type=='month':
        rows=conn.execute("SELECT * FROM shipments WHERE created_at LIKE ? ORDER BY id", (f"{now.strftime('%Y-%m')}%",)).fetchall()
    else:
        rows=conn.execute("SELECT * FROM shipments ORDER BY id").fetchall()
    conn.close()
    fn=generate_excel(rows)
    with open(os.path.join(EXCEL_DIR,fn),'rb') as f: content=f.read()
    resp=make_response(content)
    resp.headers["Content-Type"]="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    resp.headers["Content-Disposition"]=f"attachment; filename=shipments_{range_type}.xlsx"
    return resp

# ── Audit Logs ────────────────────────────────────────────────────
@app.route("/app/logs")
@roles('admin')
def audit_logs():
    user_filter=request.args.get('user','')
    conn=db()
    if user_filter:
        rows=conn.execute("SELECT * FROM audit_logs WHERE username=? ORDER BY id DESC LIMIT 500",(user_filter,)).fetchall()
    else:
        rows=conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 500").fetchall()
    users=[r[0] for r in conn.execute("SELECT DISTINCT username FROM audit_logs ORDER BY username")]
    conn.close()
    return render_template('logs.html', active='logs', rows=rows, users=users, user_filter=user_filter)

# ── Users ─────────────────────────────────────────────────────────
@app.route("/app/users", methods=["GET","POST"])
@roles('admin')
def users():
    msg=""; msg_type=""
    conn=db()
    if request.method=="POST":
        action=request.form.get('action','')
        if action=='create':
            username=request.form.get('username','').strip(); password=request.form.get('password','')
            role=request.form.get('role','staff'); display=request.form.get('display_name','').strip()
            if username and password:
                try:
                    conn.execute("INSERT INTO users (username,password_hash,role,display_name) VALUES (?,?,?,?)",
                                 (username,generate_password_hash(password),role,display))
                    conn.commit(); log_action(session['user'],'创建用户',f"{username}/{role}")
                    msg=f"✅ 用户 {username} 创建成功"; msg_type="success"
                except: msg="用户名已存在"; msg_type="error"
            else: msg="用户名和密码不能为空"; msg_type="error"
        elif action=='toggle':
            uid=request.form.get('uid')
            u=conn.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
            if u and u['username']!=session['user']:
                new_a=0 if u['active'] else 1
                conn.execute("UPDATE users SET active=? WHERE id=?",(new_a,uid)); conn.commit()
                msg=f"{'✅ 已启用' if new_a else '⏸ 已停用'}"; msg_type="success"
        elif action=='reset_pw':
            uid=request.form.get('uid'); new_pw=request.form.get('new_pw','')
            if new_pw:
                conn.execute("UPDATE users SET password_hash=? WHERE id=?",(generate_password_hash(new_pw),uid))
                conn.commit(); msg="✅ 密码已重置"; msg_type="success"
    all_users=conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close()
    return render_template('users.html', active='users', all_users=all_users, msg=msg, msg_type=msg_type)

# ── Settings ──────────────────────────────────────────────────────
@app.route("/app/settings")
@roles('admin')
def settings():
    conn = db()
    agents   = conn.execute("SELECT * FROM lookup_values WHERE category='agent'   AND active=1 ORDER BY sort_order,id").fetchall()
    channels = conn.execute("SELECT * FROM lookup_values WHERE category='channel' AND active=1 ORDER BY sort_order,id").fetchall()
    methods  = conn.execute("SELECT * FROM lookup_values WHERE category='payment_method' AND active=1 ORDER BY sort_order,id").fetchall()
    conn.close()
    return render_template('settings.html', active='settings',
        agents=agents, channels=channels, methods=methods)

# ── Lookup API ────────────────────────────────────────────────────
@app.route("/api/lookup/<category>", methods=["GET"])
@login_required
def lookup_list(category):
    conn = db()
    rows = conn.execute("SELECT id,value FROM lookup_values WHERE category=? AND active=1 ORDER BY sort_order,id", (category,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/lookup/<category>", methods=["POST"])
@roles('admin')
def lookup_add(category):
    value = (request.json or {}).get('value','').strip()
    if not value: return jsonify({'error':'empty'}), 400
    conn = db()
    conn.execute("INSERT INTO lookup_values (category,value) VALUES (?,?)", (category, value))
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    log_action(session['user'], f'新增{category}', value)
    return jsonify({'id': rid, 'value': value})

@app.route("/api/lookup/<category>/<int:lid>", methods=["DELETE"])
@roles('admin')
def lookup_delete(category, lid):
    conn = db()
    conn.execute("UPDATE lookup_values SET active=0 WHERE id=? AND category=?", (lid, category))
    conn.commit(); conn.close()
    log_action(session['user'], f'删除{category}', f'id={lid}')
    return jsonify({'ok': True})

# ── Inline cell edit ──────────────────────────────────────────────
@app.route("/api/shipments/<int:sid>/cell", methods=["PATCH"])
@roles('admin','finance')
def patch_cell(sid):
    data = request.json or {}
    field = data.get('field',''); value = data.get('value','')
    allowed = ['tracking_no','transfer_no','salesperson','customer','channel','destination',
               'postal_code','payment_received','payment_slip','payment_method','invoiced',
               'payment_amount','is_paid','misc_fee','remarks','insurance','actual_weight',
               'volume','total_weight','pieces','ship_weight','gross_profit','profit_rate',
               'agent','wooden_frame','has_docs','ship_date']
    if field not in allowed: return jsonify({'error':'invalid field'}), 400
    conn = db()
    conn.execute(f"UPDATE shipments SET {field}=? WHERE id=?", (value, sid))
    conn.commit(); conn.close()
    log_action(session['user'], '行内编辑', f'ID:{sid} {field}={value}')
    return jsonify({'ok': True})

# ── Cell color API ────────────────────────────────────────────────
@app.route("/api/shipments/<int:sid>/color", methods=["POST"])
@roles('admin','finance')
def set_color(sid):
    data = request.json or {}
    field = data.get('field',''); color = data.get('color','')
    conn = db()
    if color:
        conn.execute("INSERT OR REPLACE INTO cell_colors (shipment_id,field,color,updated_by) VALUES (?,?,?,?)",
                     (sid, field, color, session['user']))
    else:
        conn.execute("DELETE FROM cell_colors WHERE shipment_id=? AND field=?", (sid, field))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Finance stats API ─────────────────────────────────────────────
@app.route("/api/finance/stats")
@roles('admin')
def finance_stats():
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    conn = db()
    rows = conn.execute(
        "SELECT salesperson, SUM(CAST(payment_received AS REAL)) as revenue, "
        "SUM(CAST(gross_profit AS REAL)) as profit, COUNT(*) as cnt "
        "FROM shipments WHERE created_at LIKE ? GROUP BY salesperson",
        (f"{month}%",)
    ).fetchall()
    total_rev = conn.execute(
        "SELECT SUM(CAST(payment_received AS REAL)) FROM shipments WHERE created_at LIKE ?",
        (f"{month}%",)
    ).fetchone()[0] or 0
    total_profit = conn.execute(
        "SELECT SUM(CAST(gross_profit AS REAL)) FROM shipments WHERE created_at LIKE ?",
        (f"{month}%",)
    ).fetchone()[0] or 0
    today = datetime.now().strftime('%Y-%m-%d')
    today_rev = conn.execute(
        "SELECT SUM(CAST(payment_received AS REAL)) FROM shipments WHERE created_at LIKE ?",
        (f"{today}%",)
    ).fetchone()[0] or 0
    conn.close()
    return jsonify({
        'month': month,
        'total_revenue': round(total_rev, 2),
        'total_profit': round(total_profit, 2),
        'today_revenue': round(today_rev, 2),
        'by_salesperson': [dict(r) for r in rows]
    })

# ── Legacy redirects ──────────────────────────────────────────────
@app.route("/admin")
@app.route("/admin/")
@app.route("/admin/login")
@app.route("/admin/dashboard")
def admin_redirect(): return redirect(url_for('dashboard'))

# ── Main ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db(); migrate_db()
    app.run(host="0.0.0.0", port=5001, debug=False)
