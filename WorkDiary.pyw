# -*- coding: utf-8 -*-
"""
업무 다이어리 & 집중 회원관리
- 파이썬 표준 라이브러리만 사용 (pip 설치 필요 없음)
- 데이터는 이 파일과 같은 폴더의 workdiary.db 에 저장
- 폰 알림: ntfy 앱 (설정 버튼에서 토픽 등록)
"""
import os, sys, re, json, queue, random, string, sqlite3, calendar, threading, urllib.request
import datetime as dt
from collections import Counter
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import winsound
except ImportError:
    winsound = None

try:  # 윈도우 고해상도 화면에서 글씨 흐림 방지
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# ═════════════════════ 배포 설정 (배포자가 채우는 곳) ═════════════════════
APP_VERSION = "1.0.0"          # GitHub Actions가 태그(v1.0.1 등)로 자동 교체
GITHUB_REPO = ""               # 예: "내아이디/WorkDiary"  → 자동 업데이트에 사용
WORKER_URL = ""                # 예: "https://workdiary-push.내계정.workers.dev" → PC 꺼져도 폰 알림
WORKER_KEY = ""                # 클라우드플레어 Worker에 설정한 APP_KEY 와 동일하게
# ════════════════════════════════════════════════════════════════════

APP_TITLE = "업무 다이어리"
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else sys.argv[0]))
# 데이터는 exe 폴더가 아닌 %APPDATA%\WorkDiary 에 저장 → 업데이트로 exe를 바꿔도 데이터 유지
DATA_DIR = os.path.join(os.environ.get("APPDATA") or BASE_DIR, "WorkDiary")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "workdiary.db")
_OLD_DB = os.path.join(BASE_DIR, "workdiary.db")
if not os.path.exists(DB_PATH) and os.path.exists(_OLD_DB):   # 예전 버전 데이터 옮겨오기
    import shutil
    shutil.copy2(_OLD_DB, DB_PATH)

F = "맑은 고딕"
FONT, FONT_S, FONT_B, FONT_T = (F, 10), (F, 9), (F, 10, "bold"), (F, 13, "bold")
BG, ACCENT, LINE = "#f4f6fa", "#2563eb", "#d5dbe5"
WEEK = ["일", "월", "화", "수", "목", "금", "토"]
ALARM_CHECK_MS = 15000  # 15초마다 알림 확인


# ───────────────────────── 공통 함수 ─────────────────────────
def now():
    return dt.datetime.now()


def stamp():
    return now().strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(d, t):
    return dt.datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")


def short(s, n):
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def wd_name(d):
    return WEEK[(d.weekday() + 1) % 7]


def state_text(r):
    if r["done"]:
        return "완료"
    if not r["alarm"]:
        return "알림없음"
    return "울림" if r["notified"] else "🔔 대기"


def btn(parent, text, cmd, primary=False, **kw):
    return tk.Button(parent, text=text, command=cmd, font=FONT, relief="flat", cursor="hand2",
                     bg=ACCENT if primary else "#e3e8f0", fg="white" if primary else "#111",
                     activebackground="#1d4ed8" if primary else "#cfd6e2",
                     activeforeground="white" if primary else "#111", padx=10, pady=3, **kw)


def http_json(url, data=None, headers=None, timeout=15):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    h = {"User-Agent": f"WorkDiary/{APP_VERSION}"}
    if body is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET", headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        txt = r.read().decode("utf-8") or "{}"
        return json.loads(txt)


def worker_call(path, data):
    return http_json(WORKER_URL.rstrip("/") + path, data, {"X-App-Key": WORKER_KEY})


def push_sync(server, topic, title, message):
    """즉시 푸시 발송 (Worker가 설정돼 있으면 Worker 경유, 아니면 ntfy 직접)"""
    if WORKER_URL:
        return worker_call("/api/test", {"topic": topic, "title": title, "message": message})
    url = (server or "https://ntfy.sh").strip().rstrip("/")
    return http_json(url, {"topic": topic, "title": title, "message": message,
                           "priority": 4, "tags": ["alarm_clock"]})


def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


# ───────────────────────── 어깨동무 읽기 (윈도우 전용) ─────────────────────────
EKDM_CLASS = "TfrmEditdata"      # 어깨동무 회원 상세창
HOTKEY_TEXT = "F8"
IS_WIN = sys.platform == "win32"

