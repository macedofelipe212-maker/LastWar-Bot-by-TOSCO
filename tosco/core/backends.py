"""Plataformas: jogo oficial de PC (janela do Windows) ou emulador Android via ADB (roda em segundo plano,
uma conta por emulador). As tarefas só falam com esta interface, em coordenadas do frame capturado."""
import math
import os
import random
import shutil
import subprocess
import time

import cv2
import numpy as np

from . import winapi

NO_WINDOW = 0x08000000  # subprocess sem abrir console


class PCBackend:
    name = "pc"

    def __init__(self, cfg):
        self.cfg = cfg
        self.hwnd = None

    def _human(self):
        return self.cfg.data["human"]

    def describe(self):
        r = self.rect()
        if self.minimized():
            return "jogo minimizado (o motor restaura ao iniciar)"
        return f"janela {r[2]}×{r[3]} em ({r[0]},{r[1]})" if r else \
            f"janela '{self.cfg.data['game_window_title']}' não encontrada"

    def minimized(self):
        return bool(self.hwnd and winapi.user32.IsIconic(self.hwnd))

    def rect(self):
        if not self.hwnd or not winapi.user32.IsWindow(self.hwnd):
            self.hwnd = winapi.find_window(self.cfg.data["game_window_title"])
        if not self.hwnd or self.minimized():
            return None
        return winapi.client_rect(self.hwnd)

    def ready(self, restore=False):
        """restore: o motor está rodando e precisa do jogo — tira do minimizado."""
        if restore and self.rect() is None and self.minimized():
            winapi.focus(self.hwnd)
            time.sleep(1.0)
        return self.rect() is not None

    def capture(self):
        r = self.rect()
        if not r or r[2] <= 0:
            return None
        img = winapi.grab_window(self.hwnd)
        return img if img is not None else winapi.grab(r)

    def prepare(self, log):
        r = self.rect()
        if not r:
            return
        want = self.cfg.data.get("resize_to")
        sw, sh = winapi.user32.GetSystemMetrics(16), winapi.user32.GetSystemMetrics(17)  # área útil
        if want == "auto":
            # tamanho padrão 16:9: o maior desta lista que cabe na tela. Sempre o mesmo tamanho = imagens e
            # posições consistentes entre uma sessão e outra
            want = next((f"{w}x{h}" for w, h in ((1920, 1080), (1600, 900), (1280, 720), (1024, 576))
                         if w <= sw and h <= sh), "")
        if want:
            try:
                w, h = map(int, want.lower().split("x"))
                if w > sw or h > sh:
                    log(f"Redimensionar para {w}x{h} ignorado: maior que a tela ({sw}x{sh})", "warn")
                elif abs(r[2] - w) > 2 or abs(r[3] - h) > 2:
                    winapi.resize_client(self.hwnd, w, h)
                    log(f"Janela do jogo ajustada para o tamanho padrão {w}x{h} (era {r[2]}x{r[3]})")
            except ValueError:
                pass
        winapi.focus(self.hwnd)

    def _move_human(self, x, y):
        """Leva o cursor até o alvo por uma curva com aceleração, como uma mão."""
        pt = winapi.wintypes.POINT()
        winapi.user32.GetCursorPos(winapi.ctypes.byref(pt))
        x0, y0 = pt.x, pt.y
        dist = math.hypot(x - x0, y - y0)
        if dist < 4:
            return
        steps = int(min(28, max(6, dist / 40)))
        cx = (x0 + x) / 2 + random.uniform(-0.2, 0.2) * dist
        cy = (y0 + y) / 2 + random.uniform(-0.2, 0.2) * dist
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)  # ease in/out
            bx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x
            by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y
            winapi.user32.SetCursorPos(int(bx), int(by))
            winapi._mark()
            time.sleep(random.uniform(0.004, 0.009))

    def tap(self, x, y):
        r = self.rect()
        if not r:
            raise RuntimeError("janela do jogo não encontrada")
        sx, sy = r[0] + int(x), r[1] + int(y)
        if winapi.user32.GetForegroundWindow() != self.hwnd:
            winapi.focus(self.hwnd)
            time.sleep(0.15)
        if self._human().get("mouse_curve"):
            self._move_human(sx, sy)
        winapi.click(sx, sy, 0)

    def drag(self, x1, y1, x2, y2, duration=0.45):
        r = self.rect()
        winapi.drag(r[0] + x1, r[1] + y1, r[0] + x2, r[1] + y2, duration=duration)

    def scroll(self, x, y, clicks):
        r = self.rect()
        winapi.scroll(r[0] + x, r[1] + y, clicks)

    def key(self, name):
        winapi.key(name)

    def type(self, text):
        winapi.type_text(text)


