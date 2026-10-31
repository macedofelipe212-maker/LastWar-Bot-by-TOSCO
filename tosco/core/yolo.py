"""IA de reconhecimento (YOLOv8 em ONNX): acha botões e ícones do jogo em qualquer resolução e idioma,
sem precisar capturar imagens. O modelo fica em data/modelos/ (lw_rapido.onnx 640 px, lw_preciso.onnx 1280 px).
Sem o arquivo ou sem onnxruntime, o TOSCO segue só com imagens e OCR."""
import ast
import os
import threading
import time

import cv2
import numpy as np

from .paths import MODEL_DIR

MODELS = {"rapido": "lw_rapido.onnx", "preciso": "lw_preciso.onnx"}


class Yolo:
    def __init__(self):
        self._lock = threading.Lock()
        self._sess, self._names, self._size, self._kind = None, {}, 640, None
        self._cache = (None, None)  # (frame, detecções)
        self.error = ""
        self.last_ms = 0

    def path(self, kind):
        return os.path.join(MODEL_DIR, MODELS.get(kind, MODELS["rapido"]))

    def available(self, kind="rapido"):
        return os.path.isfile(self.path(kind)) or os.path.isfile(self.path("rapido"))

    def _load(self, kind):
        if self._sess is not None and self._kind == kind:
            return True
        p = self.path(kind)
        if not os.path.isfile(p):
            p = self.path("rapido" if kind == "preciso" else "preciso")
        if not os.path.isfile(p):
            self.error = "modelo não encontrado em data/modelos"
            return False
        try:
            import onnxruntime as ort
            prov = [x for x in ("DmlExecutionProvider", "CPUExecutionProvider") if x in ort.get_available_providers()]
            self._sess = ort.InferenceSession(p, providers=prov)
            meta = self._sess.get_modelmeta().custom_metadata_map
            self._names = {int(k): v for k, v in ast.literal_eval(meta["names"]).items()}
            self._size = int(self._sess.get_inputs()[0].shape[2])
            self._kind, self.error = kind, ""
            return True
        except Exception as e:  # noqa: BLE001 — sem IA o bot continua
            self._sess, self.error = None, f"IA indisponível: {e}"
            return False

    @property
    def names(self):
        return set(self._names.values())

    def detect(self, frame, kind="rapido", conf=0.35):
        """{classe: [(cx, cy, score, w, h), ...]} em coordenadas do frame, maior score primeiro.
        Resultado guardado por frame: várias buscas no mesmo frame custam uma inferência só."""
        if self._cache[0] is frame:
            return self._cache[1]
        with self._lock:
            if not self._load(kind):
                return {}
            sz = self._size
            h, w = frame.shape[:2]
            r = min(sz / w, sz / h)
            nw, nh = int(round(w * r)), int(round(h * r))
            px, py = (sz - nw) // 2, (sz - nh) // 2
            canvas = np.full((sz, sz, 3), 114, np.uint8)
            canvas[py:py + nh, px:px + nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            x = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
            t = time.time()
            out = self._sess.run(None, {self._sess.get_inputs()[0].name: x})[0][0]
            self.last_ms = int((time.time() - t) * 1000)
        scores = out[4:]
        cls, sc = scores.argmax(0), scores.max(0)
        keep = sc >= conf
        b, cls, sc = out[:4, keep].T, cls[keep], sc[keep]
        res = {}
        if len(sc):
            boxes = [[(bx[0] - bx[2] / 2 - px) / r, (bx[1] - bx[3] / 2 - py) / r, bx[2] / r, bx[3] / r] for bx in b]
            for i in np.array(cv2.dnn.NMSBoxes(boxes, sc.tolist(), conf, 0.5)).flatten():
                x0, y0, bw, bh = boxes[i]
                name = self._names.get(int(cls[i]), str(cls[i]))
                res.setdefault(name, []).append((int(x0 + bw / 2), int(y0 + bh / 2), float(sc[i]), int(bw), int(bh)))
            for v in res.values():
                v.sort(key=lambda d: -d[2])
        self._cache = (frame, res)
        return res
