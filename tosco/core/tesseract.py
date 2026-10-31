"""Tesseract para os números do jogo. O OCR do Windows não lê a fonte dos cronômetros e números pequenos do
Last War (devolve nada ou lixo); o Tesseract lê. Procura o tesseract.exe ao lado do TOSCO (pasta tesseract\\),
depois na instalação padrão. Sem ele, quem chama cai no OCR do Windows."""
import collections
import os
import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

from .paths import ROOT

_CANDIDATES = [os.path.join(ROOT, "tesseract", "tesseract.exe"),
               r"C:\Program Files\Tesseract-OCR\tesseract.exe",
               r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_exe = None


def binary():
    global _exe
    if _exe is None:
        _exe = next((p for p in _CANDIDATES if os.path.isfile(p)), None) or shutil.which("tesseract") or ""
    return _exe


def available():
    return bool(binary())


def _run(img, psm, whitelist=None):
    exe = binary()
    if not exe or img is None or img.size == 0:
        return ""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        cv2.imwrite(path, img)
        cmd = [exe, path, "stdout", "--psm", str(psm), "-l", "eng"]
        if whitelist:
            cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
        tessdata = os.path.join(os.path.dirname(exe), "tessdata")
        if os.path.isdir(tessdata):
            cmd += ["--tessdata-dir", tessdata]
        r = subprocess.run(cmd, capture_output=True, timeout=10, creationflags=_NO_WINDOW)
        return r.stdout.decode("utf-8", "ignore").strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# --- preparo da imagem -----------------------------------------------------
def _pad(img, frac=0.25):
    h, w = img.shape[:2]
    p = max(6, int(h * frac))
    return cv2.copyMakeBorder(img, p, p, p, p, cv2.BORDER_CONSTANT, value=255)


def _upscale(img, target_w=1200):
    h, w = img.shape[:2]
    f = max(1.0, min(6.0, target_w / max(1, w)))
    return cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)


def _ink_crop(bw):
    """Recorta em volta da tinta preta (fundo branco) — com margem variável o Tesseract perde dígitos."""
    ys, xs = np.where(bw < 128)
    if len(xs) == 0:
        return bw
    return bw[max(0, ys.min() - 2):ys.max() + 3, max(0, xs.min() - 2):xs.max() + 3]


def white_text(bgr, v_min=230, s_max=90):
    """Texto BRANCO em fundo escuro/colorido → preto em fundo branco (melhor preparo para os cronômetros)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 2] >= v_min) & (hsv[:, :, 1] <= s_max)
    out = np.where(mask, 0, 255).astype(np.uint8)
    out = cv2.morphologyEx(out, cv2.MORPH_OPEN, np.ones((1, 1), np.uint8))
    return out


def variants(bgr, target_w=1200):
    """Versões da imagem tentadas em ordem: isolamento do branco, cinza com borda, P&B (Otsu) com borda."""
    up = _upscale(bgr, target_w)
    out = [_pad(_ink_crop(white_text(up)))]
    gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
    if gray.mean() < 127:
        gray = 255 - gray
    out.append(_pad(gray))
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (otsu < 128).mean() > 0.5:
        otsu = 255 - otsu
    out.append(_pad(_ink_crop(otsu)))
    return out


# --- cronômetros -----------------------------------------------------------
MAX_TIMER = 4 * 3600


def parse_timer(text):
    """'00:12', '1:02:03', '12s' → segundos. Tolera dígito fantasma no início/fim (alucinação do Tesseract)."""
    t = (text or "").replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
    m = re.search(r"(\d{1,2})\s*[:.]\s*(\d{2})(?:\s*[:.]\s*(\d{2}))?", t)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        v = a * 3600 + b * 60 + int(c) if c is not None else a * 60 + b
        if 0 <= v <= MAX_TIMER and b < 60 and (c is None or int(c) < 60):
            return v
    digits = re.sub(r"\D", "", t)
    for size in (6, 5, 4):  # HHMMSS / HMMSS / MMSS, tentando prefixo e sufixo
        for win in (digits[:size], digits[-size:]):
            if len(win) != size:
                continue
            s = win.zfill(6)
            hh, mm, ss = int(s[:2]), int(s[2:4]), int(s[4:])
            if mm < 60 and ss < 60:
                v = hh * 3600 + mm * 60 + ss
                if 0 < v <= MAX_TIMER:
                    return v
    m = re.search(r"(\d{1,3})\s*s\b", t, re.I)
    return int(m.group(1)) if m else None


def read_timer(bgr):
    """Cronômetro num recorte BGR → segundos ou None. PSM 7 → 8 → 6 → 13 em cada variante."""
    if not available() or bgr is None or bgr.size == 0:
        return None
    for img in variants(bgr):
        for psm in (7, 8, 6, 13):
            v = parse_timer(_run(img, psm, "0123456789:"))
            if v is not None:
                return v
    return None


def read_timer_in_text(bgr):
    """Cronômetro numa região MAIOR (a aba inteira do popup): só aceita tokens com ':' — evita que '87%' ou
    '25600%' virem tempo."""
    if not available() or bgr is None or bgr.size == 0:
        return None
    for img in variants(bgr, 1600)[:2]:
        for psm in (6, 11):
            for tok in re.findall(r"\d{1,2}\s*:\s*\d{2}(?:\s*:\s*\d{2})?", _run(img, psm)):
                v = parse_timer(tok)
                if v is not None:
                    return v
    return None


# --- números ---------------------------------------------------------------
def read_vote(bgr, parse, need=2, psms=(7, 6, 13), whitelist=None, target_w=1200):
    """Leitura robusta de texto curto: cada variante × cada PSM; o valor que aparecer `need` vezes ganha,
    senão o mais votado. `parse(texto)` → valor ou None (rejeita)."""
    if not available() or bgr is None or bgr.size == 0:
        return None
    votes = collections.Counter()
    for img in variants(bgr, target_w):
        for psm in psms:
            v = parse(_run(img, psm, whitelist))
            if v is None:
                continue
            votes[v] += 1
            if votes[v] >= need:
                return v
    return votes.most_common(1)[0][0] if votes else None


def read_int(bgr, lo=0, hi=10 ** 9):
    def p(t):
        d = re.sub(r"[^\d]", "", t or "")
        return int(d) if d and lo <= int(d) <= hi else None
    return read_vote(bgr, p, whitelist="0123456789")


def read_fraction(bgr, min_den=1):
    """'373/120', '1 042/120' → (atual, máximo). Remove o custo negativo ('-10') e junta milhares."""
    def p(t):
        t = re.sub(r"[-—–]\s*\d{1,3}(?=\s)", " ", t or "")  # custo vermelho "-10"/"-20" antes do valor
        t = re.sub(r"(\d)[\s.,](\d{3})(?!\d)", r"\1\2", t)
        m = re.search(r"(\d+)\s*/\s*(\d+)", t)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        return (a, b) if b >= min_den else None
    return read_vote(bgr, p)  # sem lista de caracteres: ela come o espaço entre o custo e o valor


def read_level(bgr):
    """'Lv.85' / 'Niv.85' / '85' → int."""
    def p(t):
        m = re.search(r"(?:[NnLl][iI]?[vVuU]\.?\s*)?(\d{1,3})", t or "")
        return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 200 else None
    return read_vote(bgr, p, psms=(7, 6), whitelist="0123456789LlVvNi.")