if IS_WIN:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                           wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def w_class(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def w_text(h):
    res = ctypes.c_size_t()
    user32.SendMessageTimeoutW(h, 0x000E, 0, 0, 0x0002, 1500, ctypes.byref(res))  # WM_GETTEXTLENGTH
    n = res.value
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.SendMessageTimeoutW(h, 0x000D, n + 1, ctypes.cast(buf, ctypes.c_void_p).value,
                               0x0002, 1500, ctypes.byref(res))  # WM_GETTEXT
    return buf.value


def w_rect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def w_children(h):
    out = []
    cb = WNDENUMPROC(lambda c, l: (out.append(c), True)[1])
    user32.EnumChildWindows(h, cb, 0)
    return out


def ekdm_windows():
    """열려 있는 어깨동무 상세창 (위에 있는 창부터)"""
    out = []
    cb = WNDENUMPROC(lambda h, l: (out.append(h) if user32.IsWindowVisible(h) and w_class(h) == EKDM_CLASS
                                   else None, True)[1])
    user32.EnumWindows(cb, 0)
    return out


def find_ekdm(hwnd=None):
    if hwnd:
        root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
        if root and w_class(root) == EKDM_CLASS:
            return root
    wins = ekdm_windows()
    return wins[0] if wins else None


def read_ekdm(h):
    """상세창에서 이름 / 휴대폰 / 검색어 / 메모 읽기"""
    left, top, _, _ = w_rect(h)
    edits, memos = [], []
    for c in w_children(h):
        cls = w_class(c)
        if cls not in ("TDBEdit", "TDBMemo"):
            continue
        l, t, r, b = w_rect(c)
        if cls == "TDBEdit":
            edits.append((l - left, t - top, c))
        else:
            memos.append(((r - l) * (b - t), c))
    # 이름·휴대폰·…·검색어가 한 줄로 세로 정렬된 왼쪽 열 찾기
    col = []
    if edits:
        x_mode = Counter(x for x, _, _ in edits).most_common(1)[0][0]
        col = sorted((e for e in edits if abs(e[0] - x_mode) <= 3), key=lambda e: e[1])
    name = w_text(col[0][2]).strip() if len(col) > 0 else ""
    phone = w_text(col[1][2]).strip() if len(col) > 1 else ""
    keyword = w_text(col[-1][2]).strip() if len(col) > 2 else ""
    if not re.search(r"\d{3,4}\D?\d{4}$", phone):   # 혹시 순서가 다르면 전화번호 모양인 칸을 찾음
        for _, _, c in edits:
            t = w_text(c).strip()
            if re.fullmatch(r"01\d[- ]?\d{3,4}[- ]?\d{4}", t):
                phone = t
                break
    memo = w_text(max(memos)[1]) if memos else ""
    memo = memo.replace("\r\n", "\n").replace("\r", "\n").strip()
    return {"name": name, "phone": phone, "keyword": keyword, "memo": memo}


def hotkey_loop(q):
    """전역 단축키 F8 감시 (별도 스레드)"""
    MOD_NOREPEAT, VK_F8, WM_HOTKEY = 0x4000, 0x77, 0x0312
    if not user32.RegisterHotKey(None, 1, MOD_NOREPEAT, VK_F8):
        q.put(("fail", None))
        return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            q.put(("capture", user32.GetForegroundWindow()))


def digits(s):
    return re.sub(r"\D", "", s or "")


# ───────────────────────── DB ─────────────────────────
class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS members(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT,
            memo TEXT DEFAULT '', created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS schedules(
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, time TEXT, title TEXT,
            content TEXT DEFAULT '', member_id INTEGER, alarm INTEGER DEFAULT 1,
            notified INTEGER DEFAULT 0, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT UNIQUE,
            content TEXT DEFAULT '', updated TEXT);
        CREATE TABLE IF NOT EXISTS diary(date TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.conn.commit()

    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql, args=()):
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur.lastrowid

    def get(self, k, default=""):
        r = self.one("SELECT value FROM settings WHERE key=?", (k,))
        return r["value"] if r else default

    def set(self, k, v):
        self.x("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))


# ───────────────────────── 일정 / 알림 예약 창 ─────────────────────────
class ScheduleDialog(tk.Toplevel):
    def __init__(self, app, sid=None, date=None, member_id=None, title_default="", on_saved=None):
        super().__init__(app.root)
        self.app, self.db, self.sid, self.on_saved = app, app.db, sid, on_saved
        self.row = self.db.one("SELECT * FROM schedules WHERE id=?", (sid,)) if sid else None
        self.title("일정 수정" if self.row else "일정 / 알림 예약")
        self.configure(bg=BG)
        self.geometry("480x440")
        self.minsize(420, 380)
        self.transient(app.root)

        f = tk.Frame(self, bg=BG, padx=14, pady=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        def lab(text, r):
            tk.Label(f, text=text, font=FONT_B, bg=BG).grid(row=r, column=0, sticky="nw", pady=4, padx=(0, 8))

        # 날짜 / 시간
        lab("날짜·시간", 0)
        dtf = tk.Frame(f, bg=BG)
        dtf.grid(row=0, column=1, sticky="w")
        self.date_var, self.h, self.m = tk.StringVar(), tk.StringVar(), tk.StringVar()
        tk.Entry(dtf, textvariable=self.date_var, width=11, font=FONT).pack(side="left")
        tk.Label(dtf, text="  ", bg=BG).pack(side="left")
        tk.Spinbox(dtf, from_=0, to=23, width=3, format="%02.0f", wrap=True,
                   textvariable=self.h, font=FONT).pack(side="left")
        tk.Label(dtf, text=":", bg=BG, font=FONT_B).pack(side="left")
        tk.Spinbox(dtf, from_=0, to=59, increment=5, width=3, format="%02.0f", wrap=True,
                   textvariable=self.m, font=FONT).pack(side="left")

        # 빠른 선택
        qf = tk.Frame(f, bg=BG)
        qf.grid(row=1, column=1, sticky="w", pady=(2, 6))
        for text, delta in (("+10분", 10), ("+30분", 30), ("+1시간", 60), ("+3시간", 180)):
            btn(qf, text, lambda d=delta: self.set_dt(now() + dt.timedelta(minutes=d))).pack(side="left", padx=(0, 3))
        btn(qf, "내일 이 시간", self.tomorrow).pack(side="left")

        # 회원
        lab("회원", 2)
        self.members = [(None, "(회원 없음)")] + [
            (r["id"], f'{r["name"] or "(이름없음)"}  {r["phone"] or ""}')
            for r in self.db.q("SELECT * FROM members ORDER BY name")]
        self.mem_cb = ttk.Combobox(f, values=[m[1] for m in self.members], state="readonly", font=FONT)
        self.mem_cb.grid(row=2, column=1, sticky="ew", pady=4)

        # 제목 / 내용
        lab("제목", 3)
        self.title_var = tk.StringVar()
        tk.Entry(f, textvariable=self.title_var, font=FONT).grid(row=3, column=1, sticky="ew", pady=4)
        lab("내용", 4)
        self.content = tk.Text(f, height=6, wrap="word", font=FONT, relief="solid", bd=1)
        self.content.grid(row=4, column=1, sticky="nsew", pady=4)
        f.rowconfigure(4, weight=1)

        # 옵션
        of = tk.Frame(f, bg=BG)
        of.grid(row=5, column=1, sticky="w", pady=4)
        self.alarm_var, self.done_var = tk.IntVar(value=1), tk.IntVar(value=0)
        tk.Checkbutton(of, text="시간 되면 팝업 알림 (+폰 알림)", variable=self.alarm_var, bg=BG, font=FONT).pack(side="left")
        tk.Checkbutton(of, text="완료", variable=self.done_var, bg=BG, font=FONT).pack(side="left", padx=10)

        # 버튼
        bf = tk.Frame(f, bg=BG)
        bf.grid(row=6, column=0, columnspan=2, sticky="e", pady=(8, 0))
        if self.row:
            btn(bf, "삭제", self.delete).pack(side="left", padx=3)
        btn(bf, "취소", self.destroy).pack(side="left", padx=3)
        btn(bf, "저장 (Ctrl+S)", self.save, primary=True).pack(side="left", padx=3)
        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())

        # 값 채우기 (Spinbox 생성 후에 넣어야 초기화되지 않음)
        if self.row:
            self.set_dt(parse_dt(self.row["date"], self.row["time"]))
            self.title_var.set(self.row["title"] or "")
            self.content.insert("1.0", self.row["content"] or "")
            self.alarm_var.set(self.row["alarm"])
            self.done_var.set(self.row["done"])
            member_id = self.row["member_id"]
        else:
            if date and date != dt.date.today().isoformat():
                self.set_dt(dt.datetime.strptime(date + " 10:00", "%Y-%m-%d %H:%M"))
            else:
                self.set_dt((now() + dt.timedelta(hours=1)).replace(minute=0))
            self.title_var.set(title_default)
        idx = next((i for i, m in enumerate(self.members) if m[0] == member_id), 0)
        self.mem_cb.current(idx)
        self.grab_set()

    def set_dt(self, x):
        self.date_var.set(x.strftime("%Y-%m-%d"))
        self.h.set(f"{x.hour:02d}")
        self.m.set(f"{x.minute:02d}")

    def current_dt(self):
        return parse_dt(self.date_var.get().strip(), f"{int(self.h.get()):02d}:{int(self.m.get()):02d}")

    def tomorrow(self):
        try:
            self.set_dt(self.current_dt() + dt.timedelta(days=1))
        except Exception:
            self.set_dt(now() + dt.timedelta(days=1))

    def save(self):
        try:
            when = self.current_dt()
        except Exception:
            messagebox.showerror("입력 오류", "날짜는 2026-10-12, 시간은 0~23 / 0~59 형식으로 입력해주세요.", parent=self)
            return
        title = self.title_var.get().strip() or "(제목 없음)"
        i = self.mem_cb.current()
        mid = self.members[i][0] if i >= 0 else None
        d, t = when.strftime("%Y-%m-%d"), when.strftime("%H:%M")
        notified = 0 if when > now() else 1  # 지난 시간으로 저장하면 알림 안 울림
        vals = (d, t, title, self.content.get("1.0", "end-1c"), mid,
                self.alarm_var.get(), notified, self.done_var.get())
        if self.row:
            self.db.x("UPDATE schedules SET date=?,time=?,title=?,content=?,member_id=?,alarm=?,notified=?,done=? "
                      "WHERE id=?", vals + (self.sid,))
        else:
            self.db.x("INSERT INTO schedules(date,time,title,content,member_id,alarm,notified,done) "
                      "VALUES(?,?,?,?,?,?,?,?)", vals)
        self.app.refresh_all()
        if self.on_saved:
            self.on_saved()
        self.destroy()

    def delete(self):
        if messagebox.askyesno("삭제", "이 일정을 삭제할까요?", parent=self):
            self.db.x("DELETE FROM schedules WHERE id=?", (self.sid,))
            self.app.refresh_all()
            if self.on_saved:
                self.on_saved()
            self.destroy()


# ───────────────────────── 회원 관리 팝업 ─────────────────────────
class MemberDialog(tk.Toplevel):
    def __init__(self, app, mid=None):
        super().__init__(app.root)
        self.app, self.db, self.mid = app, app.db, mid
        self.configure(bg=BG)
        self.geometry("660x640")
        self.minsize(480, 460)

        top = tk.Frame(self, bg=BG, padx=12, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT_B, bg=BG).grid(row=0, column=0, sticky="w")
        self.name_var, self.phone_var = tk.StringVar(), tk.StringVar()
        self.name_entry = tk.Entry(top, textvariable=self.name_var, width=18, font=(F, 12))
        self.name_entry.grid(row=0, column=1, padx=(6, 18))
        tk.Label(top, text="휴대폰", font=FONT_B, bg=BG).grid(row=0, column=2, sticky="w")
        tk.Entry(top, textvariable=self.phone_var, width=18, font=(F, 12)).grid(row=0, column=3, padx=6)
        self.info_lbl = tk.Label(top, font=FONT_S, fg="#666", bg=BG)
        self.info_lbl.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # 상담 내용
        mf = tk.LabelFrame(self, text=" 상담 내용 정리 ", font=FONT_B, bg=BG, padx=6, pady=6)
        mf.pack(fill="both", expand=True, padx=12)
        bar = tk.Frame(mf, bg=BG)
        bar.pack(fill="x", pady=(0, 4))
        btn(bar, "🕒 현재시간 입력 (F5)", self.insert_stamp).pack(side="left")
        tk.Label(bar, text="  줄마다 날짜를 찍고 내용을 이어 쓰세요", font=FONT_S, fg="#777", bg=BG).pack(side="left")
        tf = tk.Frame(mf)
        tf.pack(fill="both", expand=True)
        self.memo = tk.Text(tf, wrap="word", font=FONT, undo=True, relief="solid", bd=1)
        sb = ttk.Scrollbar(tf, command=self.memo.yview)
        self.memo.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.memo.pack(side="left", fill="both", expand=True)

        # 재통화 / 예약
        rf = tk.LabelFrame(self, text=" 재통화 · 예약 알림 ", font=FONT_B, bg=BG, padx=6, pady=6)
        rf.pack(fill="x", padx=12, pady=(8, 0))
        rb = tk.Frame(rf, bg=BG)
        rb.pack(fill="x", pady=(0, 4))
        btn(rb, "+ 재통화 예약", self.add_res, primary=True).pack(side="left")
        btn(rb, "수정", self.edit_res).pack(side="left", padx=3)
        btn(rb, "완료/해제", self.toggle_res).pack(side="left")
        cols = ("when", "title", "state")
        self.res = ttk.Treeview(rf, columns=cols, show="headings", height=4)
        for c, t, w in (("when", "일시", 140), ("title", "제목", 300), ("state", "상태", 80)):
            self.res.heading(c, text=t)
            self.res.column(c, width=w, anchor="w" if c == "title" else "center", stretch=(c == "title"))
        self.res.tag_configure("done", foreground="#999")
        self.res.pack(fill="x")
        self.res.bind("<Double-1>", lambda e: self.edit_res())

        # 하단
        bf = tk.Frame(self, bg=BG, padx=12, pady=10)
        bf.pack(fill="x")
        btn(bf, "회원 삭제", self.delete).pack(side="left")
        btn(bf, "닫기", self.on_close).pack(side="right", padx=3)
        btn(bf, "저장 (Ctrl+S)", self.save, primary=True).pack(side="right", padx=3)

        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<F5>", lambda e: self.insert_stamp())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.load()
        self.name_entry.focus_set()

    def load(self):
        row = self.db.one("SELECT * FROM members WHERE id=?", (self.mid,)) if self.mid else None
        self.name_var.set(row["name"] if row else "")
        self.phone_var.set(row["phone"] if row else "")
        self.memo.delete("1.0", "end")
        self.memo.insert("1.0", row["memo"] if row else "")
        self.memo.edit_reset()
        self.orig = self.values()
        self.title(f"회원 관리 - {row['name']}" if row else "새 회원 등록")
        self.info_lbl.config(text=f"등록 {row['created'][:16]}   ·   수정 {row['updated'][:16]}" if row else "새 회원")
        self.load_res()

    def values(self):
        return (self.name_var.get().strip(), self.phone_var.get().strip(), self.memo.get("1.0", "end-1c"))

    def load_res(self):
        self.res.delete(*self.res.get_children())
        if not self.mid:
            return
        for r in self.db.q("SELECT * FROM schedules WHERE member_id=? ORDER BY done, date, time", (self.mid,)):
            self.res.insert("", "end", iid=str(r["id"]), values=(f'{r["date"]} {r["time"]}', r["title"], state_text(r)),
                            tags=("done",) if r["done"] else ())

    def insert_stamp(self):
        content = self.memo.get("1.0", "end-1c")
        prefix = "" if (content == "" or content.endswith("\n")) else "\n"
        self.memo.insert("end", f"{prefix}{stamp()} ")
        self.memo.mark_set("insert", "end")
        self.memo.see("end")
        self.memo.focus_set()
        return "break"

    def save(self):
        name, phone, memo = self.values()
        if not name and not phone:
            messagebox.showwarning("확인", "이름이나 전화번호 중 하나는 입력해주세요.", parent=self)
            return False
        if self.mid:
            self.db.x("UPDATE members SET name=?,phone=?,memo=?,updated=? WHERE id=?",
                      (name, phone, memo, stamp(), self.mid))
        else:
            self.mid = self.db.x("INSERT INTO members(name,phone,memo,created,updated) VALUES(?,?,?,?,?)",
                                 (name, phone, memo, stamp(), stamp()))
            self.app.member_windows[self.mid] = self
        self.load()
        self.app.refresh_members(select=self.mid)
        self.app.refresh_day()
        return True

    def add_res(self):
        if not self.mid or self.values() != self.orig:
            if not self.save():
                return
        ScheduleDialog(self.app, member_id=self.mid, title_default=f"재통화: {self.name_var.get().strip()}",
                       on_saved=self.load_res)

    def selected_res(self):
        sel = self.res.selection()
        return int(sel[0]) if sel else None

    def edit_res(self):
        sid = self.selected_res()
        if sid:
            ScheduleDialog(self.app, sid=sid, on_saved=self.load_res)

    def toggle_res(self):
        sid = self.selected_res()
        if sid:
            self.db.x("UPDATE schedules SET done=1-done WHERE id=?", (sid,))
            self.load_res()
            self.app.refresh_all()

    def delete(self):
        if not self.mid:
            self.destroy()
            return
        if messagebox.askyesno("회원 삭제", "이 회원과 연결된 예약까지 모두 삭제할까요?", parent=self):
            self.db.x("DELETE FROM schedules WHERE member_id=?", (self.mid,))
            self.db.x("DELETE FROM members WHERE id=?", (self.mid,))
            self.app.member_windows.pop(self.mid, None)
            self.app.refresh_all()
            self.destroy()

    def on_close(self):
        if self.values() != self.orig:
            ans = messagebox.askyesnocancel("저장", "변경 내용을 저장할까요?", parent=self)
            if ans is None:
                return
            if ans and not self.save():
                return
        self.app.member_windows.pop(self.mid, None)
        self.destroy()


# ───────────────────────── 키워드 메모 창 ─────────────────────────
class NoteWindow(tk.Toplevel):
    def __init__(self, app, title):
        super().__init__(app.root)
        self.app, self.db, self.note_title = app, app.db, title
        row = self.db.one("SELECT * FROM notes WHERE title=?", (title,))
        if not row:
            self.db.x("INSERT INTO notes(title,content,updated) VALUES(?,?,?)", (title, "", stamp()))
        self.title(f"📝 {title}")
        self.configure(bg=BG)
        self.geometry("520x420")
        self.minsize(240, 110)
        self.mini, self._geo, self._job = False, None, None

        bar = tk.Frame(self, bg=BG, padx=6, pady=4)
        bar.pack(fill="x")
        tk.Label(bar, text=title, font=FONT_B, bg=BG).pack(side="left")
        self.status = tk.Label(bar, text="저장됨", font=FONT_S, fg="#16a34a", bg=BG)
        self.status.pack(side="left", padx=8)
        btn(bar, "삭제", self.delete).pack(side="right", padx=2)
        self.mini_btn = btn(bar, "▁ 작게", self.toggle_mini)
        self.mini_btn.pack(side="right", padx=2)
        self.top_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="항상 위", variable=self.top_var, bg=BG, font=FONT_S,
                       command=lambda: self.attributes("-topmost", self.top_var.get())).pack(side="right")

        tf = tk.Frame(self)
        tf.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.txt = tk.Text(tf, wrap="word", font=FONT, undo=True, relief="solid", bd=1)
        sb = ttk.Scrollbar(tf, command=self.txt.yview)
        self.txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.insert("1.0", row["content"] if row else "")
        self.txt.edit_reset()
        self.txt.edit_modified(False)
        self.txt.bind("<<Modified>>", self.on_mod)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.txt.focus_set()

    def on_mod(self, _=None):
        if not self.txt.edit_modified():
            return
        self.txt.edit_modified(False)
        self.status.config(text="입력 중…", fg="#d97706")
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(800, self.save)

    def save(self):
        self._job = None
        self.db.x("UPDATE notes SET content=?, updated=? WHERE title=?",
                  (self.txt.get("1.0", "end-1c"), stamp(), self.note_title))
        if self.winfo_exists():
            self.status.config(text="저장됨", fg="#16a34a")

    def toggle_mini(self):
        if not self.mini:
            self._geo = self.geometry()
            self.geometry("300x140")
            self.mini_btn.config(text="□ 크게")
        else:
            self.geometry(self._geo or "520x420")
            self.mini_btn.config(text="▁ 작게")
        self.mini = not self.mini

    def delete(self):
        if messagebox.askyesno("메모 삭제", f"'{self.note_title}' 메모를 삭제할까요?", parent=self):
            if self._job:
                self.after_cancel(self._job)
            self.db.x("DELETE FROM notes WHERE title=?", (self.note_title,))
            self.app.note_windows.pop(self.note_title, None)
            self.app.refresh_notes()
            self.destroy()

    def close(self):
        if self._job:
            self.after_cancel(self._job)
        self.save()
        self.app.note_windows.pop(self.note_title, None)
        self.destroy()


# ───────────────────────── 알림 팝업 ─────────────────────────
class AlarmPopup(tk.Toplevel):
    def __init__(self, app, row, offset=0):
        super().__init__(app.root)
        self.app, self.sid, self.member_id = app, row["id"], row["member_id"]
        bg = "#fff7e6"
        self.title("⏰ 예약 알림")
        self.configure(bg=bg)
        self.attributes("-topmost", True)
        member = app.db.one("SELECT * FROM members WHERE id=?", (self.member_id,)) if self.member_id else None

        tk.Label(self, text="⏰ 예약 알림", font=(F, 16, "bold"), fg="#c2410c", bg=bg).pack(pady=(16, 2))
        tk.Label(self, text=f'{row["date"]} {row["time"]}', font=FONT_B, fg="#555", bg=bg).pack()
        tk.Label(self, text=row["title"], font=(F, 14, "bold"), wraplength=380, bg=bg).pack(pady=(8, 2), padx=16)
        if member:
            tk.Label(self, text=f'{member["name"]}   {member["phone"]}', font=(F, 13), fg=ACCENT, bg=bg).pack()
        if (row["content"] or "").strip():
            tk.Label(self, text=row["content"], font=FONT, wraplength=380, justify="left", bg=bg).pack(pady=6, padx=16)

        bf = tk.Frame(self, bg=bg)
        bf.pack(pady=(10, 16))
        btn(bf, "확인 (완료)", self.done, primary=True).pack(side="left", padx=3)
        btn(bf, "10분 뒤", lambda: self.snooze(10)).pack(side="left", padx=3)
        btn(bf, "30분 뒤", lambda: self.snooze(30)).pack(side="left", padx=3)
        if member:
            btn(bf, "회원 열기", self.open_member).pack(side="left", padx=3)

        self.update_idletasks()
        w, h = max(self.winfo_reqwidth(), 420), self.winfo_reqheight()
        x = self.winfo_screenwidth() - w - 30 - offset
        y = 60 + offset
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.lift()
        self.focus_force()
        self.beep(3)

    def beep(self, n):
        if n <= 0 or not self.winfo_exists():
            return
        if winsound:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        else:
            self.bell()
        self.after(700, lambda: self.beep(n - 1))

    def done(self):
        self.app.db.x("UPDATE schedules SET done=1 WHERE id=?", (self.sid,))
        self.app.refresh_all()
        self.destroy()

    def snooze(self, minutes):
        t = now() + dt.timedelta(minutes=minutes)
        self.app.db.x("UPDATE schedules SET date=?, time=?, notified=0 WHERE id=?",
                      (t.strftime("%Y-%m-%d"), t.strftime("%H:%M"), self.sid))
        self.app.refresh_all()
        self.destroy()

    def open_member(self):
        self.app.open_member(self.member_id)
        self.destroy()


# ───────────────────────── 폰 알림 설정 ─────────────────────────
class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app, self.db = app, app.db
        self.title("📱 폰 알림 설정 (ntfy)")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app.root)
        f = tk.Frame(self, bg=BG, padx=16, pady=14)
        f.pack(fill="both", expand=True)

        guide = ("① 휴대폰에 'ntfy' 앱 설치 (Play 스토어 / App Store, 무료)\n"
                 "② 앱에서 [+] → 아래 '토픽 이름'을 똑같이 입력해 구독\n"
                 "③ [테스트 발송]을 눌러 폰에 알림이 오는지 확인\n\n"
                 "※ 토픽 이름을 아는 사람은 누구나 알림을 볼 수 있어요.\n"
                 "    남이 추측하기 어려운 이름을 그대로 쓰세요.\n"
                 + ("※ 서버에서 발송하므로 PC가 꺼져 있어도 알림이 갑니다.\n"
                    "    (예약을 만들거나 바꾼 뒤 PC가 인터넷에 연결돼 있어야 서버에 반영돼요)"
                    if WORKER_URL else "※ PC 프로그램이 켜져 있어야 알림이 발송됩니다."))
        tk.Label(f, text=guide, justify="left", font=FONT, bg=BG).grid(row=0, column=0, columnspan=2, sticky="w")

        topic = self.db.get("ntfy_topic") or "wd-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        self.en = tk.IntVar(value=int(self.db.get("ntfy_on", "0")))
        self.server = tk.StringVar(value=self.db.get("ntfy_server", "https://ntfy.sh"))
        self.topic = tk.StringVar(value=topic)

        tk.Checkbutton(f, text="알림 시간에 폰으로도 보내기", variable=self.en, font=FONT_B, bg=BG)\
            .grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 6))
        if not WORKER_URL:
            tk.Label(f, text="서버", font=FONT, bg=BG).grid(row=2, column=0, sticky="w")
            tk.Entry(f, textvariable=self.server, width=34, font=FONT).grid(row=2, column=1, sticky="w", pady=3)
        tk.Label(f, text="토픽 이름", font=FONT, bg=BG).grid(row=3, column=0, sticky="w")
        tk.Entry(f, textvariable=self.topic, width=34, font=(F, 11, "bold")).grid(row=3, column=1, sticky="w", pady=3)

        bf = tk.Frame(f, bg=BG)
        bf.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.test_btn = btn(bf, "테스트 발송", self.test)
        self.test_btn.pack(side="left", padx=3)
        btn(bf, "닫기", self.destroy).pack(side="left", padx=3)
        btn(bf, "저장", self.save, primary=True).pack(side="left", padx=3)

    def save(self):
        self.db.set("ntfy_on", str(self.en.get()))
        self.db.set("ntfy_server", self.server.get().strip() or "https://ntfy.sh")
        self.db.set("ntfy_topic", self.topic.get().strip())
        self.app.request_sync()
        self.app.update_status()
        messagebox.showinfo("저장", "저장했습니다.", parent=self)

    def test(self):
        topic = self.topic.get().strip()
        if not topic:
            return
        self.test_btn.config(state="disabled", text="발송 중…")
        res = {}

        def run():
            try:
                push_sync(self.server.get(), topic, "업무 다이어리", "테스트 알림입니다 ✅")
                res["ok"] = True
            except Exception as e:
                res["err"] = str(e)

        threading.Thread(target=run, daemon=True).start()

        def poll():
            if not res:
                self.after(200, poll)
                return
            self.test_btn.config(state="normal", text="테스트 발송")
            if res.get("ok"):
                messagebox.showinfo("발송 완료", "폰에 알림이 왔는지 확인해보세요.\n안 오면 앱에서 토픽 이름이 같은지 확인!", parent=self)
            else:
                messagebox.showerror("발송 실패", res.get("err", ""), parent=self)

        poll()


