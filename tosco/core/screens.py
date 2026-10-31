"""Em que tela o jogo está: IA (classes, independe do idioma) + texto (OCR). Também as regras de segurança
dos toques (botões que gastam diamante/dinheiro) e a faixa do chat na tela principal.

Fonte das regras: LastWarBotu (screens.detect_screen, guard_click, yz.nokta_guvenli) e LWFarmBot (utils.on_main).
"""
import re

from .ocr import norm

# --- telas pelo texto: (tela, palavras-chave). A primeira que bater vence, então as mais específicas vêm antes.
TEXT_SCREENS = [
    ("other_device", ["outro dispositivo", "outro aparelho", "another device", "otro dispositivo",
                      "autre appareil", "farkli bir cihaz"]),
    # textos em PT conferidos no dicionário do próprio jogo (locale pt.json, repositório last-war-survival-game-RE)
    ("maintenance", ["servidor esta em manutencao", "manutencao", "maintenance", "mantenimiento", "bakim"]),
    ("connection_lost", ["conexao perdida", "rede desconectada", "erro de rede", "servidor desconectado",
                         "connection lost", "network error", "desconectado", "disconnected",
                         "reconectar", "reconnect", "tentar novamente", "falha no login"]),
    ("exit_game", ["sair do jogo", "exit the game", "quit the game", "quit game", "salir del juego", "oyundan cik"]),
    ("loading", ["carregando", "loading", "cargando", "chargement", "yukleniyor", "enviando solicitacao de login"]),
    ("insufficient", ["insuficiente", "pouca resistencia", "insufficient", "not enough"]),
    ("story", ["pular", "skip"]),  # só vale no topo da tela (ver detect)
]

# --- telas pela IA: (tela, classes; basta uma)
AI_SCREENS = [
    ("exit_game", ("cancel_popup",)),  # refinado pelo texto
    ("chat", ("chat_ally", "chat_world", "chat_moment", "chat_private", "chat_input")),
    ("march", ("march_icon", "team_1", "team_2", "team_3", "team_4", "march_slot")),
    ("dig_popup", ("Dig Up Tab", "Flight Test Tab", "dig_claim")),
    ("gift_popup", ("treasure_gift_popup", "treasure_gift_popup_btn")),
    ("stamina", ("stamina_card", "stamina_use_btn", "stamina_use_free")),
    ("secret_tasks", ("secret_task_card", "secret_deploy_btn", "secret_mega_deploy_btn")),
    ("alliance_tech", ("screen_ally_tech", "ally_tech_donate_btn", "ally_tech_node")),
    ("alliance_war", ("screen_alliance_war", "rally_card")),
    ("arena", ("arena_vs", "arena_storm_tab", "arena_3v3_tab")),
    ("recruit", ("recruit_tab", "recruit_x1", "recruit_x10")),
    ("inventory", ("screen_inventory",)),
    ("event", ("screen_event",)),
    ("share", ("share_popup",)),
    ("confirm", ("confirm_popup",)),
    ("info", ("info_popup", "tap_close_text", "reward_message")),
    ("panel", ("Return", "return_btn", "close_btn")),
]

# Telas em que o certo é esperar (não apertar nada)
WAIT_SCREENS = ("loading", "maintenance")


def chat_band(frame_shape):
    """Retângulo (x0, y0, x1, y1) da faixa do chat embaixo da tela principal (1920×1057: y > 950, x < 1700)."""
    h, w = frame_shape[:2]
    return 0, int(h * 0.90), int(w * 0.885), h


def in_chat_band(x, y, frame_shape):
    x0, y0, x1, y1 = chat_band(frame_shape)
    return x0 <= x < x1 and y >= y0


def detect(lines, dets, frame_shape):
    """Nome da tela. lines: OCR (pode ser None/[]); dets: detecções da IA ({} sem IA).
    'base' / 'world' = tela principal sem nada por cima; 'unknown' = não reconhecida."""
    h, w = frame_shape[:2]
    on_main = bool(dets) and ("World" in dets or "Base" in dets)
    texts = []
    for ln in lines or []:
        if on_main and in_chat_band(ln.x + ln.w // 2, ln.y + ln.h // 2, frame_shape):
            continue  # mensagens do chat não dizem nada sobre a tela
        texts.append((norm(ln.text), ln))
    for name, keys in TEXT_SCREENS:
        for t, ln in texts:
            if any(k in t for k in keys):
                if name == "story" and not (ln.y < h * 0.15 and ln.x > w * 0.6):
                    continue  # "Pular ▶▶" da história fica no topo direito
                return name
    for name, classes in AI_SCREENS:
        if name == "exit_game":
            continue  # "Sair do jogo" só pelo texto (o Cancelar existe em muitos diálogos)
        if any(c in dets for c in classes):
            return name
    if dets:
        if "World" in dets:
            return "base"
        if "Base" in dets:
            return "world"
    return "unknown"


# --- segurança dos toques ---------------------------------------------------------------------------------
# Texto perto do ponto do toque que torna o toque proibido (gasta diamante/dinheiro ou é irreversível).
DANGER_TEXT = ["comprar", "compre ja", "terminar agora", "concluir agora", "finalizar agora", "completar agora",
               "acabar agora", "aceleracao instantanea", "acelerar instantaneamente", "diamantes para",
               "gaste diamantes", "apagar tudo", "excluir tudo", "deletar tudo", "ativar vip", "teletransport",
               "teleportar", "teleporte",
               "buy", "purchase", "finish now", "complete now", "delete all", "activate vip", "teleport",
               "satin al", "simdi bitir"]
DANGER_PRICE = re.compile(r"(R\$|US\$|\$|€|£)\s*\d|\d[\d.,]*\s*(R\$|\$|€|£)")
# Classes da IA que são compra
DANGER_CLASSES = ("stamina_buy_btn", "ally_tech_donate_gem", "Hot Deals", "Mall")


def danger_class(dets, x, y, pad=6):
    """Classe de compra cuja caixa contém o ponto, ou None."""
    for cls in DANGER_CLASSES:
        for cx, cy, _sc, bw, bh in dets.get(cls, []):
            if abs(x - cx) <= bw / 2 + pad and abs(y - cy) <= bh / 2 + pad:
                return cls
    return None


def danger_text(raw):
    """Palavra proibida no texto lido em volta do toque, ou None."""
    if DANGER_PRICE.search(raw or ""):
        return "preço"
    t = norm(raw or "")
    for k in DANGER_TEXT:
        if re.search(r"(?<![a-z])" + re.escape(k), t):
            return k
    return None
