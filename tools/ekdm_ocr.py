# -*- coding: utf-8 -*-
"""어깨동무 메인 목록에서 '선택된 줄'을 화면 글자 인식(윈도우 기본 OCR)으로 읽기.
WorkDiary 본체와 확인용 스크립트가 함께 쓰는 모듈 (파이썬 기본 기능 + 윈도우 PowerShell만 사용)."""
import ctypes, os, re, struct, subprocess, tempfile, json
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

MAIN_CLASS = "TfrmAddrmain"
GRID_CLASS = "TRxDBGrid"


def _cls(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def _rect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def find_main(hwnd=None):
    if hwnd:
        root = user32.GetAncestor(hwnd, 2)
        if root and _cls(root) == MAIN_CLASS:
            return root
    out = []
    cb = WNDENUMPROC(lambda h, l: (out.append(h) if user32.IsWindowVisible(h) and _cls(h) == MAIN_CLASS
                                   else None, True)[1])
    user32.EnumWindows(cb, 0)
    return out[0] if out else None


def find_grid(main):
    best = None
    out = []
    cb = WNDENUMPROC(lambda c, l: (out.append(c), True)[1])
    user32.EnumChildWindows(main, cb, 0)
    for c in out:
        if _cls(c) == GRID_CLASS and user32.IsWindowVisible(c):
            l, t, r, b = _rect(c)
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


def capture(hwnd):
    l, t, r, b = _rect(hwnd)
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


def ocr(bmp_path):
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


def read_selected(hwnd=None, debug_dir=None, mode="gray", k=3):
    main = find_main(hwnd)
    if not main:
        raise RuntimeError("어깨동무 메인 화면을 찾지 못했어요.")
    grid = find_grid(main)
    if not grid:
        raise RuntimeError("어깨동무 회원 목록을 찾지 못했어요.")
    shot = capture(grid)
    row = find_selected_row(shot)
    if not row:
        raise RuntimeError("선택된 회원 줄을 찾지 못했어요. 목록에서 회원을 한 번 클릭해 주세요.")
    y0, y1 = row
    x1 = min(shot.w, 700)                         # 이름·휴대폰 칸이 있는 왼쪽 부분만
    strip = shot.crop_scale(0, y0, x1, y1, k=k, mode=mode)
    tmp = os.path.join(debug_dir or tempfile.gettempdir(), f"workdiary_row_{mode}{k}.bmp")
    strip.save_bmp(tmp)
    try:
        lang, words = ocr(tmp)
    finally:
        if not debug_dir:
            try:
                os.remove(tmp)
            except OSError:
                pass
    name, phone, raw = parse_row(words)
    return {"name": name, "phone": phone, "raw": raw, "lang": lang, "row": row}
