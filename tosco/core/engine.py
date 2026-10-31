"""Motor: thread de execução, agendador, watchdog, pausas humanas e a API usada pelas tarefas."""
import datetime as dt
import os
import random
import subprocess
import threading
import time
import traceback

from . import catalog, rapid, screens, winapi
from .backends import make_backend
from .config import Counters
from .ocr import OCR, norm
from .paths import LOG_DIR
from .targets import (LABEL_UNDER_ICON, OVERLAY_CLASSES, TASK_PRIORITY, TEXT_TARGETS, URGENT_SIGNALS,
                      YOLO_TARGETS)
from .telegram import Telegram
from .vision import Vision
from .yolo import Yolo

DAYS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


class StopRequested(Exception):
    pass


class TaskTimeout(Exception):
    """A tarefa passou do tempo máximo: o motor a interrompe e volta à tela principal."""


# Alvos que vivem na faixa do chat (ou logo acima dela): não são filtrados na tela principal
CHAT_BAND_OK = ("btn_chat", "gift_alert", "dig_alert", "fire_alert", "btn_to_world", "btn_to_base")
# Abas do chat aberto (ficam no topo do painel); a caixa de digitar (chat_input) não entra: ela fica embaixo
# e é sinal confiável de chat aberto
CHAT_TABS = ("chat_ally", "chat_world", "chat_moment", "chat_private")


class Field:
    """Campo de configuração de uma tarefa; a UI gera o formulário a partir disto."""

    def __init__(self, key, label, kind="bool", default=False, options=None, minimum=0, maximum=99999, hint=""):
        self.key, self.label, self.kind, self.default = key, label, kind, default
        self.options, self.minimum, self.maximum, self.hint = options or [], minimum, maximum, hint


class Card:
    """Um cartão na página do módulo: chave opcional (toggle), campos do painel lateral e resumo em verde.
    summary: texto com {campo} (ex.: "esquadrão {squad_order}") ou função(s) -> texto."""

    def __init__(self, title, icon, desc, toggle=None, fields=(), summary=None):
        self.title, self.icon, self.desc = title, icon, desc
        self.toggle, self.fields, self.summary = toggle, list(fields), summary


class Task:
    id = "task"
    cards = None        # [(seção, [Card])]; None = gerado a partir dos campos
    main_capable = False  # pode ser a tarefa principal (roda sem parar)
    name = "Tarefa"
    icon = "◆"
    group = "Geral"
    description = ""
    default_enabled = False
    default_interval = 30.0  # minutos
    templates = []           # [(nome, o que capturar)]
    fields = []
    max_minutes = 10         # tempo máximo de uma execução (0 = sem limite); passou → interrompe e volta

    def budget_min(self, s):
        return self.max_minutes

    def defaults(self):
        d = {"enabled": self.default_enabled, "interval_min": self.default_interval,
             "days": ",".join(DAYS), "hours": "00:00-23:59"}
        d.update({f.key: f.default for f in self.fields})
        return d

    def run(self, ctx, s):
        raise NotImplementedError


def in_window(days, hours, now=None):
    """days 'seg,ter,...' e hours 'HH:MM-HH:MM' (pode virar a meia-noite)."""
    now = now or dt.datetime.now()
    allowed = [d.strip().lower()[:3] for d in str(days).split(",") if d.strip()]
    if allowed and DAYS[now.weekday()] not in allowed:
        return False
    try:
        a, b = [dt.datetime.strptime(x.strip(), "%H:%M").time() for x in str(hours).split("-")]
    except ValueError:
        return True
    t = now.time()
    return a <= t <= b if a <= b else (t >= a or t <= b)


