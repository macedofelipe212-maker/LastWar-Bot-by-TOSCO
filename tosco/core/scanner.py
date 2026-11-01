"""Scanner de Mapa: parte da sua cidade (BASE → MUNDO centraliza nela), afasta o zoom ao máximo e varre
em zigue-zague. O Last War não mostra coordenadas na tela do mapa, então o TOSCO mede de verdade quanto a
câmera andou a cada arrasto (correlação de fase entre as imagens) — a posição de cada item fica exata em
relação à sua cidade, e o 'Ir' refaz o caminho medindo até chegar."""
import json
import os
import threading
import time

import cv2
import numpy as np

from .paths import DATA_DIR

CATEGORIES = [
    ("truck", "Caminhões", "⛟"), ("train", "Trens", "🚆"), ("mission", "Missões", "✦"),
    ("ghost_ops", "Ghost Ops", "👻"), ("gold_zombie", "Zumbi Dourado", "☣"), ("boss", "Chefes", "☠"),
    ("res_food", "Comida", "🌾"), ("res_iron", "Ferro", "⛏"), ("res_gold", "Ouro", "◎"),
    ("star_party", "Festa Estelar", "★"), ("season", "Achados da Temporada", "◈"),
    ("custom_1", "Personalizado 1", "①"), ("custom_2", "Personalizado 2", "②"),
]
CAT_NAMES = {k: n for k, n, _ in CATEGORIES}
CAT_ICONS = {k: i for k, _, i in CATEGORIES}

DEFAULTS = {"categories": {k: True for k, _, _ in CATEGORIES}}


def measure_shift(a, b):
    """Quanto o conteúdo da tela andou de a para b (dx, dy em px) e a confiança (0..1).
    Ignora as bordas, onde fica o HUD fixo do jogo."""
    h, w = a.shape[:2]
    y0, y1, x0, x1 = int(h * .15), int(h * .82), int(w * .12), int(w * .86)
    ga = cv2.cvtColor(a[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    gb = cv2.cvtColor(b[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    win = cv2.createHanningWindow(ga.shape[::-1], cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(ga, gb, win)
    return dx, dy, resp


def describe_pos(px, py, w):
    """'→ 2.3  ↓ 0.8 telas' a partir da cidade."""
    if w <= 0:
        return "—"
    sx, sy = px / w, py / w
    hx = ("→" if sx >= 0 else "←") + f" {abs(sx):.1f}"
    hy = ("↓" if sy >= 0 else "↑") + f" {abs(sy):.1f}"
    return f"{hx}  {hy}"


class ScanStore:
    """Resultados persistentes. Itens fixados e ocultos sobrevivem a novas varreduras."""

    def __init__(self, path=os.path.join(DATA_DIR, "mapa.json")):
        self.path = path
        self._lock = threading.Lock()
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        self.items = d.get("items", {})
        self.pinned = set(d.get("pinned", []))
        self.hidden = set(d.get("hidden", []))
        self.last_scan = d.get("last_scan")
        self.queue = d.get("queue", [])  # tarefas secretas para voltar mais tarde: [{"gx", "gy", "at"}]
        self.version = 0

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"items": self.items, "pinned": sorted(self.pinned), "hidden": sorted(self.hidden),
                           "last_scan": self.last_scan, "queue": self.queue}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            self.version += 1

    def begin_scan(self):
        with self._lock:  # mantém fixados e favoritados no jogo; o resto é refeito
            # mantém fixados, favoritados e tarefas já compartilhadas/coletadas (não repete)
            self.items = {k: v for k, v in self.items.items()
                          if k in self.pinned or v.get("fav") or v.get("shared") or v.get("plunders")}

    def add(self, cat, px, py, frame_w, score, label="", gx=None, gy=None, origin=None):
        """gx, gy: casa real do mapa (varredura por coordenadas; distância em casas a partir de origin).
        Sem elas: px, py = posição na tela em relação à cidade, medida em pixels (varredura arrastando)."""
        with self._lock:
            tol = max(18, frame_w * 0.02)
            for k, v in self.items.items():
                if v["cat"] != cat:
                    continue
                if gx is not None and v.get("gx") is not None:
                    same = abs(v["gx"] - gx) <= 2 and abs(v["gy"] - gy) <= 2
                else:
                    same = gx is None and abs(v["px"] - px) <= tol and abs(v["py"] - py) <= tol
                if same:
                    v["seen"] = time.time()
                    if label and not v.get("label"):
                        v["label"] = label
                    return k
            if gx is not None:
                k = f"{cat}:{gx}:{gy}"
                dist = float(np.hypot(gx - origin[0], gy - origin[1])) if origin else 0.0
            else:
                k = f"{cat}:{int(px)}:{int(py)}"
                dist = float(np.hypot(px, py)) / max(1, frame_w)
            self.items[k] = {"cat": cat, "px": int(px), "py": int(py), "w": int(frame_w), "score": round(score, 2),
                             "label": label, "seen": time.time(), "dist": round(dist, 2)}
            if gx is not None:
                self.items[k].update({"gx": int(gx), "gy": int(gy)})
            self.version += 1
            return k

    def toggle_pin(self, k):
        self.pinned.symmetric_difference_update({k})
        self.save()

    def hide(self, k):
        self.hidden.add(k)
        self.pinned.discard(k)
        self.save()

    def restore_hidden(self):
        self.hidden.clear()
        self.save()

    def clear(self):
        self.items = {k: v for k, v in self.items.items() if k in self.pinned}
        self.save()
