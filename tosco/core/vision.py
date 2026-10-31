"""Reconhecimento visual por template (OpenCV): multi-escala, com variantes por template
(ex.: botão em português e em inglês, tema claro/escuro) e cache."""
import glob
import json
import os
import threading

import cv2
import numpy as np

from .paths import TEMPLATE_DIR

BASE_WIDTH = 1920


class Vision:
    def __init__(self):
        os.makedirs(TEMPLATE_DIR, exist_ok=True)
        self._cache = {}
        self._lock = threading.Lock()
        self._widths = self._meta()

    # --- arquivos -------------------------------------------------------
    def _meta(self):
        try:
            with open(os.path.join(TEMPLATE_DIR, "_meta.json"), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_meta(self):
        with open(os.path.join(TEMPLATE_DIR, "_meta.json"), "w", encoding="utf-8") as f:
            json.dump(self._widths, f, indent=1)

    def files(self, name):
        """Arquivos do template: nome.png e variantes nome@<qualquer coisa>.png."""
        base = os.path.join(TEMPLATE_DIR, name)
        return sorted(p for p in glob.glob(glob.escape(base) + "*.png")
                      if os.path.basename(p)[:-4] == name or os.path.basename(p)[:-4].startswith(name + "@"))

    def path(self, name):
        return os.path.join(TEMPLATE_DIR, f"{name}.png")

    def has(self, name):
        return bool(self.files(name))

    def count(self, name):
        return len(self.files(name))

    def available(self):
        return sorted({os.path.basename(f)[:-4].split("@")[0] for f in glob.glob(os.path.join(TEMPLATE_DIR, "*.png"))})

    def save(self, name, bgr, source_width, variant=None):
        """Salva o template (ou uma variante extra) e lembra a largura da janela de origem."""
        fname = f"{name}@{variant}" if variant else name
        cv2.imencode(".png", bgr)[1].tofile(os.path.join(TEMPLATE_DIR, fname + ".png"))
        with self._lock:
            self._widths[fname] = int(source_width)
            self._write_meta()
            self._cache.pop(fname, None)
        return fname

    def next_variant(self, name):
        n = self.count(name)
        return None if n == 0 else str(n + 1)

    def delete(self, name):
        for p in self.files(name):
            os.remove(p)
            self._widths.pop(os.path.basename(p)[:-4], None)
        self._write_meta()

    def load(self, name):
        """Primeira imagem do template (para miniatura)."""
        fs = self.files(name)
        return self._load_file(fs[0]) if fs else None

    def _load_file(self, p):
        key = os.path.basename(p)[:-4]
        mtime = os.path.getmtime(p)
        hit = self._cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img is not None else None
        self._cache[key] = (mtime, (img, gray))
        return img

    def source_width(self, key):
        return self._widths.get(key, BASE_WIDTH)

    # --- busca ----------------------------------------------------------
    def find_all(self, frame, name, threshold=0.85, region=None, max_hits=20, gray=None, color_tol=45):
        """[(cx, cy, score, w, h)] em coordenadas do frame, maior score primeiro, todas as variantes."""
        if frame is None:
            return []
        fs = self.files(name)
        if not fs:
            return []
        full_w = frame.shape[1]
        ox = oy = 0
        if gray is None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if region:  # região relativa (fx, fy, fw, fh) em frações 0..1
            h, w = gray.shape[:2]
            ox, oy = int(region[0] * w), int(region[1] * h)
            gray = gray[oy:oy + int(region[3] * h), ox:ox + int(region[2] * w)]
        hits = []
        for p in fs:
            self._load_file(p)
            key = os.path.basename(p)[:-4]
            timg, tgray = self._cache[key][1]
            if tgray is None:
                continue
            tcol = cv2.mean(timg)[:3]
            base = full_w / self.source_width(key)
            for s in sorted({round(base, 3)} | {round(base * k, 3) for k in (0.92, 1.08)}):
                t = tgray if abs(s - 1.0) < 1e-3 else cv2.resize(tgray, None, fx=s, fy=s,
                                                                 interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
                th, tw = t.shape[:2]
                if th > gray.shape[0] or tw > gray.shape[1] or min(th, tw) < 6:
                    continue
                res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
                for _ in range(max_hits):
                    _, score, _, loc = cv2.minMaxLoc(res)
                    if score < threshold:
                        break
                    cx, cy = ox + loc[0] + tw // 2, oy + loc[1] + th // 2
                    # o formato bateu; a cor média também tem que bater (descarta "pão" achado num muro cinza)
                    patch = frame[cy - th // 2:cy - th // 2 + th, cx - tw // 2:cx - tw // 2 + tw]
                    if patch.size and np.linalg.norm(np.subtract(cv2.mean(patch)[:3], tcol)) <= color_tol:
                        hits.append((cx, cy, float(score), tw, th))
                    cv2.rectangle(res, (max(0, loc[0] - tw // 2), max(0, loc[1] - th // 2)),
                                  (loc[0] + tw // 2, loc[1] + th // 2), -1, -1)
        hits.sort(key=lambda h: -h[2])
        uniq = []
        for h in hits:  # a mesma coisa achada por escalas/variantes diferentes conta uma vez
            if all(abs(h[0] - u[0]) > max(8, h[3] // 3) or abs(h[1] - u[1]) > max(8, h[4] // 3) for u in uniq):
                uniq.append(h)
        return uniq[:max_hits]

    def find(self, frame, name, threshold=0.85, region=None, gray=None):
        hits = self.find_all(frame, name, threshold, region, max_hits=1, gray=gray)
        return hits[0] if hits else None
