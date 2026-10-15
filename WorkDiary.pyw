# -*- coding: utf-8 -*-
"""
업무 다이어리 & 집중 회원관리
- 파이썬 표준 라이브러리만 사용 (pip 설치 필요 없음)
- 데이터는 이 파일과 같은 폴더의 workdiary.db 에 저장
- 폰 알림: ntfy 앱 (설정 버튼에서 토픽 등록)
"""
import os, sys, re, json, time, queue, random, string, secrets, sqlite3, calendar, threading
import urllib.request, urllib.error
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
APP_VERSION = "1.0.2"          # GitHub Actions가 태그(v1.0.1 등)로 자동 교체
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
ADMIN_PASS = ""      # 관리자 본인 PC에만 있음 (서버정보.txt) → 라이선스 키 자동 발급
if not WORKER_URL:   # 내 PC에서 실행.bat 으로 켤 때: 서버정보.txt 의 서버 주소 사용 (배포 exe는 빌드 때 들어감)
    try:
        with open(os.path.join(BASE_DIR, "서버정보.txt"), encoding="utf-8-sig") as _f:
            for _ln in _f:
                _k, _, _v = _ln.strip().partition("=")
                if _k == "WORKER_URL" and _v:
                    WORKER_URL = _v
                elif _k == "WORKER_KEY" and _v:
                    WORKER_KEY = _v
                elif _k == "ADMIN_PASS" and _v:
                    ADMIN_PASS = _v
    except OSError:
        pass

F = "맑은 고딕"
FONT, FONT_S, FONT_B, FONT_T = (F, 10), (F, 9), (F, 10, "bold"), (F, 13, "bold")
FONT_H = (F, 15, "bold")
# 골드 & 아이보리 테마
BG = "#F6F1E6"          # 바탕 (아이보리)
PANEL = "#FFFDF8"       # 카드·입력칸
HEAD = "#EDE2C8"        # 표 머리·요일줄
LINE = "#E3D6B8"        # 테두리
ACCENT = "#B08326"      # 골드 (주요 버튼·선택)
ACCENT_DK = "#8F6A1C"   # 골드 진하게 (눌림)
GOLD_LT = "#F4E7C5"     # 연한 골드
GOLD_BR = "#D9B45A"     # 밝은 골드 (어두운 바탕 위 글씨)
DARK = "#1F1B16"        # 상단바 (에스프레소)
DARK2 = "#2A241D"
TEXT = "#2B2620"
TEXT2 = "#4A4033"
MUTED = "#8A7F6B"
SEC = "#EFE5CF"         # 보조 버튼
SEC_DK = "#E5D5AE"
SUN, SAT = "#B4443A", "#3E5C8A"
OK_C, WARN_C = "#4F7A3A", "#B8892B"
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


def state_text(r, db):
    if r["done"]:
        return "완료"
    al = db.q("SELECT fire_at, notified FROM alarms WHERE schedule_id=? ORDER BY fire_at", (r["id"],))
    if not al:
        return "알림없음"
    pend = [a for a in al if not a["notified"]]
    if not pend:
        return "울림"
    nxt = pend[0]["fire_at"][5:].replace("-", "/")
    return f"🔔 {nxt}" + (f" 외 {len(pend) - 1}" if len(pend) > 1 else "")


def btn(parent, text, cmd, primary=False, dark=False, **kw):
    if dark:
        bg, fg, abg, afg = DARK2, "#EAD7A4", "#3A3228", GOLD_BR
    elif primary:
        bg, fg, abg, afg = ACCENT, "white", ACCENT_DK, "white"
    else:
        bg, fg, abg, afg = SEC, TEXT2, SEC_DK, TEXT
    b = tk.Button(parent, text=text, command=cmd, font=FONT_B if primary else FONT, relief="flat", bd=0,
                  cursor="hand2", bg=bg, fg=fg, activebackground=abg, activeforeground=afg,
                  padx=kw.pop("padx", 12), pady=4, highlightthickness=0, **kw)
    b.bind("<Enter>", lambda e: b.config(bg=abg))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


def tooltip(w, text):
    """마우스를 올리면 잠깐 설명이 뜸"""
    tip = {}

    def show(_):
        t = tk.Toplevel(w)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        tk.Label(t, text=text, font=FONT_S, bg=DARK, fg="#F5EBD3", padx=8, pady=4).pack()
        t.geometry(f"+{w.winfo_rootx()}+{w.winfo_rooty() + w.winfo_height() + 4}")
        tip["t"] = t

    def hide(_):
        t = tip.pop("t", None)
        if t is not None and t.winfo_exists():
            t.destroy()

    w.bind("<Enter>", show, add="+")
    w.bind("<Leave>", hide, add="+")
    w.bind("<ButtonPress>", hide, add="+")
    return w


def bring_front(win, keep_top=False):
    """창을 확실히 맨 앞으로 (다른 프로그램 뒤에 숨지 않게)"""
    try:
        win.deiconify()
        win.lift()
        win.attributes("-topmost", True)
        win.focus_force()
        if not keep_top:
            win.after(400, lambda: win.winfo_exists() and win.attributes("-topmost", False))
    except tk.TclError:
        pass


class FlowBar(tk.Frame):
    """버튼 줄: 폭이 좁아지면 자동으로 다음 줄로 넘김 (잘리지 않음)"""

    def __init__(self, master, align="right", gap=4, **kw):
        super().__init__(master, height=34, **kw)
        self.items, self.align, self.gap, self._lastw = [], align, gap, None
        self.bind("<Configure>", self._reflow)

    def add(self, w):
        self.items.append(w)
        self._lastw = None
        self.after_idle(self._reflow)
        return w

    def _reflow(self, e=None):
        W = self.winfo_width()
        if W <= 1 or W == self._lastw:
            return
        self._lastw = W
        g = self.gap
        rows = [[]]
        x = 0
        for w in self.items:
            need = w.winfo_reqwidth() + g
            if rows[-1] and x + need > W:
                rows.append([])
                x = 0
            rows[-1].append(w)
            x += need
        y = 0
        for r in rows:
            total = sum(w.winfo_reqwidth() for w in r) + g * (len(r) - 1)
            xx = max(0, W - total) if self.align == "right" else 0
            h = max(w.winfo_reqheight() for w in r) if r else 0
            for w in r:
                w.place(x=xx, y=y)
                xx += w.winfo_reqwidth() + g
            y += h + g
        self.configure(height=max(1, y - g))


def fit_columns(tree, spec, hide_order=()):
    """표 칸 너비를 창 크기에 맞춰 비율대로 자동 조절. spec = {칸: (비율, 최소폭)}
    너무 좁으면 hide_order 순서대로 덜 중요한 칸을 잠시 숨김 (넓어지면 다시 보임)"""
    order = list(tree["columns"])

    def on_size(e=None):
        W = tree.winfo_width() - 4
        if W <= 10:
            return
        vis = list(order)
        for c in hide_order:
            if sum(spec[x][1] for x in vis) <= W:
                break
            vis.remove(c)
        tot = sum(spec[c][0] for c in vis)
        widths = {c: max(spec[c][1], int(W * spec[c][0] / tot)) for c in vis}
        over = sum(widths.values()) - W        # 최소폭 때문에 넘치면 큰 칸에서 줄임
        for c in sorted(widths, key=lambda c: -widths[c]):
            if over <= 0:
                break
            cut = min(over, widths[c] - spec[c][1])
            widths[c] -= cut
            over -= cut
        if tuple(tree["displaycolumns"]) != tuple(vis) and list(tree["displaycolumns"]) != vis:
            tree["displaycolumns"] = vis
        for c, w in widths.items():
            tree.column(c, width=w, stretch=False)
    tree.bind("<Configure>", on_size, add="+")


def toast(root, text, ms=3500):
    """확인 버튼 없이 잠깐 떴다 사라지는 안내 (다른 창을 막지 않음)"""
    w = tk.Toplevel(root)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    w.configure(bg="#1F1B16", highlightthickness=1, highlightbackground="#B08326")
    tk.Label(w, text=text, font=("맑은 고딕", 10), fg="#F5EBD3", bg="#1F1B16", justify="left",
             padx=18, pady=12).pack()
    w.update_idletasks()
    x = w.winfo_screenwidth() - w.winfo_reqwidth() - 30
    y = w.winfo_screenheight() - w.winfo_reqheight() - 80
    w.geometry(f"+{x}+{y}")
    w.bind("<Button-1>", lambda e: w.destroy())
    w.after(ms, lambda: w.winfo_exists() and w.destroy())


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


def phone_cfg(db):
    """폰 알림 설정 (예전 ntfy 설정에서 자동 이어받기)"""
    on = db.get("phone_on", "")
    if on == "":
        on = db.get("ntfy_on", "1") or "1"
        db.set("phone_on", on)
    use_ntfy = db.get("ntfy_use", "")
    if use_ntfy == "":
        use_ntfy = "1" if (db.get("ntfy_on", "0") == "1" and db.get("ntfy_topic")) else "0"
        db.set("ntfy_use", use_ntfy)
    topic = db.get("ntfy_topic") if use_ntfy == "1" else ""
    return on == "1", use_ntfy == "1", topic


def channels(db):
    """알림 받을 곳: 텔레그램 / 웹앱 (기본 둘 다 켜짐)"""
    return {"tg": db.get("ch_tg", "1") == "1", "web": db.get("ch_web", "1") == "1"}


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


# ───────────────────────── 어깨동무 메인 목록 읽기 (F9, 화면 글자 인식) ─────────────────────────
import struct, subprocess, tempfile
if IS_WIN:
    gdi32 = ctypes.windll.gdi32


EKDM_MAIN_CLASS = "TfrmAddrmain"
EKDM_GRID_CLASS = "TRxDBGrid"


def _ocls(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def _orect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def ekdm_find_main(hwnd=None):
    if hwnd:
        root = user32.GetAncestor(hwnd, 2)
        if root and _ocls(root) == EKDM_MAIN_CLASS:
            return root
    out = []
    cb = WNDENUMPROC(lambda h, l: (out.append(h) if user32.IsWindowVisible(h) and _ocls(h) == EKDM_MAIN_CLASS
                                   else None, True)[1])
    user32.EnumWindows(cb, 0)
    return out[0] if out else None


def ekdm_find_grid(main):
    best = None
    out = []
    cb = WNDENUMPROC(lambda c, l: (out.append(c), True)[1])
    user32.EnumChildWindows(main, cb, 0)
    for c in out:
        if _ocls(c) == EKDM_GRID_CLASS and user32.IsWindowVisible(c):
            l, t, r, b = _orect(c)
            if best is None or (r - l) * (b - t) > best[1]:
                best = (c, (r - l) * (b - t))
    return best[0] if best else None


class Shot:
    """화면 캡처 (BGR 24bit, 위→아래)"""

    def __init__(self, w, h, data):
        self.w, self.h, self.data = w, h, data
        self.stride = (w * 3 + 3) & ~3

    def px(self, x, y):
        i = y * self.stride + x * 3
        b, g, r = self.data[i], self.data[i + 1], self.data[i + 2]
        return r, g, b

    def crop_scale(self, x0, y0, x1, y1, k=3, mode="gray", pad=16):
        """선택 줄을 잘라 '흰 바탕 검은 글씨'로 바꾸고 k배 부드럽게 확대 (글자 인식 정확도↑)
        - 표 세로줄 제거, 둘레 여백 추가"""
        w, h = x1 - x0, y1 - y0
        g = [[0.0] * w for _ in range(h)]
        for y in range(h):
            base = (y0 + y) * self.stride
            for x in range(w):
                i = base + (x0 + x) * 3
                bb, gg, rr = self.data[i], self.data[i + 1], self.data[i + 2]
                lum = 0.299 * rr + 0.587 * gg + 0.114 * bb
                if mode == "bin":
                    g[y][x] = 0.0 if lum > 190 else 255.0
                else:                      # 파란 바탕(밝기≈120)→흰색, 흰 글씨→검정, 중간값은 부드럽게
                    v = (lum - 125.0) / (245.0 - 125.0)
                    g[y][x] = 255.0 * (1.0 - min(1.0, max(0.0, v)))
        # 표 세로줄(위아래로 거의 다 어두운 세로선) 지우기
        for x in range(w):
            if sum(1 for y in range(h) if g[y][x] < 128) >= h * 0.8:
                for y in range(h):
                    g[y][x] = 255.0
        nw, nh = w * k + pad * 2, h * k + pad * 2
        nstride = (nw * 3 + 3) & ~3
        out = bytearray(b"\xff" * (nstride * nh))
        for oy in range(h * k):
            sy = min(h - 1.0, max(0.0, (oy + 0.5) / k - 0.5))
            y0i = int(sy)
            y1i = min(h - 1, y0i + 1)
            fy = sy - y0i
            r0, r1 = g[y0i], g[y1i]
            o = (oy + pad) * nstride + pad * 3
            for ox in range(w * k):
                sx = min(w - 1.0, max(0.0, (ox + 0.5) / k - 0.5))
                x0i = int(sx)
                x1i = min(w - 1, x0i + 1)
                fx = sx - x0i
                v = (r0[x0i] * (1 - fx) + r0[x1i] * fx) * (1 - fy) + (r1[x0i] * (1 - fx) + r1[x1i] * fx) * fy
                c = int(v)
                out[o] = out[o + 1] = out[o + 2] = c
                o += 3
        return Shot(nw, nh, bytes(out))

    def save_bmp(self, path):
        size = self.stride * self.h
        with open(path, "wb") as f:
            f.write(b"BM" + struct.pack("<IHHI", 54 + size, 0, 0, 54))
            f.write(struct.pack("<IiiHHIIiiII", 40, self.w, -self.h, 1, 24, 0, size, 2835, 2835, 0, 0))
            f.write(self.data)


def screen_capture(hwnd):
    l, t, r, b = _orect(hwnd)
    w, h = r - l, b - t
    sdc = user32.GetDC(0)
    mdc = gdi32.CreateCompatibleDC(sdc)
    bmp = gdi32.CreateCompatibleBitmap(sdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, h, sdc, l, t, 0x00CC0020)  # SRCCOPY (화면에 보이는 그대로)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]
    bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 24, 0, 0, 0, 0, 0, 0)
    stride = (w * 3 + 3) & ~3
    buf = ctypes.create_string_buffer(stride * h)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(0, sdc)
    return Shot(w, h, buf.raw)


def highlight_rgb():
    c = user32.GetSysColor(13)  # COLOR_HIGHLIGHT
    return c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF


def _is_sel(p, hl):
    r, g, b = p
    if abs(r - hl[0]) + abs(g - hl[1]) + abs(b - hl[2]) < 60:
        return True
    return b > 170 and b - r > 90 and b - g > 20      # 파란 선택 줄 (어깨동무 기본색)


def find_selected_row(shot):
    """선택된(파란) 줄의 y 범위"""
    hl = highlight_rgb()
    xs = range(min(30, shot.w - 1), min(shot.w - 1, 900), 6)
    hits = []
    for y in range(shot.h):
        n = sum(1 for x in xs if _is_sel(shot.px(x, y), hl))
        hits.append(n >= len(xs) * 0.5)
    best, cur = None, None
    for y, hit in enumerate(hits + [False]):
        if hit and cur is None:
            cur = y
        elif not hit and cur is not None:
            if 10 <= y - cur <= 60 and (best is None or y - cur > best[1] - best[0]):
                best = (cur, y)
            cur = None
    return best


PS_OCR = r'''
param([string]$img)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskG = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $t) { $task = $asTaskG.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime] | Out-Null
$f = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($img)) ([Windows.Storage.StorageFile])
$s = Await ($f.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$d = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($s)) ([Windows.Graphics.Imaging.BitmapDecoder])
$b = Await ($d.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$e = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language 'ko'))
if ($e -eq $null) { $e = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
$r = Await ($e.RecognizeAsync($b)) ([Windows.Media.Ocr.OcrResult])
$words = @()
foreach ($ln in $r.Lines) { foreach ($w in $ln.Words) { $words += @{ t = $w.Text; x = [int]$w.BoundingRect.X; w = [int]$w.BoundingRect.Width } } }
@{ lang = $e.RecognizerLanguage.LanguageTag; words = $words } | ConvertTo-Json -Compress -Depth 4
'''


def win_ocr(bmp_path):
    ps = os.path.join(tempfile.gettempdir(), "workdiary_ocr.ps1")
    with open(ps, "w", encoding="utf-8-sig") as f:
        f.write(PS_OCR)
    p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps, bmp_path],
                       capture_output=True, timeout=30, creationflags=0x08000000)
    out = p.stdout.decode("utf-8", "ignore").strip()
    if not out:
        raise RuntimeError(p.stderr.decode("utf-8", "ignore")[-400:] or "OCR 결과 없음")
    j = json.loads(out)
    words = j.get("words") or []
    if isinstance(words, dict):
        words = [words]
    return j.get("lang", ""), sorted(words, key=lambda w: w["x"])


PHONE_RE = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}")


def parse_row(words):
    """OCR 단어들 → (이름, 전화번호). 전화번호 앞에 있는 글자를 이름으로."""
    text = " ".join(w["t"] for w in words)
    joined = re.sub(r"\s+", "", text)
    fixed = joined.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    m = PHONE_RE.search(fixed)
    phone = ""
    if m:
        d = re.sub(r"\D", "", m.group(0))
        phone = f"{d[:3]}-{d[3:-4]}-{d[-4:]}"
    name_words = []
    for w in words:
        t = w["t"]
        if re.search(r"\d{3,}", t):
            break
        name_words.append(t)
    name = " ".join(name_words).strip(" .|")
    name = re.sub(r"^[lI|!1\[\]]+(?=\S)", "", name).strip()     # 앞쪽 표 테두리가 l / | 로 읽힌 것 제거
    return name, phone, text


def ekdm_read_selected(hwnd=None, debug_dir=None, mode="gray", k=3):
    main = ekdm_find_main(hwnd)
    if not main:
        raise RuntimeError("어깨동무 메인 화면을 찾지 못했어요.")
    grid = ekdm_find_grid(main)
    if not grid:
        raise RuntimeError("어깨동무 회원 목록을 찾지 못했어요.")
    shot = screen_capture(grid)
    row = find_selected_row(shot)
    if not row:
        raise RuntimeError("선택된 회원 줄을 찾지 못했어요. 목록에서 회원을 한 번 클릭해 주세요.")
    y0, y1 = row
    x1 = min(shot.w, 700)                         # 이름·휴대폰 칸이 있는 왼쪽 부분만
    strip = shot.crop_scale(0, y0, x1, y1, k=k, mode=mode)
    tmp = os.path.join(debug_dir or tempfile.gettempdir(), f"workdiary_row_{mode}{k}.bmp")
    strip.save_bmp(tmp)
    try:
        lang, words = win_ocr(tmp)
    finally:
        if not debug_dir:
            try:
                os.remove(tmp)
            except OSError:
                pass
    name, phone, raw = parse_row(words)
    return {"name": name, "phone": phone, "raw": raw, "lang": lang, "row": row}


