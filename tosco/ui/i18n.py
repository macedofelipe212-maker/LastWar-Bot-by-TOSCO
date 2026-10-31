"""Textos da interface. O jogo pode estar em qualquer idioma (isso é tratado pelo OCR/templates);
aqui é só a língua dos menus do TOSCO."""

LANGS = {"pt": "Português", "en": "English", "es": "Español"}

T = {
    "nav.dash": ("PAINEL", "DASHBOARD", "PANEL"),
    "nav.mods": ("MÓDULOS", "MODULES", "MÓDULOS"),
    "nav.map": ("MAPA", "MAP", "MAPA"),
    "nav.agenda": ("AGENDA", "SCHEDULE", "AGENDA"),
    "nav.clicker": ("CLICKER", "CLICKER", "CLICKER"),
    "nav.studio": ("ESTÚDIO", "STUDIO", "ESTUDIO"),
    "nav.system": ("SISTEMA", "SETTINGS", "SISTEMA"),
    "nav.log": ("REGISTRO", "LOG", "REGISTRO"),
    "title.dash": ("PAINEL DE CONTROLE", "CONTROL PANEL", "PANEL DE CONTROL"),
    "title.mods": ("MÓDULOS DE AUTOMAÇÃO", "AUTOMATION MODULES", "MÓDULOS DE AUTOMATIZACIÓN"),
    "title.map": ("SCANNER DE MAPA", "MAP SCANNER", "ESCÁNER DE MAPA"),
    "title.agenda": ("AGENDA DE EVENTOS", "EVENT SCHEDULE", "AGENDA DE EVENTOS"),
    "title.clicker": ("AUTO CLICKER", "AUTO CLICKER", "AUTO CLICKER"),
    "title.studio": ("ESTÚDIO DE TEMPLATES", "TEMPLATE STUDIO", "ESTUDIO DE PLANTILLAS"),
    "title.system": ("SISTEMA", "SETTINGS", "SISTEMA"),
    "title.log": ("REGISTRO DE EVENTOS", "EVENT LOG", "REGISTRO DE EVENTOS"),
    "btn.start": ("▶ INICIAR", "▶ START", "▶ INICIAR"),
    "btn.pause": ("❚❚ PAUSAR", "❚❚ PAUSE", "❚❚ PAUSAR"),
    "btn.resume": ("▶ RETOMAR", "▶ RESUME", "▶ REANUDAR"),
    "btn.stop": ("■ PARAR", "■ STOP", "■ DETENER"),
    "state.ATIVO": ("ATIVO", "RUNNING", "ACTIVO"),
    "state.PAUSADO": ("PAUSADO", "PAUSED", "PAUSADO"),
    "state.PARADO": ("PARADO", "STOPPED", "DETENIDO"),
    "card.engine": ("Status do motor", "Engine status", "Estado del motor"),
    "card.view": ("Visão do jogo", "Game view", "Vista del juego"),
    "card.queue": ("Fila de módulos", "Module queue", "Cola de módulos"),
    "card.events": ("Últimos eventos", "Latest events", "Últimos eventos"),
    "card.today": ("Hoje", "Today", "Hoy"),
    "stat.runs": ("execuções", "runs", "ejecuciones"),
    "stat.taps": ("toques", "taps", "toques"),
    "stat.errors": ("erros", "errors", "errores"),
    "stat.digs": ("escavações hoje", "digs today", "excavaciones hoy"),
    "stat.joins": ("rallies hoje", "rallies today", "rallies hoy"),
    "stat.hunts": ("caçadas hoje", "hunts today", "cacerías hoy"),
    "uptime": ("tempo ativo", "uptime", "tiempo activo"),
    "now": ("agora", "now", "ahora"),
    "profile": ("PERFIL", "PROFILE", "PERFIL"),
    "new_profile": ("+ novo perfil", "+ new profile", "+ nuevo perfil"),
}

_IDX = {"pt": 0, "en": 1, "es": 2}
_lang = "pt"


def set_lang(code):
    global _lang
    _lang = code if code in _IDX else "pt"


def tr(key):
    row = T.get(key)
    return row[_IDX[_lang]] if row else key
