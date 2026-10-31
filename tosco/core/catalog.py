"""Catálogo do que a IA reconhece: cada classe do modelo com nome em português, grupo, miniatura e confiança
padrão. Nomes, grupos, miniaturas (data/miniaturas) e padrões vêm do painel do LWFarmBot (mesmo modelo, uso
autorizado pelo autor). A confiança final de cada classe: ajuste seu > limiar fixo da tarefa (YOLO_TARGETS) >
padrão daqui > ai_threshold geral."""
import os

from .paths import DATA_DIR
from .targets import YOLO_TARGETS

THUMB_DIR = os.path.join(DATA_DIR, "miniaturas")
MY_THUMB_DIR = os.path.join(DATA_DIR, "miniaturas_minhas")  # fotos trocadas por você (têm prioridade)

# (classe do modelo, nome em português, confiança padrão)
GROUPS = [
    ("Tesouro (pá + drone)", [
        ("Treasure alert", "Alerta de tesouro (ícone no mapa)", 0.50),
        ("Digging Logo", "Logo da pá (mapa)", 0.60),
        ("Flight Logo", "Logo do drone (mapa)", 0.60),
        ("Dig Help", "Popup de ajuda da pá", 0.50),
        ("Flight Help", "Popup de ajuda do drone", 0.50),
        ("Dig Up Tab", "Aba do timer da pá", 0.40),
        ("Flight Test Tab", "Aba do timer do drone", 0.40),
        ("dig_claim", "Botão de recompensa do tesouro (presente)", 0.65),
        ("dig_center", "Clique preciso na pá", 0.50),
        ("flight_center", "Clique preciso no drone", 0.50),
    ]),
    ("Links de tesouro no bate-papo", [
        ("Chat Dig Up", "Link de pá no bate-papo (ícone)", 0.30),
        ("Chat Dig Text", "Link de pá no bate-papo (texto)", 0.30),
        ("Chat Test Flight", "Link de drone no bate-papo (ícone)", 0.30),
        ("Chat Flight Text", "Link de drone no bate-papo (texto)", 0.30),
        ("chat_input", "Campo de digitação do bate-papo", 0.40),
        ("chat_text", "Área de texto do bate-papo", 0.40),
    ]),
    ("Comuns", [
        ("Event", "Botão Eventos", 0.30),
        ("march_icon", "Botão Marchar", 0.60),
        ("stamina_bar", "Barra de vigor", 0.20),
        ("stamina_out", "Botão Obter Vigor (sem vigor)", 0.50),
        ("timer_text", "Cronômetro (texto)", 0.37),
        ("reward_message", "Popup de recompensa", 0.40),
        ("share_popup", "Popup de compartilhamento", 0.40),
    ]),
    ("Esquadrões", [
        ("team_1", "Esquadrão 1", 0.50),
        ("team_2", "Esquadrão 2", 0.50),
        ("team_3", "Esquadrão 3", 0.50),
        ("team_4", "Esquadrão 4", 0.50),
    ]),
    ("Recuperação / navegação", [
        ("Return", "Botão Voltar (seta)", 0.60),
        ("return_btn", "Botão Voltar", 0.60),
        ("cancel_popup", "Botão Cancelar do popup", 0.60),
        ("confirm_popup", "Botão Confirmar (popup)", 0.40),
        ("Base", "Botão Base", 0.60),
        ("World", "Botão Mundo", 0.60),
        ("close_btn", "Botão Fechar (X)", 0.40),
    ]),
    ("Abas de eventos", [
        ("event_nav", "Barra de navegação de eventos", 0.40),
        ("event_nav_zombie", "Aba zumbis (não selecionada)", 0.40),
        ("event_nav_zombie_selected", "Aba zumbis (selecionada)", 0.60),
    ]),
    ("Farm de zumbis", [
        ("search_btn", "Botão Buscar", 0.60),
        ("attack_btn", "Botão Atacar", 0.50),
    ]),
    ("Mobilizações e descobertas", [
        ("rally_alert_icon", "Alerta de Mobilização (ícone)", 0.60),
        ("discover_btn", "Botão Minhas descobertas", 0.60),
        ("rally_btn", "Bandeira de Mobilização (chefe)", 0.60),
        ("boss_level_text", "Nível do chefe (texto)", 0.30),
        ("distance_km", "Distância KM (mapa)", 0.30),
        ("alliance_wars_btn", "Botão Guerras da Aliança", 0.50),
    ]),
    ("Aliança", [
        ("Ally Help", "Botão Ajuda da Aliança", 0.60),
    ]),
    ("Presente da Sorte", [
        ("treasure_gift", "Ícone Presente da Sorte", 0.60),
        ("treasure_gift_chat", "Presente da Sorte (chat)", 0.60),
        ("treasure_gift_popup", "Popup Presente da Sorte", 0.50),
        ("treasure_gift_popup_btn", "Botão do popup Presente", 0.30),
        ("treasure_gift_popup_reward", "Recompensa Presente da Sorte", 0.40),
    ]),
    ("Coleta de recursos", [
        ("pickaxe_resource", "Ícone de recurso (picareta pós-elite)", 0.50),
        ("share_resource", "Botão de coleta de recurso", 0.30),
    ]),
    ("Escudo e inventário", [
        ("Inventory", "Ícone Inventário", 0.50),
        ("screen_inventory", "Janela Inventário", 0.50),
        ("use_btn", "Botão Usar", 0.50),
        ("shield_8", "Escudo 8h", 0.50),
        ("shield_12", "Escudo 12h", 0.50),
        ("shield_24", "Escudo 24h", 0.50),
    ]),
    ("Arena — Combate 3v3", [
        ("arena", "Edifício Arena (mapa)", 0.30),
        ("arena_vs", "Botão VS", 0.50),
        ("arena_3v3_tab", "Aba Combate 3v3 (não selecionada)", 0.50),
        ("arena_3v3_tab_selected", "Aba Combate 3v3 (selecionada)", 0.50),
        ("arena_3v3_player", "Sua linha na classificação", 0.50),
        ("arena_3v3_player_classement", "Número da posição", 0.25),
        ("challenge_btn", "Botão Desafiar", 0.50),
        ("arena_3v3_teamselect_line", "Linha do esquadrão (Plano de Batalha)", 0.50),
        ("arena_3v3_teamselect_line_power", "Poder do esquadrão (Plano de Batalha)", 0.50),
        ("arena_swap", "Botão Trocar esquadrão", 0.50),
        ("fight_btn", "Botão Iniciar / Lutar", 0.50),
    ]),
    ("Arena de Tempestade", [
        ("arena_storm_tab", "Aba Arena de Tempestade", 0.45),
        ("arena_storm_tab_selected", "Aba Tempestade (selecionada)", 0.45),
        ("arena_storm_player", "Sua linha na classificação", 0.50),
        ("arena_storm_player_classement", "Número da posição", 0.25),
        ("arena_storm_challenge_player", "Linha do adversário (lista)", 0.45),
        ("arena_storm_challenge_player_power", "Poder do adversário (lista)", 0.35),
        ("arena_storm_refresh_list", "Atualização gratuita (lista)", 0.45),
        ("arena_storm_refresh", "Atualização paga (diamantes)", 0.45),
        ("arena_storm_teamselect_line", "Duelo de esquadrões (Plano de Batalha)", 0.50),
        ("arena_storm_teamselect_line_power", "Poder do esquadrão (Plano de Batalha)", 0.50),
    ]),
    ("Recrutar heróis", [
        ("recruit_btn", "Botão Recrutar Heróis", 0.40),
        ("recruit_x1", "Botão recrutar x1", 0.35),
        ("recruit_x10", "Botão recrutar x10", 0.35),
        ("recruit_tab", "Banner da aba (recrutamento)", 0.35),
    ]),
    ("Chefão Foragido", [
        ("event_nav_wanted_boss", "Aba Chefão Foragido (não selecionada)", 0.40),
        ("event_nav_wanted_boss_selected", "Aba Chefão Foragido (selecionada)", 0.40),
        ("btn_go", "Botão Ir", 0.40),
    ]),
    ("Posto de Comando Secreto", [
        ("secret_task_icon", "Ícone de caminhão (Posto Secreto)", 0.50),
        ("secret_quota_ally", "Cota de aliados (x/5)", 0.30),
        ("secret_tab_perso", "Aba Suas Tarefas", 0.55),
        ("secret_tab_ally", "Aba Tarefas de Aliados", 0.55),
        ("secret_task_card", "Cartão de tarefa", 0.55),
        ("secret_assist_btn", "Botão Ajudar", 0.60),
        ("secret_go_btn", "Botão Ir (tarefa pessoal)", 0.60),
        ("secret_collect_btn", "Botão Reivindicar", 0.30),
        ("secret_quick_deploy_btn", "Botão Implantação Rápida", 0.40),
        ("secret_deploy_btn", "Botão Implantar", 0.40),
        ("secret_refresh_btn", "Botão Atualizar", 0.40),
        ("secret_mega_deploy_btn", "Botão Mega Envio", 0.40),
        ("secret_mega_refresh_btn", "Botão Super atualização", 0.40),
        ("secret_mega_execute_btn", "Botão Executar (mega)", 0.30),
        ("secret_mode_normal", "Alternar modo Normal / Mega", 0.35),
        ("secret_special_badge", "Selo de estrela especial", 0.40),
    ]),
]