def ekdm_read_via_detail(hwnd=None, timeout=3.0):
    """F9 (정확한 방법): 선택된 줄을 더블클릭해 상세창을 '투명하게' 열고 글자를 그대로 읽은 뒤 바로 닫음"""
    import time
    main = ekdm_find_main(hwnd)
    if not main:
        raise RuntimeError("어깨동무 메인 화면을 찾지 못했어요.")
    grid = ekdm_find_grid(main)
    if not grid:
        raise RuntimeError("어깨동무 회원 목록을 찾지 못했어요.")
    row = find_selected_row(screen_capture(grid))
    if not row:
        raise RuntimeError("선택된 회원 줄을 찾지 못했어요. 목록에서 회원을 한 번 클릭해 주세요.")
    l, t, _, _ = _orect(grid)
    pt = wintypes.POINT(l + 60, t + (row[0] + row[1]) // 2)
    user32.ScreenToClient(grid, ctypes.byref(pt))
    lp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
    before = set(ekdm_windows())
    for msg, wp in ((0x201, 1), (0x202, 0), (0x203, 1), (0x202, 0)):   # 마우스 안 움직이고 더블클릭 신호만 보냄
        user32.PostMessageW(grid, msg, wp, lp)
    end = time.time() + timeout
    det = None
    while time.time() < end:
        new = [h for h in ekdm_windows() if h not in before]
        if new:
            det = new[0]
            ex = user32.GetWindowLongW(det, -20)
            user32.SetWindowLongW(det, -20, ex | 0x80000)              # 즉시 투명하게 (위치는 안 바꿈)
            user32.SetLayeredWindowAttributes(det, 0, 0, 2)
            break
        time.sleep(0.005)
    if not det:
        raise RuntimeError("상세창이 열리지 않았어요.")
    data = {}
    try:
        end = time.time() + 1.5
        while time.time() < end:                                     # 내용이 채워질 때까지 잠깐 대기
            data = read_ekdm(det)
            if data.get("phone") or data.get("name"):
                break
            time.sleep(0.03)
    finally:
        user32.PostMessageW(det, 0x0010, 0, 0)                       # WM_CLOSE: 바로 닫기
    if not (data.get("phone") or data.get("name")):
        raise RuntimeError("상세창에서 이름·전화번호를 읽지 못했어요.")
    data["method"] = "detail"
    return data


def hotkey_loop(q):
    """전역 단축키 F8 감시 (별도 스레드)"""
    MOD_NOREPEAT, VK_F8, VK_F9, WM_HOTKEY = 0x4000, 0x77, 0x78, 0x0312
    ok8 = user32.RegisterHotKey(None, 1, MOD_NOREPEAT, VK_F8)
    ok9 = user32.RegisterHotKey(None, 2, MOD_NOREPEAT, VK_F9)
    if not ok8 or not ok9:
        q.put(("fail", ("F8" if not ok8 else "") + (" F9" if not ok9 else "")))
        if not ok8 and not ok9:
            return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            q.put(("capture" if msg.wParam == 1 else "f9", user32.GetForegroundWindow()))


def digits(s):
    return re.sub(r"\D", "", s or "")


# ───────────────────────── DB ─────────────────────────
class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA synchronous=FULL")   # 갑자기 꺼져도 저장된 내용 보존 (트랜잭션 시작 전에 설정)
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
        CREATE TABLE IF NOT EXISTS alarms(
            id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id INTEGER, offset_min INTEGER,
            fire_at TEXT, notified INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_alarms_sched ON alarms(schedule_id);
        CREATE INDEX IF NOT EXISTS idx_alarms_fire ON alarms(notified, fire_at);
        """)
        if not self.conn.execute("SELECT 1 FROM settings WHERE key='alarms_v2'").fetchone():
            # 예전 일정(알림 1개)을 새 알림 목록으로 옮김
            self.conn.execute("INSERT INTO alarms(schedule_id, offset_min, fire_at, notified) "
                              "SELECT id, 0, date||' '||time, notified FROM schedules WHERE alarm=1")
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES('alarms_v2','1')")
        self.conn.execute("DELETE FROM alarms WHERE schedule_id NOT IN (SELECT id FROM schedules)")
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(members)")]
        if "keyword" not in cols:   # 예전 데이터에 검색어 칸 추가
            self.conn.execute("ALTER TABLE members ADD COLUMN keyword TEXT DEFAULT ''")
        if "sort_order" not in cols:  # 회원별 이름 색 + 직접 정한 순서
            self.conn.execute("ALTER TABLE members ADD COLUMN color TEXT DEFAULT ''")
            self.conn.execute("ALTER TABLE members ADD COLUMN sort_order REAL")
            ids = [r[0] for r in self.conn.execute("SELECT id FROM members ORDER BY updated DESC, id DESC")]
            self.conn.executemany("UPDATE members SET sort_order=? WHERE id=?", [(i, mid) for i, mid in enumerate(ids)])
        self.conn.execute("""CREATE TRIGGER IF NOT EXISTS members_new_on_top AFTER INSERT ON members
            WHEN NEW.sort_order IS NULL BEGIN
              UPDATE members SET sort_order = (SELECT COALESCE(MIN(sort_order), 0) - 1 FROM members WHERE id <> NEW.id)
              WHERE id = NEW.id;
            END""")
        ncols = [r[1] for r in self.conn.execute("PRAGMA table_info(notes)")]
        if "geometry" not in ncols:  # 메모: 제목 중복 허용 + 창 크기/위치·항상위 기억
            self.conn.executescript("""
            CREATE TABLE notes_new(
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', content TEXT DEFAULT '',
                updated TEXT, geometry TEXT DEFAULT '', topmost INTEGER DEFAULT 0);
            INSERT INTO notes_new(id, title, content, updated) SELECT id, title, content, updated FROM notes;
            DROP TABLE notes;
            ALTER TABLE notes_new RENAME TO notes;
            """)
        self._setup_sync()
        self.conn.commit()

    def _setup_sync(self):
        """웹앱 동기화 준비: 각 기록에 고유번호(uid) + 바뀐 것을 적어두는 대기열(sync_queue)과 자동 기록 장치(트리거)"""
        c = self.conn
        for t in ("members", "schedules", "notes"):
            if "uid" not in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]:
                c.execute(f"ALTER TABLE {t} ADD COLUMN uid TEXT")
            c.execute(f"UPDATE {t} SET uid=lower(hex(randomblob(8))) WHERE uid IS NULL OR uid=''")
            c.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{t}_uid ON {t}(uid)")
        c.execute("CREATE TABLE IF NOT EXISTS sync_queue(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, "
                  "lid INTEGER, uid TEXT, del INTEGER DEFAULT 0)")

        def changed(cols):
            return " OR ".join(f"OLD.{x} IS NOT NEW.{x}" for x in cols)

        trig = []
        for t, kind, cols in (("members", "member", ("name", "phone", "memo", "keyword", "color", "sort_order")),
                              ("schedules", "schedule", ("date", "time", "title", "content", "member_id", "done")),
                              ("notes", "note", ("title", "content"))):
            trig += [
                f"""CREATE TRIGGER IF NOT EXISTS sq_{t}_uid AFTER INSERT ON {t} WHEN NEW.uid IS NULL BEGIN
                    UPDATE {t} SET uid=lower(hex(randomblob(8))) WHERE id=NEW.id; END""",
                f"""CREATE TRIGGER IF NOT EXISTS sq_{t}_ins AFTER INSERT ON {t} BEGIN
                    INSERT INTO sync_queue(kind, lid) VALUES('{kind}', NEW.id); END""",
                f"""CREATE TRIGGER IF NOT EXISTS sq_{t}_upd AFTER UPDATE ON {t} WHEN {changed(cols)} BEGIN
                    INSERT INTO sync_queue(kind, lid) VALUES('{kind}', NEW.id); END""",
                f"""CREATE TRIGGER IF NOT EXISTS sq_{t}_del AFTER DELETE ON {t} BEGIN
                    INSERT INTO sync_queue(kind, lid, uid, del) VALUES('{kind}', OLD.id, OLD.uid, 1); END"""]
        trig += [
            """CREATE TRIGGER IF NOT EXISTS sq_alarms_ins AFTER INSERT ON alarms BEGIN
               INSERT INTO sync_queue(kind, lid) VALUES('schedule', NEW.schedule_id); END""",
            """CREATE TRIGGER IF NOT EXISTS sq_alarms_upd AFTER UPDATE ON alarms
               WHEN OLD.fire_at IS NOT NEW.fire_at OR OLD.offset_min IS NOT NEW.offset_min BEGIN
               INSERT INTO sync_queue(kind, lid) VALUES('schedule', NEW.schedule_id); END""",
            """CREATE TRIGGER IF NOT EXISTS sq_alarms_del AFTER DELETE ON alarms BEGIN
               INSERT INTO sync_queue(kind, lid) VALUES('schedule', OLD.schedule_id); END""",
            """CREATE TRIGGER IF NOT EXISTS sq_diary_ins AFTER INSERT ON diary BEGIN
               INSERT INTO sync_queue(kind, uid) VALUES('diary', NEW.date); END""",
            """CREATE TRIGGER IF NOT EXISTS sq_diary_upd AFTER UPDATE ON diary WHEN OLD.content IS NOT NEW.content BEGIN
               INSERT INTO sync_queue(kind, uid) VALUES('diary', NEW.date); END""",
            """CREATE TRIGGER IF NOT EXISTS sq_diary_del AFTER DELETE ON diary BEGIN
               INSERT INTO sync_queue(kind, uid) VALUES('diary', OLD.date); END"""]
        for sql in trig:
            c.execute(sql)

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
ALARM_PRESETS = [("정시", 0), ("10분 전", 10), ("30분 전", 30), ("1시간 전", 60), ("3시간 전", 180), ("하루 전", 1440)]
REPEAT_START = [("10분 전", 10), ("30분 전", 30), ("1시간 전", 60), ("2시간 전", 120), ("3시간 전", 180),
                ("하루 전", 1440), ("2일 전", 2880), ("3일 전", 4320), ("일주일 전", 10080)]
REPEAT_GAP = [("5분마다", 5), ("10분마다", 10), ("15분마다", 15), ("30분마다", 30), ("1시간마다", 60),
              ("2시간마다", 120), ("하루마다", 1440)]


def offset_label(m):
    if m == 0:
        return "정시"
    if m == 1440:
        return "하루 전"
    if m % 1440 == 0:
        return f"{m // 1440}일 전"
    if m % 60 == 0:
        return f"{m // 60}시간 전"
    if m > 60:
        return f"{m // 60}시간 {m % 60}분 전"
    return f"{m}분 전"


def fmt_dt(x):
    return x.strftime("%Y-%m-%d %H:%M")


def alarm_fire(event_dt, it):
    return event_dt - dt.timedelta(minutes=it["offset"]) if it.get("offset") is not None else it["at"]


def load_alarm_items(db, sid):
    out = []
    for a in db.q("SELECT * FROM alarms WHERE schedule_id=? ORDER BY fire_at", (sid,)):
        if a["offset_min"] is not None:
            out.append({"offset": a["offset_min"]})
        else:
            out.append({"at": dt.datetime.strptime(a["fire_at"], "%Y-%m-%d %H:%M")})
    return out


def save_alarms(db, sid, event_dt, items):
    """일정의 알림 목록 저장. 이미 울린 알림(같은 시각)은 다시 울리지 않게 상태 유지"""
    old = {a["fire_at"]: a["notified"] for a in db.q("SELECT * FROM alarms WHERE schedule_id=?", (sid,))}
    seen = set()
    rows = []
    for it in items:
        k = fmt_dt(alarm_fire(event_dt, it))
        if k in seen:
            continue
        seen.add(k)
        notified = old.get(k, 0 if dt.datetime.strptime(k, "%Y-%m-%d %H:%M") > now() else 1)
        rows.append((sid, it.get("offset"), k, notified))
    with db.conn:
        db.conn.execute("DELETE FROM alarms WHERE schedule_id=?", (sid,))
        db.conn.executemany("INSERT INTO alarms(schedule_id, offset_min, fire_at, notified) VALUES(?,?,?,?)", rows)


# ───────────────────────── 웹앱 ↔ PC 동기화 ─────────────────────────
SYNC_EVERY_MS = 60000      # 1분마다 웹앱에서 바뀐 것 가져오기
SYNC_CHUNK = 600_000       # 한 번에 올리는 최대 크기 (처음 올릴 때 나눠서)


def at_ts(at):
    return int(dt.datetime.strptime(at, "%Y-%m-%d %H:%M").timestamp())


def sync_record(db, kind, lid=None, uid=None):
    """로컬 기록 → 서버로 보낼 (uid, data). 이미 지워졌으면 (uid, None)"""
    if kind == "diary":
        r = db.one("SELECT content FROM diary WHERE date=?", (uid,))
        txt = r["content"] if r else ""
        return uid, ({"content": txt} if (txt or "").strip() else None)
    if kind == "member":
        r = db.one("SELECT * FROM members WHERE id=?", (lid,))
        if not r:
            return None, None
        return r["uid"], {"name": r["name"] or "", "phone": r["phone"] or "", "keyword": r["keyword"] or "",
                          "memo": r["memo"] or "", "color": r["color"] or "",
                          "sort": r["sort_order"] if r["sort_order"] is not None else 0,
                          "created": r["created"] or "", "updated": r["updated"] or ""}
    if kind == "schedule":
        r = db.one("SELECT s.*, m.uid AS muid FROM schedules s LEFT JOIN members m ON m.id=s.member_id WHERE s.id=?",
                   (lid,))
        if not r:
            return None, None
        alarms = []
        for a in db.q("SELECT * FROM alarms WHERE schedule_id=? ORDER BY fire_at", (lid,)):
            try:
                alarms.append({"offset": a["offset_min"], "at": a["fire_at"], "ts": at_ts(a["fire_at"]),
                               "notified": a["notified"]})
            except (TypeError, ValueError):
                pass
        return r["uid"], {"date": r["date"], "time": r["time"], "title": r["title"] or "", "content": r["content"] or "",
                          "member": r["muid"], "done": r["done"], "alarms": alarms}
    if kind == "note":
        r = db.one("SELECT * FROM notes WHERE id=?", (lid,))
        if not r:
            return None, None
        return r["uid"], {"title": r["title"] or "", "content": r["content"] or "", "updated": r["updated"] or ""}
    return None, None


def sync_queue_key(db, e):
    """대기열 항목 → (종류, uid)"""
    if e["kind"] == "diary" or e["del"]:
        return e["kind"], e["uid"]
    t = {"member": "members", "schedule": "schedules", "note": "notes"}[e["kind"]]
    r = db.one(f"SELECT uid FROM {t} WHERE id=?", (e["lid"],))
    return e["kind"], (r["uid"] if r else None)


def sync_collect(db, limit=SYNC_CHUNK):
    """대기열에서 서버로 올릴 변경 목록. 반환: (changes, 처리한 마지막 대기열 번호)"""
    changes, seen, size, maxid = [], set(), 0, 0
    for e in db.q("SELECT * FROM sync_queue ORDER BY id"):
        if e["del"] and e["kind"] != "diary":
            uid, data, deleted = e["uid"], None, True
        else:
            uid, data = sync_record(db, e["kind"], e["lid"], e["uid"])
            deleted = data is None and e["kind"] == "diary"
            if data is None and not deleted:
                maxid = e["id"]          # 그새 지워진 기록 → 지움 항목이 따로 있음
                continue
        if not uid or (e["kind"], uid) in seen:
            maxid = e["id"]
            continue
        item = {"kind": e["kind"], "uid": uid, "deleted": True} if deleted else {"kind": e["kind"], "uid": uid, "data": data}
        n = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if changes and size + n > limit:
            break
        seen.add((e["kind"], uid))
        changes.append(item)
        size += n
        maxid = e["id"]
    return changes, maxid


def sync_apply(db, changes, skip=()):
    """서버(웹앱)에서 바뀐 것을 PC에 반영. 반환: 바뀐 (종류, uid) 목록"""
    touched = set()
    before = (db.one("SELECT MAX(id) AS m FROM sync_queue") or {"m": 0})["m"] or 0
    nowk = now().strftime("%Y-%m-%d %H:%M")
    with db.conn:
        c = db.conn
        for ch in changes:
            kind, uid, d = ch.get("kind"), ch.get("uid"), ch.get("data") or {}
            if not uid or (kind, uid) in skip:      # PC에서 방금 고친 것은 PC 것이 우선
                continue
            dele = bool(ch.get("deleted"))
            if kind == "member":
                if dele:
                    c.execute("DELETE FROM members WHERE uid=?", (uid,))
                else:
                    vals = (d.get("name", ""), d.get("phone", ""), d.get("memo", ""), d.get("keyword", ""),
                            d.get("color", ""), d.get("sort", 0), d.get("created") or stamp(), d.get("updated") or stamp())
                    if c.execute("SELECT 1 FROM members WHERE uid=?", (uid,)).fetchone():
                        c.execute("UPDATE members SET name=?,phone=?,memo=?,keyword=?,color=?,sort_order=?,created=?,updated=? "
                                  "WHERE uid=?", vals + (uid,))
                    else:
                        c.execute("INSERT INTO members(name,phone,memo,keyword,color,sort_order,created,updated,uid) "
                                  "VALUES(?,?,?,?,?,?,?,?,?)", vals + (uid,))
            elif kind == "schedule":
                old = c.execute("SELECT id FROM schedules WHERE uid=?", (uid,)).fetchone()
                if dele:
                    if old:
                        c.execute("DELETE FROM alarms WHERE schedule_id=?", (old[0],))
                        c.execute("DELETE FROM schedules WHERE id=?", (old[0],))
                else:
                    m = c.execute("SELECT id FROM members WHERE uid=?", (d.get("member"),)).fetchone() if d.get("member") else None
                    alarms = d.get("alarms") or []
                    vals = (d.get("date"), d.get("time"), d.get("title", ""), d.get("content", ""), m[0] if m else None,
                            1 if alarms else 0, int(bool(d.get("done"))))
                    if old:
                        sid = old[0]
                        c.execute("UPDATE schedules SET date=?,time=?,title=?,content=?,member_id=?,alarm=?,done=? WHERE id=?",
                                  vals + (sid,))
                    else:
                        sid = c.execute("INSERT INTO schedules(date,time,title,content,member_id,alarm,done,notified,uid) "
                                        "VALUES(?,?,?,?,?,?,?,0,?)", vals + (uid,)).lastrowid
                    was = {a[0]: a[1] for a in c.execute("SELECT fire_at, notified FROM alarms WHERE schedule_id=?", (sid,))}
                    c.execute("DELETE FROM alarms WHERE schedule_id=?", (sid,))
                    seen = set()
                    for a in alarms:
                        at = a.get("at")
                        if not at or at in seen:
                            continue
                        seen.add(at)
                        nt = was.get(at, 1 if (a.get("notified") or at <= nowk) else 0)
                        c.execute("INSERT INTO alarms(schedule_id, offset_min, fire_at, notified) VALUES(?,?,?,?)",
                                  (sid, a.get("offset"), at, nt))
            elif kind == "note":
                if dele:
                    c.execute("DELETE FROM notes WHERE uid=?", (uid,))
                elif c.execute("SELECT 1 FROM notes WHERE uid=?", (uid,)).fetchone():
                    c.execute("UPDATE notes SET title=?, content=?, updated=? WHERE uid=?",
                              (d.get("title", ""), d.get("content", ""), d.get("updated") or stamp(), uid))
                else:
                    c.execute("INSERT INTO notes(title, content, updated, uid) VALUES(?,?,?,?)",
                              (d.get("title", ""), d.get("content", ""), d.get("updated") or stamp(), uid))
            elif kind == "diary":
                if dele or not (d.get("content") or "").strip():
                    c.execute("DELETE FROM diary WHERE date=?", (uid,))
                else:
                    c.execute("INSERT OR REPLACE INTO diary(date, content) VALUES(?,?)", (uid, d.get("content")))
            else:
                continue
            touched.add((kind, uid))
        c.execute("DELETE FROM sync_queue WHERE id > ?", (before,))   # 받아온 것을 다시 올리지 않게
    return touched


class ScheduleDialog(tk.Toplevel):
    def __init__(self, app, sid=None, date=None, member_id=None, title_default="", on_saved=None):
        super().__init__(app.root)
        self.app, self.db, self.sid, self.on_saved = app, app.db, sid, on_saved
        self.row = self.db.one("SELECT * FROM schedules WHERE id=?", (sid,)) if sid else None
        self.title("일정 수정" if self.row else "일정 / 알림 예약")
        self.configure(bg=BG)
        self.geometry("560x680")
        self.minsize(500, 600)
        self._auto_job, self._dirty = None, False

        f = tk.Frame(self, bg=BG, padx=16, pady=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        def lab(text, r):
            tk.Label(f, text=text, font=FONT_B, bg=BG).grid(row=r, column=0, sticky="nw", pady=5, padx=(0, 10))

        # 일정 날짜 / 시간
        lab("일정 날짜", 0)
        dtf = tk.Frame(f, bg=BG)
        dtf.grid(row=0, column=1, sticky="w", pady=3)
        self.date_var, self.h, self.m = tk.StringVar(), tk.StringVar(), tk.StringVar()
        tk.Entry(dtf, textvariable=self.date_var, width=11, font=FONT).pack(side="left", ipady=2)
        tk.Label(dtf, text="  ", bg=BG).pack(side="left")
        tk.Spinbox(dtf, from_=0, to=23, width=3, format="%02.0f", wrap=True,
                   textvariable=self.h, font=FONT).pack(side="left", ipady=1)
        tk.Label(dtf, text=":", bg=BG, font=FONT_B).pack(side="left")
        tk.Spinbox(dtf, from_=0, to=59, increment=5, width=3, format="%02.0f", wrap=True,
                   textvariable=self.m, font=FONT).pack(side="left", ipady=1)

        qf = tk.Frame(f, bg=BG)
        qf.grid(row=1, column=1, sticky="w", pady=(2, 6))
        for text, delta in (("+10분", 10), ("+30분", 30), ("+1시간", 60), ("+3시간", 180)):
            btn(qf, text, lambda d=delta: self.set_dt(now() + dt.timedelta(minutes=d))).pack(side="left", padx=(0, 3))
        btn(qf, "내일 이 시간", self.tomorrow).pack(side="left")

        # 제목 / 내용 (회원 연결은 화면에 안 보이고 내부에만 유지)
        lab("제목", 3)
        self.title_var = tk.StringVar()
        tk.Entry(f, textvariable=self.title_var, font=FONT).grid(row=3, column=1, sticky="ew", pady=4, ipady=2)
        lab("내용", 4)
        self.content = tk.Text(f, height=5, wrap="word", font=FONT)
        self.content.grid(row=4, column=1, sticky="nsew", pady=4)
        f.rowconfigure(4, weight=1)

        # 알림
        lab("알림", 5)
        af = tk.Frame(f, bg=BG)
        af.grid(row=5, column=1, sticky="ew", pady=4)
        pf = FlowBar(af, align="left", gap=3, bg=BG)
        pf.pack(fill="x")
        for text, m in ALARM_PRESETS:
            pf.add(btn(pf, "+" + text, lambda m=m: self.add_alarm({"offset": m})))
        pf2 = FlowBar(af, align="left", gap=3, bg=BG)
        pf2.pack(fill="x", pady=(4, 4))
        pf2.add(btn(pf2, "📅 날짜·시간 직접 지정", self.custom_alarm))
        pf2.add(btn(pf2, "🔁 반복 알림", self.repeat_alarm))
        pf2.add(btn(pf2, "모두 지우기", self.clear_alarms))
        pf2.add(btn(pf2, "선택 삭제", self.del_alarm))
        self.al_tree = ttk.Treeview(af, columns=("kind", "when"), show="headings", height=5, selectmode="extended")
        self.al_tree.heading("kind", text="종류")
        self.al_tree.heading("when", text="알림 울리는 시각")
        self.al_tree.column("kind", width=150, anchor="w")
        self.al_tree.column("when", width=200, anchor="center", stretch=False)
        fit_columns(self.al_tree, {"kind": (1, 90), "when": (1.4, 120)})
        self.al_tree.tag_configure("past", foreground="#B5AA95")
        self.al_tree.pack(fill="x")
        self.al_tree.bind("<Delete>", lambda e: self.del_alarm())
        self.al_hint = tk.Label(af, font=FONT_S, fg=MUTED, bg=BG, anchor="w")
        self.al_hint.pack(fill="x", pady=(2, 0))

        of = tk.Frame(f, bg=BG)
        of.grid(row=6, column=1, sticky="w", pady=4)
        self.done_var = tk.IntVar(value=0)
        tk.Checkbutton(of, text="완료 (남은 알림 끄기)", variable=self.done_var, bg=BG, font=FONT,
                       activebackground=BG).pack(side="left")

        bf = tk.Frame(f, bg=BG)
        bf.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))
        if self.row:
            btn(bf, "삭제", self.delete).pack(side="left", padx=3)
        btn(bf, "취소", self.cancel).pack(side="left", padx=3)
        btn(bf, "저장 (Ctrl+S)", self.save, primary=True).pack(side="left", padx=3)
        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.close_save)
        self.orig_row = self.row
        self.orig_alarms = [tuple(a) for a in self.db.q("SELECT * FROM alarms WHERE schedule_id=?", (sid,))] if sid else []

        # 값 채우기
        if self.row:
            self.set_dt(parse_dt(self.row["date"], self.row["time"]))
            self.title_var.set(self.row["title"] or "")
            self.content.insert("1.0", self.row["content"] or "")
            self.done_var.set(self.row["done"])
            self.items = load_alarm_items(self.db, sid)
            member_id = self.row["member_id"]
        else:
            if date and date != dt.date.today().isoformat():
                self.set_dt(dt.datetime.strptime(date + " 10:00", "%Y-%m-%d %H:%M"))
            else:
                self.set_dt((now() + dt.timedelta(hours=1)).replace(minute=0))
            self.title_var.set(title_default)
            self.items = [{"offset": 0}]          # 기본: 정시 알림
        self.member_id = member_id
        self.refresh_alarms()
        self._dirty = False
        bring_front(self)

        for v in (self.title_var, self.done_var):
            v.trace_add("write", lambda *a: self.schedule_autosave())
        for v in (self.date_var, self.h, self.m):
            v.trace_add("write", lambda *a: (self.refresh_alarms(), self.schedule_autosave()))
        self.content.bind("<<Modified>>", self.on_content_mod)
        self.content.edit_modified(False)

    # ---- 알림 목록 ----
    def event_dt(self):
        try:
            return self.current_dt()
        except Exception:
            return None

    def sorted_items(self):
        ev = self.event_dt()
        if not ev:
            return list(self.items)
        return sorted(self.items, key=lambda it: alarm_fire(ev, it))

    def refresh_alarms(self):
        if not hasattr(self, "al_tree"):
            return
        self.items = self.sorted_items()
        self.al_tree.delete(*self.al_tree.get_children())
        ev = self.event_dt()
        for i, it in enumerate(self.items):
            kind = offset_label(it["offset"]) if it.get("offset") is not None else "직접 지정"
            if ev:
                fire = alarm_fire(ev, it)
                when = f"{fire.month}/{fire.day} ({wd_name(fire)}) {fire:%H:%M}"
                tags = ("past",) if fire <= now() else ()
            else:
                when, tags = "-", ()
            self.al_tree.insert("", "end", iid=str(i), values=(kind, when), tags=tags)
        n = len(self.items)
        self.al_hint.config(text=f"알림 {n}개 — 시간이 되면 PC 팝업 + 폰 알림" if n else "알림 없음 (달력에만 기록)")

    def add_alarm(self, it):
        ev = self.event_dt()
        if ev:
            k = fmt_dt(alarm_fire(ev, it))
            if any(fmt_dt(alarm_fire(ev, x)) == k for x in self.items):
                return
        self.items.append(it)
        self.refresh_alarms()
        self.schedule_autosave()

    def del_alarm(self):
        sel = {int(i) for i in self.al_tree.selection()}
        if sel:
            self.items = [it for i, it in enumerate(self.items) if i not in sel]
            self.refresh_alarms()
            self.schedule_autosave()

    def clear_alarms(self):
        self.items = []
        self.refresh_alarms()
        self.schedule_autosave()

    def custom_alarm(self):
        ev = self.event_dt() or now()
        CustomAlarmDialog(self, ev - dt.timedelta(days=1), lambda at: self.add_alarm({"at": at}))

    def repeat_alarm(self):
        RepeatAlarmDialog(self, lambda offs: [self.add_alarm({"offset": o}) for o in offs])

    # ---- 일정 ----
    def on_content_mod(self, _=None):
        if self.content.edit_modified():
            self.content.edit_modified(False)
            self.schedule_autosave()

    def schedule_autosave(self):
        """일정 창은 자동 저장하지 않음 — 바뀐 것만 표시하고 [저장]을 눌러야 저장"""
        self._dirty = True

    def cancel(self):
        """취소: 저장하지 않고 닫기"""
        self.destroy()

    def close_save(self):
        """X로 닫을 때: 바꾼 내용이 있으면 저장할지 물어봄"""
        if not self._dirty:
            self.destroy()
            return
        ans = messagebox.askyesnocancel("일정", "저장하지 않은 내용이 있어요.\n저장할까요?", parent=self)
        if ans is None:
            return
        if ans:
            self.save(close=True)
        else:
            self.destroy()

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

    def save(self, close=True, quiet=False):
        if self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None
        try:
            when = self.current_dt()
        except Exception:
            if not quiet:
                messagebox.showerror("입력 오류", "날짜는 2026-10-12, 시간은 0~23 / 0~59 형식으로 입력해주세요.", parent=self)
            return
        if not self.row and quiet and not (self.title_var.get().strip() or self.content.get("1.0", "end-1c").strip()):
            return   # 아무것도 안 쓴 새 일정은 자동 저장하지 않음
        title = self.title_var.get().strip() or "(제목 없음)"
        mid = self.member_id
        d, t = when.strftime("%Y-%m-%d"), when.strftime("%H:%M")
        vals = (d, t, title, self.content.get("1.0", "end-1c"), mid, 1 if self.items else 0, 0, self.done_var.get())
        if self.row:
            self.db.x("UPDATE schedules SET date=?,time=?,title=?,content=?,member_id=?,alarm=?,notified=?,done=? "
                      "WHERE id=?", vals + (self.sid,))
        else:
            self.sid = self.db.x("INSERT INTO schedules(date,time,title,content,member_id,alarm,notified,done) "
                                 "VALUES(?,?,?,?,?,?,?,?)", vals)
        save_alarms(self.db, self.sid, when, self.items)
        self.row = self.db.one("SELECT * FROM schedules WHERE id=?", (self.sid,))
        self.app.refresh_all()
        if self.on_saved:
            self.on_saved()
        if close:
            self.destroy()

    def delete(self):
        if messagebox.askyesno("삭제", "이 일정을 삭제할까요?", parent=self):
            if self._auto_job:
                self.after_cancel(self._auto_job)
            self.db.x("DELETE FROM schedules WHERE id=?", (self.sid,))
            self.db.x("DELETE FROM alarms WHERE schedule_id=?", (self.sid,))
            self.app.refresh_all()
            if self.on_saved:
                self.on_saved()
            self.destroy()


class CustomAlarmDialog(tk.Toplevel):
    """알림 날짜·시간 직접 지정"""

    def __init__(self, parent, default, on_ok):
        super().__init__(parent)
        self.on_ok = on_ok
        self.title("알림 시각 직접 지정")
        self.configure(bg=BG, padx=18, pady=16)
        self.resizable(False, False)
        self.transient(parent)
        self.after(50, lambda: bring_front(self))
        tk.Label(self, text="이 날짜·시간에 알림", font=FONT_B, bg=BG).pack(anchor="w")
        row = tk.Frame(self, bg=BG)
        row.pack(pady=10)
        self.d, self.h, self.m = tk.StringVar(), tk.StringVar(), tk.StringVar()
        tk.Entry(row, textvariable=self.d, width=11, font=FONT).pack(side="left", ipady=2)
        tk.Label(row, text="  ", bg=BG).pack(side="left")
        tk.Spinbox(row, from_=0, to=23, width=3, format="%02.0f", wrap=True, textvariable=self.h,
                   font=FONT).pack(side="left")
        tk.Label(row, text=":", bg=BG, font=FONT_B).pack(side="left")
        tk.Spinbox(row, from_=0, to=59, increment=5, width=3, format="%02.0f", wrap=True, textvariable=self.m,
                   font=FONT).pack(side="left")
        self.d.set(default.strftime("%Y-%m-%d"))
        self.h.set(f"{default.hour:02d}")
        self.m.set(f"{default.minute:02d}")
        bf = tk.Frame(self, bg=BG)
        bf.pack(anchor="e")
        btn(bf, "취소", self.destroy).pack(side="left", padx=3)
        btn(bf, "추가", self.ok, primary=True).pack(side="left")
        self.bind("<Return>", lambda e: self.ok())
        self.grab_set()

    def ok(self):
        try:
            at = parse_dt(self.d.get().strip(), f"{int(self.h.get()):02d}:{int(self.m.get()):02d}")
        except Exception:
            messagebox.showerror("입력 오류", "날짜는 2026-10-28, 시간은 0~23 / 0~59 로 입력해주세요.", parent=self)
            return
        self.grab_release()
        self.destroy()
        self.on_ok(at)


class RepeatAlarmDialog(tk.Toplevel):
    """반복 알림: 일정 ○○ 전부터 ○○마다 ○번"""

    def __init__(self, parent, on_ok):
        super().__init__(parent)
        self.on_ok = on_ok
        self.title("🔁 반복 알림")
        self.configure(bg=BG, padx=18, pady=16)
        self.resizable(False, False)
        self.transient(parent)
        self.after(50, lambda: bring_front(self))
        row = tk.Frame(self, bg=BG)
        row.pack(anchor="w")
        tk.Label(row, text="일정", font=FONT_B, bg=BG).pack(side="left")
        self.start = ttk.Combobox(row, values=[x[0] for x in REPEAT_START], state="readonly", width=9, font=FONT)
        self.start.current(2)
        self.start.pack(side="left", padx=6)
        tk.Label(row, text="부터", font=FONT_B, bg=BG).pack(side="left")
        self.gap = ttk.Combobox(row, values=[x[0] for x in REPEAT_GAP], state="readonly", width=9, font=FONT)
        self.gap.current(3)
        self.gap.pack(side="left", padx=6)
        self.cnt = tk.StringVar(value="3")
        tk.Spinbox(row, from_=2, to=20, width=3, textvariable=self.cnt, font=FONT).pack(side="left")
        tk.Label(row, text="번", font=FONT_B, bg=BG).pack(side="left", padx=(4, 0))
        self.preview = tk.Label(self, font=FONT_S, fg=ACCENT_DK, bg=BG, justify="left", anchor="w")
        self.preview.pack(fill="x", pady=(10, 8))
        for w in (self.start, self.gap):
            w.bind("<<ComboboxSelected>>", lambda e: self.update_preview())
        self.cnt.trace_add("write", lambda *a: self.update_preview())
        bf = tk.Frame(self, bg=BG)
        bf.pack(anchor="e")
        btn(bf, "취소", self.destroy).pack(side="left", padx=3)
        btn(bf, "추가", self.ok, primary=True).pack(side="left")
        self.update_preview()
        self.grab_set()

    def offsets(self):
        s = REPEAT_START[self.start.current()][1]
        g = REPEAT_GAP[self.gap.current()][1]
        try:
            n = max(1, min(50, int(self.cnt.get())))
        except ValueError:
            n = 1
        return [s - i * g for i in range(n) if s - i * g >= 0]

    def update_preview(self):
        offs = self.offsets()
        txt = " → ".join(offset_label(o) for o in offs)
        self.preview.config(text=f"알림 {len(offs)}개:  {txt}")

    def ok(self):
        offs = self.offsets()
        self.grab_release()
        self.destroy()
        self.on_ok(offs)


# ───────────────────────── 회원 관리 팝업 ─────────────────────────
class MemberDialog(tk.Toplevel):
    def __init__(self, app, mid=None):
        super().__init__(app.root)
        self.app, self.db, self.mid = app, app.db, mid
        self.configure(bg=BG)
        self.geometry("680x720")
        self.minsize(480, 460)

        top = tk.Frame(self, bg=BG, padx=12, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="이름", font=FONT_B, bg=BG).grid(row=0, column=0, sticky="w")
        self.name_var, self.phone_var = tk.StringVar(), tk.StringVar()
        self.name_entry = tk.Entry(top, textvariable=self.name_var, width=18, font=(F, 12))
        self.name_entry.grid(row=0, column=1, padx=(6, 18))
        tk.Label(top, text="휴대폰", font=FONT_B, bg=BG).grid(row=0, column=2, sticky="w")
        tk.Entry(top, textvariable=self.phone_var, width=18, font=(F, 12)).grid(row=0, column=3, padx=6)
        tk.Label(top, text="검색어", font=FONT_B, bg=BG).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.kw_var = tk.StringVar()
        tk.Entry(top, textvariable=self.kw_var, font=(F, 11)).grid(row=1, column=1, columnspan=3, sticky="ew",
                                                                   padx=(6, 6), pady=(6, 0))
        top.columnconfigure(3, weight=1)
        self.info_lbl = tk.Label(top, font=FONT_S, fg=MUTED, bg=BG)
        self.info_lbl.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # 상담 내용
        mf = tk.LabelFrame(self, text=" 상담 내용 정리 ", font=FONT_B, bg=BG, padx=6, pady=6)
        mf.pack(fill="both", expand=True, padx=12)
        bar = tk.Frame(mf, bg=BG)
        bar.pack(fill="x", pady=(0, 4))
        btn(bar, "🕒 현재시간 입력 (F5)", self.insert_stamp).pack(side="left")
        tk.Label(bar, text="  줄마다 날짜를 찍고 내용을 이어 쓰세요", font=FONT_S, fg=MUTED, bg=BG).pack(side="left")
        tf = tk.Frame(mf)
        tf.pack(fill="both", expand=True)
        self.memo = tk.Text(tf, wrap="word", font=FONT, undo=True)
        sb = ttk.Scrollbar(tf, command=self.memo.yview)
        self.memo.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.memo.pack(side="left", fill="both", expand=True)

        # 재통화 / 예약
        rf = tk.LabelFrame(self, text=" 재통화 · 예약 알림 ", font=FONT_B, bg=BG, padx=6, pady=6)
        rb = tk.Frame(rf, bg=BG)
        rb.pack(fill="x", pady=(0, 4))
        btn(rb, "+ 재통화 예약", self.add_res, primary=True).pack(side="left")
        btn(rb, "수정", self.edit_res).pack(side="left", padx=3)
        btn(rb, "완료/해제", self.toggle_res).pack(side="left")
        cols = ("when", "title", "state")
        self.res = ttk.Treeview(rf, columns=cols, show="headings", height=4)
        for c, t, w in (("when", "일시", 140), ("title", "제목", 260), ("state", "알림", 130)):
            self.res.heading(c, text=t)
            self.res.column(c, width=w, anchor="w" if c == "title" else "center", stretch=False)
        fit_columns(self.res, {"when": (1.3, 120), "title": (2.4, 80), "state": (1.3, 100)}, hide_order=("state",))
        self.res.tag_configure("done", foreground="#B5AA95")
        self.res.pack(fill="x")
        self.res.bind("<Double-1>", lambda e: self.edit_res())

        # 하단 (창이 작아져도 버튼·예약목록은 항상 보이게, 상담 내용 칸이 줄어듦)
        bf = tk.Frame(self, bg=BG, padx=12, pady=10)
        bf.pack(side="bottom", fill="x", before=mf)
        rf.pack(side="bottom", fill="x", padx=12, pady=(8, 0), before=mf)
        btn(bf, "회원 삭제", self.delete).pack(side="left")
        btn(bf, "닫기", self.on_close).pack(side="right", padx=3)
        btn(bf, "저장 (Ctrl+S)", self.save, primary=True).pack(side="right", padx=3)
        self.save_lbl = tk.Label(bf, font=FONT_B, fg=OK_C, bg=BG)
        self.save_lbl.pack(side="right", padx=10)

        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<F5>", lambda e: self.insert_stamp())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._auto_job = None
        self.load()
        for v in (self.name_var, self.phone_var, self.kw_var):
            v.trace_add("write", lambda *a: self.schedule_autosave())
        self.memo.bind("<<Modified>>", self.on_memo_mod)
        self.name_entry.focus_set()

    # 입력하면 0.5초 뒤 자동 저장
    def on_memo_mod(self, _=None):
        if self.memo.edit_modified():
            self.memo.edit_modified(False)
            self.schedule_autosave()

    def schedule_autosave(self):
        if getattr(self, "_loading", False):
            return
        if self._auto_job:
            self.after_cancel(self._auto_job)
        self._auto_job = self.after(500, lambda: self.winfo_exists() and self.save(quiet=True))

    def load(self):
        self._loading = True
        row = self.db.one("SELECT * FROM members WHERE id=?", (self.mid,)) if self.mid else None
        self.name_var.set(row["name"] if row else "")
        self.phone_var.set(row["phone"] if row else "")
        self.kw_var.set((row["keyword"] or "") if row else "")
        self.memo.delete("1.0", "end")
        self.memo.insert("1.0", row["memo"] if row else "")
        self.memo.edit_reset()
        self.memo.edit_modified(False)
        self.orig = self.values()
        self.show_info(row)
        self.load_res()
        self.after_idle(lambda: setattr(self, "_loading", False))

    def flash_saved(self, quiet):
        if not quiet and self.winfo_exists():
            self.save_lbl.config(text=f"✔ 저장했습니다  {now():%H:%M:%S}")
            self.after(2500, lambda: self.winfo_exists() and self.save_lbl.config(text=""))

    def show_info(self, row):
        self.title(f"회원 관리 - {row['name']}" if row else "새 회원 등록")
        self.info_lbl.config(text=f"등록 {row['created'][:16]}   ·   수정 {row['updated'][:16]}   ·   ✔ 자동 저장됨"
                             if row else "새 회원 — 입력하면 자동 저장됩니다")

    def values(self):
        return (self.name_var.get().strip(), self.phone_var.get().strip(), self.memo.get("1.0", "end-1c"),
                self.kw_var.get().strip())

    def load_res(self):
        self.res.delete(*self.res.get_children())
        if not self.mid:
            return
        for r in self.db.q("SELECT * FROM schedules WHERE member_id=? ORDER BY done, date, time", (self.mid,)):
            self.res.insert("", "end", iid=str(r["id"]), values=(f'{r["date"]} {r["time"]}', r["title"], state_text(r, self.db)),
                            tags=("done",) if r["done"] else ())

    def insert_stamp(self):
        content = self.memo.get("1.0", "end-1c")
        prefix = "" if (content == "" or content.endswith("\n")) else "\n"
        self.memo.insert("end", f"{prefix}{stamp()} ")
        self.memo.mark_set("insert", "end")
        self.memo.see("end")
        self.memo.focus_set()
        return "break"

    def save(self, quiet=False):
        if self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None
        name, phone, memo, kw = self.values()
        if not name and not phone:
            if not quiet:
                messagebox.showwarning("확인", "이름이나 전화번호 중 하나는 입력해주세요.", parent=self)
            return False
        if self.mid and (name, phone, memo, kw) == self.orig:
            self.flash_saved(quiet)
            return True
        if self.mid:
            self.db.x("UPDATE members SET name=?,phone=?,memo=?,keyword=?,updated=? WHERE id=?",
                      (name, phone, memo, kw, stamp(), self.mid))
        else:
            self.mid = self.db.x("INSERT INTO members(name,phone,memo,keyword,created,updated) VALUES(?,?,?,?,?,?)",
                                 (name, phone, memo, kw, stamp(), stamp()))
            self.app.member_windows[self.mid] = self
        self.orig = (name, phone, memo, kw)
        self.show_info(self.db.one("SELECT * FROM members WHERE id=?", (self.mid,)))
        self.flash_saved(quiet)
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
            if self._auto_job:
                self.after_cancel(self._auto_job)
            self.db.x("DELETE FROM schedules WHERE member_id=?", (self.mid,))
            self.db.x("DELETE FROM members WHERE id=?", (self.mid,))
            self.app.member_windows.pop(self.mid, None)
            self.app.refresh_all()
            self.destroy()

    def on_close(self):
        self.save(quiet=True)
        self.app.member_windows.pop(self.mid, None)
        self.destroy()


# ───────────────────────── 메모 창 ─────────────────────────
NOTE_BG = "#FFF5D8"


class NoteWindow(tk.Toplevel):
    """메모 1개 = 창 1개. 입력 즉시 자동 저장, 창 크기·위치·항상 위는 메모마다 기억"""

    def __init__(self, app, nid):
        super().__init__(app.root)
        self.app, self.db, self.nid = app, app.db, nid
        row = self.db.one("SELECT * FROM notes WHERE id=?", (nid,))
        self.configure(bg=NOTE_BG)
        self.minsize(220, 120)
        self._job, self._geo_job, self._closing = None, None, False

        bar = tk.Frame(self, bg=NOTE_BG, padx=6, pady=4)
        bar.pack(fill="x")
        self.title_var = tk.StringVar(value=row["title"] or "")
        te = tk.Entry(bar, textvariable=self.title_var, font=FONT_B, relief="flat", bg="#FFF9E8")
        te.pack(side="left", fill="x", expand=True, ipady=2)
        btn(bar, "삭제", self.delete).pack(side="right", padx=(4, 0))
        self.top_var = tk.BooleanVar(value=bool(row["topmost"]))
        self.top_btn = tk.Checkbutton(bar, text="📌 항상 위", variable=self.top_var, font=FONT_S,
                                      bg=NOTE_BG, activebackground=NOTE_BG, command=self.toggle_top)
        self.top_btn.pack(side="right", padx=4)
        self.status = tk.Label(bar, text="저장됨", font=FONT_S, fg=OK_C, bg=NOTE_BG, width=6)
        self.status.pack(side="right")

        tf = tk.Frame(self)
        tf.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.txt = tk.Text(tf, wrap="word", font=FONT, undo=True, relief="flat", bd=0,
                           bg="#FFFDF5", padx=6, pady=4)
        sb = ttk.Scrollbar(tf, command=self.txt.yview)
        self.txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.insert("1.0", row["content"] or "")
        self.txt.edit_reset()
        self.txt.edit_modified(False)
        self.txt.bind("<<Modified>>", self.on_mod)
        self.title_var.trace_add("write", lambda *a: self.on_mod(force=True))
        self.update_title()

        self.restore_geometry(row["geometry"])
        self.attributes("-topmost", self.top_var.get())
        self.bind("<Configure>", self.on_configure)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.lift()
        self.focus_force()
        if row["title"]:
            self.txt.focus_set()
            self.txt.mark_set("insert", "end")
        else:
            te.focus_set()

    # 창 위치/크기 기억
    def restore_geometry(self, geo):
        m = re.fullmatch(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", geo or "")
        if not m:
            x = self.app.root.winfo_rootx() + 80 + (self.nid % 6) * 28
            y = self.app.root.winfo_rooty() + 80 + (self.nid % 6) * 28
            self.geometry(f"420x360+{x}+{y}")
            return
        w, h, x, y = int(m[1]), int(m[2]), int(m[3]), int(m[4])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        vx, vy = self.winfo_vrootx(), self.winfo_vrooty()
        vw, vh = max(self.winfo_vrootwidth(), sw), max(self.winfo_vrootheight(), sh)
        if not (vx - w + 60 <= x <= vx + vw - 60 and vy <= y <= vy + vh - 60):  # 모니터 밖이면 안으로
            x, y = 100, 100
        self.geometry(f"{w}x{h}+{x}+{y}")

    def on_configure(self, e):
        if e.widget is not self:
            return
        if self._geo_job:
            self.after_cancel(self._geo_job)
        self._geo_job = self.after(500, self.save_geometry)

    def save_geometry(self):
        self._geo_job = None
        if self.winfo_exists() and self.state() == "normal":
            self.db.x("UPDATE notes SET geometry=? WHERE id=?", (self.geometry(), self.nid))

    def toggle_top(self):
        self.attributes("-topmost", self.top_var.get())
        self.db.x("UPDATE notes SET topmost=? WHERE id=?", (int(self.top_var.get()), self.nid))

    # 자동 저장
    def update_title(self):
        t = self.title_var.get().strip() or "제목 없음"
        self.title(f"📝 {t}")

    def on_mod(self, _=None, force=False):
        if not force:
            if not self.txt.edit_modified():
                return
            self.txt.edit_modified(False)
        if getattr(self, "_applying", False):
            return
        self.update_title()
        self.status.config(text="저장 중", fg=WARN_C)
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(400, self.save)

    def save(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = None
        if not self.db.one("SELECT id FROM notes WHERE id=?", (self.nid,)):
            return
        self.db.x("UPDATE notes SET title=?, content=?, updated=? WHERE id=?",
                  (self.title_var.get().strip(), self.txt.get("1.0", "end-1c"), stamp(), self.nid))
        if self.winfo_exists():
            self.status.config(text="저장됨", fg=OK_C)
        self.app.refresh_notes()

    def apply_remote(self, row):
        """웹앱에서 고친 내용으로 바꿔 보여주기 (지금 PC에서 쓰는 중이면 PC 것이 우선)"""
        if self._job:
            return
        if (self.title_var.get().strip(), self.txt.get("1.0", "end-1c")) == ((row["title"] or ""), (row["content"] or "")):
            return
        self._applying = True
        try:
            pos = self.txt.index("insert")
            self.title_var.set(row["title"] or "")
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", row["content"] or "")
            self.txt.mark_set("insert", pos)
            self.txt.edit_reset()
            self.txt.edit_modified(False)
            self.update_title()
            self.update_idletasks()
        finally:
            self.after(50, lambda: setattr(self, "_applying", False))

    def delete(self):
        name = self.title_var.get().strip() or "제목 없음"
        if messagebox.askyesno("메모 삭제", f"'{name}' 메모를 삭제할까요?", parent=self):
            if self._job:
                self.after_cancel(self._job)
            self.db.x("DELETE FROM notes WHERE id=?", (self.nid,))
            self.app.note_windows.pop(self.nid, None)
            self.app.refresh_notes()
            self.destroy()

    def close(self):
        self.save()
        self.save_geometry()
        if not self.title_var.get().strip() and not self.txt.get("1.0", "end-1c").strip():
            self.db.x("DELETE FROM notes WHERE id=?", (self.nid,))   # 아무것도 안 쓴 메모는 지움
            self.app.refresh_notes()
        self.app.note_windows.pop(self.nid, None)
        self.destroy()


class NoteListDialog(tk.Toplevel):
    """메모 더보기: 전체 메모 목록 + 검색"""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("📝 전체 메모")
        self.configure(bg=BG)
        self.geometry("420x520")

        top = tk.Frame(self, bg=BG, padx=8, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="🔍", bg=BG).pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self.load())
        e = tk.Entry(top, textvariable=self.q, font=FONT)
        e.pack(side="left", fill="x", expand=True, padx=4)
        btn(top, "+ 새 메모", lambda: (self.app.new_note(), self.destroy()), primary=True).pack(side="right")
        cols = ("title", "preview", "updated")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        for c, t, w in (("title", "제목", 120), ("preview", "내용", 200), ("updated", "수정", 80)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c != "updated" else "center", stretch=False)
        fit_columns(self.tree, {"title": (1.3, 70), "preview": (2.2, 80), "updated": (0.8, 55)})
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree.bind("<ButtonRelease-1>", self.open_sel)
        self.tree.bind("<Return>", self.open_sel)
        self.load()
        e.focus_set()
        bring_front(self)

    def load(self):
        kw = f"%{self.q.get().strip()}%"
        self.tree.delete(*self.tree.get_children())
        for r in self.app.db.q("SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? ORDER BY id", (kw, kw)):
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["title"] or "제목 없음", short(r["content"], 40), (r["updated"] or "")[5:10]))

    def open_sel(self, _=None):
        s = self.tree.selection()
        if s:
            self.app.open_note(int(s[0]))


# ───────────────────────── 알림 팝업 ─────────────────────────
class AlarmPopup(tk.Toplevel):
    def __init__(self, app, row, offset=0):
        super().__init__(app.root)
        self.app, self.sid, self.member_id = app, row["id"], row["member_id"]
        bg = DARK
        self.title("⏰ 예약 알림")
        self.configure(bg=bg, highlightthickness=2, highlightbackground=ACCENT)
        self.attributes("-topmost", True)
        member = app.db.one("SELECT * FROM members WHERE id=?", (self.member_id,)) if self.member_id else None

        tk.Label(self, text="◆  예약 알림  ◆", font=(F, 12, "bold"), fg=GOLD_BR, bg=bg).pack(pady=(18, 2))
        ev = parse_dt(row["date"], row["time"])
        sub = f'일정  {ev.month}/{ev.day} ({wd_name(ev)}) {row["time"]}'
        if row["offset_min"]:
            sub += f'   ·   {offset_label(row["offset_min"])} 알림'
        tk.Label(self, text=sub, font=FONT_B, fg="#9C8B66", bg=bg).pack()
        tk.Frame(self, bg=ACCENT, height=1, width=260).pack(pady=10)
        tk.Label(self, text=row["title"], font=(F, 15, "bold"), fg="#F5EBD3", wraplength=380,
                 bg=bg).pack(pady=(0, 4), padx=20)
        if member:
            tk.Label(self, text=f'{member["name"]}   {member["phone"]}', font=(F, 13, "bold"), fg=GOLD_BR,
                     bg=bg).pack()
        if (row["content"] or "").strip():
            tk.Label(self, text=row["content"], font=FONT, fg="#D9CCAF", wraplength=380, justify="left",
                     bg=bg).pack(pady=6, padx=20)

        bf = tk.Frame(self, bg=bg)
        bf.pack(pady=(12, 18))
        btn(bf, "확인", self.destroy, primary=True).pack(side="left", padx=3)
        btn(bf, "완료 (남은 알림 끄기)", self.done, dark=True).pack(side="left", padx=3)
        btn(bf, "10분 뒤", lambda: self.snooze(10), dark=True).pack(side="left", padx=3)
        btn(bf, "30분 뒤", lambda: self.snooze(30), dark=True).pack(side="left", padx=3)
        if member:
            btn(bf, "회원 열기", self.open_member, dark=True).pack(side="left", padx=3)

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
        t = now() + dt.timedelta(minutes=minutes)    # 일정은 그대로, 알림만 하나 추가
        self.app.db.x("INSERT INTO alarms(schedule_id, offset_min, fire_at, notified) VALUES(?, NULL, ?, 0)",
                      (self.sid, fmt_dt(t)))
        self.app.refresh_all()
        self.destroy()

    def open_member(self):
        self.app.open_member(self.member_id)
        self.destroy()


# ───────────────────────── 폰 알림 설정 ─────────────────────────
def easy_topic():
    """폰에서 치기 쉬운 토픽 이름: wd-1234-5678 (숫자 8자리, 1억 가지)"""
    r = random.SystemRandom()
    return f"wd-{r.randint(1000, 9999)}-{r.randint(1000, 9999)}"


TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


MEMBER_COLORS = [("빨강", "#C0392B"), ("주황", "#D9730D"), ("금색", "#A87A12"), ("초록", "#2E7D32"),
                 ("파랑", "#1F5FA8"), ("보라", "#7B3FA0"), ("분홍", "#C2185B"), ("회색", "#8A7F6B"), ("기본", "")]


def make_qr_matrix(text):
    """QR코드 칸 배열 (qrcode 라이브러리가 있을 때만)"""
    try:
        import qrcode
    except ImportError:
        return None
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    return q.get_matrix()


def draw_qr(parent, text, cell=5, bg=None):
    qr = make_qr_matrix(text)
    if not qr:
        return None
    n = len(qr)
    cv = tk.Canvas(parent, width=n * cell, height=n * cell, bg="white", highlightthickness=0)
    for y, row in enumerate(qr):
        for x, v in enumerate(row):
            if v:
                cv.create_rectangle(x * cell, y * cell, x * cell + cell, y * cell + cell, fill="#1F1B16", outline="")
    return cv


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app, self.db = app, app.db
        self.title("📱 폰 연결 · 웹앱")
        self.configure(bg=BG)
        self.resizable(False, False)
        on, use_ntfy, _ = phone_cfg(self.db)
        ch = channels(self.db)
        self.en = tk.IntVar(value=int(on))
        self.ch_tg = tk.IntVar(value=int(ch["tg"]))
        self.ch_web = tk.IntVar(value=int(ch["web"]))
        self.use_ntfy = tk.IntVar(value=int(use_ntfy))
        self.topic = tk.StringVar(value=self.db.get("ntfy_topic") or easy_topic())
        self.server = tk.StringVar(value=self.db.get("ntfy_server", "https://ntfy.sh"))
        self.info = {}

        f = tk.Frame(self, bg=BG, padx=20, pady=16)
        f.pack(fill="both", expand=True)
        tk.Checkbutton(f, text="예약 알림을 폰으로도 받기", variable=self.en, font=FONT_B, bg=BG,
                       activebackground=BG).pack(anchor="w")

        if WORKER_URL:
            cf = tk.Frame(f, bg=BG)
            cf.pack(anchor="w", pady=(6, 8))
            tk.Label(cf, text="받을 곳:", font=FONT_B, bg=BG).pack(side="left")
            tk.Checkbutton(cf, text="텔레그램 (추천 · 잘 안 꺼짐)", variable=self.ch_tg, font=FONT, bg=BG,
                           activebackground=BG).pack(side="left", padx=(8, 0))
            tk.Checkbutton(cf, text="웹앱 알림", variable=self.ch_web, font=FONT, bg=BG,
                           activebackground=BG).pack(side="left", padx=(8, 0))
            tk.Checkbutton(cf, text="ntfy (예전 방식)", variable=self.use_ntfy, font=FONT, bg=BG,
                           activebackground=BG).pack(side="left", padx=(8, 0))

            nb = ttk.Notebook(f)
            nb.pack(fill="both", expand=True)
            self.tg_tab = tk.Frame(nb, bg=PANEL, padx=16, pady=14)
            web_tab = tk.Frame(nb, bg=PANEL, padx=16, pady=14)
            nt_tab = tk.Frame(nb, bg=PANEL, padx=16, pady=14)
            nb.add(web_tab, text="  📱 웹앱 (일정·회원·메모)  ")
            nb.add(self.tg_tab, text="  텔레그램  ")
            nb.add(nt_tab, text="  ntfy  ")

            # ── 텔레그램 탭 (봇 이름은 서버에서 받아옴) ──
            self.tg_msg = tk.Label(self.tg_tab, text="서버 확인 중…", font=FONT, bg=PANEL, fg=MUTED, justify="left")
            self.tg_msg.pack(anchor="w")

            # ── 웹앱 탭 ──
            self.link = f"{WORKER_URL.rstrip('/')}/app?d={app.device_id}&k={app.web_token}"
            row = tk.Frame(web_tab, bg=PANEL)
            row.pack(fill="x")
            cv = draw_qr(row, self.link, cell=4)
            if cv:
                cv.pack(side="left", padx=(0, 16))
            right = tk.Frame(row, bg=PANEL)
            right.pack(side="left", anchor="n")
            tk.Label(right, text="폰에서 일정·달력·회원·메모를 보고 등록·수정", font=FONT_T, fg=ACCENT_DK,
                     bg=PANEL).pack(anchor="w")
            tk.Label(right, font=FONT, bg=PANEL, justify="left", text=(
                "① 폰 카메라로 QR코드를 찍으세요 (안드로이드는 '크롬'으로 열기)\n"
                "② [알림] 탭 → [🔔 알림 켜기] → '허용'\n"
                "③ '홈 화면에 추가'하면 앱처럼 쓸 수 있어요\n\n"
                "폰에서 고친 내용은 1분 안에 PC에도 들어와요.\n"
                "예전에 연결한 폰도 이 QR을 한 번 다시 찍어야 데이터가 보여요.\n"
                "※ 아이폰: 공유 → '홈 화면에 추가' 후 아이콘으로 열기")).pack(anchor="w", pady=(4, 0))
            tk.Label(right, font=FONT_S, fg=SUN, bg=PANEL, justify="left", text=(
                "⚠ 이 QR·링크가 있으면 내 회원 정보를 볼 수 있어요. 다른 사람에게 보내지 마세요.\n"
                "   잃어버렸다면 [🔑 열쇠 바꾸기] → 예전 링크는 바로 막혀요.")).pack(anchor="w", pady=(6, 0))
            lf = tk.Frame(web_tab, bg=PANEL)
            lf.pack(fill="x", pady=(10, 0))
            e = tk.Entry(lf, font=FONT_S, fg=MUTED)
            e.insert(0, self.link)
            e.config(state="readonly")
            e.pack(side="left", fill="x", expand=True, ipady=3)
            btn(lf, "📋 링크 복사", lambda: self.copy(self.link, "웹앱 링크")).pack(side="left", padx=(6, 0))
            btn(lf, "🔑 열쇠 바꾸기", self.reset_token).pack(side="left", padx=(6, 0))
            self.web_lbl = tk.Label(web_tab, text="연결된 폰 확인 중…", font=FONT_B, fg=ACCENT_DK, bg=PANEL)
            self.web_lbl.pack(anchor="w", pady=(8, 0))

            # ── ntfy 탭 ──
            self.build_ntfy(nt_tab, PANEL)

            sf = tk.Frame(f, bg=BG)
            sf.pack(fill="x", pady=(10, 0))
            btn(sf, "↻ 연결 상태 새로고침", self.check).pack(side="left")
            self.log_lbl = tk.Label(f, font=FONT_S, fg=MUTED, bg=BG, justify="left", anchor="w")
            self.log_lbl.pack(fill="x", pady=(6, 0))
            self.check()
        else:
            tk.Label(f, text="※ 서버 주소가 없는 테스트 버전이에요. (배포된 exe에서는 텔레그램·웹앱으로 연결)",
                     font=FONT_S, fg=MUTED, bg=BG).pack(anchor="w", pady=(6, 0))
            self.use_ntfy.set(1)
            box = tk.Frame(f, bg=PANEL, padx=16, pady=12)
            box.pack(fill="x", pady=(8, 0))
            self.build_ntfy(box, PANEL)

        self.msg = tk.Label(f, font=FONT_S, fg=MUTED, bg=BG, justify="left")
        self.msg.pack(anchor="w", pady=(8, 0))
        bf = tk.Frame(f, bg=BG)
        bf.pack(anchor="e", pady=(10, 0))
        self.test_btn = btn(bf, "테스트 발송", self.test)
        self.test_btn.pack(side="left", padx=3)
        btn(bf, "닫기", self.close).pack(side="left", padx=3)
        btn(bf, "저장", self.save, primary=True).pack(side="left", padx=3)
        self.protocol("WM_DELETE_WINDOW", self.close)
        bring_front(self)

    def build_ntfy(self, p, bg):
        tk.Label(p, text="ntfy 앱 사용 시: 앱에서 [+] → 아래 토픽 이름으로 구독", font=FONT, bg=bg).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        tk.Label(p, text="토픽 이름", font=FONT_B, bg=bg).grid(row=1, column=0, sticky="w", padx=(0, 8))
        tk.Entry(p, textvariable=self.topic, width=16, font=(F, 13, "bold"), fg=ACCENT_DK,
                 justify="center").grid(row=1, column=1, sticky="w", pady=4, ipady=2)
        btn(p, "📋 복사", lambda: self.copy(self.topic.get().strip(), "토픽 이름")).grid(row=1, column=2, padx=4)
        if not WORKER_URL:
            tk.Label(p, text="서버", font=FONT, bg=bg).grid(row=2, column=0, sticky="w", padx=(0, 8))
            tk.Entry(p, textvariable=self.server, width=30, font=FONT).grid(row=2, column=1, columnspan=2,
                                                                            sticky="w", pady=3)

    def copy(self, text, what):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.msg.config(text=f"✔ {what}을(를) 복사했어요.", fg=OK_C)

    def close(self):
        self.destroy()
        self.app.check_phone_link(reschedule=False)

    # ── 서버에서 연결 상태 받아오기 ──
    def check(self):
        res = {}

        def run():
            try:
                res["r"] = worker_call("/api/phones", {"device": self.app.device_id})
                try:
                    res["l"] = http_json(f"{WORKER_URL.rstrip('/')}/api/list?d={self.app.device_id}").get("log") or []
                except Exception:
                    res["l"] = []
            except Exception as e:
                res["e"] = str(e)

        threading.Thread(target=run, daemon=True).start()

        def poll():
            if not res:
                self.after(200, poll)
                return
            if not self.winfo_exists():
                return
            if "e" in res:
                self.web_lbl.config(text="서버 연결 실패 — 인터넷을 확인해주세요", fg=SUN)
                self.tg_msg.config(text="서버 연결 실패 — 인터넷을 확인해주세요", fg=SUN)
                return
            r = res["r"]
            self.info = r
            n = r.get("phones", 0)
            if not r.get("webpush"):
                self.web_lbl.config(text="⚠ 서버 업데이트가 필요해요 (1_서버배포.bat 실행)", fg=SUN)
            else:
                self.web_lbl.config(text=f"✅ 연결된 폰 {n}대" if n else "아직 연결된 폰이 없어요",
                                    fg=OK_C if n else SUN)
            self.build_tg_tab(r)
            lines = []
            for lg in res.get("l", [])[:4]:
                t = dt.datetime.fromtimestamp(lg["at"])
                ok = 200 <= (lg.get("status") or 0) < 300
                lines.append(f"{t:%m/%d %H:%M}  {'✅' if ok else '⚠'} {lg.get('target', '')} · {lg.get('info', '')}")
            self.log_lbl.config(text=("최근 발송 기록\n" + "\n".join(lines)) if lines else "")
        poll()

    def build_tg_tab(self, r):
        for w in self.tg_tab.winfo_children():
            w.destroy()
        bot = r.get("tg_bot") or ""
        names = r.get("telegram") or []
        if not bot:
            tk.Label(self.tg_tab, font=FONT, bg=PANEL, fg=SUN, justify="left", text=(
                "서버에 텔레그램 봇이 아직 설정되지 않았어요.\n"
                "관리자: 1_서버배포.bat 실행 → 봇 토큰 입력")).pack(anchor="w")
            return
        link = f"https://t.me/{bot}?start={self.app.device_id}"
        row = tk.Frame(self.tg_tab, bg=PANEL)
        row.pack(fill="x")
        cv = draw_qr(row, link)
        if cv:
            cv.pack(side="left", padx=(0, 16))
        right = tk.Frame(row, bg=PANEL)
        right.pack(side="left", anchor="n", fill="x")
        if names:
            tk.Label(right, text=f"✅ 텔레그램 연결됨: {', '.join(names)}", font=FONT_T, fg=OK_C,
                     bg=PANEL).pack(anchor="w")
            tk.Label(right, font=FONT, bg=PANEL, justify="left", text=(
                "예약 시간이 되면 텔레그램 채팅으로 알림이 와요.\n"
                "텔레그램에서 /list 를 보내면 예정된 알림을 볼 수 있어요.\n\n"
                "다른 폰도 연결하려면 QR코드를 한 번 더 찍으면 돼요.")).pack(anchor="w", pady=(6, 10))
            btn(right, "연결 해제", self.tg_unlink).pack(anchor="w")
        else:
            tk.Label(right, text="텔레그램 연결 (1분)", font=FONT_T, fg=ACCENT_DK, bg=PANEL).pack(anchor="w")
            tk.Label(right, font=FONT, bg=PANEL, justify="left", text=(
                "① 폰 카메라로 QR코드를 찍으세요 (텔레그램이 열려요)\n"
                f"② @{bot} 채팅에서 아래 [시작] 버튼을 누르세요\n"
                "③ '✅ 연결됐어요' 메시지가 오면 끝!\n\n"
                "PC에 텔레그램이 깔려 있으면 아래 버튼으로도 돼요.")).pack(anchor="w", pady=(6, 10))
            bb = tk.Frame(right, bg=PANEL)
            bb.pack(anchor="w")
            btn(bb, "텔레그램으로 연결", lambda: __import__("webbrowser").open(link), primary=True).pack(side="left")
            btn(bb, "📋 링크 복사", lambda: self.copy(link, "텔레그램 연결 링크")).pack(side="left", padx=6)
            btn(bb, "연결 확인", self.check).pack(side="left")

    def reset_token(self):
        if not messagebox.askyesno("열쇠 바꾸기", "웹앱 열쇠를 새로 만들까요?\n\n"
                                   "지금 연결된 폰(웹앱)은 데이터를 볼 수 없게 되고,\n"
                                   "새 QR코드를 다시 찍어야 해요. (예약 알림은 계속 와요)", parent=self):
            return
        self.app.web_token = secrets.token_urlsafe(18)
        self.db.set("web_token", self.app.web_token)
        self.app.request_sync(200)
        self.destroy()
        SettingsDialog(self.app)

    def tg_unlink(self):
        if not messagebox.askyesno("텔레그램", "이 PC의 텔레그램 알림 연결을 해제할까요?", parent=self):
            return
        try:
            worker_call("/api/tg/unlink", {"device": self.app.device_id})
        except Exception as e:
            self.msg.config(text=f"해제 실패: {e}", fg=SUN)
            return
        self.check()

    def save(self, quiet=False):
        t = self.topic.get().strip()
        if self.use_ntfy.get() and not TOPIC_RE.match(t):
            messagebox.showwarning("토픽 이름", "토픽 이름은 영문·숫자·-·_ 로 6자 이상이어야 해요.\n(한글·띄어쓰기 불가)",
                                   parent=self)
            return False
        self.db.set("phone_on", str(self.en.get()))
        self.db.set("ch_tg", str(self.ch_tg.get()))
        self.db.set("ch_web", str(self.ch_web.get()))
        self.db.set("ntfy_use", str(self.use_ntfy.get()))
        self.db.set("ntfy_on", str(self.en.get()))
        self.db.set("ntfy_topic", t)
        self.db.set("ntfy_server", self.server.get().strip() or "https://ntfy.sh")
        self.app.request_sync()
        self.app.update_status()
        if not quiet:
            self.msg.config(text="✔ 저장했어요.", fg=OK_C)
        return True

    def test(self):
        if not self.save(quiet=True):
            return
        topic = self.topic.get().strip() if self.use_ntfy.get() else ""
        ch = channels(self.db)          # DB는 메인 스레드에서만 읽기
        self.test_btn.config(state="disabled", text="발송 중…")
        res = {}

        def run():
            try:
                if WORKER_URL:
                    res["r"] = worker_call("/api/test", {"device": self.app.device_id, "topic": topic,
                                                         "channels": ch,
                                                         "title": "업무 다이어리", "message": "테스트 알림입니다 ✅"})
                else:
                    push_sync(self.server.get(), topic, "업무 다이어리", "테스트 알림입니다 ✅")
                    res["r"] = {"ntfy": True}
            except Exception as e:
                res["e"] = str(e)

        threading.Thread(target=run, daemon=True).start()

        def poll():
            if not res:
                self.after(200, poll)
                return
            if not self.winfo_exists():
                return
            self.test_btn.config(state="normal", text="테스트 발송")
            if "e" in res:
                self.msg.config(text=f"발송 실패: {res['e']}", fg=SUN)
                return
            r = res["r"]
            parts = []
            if r.get("telegram"):
                parts.append(f"텔레그램 {r['telegram']}곳")
            if r.get("phones"):
                parts.append(f"웹앱 {r['phones']}대")
            if r.get("ntfy"):
                parts.append("ntfy 앱")
            self.msg.config(text=("✔ 보냈어요 → " + ", ".join(parts) + ". 폰을 확인해보세요.") if parts else
                            "보낼 곳이 없어요. 텔레그램이나 웹앱을 먼저 연결해 주세요.", fg=OK_C if parts else SUN)
            if WORKER_URL:
                self.after(1500, self.check)
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
        self.kw_var = tk.StringVar(value=data["keyword"])
        tk.Label(f, text="검색어", font=FONT_B, bg=BG).grid(row=2, column=0, sticky="w")
        tk.Entry(f, textvariable=self.kw_var, font=(F, 11)).grid(row=2, column=1, sticky="ew", pady=3)
        tk.Label(f, text="내용", font=FONT_B, bg=BG).grid(row=3, column=0, sticky="nw", pady=3)
        mf = tk.Frame(f)
        mf.grid(row=3, column=1, sticky="nsew", pady=3)
        self.memo = tk.Text(mf, wrap="word", font=FONT)
        msb = ttk.Scrollbar(mf, command=self.memo.yview)
        self.memo.config(yscrollcommand=msb.set)
        msb.pack(side="right", fill="y")
        self.memo.pack(side="left", fill="both", expand=True)
        f.rowconfigure(3, weight=1)
        lines = len(data["memo"].splitlines())
        tk.Label(f, text=f"메모 {lines}줄 · {len(data['memo'])}자 전체를 가져왔습니다", font=FONT_S,
                 fg=OK_C, bg=BG).grid(row=4, column=1, sticky="w")
        self.memo.insert("1.0", data["memo"])

        self.mode = tk.StringVar(value="overwrite")
        if self.existing:
            ef = tk.Frame(f, bg=GOLD_LT, padx=8, pady=6)
            ef.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            tk.Label(ef, text=f'이미 등록된 회원입니다: {self.existing["name"]} {self.existing["phone"]}',
                     font=FONT_B, bg=GOLD_LT).pack(anchor="w")
            tk.Radiobutton(ef, text="어깨동무 내용으로 덮어쓰기", variable=self.mode, value="overwrite",
                           bg=GOLD_LT, font=FONT).pack(anchor="w")
            tk.Radiobutton(ef, text="기존 내용 아래에 이어 붙이기", variable=self.mode, value="append",
                           bg=GOLD_LT, font=FONT).pack(anchor="w")

        bf = tk.Frame(f, bg=BG)
        bf.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
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
        kw = self.kw_var.get().strip()
        memo = self.memo.get("1.0", "end-1c").strip()
        if not name and not phone:
            messagebox.showwarning("확인", "이름이나 전화번호가 비어 있습니다.", parent=self)
            return
        if self.existing:
            mid = self.existing["id"]
            if self.mode.get() == "append":
                old = (self.existing["memo"] or "").rstrip()
                memo = f"{old}\n\n── 어깨동무 가져옴 {stamp()[:16]} ──\n{memo}" if old else memo
            self.db.x("UPDATE members SET name=?, phone=?, memo=?, keyword=?, updated=? WHERE id=?",
                      (name or self.existing["name"], phone, memo, kw or self.existing["keyword"] or "",
                       stamp(), mid))
            w = self.app.member_windows.pop(mid, None)   # 열려 있던 창은 새 내용으로 다시 열기
            if w and w.winfo_exists():
                w.destroy()
        else:
            mid = self.db.x("INSERT INTO members(name,phone,memo,keyword,created,updated) VALUES(?,?,?,?,?,?)",
                            (name, phone, memo, kw, stamp(), stamp()))
        self.app.search_var.set("")
        self.app.refresh_members(select=mid)
        self.destroy()
        self.app.open_member(mid)


# ───────────────────────── 메인 화면 ─────────────────────────
# ───────────────────────── 라이선스 ─────────────────────────
LIC_CHECK_MS = 10 * 60 * 1000     # 10분마다 서버에서 키 상태 확인
LIC_GRACE_SEC = 3 * 86400         # 인터넷이 끊겨도 마지막 확인 후 3일까지는 사용 가능


def machine_hwid():
    """이 PC 고유값 (윈도우 설치 고유번호 기반, 원문은 보내지 않고 해시만)"""
    import hashlib
    raw = ""
    if IS_WIN:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                               winreg.KEY_READ | 0x0100)   # 64비트 레지스트리
            raw = winreg.QueryValueEx(k, "MachineGuid")[0]
        except OSError:
            raw = ""
    if not raw:
        import uuid
        raw = f"{uuid.getnode():x}"
    return hashlib.sha256(f"workdiary|{raw}".encode()).hexdigest()[:24]


def pc_label():
    return f'{os.environ.get("COMPUTERNAME", "PC")} ({os.environ.get("USERNAME", "")})'[:80]


def lic_request(path, key, device, user_name=""):
    """서버에 키 확인. 반환: (상태, 응답) 상태 = ok / not_found / revoked / expired / other_pc / net / noserver"""
    try:
        r = worker_call(path, {"key": key, "device": device, "hwid": machine_hwid(), "pc_name": pc_label(),
                               "version": APP_VERSION, "user_name": user_name})
        return ("ok", r) if r.get("ok") else ("net", {"message": "서버 응답 오류"})
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            j = {}
        err = j.get("error", "")
        if e.code == 404 and err in ("", "not found"):
            return "noserver", {}            # 서버에 아직 라이선스 기능이 없음 (1_서버배포.bat 전)
        if err in ("not_found", "revoked", "expired", "other_pc"):
            return err, j
        return "net", {"message": f"서버 오류 ({e.code})"}
    except Exception as e:
        return "net", {"message": f"인터넷 연결을 확인해 주세요 ({e.__class__.__name__})"}


def lic_save(db, r):
    db.set("license_key", r.get("key", db.get("license_key")))
    db.set("lic_name", r.get("name", ""))
    if r.get("user_name"):
        db.set("lic_user", r["user_name"])
    db.set("lic_expires", str(int(r.get("expires") or 0)))
    db.set("lic_capture", "1" if r.get("capture") else "0")
    db.set("lic_ok_at", str(int(time.time())))


def lic_cached_ok(db):
    """인터넷이 안 될 때: 최근 3일 안에 확인됐고 만료 전이면 사용 허용"""
    try:
        ok_at, exp = int(db.get("lic_ok_at", "0") or 0), int(db.get("lic_expires", "0") or 0)
    except ValueError:
        return False
    t = time.time()
    return db.get("license_key") and ok_at and t - ok_at < LIC_GRACE_SEC and (exp == 0 or exp > t)


# 화면 캡처 막기 (윈도우 10 2004 이상: 캡처·녹화·원격화면에서 창이 안 보임 / 그 이전: 검은 화면)
CAPTURE = {"allow": True}


def _set_affinity(w, allow):
    if not IS_WIN:
        return
    try:
        hwnd = int(w.wm_frame(), 16)
        u = ctypes.windll.user32
        if allow:
            u.SetWindowDisplayAffinity(hwnd, 0)
        elif not u.SetWindowDisplayAffinity(hwnd, 0x11):
            u.SetWindowDisplayAffinity(hwnd, 0x01)
    except Exception:
        pass


def _all_toplevels(root):
    out, stack = [root], [root]
    while stack:
        for c in stack.pop().winfo_children():
            if isinstance(c, tk.Toplevel):
                out.append(c)
            stack.append(c)
    return out


def install_capture_guard(root):
    def on_map(e):
        if isinstance(e.widget, (tk.Tk, tk.Toplevel)):
            _set_affinity(e.widget, CAPTURE["allow"])
    root.bind_class("Toplevel", "<Map>", on_map, add="+")
    root.bind_class("Tk", "<Map>", on_map, add="+")


def set_capture_allowed(root, allow):
    if CAPTURE["allow"] == allow:
        return
    CAPTURE["allow"] = allow
    for w in _all_toplevels(root):
        try:
            if w.winfo_ismapped():
                _set_affinity(w, allow)
        except tk.TclError:
            pass


class KeyDialog(tk.Toplevel):
    """라이선스 키 입력 창 (처음 실행 / 정지·만료 시)"""

    def __init__(self, root, db, device, on_ok, message="", checking=False):
        super().__init__(root)
        self.db, self.device, self.on_ok = db, device, on_ok
        self.title(f"{APP_TITLE} - 라이선스")
        self.configure(bg=BG)
        self.resizable(False, False)
        hd = tk.Frame(self, bg=DARK, padx=22, pady=14)
        hd.pack(fill="x")
        tk.Label(hd, text="◆ 업무 다이어리", font=(F, 15, "bold"), fg=GOLD_BR, bg=DARK).pack(anchor="w")
        tk.Label(hd, text="라이선스 확인", font=FONT_S, fg="#B9A57A", bg=DARK).pack(anchor="w")
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")
        f = tk.Frame(self, bg=BG, padx=24, pady=18)
        f.pack(fill="both")
        self.msg = tk.Label(f, text=message, font=FONT_B, fg=SUN, bg=BG, wraplength=380, justify="left")
        self.msg.pack(anchor="w", pady=(0, 8))
        tk.Label(f, text="사용하시는 분 이름", font=FONT_B, bg=BG).pack(anchor="w")
        self.name_var = tk.StringVar(value=db.get("lic_user"))
        self.name_ent = tk.Entry(f, textvariable=self.name_var, font=(F, 13), width=22)
        self.name_ent.pack(fill="x", pady=(6, 12), ipady=4)
        tk.Label(f, text="판매자에게 받은 라이선스 키", font=FONT_B, bg=BG).pack(anchor="w")
        self.var = tk.StringVar(value=db.get("license_key"))
        self.ent = tk.Entry(f, textvariable=self.var, font=("Consolas", 16, "bold"), justify="center", width=22)
        self.ent.pack(fill="x", pady=(8, 4), ipady=6)
        tk.Label(f, text="예) WD-ABCD-EFGH-JKLM   ·   키 1개는 PC 1대에서만 쓸 수 있어요", font=FONT_S, fg=MUTED,
                 bg=BG).pack(anchor="w")
        tk.Label(f, text=f"이 PC: {pc_label()}", font=FONT_S, fg=MUTED, bg=BG).pack(anchor="w", pady=(2, 0))
        bf = tk.Frame(f, bg=BG)
        bf.pack(fill="x", pady=(16, 0))
        self.ok_btn = btn(bf, "확인", self.submit, primary=True)
        self.ok_btn.pack(side="right")
        btn(bf, "종료", self.quit_app).pack(side="right", padx=6)
        self.state_lbl = tk.Label(bf, font=FONT_S, fg=MUTED, bg=BG)
        self.state_lbl.pack(side="left")
        self.ent.bind("<Return>", lambda e: self.submit())
        self.name_ent.bind("<Return>", lambda e: self.ent.focus_set())
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2
        y = (self.winfo_screenheight() - self.winfo_reqheight()) // 3
        self.geometry(f"+{x}+{y}")
        bring_front(self)
        (self.ent if self.name_var.get().strip() else self.name_ent).focus_set()
        if checking:
            self.busy("확인 중…")

    def busy(self, text):
        self.ok_btn.config(state="disabled")
        self.state_lbl.config(text=text, fg=MUTED)

    def quit_app(self):
        try:
            self.master.destroy()
        except tk.TclError:
            pass

    def submit(self):
        key = re.sub(r"\s+", "", self.var.get().strip().upper())
        name = self.name_var.get().strip()
        if not name:
            self.msg.config(text="이름을 입력해 주세요.")
            self.name_ent.focus_set()
            return
        if not key:
            self.msg.config(text="라이선스 키를 입력해 주세요.")
            self.ent.focus_set()
            return
        self.db.set("lic_user", name)
        self.busy("서버에서 확인 중…")
        res = {}
        threading.Thread(target=lambda: res.setdefault("r", lic_request("/api/lic/activate", key, self.device, name)),
                         daemon=True).start()

        def poll():
            if "r" not in res:
                self.after(150, poll)
                return
            st, r = res["r"]
            self.ok_btn.config(state="normal")
            self.state_lbl.config(text="")
            if st == "ok":
                lic_save(self.db, r)
                self.destroy()
                self.on_ok(r)
            elif st == "noserver":
                self.db.set("license_key", key)
                self.destroy()
                self.on_ok({})
            else:
                self.msg.config(text=r.get("message") or "확인하지 못했어요.")
        poll()


def lic_start(root, db, device, on_ok):
    """시작할 때 라이선스 확인 → 통과하면 on_ok(정보)"""
    key = db.get("license_key")
    res = {}

    def run():
        k = key
        if not k and ADMIN_PASS:     # 관리자 본인 PC: 본인 키 자동 발급
            try:
                k = http_json(WORKER_URL.rstrip("/") + "/api/admin/selfkey", {}, {"X-Admin": ADMIN_PASS}).get("key", "")
            except Exception:
                k = ""
        if k:
            res["r"] = lic_request("/api/lic/activate", k, device)
        else:                        # 키 없음: 서버에 라이선스 기능이 있는지만 확인 (없으면 그냥 시작)
            st, _ = lic_request("/api/lic/check", "WD-0000-0000-0000", device)
            res["r"] = ("noserver", {}) if st == "noserver" else ("none", {})

    threading.Thread(target=run, daemon=True).start()
    box = {}

    def poll(n=0):
        if "r" not in res:
            if n == 3 and "dlg" not in box:      # 0.5초 넘게 걸리면 '확인 중' 창 표시
                box["dlg"] = KeyDialog(root, db, device, on_ok, checking=True)
            root.after(150, lambda: poll(n + 1))
            return
        st, r = res["r"]
        dlg = box.get("dlg")
        if st == "ok":
            lic_save(db, r)
            if dlg and dlg.winfo_exists():
                dlg.destroy()
            on_ok(r)
            return
        if st == "noserver" or (st == "net" and lic_cached_ok(db)):
            if dlg and dlg.winfo_exists():
                dlg.destroy()
            on_ok({})
            return
        msg = "" if st == "none" else r.get("message", "")
        if dlg and dlg.winfo_exists():
            dlg.msg.config(text=msg)
            dlg.ok_btn.config(state="normal")
            dlg.state_lbl.config(text="")
        else:
            KeyDialog(root, db, device, on_ok, message=msg)
    poll()


class App:
    def __init__(self, root, db=None):
        self.root, self.db = root, (db or DB(DB_PATH))
        self.note_windows, self.member_windows = {}, {}
        today = dt.date.today()
        self.year, self.month, self.sel_date = today.year, today.month, today
        self._diary_date, self._diary_job, self._diary_dirty, self._loading = None, None, False, False

        self._sync_job, self._sync_state, self._sync_at = None, "", None
        self._sync_busy, self._sync_again, self._legacy_until, self._rederive = False, False, 0, False
        self._update_later = set()
        self.device_id = self.db.get("device_id")
        if not self.device_id:
            self.device_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
            self.db.set("device_id", self.device_id)
        self.web_token = self.db.get("web_token")
        if not self.web_token:                    # 웹앱에서 내 데이터를 보고 고칠 때 쓰는 비밀 열쇠
            self.web_token = secrets.token_urlsafe(18)
            self.db.set("web_token", self.web_token)
        if WORKER_URL:
            if self.db.get("sync_v2_init") != "1":   # 처음 한 번: 지금까지의 모든 데이터를 서버로
                with self.db.conn:
                    c = self.db.conn
                    c.execute("DELETE FROM sync_queue")
                    for kind, t in (("member", "members"), ("schedule", "schedules"), ("note", "notes")):
                        c.execute(f"INSERT INTO sync_queue(kind, lid) SELECT '{kind}', id FROM {t} ORDER BY id")
                    c.execute("INSERT INTO sync_queue(kind, uid) SELECT 'diary', date FROM diary WHERE TRIM(content)<>''")
                    c.execute("INSERT OR REPLACE INTO settings VALUES('sync_v2_init','1')")
                    c.execute("INSERT OR REPLACE INTO settings VALUES('sync_rev','0')")
                self._rederive = True
        else:
            self.db.x("DELETE FROM sync_queue")
        root.title(f"{APP_TITLE}  v{APP_VERSION}")
        root.geometry("1600x900")
        root.minsize(1300, 700)
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
        self.request_sync(800)
        root.after(SYNC_EVERY_MS, self.sync_tick)
        root.after(300, self.restore_split)
        self.phones, self._phone_warned = None, False
        root.after(5000, self.check_phone_link)
        root.after(3000, lambda: self.check_update(startup=True))   # 켤 때: 새 버전 있으면 바로 설치
        self._update_timer()
        self._locked = False
        install_capture_guard(root)
        if WORKER_URL:
            set_capture_allowed(root, self.db.get("lic_capture", "1") == "1")
            root.after(LIC_CHECK_MS, self.lic_tick)

    # 가운데 칸막이 위치: 기본 6:4, 사용자가 옮기면 비율로 기억
    def restore_split(self):
        try:
            ratio = float(self.db.get("split_ratio", "0.6"))
        except ValueError:
            ratio = 0.6
        ratio = min(0.8, max(0.4, ratio))
        W = self.body.winfo_width()
        if W > 100:
            self.body.sashpos(0, int(W * ratio))
        self._split_w = W
        self.root.bind("<Configure>", self.on_root_resize, add="+")
        self.body.bind("<ButtonRelease-1>", lambda e: self.root.after(50, self.save_split), add="+")

    def save_split(self):
        W = self.body.winfo_width()
        if W > 100:
            self.db.set("split_ratio", f"{self.body.sashpos(0) / W:.3f}")

    def on_root_resize(self, e):
        if e.widget is not self.root:
            return
        W = self.body.winfo_width()
        if W > 100 and W != getattr(self, "_split_w", W):
            self._split_w = W
            try:
                ratio = min(0.8, max(0.4, float(self.db.get("split_ratio", "0.6"))))
            except ValueError:
                ratio = 0.6
            self.body.sashpos(0, int(W * ratio))

    UPDATE_EVERY_MIN = 30

    # ---------- 폰 연결 감시 (30분마다) ----------
    def check_phone_link(self, reschedule=True):
        if reschedule:
            self.root.after(30 * 60 * 1000, self.check_phone_link)
        if not WORKER_URL or not phone_cfg(self.db)[0]:
            self.phones = None
            return
        res = {}
        ch = channels(self.db)          # DB는 메인 스레드에서만 읽기

        def run():
            try:
                r = worker_call("/api/phones", {"device": self.device_id})
                res["n"] = (r.get("phones", 0) if ch["web"] else 0) + (len(r.get("telegram") or []) if ch["tg"] else 0)
            except Exception:
                res["n"] = None

        threading.Thread(target=run, daemon=True).start()

        def poll():
            if not res:
                self.root.after(300, poll)
                return
            prev, self.phones = self.phones, res["n"]
            self.update_status()
            if self.phones == 0 and not self._phone_warned:
                self._phone_warned = True
                toast(self.root, "⚠ 폰(텔레그램·웹앱)이 연결돼 있지 않아요 — 예약 알림이 폰으로 가지 않아요.\n"
                                 "[📱 폰 연결 · 웹앱]에서 다시 연결해 주세요. (PC 팝업 알림은 정상)", 12000)
            elif self.phones and self.phones > 0:
                self._phone_warned = False
        poll()

    def _update_timer(self):   # 켜둔 채로 지내도 30분마다 업데이트 확인
        self.root.after(self.UPDATE_EVERY_MIN * 60 * 1000, lambda: (self.check_update(), self._update_timer()))

    # ---------- 화면 구성 ----------
    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("Treeview", font=FONT, rowheight=28, background=PANEL, fieldbackground=PANEL,
                    foreground=TEXT, bordercolor=LINE, borderwidth=0)
        s.configure("Treeview.Heading", font=FONT_B, background=HEAD, foreground=TEXT2, relief="flat",
                    bordercolor=LINE, padding=(4, 5))
        s.map("Treeview.Heading", background=[("active", SEC_DK)])
        s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        s.configure("TPanedwindow", background=BG)
        s.configure("Sash", sashthickness=6, gripcount=0, background=BG)
        s.configure("TCombobox", padding=4, fieldbackground=PANEL, background=SEC, foreground=TEXT,
                    arrowcolor=ACCENT_DK, bordercolor=LINE, lightcolor=PANEL, darkcolor=LINE)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL)], selectbackground=[("readonly", PANEL)],
              selectforeground=[("readonly", TEXT)])
        s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
        s.configure("TNotebook.Tab", font=FONT_B, padding=(14, 6), background=SEC, foreground=TEXT2, borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT_DK)])
        for o in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            s.configure(o, background=SEC, troughcolor=BG, bordercolor=BG, arrowcolor=ACCENT_DK,
                        lightcolor=SEC, darkcolor=SEC, gripcount=0)
            s.map(o, background=[("active", SEC_DK)])
        # 기본 입력칸·체크박스 모양 (이후 만드는 모든 창에 적용)
        r = self.root
        for cls in ("Entry", "Text", "Spinbox"):
            r.option_add(f"*{cls}.background", PANEL)
            r.option_add(f"*{cls}.foreground", TEXT)
            r.option_add(f"*{cls}.relief", "flat")
            r.option_add(f"*{cls}.borderWidth", 0)
            r.option_add(f"*{cls}.highlightThickness", 1)
            r.option_add(f"*{cls}.highlightBackground", LINE)
            r.option_add(f"*{cls}.highlightColor", ACCENT)
            r.option_add(f"*{cls}.insertBackground", TEXT)
            r.option_add(f"*{cls}.selectBackground", GOLD_LT)
            r.option_add(f"*{cls}.selectForeground", TEXT)
        for cls in ("Checkbutton", "Radiobutton"):
            r.option_add(f"*{cls}.foreground", TEXT)
            r.option_add(f"*{cls}.activeForeground", ACCENT_DK)
            r.option_add(f"*{cls}.selectColor", PANEL)
            r.option_add(f"*{cls}.highlightThickness", 0)
        r.option_add("*Label.foreground", TEXT)
        r.option_add("*LabelFrame.foreground", ACCENT_DK)
        r.option_add("*LabelFrame.relief", "groove")
        r.option_add("*TCombobox*Listbox.background", PANEL)
        r.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        r.option_add("*TCombobox*Listbox.font", FONT)

    def _build_toolbar(self):
        tb = tk.Frame(self.root, bg=DARK, padx=16, pady=10)
        tb.pack(fill="x")
        tk.Frame(self.root, bg=ACCENT, height=2).pack(fill="x")
        tk.Label(tb, text="◆", font=(F, 14), fg=GOLD_BR, bg=DARK).pack(side="left")
        tk.Label(tb, text=f" {APP_TITLE}", font=(F, 16, "bold"), fg=GOLD_BR, bg=DARK).pack(side="left")
        tk.Label(tb, text=f"   v{APP_VERSION}", font=FONT_S, fg="#8C7A55", bg=DARK).pack(side="left", pady=(5, 0))

        btn(tb, "⟳ 업데이트", lambda: self.check_update(manual=True), dark=True).pack(side="right", padx=(6, 0))
        btn(tb, "📱 폰 연결 · 웹앱", lambda: SettingsDialog(self), dark=True).pack(side="right")
        btn(tb, f"📥 어깨동무 회원 가져오기  {HOTKEY_TEXT}", self.import_ekdm, dark=True).pack(side="right", padx=6)
        btn(tb, "📅 어깨동무 → 오늘 일정  F9", lambda: self.quick_schedule(None), dark=True).pack(side="right")
        self.clock = tk.Label(tb, font=(F, 11, "bold"), fg="#E9D9AE", bg=DARK)
        self.clock.pack(side="right", padx=18)

    def _build_status(self):
        sb = tk.Frame(self.root, bg=DARK, padx=14, pady=5)
        sb.pack(fill="x", side="bottom")
        self.status = tk.Label(sb, font=FONT_S, bg=DARK, fg="#D9C9A3", anchor="w")
        self.status.pack(fill="x")

    def _build_body(self):
        body = ttk.PanedWindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=6)
        self.body = body
        left, right = tk.Frame(body, bg=BG), tk.Frame(body, bg=BG)
        body.add(left, weight=3)
        body.add(right, weight=2)

        memo = tk.Frame(left, bg=BG, width=300)
        memo.pack(side="left", fill="y", padx=(0, 8))
        memo.pack_propagate(False)
        self._build_memo_board(memo)

        lp = ttk.PanedWindow(left, orient="vertical")
        lp.pack(side="left", fill="both", expand=True)
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

    NOTE_ROWS, NOTE_COLS = 5, 2

    def _build_memo_board(self, p):
        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill="x", pady=(0, 4))
        tk.Label(hdr, text="📝 메모", font=FONT_T, fg=ACCENT_DK, bg=BG).pack(side="left")
        btn(hdr, "+ 새 메모", self.new_note, primary=True).pack(side="right")
        grid = tk.Frame(p, bg=BG)
        grid.pack(fill="both", expand=True)
        for c in range(self.NOTE_COLS):
            grid.columnconfigure(c, weight=1, uniform="nc")
        for r in range(self.NOTE_ROWS):
            grid.rowconfigure(r, weight=1, uniform="nr")
        self.note_cards = []
        for i in range(self.NOTE_ROWS * self.NOTE_COLS):
            f = tk.Frame(grid, bg=NOTE_BG, highlightthickness=1, highlightbackground="#E6CF8E", cursor="hand2")
            f.grid(row=i // self.NOTE_COLS, column=i % self.NOTE_COLS, sticky="nsew", padx=2, pady=2)
            f.pack_propagate(False)
            t = tk.Label(f, font=FONT_B, bg=NOTE_BG, anchor="w")
            t.pack(fill="x", padx=6, pady=(4, 0))
            b = tk.Label(f, font=FONT_S, bg=NOTE_BG, fg="#7A6A48", anchor="nw", justify="left", wraplength=125)
            b.pack(fill="both", expand=True, padx=6, pady=(0, 4))
            for w in (f, t, b):
                w.bind("<Button-1>", lambda e, i=i: self.on_note_card(i))
            self.note_cards.append((f, t, b))
        self.note_ids = [None] * len(self.note_cards)
        self.more_btn = tk.Button(p, font=FONT_B, relief="flat", bg=BG, fg=ACCENT, cursor="hand2",
                                  activebackground=BG, command=lambda: NoteListDialog(self))
        self.more_btn.pack(fill="x", pady=(4, 0))

    def on_note_card(self, i):
        nid = self.note_ids[i]
        if nid:
            self.open_note(nid)
        else:
            self.new_note()

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
            fg = SUN if c == 0 else (SAT if c == 6 else TEXT2)
            tk.Label(grid, text=WEEK[c], font=FONT_B, bg=HEAD, fg=fg, pady=4).grid(row=0, column=c, sticky="nsew", padx=1, pady=1)
        for r in range(1, 7):
            grid.rowconfigure(r, weight=1, uniform="r")
        self.cells, self.cell_dates = [], [None] * 42
        for i in range(42):
            f = tk.Frame(grid, bg=PANEL, cursor="hand2")
            f.grid(row=1 + i // 7, column=i % 7, sticky="nsew", padx=1, pady=1)
            num = tk.Label(f, anchor="w", bg=PANEL, font=FONT_B)
            num.pack(fill="x", padx=4, pady=(2, 0))
            info = tk.Label(f, anchor="nw", justify="left", bg=PANEL, font=FONT_S, fg=TEXT2)
            info.pack(fill="both", expand=True, padx=4)
            for w in (f, num, info):
                w.bind("<Button-1>", lambda e, i=i: self.on_cell(i))
                w.bind("<Double-Button-1>", lambda e, i=i: self.on_cell(i, add=True))
                w.bind("<MouseWheel>", self.on_wheel)
            self.cells.append((f, num, info))
        tk.Label(p, text="날짜 클릭: 그날 일정 보기 · 더블클릭: 일정 추가 · 마우스 휠: 월 이동",
                 font=FONT_S, fg=MUTED, bg=BG).pack(anchor="w", pady=(3, 0))

    def _build_day(self, p):
        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill="x", pady=(8, 4))
        self.day_lbl = tk.Label(hdr, font=FONT_T, fg=ACCENT_DK, bg=BG)
        self.day_lbl.pack(side="left", anchor="n")
        fb = FlowBar(hdr, bg=BG)
        fb.pack(side="left", fill="x", expand=True, padx=(10, 0))
        fb.add(btn(fb, "+ 일정 추가", self.day_add, primary=True))
        fb.add(btn(fb, "수정", self.day_edit))
        fb.add(btn(fb, "완료/해제", self.day_toggle))
        fb.add(btn(fb, "삭제", self.day_delete))

        mid = tk.Frame(p, bg=BG)
        mid.pack(fill="both", expand=True)
        mid.columnconfigure(0, weight=3, uniform="day")
        mid.columnconfigure(1, weight=2, uniform="day")
        mid.rowconfigure(1, weight=1)
        cols = ("time", "title", "state")
        self.day_tree = ttk.Treeview(mid, columns=cols, show="headings", height=5)
        for c, t, w in (("time", "시간", 60), ("title", "제목", 300), ("state", "알림", 130)):
            self.day_tree.heading(c, text=t)
            self.day_tree.column(c, width=w, anchor="w" if c == "title" else "center", stretch=False)
        fit_columns(self.day_tree, {"time": (1, 46), "title": (3.6, 70), "state": (1.8, 86)},
                    hide_order=("state",))
        self.day_tree.tag_configure("done", foreground="#B5AA95")
        self.day_tree.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.day_tree.bind("<Double-1>", lambda e: self.day_edit())
        self.day_menu = self.make_menu([("✎  수정", self.day_edit), ("✓  완료 / 해제", self.day_toggle), None,
                                        ("🗑  삭제", self.day_delete)])
        self.day_tree.bind("<Button-3>", lambda e: self.popup_menu(e, self.day_tree, self.day_menu))

        tk.Label(mid, text="✎ 하루 메모 (자동 저장)", font=FONT_B, bg=BG).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.diary_txt = tk.Text(mid, wrap="word", font=FONT, undo=True, height=6)
        self.diary_txt.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        self.diary_txt.bind("<<Modified>>", self.on_diary_mod)

    def _build_members(self, p):
        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill="x", pady=(0, 4))
        tk.Label(hdr, text="👥 집중 관리 회원", font=FONT_T, fg=ACCENT_DK, bg=BG).pack(side="left", anchor="n")
        fb = FlowBar(hdr, bg=BG)
        fb.pack(side="left", fill="x", expand=True, padx=(10, 0))
        fb.add(btn(fb, "삭제", self.member_delete))
        for text, where, tip in (("⏫", "top", "맨 위로  (Ctrl+Home)"), ("▲", "up", "위로  (Ctrl+↑)"),
                                 ("▼", "down", "아래로  (Ctrl+↓)"), ("⏬", "bottom", "맨 아래로  (Ctrl+End)")):
            tooltip(fb.add(btn(fb, text, lambda w=where: self.member_move(w), padx=9)), tip)
        fb.add(btn(fb, "+ 회원 추가", lambda: self.open_member(None), primary=True))

        sr = tk.Frame(p, bg=BG)
        sr.pack(fill="x", pady=(0, 4))
        tk.Label(sr, text="🔍", bg=BG).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh_members())
        self.search_entry = tk.Entry(sr, textvariable=self.search_var, font=FONT)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.count_lbl = tk.Label(sr, font=FONT_S, fg=MUTED, bg=BG)
        self.count_lbl.pack(side="left")

        tf = tk.Frame(p)
        tf.pack(fill="both", expand=True)
        cols = ("name", "phone", "kw", "next", "last", "updated")
        self.mem_tree = ttk.Treeview(tf, columns=cols, show="headings")
        for c, t, w in (("name", "이름", 80), ("phone", "전화번호", 110), ("kw", "검색어", 110),
                        ("next", "다음 예약", 90), ("last", "최근 내용", 110), ("updated", "수정일", 80)):
            self.mem_tree.heading(c, text=t)
            self.mem_tree.column(c, width=w, anchor="w" if c in ("last", "kw") else "center", stretch=False)
        fit_columns(self.mem_tree, {"name": (1, 55), "phone": (1.45, 100), "kw": (1.6, 60),
                                    "next": (1.15, 75), "last": (2, 60), "updated": (1.05, 80)},
                    hide_order=("updated", "last", "next", "kw"))
        sb = ttk.Scrollbar(tf, command=self.mem_tree.yview)
        self.mem_tree.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.mem_tree.pack(side="left", fill="both", expand=True)
        self.mem_tree.tag_configure("odd", background="#FAF5EA")
        self.mem_tree.bind("<<TreeviewSelect>>", lambda e: self.show_summary())
        self.mem_tree.bind("<Double-1>", self.on_member_double)
        self.mem_tree.bind("<Return>", lambda e: self.open_selected_member())
        self.mem_menu = self.make_menu([("📞  전화 예약", self.member_call_res), ("📂  열기", self.open_selected_member),
                                        None,
                                        ("⏫  맨 위로   (Ctrl+Home)", lambda: self.member_move("top")),
                                        ("🔼  위로       (Ctrl+↑)", lambda: self.member_move("up")),
                                        ("🔽  아래로    (Ctrl+↓)", lambda: self.member_move("down")),
                                        ("⏬  맨 아래로 (Ctrl+End)", lambda: self.member_move("bottom")),
                                        None, ("🗑  삭제", self.member_delete)])
        cm = tk.Menu(self.mem_menu, tearoff=0, font=(F, 10), bg=PANEL, fg=TEXT, activebackground=ACCENT,
                     activeforeground="white")
        for name, hexc in MEMBER_COLORS:
            if hexc:
                cm.add_command(label=f"●  {name}", foreground=hexc, activeforeground="white",
                               command=lambda h=hexc: self.member_color(h))
            else:
                cm.add_separator()
                cm.add_command(label="기본색으로", command=lambda: self.member_color(""))
        self.mem_menu.insert_cascade(3, label="🎨  이름 색", menu=cm)
        self.mem_menu.insert_separator(4)
        self.mem_tree.bind("<Button-3>", lambda e: self.popup_menu(e, self.mem_tree, self.mem_menu))
        for key, where in (("<Control-Up>", "up"), ("<Control-Down>", "down"),
                           ("<Control-Home>", "top"), ("<Control-End>", "bottom")):
            self.mem_tree.bind(key, lambda e, w=where: (self.member_move(w), "break")[1])

    def _build_summary(self, p):
        tk.Label(p, text="요약  (더블클릭하면 상세 관리 창)", font=FONT_B, bg=BG).pack(anchor="w", pady=(8, 2))
        tf = tk.Frame(p)
        tf.pack(fill="both", expand=True)
        self.summary = tk.Text(tf, wrap="word", font=FONT, padx=12, pady=10, bg=PANEL)
        sb = ttk.Scrollbar(tf, command=self.summary.yview)
        self.summary.config(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.summary.pack(side="left", fill="both", expand=True)
        self.summary.tag_configure("h", font=(F, 13, "bold"))
        self.summary.tag_configure("g", foreground=MUTED, font=FONT_S)
        self.summary.tag_configure("sec", foreground=ACCENT, font=FONT_B)

    # ---------- 새로고침 ----------
    def refresh_all(self):
        self.refresh_calendar()
        self.refresh_day()
        self.refresh_members()
        self.update_status()
        self.request_sync()

    # ---------- 서버(클라우드플레어) 예약 동기화 ----------
    def request_sync(self, delay=2000):
        """내용이 바뀌면 2초 뒤 서버와 동기화"""
        if not WORKER_URL or not hasattr(self, "_sync_job"):
            return
        if self._sync_job:
            self.root.after_cancel(self._sync_job)
        self._sync_job = self.root.after(delay, self.do_sync)

    def do_sync(self):
        """웹앱 동기화: PC에서 바뀐 것 올리기 + 웹앱에서 바뀐 것 받아오기 (폰 알림도 서버가 일정에서 계산)"""
        self._sync_job = None
        if not WORKER_URL or getattr(self, "_locked", False):
            return
        if self._sync_busy:
            self._sync_again = True
            return
        if time.time() < self._legacy_until:      # 서버가 아직 예전 버전 → 알림만 예전 방식으로
            self.do_sync_legacy()
            return
        on, _, topic = phone_cfg(self.db)
        changes, maxid = sync_collect(self.db)
        payload = {"device": self.device_id, "token": self.web_token, "phone": on, "topic": topic or "",
                   "channels": channels(self.db), "since": int(self.db.get("sync_rev", "0") or 0),
                   "changes": changes, "rederive": self._rederive}
        self._sync_busy = True
        res = {}

        def run():
            try:
                res["r"] = worker_call("/api/sync2", payload)
            except urllib.error.HTTPError as e:
                res["e"], res["code"] = e, e.code
            except Exception as e:
                res["e"] = e

        threading.Thread(target=run, daemon=True).start()

        def poll():
            if not res:
                self.root.after(150, poll)
                return
            self._sync_busy = False
            again = False
            if "e" in res:
                if res.get("code") == 404:
                    self._legacy_until = time.time() + 600
                    self.do_sync_legacy()
                elif res.get("code") == 403:          # 라이선스 문제 → 바로 확인
                    self._sync_state = "라이선스 확인 필요"
                    self.lic_check_now()
                else:
                    self._sync_state = f"서버 동기화 실패 ({res['e'].__class__.__name__}) — 잠시 뒤 다시 시도"
            else:
                r = res["r"]
                self._rederive = False
                self.db.x("DELETE FROM sync_queue WHERE id <= ?", (maxid,))
                pending = {sync_queue_key(self.db, e) for e in self.db.q("SELECT * FROM sync_queue")}
                touched = sync_apply(self.db, r.get("changes") or [], pending)
                self.db.set("sync_rev", str(int(r.get("rev") or 0)))
                self._sync_state, self._sync_at = "ok", now()
                if touched:
                    self.after_remote(touched)
                again = bool(r.get("more")) or bool(self.db.one("SELECT 1 FROM sync_queue LIMIT 1"))
            if again or self._sync_again:
                self._sync_again = False
                self.request_sync(300 if again else 2000)
            self.update_status()
        poll()

    def sync_tick(self):
        self.root.after(SYNC_EVERY_MS, self.sync_tick)
        if not self._sync_job:
            self.do_sync()

    def after_remote(self, touched):
        """웹앱에서 바뀐 내용을 화면·열린 창에 반영"""
        kinds = {k for k, _ in touched}
        if ("diary", self._diary_date) in touched and not self._diary_dirty:
            self._diary_date = None               # 지금 보고 있는 날의 하루 메모 다시 읽기
        self.refresh_calendar()
        self.refresh_day()
        if kinds & {"member", "schedule"}:
            self.refresh_members()
        if "note" in kinds:
            self.refresh_notes()
        self.update_status()
        for mid, w in list(self.member_windows.items()):
            if not w.winfo_exists():
                continue
            r = self.db.one("SELECT uid FROM members WHERE id=?", (mid,))
            if not r:                              # 웹앱에서 지운 회원
                if w._auto_job:
                    w.after_cancel(w._auto_job)
                self.member_windows.pop(mid, None)
                w.destroy()
            elif ("member", r["uid"]) in touched and w.values() == w.orig and not w._auto_job:
                w.load()
            elif "schedule" in kinds:
                w.load_res()
        for nid, w in list(self.note_windows.items()):
            if not w.winfo_exists():
                continue
            r = self.db.one("SELECT * FROM notes WHERE id=?", (nid,))
            if not r:
                if w._job:
                    w.after_cancel(w._job)
                self.note_windows.pop(nid, None)
                w.destroy()
            elif ("note", r["uid"]) in touched:
                w.apply_remote(r)

    # ---------- 라이선스 (10분마다 확인, 정지·만료면 잠금) ----------
    def lic_tick(self):
        self.root.after(LIC_CHECK_MS, self.lic_tick)
        self.lic_check_now()

    def lic_check_now(self):
        if self._locked or getattr(self, "_lic_busy", False):
            return
        key = self.db.get("license_key")
        if not key:
            if self.db.get("lic_ok_at"):
                self.lic_lock("라이선스 키를 입력해 주세요.")
            return
        self._lic_busy = True
        res = {}
        threading.Thread(target=lambda: res.setdefault("r", lic_request("/api/lic/check", key, self.device_id)),
                         daemon=True).start()

        def poll():
            if "r" not in res:
                self.root.after(300, poll)
                return
            self._lic_busy = False
            st, r = res["r"]
            if st == "ok":
                lic_save(self.db, r)
                set_capture_allowed(self.root, bool(r.get("capture")))
            elif st == "noserver":
                pass
            elif st == "net":
                if not lic_cached_ok(self.db):
                    self.lic_lock("인터넷에 연결되지 않아 라이선스를 확인하지 못했어요.\n인터넷 연결 후 [확인]을 눌러 주세요.")
            else:
                self.lic_lock(r.get("message") or "라이선스를 사용할 수 없어요.")
        poll()

    def lic_lock(self, message):
        """라이선스 정지·만료: 내용 저장 → 창 모두 닫고 키 입력 창만"""
        if self._locked:
            return
        self._locked = True
        try:
            self.flush_diary()
            for w in list(self.member_windows.values()):
                if w.winfo_exists():
                    w.save(quiet=True)
            for w in list(self.note_windows.values()):
                if w.winfo_exists():
                    w.close()
        except Exception:
            pass
        self.member_windows.clear()
        self.note_windows.clear()
        for w in self.root.winfo_children():
            if isinstance(w, tk.Toplevel):
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        self.root.withdraw()

        def unlocked(r):
            self._locked = False
            set_capture_allowed(self.root, bool(r.get("capture", True)))
            self.root.deiconify()
            bring_front(self.root)
            self.refresh_all()
            self.refresh_notes()
        KeyDialog(self.root, self.db, self.device_id, unlocked, message=message)

    def do_sync_legacy(self):
        on, _, topic = phone_cfg(self.db)
        alarms = []
        if on:
            nowk = now().strftime("%Y-%m-%d %H:%M")
            for r in self.db.q("SELECT a.id AS aid, a.fire_at, a.offset_min, s.*, m.name AS mname, m.phone AS mphone "
                               "FROM alarms a JOIN schedules s ON s.id=a.schedule_id "
                               "LEFT JOIN members m ON s.member_id=m.id "
                               "WHERE s.done=0 AND a.notified=0 AND a.fire_at > ?", (nowk,)):
                msg = f'일정 {r["date"]} ({wd_name(parse_dt(r["date"], r["time"]))}) {r["time"]}'
                if r["offset_min"]:
                    msg += f'  ·  {offset_label(r["offset_min"])} 알림'
                if r["mname"] or r["mphone"]:
                    msg += f'\n{r["mname"] or ""}  {r["mphone"] or ""}'
                if (r["content"] or "").strip():
                    msg += f'\n{r["content"].strip()}'
                fire = dt.datetime.strptime(r["fire_at"], "%Y-%m-%d %H:%M")
                alarms.append({"sid": r["aid"], "fire_at": int(fire.timestamp()),
                               "title": f'⏰ {r["title"]}', "message": msg})
        payload = {"device": self.device_id, "topic": topic or "", "alarms": alarms, "channels": channels(self.db)}

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
    def check_update(self, manual=False, startup=False):
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
            url = asset["browser_download_url"]
            if startup:          # 켤 때는 묻지 않고 바로 업데이트 (모든 내용은 자동 저장돼 있음)
                self.install_update(url)
                return
            if not manual and latest in self._update_later:
                return           # '나중에' 누른 버전은 이번 실행 중엔 다시 안 물음
            self.update_prompt(latest, notes, url)

        poll()

    def update_prompt(self, latest, notes, url):
        """새 버전 안내 (다른 창을 막지 않는 작은 창)"""
        old = getattr(self, "_upd_win", None)
        if old is not None and old.winfo_exists():
            bring_front(old)
            return
        w = tk.Toplevel(self.root)
        self._upd_win = w
        w.title("업데이트")
        w.configure(bg=DARK, padx=22, pady=18, highlightthickness=2, highlightbackground=ACCENT)
        w.resizable(False, False)
        tk.Label(w, text="◆  새 버전이 나왔어요  ◆", font=(F, 12, "bold"), fg=GOLD_BR, bg=DARK).pack()
        tk.Label(w, text=f"v{APP_VERSION}  →  {latest}", font=(F, 14, "bold"), fg="#F5EBD3", bg=DARK).pack(pady=(6, 4))
        if notes:
            tk.Label(w, text=notes[:300], font=FONT_S, fg="#D9CCAF", bg=DARK, justify="left",
                     wraplength=360).pack(pady=(0, 6))
        tk.Label(w, text="업데이트하면 자동으로 다시 켜져요. 입력한 내용은 모두 저장돼 있어요.",
                 font=FONT_S, fg="#9C8B66", bg=DARK).pack(pady=(0, 10))
        bf = tk.Frame(w, bg=DARK)
        bf.pack()

        def later():
            self._update_later.add(latest)
            w.destroy()
        btn(bf, "지금 업데이트", lambda: (w.destroy(), self.install_update(url)), primary=True).pack(side="left", padx=3)
        btn(bf, "나중에", later, dark=True).pack(side="left", padx=3)
        w.protocol("WM_DELETE_WINDOW", later)
        w.update_idletasks()
        x = w.winfo_screenwidth() - w.winfo_reqwidth() - 30
        y = w.winfo_screenheight() - w.winfo_reqheight() - 90
        w.geometry(f"+{x}+{y}")
        bring_front(w)

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
            b.config(bg=ACCENT if on else SEC, fg="white" if on else TEXT2,
                     activebackground=ACCENT_DK if on else SEC_DK)
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
            bg = PANEL if inm else "#F3EEE3"
            if d == today:
                bg = "#FBF0D0"
            if d == self.sel_date:
                bg = "#EFD9A0"
            col = i % 7
            fg = SUN if col == 0 else (SAT if col == 6 else TEXT)
            if not inm:
                fg = "#C9BFAE"
            mark = " ✎" if d.isoformat() in diary else ""
            num.config(text=f"{d.day}{mark}" + ("  오늘" if d == today else ""), bg=bg, fg=fg)
            items = by.get(d.isoformat(), [])
            lines = [("✓" if r["done"] else "• ") + short(f'{r["time"]} {r["title"]}', 14) for r in items[:3]]
            if len(items) > 3:
                lines.append(f"  +{len(items) - 3}건 더")
            info.config(text="\n".join(lines), bg=bg, fg="#B5AA95" if not inm else "#6B5420")
            f.config(bg=bg)

    def refresh_day(self):
        d = self.sel_date
        ds = d.isoformat()
        self.day_lbl.config(text=f"📅 {d.month}월 {d.day}일 ({wd_name(d)}) 일정")
        self.day_tree.delete(*self.day_tree.get_children())
        for r in self.db.q("SELECT s.*, m.name AS mname FROM schedules s LEFT JOIN members m ON s.member_id=m.id "
                           "WHERE s.date=? ORDER BY s.time", (ds,)):
            self.day_tree.insert("", "end", iid=str(r["id"]),
                                 values=(r["time"], r["title"], state_text(r, self.db)),
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
            sql += " WHERE name LIKE ? OR phone LIKE ? OR memo LIKE ? OR keyword LIKE ?"
            args = (f"%{kw}%",) * 4
        rows = self.db.q(sql + " ORDER BY sort_order, id DESC", args)
        nowk = now().strftime("%Y-%m-%d %H:%M")
        nxt = {r["member_id"]: r["nx"] for r in self.db.q(
            "SELECT member_id, MIN(date||' '||time) AS nx FROM schedules "
            "WHERE done=0 AND member_id IS NOT NULL AND date||' '||time >= ? GROUP BY member_id", (nowk,))}
        self.mem_tree.delete(*self.mem_tree.get_children())
        for r in rows:
            lines = [l.strip() for l in (r["memo"] or "").splitlines() if l.strip()]
            n = nxt.get(r["id"])
            tags = ["odd"] if len(self.mem_tree.get_children()) % 2 else []
            if r["color"]:
                tags.append(self.color_tag(r["color"]))
            self.mem_tree.insert("", "end", iid=str(r["id"]), tags=tuple(tags), values=(
                r["name"], r["phone"], short(r["keyword"], 30), n[5:] if n else "", short(lines[-1] if lines else "", 40),
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
            if (m["keyword"] or "").strip():
                t.insert("end", "검색어  ", "sec")
                t.insert("end", f'{m["keyword"]}\n')
            t.insert("end", f'등록 {(m["created"] or "")[:16]}  ·  수정 {(m["updated"] or "")[:16]}\n\n', "g")
            t.insert("end", "▶ 예정된 예약\n", "sec")
            ups = self.db.q("SELECT * FROM schedules WHERE member_id=? AND done=0 ORDER BY date,time", (m["id"],))
            if ups:
                for r in ups:
                    t.insert("end", f'   {r["date"][5:]} {r["time"]}   {r["title"]}   [{state_text(r, self.db)}]\n')
            else:
                t.insert("end", "   없음\n", "g")
            t.insert("end", "\n▶ 상담 내용\n", "sec")
            t.insert("end", (m["memo"] or "").strip() or "(내용 없음)")
            t.see("end")
        else:
            t.insert("end", "회원을 클릭하면 여기에 요약이 나옵니다.", "g")
        t.config(state="disabled")

    def refresh_notes(self):
        rows = self.db.q("SELECT * FROM notes ORDER BY id")
        n = len(self.note_cards)
        for i, (f, t, b) in enumerate(self.note_cards):
            if i < len(rows):
                r = rows[i]
                self.note_ids[i] = r["id"]
                lines = [l for l in (r["content"] or "").splitlines() if l.strip()]
                for w in (f, t, b):
                    w.config(bg=NOTE_BG)
                f.config(highlightbackground="#E6CF8E")
                t.config(text=short(r["title"] or "제목 없음", 13), fg="#5A4316")
                b.config(text="\n".join(short(l, 18) for l in lines[:5]), fg="#7A6A48")
            else:
                self.note_ids[i] = None
                for w in (f, t, b):
                    w.config(bg="#FAF6EC")
                f.config(highlightbackground="#EADFC6")
                t.config(text="＋", fg="#C9B98F")
                b.config(text="새 메모", fg="#C9B98F")
        extra = len(rows) - n
        self.more_btn.config(text=f"─────  더보기 (+{extra})  ─────" if extra > 0 else "─────  전체 메모 보기  ─────")

    def update_status(self):
        r = self.db.one("SELECT a.fire_at, s.*, m.name AS mname FROM alarms a JOIN schedules s ON s.id=a.schedule_id "
                        "LEFT JOIN members m ON s.member_id=m.id "
                        "WHERE a.notified=0 AND s.done=0 ORDER BY a.fire_at LIMIT 1")
        push = "폰 알림 켜짐" if phone_cfg(self.db)[0] else "폰 알림 꺼짐"
        if WORKER_URL and push == "폰 알림 켜짐":
            ph = getattr(self, "phones", None)
            if ph == 0:
                push = "⚠ 폰 연결 없음 — [📱 폰 연결 · 웹앱]에서 다시 연결하세요"
            elif ph:
                push += f" (받는 곳 {ph}곳)"
        if WORKER_URL:
            if self._sync_state not in ("", "ok"):
                push += f" — {self._sync_state}"
            elif self._sync_at:
                push += f"  ·  웹앱 동기화 {self._sync_at:%H:%M}"
        if getattr(self, "hotkey_ok", False):
            push += f"     |     어깨동무: 상세창 {HOTKEY_TEXT} → 회원 가져오기 · 목록 F9 → 오늘 일정 추가"
        if r:
            who = f' ({r["mname"]})' if r["mname"] else ""
            self.status.config(text=f'⏰ 다음 알림: {r["fire_at"]}  {r["title"]}{who}  (일정 {r["date"][5:]} {r["time"]})'
                                    f'     |     {push}')
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
            bring_front(w)
            return
        w = MemberDialog(self, mid)
        if mid:
            self.member_windows[mid] = w
        bring_front(w)

    # ---------- 우클릭 메뉴 ----------
    def make_menu(self, items):
        m = tk.Menu(self.root, tearoff=0, font=(F, 10), bg=PANEL, fg=TEXT, activebackground=ACCENT,
                    activeforeground="white", bd=1, relief="solid")
        for it in items:
            if it is None:
                m.add_separator()
            else:
                m.add_command(label=it[0], command=it[1])
        return m

    def popup_menu(self, e, tree, menu):
        row = tree.identify_row(e.y)
        if not row:
            return
        tree.selection_set(row)
        tree.focus(row)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def color_tag(self, hexc):
        tag = "c" + hexc.lstrip("#")
        if tag not in getattr(self, "_color_tags", set()):
            self.mem_tree.tag_configure(tag, foreground=hexc, font=FONT_B)
            self._color_tags = getattr(self, "_color_tags", set()) | {tag}
        return tag

    def member_color(self, hexc):
        s = self.mem_tree.selection()
        if s:
            self.db.x("UPDATE members SET color=? WHERE id=?", (hexc, int(s[0])))
            self.refresh_members(select=int(s[0]))

    def member_move(self, where):
        s = self.mem_tree.selection()
        if not s:
            return
        mid = int(s[0])
        rows = self.db.q("SELECT id, sort_order FROM members ORDER BY sort_order, id DESC")
        ids = [r["id"] for r in rows]
        so = [r["sort_order"] for r in rows]
        i = ids.index(mid)
        if None in so or len(set(so)) != len(so):     # 순서값이 겹치면 한 번 새로 매김
            with self.db.conn:
                self.db.conn.executemany("UPDATE members SET sort_order=? WHERE id=?", [(k, x) for k, x in enumerate(ids)])
            so = list(range(len(ids)))
        upd = []                                      # 움직인 회원만 바꿈 (웹앱 동기화 양 줄이기)
        if where == "top" and i > 0:
            upd = [(so[0] - 1, mid)]
        elif where == "bottom" and i < len(ids) - 1:
            upd = [(so[-1] + 1, mid)]
        elif where == "up" and i > 0:
            upd = [(so[i - 1], mid), (so[i], ids[i - 1])]
        elif where == "down" and i < len(ids) - 1:
            upd = [(so[i + 1], mid), (so[i], ids[i + 1])]
        if upd:
            with self.db.conn:
                self.db.conn.executemany("UPDATE members SET sort_order=? WHERE id=?", upd)
            self.request_sync()
        self.refresh_members(select=mid)
        self.mem_tree.focus(str(mid))

    def member_call_res(self):
        s = self.mem_tree.selection()
        if not s:
            return
        mid = int(s[0])
        r = self.db.one("SELECT name FROM members WHERE id=?", (mid,))
        ScheduleDialog(self, member_id=mid, title_default=f"재통화: {(r['name'] if r else '') or ''}".strip())

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
                if w._auto_job:
                    w.after_cancel(w._auto_job)
                w.destroy()
            self.refresh_all()

    # ---------- 키워드 메모 ----------
    def new_note(self):
        nid = self.db.x("INSERT INTO notes(title, content, updated) VALUES('', '', ?)", (stamp(),))
        self.refresh_notes()
        self.open_note(nid)

    def open_note(self, nid):
        w = self.note_windows.get(nid)
        if w and w.winfo_exists():
            w.deiconify()
            w.lift()
            w.focus_force()
        elif self.db.one("SELECT id FROM notes WHERE id=?", (nid,)):
            self.note_windows[nid] = NoteWindow(self, nid)

    # ---------- 어깨동무 가져오기 ----------
    def poll_hotkey(self):
        try:
            while True:
                kind, hwnd = self.hk_queue.get_nowait()
                if self._locked:
                    if kind == "f9_done":
                        self._f9_busy = False
                    continue
                if kind == "capture":
                    self.import_ekdm(hwnd)
                elif kind == "f9":
                    self.quick_schedule(hwnd)
                elif kind == "f9_done":
                    self.open_quick_schedule(hwnd)
                elif kind == "fail":
                    toast(self.root, f"{hwnd.strip()} 단축키를 다른 프로그램이 쓰고 있어 등록하지 못했어요.\n"
                                     "상단 버튼으로는 그대로 쓸 수 있어요.", 6000)
        except queue.Empty:
            pass
        self.root.after(200, self.poll_hotkey)

    # ---------- F9: 어깨동무 목록에서 선택한 사람으로 오늘 일정 바로 만들기 ----------
    def quick_schedule(self, hwnd=None):
        if not IS_WIN:
            toast(self.root, "F9 일정 추가는 윈도우에서만 사용할 수 있어요.")
            return
        if getattr(self, "_f9_busy", False):
            return
        self._f9_busy = True


        def run():
            try:
                res = ekdm_read_via_detail(hwnd)          # 1순위: 상세창을 투명하게 열어 정확히 읽기
            except Exception as e1:
                try:
                    res = ekdm_read_selected(hwnd)        # 2순위: 화면 글자 인식
                    res["method"] = "ocr"
                except Exception as e2:
                    res = {"error": f"{e2}"}
            self.hk_queue.put(("f9_done", res))

        threading.Thread(target=run, daemon=True).start()

    def open_quick_schedule(self, res):
        self._f9_busy = False
        if res.get("error"):
            toast(self.root, f"F9: {res['error']}", 6000)
            return
        name, phone = res.get("name", ""), res.get("phone", "")
        if not phone and not name:
            toast(self.root, "F9: 이름·전화번호를 읽지 못했어요. 회원 줄을 다시 클릭하고 F9를 눌러주세요.", 6000)
            return
        title = f"{name} {phone}".strip()
        d = ScheduleDialog(self, date=dt.date.today().isoformat(), title_default=title)
        kw = (res.get("keyword") or "").strip()
        if kw:                    # 어깨동무 검색어를 내용 첫 줄에 넣고, 그 아래에 바로 쓰게
            d.content.insert("1.0", f"[검색어] {kw}\n")
            d.content.edit_modified(False)
            d.after(50, lambda: setattr(d, "_dirty", False))
        d.content.mark_set("insert", "end")
        d.content.focus_set()     # 바로 '7시 재통화' 같은 내용을 쓰면 되게

    def import_ekdm(self, hwnd=None):
        if not IS_WIN:
            toast(self.root, "어깨동무 가져오기는 윈도우에서만 사용할 수 있습니다.")
            return
        h = find_ekdm(hwnd)
        if not h:
            toast(self.root, "어깨동무에서 회원을 더블클릭해 상세창을 띄운 뒤\n"
                                                 f"{HOTKEY_TEXT} 를 눌러주세요.")
            return
        try:
            data = read_ekdm(h)
        except Exception as e:
            toast(self.root, f"어깨동무 읽기 실패: {e}", 6000)
            return
        ImportDialog(self, data)

    # ---------- 알림 ----------
    def check_alarms(self):
        try:
            if self._locked:
                return
            nowk = now().strftime("%Y-%m-%d %H:%M")
            rows = self.db.q("SELECT a.id AS aid, a.fire_at, a.offset_min, s.* FROM alarms a "
                             "JOIN schedules s ON s.id=a.schedule_id "
                             "WHERE a.notified=0 AND s.done=0 AND a.fire_at <= ? ORDER BY a.fire_at", (nowk,))
            shown = set()
            for r in rows:
                self.db.x("UPDATE alarms SET notified=1 WHERE id=?", (r["aid"],))
                if r["id"] in shown:      # 같은 일정 알림이 여러 개 밀려 있으면 팝업은 1번만
                    continue
                shown.add(r["id"])
                AlarmPopup(self, r, offset=((len(shown) - 1) % 8) * 30)
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
        on, _, topic = phone_cfg(self.db)
        if not on or not topic:
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
        self.quit_now()   # 모든 내용은 자동 저장, 폰 알림은 서버에서 발송

    def quit_now(self):
        self.flush_diary()
        for w in list(self.member_windows.values()):
            if w.winfo_exists():
                w.save(quiet=True)
        for w in list(self.note_windows.values()):
            if w.winfo_exists():
                w.close()
        self.root.destroy()


def write_crash(text):
    """시작 오류를 파일로 남김 (프로그램 폴더 + 데이터 폴더)"""
    for d in (BASE_DIR, DATA_DIR):
        try:
            with open(os.path.join(d, "error.log"), "a", encoding="utf-8") as f:
                f.write(f"\n===== {stamp()}  v{APP_VERSION} =====\n{text}\n")
        except Exception:
            pass


if __name__ == "__main__":
    import traceback
    try:
        root = tk.Tk()
        root.report_callback_exception = lambda *exc: write_crash("".join(traceback.format_exception(*exc)))
        if WORKER_URL:      # 배포판: 라이선스 확인 후 시작
            root.withdraw()
            _db = DB(DB_PATH)
            _dev = _db.get("device_id")
            if not _dev:
                _dev = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
                _db.set("device_id", _dev)

            def _go(info):
                App(root, _db)
                root.deiconify()
                bring_front(root)
            lic_start(root, _db, _dev, _go)
        else:
            App(root)
        root.mainloop()
    except Exception:
        err = traceback.format_exc()
        write_crash(err)
        try:
            messagebox.showerror("업무 다이어리 실행 오류", err[-1500:] + "\n\n(error.log 에 저장했습니다)")
        except Exception:
            print(err)
        sys.exit(1)
