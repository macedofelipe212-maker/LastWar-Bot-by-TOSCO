"""Módulos de automação do TOSCO.

Cada passo procura o elemento por template (imagem capturada) e, se for um botão com texto, também pelo
texto via OCR em vários idiomas (ver core/targets.py) — esses o TOSCO aprende sozinho.
Ícones sem texto precisam ser capturados uma vez (Estúdio ou F8 com o mouse em cima).

Convenção: hud_* telas · btn_* botões · tab_* abas · chat_* chat · rally_* chefes · map_* ícones do mapa
"""
import csv
import datetime as dt
import json
import os
import random
import re
import time

import numpy as np

from ..core import catalog, rapid, tesseract
from ..core.engine import DAYS, Card, Field, Task
from ..core.ocr import norm
from ..core.paths import REPORT_DIR
from ..core.scanner import CAT_NAMES, CATEGORIES, DEFAULTS as SCAN_DEFAULTS, ScanStore, measure_shift
from ..core.targets import ARMS_RACE_TAB, ARMS_RACE_THEMES, TEXT_TARGETS

SQUADS = ["1", "2", "3", "4"]
LEVELS = ["UR", "SSR", "SR", "R", "N"]

COMMON = [
    ("hud_base", "Algo que só aparece na tela da base (opcional se o OCR achar 'Mundo')"),
    ("hud_world", "Algo que só aparece no mapa-múndi (opcional se o OCR achar 'Base')"),
    ("btn_to_world", "Botão que vai da base para o mapa"),
    ("btn_to_base", "Botão que volta do mapa para a base"),
    ("btn_back", "Seta ← de voltar dos painéis (ajuda a fechar telas abertas)"),
    ("btn_close", "X de fechar janelas (ajuda a fechar telas abertas)"),
    ("dlg_exit_game", "Diálogo 'Sair do jogo?'"),
    ("btn_exit_cancel", "Cancelar desse diálogo"),
    ("dlg_connection_lost", "Janela de conexão perdida"),
    ("btn_reconnect", "Botão reconectar/confirmar dessa janela"),
    ("btn_confirm", "Botão confirmar genérico"),
    ("btn_march", "Botão de marchar/enviar tropas"),
    ("squad_1", "Aba do esquadrão 1 na tela de marcha"), ("squad_2", "Aba do esquadrão 2"),
    ("squad_3", "Aba do esquadrão 3"), ("squad_4", "Aba do esquadrão 4"),
    ("squad_busy", "Indicador de esquadrão ocupado/marchando"),
    ("btn_alliance", "Botão da aliança"), ("btn_search", "Lupa de busca no mapa"), ("btn_go", "Botão Buscar/Ir"),
]


def parse_list(text):
    return [p.strip() for p in str(text).replace(";", ",").split(",") if p.strip()]


def march(ctx, squads, weak_ok=False):
    """Na tela de marcha: escolhe o primeiro esquadrão livre da ordem e envia. weak_ok: confirma o aviso do jogo
    'seu esquadrão é fraco demais' (esquadrões fracos ou de 1 herói)."""
    def sent(sq):
        if weak_ok:
            ctx.sleep(0.6)
            f = ctx.frame()
            if ctx.seen("confirm_popup", 0.5, f) and ctx.seen("cancel_popup", 0.4, f):
                ctx.tap("btn_confirm", 1.0, after=0.6)
        return sq

    for sq in squads:
        if ctx.tap(f"squad_{sq}", 1.2, after=0.4):
            if ctx.vision.has("squad_busy") and ctx.exists("squad_busy", 0.88):
                continue
            if ctx.tap("btn_march", 2):
                return sent(sq)
    return sent("auto") if ctx.tap("btn_march", 2) else None


def game_weekday(ctx):
    """Dia da semana NO JOGO (0 = segunda): relógio do PC menos o horário de reset, mais o ajuste de
    Configurações ('Hoje é (no jogo)')."""
    try:
        h, m = map(int, str(ctx.cfg.get("reset_time", "05:00")).split(":"))
    except ValueError:
        h, m = 5, 0
    d = dt.datetime.now() - dt.timedelta(hours=h, minutes=m)
    return (d.weekday() + int(ctx.cfg.get("game_day_offset", 0) or 0)) % 7


def day_in(ctx, text):
    """'sab, dom' contém o dia de hoje no jogo? Campo vazio = nenhum dia."""
    want = {norm(d)[:3] for d in re.split(r"[,; ]+", str(text or "")) if d.strip()}
    return DAYS[game_weekday(ctx)] in want


def _box_has(box, pt):
    x, y, _, w, h = box
    return abs(pt[0] - x) <= w / 2 and abs(pt[1] - y) <= h / 2