class Context:
    """Tudo o que uma tarefa pode fazer no jogo."""

    def __init__(self, engine):
        self.e = engine
        self.vision, self.ocr, self.counters = engine.vision, engine.ocr, engine.counters
        self._warned = set()
        self._frame = None
        self._frame_t = 0
        self._lines = None
        self._where = None          # (frame, tela) — cache do reconhecedor de telas
        self._guard_cache = {}      # célula do toque -> (hora, motivo ou None)
        self.deadline = None        # hora limite da tarefa atual (TaskTimeout)
        self.task_name = ""

    @property
    def cfg(self):
        return self.e.cfg.data

    # --- controle -------------------------------------------------------
    def check(self):
        while self.e.paused and not self.e.stop_flag.is_set():
            time.sleep(0.1)
        if self.e.stop_flag.is_set():
            raise StopRequested()
        self._user_guard()
        if self.deadline and time.time() > self.deadline:
            raise TaskTimeout()  # repete a cada check até o motor limpar o prazo (um except da tarefa não engole)

    def _user_guard(self):
        """Você mexeu no mouse/teclado → o TOSCO solta o controle e espera N s sem mexida para voltar
        (o mouse é o mesmo: os dois juntos se atrapalham). O prazo da tarefa é estendido pela pausa."""
        if not self.cfg.get("pause_on_user", True) or self.e.backend.name != "pc":
            return
        age = winapi.user_input_age()
        if age is None:
            return
        wait = float(self.cfg.get("user_resume_s", 20))
        if age >= wait:
            return
        t0 = time.time()
        self.log(f"✋ Você está usando o PC — TOSCO pausado (volta após {wait:.0f} s sem mexer)")
        self.e.current = "pausado: você está usando o PC"
        self.e._emit()
        while not self.e.stop_flag.is_set():
            age = winapi.user_input_age()
            if age is None or age >= wait:
                break
            time.sleep(0.5)
        if self.e.stop_flag.is_set():
            raise StopRequested()
        if self.deadline:
            self.deadline += time.time() - t0
        self._frame = None  # a tela mudou enquanto você usava
        self._guard_cache.clear()
        self.log("▶ Retomando (sem mexida há alguns segundos)")
        self.e.current = self.task_name or "aguardando"
        self.e._emit()

    def sleep(self, seconds, human=True):
        if human:
            seconds *= float(self.cfg["human"].get("delay_factor", 1.0)) * random.uniform(0.9, 1.25)
        end = time.time() + seconds
        while time.time() < end:
            self.check()
            time.sleep(min(0.05, max(0, end - time.time())))

    def log(self, msg, level="info"):
        self.e.log(msg, level)

    def notify(self, msg):
        self.e.telegram.send(f"[TOSCO] {msg}")

    def warn_once(self, key, msg):
        if key not in self._warned:
            self._warned.add(key)
            self.log(msg, "warn")

    # --- visão ----------------------------------------------------------
    def frame(self, fresh=True):
        self.check()
        if not fresh and self._frame is not None and time.time() - self._frame_t < 0.25:
            return self._frame
        img = self.e.capture()
        if img is None:
            raise RuntimeError("jogo não encontrado")
        self._frame, self._frame_t, self._lines = img, time.time(), None
        return img

    def lines(self, frame=None):
        """OCR do frame atual (com cache por frame)."""
        if frame is not None and frame is not self._frame:
            return self.ocr.read(frame)
        if self._lines is None:
            self._lines = self.ocr.read(self._frame if self._frame is not None else self.frame())
        return self._lines

    def ocr_on(self):
        return self.cfg.get("ocr_enabled", True) and self.ocr.enabled

    def ai_on(self, name=None):
        if not self.cfg.get("ai_enabled", True) or not self.e.yolo.available():
            return False
        return name is None or name in YOLO_TARGETS

    def ai(self, name, frame=None, region=None):
        """Detecções da IA para um alvo do TOSCO: [(x, y, score, w, h)], melhor primeiro.
        region = (fx, fy, fw, fh) em frações da tela, como nas imagens."""
        if not self.ai_on(name):
            return []
        frame = self.frame(fresh=False) if frame is None else frame
        # corte baixo aqui: cada classe aplica a sua confiança (algumas valem a partir de 0,20 — barra de vigor)
        det = self.e.yolo.detect(frame, self.cfg.get("ai_model", "preciso"), conf=0.2)
        fh, fw = frame.shape[:2]
        out = []
        for c in YOLO_TARGETS[name]:
            cls, fixed = c if isinstance(c, tuple) else (c, None)
            thr = catalog.threshold(cls, self.cfg, fixed)  # seu ajuste na tela da IA > fixo da tarefa > padrão
            for x, y, sc, bw, bh in det.get(cls, []):
                if sc < thr:
                    continue
                if region and not (region[0] <= x / fw <= region[0] + region[2]
                                   and region[1] <= y / fh <= region[1] + region[3]):
                    continue
                out.append((x, y, sc, bw, bh))
            if out:  # classes em ordem de preferência
                break
        return out

    def find(self, name, threshold=None, region=None, frame=None, text=True, ai=True):
        """Imagem capturada primeiro; depois a IA; por fim o texto (OCR). Retorna (x, y) ou None."""
        threshold = threshold or float(self.cfg.get("match_threshold", 0.85))
        frame = self.frame() if frame is None else frame
        band = self._band_filter(name, frame)
        if self.vision.has(name):
            hit = self.vision.find(frame, name, threshold, region)
            if hit and band and band(hit[0], hit[1]):
                hit = next((h for h in self.vision.find_all(frame, name, threshold, region)
                            if not band(h[0], h[1])), None)
            if hit:
                return hit[0], hit[1]
        hits = self.ai(name, frame, region) if ai else []
        if band:
            hits = [h for h in hits if not band(h[0], h[1])]
        if hits:
            return hits[0][0], hits[0][1]
        keys = TEXT_TARGETS.get(name)
        if text and keys and self.ocr_on():
            lines = self.lines(frame) if region is None else None
            if band and lines:
                lines = [ln for ln in lines if not band(ln.x + ln.w // 2, ln.y + ln.h // 2)]
            hit = self.ocr.find(frame, keys, lines=lines, region=region)
            if hit:
                x, y, box = hit[0], hit[1], hit[3]
                up = int(LABEL_UNDER_ICON.get(name, 0) * frame.shape[0])
                if up:  # rótulo sob o ícone: o alvo é o ícone acima; a imagem aprendida pega ícone + rótulo
                    y -= up
                if self.cfg.get("auto_learn") and not self.vision.has(name):
                    self._learn(name, frame, box, center=(x, y) if up else None)
                return x, y
        if not self.vision.has(name) and not keys and not self.ai_on(name) and name not in ("hud_base", "hud_world"):
            self.warn_once(name, f"template '{name}' não capturado — passo ignorado (use o Estúdio ou F8)")
        return None

    def _band_filter(self, name, frame):
        """Na tela principal, a faixa do chat embaixo pega o toque (abre o chat) e o texto dela engana o OCR:
        retorna uma função (x, y) -> True se o ponto cai nela, ou None quando não há o que filtrar."""
        if name.startswith("chat_") or name in CHAT_BAND_OK or not self.ai_on() or not self.on_main(frame):
            return None
        return lambda x, y: screens.in_chat_band(x, y, frame.shape)

    def knows(self, name):
        """O TOSCO tem como achar este alvo (imagem, IA ou texto)?"""
        return self.vision.has(name) or self.ai_on(name) or bool(TEXT_TARGETS.get(name) and self.ocr_on())

    def _learn(self, name, frame, box, center=None):
        """Recorta o botão achado pelo texto e salva como imagem. center: ponto de toque quando não é o meio
        do texto (rótulo sob ícone) — o recorte é centrado nele, cobrindo ícone e rótulo, para o template
        depois bater exatamente no ponto certo."""
        x, y, w, h = box
        if center is None:
            pad = max(6, h // 2)
            x0, y0, x1, y1 = x - pad, y - pad, x + w + pad, y + h + pad
        else:
            hh = (y + h + 3) - center[1]
            hw = max(w // 2 + 4, hh)
            x0, y0, x1, y1 = center[0] - hw, center[1] - hh, center[0] + hw, center[1] + hh
        x0, y0 = max(0, x0), max(0, y0)
        crop = frame[y0:y1, x0:x1].copy()
        if crop.shape[0] >= 10 and crop.shape[1] >= 10:
            self.vision.save(name, crop, frame.shape[1], source_height=frame.shape[0])
            self.log(f"▣ Aprendi o botão '{name}' sozinho pelo texto")

    def find_text(self, keywords, region=None):
        if not self.ocr_on():
            return None
        frame = self.frame()
        hit = self.ocr.find(frame, keywords, region=region, lines=None if region else self.lines(frame))
        return (hit[0], hit[1]) if hit else None

    def find_all(self, name, threshold=None, region=None):
        threshold = threshold or float(self.cfg.get("match_threshold", 0.85))
        frame = self.frame()
        band = self._band_filter(name, frame) or (lambda x, y: False)
        if self.vision.has(name):
            hits = [(h[0], h[1]) for h in self.vision.find_all(frame, name, threshold, region)
                    if not band(h[0], h[1])]
            if hits or not self.ai_on(name):
                return hits
        if self.ai_on(name):
            return [(h[0], h[1]) for h in self.ai(name, frame, region) if not band(h[0], h[1])]
        self.warn_once(name, f"template '{name}' não capturado — passo ignorado (use o Estúdio ou F8)")
        return []

    def exists(self, name, threshold=None, region=None):
        return self.find(name, threshold, region) is not None

    def wait_for(self, name, timeout=5.0, threshold=None, region=None):
        if not self.knows(name):
            self.warn_once(name, f"template '{name}' não capturado — passo ignorado (use o Estúdio ou F8)")
            return None
        end = time.time() + timeout
        while True:
            hit = self.find(name, threshold, region)
            if hit or time.time() >= end:
                return hit
            self.sleep(0.3, human=False)

    def read_text(self, region=None):
        return self.ocr.text(self.frame(), region) if self.ocr_on() else ""

    def read_coords(self, region):
        return self.ocr.coords(self.frame(), region) if self.ocr_on() else None

    # --- entrada --------------------------------------------------------
    def tap_xy(self, x, y, spread=None, guard=True):
        """Toque em coordenadas do frame, com dispersão humana em volta do ponto. Retorna False (sem tocar) se
        a proteção achou compra/diamante/'terminar agora' em volta do ponto."""
        self.check()
        if guard:
            why = self.danger_at(x, y)
            if why:
                self.e.stats["blocked"] = self.e.stats.get("blocked", 0) + 1
                self.warn_once(f"guard:{x // 60}:{y // 60}:{why}",
                               f"⛔ Toque bloqueado em ({x}, {y}): '{why}' perto do botão (proteção da conta)")
                return False
        sp = int(6 * float(self.cfg["human"].get("tap_spread", 0.25)) * 4) if spread is None else spread
        self.e.backend.tap(x + random.randint(-sp, sp), y + random.randint(-sp, sp))
        self.e.stats["taps"] += 1
        return True

    def danger_at(self, x, y):
        """Motivo para NÃO tocar no ponto (botão de compra da IA, preço ou texto proibido num raio de ~90 px
        na escala 1057), ou None. Resultado guardado 5 s por região — toques repetidos não releem."""
        if not self.cfg.get("guard_clicks", True):
            return None
        f = self._frame if self._frame is not None else self.frame()
        why = screens.danger_class(self.dets(f), x, y) if self.ai_on() else None
        if why:
            return why
        if not self.ocr_on():
            return None
        cell, now = (x // 40, y // 40), time.time()
        hit = self._guard_cache.get(cell)
        if hit and now - hit[0] < 5:
            return hit[1]
        h, w = f.shape[:2]
        r = int(90 * h / 1057)
        x0, y0 = max(0, x - r), max(0, y - r)
        region = (x0 / w, y0 / h, (min(w, x + r) - x0) / w, (min(h, y + r) - y0) / h)
        why = screens.danger_text(self.ocr.text(f, region))
        self._guard_cache[cell] = (now, why)
        if len(self._guard_cache) > 200:
            self._guard_cache = {k: v for k, v in self._guard_cache.items() if now - v[0] < 5}
        return why

    def tap_rel(self, fx, fy):
        f = self._frame if self._frame is not None else self.frame()
        self.tap_xy(int(f.shape[1] * fx), int(f.shape[0] * fy))

    def tap(self, name, timeout=3.0, threshold=None, region=None, after=0.6):
        hit = self.wait_for(name, timeout, threshold, region)
        if not hit or not self.tap_xy(*hit):
            return False
        self.sleep(after)
        return True

    def tap_text(self, keywords, timeout=3.0, region=None, after=0.6):
        end = time.time() + timeout
        while True:
            hit = self.find_text(keywords, region)
            if hit:
                if not self.tap_xy(*hit):
                    return False
                self.sleep(after)
                return True
            if time.time() >= end:
                return False
            self.sleep(0.4, human=False)

    def drag_rel(self, fx1, fy1, fx2, fy2, duration=0.45):
        f = self._frame if self._frame is not None else self.frame()
        w, h = f.shape[1], f.shape[0]
        self.check()
        self.e.backend.drag(int(w * fx1), int(h * fy1), int(w * fx2), int(h * fy2), duration)
        self._frame = None

    def scroll(self, clicks, fx=0.5, fy=0.5):
        f = self._frame if self._frame is not None else self.frame()
        self.e.backend.scroll(int(f.shape[1] * fx), int(f.shape[0] * fy), clicks)

    def key(self, name):
        self.check()
        self.e.backend.key(name)

    def back(self, times=1):
        for _ in range(times):
            self.key("esc")
            self.sleep(0.45)

    def type(self, text):
        self.e.backend.type(text)

    # --- IA: leitura da tela inteira ------------------------------------
    def dets(self, frame=None, conf=0.3):
        """Todas as detecções da IA no frame: {classe: [(x, y, score, w, h)]} (vazio sem IA)."""
        if not self.ai_on():
            return {}
        frame = self.frame(fresh=False) if frame is None else frame
        return self.e.yolo.detect(frame, self.cfg.get("ai_model", "preciso"), conf)

    def seen(self, cls, min_score=0.5, frame=None):
        """Melhor detecção da classe da IA (x, y, score, w, h) acima do limiar, ou None."""
        hits = [d for d in self.dets(frame).get(cls, []) if d[2] >= min_score]
        return hits[0] if hits else None

    def ai_wait(self, name, timeout=3.0, base=None, floor=0.25, steps=4):
        """Poll DEGRESSIVO: recaptura e aceita um limiar um pouco menor a cada tentativa (animações e transições
        baixam a confiança). Retorna (x, y, score, w, h) ou None."""
        if not self.ai_on(name):
            hit = self.wait_for(name, timeout)
            return (hit[0], hit[1], 1.0, 0, 0) if hit else None
        def ladder(start):
            lo = min(floor, start)  # classe com padrão abaixo do piso (ex.: barra de vigor 0,20) começa nele
            return [max(lo, start - k * (start - lo) / max(1, steps - 1)) for k in range(steps)]

        # a escada começa na confiança de CADA classe (seu ajuste > fixo da tarefa > padrão do catálogo)
        ladders = []
        for c in YOLO_TARGETS[name]:
            cls, fixed = c if isinstance(c, tuple) else (c, None)
            ladders.append((cls, ladder(base or catalog.threshold(cls, self.cfg, fixed))))
        low = min(min(l) for _, l in ladders)
        end, i = time.time() + timeout, 0
        while True:
            f = self.frame()
            for cls, thr in ladders:
                for d in self.dets(f, conf=low).get(cls, []):
                    if d[2] >= thr[min(i, len(thr) - 1)]:
                        return d
            i += 1
            if time.time() >= end:
                return None
            self.sleep(0.3, human=False)

    # --- telas: onde estou / esperar a tela certa -----------------------
    def where(self, frame=None):
        """Nome da tela atual (core/screens.py): 'base', 'world', 'march', 'chat', 'confirm', 'panel',
        'loading', 'other_device', 'connection_lost', 'exit_game', 'unknown'…"""
        f = self.frame() if frame is None else frame
        if self._where and self._where[0] is f:
            return self._where[1]
        d = self.dets(f)
        main = self.on_main(f)
        # tela principal limpa pela IA: o OCR só seria preciso para avisos de tela cheia, que escondem a HUD
        lines = [] if main or not self.ocr_on() else self.lines(f)
        sc = main or screens.detect(lines, d, f.shape)
        self._where = (f, sc)
        return sc

    def expect(self, names, timeout=5.0, label=""):
        """Espera uma das telas (nome ou tupla). Retorna o nome alcançado ou None (e registra o passo que não
        chegou — nunca supor que o toque funcionou)."""
        names = (names,) if isinstance(names, str) else tuple(names)
        end = time.time() + timeout
        sc = None
        while True:
            sc = self.where(self.frame())
            if sc in names:
                return sc
            if time.time() >= end:
                break
            self.sleep(0.35, human=False)
        if label:
            self.log(f"↯ {self.task_name or 'passo'}: '{label}' não levou a {'/'.join(names)} (tela: {sc})", "warn")
        return None

    def step(self, label, action, expect, timeout=5.0, tries=2):
        """Executa a ação (função sem argumentos) e confirma a tela esperada; tenta de novo uma vez.
        Retorna a tela alcançada ou None."""
        for i in range(max(1, tries)):
            if action() is False:
                return None
            sc = self.expect(expect, timeout, label if i == tries - 1 else "")
            if sc:
                return sc
        return None

    def handle_blocking(self, sc):
        """Telas que pedem espera em vez de toque. True se tratou (o chamador deve olhar a tela de novo)."""
        if sc in screens.WAIT_SCREENS:
            self.warn_once(f"wait:{sc}", "Jogo carregando/em manutenção — aguardando")
            self.sleep(5 if sc == "loading" else 60, human=False)
            return True
        if sc == "other_device":
            mins = float(self.cfg.get("relog_wait_min", 10))
            self.log(f"📱 Conta aberta em outro aparelho — volto em {mins:.0f} min", "warn")
            self.notify(f"conta aberta em outro aparelho, reconecto em {mins:.0f} min")
            self.sleep(mins * 60, human=False)
            if not self.tap("btn_reconnect", 2, after=5) and not self.tap("btn_confirm", 2, after=5):
                self.tap_rel(0.5, 0.62)
                self.sleep(5)
            return True
        return False

    # --- navegação ------------------------------------------------------
    def on_main(self, frame=None):
        """Na tela principal (base ou mapa) SEM nada aberto por cima. 'base' / 'world' / None."""
        f = self.frame(fresh=False) if frame is None else frame
        d = self.dets(f)
        if not d:
            return None
        for c in OVERLAY_CLASSES:
            hits = d.get(c)
            if not hits:
                continue
            # a prévia do chat na faixa de baixo da tela principal pode ser lida como uma aba do chat; as abas de
            # verdade ficam no TOPO do painel aberto. Aba só conta se alguma detecção estiver fora da faixa.
            if c in CHAT_TABS and all(screens.in_chat_band(h[0], h[1], f.shape) for h in hits):
                continue
            return None
        if "World" in d:  # botão Mundo visível = estamos na base
            return "base"
        if "Base" in d:
            return "world"
        return None

    def press_back(self):
        """UMA ação de voltar, olhando a tela: Return > Cancelar > X > ESC."""
        f = self.frame()
        for name in ("btn_back", "btn_exit_cancel", "btn_close"):
            hit = self.find(name, frame=f, text=False)
            if hit:
                # o painel pode fechar sozinho entre ver e tocar: confere de novo numa imagem nova, no mesmo
                # lugar — senão o toque cai no que está embaixo (ex.: a faixa do chat, que abre o chat)
                again = self.find(name, frame=self.frame(), text=False)
                if not again or abs(again[0] - hit[0]) > 30 or abs(again[1] - hit[1]) > 30:
                    return "gone"
                if self.on_main(self._frame):
                    return "main"
                self.tap_xy(*again, spread=2)
                self.sleep(0.7)
                return name
        self.key("esc")
        self.sleep(0.6)
        return "esc"

    def lone_confirm(self, frame=None):
        """Popup que é só um aviso (Confirmar sem Cancelar, X nem Return) → confirma. Confirmação que gasta algo
        sempre tem Cancelar, então nunca é clicada aqui."""
        d = self.dets(frame)
        if "confirm_popup" in d and not any(c in d for c in ("cancel_popup", "close_btn", "Return")):
            x, y = d["confirm_popup"][0][:2]
            self.tap_xy(x, y, spread=2)
            self.sleep(0.8)
            return True
        return False

    def exit_to_main(self, max_steps=6):
        """Saída VERIFICADA para a tela principal, de qualquer tela: percebe → já está? → senão UMA ação de voltar
        → repete. Preso → recuperação forte (que, repetida, relança o jogo)."""
        for _ in range(max_steps):
            f = self.frame()
            if self.find("dlg_exit_game", frame=f):
                if not self.tap("btn_exit_cancel", 1.0):
                    self.key("esc")
                    self.sleep(0.5)
                continue
            sc = self.on_main(f)
            if sc:
                self.e.recover_streak = 0
                return sc
            if self.handle_blocking(self.where(f)):
                continue
            if self.lone_confirm(f):
                continue
            self.press_back()
        return self.recover_to_safe()

    def recover_to_safe(self):
        """Recuperação forte: Return → Cancelar → ESC×5 (cancelando 'Sair do jogo?') → Base/Mundo.
        Várias seguidas sem voltar ao principal → relança o jogo."""
        self.e.recover_streak += 1
        self.log(f"↺ Recuperando a tela ({self.e.recover_streak}ª vez seguida)", "warn")
        for name in ("btn_back", "btn_exit_cancel", "btn_close"):
            hit = self.find(name, text=False)
            if hit:
                self.tap_xy(*hit, spread=2)
                self.sleep(0.7)
        for _ in range(5):
            if self.on_main():
                break
            self.key("esc")
            self.sleep(0.5)
            if self.find("dlg_exit_game"):
                self.tap("btn_exit_cancel", 1.0)
                break
        sc = self.on_main()
        if not sc:
            for name in ("btn_to_world", "btn_to_base"):
                if self.tap(name, 0.8, after=1.5):
                    break
            sc = self.on_main()
        if not sc:
            # truque da Loja (piggy-lastwar-bot): sem Base/Mundo mas com o ícone da Loja na HUD, abrir a Loja e
            # sair dela sempre volta à tela principal. Só abre e sai — nada é tocado dentro da Loja.
            mall = self.seen("Mall", 0.6)
            if mall:
                self.log("↺ Recuperação: abrindo e fechando a Loja para voltar à tela principal")
                self.tap_xy(mall[0], mall[1], spread=2, guard=False)
                self.sleep(1.8)
                for _ in range(3):
                    if self.on_main():
                        break
                    if not self.tap("btn_back", 1.0, after=0.8) and not self.tap("btn_close", 0.8, after=0.8):
                        self.key("esc")
                        self.sleep(0.8)
                sc = self.on_main()
        if sc:
            self.e.recover_streak = 0
        elif self.e.recover_streak >= 4:
            self.e.request_restart("preso numa tela desconhecida")
        return sc

    def screen(self):
        """'base', 'world', 'exit' (diálogo sair do jogo) ou None."""
        f = self.frame()
        if self.find("dlg_exit_game", frame=f):
            return "exit"
        if self.ai_on():
            return self.on_main(f)
        # painéis do jogo abrem por cima sem esconder o botão MUNDO/BASE: seta de voltar ou X = ainda não é a tela
        # (a IA só vale para o X: a classe "Return" dela também aparece na tela principal)
        if self.vision.has("btn_back") and self.find("btn_back", frame=f, text=False, ai=False):
            return None
        if (self.vision.has("btn_close") or self.ai_on("btn_close")) and self.find("btn_close", frame=f, text=False):
            return None
        if self.find("hud_base", frame=f, text=False) or self.find("btn_to_world", frame=f):
            return "base"
        if self.find("hud_world", frame=f, text=False) or self.find("btn_to_base", frame=f):
            return "world"
        return None

    def can_navigate(self):
        return self.ocr_on() or self.ai_on() or self.vision.has("hud_base") or self.vision.has("hud_world")

    def go_home(self, max_esc=6):
        """Fecha janelas com ESC até reconhecer a base ou o mapa. Nunca aperta ESC às cegas:
        na tela inicial o ESC abre 'Sair do jogo?', que é detectado e cancelado."""
        if not self.can_navigate():
            self.warn_once("go_home", "sem OCR e sem 'hud_base'/'hud_world' — o TOSCO não navega")
            return None
        if self.ai_on():
            return self.exit_to_main(max_esc)
        for _ in range(max_esc):
            sc = self.screen()
            if sc == "exit":
                if not self.tap("btn_exit_cancel", 1.0):
                    self.key("esc")
                    self.sleep(0.5)
                continue
            if sc:
                return sc
            self.back()
        return self.screen()

    def to_base(self):
        if self.go_home() == "world":
            self.tap("btn_to_base", 2, after=1.6)
        return self.screen() == "base"

    def to_world(self):
        if self.go_home() == "base":
            self.tap("btn_to_world", 2, after=1.8)
        return self.screen() == "world"


class Engine:
    def __init__(self, cfg, tasks, log_cb=None, state_cb=None):
        self.cfg, self.tasks = cfg, tasks
        self.vision = Vision()
        self.yolo = Yolo()
        self.ocr = OCR()
        self.ocr.set_language(cfg.data.get("ocr_language") or None)
        self.counters = Counters(cfg)
        self.telegram = Telegram(cfg)
        self.backend = make_backend(cfg)
        self.log_cb, self.state_cb = log_cb, state_cb
        self.stop_flag = threading.Event()
        self.paused = False
        self.thread = None
        self.current = "—"
        self.last_frame = None
        self.last_run = {}
        self.queue = []          # módulos pedidos com "executar agora"
        self.only = None         # se definido, roda só estes módulos (agenda / scanner)
        self.started_at = None
        self.stats = {"taps": 0, "runs": 0, "errors": 0}
        self.lines = []
        self._next_break = None
        self.clicker = None
        self.recover_streak = 0      # recuperações fortes seguidas sem voltar à tela principal
        self._restart_reason = None  # pedido de relançar o jogo
        self._off_main = 0           # ciclos ociosos fora da tela principal (guarda anti-travamento)

    def request_restart(self, reason):
        self._restart_reason = reason

    def reload_backend(self):
        self.backend = make_backend(self.cfg)

    # --- estado ---------------------------------------------------------
    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def state(self):
        if not self.running:
            return "PARADO"
        return "PAUSADO" if self.paused else "ATIVO"

    def log(self, msg, level="info"):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.lines = (self.lines + [line])[-300:]
        if self.log_cb:
            self.log_cb(line, level)
        if self.cfg.data.get("logging_enabled", True):
            try:
                with open(os.path.join(LOG_DIR, time.strftime("log_%Y-%m-%d.txt")), "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
        if level == "error" and self.cfg.data["telegram"].get("notify_errors"):
            self.telegram.send(f"[TOSCO] {msg}")

    def _emit(self):
        if self.state_cb:
            self.state_cb()

    def capture(self):
        try:
            img = self.backend.capture()
        except Exception as ex:
            self.log(f"captura falhou: {ex}", "warn")
            img = None
        if img is not None:
            self.last_frame = img
        return img

    # --- comandos -------------------------------------------------------
    def start(self, oneshot=False):
        """oneshot: executa só a fila (executar agora / ações avulsas) e para sozinho."""
        if self.running:
            return
        self.only = "oneshot" if oneshot else None
        self.stop_flag.clear()
        self.paused = False
        self.started_at = time.time()
        winapi._mark()  # o clique em "Iniciar" não conta como você usando o PC
        self._schedule_break()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        if not oneshot:
            self.log("▶ Motor iniciado")
        self._emit()

    def stop(self):
        if self.running:
            self.stop_flag.set()
            self.log("■ Parada solicitada")
        self.paused = False
        if self.clicker:
            self.clicker.stop()
        self._emit()

    def pause(self):
        if self.running and not self.paused:
            self.paused = True
            self.log("❚❚ Pausado")
            self._emit()

    def resume(self):
        if self.running and self.paused:
            self.paused = False
            self.log("▶ Retomado")
            self._emit()

    def run_now(self, task_id):
        """Executa um módulo já. Com o motor parado, roda só ele e para."""
        if task_id not in self.queue:
            self.queue.append(task_id)
        if not self.running:
            self.start(oneshot=True)

    def run_job(self, name, fn):
        """Ação avulsa fn(ctx) — ex.: 'Ir' para coordenada, calibrar o scanner."""
        self.queue.append((name, fn))
        if not self.running:
            self.start(oneshot=True)

    def task_by_id(self, task_id):
        return next((t for t in self.tasks if t.id == task_id), None)

    # --- laço principal -------------------------------------------------
    def _schedule_break(self):
        h = self.cfg.data["human"]
        self._next_break = time.time() + float(h.get("break_every_min", 90)) * 60 * random.uniform(0.75, 1.25)

    def _due(self):
        now = time.time()
        due = []
        while self.queue:
            item = self.queue.pop(0)
            t = item if isinstance(item, tuple) else self.task_by_id(item)
            if t:
                due.append(t)
        if self.only == "oneshot":
            return due
        main = self.main_task()
        for t in self.tasks:
            if t in due or t is main:
                continue
            s = self.cfg.task(t.id, t.defaults())
            if not s["enabled"] or not in_window(s.get("days", ""), s.get("hours", "")):
                continue
            last = self.last_run.get(t.id)
            if last is None or now - last >= float(s["interval_min"]) * 60:
                due.append(t)
        # a tarefa principal roda em todo ciclo; as extras entram nos intervalos
        if main and main not in due:
            s = self.cfg.task(main.id, main.defaults())
            if in_window(s.get("days", ""), s.get("hours", "")):
                due.append(main)
        # mais urgente primeiro (escavação 1 … ajuda da aliança 100); ações avulsas na frente
        due.sort(key=lambda t: -1 if isinstance(t, tuple) else TASK_PRIORITY.get(t.id, 50))
        return due

    def main_task(self):
        """A única tarefa contínua (Escavação, Zumbis Dourados ou Mobilizações); None = só extras."""
        return self.task_by_id(self.cfg.data.get("main_task") or "")

    def _watchdog(self, ctx):
        if self.counters.check_reset():
            self.log("🌅 Horário de reset — contadores diários zerados")
        if not (self.backend.ready(restore=True) if self.backend.name == "pc" else self.backend.ready()):
            exe = self.cfg.data.get("game_exe_path")
            if self.backend.name == "pc" and exe and os.path.exists(exe) and not winapi.find_window(
                    self.cfg.data["game_window_title"]):
                self.log("Jogo fechado — reabrindo…", "warn")
                self.telegram.send("[TOSCO] jogo fechado/crash, reabrindo")
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
                ctx.sleep(float(self.cfg.data.get("restart_wait_seconds", 90)), human=False)
                self.backend.prepare(self.log)
            else:
                ctx.warn_once("nogame", "Jogo não encontrado — aguardando (confira SISTEMA)")
                ctx.sleep(10, human=False)
            return False
        ctx._warned.discard("nogame")
        if self._restart_reason:
            self._restart_game(ctx, self._restart_reason)
            return False
        f = ctx.frame()
        # modo cego: imagem toda preta (PC dormindo, sessão bloqueada, jogo sem desenhar) → não mexe em nada
        if float(f.mean()) < 6:
            self._blind_since = getattr(self, "_blind_since", None) or time.time()
            secs = time.time() - self._blind_since
            ctx.warn_once("blind", "Tela do jogo toda preta — aguardando a imagem voltar (sem clicar)")
            if secs > 120 and not getattr(self, "_blind_restarted", False):
                self._blind_restarted = True
                self._restart_game(ctx, "tela preta há 2 min")
            ctx.sleep(5, human=False)
            return False
        if getattr(self, "_blind_since", None):
            self.log("Imagem do jogo voltou")
        self._blind_since, self._blind_restarted = None, False
        ctx._warned.discard("blind")
        if ctx.find("dlg_connection_lost", 0.8, frame=f):
            self.log("Conexão perdida — reconectando", "warn")
            self.telegram.send("[TOSCO] conexão perdida, reconectando")
            if not ctx.tap("btn_reconnect", 2):
                ctx.tap_rel(0.5, 0.62)
            ctx.sleep(15)
            return False
        # carregando / manutenção / conta aberta no celular: esperar, não tocar
        if ctx.ai_on() and not ctx.on_main(f) and ctx.handle_blocking(ctx.where(f)):
            return False
        h = self.cfg.data["human"]
        if h.get("breaks_enabled") and time.time() >= self._next_break:
            mins = float(h.get("break_minutes", 8)) * random.uniform(0.7, 1.3)
            self.log(f"☕ Pausa humana de {mins:.0f} min")
            self.current = "pausa humana"
            self._emit()
            ctx.sleep(mins * 60, human=False)
            self._schedule_break()
        return True

    def _restart_game(self, ctx, reason):
        """Fecha o jogo e deixa o watchdog reabri-lo (precisa do caminho do jogo em SISTEMA)."""
        self._restart_reason = None
        self.recover_streak = 0
        exe = self.cfg.data.get("game_exe_path")
        if self.backend.name != "pc" or not exe or not os.path.exists(exe):
            self.log(f"Jogo travado ({reason}) — configure o caminho do jogo em SISTEMA para o TOSCO relançar", "warn")
            self.telegram.send(f"[TOSCO] jogo travado ({reason}), precisa de ajuda")
            return
        hwnd = winapi.find_window(self.cfg.data["game_window_title"])
        pid = winapi.window_pid(hwnd) if hwnd else 0
        self.log(f"↻ Relançando o jogo ({reason})", "warn")
        self.telegram.send(f"[TOSCO] relançando o jogo ({reason})")
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=0x08000000)
        ctx.sleep(5, human=False)

    def _urgent(self, ctx, exclude=None):
        """Tarefa urgente cujo sinal está na tela agora (escavação, presente) — passa na frente da fila."""
        if not ctx.ai_on():
            return None
        ctx.frame()
        for tid, signals in URGENT_SIGNALS.items():
            t = self.task_by_id(tid)
            if not t or t is exclude:
                continue
            s = self.cfg.task(tid, t.defaults())
            if not (s.get("enabled") or t is self.main_task()):
                continue
            if any(ctx.ai(sig) for sig in signals):
                return t
        return None

    def _idle_guard(self, ctx):
        """Guarda anti-travamento com o bot ocioso: fecha popup com X, popup só-Confirmar, e volta à tela
        principal se ficou fora dela 2 ciclos seguidos."""
        if not ctx.ai_on():
            return
        f = ctx.frame()
        if ctx.find("dlg_exit_game", frame=f):
            ctx.tap("btn_exit_cancel", 1.0)
            return
        if ctx.on_main(f):
            self._off_main = 0
            return
        if ctx.lone_confirm(f):
            return
        self._off_main += 1
        if ctx.seen("close_btn", 0.6, f):
            ctx.tap("btn_close", 0.5)
        elif self._off_main >= 2:
            self.log("Fora da tela principal — voltando")
            ctx.exit_to_main()
            self._off_main = 0

    def _run_task(self, ctx, t):
        is_job = isinstance(t, tuple)
        name = t[0] if is_job else t.name
        self.current = name
        self._emit()
        self.log(name if is_job else f"{t.icon} {t.name}")
        s = None if is_job else self.cfg.task(t.id, t.defaults())
        mins = 0 if is_job else float(t.budget_min(s) or 0)
        ctx.task_name, ctx.deadline = name, (time.time() + mins * 60 if mins > 0 else None)
        try:
            if is_job:
                t[1](ctx)
            else:
                t.run(ctx, s)
            self.stats["runs"] += 1
        except StopRequested:
            raise
        except TaskTimeout:
            ctx.deadline = None
            self.stats["errors"] += 1
            self.log(f"⏱ {name}: passou de {mins:.0f} min — interrompida, voltando à tela principal", "warn")
            try:
                ctx.go_home()
            except RuntimeError:
                pass
        except Exception as ex:
            self.stats["errors"] += 1
            self.log(f"✖ {name}: {ex}", "error")
            if os.environ.get("TOSCO_DEBUG"):
                self.log(traceback.format_exc(), "error")
        finally:
            ctx.deadline, ctx.task_name = None, ""
        if not is_job:
            self.last_run[t.id] = time.time()
        ctx.check()

    def _loop(self):
        ctx = Context(self)
        try:
            self.backend.prepare(self.log)
        except Exception as ex:
            self.log(f"preparação: {ex}", "warn")
        # aquece o RapidOCR aqui (1–2 s, fora da janela e fora da escavação); falha vira aviso, não silêncio
        if rapid.installed() and not rapid.available():
            self.log(f"RapidOCR indisponível ({rapid.error}) — cronômetros pelo Tesseract/OCR do Windows", "warn")
        last_status = time.time()
        try:
            while not self.stop_flag.is_set():
                ctx.check()
                try:
                    ok = self._watchdog(ctx)
                except RuntimeError:
                    ok = False
                    ctx.sleep(5, human=False)
                if not ok:
                    if self.only == "oneshot":
                        self.log("Ação cancelada: jogo não encontrado", "warn")
                        self.queue.clear()
                        break
                    continue
                due = self._due()
                for t in due:
                    # antes de cada tarefa: um sinal urgente na tela (escavação, presente) passa na frente
                    if self.only != "oneshot" and not isinstance(t, tuple):
                        u = self._urgent(ctx, exclude=t)
                        if u and TASK_PRIORITY.get(u.id, 50) < TASK_PRIORITY.get(t.id, 50):
                            self.log(f"⚡ {u.name} passou na frente")
                            self._run_task(ctx, u)
                    self._run_task(ctx, t)
                if self.only == "oneshot" and not self.queue:
                    break
                if self.only != "oneshot":
                    try:
                        self._idle_guard(ctx)
                    except RuntimeError:
                        pass
                self.current = "aguardando"
                self._emit()
                mins = float(self.cfg.data["telegram"].get("status_minutes", 0) or 0)
                if mins and time.time() - last_status > mins * 60:
                    last_status = time.time()
                    self.telegram.send(self.status_text())
                ctx.sleep(float(self.cfg.data.get("loop_delay", 1.0)))
        except StopRequested:
            pass
        except Exception as ex:
            self.log(f"Falha no motor: {ex}", "error")
        finally:
            self.current = "—"
            self.only = None
            self.log("■ Todas as tarefas paradas")
            self._emit()

    def status_text(self):
        up = int(time.time() - self.started_at) if self.running and self.started_at else 0
        c = self.counters.all()
        extra = ", ".join(f"{k}: {v}" for k, v in sorted(c.items()) if isinstance(v, int))[:600]
        return (f"[TOSCO] {self.state()} · {self.current}\nativo {up // 3600}h{up % 3600 // 60:02d}m · "
                f"{self.stats['runs']} execuções · {self.stats['taps']} toques · {self.stats['errors']} erros\n"
                f"hoje: {extra or '—'}")


class AutoClicker:
    """Clicker independente do motor: clica no ponto alvo (tela) com intervalo + variação."""

    def __init__(self, log):
        self.log = log
        self._stop = threading.Event()
        self.thread = None

    @property
    def active(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, x, y, cooldown=0.05, jitter=0.005, stop_after=None, jitter_px=1):
        if self.active:
            return
        self._stop.clear()

        def go():
            n, t0 = 0, time.time()
            pt = winapi.wintypes.POINT()
            while not self._stop.is_set():
                winapi.user32.GetCursorPos(winapi.ctypes.byref(pt))
                if pt.x <= 2 and pt.y <= 2:  # trava de segurança: mouse no canto superior esquerdo
                    break
                winapi.click(x, y, jitter_px)
                n += 1
                if stop_after and time.time() - t0 >= stop_after:
                    break
                time.sleep(max(0.005, cooldown + random.uniform(-jitter, jitter)))
            self.log(f"⌖ Clicker parou após {n} cliques")

        self.thread = threading.Thread(target=go, daemon=True)
        self.thread.start()
        self.log(f"⌖ Clicker ativo em ({x}, {y})")

    def stop(self):
        self._stop.set()


def norm_text(s):
    return norm(s)