ADB_CANDIDATES = [
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"C:\Program Files\MuMu\emulator\nemu\vmonitor\bin\adb_server.exe",
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\LDPlayer\LDPlayer4.0\adb.exe",
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\Nox\bin\adb.exe",
    r"C:\Program Files\Microvirt\MEmu\adb.exe",
]
KEYCODES = {"esc": 4, "back": 4, "enter": 66, "home": 3, "space": 62, "tab": 61, "backspace": 67}


def find_adb(configured=""):
    if configured and os.path.exists(configured):
        return configured
    for c in ADB_CANDIDATES:
        if os.path.exists(c):
            return c
    return shutil.which("adb")


class ADBBackend:
    name = "adb"

    def __init__(self, cfg):
        self.cfg = cfg
        self.adb = None
        self._size = None

    def _cmd(self, *args, timeout=15, binary=False):
        self.adb = self.adb or find_adb(self.cfg.data.get("adb_path", ""))
        if not self.adb:
            raise RuntimeError("adb não encontrado — informe o caminho em SISTEMA")
        serial = self.cfg.data.get("adb_serial", "")
        cmd = [self.adb] + (["-s", serial] if serial else []) + list(args)
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        return out.stdout if binary else out.stdout.decode("utf-8", "ignore")

    def devices(self):
        try:
            txt = self._cmd("devices", timeout=8)
        except Exception:
            return []
        return [l.split("\t")[0] for l in txt.splitlines()[1:] if "\tdevice" in l]

    def connect(self, address):
        return self._cmd("connect", address, timeout=10)

    def describe(self):
        d = self.devices()
        s = self.cfg.data.get("adb_serial", "")
        if not d:
            return "nenhum emulador conectado via ADB"
        return f"emulador {s or d[0]}" + (f" ({self._size[0]}×{self._size[1]})" if self._size else "")

    def ready(self):
        return bool(self.devices())

    def capture(self):
        raw = self._cmd("exec-out", "screencap", "-p", binary=True, timeout=10)
        if not raw:
            return None
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            self._size = (img.shape[1], img.shape[0])
        return img

    def prepare(self, log):
        log(f"ADB: {self.describe()}")

    def tap(self, x, y):
        self._cmd("shell", "input", "tap", str(int(x)), str(int(y)))

    def drag(self, x1, y1, x2, y2, duration=0.45):
        self._cmd("shell", "input", "swipe", *map(str, map(int, (x1, y1, x2, y2))), str(int(duration * 1000)))

    def scroll(self, x, y, clicks):
        dy = int(-clicks * 120)
        self.drag(x, y, x, y + dy, 0.25)

    def key(self, name):
        code = KEYCODES.get(name.lower())
        if code:
            self._cmd("shell", "input", "keyevent", str(code))

    def type(self, text):
        safe = "".join(c for c in text if ord(c) < 128).replace(" ", "%s")
        for ch in "\\'\"()&<>|;*?$`":
            safe = safe.replace(ch, "")
        if safe:
            self._cmd("shell", "input", "text", safe)


def make_backend(cfg):
    return ADBBackend(cfg) if cfg.data.get("backend") == "adb" else PCBackend(cfg)
