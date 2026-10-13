# -*- coding: utf-8 -*-
"""어깨동무 메인(목록) 화면 구조 확인 — 설치 필요 없음 (윈도우 기본 기능만 사용)
실행 후 5초 안에 어깨동무 메인 화면(회원 목록)을 클릭하세요. 회원 한 명을 선택해 둔 상태로.
결과: 같은 폴더의 ekdm_main_probe.txt
"""
import ctypes, os, sys, time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
OUT = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "..", "ekdm_main_probe.txt")


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def text(h, limit=300):
    r = ctypes.c_size_t()
    user32.SendMessageTimeoutW(h, 0x000E, 0, 0, 2, 1000, ctypes.byref(r))
    n = min(r.value, 20000)
    b = ctypes.create_unicode_buffer(n + 2)
    user32.SendMessageTimeoutW(h, 0x000D, n + 1, ctypes.cast(b, ctypes.c_void_p).value, 2, 1000, ctypes.byref(r))
    t = b.value.replace("\r", "").replace("\n", " / ")
    return (t[:limit] + f"…({len(b.value)}자)") if len(t) > limit else t


def rect(h):
    r = wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def pid(h):
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def children(h):
    out = []
    cb = WNDENUMPROC(lambda c, l: (out.append(c), True)[1])
    user32.EnumChildWindows(h, cb, 0)
    return out


print("5초 안에 어깨동무 '메인 화면(회원 목록)'을 클릭하세요. 회원 한 명을 선택해 두세요.")
for i in range(5, 0, -1):
    print(i)
    time.sleep(1)

fg = user32.GetAncestor(user32.GetForegroundWindow(), 2)
P = pid(fg)
L = []
L.append(f"foreground: class={cls(fg)} title={text(fg, 80)!r} rect={rect(fg)} pid={P}")

# 같은 프로그램의 모든 최상위 창 (숨겨진 창 포함)
tops = []
cb = WNDENUMPROC(lambda h, l: (tops.append(h) if pid(h) == P else None, True)[1])
user32.EnumWindows(cb, 0)
L.append("\n=== 같은 프로그램의 최상위 창 ===")
for h in tops:
    L.append(f"{h:#x} class={cls(h)} visible={bool(user32.IsWindowVisible(h))} title={text(h, 60)!r} rect={rect(h)}")

for top in [fg] + [h for h in tops if h != fg and cls(h) not in ("TApplication",)]:
    L.append(f"\n=== 창 {cls(top)} ({top:#x}) visible={bool(user32.IsWindowVisible(top))} 의 내부 ===")
    ox, oy, _, _ = rect(top)
    for c in children(top):
        cn = cls(c)
        if cn in ("TPanel", "TGroupBox", "TTabSheet", "TPageControl", "TToolBar", "TSpeedButton", "TBitBtn",
                  "TButton", "TImage", "TScrollBox", "TSplitter", "TToolButton"):
            continue
        x, y, w, hh = rect(c)
        L.append(f"  [{cn}] vis={int(bool(user32.IsWindowVisible(c)))} pos=({x - ox},{y - oy}) size=({w}x{hh}) "
                 f"text={text(c)!r}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print("완료! ekdm_main_probe.txt 가 WorkDiary 폴더에 저장됐습니다.")
input("Enter를 누르면 닫힙니다.")
