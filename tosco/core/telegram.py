"""Controle pelo celular via Telegram: avisos (escavação, erro, crash, conexão) e comandos
(/status, /print, /iniciar, /parar, /pausar, /retomar, /log, /modulos, /ligar, /desligar).
Só obedece ao chat_id configurado."""
import json
import threading
import time
import urllib.parse
import urllib.request
import uuid

import cv2

HELP = ("TOSCO — comandos:\n"
        "/status — estado, módulo atual e contadores\n"
        "/print — captura da tela do jogo\n"
        "/iniciar  /parar  /pausar  /retomar\n"
        "/log — últimas 20 linhas do registro\n"
        "/modulos — lista os módulos e se estão ligados\n"
        "/ligar <id>  /desligar <id> — liga/desliga um módulo\n"
        "/agora <id> — executa um módulo já\n"
        "/clicker — liga/desliga o auto clicker")


class Telegram:
    def __init__(self, cfg):
        self.cfg = cfg
        self.handler = None  # função(comando, argumento) -> texto ou ("photo", bgr, legenda)
        self._offset = None
        self._thread = None
        self._stop = threading.Event()

    @property
    def tg(self):
        return self.cfg.data["telegram"]

    def configured(self):
        return bool(self.tg.get("enabled") and self.tg.get("token") and self.tg.get("chat_id"))

    def _api(self, method, data=None, files=None, timeout=20):
        url = f"https://api.telegram.org/bot{self.tg['token']}/{method}"
        if files:
            boundary = uuid.uuid4().hex
            body = b""
            for k, v in (data or {}).items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
            for k, (fname, content, ctype) in files.items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                         f"Content-Type: {ctype}\r\n\r\n").encode() + content + b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            req = urllib.request.Request(url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        else:
            req = urllib.request.Request(url, urllib.parse.urlencode(data or {}).encode())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def send(self, text):
        if not self.configured():
            return False
        threading.Thread(target=self._safe, args=("sendMessage", {"chat_id": self.tg["chat_id"],
                                                                  "text": text[:4000]}), daemon=True).start()
        return True

    def send_photo(self, bgr, caption=""):
        if not self.configured() or bgr is None:
            return False
        ok, png = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        threading.Thread(target=self._safe, args=("sendPhoto", {"chat_id": self.tg["chat_id"], "caption": caption},
                                                  {"photo": ("tela.jpg", png.tobytes(), "image/jpeg")}),
                         daemon=True).start()
        return True

    def _safe(self, method, data, files=None):
        try:
            self._api(method, data, files)
        except Exception:
            pass

    # --- comandos -------------------------------------------------------
    def start_polling(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop_polling(self):
        self._stop.set()

    def _poll(self):
        while not self._stop.is_set():
            if not (self.configured() and self.tg.get("commands")):
                time.sleep(5)
                continue
            try:
                params = {"timeout": 25}
                if self._offset:
                    params["offset"] = self._offset
                res = self._api("getUpdates", params, timeout=35)
                for up in res.get("result", []):
                    self._offset = up["update_id"] + 1
                    msg = up.get("message") or {}
                    if str(msg.get("chat", {}).get("id")) != str(self.tg["chat_id"]):
                        continue  # ignora estranhos
                    text = (msg.get("text") or "").strip()
                    if text.startswith("/"):
                        cmd, _, arg = text[1:].partition(" ")
                        self._answer(cmd.split("@")[0].lower(), arg.strip())
            except Exception:
                time.sleep(8)

    def _answer(self, cmd, arg):
        if cmd in ("start", "ajuda", "help"):
            self.send(HELP)
            return
        if not self.handler:
            return
        try:
            out = self.handler(cmd, arg)
        except Exception as ex:
            out = f"erro: {ex}"
        if isinstance(out, tuple) and out[0] == "photo":
            if not self.send_photo(out[1], out[2]):
                self.send("sem imagem do jogo")
        elif out:
            self.send(out)
