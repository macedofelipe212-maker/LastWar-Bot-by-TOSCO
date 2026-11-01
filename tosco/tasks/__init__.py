"""Módulos de automação do TOSCO.

Cada passo procura o elemento por template (imagem capturada) e, se for um botão com texto, também pelo
texto via OCR em vários idiomas (ver core/targets.py) — esses o TOSCO aprende sozinho.
Ícones sem texto precisam ser capturados uma vez (Estúdio ou F8 com o mouse em cima).

Convenção: hud_* telas · btn_* botões · tab_* abas · chat_* chat · rally_* chefes · map_* ícones do mapa
"""
import csv
import datetime as dt
import os
import random
import re
import time

from ..core import catalog, rapid, tesseract
from ..core.engine import Card, Field, Task
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
            Card("Festas e fogos", "✺", "Festas e fogos de artifício da aliança.", toggle="take_parties",
                 summary=lambda s: "pega festas" if s["take_parties"] else "ignora festas"),
        ]),
        ("Como tocar", [
            Card("Toques rápidos", "⚡", "Quantos toques e com que velocidade nos ovos e festas.",
                 fields=["max_taps", "tap_cooldown"], summary="{max_taps} toques · {tap_cooldown}s entre eles"),
            Card("Final da escavação", "⏱", "Quando o cronômetro chega perto do fim, toca sem parar até o presente.",
                 fields=["spam_threshold", "spam_duration"],
                 summary="faltando {spam_threshold}s · até {spam_duration}s"),
            Card("Parecer humano", "◔", "Deixa passar algumas de propósito, como um jogador real.",
                 fields=["skip_chance"], summary=lambda s: f"pula {s['skip_chance']}%" if s["skip_chance"]
                 else "pega todas"),
            Card("Só avisar", "🔔", "Não toca em nada: só avisa (registro e Telegram).", toggle="detect_only"),
        ]),
        ("No chat", [
            Card("Mensagens", "✉", "Agradece no chat depois de cada escavação.", toggle="send_message",
                 fields=["messages", "message_limit_min"],
                 summary=lambda s: f"no máx. 1 a cada {s['message_limit_min']} min" if s["send_message"]
                 else "desligado"),
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

    def _thanks(self, ctx, s):
        if not s["send_message"] or time.time() - getattr(self, "_last_msg", 0) < int(s["message_limit_min"]) * 60:
            return
        msgs = parse_list(s["messages"])
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
            self._thanks(ctx, s)
        else:
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
                if s["detect_only"] or random.randint(1, 100) <= int(s["skip_chance"]):
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

    # --- estados -------------------------------------------------------
    def _run_ai(self, ctx, s):
        ctx.frame()
        if self._claim(ctx, s):  # prioridade máxima em qualquer estado
            return True
        if self._st:
            return self._waiting(ctx, s)
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
        thr = int(s.get("spam_threshold", 13))
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
    description = "Toca nas bolhas de comida, ferro, ouro e caminhão sobre os prédios da base."
    default_enabled, default_interval = True, 20.0
    templates = [("bubble_food", "Bolha de comida pronta"), ("bubble_iron", "Bolha de ferro pronta"),
                 ("bubble_gold", "Bolha de ouro pronta"), ("bubble_truck", "Bolha do caminhão de recursos")]
    fields = [Field("food", "Comida", "bool", True), Field("iron", "Ferro", "bool", True),
              Field("gold", "Ouro", "bool", True), Field("truck", "Caminhão", "bool", True),
              Field("threshold", "Limiar (bolhas brilham; a cor também é conferida)", "float", 0.65,
                    minimum=0.5, maximum=0.95)]

    def run(self, ctx, s):
        ctx.to_base()
        total = 0
        kinds = [k for k in ("food", "iron", "gold", "truck") if s[k]]
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
    description = "Ajuda os membros, coleta presentes da aliança e doa para a tecnologia recomendada."
    default_enabled, default_interval = True, 15.0
    templates = [("btn_alliance_help", "Botão flutuante de ajuda (mãos)"),
                 ("btn_alliance_gifts", "Entrada de presentes da aliança"), ("btn_claim_all", "Coletar tudo"),
                 ("btn_alliance_tech", "Entrada de tecnologia da aliança"),
                 ("tech_recommended", "Selo de tecnologia recomendada"),
                 ("btn_donate", "Botão de doar"), ("btn_donate_diamond", "Botão de doar com diamantes")]
    fields = [Field("help", "Ajudar membros", "bool", True), Field("gifts", "Coletar presentes", "bool", True),
              Field("donate", "Doar tecnologia", "bool", True),
              Field("diamond_limit", "Doações com diamante por dia", "int", 0, minimum=0, maximum=100)]

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
        ctx.go_home()


class Daily(Task):
    id, name, icon, group = "daily", "Diárias: Loja, Trem, VIP", "✉", "Escavações & Diárias"
    description = "Brinde grátis da loja, curtidas no trem, baú VIP, correio e recompensas de tarefas diárias."
    default_enabled, default_interval = True, 120.0
    templates = [("btn_mall", "Entrada da loja"), ("mall_free", "Brinde grátis da loja"),
                 ("btn_train", "Entrada do trem"), ("btn_vip", "Entrada do VIP"), ("vip_chest", "Baú VIP grátis"),
                 ("btn_mail", "Correio"), ("btn_daily_tasks", "Tarefas diárias"), ("daily_chest", "Baú de atividade pronto")]
    fields = [Field("mall", "Brinde da loja", "bool", True), Field("train", "Curtir trem", "bool", True),
              Field("vip", "Baú VIP", "bool", True), Field("mail", "Coletar correio", "bool", True),
              Field("chests", "Baús de tarefas diárias", "bool", True)]

    def run(self, ctx, s):
        ctx.to_base()
        if s["mall"] and ctx.counters.get("mall_free") == 0 and ctx.tap("btn_mall", 2):
            if ctx.tap("mall_free", 2):
                ctx.counters.add("mall_free")
            ctx.go_home()
        if s["train"] and ctx.tap("btn_train", 2):
            while ctx.tap("btn_like", 1, after=0.3):
                ctx.counters.add("train_likes")
            ctx.go_home()
        if s["vip"] and ctx.tap("btn_vip", 2):
            ctx.tap("vip_chest", 2) and ctx.tap("btn_claim", 1.5)
            ctx.go_home()
        if s["mail"] and ctx.tap("btn_mail", 2):
            ctx.tap("btn_claim_all", 2)
            ctx.go_home()
        if s["chests"] and ctx.tap("btn_daily_tasks", 2):
            while ctx.tap("btn_claim", 1, after=0.5):
                ctx.counters.add("daily_claims")
            for x, y in ctx.find_all("daily_chest", 0.85):
                ctx.tap_xy(x, y)
                ctx.sleep(0.8)
                ctx.back()
            ctx.go_home()


class SecretSquad(Task):
    id, name, icon, group = "secret_squad", "Esquadrão Secreto", "✦", "Escavações & Diárias"
    description = "Coleta missões concluídas e despacha novas a partir do nível mínimo escolhido."
    default_enabled, default_interval = True, 30.0
    templates = [("btn_secret_squad", "Entrada do esquadrão secreto"), ("btn_quick_deploy", "Escalar automático")] + \
                [(f"mission_{l}", f"Selo de missão nível {l}") for l in LEVELS]
    fields = [Field("claim_only", "Apenas coletar", "bool", False),
              Field("min_level", "Nível mínimo da missão", "choice", "SSR", options=LEVELS)]

    def run(self, ctx, s):
        ctx.to_base()
        if not ctx.tap("btn_secret_squad", 3):
            return
        n = 0
        while n < 6 and ctx.tap("btn_claim", 1, after=0.8):
            ctx.back()
            n += 1
        if not s["claim_only"]:
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


class Trucks(Task):
    id, name, icon, group = "trucks", "Caminhões", "⛟", "Escavações & Diárias"
    description = "Coleta caminhões que chegaram e envia novos, renovando até achar o nível desejado."
    default_interval = 30.0
    templates = [("btn_trucks", "Entrada dos caminhões/escolta"), ("btn_truck_claim", "Coletar caminhão"),
                 ("btn_truck_send", "Enviar caminhão"), ("btn_truck_refresh", "Renovar caminhão")] + \
                [(f"truck_{l}", f"Caminhão nível {l}") for l in LEVELS[:3]]
    fields = [Field("send", "Enviar caminhões", "bool", True),
              Field("level", "Nível mínimo", "choice", "SSR", options=LEVELS[:3]),
              Field("max_refresh", "Renovações gratuitas máx.", "int", 3, minimum=0, maximum=20)]

    def run(self, ctx, s):
        ctx.to_base()
        if not ctx.tap("btn_trucks", 3):
            return
        while ctx.tap("btn_truck_claim", 1, after=0.8):
            ctx.back()
            ctx.counters.add("trucks_claimed")
        if s["send"] and ctx.tap("btn_truck_send", 2):
            allowed = LEVELS[:LEVELS.index(s["level"]) + 1]
            for _ in range(int(s["max_refresh"]) + 1):
                if any(ctx.vision.has(f"truck_{l}") and ctx.exists(f"truck_{l}", 0.86) for l in allowed):
                    break
                if not ctx.tap("btn_truck_refresh", 1.5, after=1.0):
                    break
            if ctx.tap("btn_depart", 2):
                ctx.counters.add("trucks_sent")
                ctx.log("⛟ Caminhão enviado")
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
        t = norm(ctx.ocr.text(f, region))
        info["text"] = t
        m = re.search(r"\b(?:nv|lv|nivel)\s*\.?\s*(\d{1,3})\b", t)
        info["lvl"] = int(m.group(1)) if m else 0
        m = re.search(r"\b(\d)\s*/\s*(\d)\b", t)
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


class Hunt(Task):
    id, name, icon, group = "hunt", "Zumbis Dourados & Rally", "☣", "Rallies & Eventos"
    description = "Gasta stamina em zumbis/Elites da Perdição pela busca do mapa: ataque solo ou inicia rally, " \
                  "e pode subir de nível sozinho."
    max_minutes = 30
    default_interval = 5.0
    templates = [("search_zombie", "Aba Zumbi na busca"), ("search_doom", "Aba Elite da Perdição na busca"),
                 ("search_gold_zombie", "Aba Zumbi Dourado na busca"),
                 ("btn_level_minus", "Botão - do nível"), ("btn_level_plus", "Botão + do nível"),
                 ("btn_rally_confirm", "Confirmar duração do rally"), ("no_stamina", "Aviso de sem stamina")]
    fields = [Field("mode", "Alvo", "choice", "zombie", options=["zombie", "gold_zombie", "doom"]),
              Field("level", "Nível do alvo", "int", 1, minimum=1, maximum=60),
              Field("climb", "Subir 1 nível a cada vitória", "bool", False),
              Field("max_level", "Nível máximo ao subir", "int", 30, minimum=1, maximum=60),
              Field("rally", "Iniciar rally (em vez de ataque solo)", "bool", False),
              Field("max_attacks", "Ataques por execução", "int", 3, minimum=1, maximum=50),
              Field("daily_limit", "Limite diário (0 = ∞)", "int", 0, minimum=0, maximum=999),
              Field("squad_order", "Ordem de esquadrões", "text", "1,2,3,4"),
              Field("heal", "Curar depois", "bool", True)]
    main_capable = True
    cards = [
        ("O que fazer", [
            Card("Alvo", "☣", "Zumbi comum, Zumbi Dourado ou Elite da Perdição, e o nível.",
                 fields=["mode", "level", "climb", "max_level"],
                 summary=lambda s: f"{ {'zombie': 'zumbi', 'gold_zombie': 'zumbi dourado', 'doom': 'elite'}.get(s['mode'], s['mode'])}"
                                   f" nv {s['level']}" + (" · sobe de nível" if s["climb"] else "")),
            Card("Iniciar rally", "⚑", "Lidera um rally em vez de atacar sozinho.", toggle="rally",
                 summary=lambda s: "inicia rally" if s["rally"] else "ataque solo"),
        ]),
        ("Energia e limites", [
            Card("Ataques", "⚔", "Quantos ataques por rodada e por dia.", fields=["max_attacks", "daily_limit"],
                 summary=lambda s: f"{s['max_attacks']} por rodada · " +
                                   (f"{s['daily_limit']}/dia" if int(s["daily_limit"]) else "sem limite diário")),
            Card("Esquadrões", "⚑", "Ordem de preferência dos esquadrões.", fields=["squad_order"],
                 summary="ordem {squad_order}"),
            Card("Curar tropas", "✚", "Cura os feridos depois de cada rodada.", toggle="heal"),
        ]),
    ]

    def run(self, ctx, s):
        squads = parse_list(s["squad_order"]) or SQUADS
        for _ in range(int(s["max_attacks"])):
            if int(s["daily_limit"]) and ctx.counters.get("hunts") >= int(s["daily_limit"]):
                ctx.log("☣ Limite diário de caçadas atingido")
                break
            ctx.to_world()
            if not (ctx.tap("btn_search", 2) and ctx.tap(f"search_{s['mode']}", 2)):
                break
            for _ in range(60):
                if not ctx.tap("btn_level_minus", 0.3, after=0.05):
                    break
            for _ in range(int(s["level"]) - 1):
                ctx.tap("btn_level_plus", 0.5, after=0.08)
            if not ctx.tap("btn_go", 2, after=2.0):
                break
            ctx.tap_rel(0.5, 0.5)
            ctx.sleep(0.8)
            if s["rally"]:
                if not ctx.tap("btn_rally", 2):
                    break
                ctx.tap("btn_rally_confirm", 1.5)
            elif not ctx.tap("btn_attack", 2):
                break
            if ctx.vision.has("no_stamina") and ctx.exists("no_stamina", 0.85):
                ctx.log("☣ Sem stamina", "warn")
                break
            if not march(ctx, squads):
                break
            ctx.counters.add("hunts")
            if s["climb"] and int(s["level"]) < int(s["max_level"]):
                s["level"] = int(s["level"]) + 1
                ctx.log(f"☣ Próximo alvo: nível {s['level']}")
            ctx.sleep(1.5)
        if s["heal"]:
            heal(ctx)
        ctx.go_home()


class MarshalGuard(Task):
    id, name, icon, group = "marshal_guard", "Guarda do Marechal", "♜", "Rallies & Eventos"
    description = "No evento do Marechal: um esquadrão inicia rallies e os outros entram nos rallies da aliança."
    default_interval = 2.0
    templates = [("btn_marshal_event", "Entrada/ícone do evento Guarda do Marechal"),
                 ("marshal_target", "O Marechal no mapa (ou o botão de ir até ele)")]
    fields = [Field("start", "Iniciar rallies", "bool", True),
              Field("start_squad", "Esquadrão que inicia", "choice", "1", options=SQUADS),
              Field("join", "Entrar nos rallies da aliança", "bool", True),
              Field("join_squads", "Esquadrões que entram", "text", "2,3,4"),
              Field("daily_limit", "Limite de rallies/dia (0 = ∞)", "int", 0, minimum=0, maximum=999)]

    def run(self, ctx, s):
        lim = int(s["daily_limit"])
        if lim and ctx.counters.get("marshal") >= lim:
            return
        if s["start"]:
            ctx.to_world()
            if ctx.tap("btn_marshal_event", 2, after=1.5) or ctx.tap("marshal_target", 2, after=1.5):
                ctx.tap_rel(0.5, 0.5)
                ctx.sleep(0.8)
                if ctx.tap("btn_rally", 2):
                    ctx.tap("btn_rally_confirm", 1.5)
                    if march(ctx, [s["start_squad"]]):
                        ctx.counters.add("marshal")
                        ctx.log(f"♜ Rally do Marechal iniciado (esq. {s['start_squad']})")
            ctx.go_home()
        if s["join"]:
            joiner = AutoJoin()
            js = dict(ctx.e.cfg.task(joiner.id, joiner.defaults()))
            js.update({f"boss_{k}": k == "marshal" for k, _ in RALLY_BOSSES})
            js["squad_order"] = s["join_squads"]
            joiner.run(ctx, js)


class ArmsRace(Task):
    id, name, icon, group = "arms_race", "Corrida Armamentista", "🏁", "Rallies & Eventos"
    description = "Lê o tema atual da Corrida (OCR) e roda o módulo certo para buscar a caixa do topo da rodada."
    default_interval = 30.0
    templates = [("btn_arms_race", "Entrada da Corrida Armamentista (ícone de eventos)"),
                 ("btn_train_troops", "Treinar tropas (no quartel)"), ("btn_barracks", "Quartel"),
                 ("btn_recruit", "Recrutar heróis"), ("btn_drone", "Tela do drone"), ("btn_drone_up", "Melhorar drone"),
                 ("btn_research", "Laboratório / pesquisa"), ("btn_speedup", "Usar aceleração")]
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
              Field("speedups", "Acelerações por rodada (construção/pesquisa)", "int", 1, minimum=0, maximum=20)]
    cards = [
        ("Quais temas fazer", [
            Card("Tropas", "⚔", "Treina tropas no quartel no tema de Unidades.", toggle="units"),
            Card("Heróis", "★", "Recruta heróis no tema de Heróis.", toggle="heroes"),
            Card("Drone", "✈", "Melhora o drone no tema de Drone.", toggle="drone"),
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
        elif th == "heroes" and ctx.tap("btn_recruit", 2):
            ctx.tap("btn_confirm", 1.5)
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
class Reports(Task):
    id, name, icon, group = "reports", "Relatórios R4/R5", "▤", "Relatórios & Mapa"
    description = "Abre o ranking (VS, doações, abates), rola a lista, lê nomes e pontos por OCR e salva em CSV " \
                  "(abre no Excel)."
    default_interval = 1440.0
    templates = [("btn_alliance_ranking", "Ranking da aliança"), ("tab_vs", "Aba VS/pontos do dia"),
                 ("tab_donation", "Aba doações"), ("tab_kills", "Aba abates")]
    fields = [Field("vs", "VS do dia", "bool", True), Field("donation", "Doações", "bool", True),
              Field("kills", "Abates", "bool", False),
              Field("pages", "Páginas a rolar", "int", 12, minimum=1, maximum=60)]

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

    def run(self, ctx, s):
        if not ctx.ocr_on():
            ctx.log("▤ Relatórios precisam do OCR ligado", "warn")
            return
        ctx.to_base()
        for key, tab in (("vs", "tab_vs"), ("donation", "tab_donation"), ("kills", "tab_kills")):
            if not s[key]:
                continue
            if not (ctx.tap("btn_alliance", 2) and ctx.tap("btn_alliance_ranking", 2) and ctx.tap(tab, 2)):
                ctx.go_home()
                continue
            rows = {}
            for _ in range(int(s["pages"])):
                f = ctx.frame()
                new = self.parse(ctx.ocr.read(f, region=(0.05, 0.15, 0.9, 0.75)))
                before = len(rows)
                for k, v in new.items():
                    rows[k] = max(v, rows.get(k, 0))
                if len(rows) == before and _ > 0:
                    break
                ctx.drag_rel(0.5, 0.78, 0.5, 0.32, 0.6)
                ctx.sleep(0.8)
            path = os.path.join(REPORT_DIR, f"{key}_{dt.datetime.now():%Y-%m-%d_%H%M}.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["posição", "nome", "pontos"])
                for i, (k, v) in enumerate(sorted(rows.items(), key=lambda kv: -kv[1]), 1):
                    w.writerow([i, k, v])
            ctx.log(f"▤ Relatório {key}: {len(rows)} membros → {os.path.basename(path)}")
            ctx.go_home()


class MapScanner(Task):
    id, name, icon, group = "map_scanner", "Scanner de Mapa", "◎", "Relatórios & Mapa"
    description = "Varre o mapa em volta da sua cidade e lista caminhões, trens, missões, zumbis, recursos… " \
                  "com a posição e botão IR (página MAPA)."
    max_minutes = 0  # a varredura grande pode levar horas
    default_interval = 60.0
    templates = [(f"map_{k}", f"Ícone no mapa: {n}") for k, n, _ in CATEGORIES] + \
                [("btn_bookmark", "Estrela de favoritar na ficha do alvo"),
                 ("btn_favorites", "Botão que abre a lista de favoritos do mapa")]
    fields = [Field("bookmark", "Favoritar no jogo ao chegar (IR seguinte vai pelos favoritos)", "bool", True),
              Field("rows", "Linhas da varredura", "int", 3, minimum=1, maximum=30),
              Field("cols", "Colunas da varredura", "int", 4, minimum=1, maximum=30),
              Field("step", "Passo (fração da tela)", "float", 0.5, minimum=0.2, maximum=0.7),
              Field("zoom_out", "Afastar zoom (giros da roda)", "int", 15, minimum=0, maximum=40),
              Field("threshold", "Limiar de reconhecimento", "float", 0.84, minimum=0.6, maximum=0.98),
              Field("read_labels", "Ler texto ao lado do ícone", "bool", True)]
    store = ScanStore()

    def defaults(self):
        d = super().defaults()
        d.update({k: v for k, v in SCAN_DEFAULTS.items() if k not in d})
        return d

    def _home(self, ctx, s):
        """Câmera na sua cidade e zoom no mínimo: a origem fixa de todas as posições."""
        ctx.to_base()
        if not ctx.to_world():
            raise RuntimeError("não consegui abrir o mapa")
        ctx.sleep(1.0)
        if ctx.e.backend.name == "pc":
            for _ in range(int(s["zoom_out"])):
                ctx.scroll(-1, 0.5, 0.45)
                ctx.sleep(0.07, human=False)
            ctx.sleep(1.0)
        return ctx.frame()

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

    # O que a IA já reconhece no mapa, por categoria do scanner: o scanner funciona sem você capturar nada.
    # (ícones capturados por você no Estúdio continuam valendo e somam com a IA)
    AI_MAP = {"truck": ("truck_map", "Truck"), "mission": ("task_map", "Secret Task", "Secret Task Ally",
                                                          "Secret Task non-ally"),
              "boss": ("boss_zombie", "boss_walker", "elite_maudite", "garde_marechal"),
              "res_food": ("Farm",), "res_iron": ("Iron Mine",), "res_gold": ("Gold Mine",)}

    def _hits(self, ctx, f, cat, s):
        """Detecções de uma categoria no frame: imagens suas (map_…) + IA. [(x, y, score, w, h)]"""
        out = []
        if ctx.vision.has(f"map_{cat}"):
            out += ctx.vision.find_all(f, f"map_{cat}", float(s["threshold"]))
        if ctx.ai_on():
            d = ctx.dets(f, conf=0.2)
            for cls in self.AI_MAP.get(cat, ()):
                thr = catalog.threshold(cls, ctx.cfg)
                out += [h for h in d.get(cls, []) if h[2] >= max(0.4, thr)]
        return out

    def run(self, ctx, s):
        st = self.store
        ai = ctx.ai_on()
        cats = [k for k, _, _ in CATEGORIES if s["categories"].get(k, True)
                and (ctx.vision.has(f"map_{k}") or (ai and k in self.AI_MAP))]
        if not cats:
            ctx.log("◎ Nada para procurar: ligue a IA (Configurações) ou capture um ícone de mapa (map_…) "
                    "no Estúdio de imagens", "warn")
            return
        ctx.log("◎ Procurando: " + ", ".join(CAT_NAMES[k] for k in cats)
                + ("  (pela IA" + (" + suas imagens)" if any(ctx.vision.has(f"map_{k}") for k in cats) else ")")
                   if ai else ""))
        f = self._home(ctx, s)
        h, w = f.shape[:2]
        rows, cols, step = int(s["rows"]), int(s["cols"]), float(s["step"])
        cam = [0.0, 0.0]
        # começa no canto superior esquerdo da área, para a cidade ficar no meio da varredura
        f, mx, my = self._move(ctx, f, -step * w * (cols - 1) / 2, -step * h * (rows - 1) / 2)
        cam[0] += mx
        cam[1] += my
        st.begin_scan()
        found = 0
        for r in range(rows):
            for c in range(cols):
                for cat in cats:
                    for (x, y, score, tw, th) in self._hits(ctx, f, cat, s):
                        if not (0.1 * w < x < 0.9 * w and 0.12 * h < y < 0.85 * h):
                            continue  # HUD do jogo
                        label = ""
                        if s["read_labels"] and ctx.ocr_on():
                            crop = f[int(max(0, y - th)):int(min(h, y + th * 1.6)),
                                     int(max(0, x - tw * 1.5)):int(min(w, x + tw * 1.5))]
                            label = " ".join(l.text for l in ctx.ocr.read(crop))[:60]
                        st.add(cat, cam[0] + x - w / 2, cam[1] + y - h * 0.45, w, score, label)
                        found += 1
                if c < cols - 1:  # zigue-zague
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

    def go(self, ctx, item, key=None):
        """IR: pelos favoritos do jogo quando o item já foi favoritado (rápido e exato, mesmo longe);
        senão volta para a cidade e anda medindo até ele. Ao chegar, toca no alvo, lê as coordenadas
        reais da ficha e, se ligado, favorita no jogo para os próximos IR."""
        s = ctx.e.cfg.task(self.id, self.defaults())
        if item.get("fav") and item.get("gx") is not None and self._go_favorite(ctx, item):
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
        """Com a ficha do alvo aberta: guarda X:Y reais (OCR) e favorita no jogo (estrela da ficha)."""
        changed = False
        xy = ctx.ocr.coords(ctx.frame(), (0.0, 0.0, 1.0, 0.86)) if ctx.ocr_on() else None
        if xy and 0 <= xy[0] < 3000 and 0 <= xy[1] < 3000:  # grade do servidor: 1000×1000 (3000 na temporada)
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
                    ctx.tap_rel(0.5, 0.45)  # o jogo centraliza no favorito: abre a ficha do alvo
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


class Shield(Task):
    id, name, icon, group = "shield", "Escudo Automático", "⛨", "Sempre ligado"
    description = "Ativa o escudo no horário da agenda e renova quando aparece o aviso de expiração."
    default_interval = 10.0
    templates = [("shield_expiring", "Ícone de escudo acabando/ausente"), ("btn_base_buffs", "Botão de buffs da base"),
                 ("buff_shield", "Linha do escudo nos buffs")]
    fields = [Field("always", "Renovar mesmo sem aviso", "bool", False)]

    def run(self, ctx, s):
        ctx.to_base()
        if not (s["always"] or (ctx.vision.has("shield_expiring") and ctx.exists("shield_expiring", 0.85))):
            return
        ok = ctx.tap("btn_base_buffs", 2) and ctx.tap("buff_shield", 2) and ctx.tap("btn_use", 2)
        ctx.log("⛨ Escudo ativado" if ok else "⛨ Falha ao ativar escudo", "info" if ok else "warn")
        if not ok:
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
