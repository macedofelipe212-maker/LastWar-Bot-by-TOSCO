"""OCR nativo do Windows 10/11 (Windows.Media.Ocr): lê texto em qualquer idioma instalado no Windows,
sem Tesseract. Usado para achar botões pelo texto e ler coordenadas/números."""
import asyncio
import re
import threading
import unicodedata

import cv2
import numpy as np

try:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter
    AVAILABLE = True
except Exception:  # sem winrt (ou Windows antigo): o resto do bot segue só com templates
    AVAILABLE = False


def norm(s):
    """minúsculas, sem acentos e sem pontuação: 'Confirmar!' == 'confirmar'."""
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9: ]", "", "".join(c for c in s if not unicodedata.combining(c))).strip()


class Word:
    __slots__ = ("text", "x", "y", "w", "h")

    def __init__(self, text, x, y, w, h):
        self.text, self.x, self.y, self.w, self.h = text, x, y, w, h

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2

    def __repr__(self):
        return f"Word({self.text!r} @ {self.x},{self.y})"


class Line(Word):
    __slots__ = ("words",)


class OCR:
    def __init__(self):
        self.enabled = AVAILABLE
        self._engine = None
        self._loop = None
        self._lock = threading.Lock()
        self.language = None

    def languages(self):
        if not AVAILABLE:
            return []
        return [l.language_tag for l in OcrEngine.available_recognizer_languages]

    def set_language(self, tag=None):
        if not AVAILABLE:
            return
        with self._lock:
            eng = OcrEngine.try_create_from_language(Language(tag)) if tag else None
            self._engine = eng or OcrEngine.try_create_from_user_profile_languages()
            self.language = self._engine.recognizer_language.language_tag if self._engine else None

    def _run(self, coro):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    def read(self, bgr, region=None, upscale=None):
        """Retorna [Line] com palavras e caixas em coordenadas do frame original."""
        if not AVAILABLE or bgr is None:
            return []
        if self._engine is None:
            self.set_language()
        ox = oy = 0
        if region:
            h, w = bgr.shape[:2]
            ox, oy = int(region[0] * w), int(region[1] * h)
            bgr = bgr[oy:oy + int(region[3] * h), ox:ox + int(region[2] * w)]
        if bgr.size == 0:
            return []
        # texto pequeno lê muito melhor ampliado: leva a imagem a ~2300 px de largura (rótulos de 8 px como
        # "BASE" sob os ícones só aparecem assim); recortes pequenos sempre ao menos 2x
        h0, w0 = bgr.shape[:2]
        f = upscale or max(2.0 if h0 < 400 else 1.0, min(2.5, 2300 / max(1, w0)))
        f = min(f, OcrEngine.max_image_dimension / max(bgr.shape[:2]))
        img = cv2.resize(bgr, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC) if f != 1.0 else bgr
        bgra = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        h, w = bgra.shape[:2]
        with self._lock:
            dw = DataWriter()
            dw.write_bytes(np.ascontiguousarray(bgra).tobytes())
            sb = SoftwareBitmap.create_copy_from_buffer(dw.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)
            res = self._run(self._engine.recognize_async(sb))
        out = []
        for ln in res.lines:
            words = []
            for wd in ln.words:
                r = wd.bounding_rect
                words.append(Word(wd.text, ox + int(r.x / f), oy + int(r.y / f), int(r.width / f), int(r.height / f)))
            if not words:
                continue
            x0, y0 = min(w.x for w in words), min(w.y for w in words)
            x1, y1 = max(w.x + w.w for w in words), max(w.y + w.h for w in words)
            line = Line(ln.text, x0, y0, x1 - x0, y1 - y0)
            line.words = words
            out.append(line)
        return out

    def text(self, bgr, region=None):
        return "\n".join(l.text for l in self.read(bgr, region))

    def find(self, bgr, keywords, region=None, lines=None):
        """Primeira linha/palavra que contém alguma das palavras-chave (qualquer idioma).
        Retorna (cx, cy, texto, (x, y, w, h)) ou None."""
        keys = [norm(k) for k in keywords if k]
        for ln in (lines if lines is not None else self.read(bgr, region)):
            t = norm(ln.text)
            for k in keys:
                if k and (t == k or (len(k) >= 4 and k in t)):
                    # caixa justa: só as palavras que formam a chave
                    hit = [w for w in ln.words if norm(w.text) and norm(w.text) in k] or ln.words
                    x0, y0 = min(w.x for w in hit), min(w.y for w in hit)
                    x1, y1 = max(w.x + w.w for w in hit), max(w.y + w.h for w in hit)
                    return (x0 + x1) // 2, (y0 + y1) // 2, ln.text, (x0, y0, x1 - x0, y1 - y0)
        return None

    def numbers(self, bgr, region=None):
        return [int(n.replace(".", "").replace(",", "")) for n in
                re.findall(r"\d[\d.,]*", self.text(bgr, region)) if n.replace(".", "").replace(",", "").isdigit()]

    def coords(self, bgr, region=None):
        """Lê 'X:123 Y:456' (ou '#12 X:123 Y:456') -> (x, y) ou None. Só com X e Y explícitos:
        '22,031' (diamantes) não é coordenada."""
        t = self.text(bgr, region).upper().replace("O", "0")
        m = re.search(r"X\s*[:.]\s*(\d{1,4})\D{0,6}Y\s*[:.]\s*(\d{1,4})", t)
        return (int(m.group(1)), int(m.group(2))) if m else None