def _power_m(text):
    """'32,5M' / '531K' / '1.2B' → milhões (float) ou None."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([kmb])\b", str(text).lower())  # norm() tiraria a vírgula decimal
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v / 1000 if m.group(2) == "k" else v * 1000 if m.group(2) == "b" else v


def _hm(text):
    try:
        h, m = str(text).strip().split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _clock_in(a, b, now=None):
    """Agora está entre a e b ('HH:MM', pode virar a meia-noite)? Campo vazio = sempre."""
    lo, hi = _hm(a), _hm(b)
    if lo is None or hi is None:
        return True
    now = now or dt.datetime.now()
    t = now.hour * 60 + now.minute
    return lo <= t <= hi if lo <= hi else (t >= lo or t <= hi)


def _in_windows(text, now=None):
    """'02:00-07:00, 13:00-14:00' → agora está em alguma janela?"""
    for part in re.split(r"[,;]", str(text or "")):
        if "-" in part:
            a, b = part.split("-", 1)
            if _hm(a) is not None and _hm(b) is not None and _clock_in(a, b, now):
                return True
    return False


# ---------------------------------------------------------------- escavações e diárias
class AutoDigs(Task):
    id, name, icon, group = "auto_digs", "Escavações & Ovos", "⛏", "Escavações & Diárias"
    description = "Vigia o chat da aliança, entra nas escavações/ovos assim que aparecem e toca até o top 20."
    default_enabled, default_interval = True, 0.5

    def budget_min(self, s):  # uma rodada: até 90 s de espera + os toques rápidos + folga
        return float(s.get("spam_duration", 120)) / 60 + 8
    templates = [("btn_chat", "Botão que abre o chat"), ("tab_chat_alliance", "Aba do chat da aliança"),
                 ("chat_dig", "Ícone de escavação compartilhada no chat"), ("chat_egg", "Ícone de ovo no chat"),
                 ("chat_party", "Ícone de festa/fogos no chat"),
                 ("dig_spot", "O ponto de escavação no mapa"), ("dig_open", "Indicador de escavação aberta"),
                 ("btn_collect", "Botão de coletar recompensa"), ("chat_input", "Campo de digitar no chat")]
    fields = [
        Field("take_eggs", "Pegar ovos", "bool", True), Field("take_parties", "Pegar festas/fogos", "bool", True),
        Field("detect_only", "Só avisar (não tocar)", "bool", False),
        Field("skip_chance", "Pular aleatoriamente (% p/ parecer humano)", "int", 0, minimum=0, maximum=50),
        Field("max_taps", "Toques máximos por escavação", "int", 40, minimum=1, maximum=500),
        Field("tap_cooldown", "Intervalo entre toques (s)", "float", 0.05, minimum=0.01, maximum=2),
        Field("send_message", "Agradecer no chat depois", "bool", False),
        Field("messages", "Mensagens (separe por vírgula)", "text", "thanks, ty, valeu, gg"),
        Field("message_limit_min", "Mín. entre mensagens (min)", "int", 5, minimum=0, maximum=600),
        Field("squad_order", "Ordem de esquadrões", "text", "1,2,3,4"),
        Field("spam_threshold", "Começar os toques rápidos faltando (s)", "int", 13, minimum=1, maximum=120),
        Field("spam_threshold_max", "…até (s; sorteio a cada escavação, 0 = sem sorteio)", "int", 0, minimum=0,
              maximum=120),
        Field("late_windows", "Toque atrasado nestes horários (ex.: 02:00-07:00, 13:00-14:00)", "text", ""),
        Field("late_wait_s", "…esperar depois do fim do cronômetro (s)", "int", 3, minimum=0, maximum=120),
        Field("take_fireworks", "Pegar fogos de artifício", "bool", True),
        Field("gift_wait_min", "Esperar antes de abrir presente/ovo da sorte — de (s)", "float", 3.0, minimum=0,
              maximum=30),
        Field("gift_wait_max", "…até (s)", "float", 4.0, minimum=0, maximum=30),
        Field("skip_take_min", "Pular algumas: pegar de", "int", 0, minimum=0, maximum=50,
              hint="0 = desligado (usa a % de pular aleatório)"),
        Field("skip_take_max", "…até", "int", 0, minimum=0, maximum=50),
        Field("skip_skip_min", "…depois pular de", "int", 1, minimum=1, maximum=20),
        Field("skip_skip_max", "…até", "int", 1, minimum=1, maximum=20),
        Field("never_skip_drone", "Nunca pular escavações de drone", "bool", True),
        Field("messages_gift", "Mensagens depois de ovo/presente (vazio = as mesmas)", "text", ""),
        Field("msg_from", "Mensagens só a partir de (HH:MM)", "text", "08:00"),
        Field("msg_to", "…até (HH:MM)", "text", "22:00"),
        Field("spam_duration", "Tocar rápido por no máximo (s)", "int", 120, minimum=5, maximum=600),
        Field("max_wait_min", "Desistir da escavação depois de (min)", "int", 60, minimum=1, maximum=240),
        Field("chat_scan_min", "Sem alerta: olhar o chat a cada (min, 0 = nunca)", "int", 3, minimum=0, maximum=120),
    ]
    main_capable = True
    cards = [
        ("O que coletar", [
            Card("Escavações", "⛏", "As escavações da sua aliança: o TOSCO manda um esquadrão até o ponto, "
                 "espera o cronômetro e coleta o presente.", fields=["squad_order", "max_wait_min"],
                 summary="esquadrões {squad_order} · desiste após {max_wait_min} min"),
            Card("Ovos", "◒", "Ovos compartilhados no chat: toques rápidos para o top 20.", toggle="take_eggs",
                 summary=lambda s: "pega os ovos" if s["take_eggs"] else "ignora ovos"),
            Card("Festas", "✺", "Escavações de festa (Corrida de Rua, Halloween, Natal…).", toggle="take_parties",
                 summary=lambda s: "pega festas" if s["take_parties"] else "ignora festas"),
            Card("Fogos de artifício", "✷", "Recompensas de fogos de artifício (ícone acima da barra do chat).",
                 toggle="take_fireworks"),
            Card("Presentes da sorte", "♣", "Espera um pouco antes de abrir (sorteio), para outros abrirem primeiro.",
                 fields=["gift_wait_min", "gift_wait_max"],
                 summary=lambda s: f"espera {float(s['gift_wait_min']):g}–{float(s['gift_wait_max']):g} s"),
        ]),
        ("Como tocar", [
            Card("Toques rápidos", "⚡", "Quantos toques e com que velocidade nos ovos e festas.",
                 fields=["max_taps", "tap_cooldown"], summary="{max_taps} toques · {tap_cooldown}s entre eles"),
            Card("Final da escavação", "⏱", "Começa a tocar quando restarem de X a Y segundos (sorteio a cada "
                 "escavação) e toca sem parar até o presente.",
                 fields=["spam_threshold", "spam_threshold_max", "spam_duration"],
                 summary=lambda s: (f"faltando {s['spam_threshold']}–{s['spam_threshold_max']}s"
                                    if int(s["spam_threshold_max"]) > int(s["spam_threshold"])
                                    else f"faltando {s['spam_threshold']}s") + f" · até {s['spam_duration']}s"),
            Card("Toque de recompensa atrasado", "◷", "Nestes horários não fica tocando: espera o cronômetro acabar, "
                 "aguarda alguns segundos e toca UMA vez. Fora deles coleta na hora.",
                 fields=["late_windows", "late_wait_s"],
                 summary=lambda s: f"{s['late_windows']} · +{s['late_wait_s']}s" if s["late_windows"].strip()
                 else "desligado"),
            Card("Pular algumas", "◔", "Pega algumas e pula outras, como um jogador real: 'pegar 2–3, depois pular "
                 "1'. Com o primeiro campo em 0 usa a % de pular aleatório.",
                 fields=["skip_take_min", "skip_take_max", "skip_skip_min", "skip_skip_max", "never_skip_drone",
                         "skip_chance"],
                 summary=lambda s: (f"pega {s['skip_take_min']}–{s['skip_take_max']}, pula "
                                    f"{s['skip_skip_min']}–{s['skip_skip_max']}") if int(s["skip_take_min"])
                 else (f"pula {s['skip_chance']}%" if s["skip_chance"] else "pega todas")),
            Card("Só avisar", "🔔", "Não toca em nada: só avisa (registro e Telegram).", toggle="detect_only"),
        ]),
        ("No chat", [
            Card("Mensagens", "✉", "Agradece no chat depois de cada escavação e de cada ovo/presente. Textos "
                 "separados por vírgula ou '|': um é sorteado a cada vez.", toggle="send_message",
                 fields=["messages", "messages_gift", "message_limit_min", "msg_from", "msg_to"],
                 summary=lambda s: (f"1 a cada {s['message_limit_min']} min · {s['msg_from']}–{s['msg_to']}"
                                    if s["send_message"] else "desligado")),
        ]),
    ]

    # Máquina de estados com a IA (fluxo do LWFarmBot): IDLE → (alerta | chat) → NAVIGATED (logo no mapa) →
    # JOINING (Ajudar a cavar → esquadrão → Marchar) → WAITING (cronômetro; toques rápidos nos últimos segundos)
    # → COLLECTING (presente). O presente pronto tem prioridade em QUALQUER estado (um aliado pode terminar antes).
    # Cronômetro longo: devolve a vez às outras tarefas e volta no próximo ciclo (a escavação é a mais urgente).
    # Sem IA, cai no fluxo antigo por imagens capturadas.
    _st = None  # escavação em andamento: {"t": entrou, "logo": (x, y), "reopen": n, "unread": n}

    def run(self, ctx, s):
        if ctx.ai_on():
            return self._run_ai(ctx, s)
        return self._run_templates(ctx, s)

    # --- peças ---------------------------------------------------------
    def _timer(self, ctx):
        """Cronômetro do popup na caixa `timer_text`: RapidOCR no recorte justo (~11 ms) → Tesseract com margem;
        senão na aba inteira, só tokens com ':'; por último o OCR do Windows (que sozinho não lê a fonte do jogo)."""
        f = ctx.frame(fresh=False)
        box = ctx.ai("dig_timer", f)
        if box:
            x, y, _, w, h = box[0]
            v = rapid.read_timer_box(f, (x, y, w, h))
            if v == rapid.INVALID:
                return None  # relógio lido com certeza mas fora do limite: o Tesseract só "consertaria" para errado
            if v is not None:
                return v
            mx, my = int(w * 0.25) + 4, int(h * 0.35) + 4
            crop = f[max(0, y - h // 2 - my):y + h // 2 + my, max(0, x - w // 2 - mx):x + w // 2 + mx]
            v = tesseract.read_timer(crop)
            if v is not None:
                return v
        tab = ctx.ai("dig_timer_popup", f)
        if tab:
            x, y, _, w, h = tab[0]
            crop = f[max(0, y - h // 2):y + h // 2, max(0, x - w // 2):x + w // 2]
            v = rapid.read_timer_in_text(crop)
            if v == rapid.INVALID:
                return None
            if v is None:
                v = tesseract.read_timer_in_text(crop)
            if v is not None:
                return v
        if box and ctx.ocr_on():
            x, y, _, w, h = box[0]
            crop = f[max(0, y - h):y + h, max(0, x - w):x + w]
            return tesseract.parse_timer(" ".join(l.text for l in ctx.ocr.read(crop, upscale=3.0)))
        return None

    def _claim(self, ctx, s=None):
        """Presente pronto (escavação terminada, por nós ou pela aliança) → coleta, fecha a recompensa."""
        hit = ctx.find("dig_claim", text=False)
        if not hit:
            return False
        ctx.tap_xy(*hit, spread=2)
        ctx.sleep(1.2)
        f = ctx.frame()
        proof = bool(ctx.seen("reward_message", 0.4, f) or ctx.seen("share_popup", 0.4, f))
        if proof and ctx.cfg["telegram"].get("notify_digs"):
            ctx.e.telegram.send_photo(f, "⛏ Recompensa da escavação")  # o print do que veio, no celular
        for _ in range(4):  # tela de recompensa: fecha pelo X; sem X, toque embaixo
            if ctx.on_main():
                break
            if not ctx.tap("btn_close", 0.8, after=0.5):
                ctx.tap_rel(0.5, 0.88)
                ctx.sleep(0.6)
        ctx.counters.add("digs")
        ctx.log("⛏ Presente da escavação coletado")
        self._st = None
        if s and (proof or s.get("send_message")):
            self._thanks(ctx, s)
        return True

    def _thanks(self, ctx, s, kind="dig"):
        if not s["send_message"] or time.time() - getattr(self, "_last_msg", 0) < int(s["message_limit_min"]) * 60:
            return
        if not _clock_in(s.get("msg_from", ""), s.get("msg_to", "")):
            return
        text = s.get("messages_gift") if kind == "gift" and str(s.get("messages_gift", "")).strip() else s["messages"]
        msgs = [m.strip() for m in re.split(r"[,|]", str(text)) if m.strip()]
        if msgs and ctx.tap("btn_chat", 2):
            ctx.tap("tab_chat_alliance", 1.2)  # garante o canal da aliança
            if ctx.tap("chat_input", 2):
                ctx.type(random.choice(msgs))
                ctx.key("enter")
                self._last_msg = time.time()
                ctx.sleep(0.6)
        ctx.go_home()

    def _gift(self, ctx, s):
        """Presente/Ovo da Sorte: ícone preso logo acima da barra do chat → link → botão da janela → recompensa →
        fecha VERIFICADO (X; se continuar aberto, ESC até 4×). Repete enquanto houver outro link."""
        if not s["take_eggs"] or not ctx.find("gift_alert", text=False):
            return False
        ctx.tap("gift_alert", 1, after=1.2)
        done = 0
        for _ in range(4):
            link = ctx.ai_wait("chat_egg", 2.5)
            if not link:
                break
            if s["detect_only"]:
                ctx.log("◒ Presente da aliança visto (só avisar)")
                break
            lo, hi = float(s.get("gift_wait_min", 0) or 0), float(s.get("gift_wait_max", 0) or 0)
            if hi > 0:
                ctx.sleep(random.uniform(lo, max(lo, hi)), human=False)  # outros abrem primeiro
            ctx.tap_xy(link[0], link[1], spread=2)
            btn = ctx.ai_wait("gift_popup_btn", 2.5)
            if btn:
                for _ in range(int(s["max_taps"])):
                    if ctx.ai("gift_reward"):
                        ctx.tap("gift_reward", 1)
                        ctx.tap("btn_like", 1.2, after=0.4)  # curtir quem deu o presente (como o piggy-lastwar-bot)
                        ctx.counters.add("eggs")
                        done += 1
                        ctx.log("◒ Presente/ovo da aliança coletado")
                        break
                    hit = ctx.find("gift_popup_btn", text=False)
                    if not hit:
                        break
                    ctx.tap_xy(*hit, spread=3)
                    time.sleep(max(0.02, float(s["tap_cooldown"]) * random.uniform(0.85, 1.3)))
                    ctx.check()
            for _ in range(4):  # fecha o popup do presente sem fechar o chat
                if not (ctx.ai("gift_reward") or ctx.ai("gift_popup_btn") or ctx.seen("treasure_gift_popup", 0.5)):
                    break
                if not ctx.tap("btn_close", 1.5, after=0.5):
                    ctx.key("esc")
                    ctx.sleep(0.5)
        if done:
            self._thanks(ctx, s, "gift")
        else:
            ctx.go_home()
        return True

    def _fireworks(self, ctx, s):
        """Fogos de artifício: ícone acima da barra do chat → botão de coletar → fecha."""
        if not s.get("take_fireworks", True) or not ctx.ai("fire_alert", ctx.frame(fresh=False)):
            return False
        ctx.tap("fire_alert", 1, after=1.0)
        got = 0
        for _ in range(5):
            if not ctx.tap("fire_claim", 1.2, after=0.8):
                break
            got += 1
        if got:
            ctx.counters.add("fireworks", got)
            ctx.log(f"✷ Fogos de artifício coletados ({got})")
        ctx.go_home()
        return True

    def _open_dig(self, ctx, s):
        """Do alerta (ou do chat) até o logo da escavação no mapa. Retorna o logo (x, y) ou None."""
        if ctx.find("dig_alert", text=False):
            ctx.tap("dig_alert", 1, after=1.2)
        elif (self._st is None and float(s.get("chat_scan_min", 3)) > 0
              and time.time() - getattr(self, "_last_chat", 0) >= float(s.get("chat_scan_min", 3)) * 60):
            self._last_chat = time.time()  # sem alerta: olha o chat da aliança de vez em quando
            if not ctx.tap("btn_chat", 1.5, after=1.0):
                return None
            ctx.tap("tab_chat_alliance", 1.2)
        else:
            return None
        end = time.time() + 6
        while time.time() < end:  # o alerta às vezes leva direto ao mapa, às vezes ao link no chat
            f = ctx.frame()
            if ctx.ai("dig_claim", f):
                return "claim"
            logo = ctx.ai("dig_logo", f)
            if logo:
                return logo[0][:2]
            link = ctx.ai("chat_dig", f)  # só "Chat Dug up" (já escavada) não está em chat_dig → ignorada
            if link:
                ctx.log("⛏ Escavação encontrada no chat")
                if ctx.cfg["telegram"].get("notify_digs"):
                    ctx.notify("escavação encontrada")
                drone = bool(ctx.seen("drone_chat", 0.4, f) or ctx.seen("Chat Test Flight", 0.4, f)
                             or ctx.seen("flight_chat", 0.4, f))
                if s["detect_only"] or self._skip(s, drone):
                    return None
                ctx.tap_xy(link[0][0], link[0][1], spread=2)
                hit = ctx.ai_wait("dig_logo", 8)
                if hit:
                    return hit[:2]
                # o link sempre centraliza o mapa na escavação: sem achar o logo, o ponto certo é o centro da tela
                if ctx.on_main() == "world":
                    f = ctx.frame(fresh=False)
                    ctx.log("⛏ Logo não reconhecido — usando o centro da tela (o mapa centraliza na escavação)")
                    return f.shape[1] // 2, f.shape[0] // 2
                return None
            ctx.sleep(0.4, human=False)
        return None

    def _skip(self, s, drone=False):
        """Pular algumas escavações para parecer jogador: padrão 'pegar 2–3, depois pular 1' ou % aleatório."""
        if drone and s.get("never_skip_drone", True):
            return False
        lo = int(s.get("skip_take_min", 0) or 0)
        if not lo:
            return random.randint(1, 100) <= int(s.get("skip_chance", 0) or 0)
        st = getattr(self, "_skipst", None)
        if not st:
            st = self._skipst = {"take": random.randint(lo, max(lo, int(s.get("skip_take_max", lo) or lo))),
                                 "skip": 0}
        if st["take"] > 0:
            st["take"] -= 1
            if st["take"] == 0:
                a = int(s.get("skip_skip_min", 1) or 1)
                st["skip"] = random.randint(a, max(a, int(s.get("skip_skip_max", a) or a)))
            return False
        st["skip"] -= 1
        if st["skip"] <= 0:
            self._skipst = None
        return True

    # --- estados -------------------------------------------------------
    def _run_ai(self, ctx, s):
        ctx.frame()
        if self._claim(ctx, s):  # prioridade máxima em qualquer estado
            return True
        if self._st:
            return self._waiting(ctx, s)
        if self._fireworks(ctx, s):
            return True
        if self._gift(ctx, s):
            return True
        logo = self._open_dig(ctx, s)
        if logo == "claim":
            return self._claim(ctx, s)
        if not logo:
            if not ctx.on_main():
                ctx.go_home()
            return False
        return self._join(ctx, s, logo)

    def _join(self, ctx, s, logo):
        """NAVIGATED → JOINING: toca no logo; 'Ajudar a cavar' → esquadrão → Marchar."""
        nxt = None
        h = ctx.frame(fresh=False).shape[0]
        # o 1º toque é no logo; se o popup não abrir (ex.: logo não reconhecido e o toque foi no centro da tela),
        # tenta um pouco acima e um pouco abaixo antes de desistir
        for dy in (0.0, -0.06, 0.06):
            ctx.tap_xy(logo[0], int(logo[1] + dy * h), spread=2)
            end = time.time() + (3.5 if dy == 0 else 2.0)
            while time.time() < end and not nxt:
                f = ctx.frame()
                for name in ("dig_claim", "dig_help", "dig_timer_popup"):
                    if ctx.ai(name, f):
                        nxt = name
                        break
                else:
                    ctx.sleep(0.3, human=False)
            if nxt:
                break
        if nxt == "dig_claim":
            return self._claim(ctx, s)
        if nxt == "dig_help":
            ctx.tap("dig_help", 1.5, after=1.0)
            if not march(ctx, parse_list(s.get("squad_order", "")) or SQUADS):
                ctx.log("⛏ Sem esquadrão livre para a escavação", "warn")
                ctx.go_home()
                return False
            ctx.log("⛏ Esquadrão enviado para a escavação")
        elif nxt is None:
            ctx.log("⛏ Escavação: o popup não abriu", "warn")
            ctx.go_home()
            return False
        self._st = {"t": time.time(), "logo": logo, "reopen": 0, "unread": 0}
        ctx.sleep(1.2)
        return self._waiting(ctx, s)

    def _waiting(self, ctx, s):
        """WAITING: abre o popup do cronômetro pelo logo; ≤ limite → toques rápidos até o presente."""
        st = self._st
        if time.time() - st["t"] > int(s.get("max_wait_min", 60)) * 60:
            ctx.log("⛏ Escavação demorou demais — desisti", "warn")
            self._st = None
            ctx.go_home()
            return False
        if "thr" not in st:  # sorteio uma vez por escavação (QB: 5–7 s)
            lo = int(s.get("spam_threshold", 13))
            st["thr"] = random.randint(lo, max(lo, int(s.get("spam_threshold_max", 0) or 0)))
        thr = st["thr"]
        late = _in_windows(s.get("late_windows", ""))
        end = time.time() + 90
        while time.time() < end:
            f = ctx.frame()
            if self._claim(ctx, s):
                return True
            if ctx.seen("Treasure gone", 0.6, f):  # outro pegou o presente antes: não adianta esperar
                ctx.log("⛏ O tesouro já foi pego por outro — encerrando esta escavação")
                self._st = None
                ctx.go_home()
                return False
            if ctx.ai("squad_1", f) and ctx.ai("btn_march", f):  # a equipe não saiu: marcha de novo
                march(ctx, parse_list(s.get("squad_order", "")) or SQUADS)
                continue
            if not ctx.ai("dig_timer_popup", f):  # popup fechado → reabre pelo logo (ou volta pelo alerta)
                logo = ctx.ai("dig_logo", f)
                pt = logo[0][:2] if logo else self._open_dig(ctx, s)
                if pt == "claim":
                    return self._claim(ctx, s)
                if not pt:
                    st["reopen"] += 1
                    if st["reopen"] >= 5:
                        ctx.log("⛏ Não consegui reabrir a escavação — desisti", "warn")
                        self._st = None
                    ctx.go_home()
                    return False
                st["logo"] = pt
                ctx.tap_xy(*pt, spread=2)
                ctx.sleep(1.0)
                continue
            st["reopen"] = 0
            left = self._timer(ctx)
            if left is None:
                st["unread"] += 1
                if st["unread"] < 4:
                    ctx.sleep(1.0, human=False)
                    continue
            elif late and left > 0:
                st["unread"] = 0
                if left > 75:
                    ctx.log(f"⛏ Escavação em {left // 60}:{left % 60:02d} — volto depois (toque atrasado)")
                    ctx.key("esc")
                    return False
                ctx.sleep(min(left, 20), human=False)
                continue
            elif late:
                ctx.sleep(float(s.get("late_wait_s", 3)) * random.uniform(0.9, 1.3), human=False)
                ctx.tap_xy(*st["logo"], spread=3)  # um toque só, depois do fim
                ctx.sleep(1.0)
                ctx.frame()
                if self._claim(ctx, s):
                    return True
                continue
            elif left > thr:
                st["unread"] = 0
                if left > 75:
                    ctx.log(f"⛏ Escavação em {left // 60}:{left % 60:02d} — volto depois")
                    ctx.key("esc")  # fecha o popup e deixa as outras tarefas rodarem
                    return False
                ctx.sleep(min(left - thr, 20), human=False)
                continue
            ctx.log("⛏ Últimos segundos: tocando rápido")
            if ctx.danger_at(*st["logo"]):  # confere uma vez; no spam cada milissegundo conta
                return False
            t_end = time.time() + int(s.get("spam_duration", 120))
            n = 0
            while time.time() < t_end and n < 4000:
                ctx.tap_xy(*st["logo"], spread=3, guard=False)
                n += 1
                time.sleep(max(0.02, float(s["tap_cooldown"]) * random.uniform(0.85, 1.3)))
                ctx.check()
                if n % 15 == 0:
                    ctx.frame()
                    if self._claim(ctx, s):
                        return True
            break
        return False

    def _run_templates(self, ctx, s):
        if not ctx.tap("btn_chat", 2):
            return
        ctx.tap("tab_chat_alliance", 1.5)
        kinds = ["chat_dig"] + (["chat_egg"] if s["take_eggs"] else []) + (["chat_party"] if s["take_parties"] else [])
        hits = [h for k in kinds for h in ctx.find_all(k, 0.86)]
        if not hits:
            ctx.back()
            return
        ctx.log(f"⛏ {len(hits)} escavação(ões)/evento(s) no chat")
        if ctx.cfg["telegram"].get("notify_digs"):
            ctx.notify("escavação encontrada")
        if s["detect_only"] or random.randint(1, 100) <= int(s["skip_chance"]):
            ctx.back()
            return
        ctx.tap_xy(*hits[0])
        ctx.sleep(2.0)
        # escavação: o mapa centraliza nela; toca no centro e envia um esquadrão (Marchar)
        ctx.tap_rel(0.5, 0.5)
        ctx.sleep(0.8)
        if ctx.tap("btn_march", 1.5):
            ctx.counters.add("digs")
            ctx.log("⛏ Esquadrão enviado para a escavação")
            ctx.go_home()
            return
        spot = ctx.wait_for("dig_spot", 4, 0.8)  # ovos/festas: toques rápidos para o top 20
        if spot and not ctx.danger_at(*spot):
            for _ in range(int(s["max_taps"])):
                ctx.tap_xy(*spot, spread=3, guard=False)
                time.sleep(max(0.01, float(s["tap_cooldown"]) * random.uniform(0.85, 1.3)))
                ctx.check()
                if ctx.vision.has("dig_open") and ctx.exists("dig_open", 0.85):
                    break
            ctx.tap("btn_collect", 3)
            ctx.counters.add("digs")
        if s["send_message"] and time.time() - getattr(self, "_last_msg", 0) >= int(s["message_limit_min"]) * 60:
            msgs = parse_list(s["messages"])
            if msgs and ctx.tap("btn_chat", 2) and ctx.tap("chat_input", 2):
                ctx.type(random.choice(msgs))
                ctx.key("enter")
                self._last_msg = time.time()
        ctx.go_home()


class Survivors(Task):
    id, name, icon, group = "survivors", "Sobreviventes & Ajuda", "✚", "Escavações & Diárias"
    description = "Resgata sobreviventes que aparecem na base e toca no botão flutuante de ajuda da aliança."
    default_enabled, default_interval = True, 3.0
    templates = [("survivor_found", "Balão/ícone de sobrevivente encontrado"),
                 ("survivor_claim", "Botão/ícone para receber o sobrevivente"),
                 ("btn_alliance_help", "Botão flutuante de ajuda (aperto de mãos)")]
    fields = [Field("survivors", "Resgatar sobreviventes", "bool", True),
              Field("help", "Ajudar aliança", "bool", True)]

    def run(self, ctx, s):
        if ctx.go_home() is None:
            return
        n = 0
        while s["help"] and n < 10 and ctx.vision.has("btn_alliance_help") and \
                ctx.tap("btn_alliance_help", 0.5, after=0.4):
            n += 1
        if n:
            ctx.counters.add("alliance_help", n)
        if s["survivors"] and ctx.vision.has("survivor_found") and ctx.tap("survivor_found", 0.8, after=1.0):
            for _ in range(2):  # o primeiro toque abre, o segundo recebe
                ctx.tap("survivor_claim", 1.5, after=0.8)
            ctx.counters.add("survivors")
            ctx.log("✚ Sobrevivente resgatado")
            ctx.go_home()


class IdleRewards(Task):
    id, name, icon, group = "idle_rewards", "Recompensas parado & Visitantes", "⧗", "Escavações & Diárias"
    description = "Coleta as recompensas acumuladas do Overlord e do Caminhão Armado e cumprimenta os visitantes " \
                  "da sua cidade."
    default_enabled, default_interval = True, 60.0
    templates = [("idle_overlord", "Bolha/ícone de recompensa acumulada do Overlord na base"),
                 ("idle_truck", "Bolha/ícone de recompensa do Caminhão Armado na base"),
                 ("city_visitor", "Visitante na sua cidade (balão sobre o personagem)"),
                 ("btn_greet", "Botão Cumprimentar do visitante")]
    fields = [Field("overlord", "Recompensa do Overlord", "bool", True),
              Field("truck", "Recompensa do Caminhão Armado", "bool", True),
              Field("visitors", "Cumprimentar visitantes", "bool", True)]
    cards = [("O que coletar", [
        Card("Overlord", "♚", "Recompensas que o Overlord acumula enquanto você está fora.", toggle="overlord"),
        Card("Caminhão Armado", "⛟", "Recompensas do Caminhão Armado parado na base.", toggle="truck"),
    ]), ("Cidade", [
        Card("Visitantes", "☺", "Cumprimenta quem visita a sua cidade (dá recompensa pequena).", toggle="visitors"),
    ])]

    def _claim(self, ctx, icon, label):
        if not ctx.vision.has(icon) or not ctx.tap(icon, 0.8, after=1.0):
            return False
        for _ in range(3):  # 'Receber' / 'Coletar tudo' e eventual janela de confirmação
            if not (ctx.tap("btn_claim_all", 0.8, after=0.6) or ctx.tap("btn_claim", 0.8, after=0.6)
                    or ctx.tap("btn_collect", 0.8, after=0.6)):
                break
        ctx.counters.add(f"idle_{label}")
        ctx.log(f"⧗ Recompensa do {label} coletada")
        ctx.go_home()
        return True

    def run(self, ctx, s):
        if not ctx.to_base():
            return
        if s["overlord"]:
            self._claim(ctx, "idle_overlord", "Overlord")
        if s["truck"]:
            self._claim(ctx, "idle_truck", "Caminhão Armado")
        if s["visitors"] and ctx.vision.has("city_visitor"):
            n = 0
            for _ in range(5):
                if not ctx.tap("city_visitor", 0.8, after=1.0):
                    break
                if ctx.tap("btn_greet", 1.5, after=0.8):
                    n += 1
                ctx.go_home()
            if n:
                ctx.counters.add("visitors", n)
                ctx.log(f"☺ {n} visitante(s) cumprimentado(s)")


class Resources(Task):
    id, name, icon, group = "resources", "Coleta de Recursos", "⛁", "Escavações & Diárias"
    description = "Toca nas bolhas de comida, ferro, ouro, caminhão e outros recursos sobre os prédios da base; " \
                  "pode pedir antes o buff do Ministro do Interior."
    default_enabled, default_interval = True, 20.0
    templates = [("bubble_food", "Bolha de comida pronta"), ("bubble_iron", "Bolha de ferro pronta"),
                 ("bubble_gold", "Bolha de ouro pronta"), ("bubble_truck", "Bolha do caminhão de recursos"),
                 ("bubble_other", "Bolha de outro recurso (minério, EXP, guia, parafuso, componentes, drone, petróleo)"),
                 ("btn_capitol", "Capitólio (onde se pede o cargo/buff)"),
                 ("minister_interior", "Cargo do Ministro do Interior"), ("btn_apply_buff", "Botão de pedir o buff")]
    fields = [Field("food", "Comida", "bool", True), Field("iron", "Ferro", "bool", True),
              Field("gold", "Ouro", "bool", True), Field("truck", "Caminhão", "bool", True),
              Field("other", "Outros (minério, EXP, guia, parafuso, componentes, drone, petróleo)", "bool", True),
              Field("minister", "Pedir antes o buff do Ministro do Interior", "bool", False),
              Field("threshold", "Limiar (bolhas brilham; a cor também é conferida)", "float", 0.65,
                    minimum=0.5, maximum=0.95)]

    def _minister(self, ctx):
        if ctx.counters.get("minister_buff"):
            return
        if not ctx.vision.has("minister_interior"):
            ctx.warn_once("minister", "⛁ Buff do Ministro: capture 'btn_capitol', 'minister_interior' e "
                                      "'btn_apply_buff' no Estúdio de imagens")
            return
        if ctx.tap("btn_capitol", 2, after=1.2) and ctx.tap("minister_interior", 2, after=1.0) \
                and ctx.tap("btn_apply_buff", 2, after=1.0):
            ctx.counters.add("minister_buff")
            ctx.log("⛁ Buff do Ministro do Interior pedido")
        ctx.go_home()

    def run(self, ctx, s):
        ctx.to_base()
        if s.get("minister"):
            self._minister(ctx)
            ctx.to_base()
        total = 0
        kinds = [k for k in ("food", "iron", "gold", "truck", "other") if s.get(k)]
        # um toque pode coletar várias bolhas de uma vez (no jogo, todas): toca UMA e olha de novo,
        # senão os toques seguintes caem em prédios vazios e abrem telas
        for _ in range(12):
            hit = next((h for k in kinds for h in ctx.find_all(f"bubble_{k}", float(s["threshold"]))), None)
            if not hit:
                break
            ctx.tap_xy(*hit, spread=2)
            total += 1
            ctx.sleep(1.0)
        if total:
            ctx.counters.add("bubbles", total)
            ctx.log(f"⛁ {total} coletas")


class Alliance(Task):
    id, name, icon, group = "alliance", "Aliança", "⬢", "Escavações & Diárias"
    description = "Ajuda os membros, coleta presentes (normais e premium), doa para a tecnologia recomendada e " \
                  "pega as recompensas da Estrela da Aliança aos domingos."
    default_enabled, default_interval = True, 15.0
    templates = [("btn_alliance_help", "Botão flutuante de ajuda (mãos)"),
                 ("btn_alliance_gifts", "Entrada de presentes da aliança"), ("btn_claim_all", "Coletar tudo"),
                 ("tab_gifts_premium", "Aba de presentes premium da aliança"),
                 ("btn_alliance_tech", "Entrada de tecnologia da aliança"),
                 ("tech_recommended", "Selo de tecnologia recomendada"),
                 ("btn_donate", "Botão de doar"), ("btn_donate_diamond", "Botão de doar com diamantes"),
                 ("btn_alliance_star", "Entrada da Estrela da Aliança")]
    fields = [Field("help", "Ajudar membros", "bool", True), Field("gifts", "Coletar presentes", "bool", True),
              Field("gifts_premium", "Também os presentes premium", "bool", True),
              Field("donate", "Doar tecnologia", "bool", True),
              Field("diamond_limit", "Doações com diamante por dia", "int", 0, minimum=0, maximum=100),
              Field("star", "Recompensas da Estrela da Aliança (domingo)", "bool", True)]

    def run(self, ctx, s):
        ctx.to_base()
        if s["help"]:
            n = 0
            while n < 10 and ctx.tap("btn_alliance_help", 0.8, after=0.3):
                n += 1
            if n:
                ctx.counters.add("alliance_help", n)
        if not ctx.tap("btn_alliance", 2):
            return
        if s["gifts"] and ctx.tap("btn_alliance_gifts", 2):
            ctx.tap("btn_claim_all", 2)
            if s.get("gifts_premium") and ctx.vision.has("tab_gifts_premium") and ctx.tap("tab_gifts_premium", 1.5):
                ctx.tap("btn_claim_all", 2)
            ctx.back()
        if s["donate"] and ctx.tap("btn_alliance_tech", 2):
            ctx.tap("tech_recommended", 2)
            for _ in range(20):
                if not ctx.tap("btn_donate", 1, after=0.2):
                    break
            while ctx.counters.get("diamond_donations") < int(s["diamond_limit"]):
                if not ctx.tap("btn_donate_diamond", 1, after=0.3):
                    break
                ctx.counters.add("diamond_donations")
            ctx.back()
        if s.get("star") and game_weekday(ctx) == 6 and not ctx.counters.get("alliance_star") \
                and ctx.vision.has("btn_alliance_star") and ctx.tap("btn_alliance_star", 2, after=1.0):
            n = 0
            while n < 8 and (ctx.tap("btn_claim_all", 1, after=0.6) or ctx.tap("btn_claim", 1, after=0.6)):
                n += 1
            ctx.counters.add("alliance_star")
            ctx.log("⬢ Estrela da Aliança: recompensas coletadas" if n else "⬢ Estrela da Aliança: nada a coletar")
        ctx.go_home()


class Daily(Task):
    id, name, icon, group = "daily", "Diárias: Loja, Trem, VIP", "✉", "Escavações & Diárias"
    description = "Brinde grátis e passes da loja, curtidas no trem, baú VIP, correio, energia grátis e " \
                  "recompensas de tarefas diárias."
    default_enabled, default_interval = True, 120.0
    templates = [("btn_mall", "Entrada da loja"), ("mall_free", "Brinde grátis da loja"),
                 ("mall_monthly", "Passe mensal na loja (resgate diário)"),
                 ("mall_weekly", "Brinde/passe semanal na loja"), ("mall_sovereign", "Passe do Soberano na loja"),
                 ("btn_train", "Entrada do trem"), ("btn_vip", "Entrada do VIP"), ("vip_chest", "Baú VIP grátis"),
                 ("btn_mail", "Correio"), ("btn_daily_tasks", "Tarefas diárias"), ("daily_chest", "Baú de atividade pronto")]
    fields = [Field("mall", "Brinde da loja", "bool", True),
              Field("mall_monthly", "Passe mensal (se você tiver)", "bool", True),
              Field("mall_weekly", "Brinde/passe semanal", "bool", True),
              Field("mall_sovereign", "Passe do Soberano (se você tiver)", "bool", True),
              Field("train", "Curtir trem", "bool", True),
              Field("vip", "Baú VIP", "bool", True), Field("mail", "Coletar correio", "bool", True),
              Field("energy", "Energia grátis do dia", "bool", True),
              Field("chests", "Baús de tarefas diárias", "bool", True)]
    cards = [("Base e recompensas grátis", [
        Card("Energia grátis", "⚡", "Pega a energia grátis do dia (barra de energia → Usar grátis).", toggle="energy"),
        Card("Presentes VIP", "♛", "Resgata o baú VIP diário.", toggle="vip"),
        Card("Correio", "✉", "Abre o correio e resgata tudo.", toggle="mail"),
        Card("Brindes da loja", "🛒", "Brinde diário e, se você tiver, passe mensal, semanal e do Soberano "
             "(passe só é resgatado se você tiver; nada é comprado).",
             toggle="mall", fields=["mall_monthly", "mall_weekly", "mall_sovereign"],
             summary=lambda s: "brinde" + "".join(f" · {n}" for k, n in (("mall_monthly", "mensal"),
                                                                       ("mall_weekly", "semanal"),
                                                                       ("mall_sovereign", "Soberano")) if s[k])),
        Card("Trem", "🚂", "Curte os trens (grátis).", toggle="train"),
        Card("Baús das tarefas diárias", "▣", "Resgata tarefas prontas e os baús de atividade.", toggle="chests"),
    ])]

    def _energy(self, ctx):
        if ctx.counters.get("free_energy") or not ctx.ai_on():
            return
        ctx.to_world()
        bar = ctx.ai("stamina_bar", ctx.frame())
        if not bar:
            return
        ctx.tap_xy(bar[0][0], bar[0][1], spread=2)
        ctx.sleep(1.0)
        hit = ctx.seen("stamina_use_free", 0.5, ctx.frame())
        if hit:
            ctx.tap_xy(hit[0], hit[1], spread=2)
            ctx.sleep(0.8)
            ctx.counters.add("free_energy")
            ctx.log("⚡ Energia grátis do dia coletada")
        else:
            ctx.counters.add("free_energy")  # já pega hoje: não abre de novo até o reset
        ctx.go_home()

    def run(self, ctx, s):
        if s.get("energy"):
            self._energy(ctx)
        ctx.to_base()
        if s["mall"] and ctx.tap("btn_mall", 2):
            if ctx.counters.get("mall_free") == 0 and ctx.tap("mall_free", 2):
                ctx.counters.add("mall_free")
            for k, label in (("mall_monthly", "passe mensal"), ("mall_weekly", "semanal"),
                             ("mall_sovereign", "passe do Soberano")):
                if s.get(k) and not ctx.counters.get(k) and ctx.vision.has(k) and ctx.tap(k, 1.5, after=1.0):
                    if ctx.tap("btn_claim", 1.5) or ctx.tap("btn_collect", 1.0):
                        ctx.log(f"🛒 Loja: {label} resgatado")
                    ctx.counters.add(k)
                    ctx.press_back()
            ctx.go_home()
        if s["train"] and ctx.tap("btn_train", 2):
            for _ in range(30):  # limite: um botão que não some não prende o bot
                if not ctx.tap("btn_like", 1, after=0.3):
                    break
                ctx.counters.add("train_likes")
            ctx.go_home()
        if s["vip"] and ctx.tap("btn_vip", 2):
            ctx.tap("vip_chest", 2) and ctx.tap("btn_claim", 1.5)
            ctx.go_home()
        if s["mail"] and ctx.tap("btn_mail", 2):
            ctx.tap("btn_claim_all", 2)
            ctx.go_home()
        if s["chests"] and ctx.tap("btn_daily_tasks", 2):
            for _ in range(30):
                if not ctx.tap("btn_claim", 1, after=0.5):
                    break
                ctx.counters.add("daily_claims")
            for x, y in ctx.find_all("daily_chest", 0.85):
                ctx.tap_xy(x, y)
                ctx.sleep(0.8)
                ctx.back()
            ctx.go_home()


SECRET_MODES = ["só coletar recompensas", "coletar + enviar novas"]
RARITIES = ["UR", "SSR", "SR"]


class SecretSquad(Task):
    id, name, icon, group = "secret_squad", "Missões Secretas", "✦", "Escavações & Diárias"
    description = "Posto de Comando Secreto: coleta as missões prontas, envia novas pela raridade, troca para o " \
                  "envio Mega no fim, assiste os aliados até 5/5 e abre os baús do Tesouro Escondido."
    default_enabled, default_interval = True, 30.0
    templates = [("btn_secret_squad", "Entrada do esquadrão secreto"), ("btn_quick_deploy", "Escalar automático")] + \
                [(f"mission_{l}", f"Selo de missão nível {l}") for l in LEVELS]
    fields = [Field("mode", "O que fazer", "choice", SECRET_MODES[1], options=SECRET_MODES),
              Field("ur", "Enviar UR", "bool", True), Field("ssr", "Enviar SSR", "bool", True),
              Field("sr", "Enviar SR", "bool", False),
              Field("mega_left", "Envio Mega quando restarem (tarefas; 0 = nunca)", "int", 4, minimum=0, maximum=20),
              Field("refresh_max", "Atualizar a lista grátis até (vezes)", "int", 1, minimum=0, maximum=10),
              Field("alt_days", "Outro nível nestes dias (ex.: sab, dom)", "text", ""),
              Field("alt_level", "…nível mínimo nesses dias", "choice", "SR", options=RARITIES),
              Field("star_days", "Missões com estrela só nestes dias (vazio = qualquer dia)", "text", ""),
              Field("ally", "Assistir missões dos aliados (até 5/5)", "bool", True),
              Field("ally_min", "…raridade mínima", "choice", "SR", options=RARITIES),
              Field("chests", "Baús do Tesouro Escondido / Aventura", "bool", True),
              Field("ghost", "Operações Fantasmas", "bool", False),
              Field("ghost_days", "…nos dias", "text", "qui"),
              Field("claim_only", "Apenas coletar (versões antigas)", "bool", False),
              Field("min_level", "Nível mínimo (sem IA)", "choice", "SSR", options=LEVELS)]
    cards = [
        ("Missões secretas", [
            Card("Missões secretas", "✦", "Coleta as prontas e envia novas das raridades marcadas.",
                 fields=["mode", "ur", "ssr", "sr"],
                 summary=lambda s: s["mode"] if s["mode"] == SECRET_MODES[0] else
                 "envia " + ("/".join(r for r in RARITIES if s[r.lower()]) or "nada")),
            Card("Envio Mega", "⏩", "Normal, depois Mega quando restarem poucas tarefas. Nunca troca para Mega se "
                 "ainda houver UR para enviar.", fields=["mega_left", "refresh_max"],
                 summary=lambda s: (f"Mega com {s['mega_left']} restando" if int(s["mega_left"]) else "sem Mega")
                 + (f" · atualiza {s['refresh_max']}x" if int(s["refresh_max"]) else "")),
            Card("Outro nível em alguns dias", "📅", "Nesses dias (do jogo) envia a partir de outro nível.",
                 fields=["alt_days", "alt_level"],
                 summary=lambda s: f"{s['alt_days']}: a partir de {s['alt_level']}" if s["alt_days"].strip()
                 else "desligado"),
            Card("Missões com estrela", "★", "Só envia missões com estrela/especiais nos dias escolhidos.",
                 fields=["star_days"], summary=lambda s: s["star_days"] or "qualquer dia"),
        ]),
        ("Aliados e baús", [
            Card("Missões dos aliados", "🤝", "Aba dos aliados → Assistir (de cima para baixo) até a cota 5/5.",
                 toggle="ally", fields=["ally_min"], summary="a partir de {ally_min}"),
            Card("Baús do Tesouro", "▣", "Abre os baús do Tesouro Escondido e de Aventura quando prontos.",
                 toggle="chests"),
            Card("Operações Fantasmas", "👻", "Envia as missões das Operações Fantasmas nos dias escolhidos.",
                 toggle="ghost", fields=["ghost_days"], summary="dias: {ghost_days}"),
        ]),
    ]

    # --- peças (classes da IA do Posto Secreto) -------------------------
    @staticmethod
    def _hit(ctx, cls, conf=0.4, f=None):
        d = ctx.dets(f, conf).get(cls, [])
        return d[0] if d else None

    def _tap_cls(self, ctx, cls, conf=0.4, after=1.0):
        b = self._hit(ctx, cls, conf, ctx.frame())
        if not b:
            return False
        ctx.tap_xy(b[0], b[1], spread=2)
        ctx.sleep(after)
        return True

    def _open(self, ctx):
        if ctx.go_home() is None:
            return False
        icon = ctx.ai_wait("btn_secret_squad", 3)
        if not icon:
            return False
        ctx.tap_xy(icon[0], icon[1], spread=2)
        ctx.sleep(1.5)
        f = ctx.frame()
        return bool(self._hit(ctx, "secret_tab_perso", 0.35, f) or self._hit(ctx, "secret_tab_perso_selected", 0.35, f)
                    or self._hit(ctx, "secret_task_card", 0.35, f))

    def _close_reward(self, ctx):
        for _ in range(3):
            f = ctx.frame()
            if self._hit(ctx, "secret_task_card", 0.35, f) or self._hit(ctx, "secret_tab_perso_selected", 0.35, f):
                return
            hit = ctx.seen("tap_close_text", 0.4, f)
            if hit:
                ctx.tap_xy(hit[0], hit[1], spread=2)
            else:
                ctx.key("esc")
            ctx.sleep(0.7)

    def _collect(self, ctx):
        n = 0
        while n < 6 and self._tap_cls(ctx, "secret_collect_btn", 0.45, after=1.5):
            n += 1
            self._close_reward(ctx)
        if n:
            ctx.counters.add("secret_collected", n)
            ctx.log(f"✦ {n} missão(ões) secreta(s) coletada(s)")
        return n

    def _cards(self, ctx, f):
        d = ctx.dets(f, 0.3)
        out = []
        for c in d.get("secret_task_card", []):
            rar = next((r for r in RARITIES for b in d.get(f"secret_rarity_{r.lower()}", []) if _box_has(c, b)), None)
            go = next((b for b in d.get("secret_go_btn", []) if _box_has(c, b)), None)
            red = sum(1 for b in d.get("secret_star_red", []) if _box_has(c, b))
            yel = sum(1 for b in d.get("secret_star_yellow", []) if _box_has(c, b))
            special = any(_box_has(c, b) for b in d.get("secret_special_badge", []))
            out.append({"box": c, "rar": rar, "go": go, "level": 5 + red if red else yel,
                        "star": special or red > 0})
        return out

    def _allowed(self, ctx, s):
        if str(s.get("alt_days", "")).strip() and day_in(ctx, s["alt_days"]):
            return set(RARITIES[:RARITIES.index(s.get("alt_level", "SR")) + 1])
        return {r for r in RARITIES if s.get(r.lower())}

    def _mega(self, ctx):
        """Normal → Mega: 'Mega envio' → 'Executar agora'. Popup de custo (com Cancelar) → cancela."""
        if not (self._tap_cls(ctx, "secret_mode_mega", 0.4) or self._hit(ctx, "secret_mega_deploy_btn", 0.4)):
            return False
        if not self._tap_cls(ctx, "secret_mega_deploy_btn", 0.4, after=1.2):
            return False
        self._tap_cls(ctx, "secret_mega_execute_btn", 0.4, after=1.2)
        f = ctx.frame()
        if ctx.seen("confirm_popup", 0.5, f) and ctx.seen("cancel_popup", 0.4, f):
            ctx.tap("btn_exit_cancel", 1.0)  # custa algo: não gasta
            ctx.log("✦ Envio Mega pede bilhetes/diamantes — cancelado")
            return False
        ctx.counters.add("secret_mega")
        ctx.log("✦ Envio Mega feito")
        self._tap_cls(ctx, "secret_mode_normal", 0.4)
        return True

    def _deploy(self, ctx, s, every=False):
        allowed = set(RARITIES) if every else self._allowed(ctx, s)
        star_ok = every or not str(s.get("star_days", "")).strip() or day_in(ctx, s["star_days"])
        refreshes, sent = 0, 0
        order = {r: i for i, r in enumerate(RARITIES)}
        for _ in range(10):
            f = ctx.frame()
            cards = self._cards(ctx, f)
            open_cards = [c for c in cards if c["go"]]
            ok = [c for c in open_cards if c["rar"] in allowed and (star_ok or not c["star"])]
            mega_left = int(s.get("mega_left", 0) or 0)
            if not every and mega_left and open_cards and len(open_cards) <= mega_left \
                    and not any(c["rar"] == "UR" for c in ok) and self._mega(ctx):
                break
            if ok:
                c = min(ok, key=lambda c: (order.get(c["rar"], 9), -c["level"]))
                ctx.tap_xy(c["go"][0], c["go"][1], spread=2)
                ctx.sleep(1.2)
                self._tap_cls(ctx, "secret_quick_deploy_btn", 0.4, after=0.8)
                f = ctx.frame()
                if self._hit(ctx, "secret_deploy_btn_off", 0.45, f) and not self._hit(ctx, "secret_deploy_btn", 0.5, f):
                    ctx.log("✦ Sem heróis livres para a missão")
                    ctx.press_back()
                    break
                if self._tap_cls(ctx, "secret_deploy_btn", 0.45, after=1.2):
                    sent += 1
                    ctx.counters.add("secret_missions")
                    ctx.log(f"✦ Missão {c['rar'] or ''} nível {c['level']} enviada")
                    continue
                ctx.press_back()
                break
            if refreshes < int(s.get("refresh_max", 0) or 0) and self._hit(ctx, "secret_refresh_btn", 0.45, f):
                self._tap_cls(ctx, "secret_refresh_btn", 0.45, after=1.2)
                refreshes += 1
                f = ctx.frame()
                if ctx.seen("confirm_popup", 0.5, f) and ctx.seen("cancel_popup", 0.4, f):
                    ctx.tap("btn_exit_cancel", 1.0)  # atualizar custaria bilhete/diamante
                    break
                continue
            break
        return sent

    def _ally(self, ctx, s):
        if not (self._tap_cls(ctx, "secret_tab_ally", 0.4) or self._hit(ctx, "secret_tab_ally_selected", 0.4)):
            return 0
        order = {r: i for i, r in enumerate(RARITIES)}
        limit = order.get(s.get("ally_min", "SR"), 2)
        n = 0
        for _ in range(5):
            f = ctx.frame()
            q = self._hit(ctx, "secret_quota_ally", 0.35, f) or self._hit(ctx, "secret_quota_ally_selected", 0.35, f)
            if q and ctx.ocr_on():
                h, w = f.shape[:2]
                txt = ctx.ocr.text(f, (max(0, (q[0] - q[3]) / w), max(0, (q[1] - q[4]) / h), 2 * q[3] / w,
                                       2 * q[4] / h))
                m = re.search(r"(\d)\s*[/7]\s*5", txt)
                if m and int(m.group(1)) >= 5:
                    break
            cards = self._cards(ctx, f)
            btns = sorted(ctx.dets(f, 0.4).get("secret_assist_btn", []), key=lambda b: b[1])
            pick = None
            for b in btns:
                card = next((c for c in cards if _box_has(c["box"], b)), None)
                if card is None or order.get(card["rar"], 0) <= limit:
                    pick = b
                    break
            if not pick:
                break
            ctx.tap_xy(pick[0], pick[1], spread=2)
            ctx.sleep(1.5)
            self._close_reward(ctx)
            n += 1
        if n:
            ctx.counters.add("secret_assists", n)
            ctx.log(f"🤝 {n} missão(ões) de aliado assistida(s)")
        self._tap_cls(ctx, "secret_tab_perso", 0.4)
        return n

    def _tab(self, ctx, cls):
        return self._tap_cls(ctx, cls, 0.4, after=1.2) or bool(self._hit(ctx, cls + "_selected", 0.4))

    def run(self, ctx, s):
        if not ctx.ai_on():
            return self._run_templates(ctx, s)
        if not self._open(ctx):
            ctx.go_home()
            return
        self._collect(ctx)
        if s.get("mode") != SECRET_MODES[0] and not s.get("claim_only"):
            self._deploy(ctx, s)
        if s.get("ally"):
            self._ally(ctx, s)
        if s.get("chests") and self._tab(ctx, "secret_post_tab_treasure"):
            self._collect(ctx)
            self._tab(ctx, "secret_post_tab_tasks")
        if s.get("ghost") and day_in(ctx, s.get("ghost_days", "qui")) and self._tab(ctx, "secret_post_tab_ghost"):
            self._collect(ctx)
            self._deploy(ctx, s, every=True)
            self._tab(ctx, "secret_post_tab_tasks")
        ctx.go_home()

    def _run_templates(self, ctx, s):
        ctx.to_base()
        if not ctx.tap("btn_secret_squad", 3):
            return
        n = 0
        while n < 6 and ctx.tap("btn_claim", 1, after=0.8):
            ctx.back()
            n += 1
        if s.get("mode") != SECRET_MODES[0] and not s["claim_only"]:
            for lvl in LEVELS[:LEVELS.index(s["min_level"]) + 1]:
                for x, y in ctx.find_all(f"mission_{lvl}", 0.85):
                    ctx.tap_xy(x, y)
                    ctx.sleep(0.6)
                    ctx.tap("btn_dispatch", 1.5)
                    ctx.tap("btn_quick_deploy", 1.5)
                    if ctx.tap("btn_confirm", 1.5):
                        ctx.counters.add("secret_missions")
                        ctx.log(f"✦ Missão {lvl} despachada")
        ctx.go_home()


TRUCK_MODES = ["um por um", "Mega (só Rena)"]


class Trucks(Task):
    id, name, icon, group = "trucks", "Caminhões", "⛟", "Escavações & Diárias"
    description = "Coleta caminhões que chegaram, envia novos renovando até o nível desejado e, se quiser, saqueia " \
                  "caminhões de outros com poder até o limite."
    default_interval = 30.0
    templates = [("btn_trucks", "Entrada dos caminhões/escolta"), ("btn_truck_claim", "Coletar caminhão"),
                 ("btn_truck_send", "Enviar caminhão"), ("btn_truck_refresh", "Renovar caminhão"),
                 ("btn_truck_mega", "Envio Mega de caminhões (Rena)"),
                 ("btn_plunder_list", "Lista de pilhagem (caminhões para saquear)")] + \
                [(f"truck_{l}", f"Caminhão nível {l}") for l in LEVELS[:3]]
    fields = [Field("send", "Enviar caminhões", "bool", True),
              Field("send_mode", "Como enviar", "choice", TRUCK_MODES[0], options=TRUCK_MODES),
              Field("level", "Nível mínimo", "choice", "SSR", options=LEVELS[:3]),
              Field("max_refresh", "Renovações gratuitas máx.", "int", 3, minimum=0, maximum=20),
              Field("send_days", "Só enviar nestes dias (vazio = todo dia)", "text", ""),
              Field("alt_days", "Outro nível nestes dias (ex.: sab, dom)", "text", ""),
              Field("alt_level", "…nível mínimo nesses dias", "choice", "SR", options=LEVELS[:3]),
              Field("plunder", "Saquear caminhões", "bool", False),
              Field("plunder_level", "Nível alvo (mínimo)", "choice", "UR", options=LEVELS[:3]),
              Field("plunder_power", "Poder máximo do inimigo (milhões; 0 = sem limite)", "float", 0.0, minimum=0,
                    maximum=100000),
              Field("plunder_count", "Saques por rodada", "int", 2, minimum=1, maximum=10),
              Field("plunder_daily", "Saques por dia (0 = ∞)", "int", 4, minimum=0, maximum=50)]
    cards = [
        ("Enviar", [
            Card("Enviar caminhões", "⛟", "Um por um, ou Mega (todos os Rena de uma vez; se não der, um por um). "
                 "Renova de graça até o nível mínimo.", toggle="send", fields=["send_mode", "level", "max_refresh"],
                 summary="{send_mode} · {level}+ · renova {max_refresh}x"),
            Card("Agenda semanal", "📅", "Dias do jogo em que envia, e outro nível mínimo em dias específicos.",
                 fields=["send_days", "alt_days", "alt_level"],
                 summary=lambda s: (s["send_days"] or "todo dia") + (f" · {s['alt_days']}: {s['alt_level']}+"
                                                                     if s["alt_days"].strip() else "")),
        ]),
        ("Saquear", [
            Card("Saquear caminhões", "⚔", "Abre a lista de pilhagem e ataca caminhões do nível escolhido com poder "
                 "até o limite (lido na linha). Desligado por padrão: ataque a outros jogadores.", toggle="plunder",
                 fields=["plunder_level", "plunder_power", "plunder_count", "plunder_daily"],
                 summary=lambda s: f"{s['plunder_level']}+ · poder ≤ {float(s['plunder_power']):g}M"
                 if float(s["plunder_power"]) else f"{s['plunder_level']}+ · qualquer poder"),
        ]),
    ]

    def _plunder(self, ctx, s):
        daily = int(s.get("plunder_daily", 0) or 0)
        if daily and ctx.counters.get("plunders") >= daily:
            return
        if not ctx.vision.has("btn_plunder_list") or not ctx.tap("btn_plunder_list", 2, after=1.2):
            ctx.warn_once("plunder", "⛟ Saquear: capture 'btn_plunder_list' (lista de pilhagem) no Estúdio")
            return
        allowed = LEVELS[:LEVELS.index(s.get("plunder_level", "UR")) + 1]
        maxp = float(s.get("plunder_power", 0) or 0)
        done = 0
        for _ in range(int(s.get("plunder_count", 2))):
            f = ctx.frame()
            rows = sorted(ctx.dets(f, 0.45).get("plunder_btn", []), key=lambda b: b[1])
            target = None
            for b in rows:
                h, w = f.shape[:2]
                t = ctx.ocr.text(f, (0.0, max(0.0, (b[1] - b[4]) / h), max(0.05, b[0] / w), 2 * b[4] / h)) \
                    if ctx.ocr_on() else ""
                lvl_ok = any(re.search(rf"\b{l}\b", t.upper()) for l in allowed) or not ctx.ocr_on()
                pw = _power_m(t)
                if lvl_ok and (not maxp or (pw is not None and pw <= maxp)):
                    target = b
                    break
            if not target:
                break
            ctx.tap_xy(target[0], target[1], spread=2)
            ctx.sleep(1.2)
            if not march(ctx, SQUADS):
                ctx.press_back()
                break
            done += 1
            ctx.counters.add("plunders")
            ctx.log("⛟ Caminhão saqueado")
            if daily and ctx.counters.get("plunders") >= daily:
                break
            if not ctx.tap("btn_plunder_list", 2, after=1.2):
                break
        ctx.press_back()

    def run(self, ctx, s):
        ctx.to_base()
        if not ctx.tap("btn_trucks", 3):
            return
        for _ in range(8):
            if not ctx.tap("btn_truck_claim", 1, after=0.8):
                break
            ctx.back()
            ctx.counters.add("trucks_claimed")
        days_ok = not str(s.get("send_days", "")).strip() or day_in(ctx, s["send_days"])
        if s["send"] and days_ok:
            lvl = s["alt_level"] if str(s.get("alt_days", "")).strip() and day_in(ctx, s["alt_days"]) else s["level"]
            mega = s.get("send_mode") == TRUCK_MODES[1] and ctx.vision.has("btn_truck_mega") \
                and ctx.tap("btn_truck_mega", 2, after=1.0)
            if mega and (ctx.tap("btn_depart", 2) or ctx.tap("btn_confirm", 1.5)):
                ctx.counters.add("trucks_sent")
                ctx.log("⛟ Caminhões enviados (Mega)")
            elif ctx.tap("btn_truck_send", 2):
                allowed = LEVELS[:LEVELS.index(lvl) + 1]
                for _ in range(int(s["max_refresh"]) + 1):
                    if any(ctx.vision.has(f"truck_{l}") and ctx.exists(f"truck_{l}", 0.86) for l in allowed):
                        break
                    if not ctx.tap("btn_truck_refresh", 1.5, after=1.0):
                        break
                if ctx.tap("btn_depart", 2):
                    ctx.counters.add("trucks_sent")
                    ctx.log("⛟ Caminhão enviado")
        if s.get("plunder"):
            self._plunder(ctx, s)
        ctx.go_home()


class Farm(Task):
    id, name, icon, group = "farm", "Coleta no Mapa", "⛰", "Escavações & Diárias"
    description = "Envia esquadrões livres para coletar recursos no mapa-múndi."
    default_interval = 20.0
    max_minutes = 20
    templates = [("search_food", "Aba comida na busca"), ("search_iron", "Aba ferro na busca"),
                 ("search_gold", "Aba ouro na busca")]
    fields = [Field(f"squad_{n}", f"Esquadrão {n}", "choice", "não enviar",
                    options=["não enviar", "food", "iron", "gold"]) for n in SQUADS] + [
        Field("skip_weekend", "Pular sexta e sábado", "bool", False)]

    def run(self, ctx, s):
        if s["skip_weekend"] and dt.date.today().weekday() in (4, 5):
            return
        for n in SQUADS:
            res = s[f"squad_{n}"]
            if res == "não enviar":
                continue
            ctx.to_world()
            if not (ctx.tap("btn_search", 2) and ctx.tap(f"search_{res}", 2) and ctx.tap("btn_go", 2, after=2.0)):
                break
            ctx.tap_rel(0.5, 0.5)
            ctx.sleep(0.8)
            if ctx.tap("btn_gather", 2) and march(ctx, [n]):
                ctx.counters.add("gathers")
                ctx.log(f"⛰ Esquadrão {n} coletando {res}")
        ctx.go_home()


class Arena(Task):
    id, name, icon, group = "arena", "Arena & Briga 3v3", "⚡", "Escavações & Diárias"
    description = "Faz as batalhas diárias grátis da arena tempestade (e 3v3) contra o oponente mais fraco visível."
    default_interval = 180.0
    templates = [("btn_arena", "Entrada da arena"), ("btn_brawl", "Entrada da briga 3v3"),
                 ("arena_no_tickets", "Sem tentativas grátis")]
    fields = [Field("battles", "Batalhas na arena por dia", "int", 5, minimum=0, maximum=30),
              Field("brawl", "Batalhas na 3v3 por dia", "int", 0, minimum=0, maximum=50)]

    def _fight(self, ctx, entry, key, limit):
        if limit <= 0 or ctx.counters.get(key) >= limit or not ctx.tap(entry, 3):
            return
        while ctx.counters.get(key) < limit:
            if (ctx.vision.has("arena_no_tickets") and ctx.exists("arena_no_tickets", 0.86)) \
                    or not ctx.tap("btn_challenge", 2):
                break
            if not ctx.tap("btn_battle", 2, after=1.5):
                break
            ctx.tap("btn_skip", 4)
            ctx.sleep(1.0)
            ctx.back()
            ctx.counters.add(key)
        ctx.go_home()

    def run(self, ctx, s):
        ctx.to_base()
        self._fight(ctx, "btn_arena", "arena", int(s["battles"]))
        self._fight(ctx, "btn_brawl", "brawl", int(s["brawl"]))


# ---------------------------------------------------------------- rallies e eventos
RALLY_BOSSES = [("gold", "Zumbi Dourado"), ("doom", "Elite da Perdição"), ("doomwalker", "Doomwalker"),
                ("vanguard", "Vanguarda"), ("eliteinstructor", "Instrutor de Elite"), ("eliteforces", "Forças de Elite"),
                ("marshal", "Guarda do Marechal"), ("giantcrocodile", "Crocodilo Gigante"), ("slugger", "Slugger"),
                ("skypredator", "Predador do Céu"), ("sandworm", "Verme da Areia"), ("oniwagon", "Oni Wagon"),
                ("plaguemarauder", "Saqueador da Praga"), ("custom", "Chefe personalizado")]
# Nome do chefe na linha do rally (OCR), sem acento/minúsculas. PT conferido no dicionário do jogo (locale pt.json).
RALLY_BOSS_TEXT = {
    "gold": ["dourad", "golden", "gold zombie"],
    "doom": ["juizo final", "elite do apocalipse", "doom elite", "perdicao"],
    "doomwalker": ["doom walker", "doomwalker"],
    "vanguard": ["vanguarda", "vanguard"],
    "eliteinstructor": ["instrutor elite", "instrutor de elite", "elite instructor"],
    "eliteforces": ["tropas de elite", "forcas de elite", "elite forces"],
    "marshal": ["marechal", "marshal"],
    "giantcrocodile": ["crocodil"],
    "slugger": ["slugger"],
    "skypredator": ["predador do ceu", "sky predator"],
    "sandworm": ["verme da areia", "vermes da areia", "sandworm"],
    "oniwagon": ["oniwagon", "oni wagon"],
    "plaguemarauder": ["saqueador da praga", "plague marauder"],
}


POSITIONS = ["1+", "2+", "3+", "4", "2 ou 3"]
POSITION_HELP = ("1+ entra na hora · 2+ espera 1 jogador ter entrado · 3+ espera dois · 4 só pega o último lugar · "
                 "'2 ou 3' sorteia um dos dois")
_POS_DRAW = {}


def _others_needed(pos, key=None):
    """Quantos OUTROS jogadores (além do líder) precisam ter entrado antes de nós. '2 ou 3' sorteia uma vez por
    mobilização (key), para não mudar de ideia a cada olhada."""
    if pos == "2 ou 3":
        if key not in _POS_DRAW:
            if len(_POS_DRAW) > 200:
                _POS_DRAW.clear()
            _POS_DRAW[key] = random.choice((1, 2))
        return _POS_DRAW[key]
    return {"1+": 0, "2+": 1, "3+": 2, "4": 3}.get(str(pos), 0)


def _names(text):
    return [norm(n) for n in re.split(r"[,;|\n]", str(text or "")) if n.strip()]


def _squad_summary(n):
    def f(s):
        if not s.get(f"sq{n}_on", True):
            return "não entra"
        lo, hi = int(s.get(f"sq{n}_min", 0) or 0), int(s.get(f"sq{n}_max", 0) or 0)
        lv = f"Nv {lo or 1}–{hi}" if hi else (f"Nv {lo}+" if lo else "qualquer nível")
        return f"{lv} · posição {s.get(f'sq{n}_pos', '1+')}"
    return f


class AutoJoin(Task):
    id, name, icon, group = "auto_join", "Auto-Entrar em Rallies", "⚔", "Rallies & Eventos"
    description = "Quando aparece o alerta de rally (mira vermelha), abre a lista e entra nos rallies dos chefes " \
                  "escolhidos; cada esquadrão tem sua faixa de nível e sua posição na mobilização."
    default_interval = 0.5
    templates = [("rally_alert", "Ícone de mira vermelha com contador na lateral (há rallies ativos)"),
                 ("btn_join_rally", "Quadrado cinza com '+' verde: vaga para entrar no rally"),
                 ("full_queue", "Retratos dos esquadrões com X vermelho (fila de marcha cheia)"),
                 ("btn_hospital", "Hospital (na base)")] + \
                [(f"rally_{k}", f"Retrato/ícone do chefe: {n}") for k, n in RALLY_BOSSES]
    fields = [Field("any_boss", "Entrar em QUALQUER rally (ignora a lista de chefes)", "bool", False)] + \
             [Field(f"boss_{k}", n, "bool", k in ("gold", "marshal")) for k, n in RALLY_BOSSES] + [
        Field("daily_limit", "Limite de entradas/dia por chefe (0 = ∞)", "int", 0, minimum=0, maximum=999),
        Field("max_level", "Nível máximo do chefe para todos (0 = qualquer)", "int", 0, minimum=0, maximum=999),
        Field("squad_order", "Ordem de esquadrões (sem o esquadrão inteligente)", "text", "3,2,4,1"),
        Field("smart_squad", "Esquadrão inteligente", "bool", True),
    ] + [f for n in SQUADS for f in (
        Field(f"sq{n}_on", f"Esquadrão {n} entra", "bool", True),
        Field(f"sq{n}_min", f"Esquadrão {n}: nível mínimo do chefe (0 = qualquer)", "int", 0, minimum=0, maximum=999),
        Field(f"sq{n}_max", f"Esquadrão {n}: nível máximo do chefe (0 = qualquer)", "int", 0, minimum=0, maximum=999),
        Field(f"sq{n}_pos", f"Esquadrão {n}: posição na mobilização", "choice", "1+", options=POSITIONS,
              hint=POSITION_HELP))] + [
        Field("join_anyway", "Entrar mesmo assim se a posição não vier", "bool", True),
        Field("join_anyway_s", "…depois de (s)", "int", 15, minimum=3, maximum=300),
        Field("weak_ok", "Confirmar o aviso 'esquadrão fraco demais'", "bool", False),
        Field("max_rally_min", "Ignorar mobilizações que faltam mais de (min, 0 = não ignorar)", "int", 0,
              minimum=0, maximum=60),
        Field("blacklist", "Lista negra: nunca entrar nas mobilizações destes jogadores (vírgula)", "text", ""),
        Field("whitelist", "Lista branca: entrar mesmo fora das regras de nível e posição (vírgula)", "text", ""),
        Field("check_digs", "Verificar escavações depois das entradas", "bool", True),
        Field("heal_after", "Curar a cada N entradas — de (0 = nunca)", "int", 10, minimum=0, maximum=100),
        Field("heal_after_max", "…até N entradas (sorteio)", "int", 15, minimum=0, maximum=100),
        Field("heal_batch_min", "Curar em lotes de — mínimo (0 = tudo de uma vez)", "int", 0, minimum=0,
              maximum=100000),
        Field("heal_batch_max", "…máximo", "int", 0, minimum=0, maximum=100000),
        Field("delay_before", "Espera antes de marchar (s)", "float", 0.0, minimum=0, maximum=30),
        Field("delay_after", "Espera depois de cada entrada (s)", "float", 0.0, minimum=0, maximum=60),
    ]
    main_capable = True
    cards = [
        ("Chefes para entrar", [
            Card("Qualquer rally", "✱", "Entra em qualquer rally aberto, sem olhar o chefe.", toggle="any_boss",
                 summary=lambda s: "todos os rallies" if s["any_boss"] else "só os chefes ligados abaixo"),
        ] + [Card(n, "☠", f"Rallies de {n}. Acha pelo nome na linha (OCR) ou pela imagem 'rally_{k}'.",
                  toggle=f"boss_{k}") for k, n in RALLY_BOSSES]),
        ("Esquadrões", [
            Card(f"Esquadrão {n}", "⚑", "Liga/desliga, faixa de nível do chefe e posição na mobilização. "
                 + POSITION_HELP + ".", toggle=f"sq{n}_on", fields=[f"sq{n}_min", f"sq{n}_max", f"sq{n}_pos"],
                 summary=_squad_summary(n)) for n in SQUADS
        ] + [
            Card("Esquadrão inteligente", "◎", "Ligado: vai o esquadrão de faixa de nível mais BAIXA que ainda serve "
                 "para o chefe; os fortes ficam para os chefes grandes. Desligado: segue a ordem.",
                 toggle="smart_squad", fields=["squad_order"],
                 summary=lambda s: "o mais fraco que serve" if s["smart_squad"] else f"ordem {s['squad_order']}"),
        ]),
        ("Durante as entradas", [
            Card("Limite diário", "⏳", "Máximo de entradas por dia em cada chefe.", fields=["daily_limit"],
                 summary=lambda s: f"no máximo {s['daily_limit']} por dia" if int(s["daily_limit"]) else "sem limite"),
            Card("Nível máximo geral", "▲", "Teto para todos os esquadrões (lido na linha do rally).",
                 fields=["max_level"],
                 summary=lambda s: f"até Nv.{s['max_level']}" if int(s.get("max_level", 0) or 0) else "qualquer nível"),
            Card("Entrar mesmo assim", "↻", "Se a posição escolhida não vier a tempo, entra em qualquer posição livre "
                 "(as regras de nível continuam valendo).", toggle="join_anyway", fields=["join_anyway_s"],
                 summary=lambda s: f"após {s['join_anyway_s']} s" if s["join_anyway"] else "só na posição certa"),
            Card("Esquadrões fracos também vão", "⚠", "Depois de Marchar, confirma o aviso 'seu esquadrão é fraco "
                 "demais'.", toggle="weak_ok"),
            Card("Mobilizações longas", "⌛", "Ignora mobilizações que ainda faltam muitos minutos para sair.",
                 fields=["max_rally_min"],
                 summary=lambda s: f"ignora > {s['max_rally_min']} min" if int(s["max_rally_min"]) else "entra em todas"),
            Card("Verificar escavações", "⛏", "Depois das entradas dá uma passada nas escavações, ovos e presentes "
                 "(usa as configurações de Escavações & Ovos).", toggle="check_digs"),
            Card("Curar tropas", "✚", "Cura os feridos a cada algumas entradas (sorteio na faixa), em lotes para "
                 "a aliança ajudar em cada um.",
                 fields=["heal_after", "heal_after_max", "heal_batch_min", "heal_batch_max"],
                 summary=lambda s: (f"a cada {s['heal_after']}–{max(s['heal_after'], s['heal_after_max'])} entradas"
                                    + (f" · lotes {s['heal_batch_min']}–{s['heal_batch_max']}"
                                       if int(s["heal_batch_min"]) else "")) if int(s["heal_after"]) else "nunca"),
            Card("Esperas", "◷", "Esperas extras em volta de cada entrada (variam ±20 %).",
                 fields=["delay_before", "delay_after"],
                 summary=lambda s: (f"{float(s['delay_before']):g}s antes · {float(s['delay_after']):g}s depois"
                                    if float(s["delay_before"]) or float(s["delay_after"]) else "sem espera")),
        ]),
        ("Listas de jogadores", [
            Card("Lista negra", "⛔", "Nunca entra nas mobilizações destes jogadores (nomes separados por vírgula; "
                 "basta um pedaço do nome).", fields=["blacklist"],
                 summary=lambda s: f"{len(_names(s['blacklist']))} jogador(es)" if _names(s["blacklist"]) else "vazia"),
            Card("Lista branca", "★", "Entra nas mobilizações destes jogadores mesmo fora das regras de nível e "
                 "posição.", fields=["whitelist"],
                 summary=lambda s: f"{len(_names(s['whitelist']))} jogador(es)" if _names(s["whitelist"]) else "vazia"),
        ]),
    ]

    def __init__(self):
        self._seen = {}        # mobilização -> primeira vez vista (para 'entrar mesmo assim')
        self._next_heal = None

    def _open_list(self, ctx):
        """Atalho pelo alerta de rally; CONFIRMA que a lista abriu. O alerta às vezes leva ao mapa (Ponto de
        Reunião da Aliança) em vez da lista — aí vai por Aliança › Guerra."""
        if ctx.vision.has("rally_alert") or ctx.ai_on("rally_alert"):
            if not ctx.exists("rally_alert", 0.8):
                return False  # sem alerta = sem rally ativo: nem abre nada
            if not ctx.tap("rally_alert", 1.5, 0.8, after=1.2):
                return False
            if not ctx.ai_on() or ctx.expect("alliance_war", 3):
                return True
            ctx.log("⚔ O alerta não abriu a lista de rallies — indo por Aliança › Guerra")
            ctx.go_home()
        elif not ctx.ai_on():
            ctx.to_world()
            return ctx.tap("btn_alliance", 2) and ctx.tap("tab_alliance_war", 2, after=1.2)
        if not ctx.step("abrir Aliança", lambda: ctx.tap("btn_alliance", 2, after=1.0),
                        ("panel", "alliance_war", "alliance_tech", "event", "unknown"), 3):
            return False
        return bool(ctx.step("aba Guerra", lambda: ctx.tap("tab_alliance_war", 2, after=1.2), "alliance_war", 3))

    @staticmethod
    def _row(ctx, slot):
        """Lê a linha do '+' (OCR à esquerda dele): chefe, nível ('Nv. 26'), quantos já entraram ('2/5'), quanto
        falta para sair ('04:32') e o texto inteiro (para as listas de jogadores)."""
        info = {"key": None, "lvl": 0, "joined": None, "left": None, "text": ""}
        if not ctx.ocr_on():
            return info
        f = ctx.frame(fresh=False)
        h, w = f.shape[:2]
        x, y = slot
        region = (max(0.0, x / w - 0.45), max(0.0, y / h - 0.07), min(0.45, x / w), 0.14)
        raw = ctx.ocr.text(f, region)
        t = norm(raw)  # norm() tira a barra: "2/5" → "25"; a contagem é lida no texto cru
        info["text"] = t
        m = re.search(r"\b(?:nv|lv|nivel)\s*\.?\s*(\d{1,3})\b", t)
        info["lvl"] = int(m.group(1)) if m else 0
        m = re.search(r"\b(\d)\s*/\s*(\d)\b", raw)
        if m and 0 < int(m.group(2)) <= 9:
            info["joined"] = int(m.group(1))
        m = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", t)
        if m:
            a, b, c = m.groups()
            info["left"] = int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
        for k, keys in RALLY_BOSS_TEXT.items():
            if any(kw in t for kw in keys):
                info["key"] = k
                break
        return info

    @staticmethod
    def _squads_for(s, lvl, white):
        """Esquadrões que podem ir num chefe deste nível, na ordem certa."""
        order = [q for q in (parse_list(s["squad_order"]) or SQUADS) if q in SQUADS]
        order += [q for q in SQUADS if q not in order]
        ok = []
        for q in order:
            if not s.get(f"sq{q}_on", True):
                continue
            lo, hi = int(s.get(f"sq{q}_min", 0) or 0), int(s.get(f"sq{q}_max", 0) or 0)
            if lvl and not white and ((lo and lvl < lo) or (hi and lvl > hi)):
                continue
            ok.append(q)
        if s.get("smart_squad", True):  # o de faixa mais baixa que serve primeiro (sort é estável: empate = ordem)
            ok.sort(key=lambda q: int(s.get(f"sq{q}_max", 0) or 0) or 10 ** 6)
        return ok

    def _pick(self, ctx, s, slots):
        """Melhor vaga entre as visíveis: (nível, vaga, chefe, esquadrões) ou None."""
        top = int(s.get("max_level", 0) or 0)
        black, white = _names(s.get("blacklist")), _names(s.get("whitelist"))
        limit = int(s["daily_limit"])
        frame_h = ctx.frame(fresh=False).shape[0]
        tmpl = {}  # chefe pela imagem capturada, se houver
        for k, _ in RALLY_BOSSES:
            if s.get(f"boss_{k}") and ctx.vision.has(f"rally_{k}"):
                hit = ctx.find(f"rally_{k}", 0.84, text=False)
                if hit:
                    tmpl[k] = hit
        cands, now = [], time.time()
        for slot in slots:
            r = self._row(ctx, slot)
            key = next((k for k, hit in tmpl.items() if abs(hit[1] - slot[1]) < frame_h * 0.12), r["key"])
            if not s["any_boss"] and (not key or not s.get(f"boss_{key}")):
                continue
            key = key or "any"
            if limit and ctx.counters.get(f"join_{key}") >= limit:
                continue
            if any(b in r["text"] for b in black):
                continue
            is_white = any(n in r["text"] for n in white)
            lvl = r["lvl"]
            if top and lvl > top and not is_white:
                continue
            mx = int(s.get("max_rally_min", 0) or 0)
            if mx and r["left"] and r["left"] > mx * 60:
                continue
            squads = self._squads_for(s, lvl, is_white)
            if not squads:
                continue
            rid = (key, lvl, r["text"][:24])
            if not is_white:
                need = _others_needed(s.get(f"sq{squads[0]}_pos", "1+"), rid)
                if need:
                    first = self._seen.setdefault(rid, now)
                    others = (r["joined"] - 1) if r["joined"] else None
                    late = s.get("join_anyway", True) and now - first >= int(s.get("join_anyway_s", 15))
                    if not ((others is not None and others >= need) or late):
                        continue  # ainda não chegou a nossa posição
            cands.append((lvl, slot, key, squads))
        if len(self._seen) > 300:
            self._seen.clear()
        return max(cands, key=lambda c: c[0]) if cands else None

    def run(self, ctx, s):
        if not ctx.knows("btn_join_rally"):
            ctx.warn_once("join", "⚔ Capture 'btn_join_rally' (o '+' verde da vaga) no Estúdio")
            return
        if not self._open_list(ctx):
            self._after(ctx, s)
            return
        names = dict(RALLY_BOSSES)
        joined = False
        for _ in range(4):  # entra em até 4 rallies por execução (um por esquadrão)
            if ctx.vision.has("full_queue") and ctx.exists("full_queue", 0.85):
                ctx.log("⚔ Fila de marcha cheia — aguardando esquadrões voltarem")
                break
            slots = ctx.find_all("btn_join_rally", 0.85)
            if not slots:
                break
            pick = self._pick(ctx, s, slots)
            if not pick:
                break
            lvl, target, key, squads = pick
            label = names.get(key, "rally") + (f" Nv.{lvl}" if lvl else "")
            ctx.tap_xy(*target, spread=2)
            ctx.sleep(1.0)
            if float(s["delay_before"]):
                ctx.sleep(float(s["delay_before"]) * random.uniform(0.8, 1.2))
            sq = march(ctx, squads, weak_ok=s.get("weak_ok", False))
            if not sq:
                ctx.back()
                break
            joined = True
            n = ctx.counters.add(f"join_{key}")
            ctx.counters.add("joins_total")
            ctx.log(f"⚔ Entrou no rally {label} (esq. {sq}) — {n} hoje")
            ctx.sleep(1.5)
            if float(s.get("delay_after", 0)):
                ctx.sleep(float(s["delay_after"]) * random.uniform(0.8, 1.2))
            if self._heal_due(ctx, s):
                heal_troops(ctx, s.get("heal_batch_min", 0), s.get("heal_batch_max", 0))
                break
        ctx.go_home()
        self._after(ctx, s)
        return joined

    def _heal_due(self, ctx, s):
        lo = int(s.get("heal_after", 0) or 0)
        if not lo:
            return False
        total = ctx.counters.get("joins_total")
        if self._next_heal is None or self._next_heal < total - 100 or self._next_heal > total + 200:
            self._next_heal = total + random.randint(lo, max(lo, int(s.get("heal_after_max", lo) or lo)))
        if total >= self._next_heal:
            self._next_heal = None
            return True
        return False

    @staticmethod
    def _after(ctx, s):
        """Depois das entradas: uma passada nas escavações/ovos/presentes (usa as configurações delas)."""
        if s.get("check_digs", True):
            check_digs(ctx)


def check_digs(ctx):
    """Passada rápida em escavações, ovos e presentes no meio de outra tarefa (configurações de Escavações & Ovos).
    A escavação devolve a vez sozinha quando o cronômetro ainda está longe."""
    dig = ctx.e.task_by_id("auto_digs")
    if not dig:
        return False
    try:
        return bool(dig.run(ctx, ctx.e.cfg.task(dig.id, dig.defaults())))
    except RuntimeError:
        return False


def heal_troops(ctx, batch_min=0, batch_max=0, ask_help=True):
    """Cura pela ambulância do HUD do mapa (fluxo do LWFarmBot): coleta os já curados, abre, põe a quantidade do
    lote (se pedido), Curar e toca de novo na ambulância para pedir ajuda da aliança. Sem a ambulância (IA
    desligada / outra versão), cai no Hospital da base."""
    if ctx.ai_on("hospital_icon") and ctx.to_world():
        for _ in range(2):  # soldados já curados primeiro (senão a ambulância só mostra a cura pronta)
            done = ctx.ai("healed_troops", ctx.frame())
            if not done:
                break
            ctx.tap_xy(done[0][0], done[0][1], spread=2)
            ctx.sleep(1.0)
            ctx.log("✚ Soldados curados coletados")
        amb = ctx.ai("hospital_icon", ctx.frame())
        if not amb:
            ctx.go_home()
            return False  # sem ambulância = ninguém ferido
        ax, ay = amb[0][0], amb[0][1]
        ctx.tap_xy(ax, ay, spread=2)
        ctx.sleep(1.2)
        lo, hi = int(batch_min or 0), int(batch_max or 0)
        if lo:
            n = random.randint(lo, max(lo, hi))
            box = ctx.ai("heal_input", ctx.frame())
            if box:
                ctx.tap_xy(box[0][0], box[0][1], spread=1)
                ctx.sleep(0.3)
                for _ in range(7):
                    ctx.key("backspace")
                ctx.type(str(n))
                ctx.key("enter")
                ctx.sleep(0.4)
        if not ctx.tap("btn_heal", 2, after=1.0):
            ctx.log("✚ Hospital aberto, mas sem botão Curar (cura em andamento ou faltam recursos)")
            ctx.go_home()
            return False
        ctx.counters.add("heals")
        ctx.log("✚ Feridos em cura" + (f" (lote de {n})" if lo else ""))
        if ask_help and ctx.ai("hospital_icon", ctx.frame()):
            ctx.tap_xy(ax, ay, spread=2)  # de novo na ambulância = pedir ajuda da aliança
            ctx.sleep(0.8)
        ctx.go_home()
        return True
    ctx.to_base()
    ok = bool(ctx.tap("btn_hospital", 2) and ctx.tap("btn_heal", 2))
    if ok:
        ctx.counters.add("heals")
        ctx.log("✚ Tropas curadas")
    ctx.go_home()
    return ok


def heal(ctx):
    return heal_troops(ctx)


ENERGY_PERIODS = ["por evento (7 dias)", "por dia", "por sessão"]
HUNT_FINISH = ["continuar entrando em mobilizações", "voltar para Escavações & Ovos", "parar o bot"]
ZOMBIE_TYPES = [("tank", "Tanque"), ("air", "Avião"), ("missile", "Míssil")]
COST_HUNT, COST_RALLY = 10, 20  # energia por zumbi pequeno / por mobilização iniciada


def energy_used(ctx, s):
    """Energia já gasta no período escolhido (QB: 'Energia usada 0/500')."""
    period = s.get("energy_period", ENERGY_PERIODS[0])
    if period == "por dia":
        return ctx.counters.get("hunt_energy")
    if period == "por sessão":
        return ctx.e.session.get("hunt_energy", 0)
    since = s.get("energy_since") or ""
    try:
        old = (dt.date.today() - dt.date.fromisoformat(since)).days >= 7
    except ValueError:
        old = True
    if old:  # o evento dura 3 dias e volta a cada 2 semanas: 7 dias sem gastar = começa outro orçamento
        s["energy_used"], s["energy_since"] = 0, dt.date.today().isoformat()
    return int(s.get("energy_used", 0) or 0)


def spend_energy(ctx, s, n):
    ctx.counters.add("hunt_energy", n)
    if not s.get("energy_since"):
        s["energy_since"] = dt.date.today().isoformat()
    s["energy_used"] = int(s.get("energy_used", 0) or 0) + n


class Hunt(Task):
    id, name, icon, group = "hunt", "Zumbis Dourados & Rally", "☣", "Rallies & Eventos"
    description = "Caça zumbis e inicia mobilizações de chefes com a energia que você reservar; entre uma marcha e " \
                  "outra entra em mobilizações e passa nas escavações."
    max_minutes = 30
    default_interval = 5.0
    templates = [("search_zombie", "Aba Zumbi na busca"), ("search_doom", "Aba Elite da Perdição na busca"),
                 ("search_gold_zombie", "Aba Zumbi Dourado na busca"),
                 ("btn_level_minus", "Botão - do nível"), ("btn_level_plus", "Botão + do nível"),
                 ("btn_rally_confirm", "Confirmar duração do rally"), ("no_stamina", "Aviso de sem stamina"),
                 ("btn_event_rewards", "Botão de coletar recompensas do evento Zumbis Dourados")] + \
                [(f"zombie_type_{k}", f"Filtro de tipo de zumbi na busca: {n}") for k, n in ZOMBIE_TYPES]
    fields = [
        Field("mode", "Alvo", "choice", "gold_zombie", options=["zombie", "gold_zombie", "doom"]),
        Field("hunt_on", "Caçar zumbis pequenos (10 de energia cada)", "bool", True),
        Field("level", "Nível do zumbi", "int", 1, minimum=1, maximum=100),
        Field("climb", "Subir 1 nível a cada vitória", "bool", False),
        Field("max_level", "Nível máximo ao subir", "int", 30, minimum=1, maximum=100),
    ] + [Field(f"hunt_sq{n}", f"Esquadrão {n} caça", "bool", n == "1") for n in SQUADS] + [
        Field("keep_hunting", "Continuar caçando (sem esperar voltar à base)", "bool", True),
    ] + [Field(f"ztype_{k}", f"Tipo {n}", "bool", k == "tank") for k, n in ZOMBIE_TYPES] + [
        Field("rally", "Iniciar mobilizações de chefes (20 de energia cada)", "bool", False),
    ] + [f for n in SQUADS for f in (
        Field(f"rally_sq{n}", f"Esquadrão {n} inicia", "bool", False),
        Field(f"rally_sq{n}_min", f"Esquadrão {n}: nível do chefe de", "int", 1, minimum=1, maximum=100),
        Field(f"rally_sq{n}_max", f"…até", "int", 100, minimum=1, maximum=100))] + [
        Field("rally_high_first", "Chefes de nível mais alto primeiro", "bool", True),
        Field("join", "Entrar também nas mobilizações (usa Auto-Entrar em Rallies)", "bool", True),
        Field("energy_budget", "Gastar no máximo (energia; 0 = sem limite)", "int", 500, minimum=0, maximum=100000),
        Field("energy_period", "Com que frequência", "choice", ENERGY_PERIODS[0], options=ENERGY_PERIODS),
        Field("energy_used", "Energia já usada neste período (ponha 0 para zerar)", "int", 0, minimum=0,
              maximum=100000),
        Field("free_energy", "Usar energia grátis quando acabar", "bool", True),
        Field("use_scrolls", "Usar pergaminhos de energia do inventário", "bool", True),
        Field("max_attacks", "Marchas por rodada", "int", 6, minimum=1, maximum=50),
        Field("daily_limit", "Limite diário de caçadas (0 = ∞)", "int", 0, minimum=0, maximum=999),
        Field("check_digs", "Verificar escavações entre as marchas", "bool", True),
        Field("heal", "Curar tropas", "bool", True),
        Field("heal_batch_min", "Curar em lotes de — mínimo (0 = tudo)", "int", 0, minimum=0, maximum=100000),
        Field("heal_batch_max", "…máximo", "int", 0, minimum=0, maximum=100000),
        Field("collect_rewards", "Coletar as recompensas do evento no final", "bool", True),
        Field("on_finish", "Quando a energia acabar", "choice", HUNT_FINISH[0], options=HUNT_FINISH),
        Field("squad_order", "Ordem de esquadrões (versões antigas)", "text", "1,2,3,4"),
    ]
    main_capable = True
    cards = [
        ("O que fazer", [
            Card("Caçar zumbis pequenos", "☣", "10 de energia cada. Esquadrões que caçam, nível e se continua caçando "
                 "sem esperar o esquadrão voltar.", toggle="hunt_on",
                 fields=["mode", "level", "climb", "max_level"] + [f"hunt_sq{n}" for n in SQUADS] + ["keep_hunting"],
                 summary=lambda s: "esquadrões " + (",".join(n for n in SQUADS if s.get(f"hunt_sq{n}")) or "nenhum")
                 + f" · nv {s['level']}" + (" · sobe" if s["climb"] else "")),
            Card("Tipo de zumbi", "◈", "Filtra o tipo na busca (precisa das imagens 'zombie_type_…' no Estúdio).",
                 fields=[f"ztype_{k}" for k, _ in ZOMBIE_TYPES],
                 summary=lambda s: ", ".join(n for k, n in ZOMBIE_TYPES if s.get(f"ztype_{k}")) or "qualquer"),
            Card("Iniciar mobilizações", "⚑", "20 de energia cada. Cada esquadrão líder com sua faixa de nível do "
                 "chefe; começa pelos de nível mais alto.", toggle="rally",
                 fields=[k for n in SQUADS for k in (f"rally_sq{n}", f"rally_sq{n}_min", f"rally_sq{n}_max")]
                 + ["rally_high_first"],
                 summary=lambda s: "líderes " + (",".join(n for n in SQUADS if s.get(f"rally_sq{n}")) or "nenhum")),
            Card("Entrar em mobilizações", "⚔", "Grátis. Usa as regras da página Auto-Entrar em Rallies (esquadrões, "
                 "níveis, posição, listas).", toggle="join"),
        ]),
        ("Energia", [
            Card("Energia a usar", "⚡", "UM orçamento para caçada + mobilizações iniciadas. Parar/Iniciar continuam "
                 "de onde parou; ponha 0 em 'já usada' para zerar.",
                 fields=["energy_budget", "energy_period", "energy_used"],
                 summary=lambda s: (f"{s['energy_used']}/{s['energy_budget']} · {s['energy_period']}"
                                    if int(s["energy_budget"]) else "sem limite")),
            Card("Recarregar energia", "↺", "Quando acabar: primeiro a energia grátis, depois os pergaminhos do "
                 "inventário. Nunca compra com diamantes.", fields=["free_energy", "use_scrolls"],
                 summary=lambda s: " + ".join(x for x, on in (("grátis", s["free_energy"]),
                                                              ("pergaminhos", s["use_scrolls"])) if on) or "não recarrega"),
            Card("Limites", "⏳", "Marchas por rodada e caçadas por dia.", fields=["max_attacks", "daily_limit"],
                 summary=lambda s: f"{s['max_attacks']} por rodada · " +
                                   (f"{s['daily_limit']}/dia" if int(s["daily_limit"]) else "sem limite diário")),
        ]),
        ("Durante a sessão", [
            Card("Verificar escavações", "⛏", "Entre as marchas dá uma passada no chat da aliança (escavações, ovos, "
                 "presentes).", toggle="check_digs"),
            Card("Curar tropas", "✚", "Cura pedindo ajuda da aliança, em lotes se quiser.", toggle="heal",
                 fields=["heal_batch_min", "heal_batch_max"],
                 summary=lambda s: ("lotes " + f"{s['heal_batch_min']}–{s['heal_batch_max']}"
                                    if int(s["heal_batch_min"]) else "tudo de uma vez") if s["heal"] else "não cura"),
            Card("Ao terminar", "⚑", "Quando a energia acaba: coleta as recompensas, cura e depois…",
                 fields=["collect_rewards", "on_finish"], summary="{on_finish}"),
        ]),
    ]

    def _search(self, ctx, s, level):
        """Busca do mapa no alvo e nível pedidos; deixa o alvo aberto no centro. False = não deu."""
        ctx.to_world()
        if not (ctx.tap("btn_search", 2) and ctx.tap(f"search_{s['mode']}", 2)):
            return False
        for k, _ in ZOMBIE_TYPES:
            if s.get(f"ztype_{k}") and ctx.vision.has(f"zombie_type_{k}"):
                ctx.tap(f"zombie_type_{k}", 1.0, after=0.3)
        for _ in range(100):
            if not ctx.tap("btn_level_minus", 0.3, after=0.05):
                break
        for _ in range(int(level) - 1):
            ctx.tap("btn_level_plus", 0.5, after=0.08)
        if not ctx.tap("btn_go", 2, after=2.0):
            return False
        ctx.tap_rel(0.5, 0.5)
        ctx.sleep(0.8)
        return True

    def _no_energy(self, ctx, s):
        """Aviso de sem energia: recarrega (grátis → pergaminhos) se permitido. True = continua sem energia."""
        f = ctx.frame()
        empty = (ctx.vision.has("no_stamina") and ctx.exists("no_stamina", 0.85)) or ctx.seen("stamina_out", 0.5, f)
        if not empty:
            return False
        if s.get("free_energy") and ctx.ai("btn_stamina_use", f):
            hit = ctx.seen("stamina_use_free", 0.5, f)
            if hit:
                ctx.tap_xy(hit[0], hit[1], spread=2)
                ctx.sleep(0.8)
                ctx.log("☣ Energia grátis usada")
                return False
        if s.get("use_scrolls"):
            hit = ctx.seen("stamina_use_btn", 0.5, f)
            if hit:
                ctx.tap_xy(hit[0], hit[1], spread=2)
                ctx.sleep(0.8)
                ctx.log("☣ Pergaminho de energia usado")
                return False
        ctx.log("☣ Sem energia", "warn")
        ctx.go_home()
        return True

    def _actions(self, s):
        """O que tentar nesta marcha, em ordem: mobilizações primeiro (rendem mais), depois caçada."""
        out = []
        if s.get("rally"):
            leaders = [n for n in SQUADS if s.get(f"rally_sq{n}")] or ["1"]
            hi = s.get("rally_high_first", True)
            seen = set()
            for q in sorted(leaders, key=lambda q: -int(s.get(f"rally_sq{q}_max", 100)) if hi else 0):
                lvl = int(s.get(f"rally_sq{q}_max" if hi else f"rally_sq{q}_min", 1) or 1)
                if lvl in seen:
                    continue
                seen.add(lvl)  # um líder ocupado → tenta o próximo líder (outro nível) antes da caçada
                fits = [n for n in leaders if int(s.get(f"rally_sq{n}_min", 1)) <= lvl <= int(s.get(f"rally_sq{n}_max", 100))]
                out.append(("rally", lvl, fits or [q], COST_RALLY))
        if s.get("hunt_on", True):
            hunters = [n for n in SQUADS if s.get(f"hunt_sq{n}")] or parse_list(s.get("squad_order")) or SQUADS
            out.append(("hunt", int(s["level"]), hunters, COST_HUNT))
        return out

    def run(self, ctx, s):
        budget = int(s.get("energy_budget", 0) or 0)
        joiner = ctx.e.task_by_id("auto_join")
        marched = 0
        finished = False
        for _ in range(int(s["max_attacks"])):
            if int(s["daily_limit"]) and ctx.counters.get("hunts") >= int(s["daily_limit"]):
                ctx.log("☣ Limite diário de caçadas atingido")
                finished = True
                break
            used = energy_used(ctx, s)
            acts = [a for a in self._actions(s) if not budget or used + a[3] <= budget]
            if not acts:
                ctx.log(f"☣ Orçamento de energia gasto ({used}/{budget})")
                finished = True
                break
            done = False
            for kind, lvl, squads, cost in acts:
                if not self._search(ctx, s, lvl):
                    continue
                if kind == "rally":
                    if not ctx.tap("btn_rally", 2):
                        ctx.go_home()
                        continue
                    ctx.tap("btn_rally_confirm", 1.5)
                elif not ctx.tap("btn_attack", 2):
                    ctx.go_home()
                    continue
                if self._no_energy(ctx, s):
                    finished = True
                    break
                sq = march(ctx, squads)
                if not sq:
                    ctx.back()
                    ctx.go_home()
                    continue  # nenhum esquadrão desta função livre: tenta a outra ação
                spend_energy(ctx, s, cost)
                marched += 1
                done = True
                if kind == "hunt":
                    ctx.counters.add("hunts")
                    if s["climb"] and int(s["level"]) < int(s["max_level"]):
                        s["level"] = int(s["level"]) + 1
                        ctx.log(f"☣ Próximo alvo: nível {s['level']}")
                    ctx.log(f"☣ Caçando zumbi Nv.{lvl} (esq. {sq}) — energia {energy_used(ctx, s)}"
                            + (f"/{budget}" if budget else ""))
                else:
                    ctx.counters.add("hunt_rallies")
                    ctx.log(f"⚑ Mobilização iniciada Nv.{lvl} (esq. {sq})")
                ctx.sleep(1.2)
                break
            if finished or not done:
                break
            if s.get("join") and joiner:
                joiner.run(ctx, ctx.e.cfg.task(joiner.id, joiner.defaults()))
            elif s.get("check_digs", True):
                check_digs(ctx)
            if not s.get("keep_hunting", True):
                break
        if not marched and s.get("join") and joiner and not finished:
            joiner.run(ctx, ctx.e.cfg.task(joiner.id, joiner.defaults()))  # sem energia/alvo: ao menos entra
        if s["heal"] and (marched or finished):
            heal_troops(ctx, s.get("heal_batch_min", 0), s.get("heal_batch_max", 0))
        if finished:
            self._finish(ctx, s)
        ctx.go_home()

    def _finish(self, ctx, s):
        if s.get("collect_rewards") and ctx.vision.has("btn_event_rewards"):
            if ctx.tap("btn_event_rewards", 2, after=1.0):
                ctx.tap("btn_claim_all", 1.5) or ctx.tap("btn_claim", 1.5)
                ctx.log("☣ Recompensas do evento coletadas")
            ctx.go_home()
        what = s.get("on_finish", HUNT_FINISH[0])
        if what == HUNT_FINISH[1] and ctx.e.cfg.data.get("main_task") == self.id:
            ctx.e.cfg.data["main_task"] = "auto_digs"
            ctx.log("☣ Energia acabou — o foco do bot volta para Escavações & Ovos")
            ctx.e._emit()
        elif what == HUNT_FINISH[2]:
            ctx.log("☣ Energia acabou — parando o bot")
            ctx.e.stop()


class MarshalGuard(Task):
    id, name, icon, group = "marshal_guard", "Guarda do Marechal", "♜", "Rallies & Eventos"
    description = "No Exercício da Aliança (Marechal): um esquadrão inicia mobilizações e os outros entram; fica até " \
                  "o fim do exercício (30 min) e volta à tarefa principal."
    default_interval = 2.0
    max_minutes = 35
    templates = [("btn_marshal_event", "Entrada/ícone do evento Guarda do Marechal"),
                 ("marshal_target", "O Marechal no mapa (ou o botão de ir até ele)")]
    fields = [Field("start", "Iniciar mobilizações", "bool", True),
              Field("start_squad", "Esquadrão que inicia", "choice", "1", options=SQUADS),
              Field("join", "Entrar nas mobilizações da aliança", "bool", True),
              Field("join_squads", "Esquadrões que entram", "text", "2,3,4"),
              Field("join_pos", "Posição de entrada", "choice", "1+", options=POSITIONS, hint=POSITION_HELP),
              Field("daily_limit", "Limitar entradas diárias a (0 = ∞)", "int", 0, minimum=0, maximum=999),
              Field("stay_min", "Ficar no máximo (min)", "int", 30, minimum=1, maximum=60),
              Field("check_digs", "Verificar escavações durante o exercício", "bool", True),
              Field("heal", "Curar tropas", "bool", True),
              Field("heal_limit", "…limitar tropas curadas por vez (0 = tudo)", "int", 0, minimum=0, maximum=100000)]
    cards = [
        ("O que fazer", [
            Card("Iniciar mobilizações", "⚑", "Dica: um esquadrão com 1 herói e sem tropas (mobilização que falhar "
                 "não custa tropas).", toggle="start", fields=["start_squad"], summary="esquadrão {start_squad}"),
            Card("Entrar em mobilizações", "⚔", "Use os esquadrões mais fortes: as recompensas dependem do dano. "
                 "Depois de algumas entradas o dano chega ao máximo — limite as entradas diárias.", toggle="join",
                 fields=["join_squads", "join_pos", "daily_limit"],
                 summary=lambda s: f"esq. {s['join_squads']} · posição {s['join_pos']}"
                 + (f" · {s['daily_limit']}/dia" if int(s["daily_limit"]) else "")),
        ]),
        ("Durante o exercício", [
            Card("Verificar escavações", "⛏", "Após cada entrada e com os esquadrões fora.", toggle="check_digs"),
            Card("Curar tropas", "✚", "Cura os feridos, com limite por vez se quiser.", toggle="heal",
                 fields=["heal_limit"],
                 summary=lambda s: (f"até {s['heal_limit']} por vez" if int(s["heal_limit"]) else "tudo")
                 if s["heal"] else "não cura"),
            Card("Quando sair", "⏱", "O exercício dura 30 min; sai assim que ele termina.", fields=["stay_min"],
                 summary="no máximo {stay_min} min"),
        ]),
    ]

    def _pass(self, ctx, s):
        """Uma passada: inicia (se der) e entra. True = o Marechal ainda está aí."""
        lim = int(s["daily_limit"])
        found = False
        if s["start"] and not (lim and ctx.counters.get("marshal") >= lim):
            ctx.to_world()
            if ctx.tap("btn_marshal_event", 2, after=1.5) or ctx.tap("marshal_target", 2, after=1.5):
                found = True
                ctx.tap_rel(0.5, 0.5)
                ctx.sleep(0.8)
                if ctx.tap("btn_rally", 2):
                    ctx.tap("btn_rally_confirm", 1.5)
                    if march(ctx, [s["start_squad"]]):
                        ctx.counters.add("marshal")
                        ctx.log(f"♜ Mobilização do Marechal iniciada (esq. {s['start_squad']})")
            ctx.go_home()
        if s["join"] and not (lim and ctx.counters.get("join_marshal") >= lim):
            joiner = AutoJoin()
            js = dict(ctx.e.cfg.task(joiner.id, joiner.defaults()))
            js.update({f"boss_{k}": k == "marshal" for k, _ in RALLY_BOSSES})
            js.update({"any_boss": False, "squad_order": s["join_squads"], "check_digs": False, "heal_after": 0,
                       "daily_limit": lim})
            wanted = [q for q in parse_list(s["join_squads"]) if q in SQUADS]
            for q in SQUADS:
                js[f"sq{q}_on"] = q in wanted
                js[f"sq{q}_min"], js[f"sq{q}_max"] = 0, 0
                js[f"sq{q}_pos"] = s.get("join_pos", "1+")
            if joiner.run(ctx, js):
                found = True
        if s.get("check_digs", True):
            check_digs(ctx)
        return found

    def run(self, ctx, s):
        end = time.time() + int(s.get("stay_min", 30)) * 60
        idle, seen = 0, False
        while time.time() < end:
            if self._pass(ctx, s):
                idle, seen = 0, True
            else:
                idle += 1
                if idle >= (2 if seen else 1):  # sem Marechal = exercício acabou (ou nem começou)
                    break
            ctx.sleep(20)
        if s.get("heal"):
            n = int(s.get("heal_limit", 0) or 0)
            heal_troops(ctx, n, n)
        ctx.go_home()


HERO_MODES = ["bilhetes de recrutamento", "EXP de herói"]
DRONE_TARGETS = ["melhorar o drone", "Elite da Destruição", "Zumbis"]


class ArmsRace(Task):
    id, name, icon, group = "arms_race", "Corrida Armamentista", "🏁", "Rallies & Eventos"
    description = "Lê o tema atual da Corrida (OCR) e roda o módulo certo para buscar a caixa do topo da rodada."
    default_interval = 30.0
    templates = [("btn_arms_race", "Entrada da Corrida Armamentista (ícone de eventos)"),
                 ("btn_train_troops", "Treinar tropas (no quartel)"), ("btn_barracks", "Quartel"),
                 ("btn_recruit", "Recrutar heróis"), ("btn_drone", "Tela do drone"), ("btn_drone_up", "Melhorar drone"),
                 ("btn_research", "Laboratório / pesquisa"), ("btn_speedup", "Usar aceleração"),
                 ("btn_hero_levelup", "Botão de subir nível do herói (EXP)")]
    fields = [Field("units", "Tropas: treinar", "bool", True), Field("heroes", "Heróis: recrutar", "bool", False),
              Field("drone", "Drone: melhorar", "bool", True), Field("tech", "Pesquisa: acelerar", "bool", False),
              Field("city", "Construção: acelerar", "bool", False),
              Field("kill", "Abates: rodar Zumbis/Rally", "bool", True),
              Field("reset_time", "Início da 1ª faixa no seu relógio (meia-noite do servidor)", "text", "23:00",
                    hint="A Corrida tem 6 faixas de 4 h por dia; a 1ª começa na meia-noite do servidor"),
              Field("collect", "Coletar os baús da Corrida", "bool", True),
              Field("target", "Meta de baús por faixa (depois disso não insiste)", "choice", "3",
                    options=["1", "2", "3", "máx"]),
              Field("stop_full", "Parar quando já tiver 18/18 baús do dia", "bool", True),
              Field("speedups", "Acelerações por rodada (construção/pesquisa)", "int", 1, minimum=0, maximum=20),
              Field("hero_mode", "Heróis: como ganhar os pontos", "choice", HERO_MODES[0], options=HERO_MODES),
              Field("hero_name", "…herói que recebe a EXP (nome, como no jogo)", "text", ""),
              Field("hero_ups", "…melhorias por rodada", "int", 3, minimum=1, maximum=30),
              Field("drone_target", "Drone: o que fazer", "choice", DRONE_TARGETS[0], options=DRONE_TARGETS),
              Field("drone_level", "…nível da Elite / do zumbi", "int", 30, minimum=1, maximum=100),
              Field("drone_attacks", "…ataques por rodada", "int", 3, minimum=1, maximum=20),
              Field("drone_squads", "…esquadrões", "text", "1,2,3")]
    cards = [
        ("Quais temas fazer", [
            Card("Tropas", "⚔", "Treina tropas no quartel no tema de Unidades.", toggle="units"),
            Card("Heróis", "★", "Pontos com bilhetes de recrutamento, ou EXP de herói para o herói escolhido.",
                 toggle="heroes", fields=["hero_mode", "hero_name", "hero_ups"],
                 summary=lambda s: s["hero_mode"] + (f" · {s['hero_name']}" if s["hero_mode"] == HERO_MODES[1]
                                                     and s["hero_name"].strip() else "")),
            Card("Drone", "✈", "Melhora o drone, ou ataca Elites da Destruição / zumbis com energia (usa a página "
                 "Zumbis Dourados, com o nível e os esquadrões daqui).", toggle="drone",
                 fields=["drone_target", "drone_level", "drone_attacks", "drone_squads"],
                 summary=lambda s: s["drone_target"] + ("" if s["drone_target"] == DRONE_TARGETS[0]
                                                        else f" Nv.{s['drone_level']}")),
            Card("Pesquisa", "⚗", "Usa aceleração na pesquisa no tema de Tecnologia.", toggle="tech"),
            Card("Construção", "⚒", "Usa aceleração na construção no tema de Cidade.", toggle="city"),
            Card("Abates", "☠", "Roda Zumbis/Rally no tema de Abates.", toggle="kill"),
        ]),
        ("Faixas e baús", [
            Card("Horário das faixas", "◷", "6 faixas de 4 h por dia, a partir da meia-noite do servidor.",
                 fields=["reset_time"], summary="1ª faixa às {reset_time}"),
            Card("Baús", "▣", "Coleta os baús de pontos e do dia; para quando bater a meta da faixa.",
                 toggle="collect", fields=["target", "stop_full"],
                 summary=lambda s: f"meta {s['target']} por faixa" + (" · para em 18/18" if s["stop_full"] else "")),
            Card("Acelerações", "⏩", "Quantas acelerações usar por rodada nos temas de construção e pesquisa "
                                      "(0 = nenhuma).", fields=["speedups"], summary="até {speedups} por rodada"),
        ]),
    ]

    @staticmethod
    def stage(reset_time, now=None):
        """Faixa atual da Corrida: (número 1–6, início 'HHh', fim 'HHh', minutos até acabar, 'MMDD' do início)."""
        now = now or dt.datetime.now()
        try:
            h, m = map(int, str(reset_time).split(":"))
        except ValueError:
            h, m = 23, 0
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if start > now:
            start -= dt.timedelta(days=1)
        mins = int((now - start).total_seconds() // 60)
        n = mins // 240
        a = start + dt.timedelta(minutes=240 * n)
        b = a + dt.timedelta(minutes=240)
        return n + 1, a.strftime("%Hh"), b.strftime("%Hh"), int((b - now).total_seconds() // 60), a.strftime("%m%d")

    def _open(self, ctx):
        """Abre o painel da Corrida: imagem sua (btn_arms_race) ou Eventos → aba da Corrida (pela IA)."""
        if ctx.vision.has("btn_arms_race"):
            if not ctx.tap("btn_arms_race", 2, after=1.2):
                return False
        elif not ctx.tap("btn_events", 2, after=1.5):
            return False
        if ctx.ai_wait("arms_score", 2.5):
            return True
        if ctx.tap_text(ARMS_RACE_TAB, 2, after=1.2):  # aba pelo nome, se a IA não confirmou
            return bool(ctx.ai_wait("arms_score", 2.5)) or True
        return True  # sem confirmação da IA: segue pelo texto do tema

    def theme(self, ctx):
        txt = ctx.read_text(region=(0.0, 0.05, 1.0, 0.45))
        t = norm(txt)
        for key, words in ARMS_RACE_THEMES.items():
            if any(norm(w) in t for w in words):
                return key
        return None

    def _chests(self, ctx, s, st_key):
        """Coleta baús; devolve True se o dia já está completo (18/18) e a opção de parar está ligada."""
        txt = ctx.read_text(region=(0.0, 0.0, 1.0, 0.6))
        m = re.search(r"(\d{1,2})\s*/\s*18\b", txt)
        if m and s.get("stop_full") and int(m.group(1)) >= 18:
            ctx.log("🏁 18/18 baús do dia — nada mais a fazer hoje na Corrida")
            return True
        if not s.get("collect"):
            return False
        cap = 99 if s.get("target") == "máx" else int(s.get("target") or 3)
        got = ctx.counters.get(st_key)
        tried = []
        for _ in range(4):  # um baú por vez, olhando a tela de novo a cada um
            if got >= cap:
                break
            hits = [h for name in ("arms_chest_day", "arms_chest") for h in sorted(ctx.find_all(name),
                                                                                   key=lambda h: -h[0])]
            hits = [h for h in hits if all(abs(h[0] - t[0]) > 20 or abs(h[1] - t[1]) > 20 for t in tried)]
            if not hits:
                break
            x, y = hits[0]
            tried.append((x, y))
            ctx.tap_xy(x, y, spread=2)
            ctx.sleep(1.0)
            if ctx.seen("reward_message", 0.4) or ctx.lone_confirm():
                got = ctx.counters.add(st_key)
                ctx.log(f"🏁 Baú da Corrida coletado ({got}/{cap if cap < 99 else 'máx'} nesta faixa)")
            if not ctx.ai("arms_score"):  # abriu um popup (recompensa ou prévia do baú): fecha e confere
                ctx.press_back()
                if not ctx.ai("arms_score", ctx.frame()):
                    break  # saiu do painel: não toca mais às cegas
        return False

    def _heroes(self, ctx, s):
        if s.get("hero_mode") == HERO_MODES[1] and str(s.get("hero_name", "")).strip():
            if not ctx.tap("btn_heroes", 2, after=1.2):
                return
            if not ctx.tap_text([s["hero_name"].strip()], 2, after=1.2):
                ctx.log(f"🏁 Herói '{s['hero_name']}' não achado na lista", "warn")
                return
            ups = 0
            for _ in range(int(s.get("hero_ups", 3))):
                if not ctx.tap("btn_hero_levelup", 1.2, after=0.5):
                    break
                ups += 1
            ctx.log(f"🏁 EXP de herói: {ups} melhoria(s) em {s['hero_name']}" if ups else
                    "🏁 Sem botão de melhorar (capture 'btn_hero_levelup' ou falta EXP)")
            return
        if ctx.tap("btn_recruit", 2):
            ctx.tap("btn_confirm", 1.5)

    def _drone_fight(self, ctx, s):
        hunt = ctx.e.task_by_id("hunt")
        if not hunt:
            return
        hs = dict(ctx.e.cfg.task(hunt.id, hunt.defaults()))
        elite = s.get("drone_target") == DRONE_TARGETS[1]
        squads = [q for q in parse_list(s.get("drone_squads")) if q in SQUADS] or ["1"]
        lvl = int(s.get("drone_level", 30))
        hs.update({"mode": "doom" if elite else "zombie", "level": lvl, "climb": False, "join": False,
                   "hunt_on": not elite, "rally": elite, "max_attacks": int(s.get("drone_attacks", 3)),
                   "energy_budget": 0, "on_finish": HUNT_FINISH[0], "daily_limit": 0})
        for q in SQUADS:
            hs[f"hunt_sq{q}"] = q in squads and not elite
            hs[f"rally_sq{q}"] = q in squads and elite
            hs[f"rally_sq{q}_min"], hs[f"rally_sq{q}_max"] = lvl, lvl
        ctx.log("🏁 Drone: " + ("mobilizações contra a Elite" if elite else "zumbis") + f" Nv.{lvl}")
        hunt.run(ctx, hs)

    def run(self, ctx, s):
        n, a, b, left, day = self.stage(s.get("reset_time", "23:00"))
        st_key = f"arms_chests_{day}_{n}"  # baús desta faixa, deste dia
        ctx.log(f"🏁 Corrida: faixa {n}/6 ({a}–{b}), acaba em {left // 60}h{left % 60:02d}")
        if not self._open(ctx):
            ctx.log("🏁 Não consegui abrir a Corrida (capture 'btn_arms_race' no Estúdio se a IA não achar)", "warn")
            return
        th = self.theme(ctx)
        done = self._chests(ctx, s, st_key)
        ctx.go_home()
        if done:
            return
        if not th:
            ctx.log("🏁 Tema da Corrida não identificado", "warn")
            return
        ctx.log(f"🏁 Tema atual: {th}")
        if not s.get(th):
            return
        if th in ("tech", "city") and int(s.get("speedups", 1)) <= 0:
            ctx.log("🏁 Acelerações em 0 — tema de construção/pesquisa pulado")
            return
        ctx.to_base()
        if th == "units" and ctx.tap("btn_barracks", 2):
            ctx.tap("btn_train_troops", 2) and ctx.tap("btn_confirm", 1.5)
        elif th == "heroes":
            self._heroes(ctx, s)
        elif th == "drone" and s.get("drone_target", DRONE_TARGETS[0]) != DRONE_TARGETS[0]:
            self._drone_fight(ctx, s)
        elif th == "drone" and ctx.tap("btn_drone", 2):
            for _ in range(5):
                if not ctx.tap("btn_drone_up", 1.2, after=0.4):
                    break
        elif th in ("tech", "city") and ctx.tap("btn_research" if th == "tech" else "btn_speedup", 2):
            for _ in range(int(s.get("speedups", 1))):
                if not (ctx.tap("btn_speedup", 1.5) and ctx.tap("btn_use", 1.5)):
                    break
        elif th == "kill":
            ctx.e.run_now("hunt")
        ctx.go_home()


class FirstLady(Task):
    id, name, icon, group = "first_lady", "Primeira-Dama / Cargos", "♛", "Rallies & Eventos"
    description = "Para quem tem o cargo: aprova os pedidos de cargos do capitólio por ordem de chegada."
    default_interval = 1.0
    templates = [("btn_capitol", "Entrada do capitólio/cargos"), ("fl_position", "Cargo com pedidos pendentes"),
                 ("btn_applicants", "Lista de candidatos")]
    fields = [Field("max_per_run", "Aprovações por execução", "int", 10, minimum=1, maximum=100)]

    def run(self, ctx, s):
        if not ctx.tap("btn_capitol", 2):
            return
        done = 0
        for x, y in ctx.find_all("fl_position", 0.85):
            ctx.tap_xy(x, y)
            ctx.sleep(0.6)
            ctx.tap("btn_applicants", 1.2)
            while done < int(s["max_per_run"]) and ctx.tap("btn_appoint", 1.2, after=0.5):
                ctx.tap("btn_confirm", 1)
                done += 1
            ctx.back()
        if done:
            ctx.counters.add("appointments", done)
            ctx.log(f"♛ {done} cargo(s) aprovados")
        ctx.go_home()


# ---------------------------------------------------------------- relatórios e mapa
REPORT_DAYS = ["todo dia", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
REPORT_KINDS = [("vs", "VS semanal", "tab_vs_week"), ("vs_daily", "VS diário", "tab_vs"),
                ("donation", "Doação diária", "tab_donation"), ("donation_week", "Doação semanal", "tab_donation_week"),
                ("kills", "Pontuações de mortes", "tab_kills")]


def _xlsx(path, rows):
    """Planilha .xlsx mínima (só texto e números) sem precisar do openpyxl."""
    import zipfile
    from xml.sax.saxutils import escape

    def cell(ref, v):
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'

    cols = "ABCDEFGHIJ"
    body = "".join(f'<row r="{i}">' + "".join(cell(f"{cols[j]}{i}", v) for j, v in enumerate(r)) + "</row>"
                   for i, r in enumerate(rows, 1))
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.'
                               'org/package/2006/content-types"><Default Extension="rels" ContentType="application/'
                               'vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType='
                               '"application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/'
                               'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName='
                               '"/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                               'spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                       'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
                       'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/'
                           'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
                           'relationships"><sheets><sheet name="Relatorio" sheetId="1" r:id="rId1"/></sheets>'
                           '</workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
                                      'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type='
                                      '"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
                                      ' Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.'
                                    'openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + body +
                                    '</sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


class Reports(Task):
    id, name, icon, group = "reports", "Relatórios R4/R5", "▤", "Relatórios & Mapa"
    description = "Abre o ranking (VS semanal/diário, doações diária/semanal, mortes), lê nomes e pontos por OCR e " \
                  "salva em Excel, Texto e CSV, no horário agendado."
    default_interval = 15.0
    templates = [("btn_alliance_ranking", "Ranking da aliança"), ("tab_vs", "Aba VS do dia"),
                 ("tab_vs_week", "Aba VS da semana"), ("tab_donation", "Aba doações de hoje"),
                 ("tab_donation_week", "Aba doações da semana"), ("tab_kills", "Aba abates")]
    fields = [Field(k, label, "bool", k in ("vs", "donation")) for k, label, _ in REPORT_KINDS] + [
        Field("when", "Executar em", "choice", "todo dia", options=REPORT_DAYS),
        Field("at", "…às (HH:MM, hora do PC)", "text", "09:00"),
        Field("xlsx", "Salvar em Excel (.xlsx)", "bool", True), Field("txt", "Salvar em Texto (.txt)", "bool", True),
        Field("csv", "Salvar em CSV (.csv)", "bool", True),
        Field("keep", "Manter só os últimos (relatórios de cada tipo)", "int", 10, minimum=1, maximum=500),
        Field("pages", "Páginas a rolar", "int", 12, minimum=1, maximum=60),
        Field("last_run", "Último relatório (automático)", "text", "")]
    cards = [
        ("Relatórios", [Card(label, "▤", f"Abre o ranking '{label}' e salva a lista inteira.", toggle=k)
                        for k, label, _ in REPORT_KINDS]),
        ("Agendar e arquivos", [
            Card("Agendar", "◷", "Com o bot rodando, cria os relatórios a partir deste horário (num momento seguro) e "
                 "continua o que estava fazendo. 'Executar agora' na página funciona com o bot parado.",
                 fields=["when", "at"], summary=lambda s: f"{s['when']} às {s['at']}" + (
                     f" · último {s['last_run']}" if s.get("last_run") else "")),
            Card("Arquivos", "📁", "Formatos e quantos guardar (o mais antigo de cada tipo é apagado).",
                 fields=["xlsx", "txt", "csv", "keep", "pages"],
                 summary=lambda s: "salva em " + (", ".join(n for k, n in (("xlsx", "Excel"), ("txt", "Texto"),
                                                                         ("csv", "CSV")) if s[k]) or "CSV")
                 + f"; mantém {s['keep']}"),
        ]),
    ]

    @staticmethod
    def parse(lines):
        rows = {}
        for ln in lines:
            m = re.match(r"^\s*(?:\d{1,3}[.)\s]+)?(.+?)\s+([\d][\d.,]{2,})\s*$", ln.text)
            if m:
                name = m.group(1).strip(" .:-|")
                val = int(re.sub(r"[.,]", "", m.group(2)))
                if len(name) >= 2:
                    rows[name] = max(val, rows.get(name, 0))
        return rows

    def _due(self, s, ctx):
        """Agendado para hoje e já passou da hora, e ainda não rodou hoje? 'Executar agora' sempre roda."""
        if ctx.forced:
            return True
        if int(s.get("interval_min", 15) or 15) >= 1440:
            s["interval_min"] = 15  # versões antigas rodavam 1x por dia: agora confere o horário a cada 15 min
        today = dt.date.today().isoformat()
        if s.get("last_run", "").startswith(today):
            return False
        when = s.get("when", "todo dia")
        if when != "todo dia" and REPORT_DAYS.index(when) - 1 != dt.date.today().weekday():
            return False
        t = _hm(s.get("at", "09:00"))
        now = dt.datetime.now()
        return t is None or now.hour * 60 + now.minute >= t

    def _save(self, s, key, rows):
        stamp = f"{dt.datetime.now():%Y-%m-%d_%H%M}"
        table = [["posição", "nome", "pontos"]] + [[i, k, v] for i, (k, v) in
                                                   enumerate(sorted(rows.items(), key=lambda kv: -kv[1]), 1)]
        made = []
        if s.get("csv", True) or not (s.get("xlsx") or s.get("txt")):
            path = os.path.join(REPORT_DIR, f"{key}_{stamp}.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh, delimiter=";").writerows(table)
            made.append(path)
        if s.get("txt"):
            path = os.path.join(REPORT_DIR, f"{key}_{stamp}.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(f"{r[0]:>4}  {str(r[1])[:28]:<28}  {r[2]}" for r in table[1:]))
            made.append(path)
        if s.get("xlsx"):
            path = os.path.join(REPORT_DIR, f"{key}_{stamp}.xlsx")
            _xlsx(path, table)
            made.append(path)
        keep = int(s.get("keep", 10) or 10)
        for ext in ("csv", "txt", "xlsx"):
            old = sorted(f for f in os.listdir(REPORT_DIR) if f.startswith(key + "_2") and f.endswith("." + ext))
            for f in old[:-keep]:
                try:
                    os.remove(os.path.join(REPORT_DIR, f))
                except OSError:
                    pass
        return made

    def run(self, ctx, s):
        if not self._due(s, ctx):
            return
        if not ctx.ocr_on():
            ctx.log("▤ Relatórios precisam do OCR ligado", "warn")
            return
        ctx.to_base()
        for key, label, tab in REPORT_KINDS:
            if not s.get(key):
                continue
            if not (ctx.tap("btn_alliance", 2) and ctx.tap("btn_alliance_ranking", 2) and ctx.tap(tab, 2)):
                ctx.warn_once(f"rep:{tab}", f"▤ {label}: capture '{tab}' (aba do ranking) no Estúdio")
                ctx.go_home()
                continue
            rows = {}
            for i in range(int(s["pages"])):
                f = ctx.frame()
                new = self.parse(ctx.ocr.read(f, region=(0.05, 0.15, 0.9, 0.75)))
                before = len(rows)
                for k, v in new.items():
                    rows[k] = max(v, rows.get(k, 0))
                if len(rows) == before and i > 0:
                    break
                ctx.drag_rel(0.5, 0.78, 0.5, 0.32, 0.6)
                ctx.sleep(0.8)
            made = self._save(s, key, rows)
            ctx.log(f"▤ {label}: {len(rows)} membros → " + ", ".join(os.path.basename(m) for m in made))
            ctx.go_home()
        s["last_run"] = f"{dt.datetime.now():%Y-%m-%d %H:%M}"


class MapScanner(Task):
    id, name, icon, group = "map_scanner", "Scanner de Mapa", "◎", "Relatórios & Mapa"
    description = "Varre uma área do mapa (centro + raio) pulando por coordenadas pela busca do jogo e lista " \
                  "caminhões, missões, chefes, recursos… com X/Y real e botão IR."
    max_minutes = 0  # a varredura grande pode levar horas
    default_interval = 60.0
    templates = [(f"map_{k}", f"Ícone no mapa: {n}") for k, n, _ in CATEGORIES] + \
                [("btn_bookmark", "Estrela de favoritar na ficha do alvo"),
                 ("btn_favorites", "Botão que abre a lista de favoritos do mapa")]
    fields = [Field("center", "Centro da varredura", "choice", "minha cidade",
                    options=["minha cidade", "coordenadas abaixo"]),
              Field("cx", "Centro X", "int", 500, minimum=0, maximum=2999),
              Field("cy", "Centro Y", "int", 500, minimum=0, maximum=2999),
              Field("radius", "Raio (casas)", "int", 60, minimum=10, maximum=600),
              Field("bookmark", "Favoritar no jogo ao chegar (IR seguinte vai pelos favoritos)", "bool", False),
              Field("rows", "Linhas (modo sem coordenadas)", "int", 3, minimum=1, maximum=30),
              Field("cols", "Colunas (modo sem coordenadas)", "int", 4, minimum=1, maximum=30),
              Field("step", "Passo (fração da tela, modo sem coordenadas)", "float", 0.5, minimum=0.2, maximum=0.7),
              Field("zoom_out", "Afastar zoom: no máximo (giros; para antes da vista estratégica)", "int", 6,
                    minimum=0, maximum=40),
              Field("threshold", "Limiar das suas imagens map_…", "float", 0.84, minimum=0.6, maximum=0.98),
              Field("read_labels", "Ler texto ao lado do ícone", "bool", True),
              Field("calib", "Calibração (automática)", "text", "")]
    store = ScanStore()

    def defaults(self):
        d = super().defaults()
        d.update({k: v for k, v in SCAN_DEFAULTS.items() if k not in d})
        return d

    # O que a IA já reconhece no mapa, por categoria do scanner: o scanner funciona sem você capturar nada.
    # (ícones capturados por você no Estúdio continuam valendo e somam com a IA)
    AI_MAP = {"truck": ("truck_map", "Truck"), "mission": ("task_map", "Secret Task", "Secret Task Ally",
                                                          "Secret Task non-ally"),
              "boss": ("boss_zombie", "boss_walker", "elite_maudite", "garde_marechal"),
              "res_food": ("Farm",), "res_iron": ("Iron Mine",), "res_gold": ("Gold Mine",)}

    # --- câmera ------------------------------------------------------------
    def _zoom_far(self, ctx, s):
        """Afasta um dente por vez enquanto a lupa continua na tela; quando ela some (vista estratégica: missões
        e caminhões somem do mapa) volta um dente. Resultado: a vista NORMAL mais afastada."""
        if ctx.e.backend.name != "pc":
            return
        for _ in range(int(s.get("zoom_out", 6))):
            ctx.scroll(-1, 0.5, 0.45)
            ctx.sleep(0.6, human=False)
            if not ctx.ai("btn_search", ctx.frame()):
                for _ in range(3):  # volta até a lupa reaparecer
                    ctx.scroll(1, 0.5, 0.45)
                    ctx.sleep(0.7, human=False)
                    if ctx.ai("btn_search", ctx.frame()):
                        break
                break

    def _home(self, ctx, s):
        """Câmera na sua cidade e zoom na vista normal mais afastada."""
        ctx.to_base()
        if not ctx.to_world():
            raise RuntimeError("não consegui abrir o mapa")
        ctx.sleep(1.0)
        self._zoom_far(ctx, s)
        return ctx.frame()

    @staticmethod
    def _center(f):
        return f.shape[1] / 2, f.shape[0] / 2

    def _goto(self, ctx, x, y):
        """Lupa → campos X e Y (IA coord_input, da esquerda para a direita) → Ir. O mapa centraliza na casa."""
        if not ctx.tap("btn_search", 2, after=1.0):
            return False
        boxes = sorted(ctx.ai("coord_input", ctx.frame()), key=lambda b: b[0])[:2]
        if len(boxes) < 2:
            ctx.press_back()
            return False
        for b, v in zip(boxes, (x, y)):
            ctx.tap_xy(b[0], b[1], spread=1)
            ctx.sleep(0.25)
            ctx.tap_xy(b[0], b[1], spread=1)  # 2º toque: tira o foco do campo anterior
            ctx.sleep(0.25)
            for _ in range(5):
                ctx.key("backspace")
            ctx.type(str(int(v)))
            ctx.sleep(0.2)
        if not ctx.tap("btn_coord_go", 1.5, after=1.2):
            ctx.key("enter")
            ctx.sleep(1.2)
        for _ in range(6):  # confirma que saiu da tela de busca
            f = ctx.frame()
            if not ctx.ai("coord_input", f):
                ctx.sleep(0.6, human=False)  # o mapa ainda desliza um pouco
                return True
            ctx.sleep(0.5, human=False)
        ctx.press_back()
        return False

    def _my_city(self, ctx):
        """Coordenadas da sua cidade: o mapa abre centrado nela; toca no centro e lê 'X:… Y:…' da ficha."""
        f = ctx.frame()
        cx, cy = self._center(f)
        ctx.tap_xy(int(cx), int(cy), spread=1)
        ctx.sleep(1.2)
        xy = ctx.ocr.coords(ctx.frame()) if ctx.ocr_on() else None
        ctx.press_back()
        ctx.sleep(0.5)
        return xy

    def _calibrate(self, ctx, s, x0, y0):
        """Quantos pixels vale 1 casa em X e em Y nesta janela e neste zoom (pula +D casas e mede o deslocamento
        da imagem). Guarda a matriz pixel→casa; refaz se o tamanho da janela mudar."""
        f = ctx.frame()
        key = f"{f.shape[1]}x{f.shape[0]}"
        try:
            cal = json.loads(s.get("calib") or "{}")
        except ValueError:
            cal = {}
        if cal.get("key") == key and "m" in cal:
            return np.array(cal["m"], float)
        D = 6
        if not self._goto(ctx, x0, y0):
            return None
        a = ctx.frame()
        vecs = []
        for dx, dy in ((D, 0), (0, D)):
            if not self._goto(ctx, x0 + dx, y0 + dy):
                return None
            b = ctx.frame()
            mx, my, resp = measure_shift(a, b)
            if resp < 0.03 or abs(mx) + abs(my) < 4:
                ctx.log(f"◎ Calibração falhou (deslocamento {mx:.0f},{my:.0f}, confiança {resp:.2f})", "warn")
                return None
            vecs.append((-mx / D, -my / D))  # a casa +D estava em -deslocamento na tela de antes
            self._goto(ctx, x0, y0)
            a = ctx.frame()
        m = np.array([[vecs[0][0], vecs[1][0]], [vecs[0][1], vecs[1][1]]], float)  # casas → pixels
        if abs(np.linalg.det(m)) < 1e-3:
            return None
        s["calib"] = json.dumps({"key": key, "m": m.tolist()})
        ctx.log(f"◎ Calibrado: 1 casa X = ({vecs[0][0]:.1f}, {vecs[0][1]:.1f}) px · "
                f"1 casa Y = ({vecs[1][0]:.1f}, {vecs[1][1]:.1f}) px")
        return m

    @staticmethod
    def _view_tiles(m, w, h):
        """Meia-largura (em casas) do quadrado de casas que cabe na área útil da tela (sem o HUD)."""
        hw, hh = 0.36 * w, 0.32 * h
        ax = abs(m[0][0]) + abs(m[0][1])
        ay = abs(m[1][0]) + abs(m[1][1])
        return max(2.0, min(hw / max(ax, 1e-6), hh / max(ay, 1e-6)))

    @staticmethod
    def _grid(cx, cy, radius, step, half=0.0):
        """Centros dos pulos cobrindo o quadrado centro±raio, do meio para fora (o perto fica pronto primeiro).
        half: meia-tela em casas — o último pulo já enxerga até a borda, sem pulo a mais."""
        n = max(0, int(np.ceil(max(0.0, radius - half) / step)))
        pts = [(int(round(cx + i * step)), int(round(cy + j * step)))
               for i in range(-n, n + 1) for j in range(-n, n + 1)]
        pts = [(x, y) for x, y in pts if 0 <= x <= 2999 and 0 <= y <= 2999]
        return sorted(set(pts), key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)

    def _hits(self, ctx, f, cat, s):
        """Detecções de uma categoria no frame: imagens suas (map_…) + IA. [(x, y, score, w, h)]"""
        out = []
        if ctx.vision.has(f"map_{cat}"):
            out += ctx.vision.find_all(f, f"map_{cat}", float(s["threshold"]))
        if ctx.ai_on():
            d = ctx.dets(f, conf=0.2)
            for cls in self.AI_MAP.get(cat, ()):
                thr = catalog.threshold(cls, ctx.cfg)
                out += [h for h in d.get(cls, []) if h[2] >= max(0.35, thr)]
        return out

    def _label(self, ctx, s, f, x, y, tw, th):
        if not (s["read_labels"] and ctx.ocr_on()):
            return ""
        h, w = f.shape[:2]
        crop = f[int(max(0, y - th)):int(min(h, y + th * 1.6)), int(max(0, x - tw * 1.5)):int(min(w, x + tw * 1.5))]
        return " ".join(l.text for l in ctx.ocr.read(crop))[:60]

    def _cats(self, ctx, s):
        ai = ctx.ai_on()
        return [k for k, _, _ in CATEGORIES if s["categories"].get(k, True)
                and (ctx.vision.has(f"map_{k}") or (ai and k in self.AI_MAP))]

    # --- varredura ---------------------------------------------------------
    def run(self, ctx, s):
        cats = self._cats(ctx, s)
        if not cats:
            ctx.log("◎ Nada para procurar: ligue a IA (Configurações) ou capture um ícone de mapa (map_…) "
                    "no Estúdio de imagens", "warn")
            return
        ctx.log("◎ Procurando: " + ", ".join(CAT_NAMES[k] for k in cats))
        f = self._home(ctx, s)
        if s.get("center") == "coordenadas abaixo":
            c = (int(s["cx"]), int(s["cy"]))
        else:
            c = self._my_city(ctx)
            if c:
                ctx.log(f"◎ Sua cidade: X:{c[0]} Y:{c[1]}")
        m = self._calibrate(ctx, s, *c) if c else None
        if m is None:
            ctx.log("◎ Sem coordenadas (busca do mapa ou ficha da cidade não reconhecidas) — varrendo arrastando",
                    "warn")
            return self._run_drag(ctx, s, cats)
        self._run_coords(ctx, s, cats, c, m)

    def _run_coords(self, ctx, s, cats, c, m):
        st = self.store
        f = ctx.frame()
        h, w = f.shape[:2]
        inv = np.linalg.inv(m)
        half = self._view_tiles(m, w, h)
        pts = self._grid(c[0], c[1], int(s["radius"]), max(3, int(half * 2 * 0.9)), half)
        ctx.log(f"◎ Área X:{c[0]}±{s['radius']} Y:{c[1]}±{s['radius']} — {len(pts)} pulos "
                f"(cada tela ≈ {2 * half:.0f}×{2 * half:.0f} casas)")
        st.begin_scan()
        found = 0
        for i, (gx, gy) in enumerate(pts, 1):
            if not self._goto(ctx, gx, gy):
                ctx.log(f"◎ Não consegui pular para X:{gx} Y:{gy}", "warn")
                continue
            f = ctx.frame()
            x0, y0 = self._center(f)
            for cat in cats:
                for (x, y, score, tw, th) in self._hits(ctx, f, cat, s):
                    if not (0.1 * w < x < 0.9 * w and 0.12 * h < y < 0.85 * h):
                        continue  # HUD do jogo
                    tx, ty = inv @ np.array([x - x0, y - y0])
                    ix, iy = int(round(gx + tx)), int(round(gy + ty))
                    if abs(ix - c[0]) > int(s["radius"]) + half or abs(iy - c[1]) > int(s["radius"]) + half:
                        continue
                    st.add(cat, x - x0, y - y0, w, score, self._label(ctx, s, f, x, y, tw, th),
                           gx=ix, gy=iy, origin=c)
                    found += 1
            if i % 5 == 0:
                st.save()
                ctx.log(f"◎ {i}/{len(pts)} pulos · {len(st.items)} itens")
        st.last_scan = time.time()
        st.save()
        ctx.log(f"◎ Varredura concluída: {len(st.items)} itens ({found} detecções)")

    @staticmethod
    def _move(ctx, prev, dx_px, dy_px):
        """Move a câmera ~(dx, dy) px e devolve (novo frame, deslocamento real medido da câmera)."""
        w, h = prev.shape[1], prev.shape[0]
        fx, fy = dx_px / w, dy_px / h
        ctx.drag_rel(0.5 + fx / 2, 0.45 + fy / 2, 0.5 - fx / 2, 0.45 - fy / 2, 0.6)
        ctx.sleep(0.8, human=False)
        cur = ctx.frame()
        mx, my, resp = measure_shift(prev, cur)
        if resp < 0.05:  # imagem mudou demais para medir: confia no comando
            return cur, dx_px, dy_px
        return cur, -mx, -my

    def _run_drag(self, ctx, s, cats):
        """Reserva sem coordenadas: arrasta em zigue-zague medindo o deslocamento (posições relativas à cidade)."""
        st = self.store
        f = ctx.frame()
        h, w = f.shape[:2]
        rows, cols, step = int(s["rows"]), int(s["cols"]), float(s["step"])
        cam = [0.0, 0.0]
        f, mx, my = self._move(ctx, f, -step * w * (cols - 1) / 2, -step * h * (rows - 1) / 2)
        cam[0] += mx
        cam[1] += my
        st.begin_scan()
        found = 0
        for r in range(rows):
            for col in range(cols):
                for cat in cats:
                    for (x, y, score, tw, th) in self._hits(ctx, f, cat, s):
                        if not (0.1 * w < x < 0.9 * w and 0.12 * h < y < 0.85 * h):
                            continue
                        st.add(cat, cam[0] + x - w / 2, cam[1] + y - h * 0.45, w, score,
                               self._label(ctx, s, f, x, y, tw, th))
                        found += 1
                if col < cols - 1:
                    f, mx, my = self._move(ctx, f, step * w * (1 if r % 2 == 0 else -1), 0)
                    cam[0] += mx
                    cam[1] += my
            if r < rows - 1:
                f, mx, my = self._move(ctx, f, 0, step * h)
                cam[0] += mx
                cam[1] += my
        st.last_scan = time.time()
        st.save()
        ctx.log(f"◎ Varredura concluída: {len(st.items)} itens ({found} detecções)")

    # --- IR -----------------------------------------------------------------
    def go(self, ctx, item, key=None):
        """IR: com X/Y, pula direto pela busca do mapa e abre a ficha no centro. Sem X/Y (varredura antiga):
        favoritos do jogo, ou volta para a cidade e anda medindo até ele."""
        s = ctx.e.cfg.task(self.id, self.defaults())
        if item.get("gx") is not None:
            ctx.to_world()
            if self._goto(ctx, item["gx"], item["gy"]):
                f = ctx.frame()
                cx, cy = self._center(f)
                ctx.tap_xy(int(cx), int(cy), spread=1)
                ctx.sleep(1.2)
                ctx.log(f"◎ Cheguei em X:{item['gx']} Y:{item['gy']}")
                self._after_arrival(ctx, s, item, key)
                return
            if item.get("fav") and self._go_favorite(ctx, item):
                return
        f = self._home(ctx, s)
        w, h = f.shape[1], f.shape[0]
        k = w / max(1, item.get("w", w))  # item escaneado com outra largura de janela
        tx, ty = item["px"] * k, item["py"] * k
        cam = [0.0, 0.0]
        for _ in range(40):
            nx, ny = tx - cam[0], ty - cam[1]
            if abs(nx) < 0.3 * w and abs(ny) < 0.3 * h:
                ctx.tap_xy(int(w / 2 + nx), int(h * 0.45 + ny), spread=2)
                ctx.sleep(1.2)
                ctx.log("◎ Cheguei no alvo")
                self._after_arrival(ctx, s, item, key)
                return
            f, mx, my = self._move(ctx, f, max(-0.35 * w, min(0.35 * w, nx)), max(-0.3 * h, min(0.3 * h, ny)))
            cam[0] += mx
            cam[1] += my
        raise RuntimeError("não consegui chegar no alvo")

    def _after_arrival(self, ctx, s, item, key):
        """Com a ficha do alvo aberta: confere X:Y reais (OCR) e favorita no jogo (estrela da ficha)."""
        changed = False
        xy = ctx.ocr.coords(ctx.frame(), (0.0, 0.0, 1.0, 0.86)) if ctx.ocr_on() else None
        if xy and 0 <= xy[0] < 3000 and 0 <= xy[1] < 3000:  # grade do servidor: 1000×1000 (3000 na temporada)
            if (item.get("gx"), item.get("gy")) != tuple(xy):
                item["gx"], item["gy"] = xy
                changed = True
            ctx.log(f"◎ Coordenadas do alvo: X:{xy[0]} Y:{xy[1]}")
        if s.get("bookmark") and not item.get("fav") and ctx.vision.has("btn_bookmark"):
            if ctx.tap("btn_bookmark", 1.5, after=0.8):
                ctx.tap("btn_confirm", 1.5, after=0.6)
                item["fav"] = True
                changed = True
                ctx.log("★ Alvo salvo nos favoritos do jogo")
        if changed:
            self.store.save()

    def _go_favorite(self, ctx, item):
        """Abre os favoritos do mapa, acha a linha com X e Y do item (OCR) e toca no 'Ir' dela."""
        if not ctx.ocr_on() or not ctx.to_world() or not ctx.tap("btn_favorites", 2, after=1.2):
            return False
        gx, gy = str(item["gx"]), str(item["gy"])
        for _ in range(6):  # rola a lista até achar
            for ln in ctx.lines():
                digits = re.findall(r"\d+", ln.text.upper().replace("O", "0"))
                if gx in digits and gy in digits:
                    go = [w for l2 in ctx.lines() for w in l2.words
                          if w.text.strip().lower() in ("ir", "go", "aller", "los", "vai", "git", "pergi")
                          and abs(w.center[1] - ln.center[1]) < ln.h * 3]
                    tx, ty = go[0].center if go else ln.center
                    ctx.tap_xy(tx, ty, spread=2)
                    ctx.sleep(2.0)
                    ctx.tap_rel(0.5, 0.5)  # o jogo centraliza no favorito: abre a ficha do alvo
                    ctx.log(f"★ Indo pelos favoritos: X:{gx} Y:{gy}")
                    return True
            ctx.drag_rel(0.5, 0.75, 0.5, 0.35, 0.6)
            ctx.sleep(0.8)
        ctx.back()
        return False


# ---------------------------------------------------------------- sempre ligado
class BaseCare(Task):
    id, name, icon, group = "base_care", "Hospital, Treino & Pesquisa", "✚", "Escavações & Diárias"
    description = "Cura os feridos pela ambulância do mapa e pede ajuda da aliança; coloca o quartel e o " \
                  "laboratório parados para trabalhar."
    default_interval = 30.0
    templates = [("bubble_train_idle", "Balão do quartel parado (sem treinar)"),
                 ("bubble_research_idle", "Balão do laboratório parado (sem pesquisa)")]
    fields = [Field("heal", "Curar feridos", "bool", True),
              Field("heal_help", "Pedir ajuda da aliança na cura", "bool", True),
              Field("heal_batch_min", "Curar em lotes de — mínimo (0 = tudo)", "int", 0, minimum=0, maximum=100000),
              Field("heal_batch_max", "…máximo", "int", 0, minimum=0, maximum=100000),
              Field("train", "Treinar quando o quartel estiver parado", "bool", False),
              Field("research", "Pesquisar quando o laboratório estiver parado", "bool", False)]
    cards = [("Hospital", [
        Card("Curar feridos", "✚", "No mapa: coleta os já curados, toca na ambulância e em Curar (a quantidade que o "
                                   "jogo sugerir). Nunca toca em 'Terminar agora'.", toggle="heal"),
        Card("Ajuda na cura", "🤝", "Depois de curar, toca na ambulância de novo para pedir ajuda da aliança.",
             toggle="heal_help"),
        Card("Curar em lotes", "▦", "Curas menores terminam mais rápido e a aliança ajuda em cada uma "
             "(sorteio entre o mínimo e o máximo; 0 = tudo de uma vez).", fields=["heal_batch_min", "heal_batch_max"],
             summary=lambda s: f"lotes de {s['heal_batch_min']}–{s['heal_batch_max']}" if int(s["heal_batch_min"])
             else "tudo de uma vez"),
    ]), ("Base parada", [
        Card("Treino", "⚒", "Quando o quartel estiver parado: abre e toca em Treinar. Precisa da imagem do balão do "
                            "quartel parado (Estúdio de imagens → 'bubble_train_idle').", toggle="train"),
        Card("Pesquisa", "⚗", "Quando o laboratório estiver parado: abre e toca em Pesquisar. Precisa da imagem do "
                              "balão (Estúdio de imagens → 'bubble_research_idle').", toggle="research"),
    ])]

    def _heal(self, ctx, s):
        heal_troops(ctx, s.get("heal_batch_min", 0), s.get("heal_batch_max", 0), ask_help=s["heal_help"])

    def _idle_building(self, ctx, bubble, go, counter, label):
        if not ctx.vision.has(bubble):
            ctx.warn_once(f"need:{bubble}", f"{label}: capture o balão '{bubble}' no Estúdio de imagens (F8) "
                                            f"para o TOSCO saber quando está parado")
            return
        if not ctx.to_base() or not ctx.tap(bubble, 1.0, after=1.2):
            return
        if ctx.tap(go, 2, after=1.0):
            ctx.counters.add(counter)
            ctx.log(f"{label}: iniciado")
        else:
            ctx.log(f"{label}: abri o prédio, mas não achei o botão (faltam recursos?)")
        ctx.go_home()

    def run(self, ctx, s):
        if s["heal"]:
            self._heal(ctx, s)
        if s["train"]:
            self._idle_building(ctx, "bubble_train_idle", "btn_train_go", "trained", "⚒ Treino")
        if s["research"]:
            self._idle_building(ctx, "bubble_research_idle", "btn_research_go", "research", "⚗ Pesquisa")


class Heroes(Task):
    id, name, icon, group = "heroes", "Heróis: recrutamento grátis", "★", "Escavações & Diárias"
    description = "Abre Recrutar Heróis e usa só as tiragens GRÁTIS de cada aba. Nunca gasta bilhete nem diamante."
    default_interval = 240.0
    fields = [Field("max_tabs", "Quantas abas de recrutamento olhar", "int", 3, minimum=1, maximum=6)]
    cards = [("Recrutamento", [
        Card("Só grátis", "★", "Em cada aba, só toca no x1 quando aparece escrito 'Grátis' em cima dele. A trava de "
                               "compra do TOSCO também bloqueia o toque se houver preço ou diamante perto.",
             fields=["max_tabs"], summary="olha {max_tabs} abas"),
    ])]

    @staticmethod
    def _free_x1(ctx):
        f = ctx.frame()
        hits = ctx.ai("recruit_x1", f)
        if not hits:
            return False
        x, y, _, w, h = hits[0]
        fh, fw = f.shape[:2]
        # o "Grátis" fica no próprio botão ou logo acima dele
        region = (max(0.0, (x - w) / fw), max(0.0, (y - 1.8 * h) / fh), min(1.0, 2 * w / fw), min(1.0, 2.6 * h / fh))
        if not ctx.find_text(TEXT_TARGETS["free_label"], region=region):
            return False
        ctx.tap_xy(x, y, spread=2)
        ctx.sleep(2.5)
        for _ in range(5):  # sai da revelação até a aba voltar
            if ctx.ai("recruit_x1", ctx.frame()):
                break
            if not ctx.lone_confirm():
                ctx.tap_rel(0.5, 0.88)
            ctx.sleep(1.0)
        return True

    def run(self, ctx, s):
        if not ctx.ai_on():
            ctx.warn_once("heroes:ai", "★ Heróis precisa da IA ligada (Configurações)")
            return
        if ctx.go_home() is None or not ctx.tap("btn_heroes", 2, after=1.2):
            return
        if not ctx.tap("btn_recruit", 2, after=1.5):
            ctx.go_home()
            return
        tabs = sorted(ctx.ai("recruit_tab", ctx.frame()), key=lambda d: d[0]) or [None]
        got = 0
        for tab in tabs[:int(s["max_tabs"])]:
            if tab:
                ctx.tap_xy(tab[0], tab[1], spread=2)
                ctx.sleep(1.0)
            if self._free_x1(ctx):
                got += 1
                ctx.counters.add("hero_recruits")
        ctx.log(f"★ {got} recrutamento(s) grátis" if got else "★ Nenhum recrutamento grátis agora")
        ctx.go_home()


SHIELD_HOURS = ["8 h", "12 h", "24 h"]
WEEKDAYS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _week_min(day, hhmm):
    t = _hm(hhmm)
    return (WEEKDAYS_PT.index(day) if day in WEEKDAYS_PT else 0) * 1440 + (t if t is not None else 0)


class Shield(Task):
    id, name, icon, group = "shield", "Escudo Automático", "⛨", "Sempre ligado"
    description = "Mantém um escudo ativo dentro do seu horário: ativa o próximo um pouco antes do anterior acabar " \
                  "(escudo do inventário; a Loja da Aliança como reserva). Nunca compra com diamantes."
    default_interval = 10.0
    templates = [("shield_expiring", "Ícone de escudo acabando/ausente"), ("btn_base_buffs", "Botão de buffs da base"),
                 ("buff_shield", "Linha do escudo nos buffs"),
                 ("btn_alliance_shop", "Loja da Aliança"), ("shop_shield", "Escudo na Loja da Aliança")]
    fields = [Field("from_day", "De (dia)", "choice", "Segunda", options=WEEKDAYS_PT),
              Field("from_time", "…às", "text", "00:00"),
              Field("to_day", "Até (dia)", "choice", "Domingo", options=WEEKDAYS_PT),
              Field("to_time", "…às", "text", "23:59"),
              Field("hours", "Escudo", "choice", "24 h", options=SHIELD_HOURS),
              Field("ahead_min", "Ativar o próximo quanto antes de acabar (min)", "int", 20, minimum=1, maximum=180),
              Field("alliance_shop", "Usar a Loja da Aliança se faltar no inventário", "bool", True),
              Field("always", "Renovar mesmo sem aviso (versões antigas)", "bool", False),
              Field("shield_until", "Escudo ativo até (automático)", "text", "")]
    cards = [("Configurar", [
        Card("Quando", "◷", "Dias e horários (relógio do PC) em que o bot pode ativar o escudo. Para a semana toda: "
             "Segunda 00:00 até Domingo 23:59.", fields=["from_day", "from_time", "to_day", "to_time"],
             summary="{from_day} {from_time} → {to_day} {to_time}"),
        Card("Manter o escudo ativo", "⛨", "Ativa o escudo e renova um pouco antes de acabar. Primeiro o do "
             "inventário, depois a Loja da Aliança. Dica: tenha escudos no inventário.",
             fields=["hours", "ahead_min", "alliance_shop"], summary="{hours} · renova {ahead_min} min antes"),
    ])]

    def _in_window(self, s):
        now = dt.datetime.now()
        t = now.weekday() * 1440 + now.hour * 60 + now.minute
        a, b = _week_min(s["from_day"], s["from_time"]), _week_min(s["to_day"], s["to_time"])
        return a <= t <= b if a <= b else (t >= a or t <= b)

    def _from_inventory(self, ctx, hours):
        """Inventário → escudo da duração (IA shield_8/12/24, rolando) → Usar → confirma."""
        if not ctx.tap("btn_inventory", 2, after=1.5):
            return False
        cls = f"shield_{hours}"
        for _ in range(6):
            hit = ctx.seen(cls, 0.45, ctx.frame())
            if hit:
                ctx.tap_xy(hit[0], hit[1], spread=2)
                ctx.sleep(0.8)
                if ctx.tap("btn_use", 2, after=1.0):
                    ctx.tap("btn_confirm", 1.2)
                    return True
                return False
            ctx.drag_rel(0.5, 0.75, 0.5, 0.4, 0.6)
            ctx.sleep(0.8)
        return False

    def _from_shop(self, ctx):
        if not (ctx.vision.has("btn_alliance_shop") and ctx.vision.has("shop_shield")):
            return False
        ok = ctx.tap("btn_alliance", 2) and ctx.tap("btn_alliance_shop", 2) and ctx.tap("shop_shield", 2) \
            and ctx.tap("btn_use", 2)
        return bool(ok)

    def run(self, ctx, s):
        if not self._in_window(s):
            return
        hours = int(str(s.get("hours", "24 h")).split()[0])
        until = float(s.get("shield_until") or 0)
        due = time.time() >= until - int(s.get("ahead_min", 20)) * 60
        warn = ctx.vision.has("shield_expiring") and ctx.exists("shield_expiring", 0.85)
        if not (due or warn or s.get("always")):
            return
        ctx.to_base()
        ok = self._from_inventory(ctx, hours) if ctx.ai_on() else False
        if not ok:
            ctx.go_home()
            ctx.to_base()
            ok = bool(ctx.tap("btn_base_buffs", 2) and ctx.tap("buff_shield", 2) and ctx.tap("btn_use", 2))
        if not ok and s.get("alliance_shop"):
            ctx.go_home()
            ok = self._from_shop(ctx)
        if ok:
            s["shield_until"] = str(int(max(time.time(), until) + hours * 3600) if until > time.time()
                                    else int(time.time() + hours * 3600))
            ctx.counters.add("shields")
            ctx.log(f"⛨ Escudo de {hours} h ativado")
        else:
            ctx.log("⛨ Falha ao ativar escudo (sem escudo no inventário?)", "warn")
            ctx.notify("falha ao renovar escudo")
        ctx.go_home()


class Routine(Task):
    """Macro escrita por você, uma ação por linha:
    toque <template> | texto <Palavra|Word> | ponto <0..1> <0..1> | espera <seg> | voltar [n]
    arrasta <x1> <y1> <x2> <y2> | digita <texto> | tecla <enter|esc> | base | mapa | se <template> | fim
    (linhas entre 'se X' e 'fim' só rodam se X estiver na tela)."""
    group = "Sempre ligado"
    icon = "⌘"
    default_interval = 60.0
    max_minutes = 30  # "espera <seg>" é livre
    fields = [Field("script", "Passos (um por linha)", "code",
                    "base\ntoque btn_mail\ntexto Receber tudo|Claim all\nvoltar")]

    def __init__(self, n):
        self.id = f"routine_{n}"
        self.name = f"Rotina personalizada {n}"
        self.description = "Crie seus próprios passos: toque em template, texto, ponto, espera, arrasta, digita…"
        self.templates = []

    def run(self, ctx, s):
        skip = 0
        for raw in str(s["script"]).splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            cmd, _, arg = line.partition(" ")
            cmd = cmd.lower()
            if skip:
                skip += cmd == "se"
                skip -= cmd == "fim"
                continue
            if cmd == "fim":
                continue
            if cmd == "se":
                if not ctx.exists(arg.strip()):
                    skip = 1
            elif cmd == "toque":
                ctx.tap(arg.strip(), 3)
            elif cmd == "texto":
                ctx.tap_text(arg.split("|"), 3)
            elif cmd == "ponto":
                fx, fy = map(float, arg.split()[:2])
                ctx.tap_rel(fx, fy)
                ctx.sleep(0.5)
            elif cmd == "espera":
                ctx.sleep(float(arg or 1))
            elif cmd == "voltar":
                ctx.back(int(arg or 1))
            elif cmd == "arrasta":
                ctx.drag_rel(*map(float, arg.split()[:4]))
                ctx.sleep(0.6)
            elif cmd == "digita":
                ctx.type(arg)
            elif cmd == "tecla":
                ctx.key(arg.strip())
            elif cmd == "base":
                ctx.to_base()
            elif cmd == "mapa":
                ctx.to_world()
            else:
                ctx.log(f"⌘ comando desconhecido: {line}", "warn")


ALL_TASKS = [AutoDigs(), Survivors(), IdleRewards(), Resources(), Alliance(), Daily(), SecretSquad(), Trucks(), Farm(), Arena(),
             AutoJoin(), Hunt(), MarshalGuard(), ArmsRace(), FirstLady(),
             Reports(), MapScanner(),
             BaseCare(), Heroes(), Shield(), Routine(1), Routine(2), Routine(3)]


def all_templates():
    """[(nome, descrição, dono, aprende_sozinho)] sem repetição."""
    seen, out = set(), []
    extra = [(k, "Botão com texto (o TOSCO acha e aprende sozinho)") for k in TEXT_TARGETS]
    for owner, items in [("Comum", COMMON)] + [(t.name, t.templates) for t in ALL_TASKS] + [("Texto", extra)]:
        for name, desc in items:
            if name not in seen:
                seen.add(name)
                out.append((name, desc, owner, name in TEXT_TARGETS))
    return out