# ───────────────────────── 어깨동무 가져오기 미리보기 ─────────────────────────
class ImportDialog(tk.Toplevel):
    def __init__(self, app, data):
        super().__init__(app.root)
        self.app, self.db = app, app.db
        self.title("어깨동무에서 가져오기")
        self.configure(bg=BG)
        self.geometry("560x560")
        self.minsize(440, 420)

        # 같은 전화번호 회원이 이미 있는지
        d = digits(data["phone"])
        self.existing = None
        if d:
            for r in self.db.q("SELECT * FROM members"):
                if digits(r["phone"]) == d:
                    self.existing = r
                    break

        f = tk.Frame(self, bg=BG, padx=12, pady=10)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        self.name_var = tk.StringVar(value=data["name"])
        self.phone_var = tk.StringVar(value=data["phone"])
        tk.Label(f, text="이름", font=FONT_B, bg=BG).grid(row=0, column=0, sticky="w")
        tk.Entry(f, textvariable=self.name_var, font=(F, 12)).grid(row=0, column=1, sticky="ew", pady=3)
        tk.Label(f, text="휴대폰", font=FONT_B, bg=BG).grid(row=1, column=0, sticky="w")
        tk.Entry(f, textvariable=self.phone_var, font=(F, 12)).grid(row=1, column=1, sticky="ew", pady=3)
        tk.Label(f, text="내용", font=FONT_B, bg=BG).grid(row=2, column=0, sticky="nw", pady=3)
        mf = tk.Frame(f)
        mf.grid(row=2, column=1, sticky="nsew", pady=3)
        self.memo = tk.Text(mf, wrap="word", font=FONT, relief="solid", bd=1)
        msb = ttk.Scrollbar(mf, command=self.memo.yview)
        self.memo.config(yscrollcommand=msb.set)
        msb.pack(side="right", fill="y")
        self.memo.pack(side="left", fill="both", expand=True)
        f.rowconfigure(2, weight=1)
        lines = len(data["memo"].splitlines())
        tk.Label(f, text=f"메모 {lines}줄 · {len(data['memo'])}자 전체를 가져왔습니다", font=FONT_S,
                 fg="#16a34a", bg=BG).grid(row=5, column=1, sticky="w")
        body = data["memo"]
        if data["keyword"]:
            body = f'검색어: {data["keyword"]}\n' + body
        self.memo.insert("1.0", body)

        self.mode = tk.StringVar(value="overwrite")
        if self.existing:
            ef = tk.Frame(f, bg="#fff7e6", padx=8, pady=6)
            ef.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            tk.Label(ef, text=f'이미 등록된 회원입니다: {self.existing["name"]} {self.existing["phone"]}',
                     font=FONT_B, bg="#fff7e6").pack(anchor="w")
            tk.Radiobutton(ef, text="어깨동무 내용으로 덮어쓰기", variable=self.mode, value="overwrite",
                           bg="#fff7e6", font=FONT).pack(anchor="w")
            tk.Radiobutton(ef, text="기존 내용 아래에 이어 붙이기", variable=self.mode, value="append",
                           bg="#fff7e6", font=FONT).pack(anchor="w")

        bf = tk.Frame(f, bg=BG)
        bf.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        btn(bf, "취소", self.destroy).pack(side="left", padx=3)
        btn(bf, "저장하고 열기 (Enter)", self.save, primary=True).pack(side="left", padx=3)
        self.bind("<Return>", lambda e: self.save() if e.widget is not self.memo else None)
        self.bind("<Escape>", lambda e: self.destroy())

        # 다른 프로그램 위로 확실히 띄우기
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.after(400, lambda: self.winfo_exists() and self.attributes("-topmost", False))

    def save(self):
        name, phone = self.name_var.get().strip(), self.phone_var.get().strip()
        memo = self.memo.get("1.0", "end-1c").strip()
        if not name and not phone:
            messagebox.showwarning("확인", "이름이나 전화번호가 비어 있습니다.", parent=self)
            return
        if self.existing:
            mid = self.existing["id"]
            if self.mode.get() == "append":
                old = (self.existing["memo"] or "").rstrip()
                memo = f"{old}\n\n── 어깨동무 가져옴 {stamp()[:16]} ──\n{memo}" if old else memo
            self.db.x("UPDATE members SET name=?, phone=?, memo=?, updated=? WHERE id=?",
                      (name or self.existing["name"], phone, memo, stamp(), mid))
            w = self.app.member_windows.pop(mid, None)   # 열려 있던 창은 새 내용으로 다시 열기
            if w and w.winfo_exists():
                w.destroy()
        else:
            mid = self.db.x("INSERT INTO members(name,phone,memo,created,updated) VALUES(?,?,?,?,?)",
                            (name, phone, memo, stamp(), stamp()))
        self.app.search_var.set("")
        self.app.refresh_members(select=mid)
        self.destroy()
        self.app.open_member(mid)


