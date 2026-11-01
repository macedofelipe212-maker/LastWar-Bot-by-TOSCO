"""Pacote de diagnóstico: um .zip com o que é preciso para entender um problema — log de hoje e de ontem,
contadores, configuração SEM segredos, versão/ambiente e (se você quiser) os últimos prints do jogo."""
import copy
import datetime as dt
import json
import os
import platform
import sys
import time
import zipfile

import cv2

from .paths import DATA_DIR, LOG_DIR, MODEL_DIR

DIAG_DIR = os.path.join(DATA_DIR, "diagnostico")
SECRET_KEYS = ("token", "chat_id", "password", "senha", "api_key", "key")


def _mask(obj):
    """Cópia da configuração com tokens, chat_id, chaves etc. trocados por '***'."""
    if isinstance(obj, dict):
        return {k: ("***" if any(s in str(k).lower() for s in SECRET_KEYS) and v else _mask(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask(v) for v in obj]
    return obj


def _env(engine):
    b = engine.backend
    try:
        where = b.describe()
    except Exception as ex:
        where = f"erro: {ex}"
    models = sorted(f for f in os.listdir(MODEL_DIR) if f.endswith(".onnx")) if os.path.isdir(MODEL_DIR) else []
    return {
        "gerado_em": dt.datetime.now().isoformat(timespec="seconds"),
        "executavel": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "windows": platform.platform(),
        "plataforma": b.name,
        "jogo": where,
        "estado": engine.state(),
        "fazendo": engine.current,
        "modelos_ia": models,
        "ia_ms": getattr(engine.yolo, "last_ms", None),
        "stats": engine.stats,
        "sessao": engine.session,
    }


def make(engine, include_prints=True):
    """Cria o zip em data/diagnostico e devolve o caminho."""
    os.makedirs(DIAG_DIR, exist_ok=True)
    path = os.path.join(DIAG_DIR, time.strftime("diagnostico_%Y-%m-%d_%H%M%S.zip"))
    today = dt.date.today()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for d in (today - dt.timedelta(days=1), today):
            log = os.path.join(LOG_DIR, f"log_{d:%Y-%m-%d}.txt")
            if os.path.exists(log):
                z.write(log, f"logs/{os.path.basename(log)}")
        cfg = _mask(copy.deepcopy({"perfil": engine.cfg.active, "config": engine.cfg.data}))
        z.writestr("configuracao_sem_segredos.json", json.dumps(cfg, indent=2, ensure_ascii=False))
        z.writestr("contadores_hoje.json", json.dumps(engine.counters.all(), indent=2, ensure_ascii=False))
        z.writestr("ambiente.json", json.dumps(_env(engine), indent=2, ensure_ascii=False, default=str))
        z.writestr("ultimas_linhas.txt", "\n".join(engine.lines[-300:]))
        if include_prints:
            for i, (t, img) in enumerate(list(engine.recent_frames)):
                h, w = img.shape[:2]
                if w > 1280:  # menor: o zip continua fácil de mandar
                    img = cv2.resize(img, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    z.writestr(f"prints/{i + 1}_{time.strftime('%H%M%S', time.localtime(t))}.jpg", buf.tobytes())
    return path
