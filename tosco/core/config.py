"""Perfis de configuração e contadores diários com horário de reset."""
import copy
import datetime as dt
import json
import os
import threading

from .paths import DATA_DIR

DEFAULTS = {
    "main_task": "auto_digs",            # roda sem parar; as demais são extras com intervalo
    # jogo / plataforma
    "backend": "pc",                      # "pc" (jogo oficial de PC) ou "adb" (emulador)
    "game_window_title": "Last War-Survival Game",
    "game_exe_path": "",
    "adb_path": "",
    "adb_serial": "",
    "resize_to": "auto",                  # auto = tamanho padrão 16:9 que cabe na tela · "" = não mexer · "WxH"
    "restart_wait_seconds": 90,
    "reset_time": "05:00",
    "loop_delay": 1.0,
    # visão
    "ocr_enabled": True,
    "ocr_language": "",                   # vazio = idioma do Windows
    "auto_learn": True,                   # salva template sozinho quando acha o botão pelo texto
    "match_threshold": 0.85,
    "ai_enabled": True,                   # IA de reconhecimento (data/modelos/*.onnx)
    "ai_model": "preciso",                # preciso (1280 px, ~0,4 s) | rapido (640 px, ~0,1 s; perde ícones pequenos)
    "ai_threshold": 0.5,
    "ai_class_thresholds": {},            # ajustes por tipo de botão feitos na tela "Estúdio visual (IA)"
    "guard_clicks": True,                 # nunca toca perto de "Comprar", preço, "Terminar agora"… (core/screens.py)
    "relog_wait_min": 10,                 # conta aberta no celular: espera antes de reconectar
    "pause_on_user": True,                # você mexeu no mouse/teclado → pausa (o mouse é o mesmo)
    "user_resume_s": 20,                  # volta após N s sem você mexer
    # comportamento humano
    "human": {"mouse_curve": True, "delay_factor": 1.0, "tap_spread": 0.25,
              "breaks_enabled": False, "break_every_min": 90, "break_minutes": 8},
    # interface
    "ui": {"language": "pt", "scale": 100, "start_with_windows": False, "start_minimized": False,
           "autostart_engine": False},
    "hotkeys": {"start": "alt+s", "stop": "alt+q", "pause": "alt+p", "resume": "alt+r", "clicker": "alt+c",
                "capture": "f8"},
    "telegram": {"token": "", "chat_id": "", "enabled": False, "commands": True, "status_minutes": 0,
                 "notify_digs": True, "notify_errors": True},
    "events": [],                         # agenda: [{"time","days","action","target","enabled"}]
    "logging_enabled": True,
    "tasks": {},
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Config:
    def __init__(self, path=os.path.join(DATA_DIR, "settings.json")):
        self.path = path
        self._lock = threading.RLock()
        raw = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                os.replace(path, path + ".corrompido")
        self.active = raw.get("active_profile", "Padrão")
        self.profiles = raw.get("profiles", {})
        self.profiles.setdefault(self.active, {})
        self.data = _merge(DEFAULTS, self.profiles[self.active])
        # versões antigas gravavam "" (não mexer) sem a pessoa escolher: passa uma vez para o tamanho padrão
        if self.data.get("resize_to") == "" and not self.data.get("_mig_resize_auto"):
            self.data["resize_to"] = "auto"
        self.data["_mig_resize_auto"] = True

    def task(self, task_id, schema_defaults):
        with self._lock:
            cur = self.data["tasks"].get(task_id, {})
            self.data["tasks"][task_id] = _merge(schema_defaults, cur)
            return self.data["tasks"][task_id]

    def switch(self, name):
        with self._lock:
            self.profiles[self.active] = self.data
            self.active = name
            self.data = _merge(DEFAULTS, self.profiles.setdefault(name, {}))

    def save(self):
        with self._lock:
            self.profiles[self.active] = self.data
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"active_profile": self.active, "profiles": self.profiles}, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)


class Counters:
    """Contadores que zeram no horário de reset do servidor (ex.: 05:00)."""

    def __init__(self, cfg, path=os.path.join(DATA_DIR, "contadores_diarios.json")):
        self.cfg, self.path = cfg, path
        self._lock = threading.Lock()
        self.listener = None  # f(chave, n) a cada add: o motor soma também no contador da sessão
        try:
            with open(path, encoding="utf-8") as f:
                self.state = json.load(f)
        except Exception:
            self.state = {"day": None, "values": {}}
        self.check_reset()

    def _game_day(self):
        try:
            h, m = map(int, self.cfg.data.get("reset_time", "05:00").split(":"))
        except ValueError:
            h, m = 5, 0
        return (dt.datetime.now() - dt.timedelta(hours=h, minutes=m)).date().isoformat()

    def check_reset(self):
        with self._lock:
            day = self._game_day()
            if self.state.get("day") != day:
                self.state = {"day": day, "values": {}}
                self._save()
                return True
        return False

    def get(self, key):
        return self.state["values"].get(key, 0)

    def add(self, key, n=1):
        with self._lock:
            self.state["values"][key] = self.state["values"].get(key, 0) + n
            self._save()
            val = self.state["values"][key]
        if self.listener:
            self.listener(key, n)
        return val

    def all(self):
        return dict(self.state["values"])

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)