# ───────────────────────── 메인 화면 ─────────────────────────
class App:
    def __init__(self, root):
        self.root, self.db = root, DB(DB_PATH)
        self.note_windows, self.member_windows = {}, {}
        today = dt.date.today()
        self.year, self.month, self.sel_date = today.year, today.month, today
        self._diary_date, self._diary_job, self._diary_dirty, self._loading = None, None, False, False

        self._sync_job, self._sync_state = None, ""
        self.device_id = self.db.get("device_id")
        if not self.device_id:
            self.device_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
            self.db.set("device_id", self.device_id)
        root.title(f"{APP_TITLE}  v{APP_VERSION}")
        root.geometry("1440x880")
        root.minsize(1100, 680)
        root.configure(bg=BG)
        self._style()
        self._build_toolbar()
        self._build_status()
        self._build_body()
        root.protocol("WM_DELETE_WINDOW", self.on_quit)
        root.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.refresh_all()
        self.refresh_notes()
        self.tick()
        root.after(1500, self.check_alarms)
        self.hk_queue = queue.Queue()
        self.hotkey_ok = False
        if IS_WIN:
            self.hotkey_ok = True
            threading.Thread(target=hotkey_loop, args=(self.hk_queue,), daemon=True).start()
            root.after(200, self.poll_hotkey)
        self.request_sync()
        root.after(4000, self.check_update)
        self._update_timer()

    def _update_timer(self):   # 켜둔 채로 지내도 6시간마다 업데이트 확인
        self.root.after(6 * 3600 * 1000, lambda: (self.check_update(), self._update_timer()))

    # ---------- 화면 구성 ----------
    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("Treeview", font=FONT, rowheight=26, background="white", fieldbackground="white")
        s.configure("Treeview.Heading", font=FONT_B, background="#e8edf5")
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        s.configure("TPanedwindow", background=BG)
        s.configure("TCombobox", padding=3)

    def _build_toolbar(self):
        tb = tk.Frame(self.root, bg="white", padx=10, pady=8, highlightthickness=1, highlightbackground=LINE)
        tb.pack(fill="x")
        tk.Label(tb, text="키워드 / 제목", font=FONT_B, bg="white").pack(side="left")
        self.note_var = tk.StringVar()
        self.note_cb = ttk.Combobox(tb, textvariable=self.note_var, width=30, font=FONT)
        self.note_cb.pack(side="left", padx=6)
        self.note_cb.bind("<Return>", lambda e: self.open_note())
        self.note_cb.bind("<<ComboboxSelected>>", lambda e: self.open_note())
        btn(tb, "📝 메모 열기", self.open_note, primary=True).pack(side="left")
        tk.Label(tb, text="  (새 제목을 쓰면 새 메모, 목록에서 고르면 기존 메모)", font=FONT_S,
                 fg="#888", bg="white").pack(side="left")

        btn(tb, "⟳ 업데이트", lambda: self.check_update(manual=True)).pack(side="right", padx=(6, 0))
        btn(tb, "📱 폰 알림 설정", lambda: SettingsDialog(self)).pack(side="right")
        btn(tb, f"📥 어깨동무 가져오기 ({HOTKEY_TEXT})", self.import_ekdm).pack(side="right", padx=6)
        self.clock = tk.Label(tb, font=FONT_B, fg="#333", bg="white")
        self.clock.pack(side="right", padx=14)

    def _build_status(self):
        sb = tk.Frame(self.root, bg="#e8edf5", padx=10, pady=4)
        sb.pack(fill="x", side="bottom")
        self.status = tk.Label(sb, font=FONT_S, bg="#e8edf5", fg="#333", anchor="w")
        self.status.pack(fill="x")

    def _build_body(self):
        body = ttk.PanedWindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=6)
        left, right = tk.Frame(body, bg=BG), tk.Frame(body, bg=BG)
        body.add(left, weight=3)
        body.add(right, weight=2)

        lp = ttk.PanedWindow(left, orient="vertical")
        lp.pack(fill="both", expand=True)
        cal, day = tk.Frame(lp, bg=BG), tk.Frame(lp, bg=BG)
        lp.add(cal, weight=3)
        lp.add(day, weight=2)
        self._build_calendar(cal)
        self._build_day(day)

        rp = ttk.PanedWindow(right, orient="vertical")
        rp.pack(fill="both", expand=True, padx=(8, 0))
        ml, sm = tk.Frame(rp, bg=BG), tk.Frame(rp, bg=BG)
        rp.add(ml, weight=3)
        rp.add(sm, weight=2)
        self._build_members(ml)
        self._build_summary(sm)

    def _build_calendar(self, p):
        yr = tk.Frame(p, bg=BG)
        yr.pack(fill="x", pady=(0, 4))
        btn(yr, "◀", lambda: self.change_year(-1)).pack(side="left")
        self.year_lbl = tk.Label(yr, font=FONT_T, bg=BG, width=7)
        self.year_lbl.pack(side="left")
        btn(yr, "▶", lambda: self.change_year(1)).pack(side="left")
        btn(yr, "오늘", self.go_today).pack(side="left", padx=8)
        self.month_lbl = tk.Label(yr, font=(F, 15, "bold"), bg=BG, fg=ACCENT)
        self.month_lbl.pack(side="right", padx=6)

        mrow = tk.Frame(p, bg=BG)
        mrow.pack(fill="x", pady=(0, 6))
        self.month_btns = []
        for m in range(1, 13):
            b = tk.Button(mrow, text=f"{m}월", font=FONT_B, relief="flat", cursor="hand2",
                          command=lambda m=m: self.set_month(m))
            b.pack(side="left", fill="x", expand=True, padx=1)
            self.month_btns.append(b)

        grid = tk.Frame(p, bg=LINE)
        grid.pack(fill="both", expand=True)
        for c in range(7):
            grid.columnconfigure(c, weight=1, uniform="c")
            fg = "#d33" if c == 0 else ("#2563eb" if c == 6 else "#333")
            tk.Label(grid, text=WEEK[c], font=FONT_B, bg="#e8edf5", fg=fg).grid(row=0, column=c, sticky="nsew", padx=1, pady=1)
        for r in range(1, 7):
            grid.rowconfigure(r, weight=1, uniform="r")
        self.cells, self.cell_dates = [], [None] * 42
        for i in range(42):
            f = tk.Frame(grid, bg="white", cursor="hand2")
            f.grid(row=1 + i // 7, column=i % 7, sticky="nsew", padx=1, pady=1)
            num = tk.Label(f, anchor="w", bg="white", font=FONT_B)
            num.pack(fill="x", padx=4, pady=(2, 0))
            info = tk.Label(f, anchor="nw", justify="left", bg="white", font=FONT_S, fg="#444")
            info.pack(fill="both", expand=True, padx=4)
            for w in (f, num, info):
                w.bind("<Button-1>", lambda e, i=i: self.on_cell(i))
                w.bind("<Double-Button-1>", lambda e, i=i: self.on_cell(i, add=True))
                w.bind("<MouseWheel>", self.on_wheel)
            self.cells.append((f, num, info))
        tk.Label(p, text="날짜 클릭: 그날 일정 보기 · 더블클릭: 일정 추가 · 마우스 휠: 월 이동",
                 font=FONT_S, fg="#888", bg=BG).pack(anchor="w", pady=(3, 0))

    def _build_day(self, p):
        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill="x", pady=(8, 4))
        self.day_lbl = tk.Label(hdr, font=FONT_T, bg=BG)
        self.day_lbl.pack(side="left")
        btn(hdr, "삭제", self.day_delete).pack(side="right", padx=2)
        btn(hdr, "완료/해제", self.day_toggle).pack(side="right", padx=2)
        btn(hdr, "수정", self.day_edit).pack(side="right", padx=2)
        btn(hdr, "+ 일정 추가", self.day_add, primary=True).pack(side="right", padx=2)

        mid = tk.Frame(p, bg=BG)
        mid.pack(fill="both", expand=True)
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(1, weight=1)
        cols = ("time", "title", "member", "state")
        self.day_tree = ttk.Treeview(mid, columns=cols, show="headings", height=5)
        for c, t, w in (("time", "시간", 60), ("title", "제목", 240), ("member", "회원", 110), ("state", "알림", 80)):
            self.day_tree.heading(c, text=t)
            self.day_tree.column(c, width=w, anchor="w" if c == "title" else "center", stretch=(c == "title"))
        self.day_tree.tag_configure("done", foreground="#999")
        self.day_tree.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.day_tree.bind("<Double-1>", lambda e: self.day_edit())

        tk.Label(mid, text="✎ 하루 메모 (자동 저장)", font=FONT_B, bg=BG).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.diary_txt = tk.Text(mid, wrap="word", font=FONT, undo=True, relief="solid", bd=1, height=6)
        self.diary_txt.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        self.diary_txt.bind("<<Modified>>", self.on_diary_mod)

    def _build_members(self, p):
        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill="x", pady=(0, 4))
        tk.Label(hdr, text="👥 집중 관리 회원", font=FONT_T, bg=BG).pack(side="left")
        btn(hdr, "삭제", self.member_delete).pack(side="right", padx=2)
        btn(hdr, "+ 회원 추가", lambda: self.open_member(None), primary=True).pack(side="right", padx=2)

        sr = tk.Frame(p, bg=BG)
        sr.pack(fill="x", pady=(0, 4))
        tk.Label(sr, text="🔍", bg=BG).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh_members())
        self.search_entry = tk.Entry(sr, textvariable=self.search_var, font=FONT, relief="solid", bd=1)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.count_lbl = tk.Label(sr, font=FONT_S, fg="#666", bg=BG)
        self.count_lbl.pack(side="left")

        tf = tk.Frame(p)
        tf.pack(fill="both", expand=True)
        cols = ("name", "phone", "next", "last", "updated")
        self.mem_tree = ttk.Treeview(tf, columns=cols, show="headings")
        for c, t, w in (("name", "이름", 90), ("phone", "전화번호", 115), ("next", "다음 예약", 110),
                        ("last", "최근 내용", 220), ("updated", "수정일", 85)):
            self.mem_tree.heading(c, text=t)
            self.mem_tree.column(c, width=w, anchor="w" if c == "last" else "center", stretch=(c == "last"))
        sb = ttk.Scrollbar(tf, command=self.mem_tree.yview)
        self.mem_tree.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.mem_tree.pack(side="left", fill="both", expand=True)
        self.mem_tree.bind("<<TreeviewSelect>>", lambda e: self.show_summary())
        self.mem_tree.bind("<Double-1>", self.on_member_double)
        self.mem_tree.bind("<Return>", lambda e: self.open_selected_member())

    def _build_summary(self, p):
        tk.Label(p, text="요약  (더블클릭하면 상세 관리 창)", font=FONT_B, bg=BG).pack(anchor="w", pady=(8, 2))
        tf = tk.Frame(p)
        tf.pack(fill="both", expand=True)
        self.summary = tk.Text(tf, wrap="word", font=FONT, relief="solid", bd=1, padx=8, pady=6, bg="white")
        sb = ttk.Scrollbar(tf, command=self.summary.yview)
        self.summary.config(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.summary.pack(side="left", fill="both", expand=True)
        self.summary.tag_configure("h", font=(F, 13, "bold"))
        self.summary.tag_configure("g", foreground="#777", font=FONT_S)
        self.summary.tag_configure("sec", foreground=ACCENT, font=FONT_B)

    # ---------- 새로고침 ----------
    def refresh_all(self):
        self.refresh_calendar()
        self.refresh_day()
        self.refresh_members()
        self.update_status()
        self.request_sync()

    # ---------- 서버(클라우드플레어) 예약 동기화 ----------
    def request_sync(self):
        """일정이 바뀌면 2초 뒤 서버에 '앞으로 울릴 알림 목록' 전체를 보냄"""
        if not WORKER_URL or not hasattr(self, "_sync_job"):
            return
        if self._sync_job:
            self.root.after_cancel(self._sync_job)
        self._sync_job = self.root.after(2000, self.do_sync)

    def do_sync(self):
        self._sync_job = None
        topic = self.db.get("ntfy_topic")
        on = self.db.get("ntfy_on", "0") == "1" and bool(topic)
        alarms = []
        if on:
            nowk = now().strftime("%Y-%m-%d %H:%M")
            for r in self.db.q("SELECT s.*, m.name AS mname, m.phone AS mphone FROM schedules s "
                               "LEFT JOIN members m ON s.member_id=m.id "
                               "WHERE s.alarm=1 AND s.done=0 AND s.notified=0 AND s.date||' '||s.time > ?", (nowk,)):
                msg = f'{r["date"]} {r["time"]}'
                if r["mname"] or r["mphone"]:
                    msg += f'\n{r["mname"] or ""}  {r["mphone"] or ""}'
                if (r["content"] or "").strip():
                    msg += f'\n{r["content"].strip()}'
                alarms.append({"sid": r["id"], "fire_at": int(parse_dt(r["date"], r["time"]).timestamp()),
                               "title": f'⏰ {r["title"]}', "message": msg})
        payload = {"device": self.device_id, "topic": topic or "", "alarms": alarms}

        def run():
            try:
                worker_call("/api/sync", payload)
                self._sync_state = "ok"
            except Exception as e:
                self._sync_state = f"서버 동기화 실패 ({e.__class__.__name__}) — 1분 뒤 재시도"
                self.root.after(60000, self.request_sync)

        threading.Thread(target=run, daemon=True).start()
        self.root.after(3000, self.update_status)

    # ---------- 자동 업데이트 ----------
    def check_update(self, manual=False):
        if not GITHUB_REPO:
            if manual:
                messagebox.showinfo("업데이트", "업데이트 저장소가 설정되지 않았습니다.")
            return
        res = {}

        def run():
            try:
                res["rel"] = http_json(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest")
            except Exception as e:
                res["err"] = str(e)

        threading.Thread(target=run, daemon=True).start()

        def poll():
            if not res:
                self.root.after(300, poll)
                return
            if "err" in res:
                if manual:
                    messagebox.showerror("업데이트", f"확인 실패: {res['err']}")
                return
            rel = res["rel"]
            latest = rel.get("tag_name", "")
            asset = next((a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".exe")), None)
            if ver_tuple(latest) <= ver_tuple(APP_VERSION) or not asset:
                if manual:
                    messagebox.showinfo("업데이트", f"최신 버전입니다. (v{APP_VERSION})")
                return
            if not FROZEN:
                if manual:
                    messagebox.showinfo("업데이트", f"새 버전 {latest} 이 있습니다. (exe 실행 시 자동 설치)")
                return
            notes = (rel.get("body") or "").strip()
            if messagebox.askyesno("업데이트", f"새 버전 {latest} 이 있습니다. (현재 v{APP_VERSION})\n\n"
                                            f"{notes[:400]}\n\n지금 업데이트할까요? (자동으로 다시 켜집니다)"):
                self.install_update(asset["browser_download_url"])

        poll()

    def install_update(self, url):
        exe = sys.executable
        new = exe + ".new"
        win = tk.Toplevel(self.root)
        win.title("업데이트")
        win.configure(bg=BG)
        tk.Label(win, text="새 버전을 내려받는 중입니다…", font=FONT_B, bg=BG, padx=30, pady=20).pack()
        win.attributes("-topmost", True)
        res = {}

        def run():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": f"WorkDiary/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=120) as r, open(new, "wb") as f:
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                res["ok"] = os.path.getsize(new) > 1_000_000
            except Exception as e:
                res["err"] = str(e)

        threading.Thread(target=run, daemon=True).start()

        def poll():
            if not res:
                self.root.after(300, poll)
                return
            win.destroy()
            if not res.get("ok"):
                messagebox.showerror("업데이트", f"다운로드 실패: {res.get('err', '파일이 올바르지 않음')}")
                return
            bat = os.path.join(DATA_DIR, "update.bat")
            with open(bat, "w", encoding="cp949", errors="ignore") as f:
                f.write(f'@echo off\r\n'
                        f'ping 127.0.0.1 -n 3 > nul\r\n'
                        f':retry\r\n'
                        f'move /y "{new}" "{exe}" > nul 2>&1\r\n'
                        f'if errorlevel 1 (ping 127.0.0.1 -n 2 > nul & goto retry)\r\n'
                        f'start "" "{exe}"\r\n'
                        f'del "%~f0"\r\n')
            import subprocess
            subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000)  # 창 없이 실행
            self.quit_now()

        poll()

    def refresh_calendar(self):
        y, m = self.year, self.month
        self.year_lbl.config(text=f"{y}년")
        self.month_lbl.config(text=f"{y}년 {m}월")
        for i, b in enumerate(self.month_btns, 1):
            on = i == m
            b.config(bg=ACCENT if on else "#e3e8f0", fg="white" if on else "#222",
                     activebackground="#1d4ed8" if on else "#cfd6e2")
        days = list(calendar.Calendar(firstweekday=6).itermonthdates(y, m))
        while len(days) < 42:
            days.append(days[-1] + dt.timedelta(days=1))
        start, end = days[0].isoformat(), days[-1].isoformat()
        by = {}
        for r in self.db.q("SELECT date,time,title,done FROM schedules WHERE date BETWEEN ? AND ? ORDER BY time",
                           (start, end)):
            by.setdefault(r["date"], []).append(r)
        diary = {r["date"] for r in self.db.q(
            "SELECT date FROM diary WHERE date BETWEEN ? AND ? AND TRIM(content)<>''", (start, end))}
        today = dt.date.today()
        for i, d in enumerate(days):
            self.cell_dates[i] = d
            f, num, info = self.cells[i]
            inm = d.month == m
            bg = "white" if inm else "#f5f6f8"
            if d == today:
                bg = "#fff3c4"
            if d == self.sel_date:
                bg = "#d6e6ff"
            col = i % 7
            fg = "#d33" if col == 0 else ("#2563eb" if col == 6 else "#222")
            if not inm:
                fg = "#bbb"
            mark = " ✎" if d.isoformat() in diary else ""
            num.config(text=f"{d.day}{mark}" + ("  오늘" if d == today else ""), bg=bg, fg=fg)
            items = by.get(d.isoformat(), [])
            lines = [("✓" if r["done"] else "• ") + short(f'{r["time"]} {r["title"]}', 14) for r in items[:3]]
            if len(items) > 3:
                lines.append(f"  +{len(items) - 3}건 더")
            info.config(text="\n".join(lines), bg=bg, fg="#999" if not inm else "#444")
            f.config(bg=bg)

    def refresh_day(self):
        d = self.sel_date
        ds = d.isoformat()
        self.day_lbl.config(text=f"📅 {d.month}월 {d.day}일 ({wd_name(d)}) 일정")
        self.day_tree.delete(*self.day_tree.get_children())
        for r in self.db.q("SELECT s.*, m.name AS mname FROM schedules s LEFT JOIN members m ON s.member_id=m.id "
                           "WHERE s.date=? ORDER BY s.time", (ds,)):
            self.day_tree.insert("", "end", iid=str(r["id"]),
                                 values=(r["time"], r["title"], r["mname"] or "", state_text(r)),
                                 tags=("done",) if r["done"] else ())
        if self._diary_date != ds:
            self.flush_diary()
            row = self.db.one("SELECT content FROM diary WHERE date=?", (ds,))
            self._loading = True
            self.diary_txt.delete("1.0", "end")
            self.diary_txt.insert("1.0", row["content"] if row else "")
            self.diary_txt.edit_reset()
            self.diary_txt.edit_modified(False)
            self._loading = False
            self._diary_date = ds

    def refresh_members(self, select=None):
        if select is None:
            sel = self.mem_tree.selection()
            select = int(sel[0]) if sel else None
        kw = self.search_var.get().strip()
        sql, args = "SELECT * FROM members", ()
        if kw:
            sql += " WHERE name LIKE ? OR phone LIKE ? OR memo LIKE ?"
            args = (f"%{kw}%",) * 3
        rows = self.db.q(sql + " ORDER BY updated DESC", args)
        nowk = now().strftime("%Y-%m-%d %H:%M")
        nxt = {r["member_id"]: r["nx"] for r in self.db.q(
            "SELECT member_id, MIN(date||' '||time) AS nx FROM schedules "
            "WHERE done=0 AND member_id IS NOT NULL AND date||' '||time >= ? GROUP BY member_id", (nowk,))}
        self.mem_tree.delete(*self.mem_tree.get_children())
        for r in rows:
            lines = [l.strip() for l in (r["memo"] or "").splitlines() if l.strip()]
            n = nxt.get(r["id"])
            self.mem_tree.insert("", "end", iid=str(r["id"]), values=(
                r["name"], r["phone"], n[5:] if n else "", short(lines[-1] if lines else "", 40),
                (r["updated"] or "")[:10]))
        self.count_lbl.config(text=f"{len(rows)}명")
        if select and self.mem_tree.exists(str(select)):
            self.mem_tree.selection_set(str(select))
            self.mem_tree.see(str(select))
        self.show_summary()

    def show_summary(self):
        t = self.summary
        t.config(state="normal")
        t.delete("1.0", "end")
        sel = self.mem_tree.selection()
        m = self.db.one("SELECT * FROM members WHERE id=?", (int(sel[0]),)) if sel else None
        if m:
            t.insert("end", f'{m["name"] or "(이름없음)"}    {m["phone"] or ""}\n', "h")
            t.insert("end", f'등록 {(m["created"] or "")[:16]}  ·  수정 {(m["updated"] or "")[:16]}\n\n', "g")
            t.insert("end", "▶ 예정된 예약\n", "sec")
            ups = self.db.q("SELECT * FROM schedules WHERE member_id=? AND done=0 ORDER BY date,time", (m["id"],))
            if ups:
                for r in ups:
                    t.insert("end", f'   {r["date"][5:]} {r["time"]}   {r["title"]}   [{state_text(r)}]\n')
            else:
                t.insert("end", "   없음\n", "g")
            t.insert("end", "\n▶ 상담 내용\n", "sec")
            t.insert("end", (m["memo"] or "").strip() or "(내용 없음)")
            t.see("end")
        else:
            t.insert("end", "회원을 클릭하면 여기에 요약이 나옵니다.", "g")
        t.config(state="disabled")

    def refresh_notes(self):
        self.note_cb["values"] = [r["title"] for r in self.db.q("SELECT title FROM notes ORDER BY updated DESC")]

    def update_status(self):
        r = self.db.one("SELECT s.*, m.name AS mname FROM schedules s LEFT JOIN members m ON s.member_id=m.id "
                        "WHERE alarm=1 AND notified=0 AND done=0 ORDER BY date, time LIMIT 1")
        push = "폰 알림 켜짐" if self.db.get("ntfy_on", "0") == "1" else "폰 알림 꺼짐"
        if WORKER_URL and push == "폰 알림 켜짐":
            push += " (서버)" if self._sync_state in ("", "ok") else f" — {self._sync_state}"
        if getattr(self, "hotkey_ok", False):
            push += f"     |     어깨동무 상세창에서 {HOTKEY_TEXT} → 가져오기"
        if r:
            who = f' ({r["mname"]})' if r["mname"] else ""
            self.status.config(text=f'⏰ 다음 알림: {r["date"]} {r["time"]}  {r["title"]}{who}     |     {push}')
        else:
            self.status.config(text=f"⏰ 예정된 알림 없음     |     {push}")

    def tick(self):
        n = now()
        self.clock.config(text=f"{n:%Y-%m-%d} ({wd_name(n)}) {n:%H:%M:%S}")
        self.root.after(1000, self.tick)

    # ---------- 달력 동작 ----------
    def on_cell(self, i, add=False):
        d = self.cell_dates[i]
        if not d:
            return
        self.sel_date = d
        self.year, self.month = d.year, d.month
        self.refresh_calendar()
        self.refresh_day()
        if add:
            ScheduleDialog(self, date=d.isoformat())

    def set_month(self, m):
        self.month = m
        today = dt.date.today()
        self.sel_date = today if (today.year, today.month) == (self.year, m) else dt.date(self.year, m, 1)
        self.refresh_calendar()
        self.refresh_day()

    def change_year(self, delta):
        self.year += delta
        self.set_month(self.month)

    def on_wheel(self, e):
        m, y = self.month + (-1 if e.delta > 0 else 1), self.year
        if m < 1:
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self.year = y
        self.set_month(m)

    def go_today(self):
        t = dt.date.today()
        self.year, self.month, self.sel_date = t.year, t.month, t
        self.refresh_calendar()
        self.refresh_day()

    # ---------- 하루 일정 / 메모 ----------
    def day_sel(self):
        s = self.day_tree.selection()
        return int(s[0]) if s else None

    def day_add(self):
        ScheduleDialog(self, date=self.sel_date.isoformat())

    def day_edit(self):
        sid = self.day_sel()
        if sid:
            ScheduleDialog(self, sid=sid)

    def day_toggle(self):
        sid = self.day_sel()
        if sid:
            self.db.x("UPDATE schedules SET done=1-done WHERE id=?", (sid,))
            self.refresh_all()

    def day_delete(self):
        sid = self.day_sel()
        if sid and messagebox.askyesno("삭제", "선택한 일정을 삭제할까요?"):
            self.db.x("DELETE FROM schedules WHERE id=?", (sid,))
            self.refresh_all()

    def on_diary_mod(self, _=None):
        if not self.diary_txt.edit_modified():
            return
        self.diary_txt.edit_modified(False)
        if self._loading:
            return
        self._diary_dirty = True
        if self._diary_job:
            self.root.after_cancel(self._diary_job)
        self._diary_job = self.root.after(800, self.flush_diary)

    def flush_diary(self):
        if self._diary_job:
            self.root.after_cancel(self._diary_job)
            self._diary_job = None
        if self._diary_dirty and self._diary_date:
            self.db.x("INSERT OR REPLACE INTO diary(date, content) VALUES(?,?)",
                      (self._diary_date, self.diary_txt.get("1.0", "end-1c")))
            self._diary_dirty = False
            self.refresh_calendar()

    # ---------- 회원 ----------
    def on_member_double(self, e):
        iid = self.mem_tree.identify_row(e.y)
        if iid:
            self.open_member(int(iid))

    def open_selected_member(self):
        s = self.mem_tree.selection()
        if s:
            self.open_member(int(s[0]))

    def open_member(self, mid):
        w = self.member_windows.get(mid) if mid else None
        if w and w.winfo_exists():
            w.deiconify()
            w.lift()
            w.focus_force()
            return
        w = MemberDialog(self, mid)
        if mid:
            self.member_windows[mid] = w

    def member_delete(self):
        s = self.mem_tree.selection()
        if not s:
            return
        mid = int(s[0])
        if messagebox.askyesno("회원 삭제", "선택한 회원과 연결된 예약까지 모두 삭제할까요?"):
            self.db.x("DELETE FROM schedules WHERE member_id=?", (mid,))
            self.db.x("DELETE FROM members WHERE id=?", (mid,))
            w = self.member_windows.pop(mid, None)
            if w and w.winfo_exists():
                w.destroy()
            self.refresh_all()

    # ---------- 키워드 메모 ----------
    def open_note(self):
        title = self.note_var.get().strip()
        if not title:
            messagebox.showinfo("키워드 / 제목", "왼쪽 위 칸에 제목을 먼저 입력해주세요.")
            return
        w = self.note_windows.get(title)
        if w and w.winfo_exists():
            w.deiconify()
            w.lift()
            w.focus_force()
        else:
            self.note_windows[title] = NoteWindow(self, title)
        self.refresh_notes()

    # ---------- 어깨동무 가져오기 ----------
    def poll_hotkey(self):
        try:
            while True:
                kind, hwnd = self.hk_queue.get_nowait()
                if kind == "capture":
                    self.import_ekdm(hwnd)
                elif kind == "fail":
                    self.hotkey_ok = False
                    self.update_status()
                    messagebox.showwarning("단축키", f"{HOTKEY_TEXT} 단축키를 다른 프로그램이 쓰고 있어 등록하지 못했습니다.\n"
                                                    "상단의 [어깨동무 가져오기] 버튼은 그대로 쓸 수 있어요.")
        except queue.Empty:
            pass
        self.root.after(200, self.poll_hotkey)

    def import_ekdm(self, hwnd=None):
        if not IS_WIN:
            messagebox.showinfo("어깨동무 가져오기", "윈도우에서만 사용할 수 있습니다.")
            return
        h = find_ekdm(hwnd)
        if not h:
            messagebox.showinfo("어깨동무 가져오기", "어깨동무에서 회원을 더블클릭해 상세창을 띄운 뒤\n"
                                                 f"{HOTKEY_TEXT} 를 눌러주세요.")
            return
        try:
            data = read_ekdm(h)
        except Exception as e:
            messagebox.showerror("어깨동무 가져오기", f"읽기 실패: {e}")
            return
        ImportDialog(self, data)

    # ---------- 알림 ----------
    def check_alarms(self):
        try:
            nowk = now().strftime("%Y-%m-%d %H:%M")
            rows = self.db.q("SELECT * FROM schedules WHERE alarm=1 AND notified=0 AND done=0 "
                             "AND date||' '||time <= ? ORDER BY date, time", (nowk,))
            for i, r in enumerate(rows):
                self.db.x("UPDATE schedules SET notified=1 WHERE id=?", (r["id"],))
                AlarmPopup(self, r, offset=(i % 8) * 30)
                self.send_push(r)
            if rows:
                self.refresh_all()
            else:
                self.update_status()
        finally:
            self.root.after(ALARM_CHECK_MS, self.check_alarms)

    def send_push(self, r):
        if WORKER_URL:      # 서버가 예약 시간에 직접 보내므로 PC에서는 보내지 않음 (중복 방지)
            return
        if self.db.get("ntfy_on", "0") != "1":
            return
        topic = self.db.get("ntfy_topic")
        if not topic:
            return
        server = self.db.get("ntfy_server", "https://ntfy.sh")
        m = self.db.one("SELECT * FROM members WHERE id=?", (r["member_id"],)) if r["member_id"] else None
        msg = f'{r["date"]} {r["time"]}'
        if m:
            msg += f'\n{m["name"]}  {m["phone"]}'
        if (r["content"] or "").strip():
            msg += f'\n{r["content"].strip()}'
        title = f'⏰ {r["title"]}'

        def run():
            try:
                push_sync(server, topic, title, msg)
            except Exception as e:
                print("push 실패:", e)

        threading.Thread(target=run, daemon=True).start()

    def on_quit(self):
        msg = ("PC 팝업 알림은 꺼지지만 폰 알림은 서버에서 계속 갑니다.\n종료할까요?" if WORKER_URL else
               "프로그램을 닫으면 예약 알림이 울리지 않습니다.\n종료할까요?\n(창만 내려두려면 최소화 하세요)")
        if not messagebox.askokcancel("종료", msg):
            return
        self.quit_now()

    def quit_now(self):
        self.flush_diary()
        for w in list(self.note_windows.values()):
            if w.winfo_exists():
                w.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
