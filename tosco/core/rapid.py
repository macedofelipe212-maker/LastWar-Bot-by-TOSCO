"""RapidOCR (PP-OCR em ONNX) para os números do jogo. Num print real do Last War leu todos os cronômetros
("13:26:38", "00:00:52") e números ("107,621,685", "3.00K") que o OCR do Windows errou, em ~11 ms por recorte.
Fica na frente do Tesseract; sem o pacote `rapidocr`, quem chama cai no Tesseract/OCR do Windows."""
import importlib.util
import re
import threading

import cv2
import numpy as np

from . import tesseract

INVALID = -1  # leu um relógio com certeza, mas fora do limite: quem chama NÃO deve tentar "consertar" com outro OCR

_engine = None
_failed = False
error = ""  # motivo da falha ao carregar (mostrado no registro)
_lock = threading.Lock()


def installed():
    """Barato (não carrega nada): o pacote existe? Para a interface, que não pode esperar o carregamento."""
    return importlib.util.find_spec("rapidocr") is not None


def _get():
    """Carrega o motor uma vez e faz uma leitura de aquecimento: o RapidOCR só abre os modelos (detecção e
    reconhecimento) na primeira leitura — sem o aquecimento uma falha de modelo apareceria no meio da escavação.
    None se o pacote/modelos não funcionarem (motivo em `error`)."""
    global _engine, _failed, error
    if _engine is None and not _failed:
        with _lock:
            if _engine is None and not _failed:
                try:
                    import logging
                    from rapidocr import RapidOCR
                    logging.getLogger("RapidOCR").setLevel(logging.ERROR)  # "detection result is empty" a cada recorte
                    eng = RapidOCR()
                    blank = np.full((48, 160, 3), 255, np.uint8)
                    eng(blank, use_cls=False)                    # carrega detecção + reconhecimento
                    eng(blank, use_det=False, use_cls=False)     # e o caminho só-reconhecimento
                    _engine = eng
                except Exception as ex:  # pacote ausente, modelo corrompido/sem download, onnxruntime sem provider…
                    _failed, error = True, f"{type(ex).__name__}: {ex}"[:200]
    return _engine


def available():
    """Carrega (e aquece) o motor se preciso — chamar na thread do motor, não na da interface."""
    return _get() is not None


def read(bgr, rec_only=False):
    """Textos lidos no recorte BGR, na ordem da tela. rec_only: o recorte já é UMA linha (pula a detecção)."""
    eng = _get()
    if eng is None or bgr is None or bgr.size == 0 or min(bgr.shape[:2]) < 4:
        return []
    img = bgr
    if img.shape[0] < 24:  # texto muito baixo: o reconhecedor quer ~32 px de altura
        f = 32 / img.shape[0]
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    try:
        with _lock:  # a sessão ONNX é compartilhada entre a thread do motor e a interface
            r = eng(img, use_det=not rec_only, use_cls=False)
    except Exception:
        return []
    return [t for t in (getattr(r, "txts", None) or ()) if t]


# ESTRITO: nem dígito nem ':' colado antes/depois — '1:2:03', ':02:03' e '01:23:4' (dígito perdido ou cortado)
# não casam em vez de virarem um tempo curto errado
_CLOCK = re.compile(r"(?<![\d:])(\d{1,2})\s*:\s*(\d{2})(?:\s*:\s*(\d{2}))?(?![\d:])")


def _clock(text):
    """'1:02:03' / '00:52' → segundos; relógio fora do limite (ex.: '13:26:38', de evento) → INVALID;
    sem relógio inteiro → None."""
    m = _CLOCK.search(text or "")
    if not m:
        return None
    a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
    if b >= 60 or (c is not None and int(c) >= 60):
        return INVALID
    v = a * 3600 + b * 60 + int(c) if c is not None else a * 60 + b
    return v if 0 <= v <= tesseract.MAX_TIMER else INVALID


def _read_clock(bgr):
    """Um recorte → segundos, INVALID ou None. Com ':' a leitura é estrita; só sem ':' (o reconhecedor perdeu os
    dois-pontos) vale o conserto de dígitos do Tesseract."""
    texts = read(bgr, rec_only=True) or read(bgr)
    if not texts:
        return None
    if any(":" in t for t in texts):
        vals = [_clock(t) for t in texts if ":" in t]
        good = [v for v in vals if v is not None and v != INVALID]
        return good[0] if good else (INVALID if INVALID in vals else None)
    return tesseract.parse_timer(" ".join(texts))


def read_timer_box(frame, box):
    """Cronômetro na caixa (x, y, w, h centro) do frame, lido em DOIS recortes com pixels reais da tela: o justo
    e um com margem (a caixa da IA às vezes vem curta e corta o primeiro dígito — '1:00:08' viraria ':00:08').
    Se discordarem vale o MAIOR: um dígito cortado só encurta o tempo, e tempo curto demais faz o bot começar a
    tocar antes da hora. Devolve segundos, INVALID ou None."""
    if frame is None or not available():
        return None
    x, y, w, h = box
    H, W = frame.shape[:2]
    vals = []
    for mx, my in ((2, 2), (int(w * 0.15) + 3, int(h * 0.3) + 3)):
        crop = frame[max(0, y - h // 2 - my):min(H, y + h // 2 + my), max(0, x - w // 2 - mx):min(W, x + w // 2 + mx)]
        vals.append(_read_clock(crop))
    good = [v for v in vals if v is not None and v != INVALID]
    if good:
        return max(good)
    return INVALID if INVALID in vals else None


def read_timer_in_text(bgr):
    """Cronômetro numa região MAIOR (a aba inteira do popup): só aceita relógios inteiros — evita que '87%' vire
    tempo. Devolve segundos, INVALID ou None."""
    if bgr is None or bgr.size == 0 or not available():
        return None
    seen_invalid = False
    for t in read(bgr):
        v = _clock(t)
        if v == INVALID:
            seen_invalid = True
        elif v is not None:
            return v
    return INVALID if seen_invalid else None


def read_int(bgr, lo=0, hi=10 ** 9):
    """'107,621,685' / '35.785' → int (sufixos K/M não convertidos: use parse próprio para isso)."""
    for t in read(bgr, rec_only=True) or read(bgr):
        d = re.sub(r"[^\d]", "", t)
        if d and lo <= int(d) <= hi:
            return int(d)
    return None
