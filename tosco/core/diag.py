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


# Teste de calibração (como o diagnóstico do LWFarmBot): percorre telas e confere o que a IA reconhece, SEM tocar
# em nada que gaste algo. (zona, como abrir, classes esperadas na tela aberta)
CALIB_ZONES = [
    ("Tela principal", None, ("World", "Base", "Chat", "Alliance Tab", "Event", "Heroes", "Inventory", "Mail")),
    ("Eventos", "btn_events", ("screen_event", "event_nav", "arms_race_score")),
    ("Inventário", "btn_inventory", ("screen_inventory", "Return")),
    ("Aliança", "btn_alliance", ("alliance_tech_btn", "alliance_wars_btn", "Return")),
    ("Chat", "btn_chat", ("chat_ally", "chat_input", "chat_text")),
    ("Posto Secreto", "btn_secret_squad", ("secret_tab_perso", "secret_tab_perso_selected", "secret_task_card")),
    ("Heróis", "btn_heroes", ("recruit_btn", "Return")),
]


def calibrate(ctx):
    """Roda como ação avulsa do motor. Devolve [(zona, abriu, [(classe, score ou None)])] e escreve no registro."""
    out = []
    if not ctx.ai_on():
        ctx.log("🩺 Calibração: ligue a IA em Configurações", "warn")
        return out
    for zone, opener, classes in CALIB_ZONES:
        ctx.go_home()
        opened = True
        if opener:
            opened = bool(ctx.tap(opener, 2.5, after=1.5))
        f = ctx.frame()
        det = ctx.dets(f, 0.2)
        found = [(c, round(det[c][0][2], 2) if c in det else None) for c in classes]
        ok = opened and any(sc is not None and sc >= 0.4 for _, sc in found)
        out.append((zone, ok, found))
        seen = ", ".join(f"{c} {sc:.2f}" for c, sc in found if sc is not None) or "nada"
        ctx.log(f"🩺 {'✓' if ok else '✗'} {zone}" + ("" if opened else " (não abriu)") + f" — {seen}",
                "info" if ok else "warn")
        try:
            os.makedirs(DIAG_DIR, exist_ok=True)
            cv2.imwrite(os.path.join(DIAG_DIR, f"calibracao_{len(out)}.jpg"), f, [cv2.IMWRITE_JPEG_QUALITY, 75])
        except Exception:
            pass
    ctx.go_home()
    good = sum(1 for _, ok, _ in out if ok)
    h, w = ctx.frame(fresh=False).shape[:2]
    ctx.log(f"🩺 Calibração: {good}/{len(out)} telas reconhecidas · janela {w}×{h}"
            + ("" if abs(w / h - 16 / 9) < 0.05 else " — proporção fora de 16:9: use o tamanho automático"))
    return out


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