LABELS = {cls: label for _, items in GROUPS for cls, label, _d in items}
DEFAULTS = {cls: d for _, items in GROUPS for cls, _l, d in items}
# limiares fixos que as tarefas do TOSCO já pedem (ex.: ("dig_claim", 0.8)) valem como padrão dessas classes
FIXED = {c[0]: c[1] for classes in YOLO_TARGETS.values() for c in classes if isinstance(c, tuple)}


def label(cls):
    return LABELS.get(cls, cls)


def default(cls, cfg=None):
    if cls in FIXED:
        return FIXED[cls]
    if cls in DEFAULTS:
        return DEFAULTS[cls]
    return float((cfg or {}).get("ai_threshold", 0.5))


def threshold(cls, cfg, fixed=None):
    """Confiança mínima que vale agora para a classe: o seu ajuste na tela da IA, senão o limiar fixo da tarefa,
    senão o padrão do catálogo, senão o geral."""
    user = (cfg.get("ai_class_thresholds") or {}).get(cls)
    if user is not None:
        return float(user)
    if fixed is not None:
        return float(fixed)
    return default(cls, cfg)


def _fname(cls):
    return cls.replace(" ", "_") + ".png"


def thumb(cls):
    """Caminho da miniatura da classe: a sua (se trocou) ou a original; None se não houver."""
    for d in (MY_THUMB_DIR, THUMB_DIR):
        p = os.path.join(d, _fname(cls))
        if os.path.isfile(p):
            return p
    return None


def is_mine(cls):
    return os.path.isfile(os.path.join(MY_THUMB_DIR, _fname(cls)))


def original_thumb(cls):
    p = os.path.join(THUMB_DIR, _fname(cls))
    return p if os.path.isfile(p) else None


def save_my_thumb(cls, bgr):
    """Troca a foto de exemplo pela sua (recorte do seu jogo ou arquivo). Só ilustra: a IA não usa a foto."""
    import cv2
    os.makedirs(MY_THUMB_DIR, exist_ok=True)
    cv2.imencode(".png", bgr)[1].tofile(os.path.join(MY_THUMB_DIR, _fname(cls)))


def reset_my_thumb(cls):
    p = os.path.join(MY_THUMB_DIR, _fname(cls))
    if os.path.isfile(p):
        os.remove(p)


def target_class(name):
    """Classe principal da IA para um alvo do TOSCO (ex.: 'btn_march' -> 'march_icon'), ou None."""
    classes = YOLO_TARGETS.get(name)
    if not classes:
        return None
    c = classes[0]
    return c[0] if isinstance(c, tuple) else c
