"""Acesso ao Windows via ctypes: localizar a janela do jogo, capturar, clicar e teclar."""
import ctypes
import random
import time
from ctypes import wintypes

import numpy as np
from PIL import ImageGrab

user32 = ctypes.WinDLL("user32", use_last_error=True)

try:  # coordenadas reais de pixel mesmo com escala do Windows != 100%
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9

VK = {"esc": 0x1B, "enter": 0x0D, "space": 0x20, "tab": 0x09, "backspace": 0x08, "f8": 0x77}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_bot = {"t": 0.0, "cursor": None}  # última entrada gerada pelo TOSCO (para não confundir com a do usuário)


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    _mark()


def _mark():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    _bot["t"], _bot["cursor"] = time.monotonic(), (pt.x, pt.y)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds():
    """Segundos desde a última entrada de mouse/teclado no Windows (de qualquer origem)."""
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not user32.GetLastInputInfo(ctypes.byref(li)):
        return 1e9
    return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


def user_input_age(grace=0.8):
    """Há quantos segundos o USUÁRIO mexeu (mouse/teclado), descontando a entrada do próprio TOSCO; None se a
    última entrada foi do TOSCO. O cursor fora de onde o TOSCO o deixou também conta como mexida do usuário."""
    now = time.monotonic()
    idle = idle_seconds()
    last = now - idle
    if last > _bot["t"] + grace:
        return idle
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    c = _bot["cursor"]
    if c and (abs(pt.x - c[0]) > 25 or abs(pt.y - c[1]) > 25):
        return idle
    return None


def list_windows():
    """[(hwnd, título)] de janelas visíveis com título."""
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


BROWSER_CLASSES = ("Chrome_WidgetWin", "MozillaWindowClass", "ApplicationFrameWindow")


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_window(title_part):
    """Título exato primeiro; depois parcial, ignorando o próprio TOSCO e abas de navegador
    (uma pesquisa 'bot last war' no Chrome também tem 'Last War' no título)."""
    wins = [(h, t) for h, t in list_windows() if not t.startswith(("TOSCO", "NEXUS"))]
    for hwnd, title in wins:
        if title.lower() == title_part.lower():
            return hwnd
    partial = [h for h, t in wins
               if title_part.lower() in t.lower() and not window_class(h).startswith(BROWSER_CLASSES)]
    # o jogo é uma janela Unity: entre várias "Last War" (ferramentas, sites de stats), prefere ela
    unity = [h for h in partial if window_class(h) == "UnityWndClass"]
    return (unity or partial or [None])[0]


def window_pid(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def client_rect(hwnd):
    """Retângulo da área cliente em coordenadas de tela: (x, y, w, h)."""
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def focus(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


def resize_client(hwnd, w, h):
    """Redimensiona a janela para que a área cliente fique w x h."""
    wr, cr = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(wr))
    user32.GetClientRect(hwnd, ctypes.byref(cr))
    dw = (wr.right - wr.left) - cr.right
    dh = (wr.bottom - wr.top) - cr.bottom
    user32.MoveWindow(hwnd, wr.left, wr.top, w + dw, h + dh, True)


def grab(rect):
    """Captura BGR (numpy) de um retângulo (x, y, w, h) da tela."""
    x, y, w, h = rect
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    return np.array(img)[:, :, ::-1].copy()


gdi32 = ctypes.WinDLL("gdi32")
# handles são de 64 bits: sem restype/argtypes o ctypes trunca para int
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                            ctypes.c_void_p, wintypes.UINT]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def grab_window(hwnd):
    """Captura só a área cliente da janela (mesmo coberta por outras) via PrintWindow.
    Retorna BGR ou None se a janela não renderizar por esse caminho."""
    rect = client_rect(hwnd)
    if not rect or rect[2] <= 0 or rect[3] <= 0:
        return None
    w, h = rect[2], rect[3]
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        PW_CLIENTONLY, PW_RENDERFULLCONTENT = 0x1, 0x2
        if not user32.PrintWindow(hwnd, mdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return None
        bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, :3].copy()
        return img if img.max() > 0 else None
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)


def click(x, y, jitter_px=2):
    x += random.randint(-jitter_px, jitter_px)
    y += random.randint(-jitter_px, jitter_px)
    user32.SetCursorPos(int(x), int(y))
    _mark()
    time.sleep(0.02)
    down =INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)))
    up = INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)))
    _send(down)
    time.sleep(random.uniform(0.03, 0.07))
    _send(up)


def drag(x1, y1, x2, y2, steps=20, duration=0.4):
    user32.SetCursorPos(int(x1), int(y1))
    _send(INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0))))
    for i in range(1, steps + 1):
        user32.SetCursorPos(int(x1 + (x2 - x1) * i / steps), int(y1 + (y2 - y1) * i / steps))
        _mark()
        time.sleep(duration / steps)
    time.sleep(0.15)  # segura parado antes de soltar: o mapa não "desliza" por inércia
    _send(INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0))))


def scroll(x, y, clicks):
    user32.SetCursorPos(int(x), int(y))
    _send(INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(0, 0, ctypes.c_ulong(120 * clicks).value,
                                                             MOUSEEVENTF_WHEEL, 0, 0))))


def key(name):
    vk = VK.get(name.lower()) or ord(name.upper()[0])
    _send(INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(vk, 0, 0, 0, 0))))
    time.sleep(0.03)
    _send(INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0))))


def type_text(text):
    """Digita texto unicode (usado para mensagens no chat)."""
    KEYEVENTF_UNICODE = 0x0004
    for ch in text:
        code = ord(ch)
        _send(INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0))),
              INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))))
        time.sleep(0.01)
