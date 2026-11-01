"""Estúdio visual (IA): o que a IA do TOSCO reconhece no jogo, com miniatura e nome em português de cada coisa,
agrupado por assunto, e a confiança de cada uma num controle deslizante (como o painel do LWFarmBot).
O botão "O QUE A IA VÊ AGORA" tira um print do jogo e marca, em cada cartão e na imagem, o que foi achado."""
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from ..core import catalog
from . import theme as T
from .widgets import Card, bgr_to_pixmap

SEEN_MIN = 0.2  # abaixo disso nem conta como "viu alguma coisa"


def _btn(text, kind=None, slot=None, tip=None):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def _muted(text):
    lab = QLabel(text)
    lab.setObjectName("muted")
    return lab


SLIDER_HELP = ("Confiança: o quanto a IA precisa ter certeza antes do bot usar isto.\n"
               "← Menor: aceita mesmo em dúvida. Use se o bot NÃO acha isto na tela (cartão laranja, 'fraco').\n"
               "→ Maior: só aceita com muita certeza. Use se o bot clica no lugar ERRADO.\n"
               "Não mexe na foto — a foto é só exemplo de como isto aparece no jogo.")


def annotate(img, det, cfg):
    """Print do jogo com caixa + nome em português de tudo que a IA achou: verde = o bot usa, laranja = fraco."""
    pix = bgr_to_pixmap(img)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    f = QFont(T.FONT.split(",")[0])
    f.setPixelSize(max(11, img.shape[0] // 60))
    f.setBold(True)
    p.setFont(f)
    for cls, ds in det.items():
        thr = catalog.threshold(cls, cfg, catalog.FIXED.get(cls))
        for x, y, sc, bw, bh in ds:
            col = QColor(T.LIME if sc >= thr else T.AMBER)
            p.setPen(QPen(col, max(2, img.shape[0] // 400)))
            r = QRectF(x - bw / 2, y - bh / 2, bw, bh)
            p.drawRect(r)
            text = f"{catalog.label(cls)} {sc:.2f}"
            tw = p.fontMetrics().horizontalAdvance(text) + 6
            th = p.fontMetrics().height()
            bg = QRectF(max(0, min(r.left(), img.shape[1] - tw)), max(0, r.top() - th), tw, th)  # não corta na borda
            p.fillRect(bg, QColor(0, 0, 0, 170))
            p.drawText(bg.adjusted(3, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
    p.end()
    return pix


class ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


def _big(pix, w=360, h=240):
    return pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pix.isNull() else pix


class ItemDialog(QDialog):
    """Clique na miniatura: foto ampliada + como está no seu jogo agora + trocar a foto."""

    def __init__(self, card):
        super().__init__(card)
        self.card, self.page, cls = card, card.page, card.cls
        self.setWindowTitle(card.name)
        self.setMinimumWidth(820)
        self.setStyleSheet(f"QDialog {{ background:{T.PANEL}; }}")
        v = QVBoxLayout(self)
        h = QLabel(card.name)
        h.setStyleSheet("font-size:18px;font-weight:800")
        v.addWidget(h)
        v.addWidget(_muted(f"Classe da IA: {cls} · confiança atual {card.current():.2f} "
                           f"(padrão {catalog.default(cls, self.page.cfg):.2f})"))
        row = QHBoxLayout()
        self.ex = self._panel(row, "FOTO DE EXEMPLO" + ("  (sua)" if catalog.is_mine(cls) else "  (original)"))
        p = catalog.thumb(cls)
        if p:
            self.ex.setPixmap(_big(QPixmap(p)))
        else:
            self.ex.setText("sem foto")
        self.live = self._panel(row, "NO SEU JOGO AGORA")
        v.addLayout(row)
        look = QHBoxLayout()
        look.addStretch()
        look.addWidget(_btn("⟳ Procurar no jogo agora", "accent", self._look,
                            "Tira um print do jogo agora e mostra à direita onde a IA achou isto"))
        v.addLayout(look)
        self.names = catalog.targets_for(cls)
        vis = self.page.engine.vision
        if self.names:
            linked = ", ".join(f"{n} ({'●' if vis.has(n) else '○'})" for n in self.names)
            v.addWidget(_muted(f"Ligado ao Estúdio de imagens: {linked}   (● já tem imagem sua · ○ ainda não)"))
        else:
            v.addWidget(_muted("Nenhuma tarefa do TOSCO usa isto ainda — por isso não aparece no Estúdio de imagens."))
        help_ = _muted(SLIDER_HELP)
        help_.setWordWrap(True)
        v.addWidget(help_)
        bar = QHBoxLayout()
        self.use_btn = _btn("📷 Usar o recorte do meu jogo", "go", self._use_live,
                            "Vira a foto daqui E a imagem do Estúdio de imagens (o TOSCO procura essa imagem antes "
                            "da IA: mais rápido e exato na sua tela)")
        bar.addWidget(self.use_btn)
        self._show_live()
        if self.names:
            bar.addWidget(_btn("▣ Abrir no Estúdio de imagens", None, self._open_studio1,
                               "Vai para o Estúdio de imagens já com este nome escolhido"))
        bar.addWidget(_btn("📂 Trocar por arquivo…", None, self._from_file, "Escolhe um PNG/JPG do seu PC"))
        r = _btn("↺ Voltar à original", None, self._reset)
        r.setEnabled(catalog.is_mine(cls) and catalog.original_thumb(cls) is not None)
        bar.addWidget(r)
        bar.addStretch()
        bar.addWidget(_btn("Fechar", None, self.accept))
        v.addLayout(bar)

    def _show_live(self):
        self.crop = self.page.crop_of(self.card.cls)
        if self.crop is not None:
            sc = self.page.last_scores.get(self.card.cls, 0)
            self.live.setPixmap(_big(bgr_to_pixmap(self.crop)))
            self.live.setToolTip(f"Achado com confiança {sc:.2f}")
        elif self.page._last_img is None:
            self.live.setText("Ainda não olhei o jogo.\n\nClique em  ⟳ Procurar no jogo agora.")
        else:
            self.live.setText("A IA não achou isto na tela atual do jogo.\n\nAbra no jogo a tela onde isto aparece\n"
                              "e clique em  ⟳ Procurar no jogo agora.")
        self.use_btn.setEnabled(self.crop is not None)

    def _look(self):
        self.page.scan()
        self._show_live()

    def _panel(self, row, title):
        box = QVBoxLayout()
        t = QLabel(title)
        t.setObjectName("h")
        box.addWidget(t)
        lab = QLabel()
        lab.setAlignment(Qt.AlignCenter)
        lab.setFixedSize(380, 260)
        lab.setStyleSheet(f"background:#04070e;border:1px solid {T.LINE};color:{T.MUTED}")
        box.addWidget(lab)
        row.addLayout(box)
        return lab

    def _done(self):
        self.card.reload_thumb()
        self.accept()

    def _use_live(self):
        catalog.save_my_thumb(self.card.cls, self.crop)
        # o mesmo recorte vira imagem no Estúdio de imagens de cada nome ligado: o TOSCO procura a imagem SUA
        # primeiro (template, exato na sua tela) e só depois a IA
        img = self.page._last_img
        vis = self.page.engine.vision
        for n in self.names:
            vis.save(n, self.crop, img.shape[1], vis.next_variant(n), source_height=img.shape[0])
        if self.names:
            self.page.engine.log(f"▣ Recorte de '{self.card.name}' salvo também no Estúdio de imagens: "
                                 + ", ".join(self.names))
        self.page.win.refresh_studio()
        self._done()

    def _open_studio1(self):
        self.accept()
        self.page.win.open_studio(self.names[0])

    def _from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Escolher foto", "", "Imagens (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            catalog.save_my_thumb(self.card.cls, img)
            self._done()

    def _reset(self):
        catalog.reset_my_thumb(self.card.cls)
        self._done()


class ItemCard(QFrame):
    """Um tipo de coisa que a IA reconhece: miniatura, nome, se foi visto agora, confiança e padrão."""

    def __init__(self, page, cls, name):
        super().__init__()
        self.page, self.cls, self.name = page, cls, name
        self.setObjectName("card")
        self.setToolTip(f"{name}\nclasse da IA: {cls}")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.thumb = ClickLabel()
        self.thumb.setFixedSize(40, 40)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setCursor(Qt.PointingHandCursor)
        self.thumb.setToolTip("Clique para ampliar e trocar a foto")
        self.thumb.clicked.connect(lambda: ItemDialog(self).exec())
        self.reload_thumb()
        top.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = QLabel(name)
        self.title.setStyleSheet("font-weight:700")
        self.title.setWordWrap(True)
        col.addWidget(self.title)
        self.seen = _muted("—")
        col.addWidget(self.seen)
        top.addLayout(col, 1)
        self.value = QLabel()
        self.value.setStyleSheet(f"font-family:{T.MONO};color:{T.CYAN};font-size:13px")
        top.addWidget(self.value)
        v.addLayout(top)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(10, 95)
        self.slider.setToolTip(SLIDER_HELP)
        self.slider.valueChanged.connect(self._changed)
        row.addWidget(self.slider, 1)
        self.default = _muted("")
        row.addWidget(self.default)
        self.reset = _btn("Redefinir", "ghost", self._reset, "Volta para o valor padrão")
        row.addWidget(self.reset)
        v.addLayout(row)
        self.refresh()

    def reload_thumb(self):
        p = catalog.thumb(self.cls)
        mine = catalog.is_mine(self.cls)
        self.thumb.setStyleSheet(f"background:#04070e;border:1px solid {T.LIME if mine else T.LINE};"
                                 f"border-radius:3px")
        if p:
            self.thumb.setPixmap(QPixmap(p).scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb.setText("?")

    def current(self):
        return catalog.threshold(self.cls, self.page.cfg, catalog.FIXED.get(self.cls))

    def refresh(self):
        d = catalog.default(self.cls, self.page.cfg)
        cur = self.current()
        self.slider.blockSignals(True)
        self.slider.setValue(round(cur * 100))
        self.slider.blockSignals(False)
        self.value.setText(f"{cur:.2f}")
        self.default.setText(f"padrão {d:.2f}")
        custom = self.cls in (self.page.cfg.get("ai_class_thresholds") or {})
        self.reset.setEnabled(custom)
        self.value.setStyleSheet(f"font-family:{T.MONO};color:{T.AMBER if custom else T.CYAN};font-size:13px")

    def _changed(self, v):
        val = round(v / 100, 2)
        store = self.page.cfg.setdefault("ai_class_thresholds", {})
        if abs(val - catalog.default(self.cls, self.page.cfg)) < 0.005:
            store.pop(self.cls, None)
        else:
            store[self.cls] = val
        self.page.changed()
        self.refresh()
        self.page.restyle_seen(self)

    def _reset(self):
        (self.page.cfg.get("ai_class_thresholds") or {}).pop(self.cls, None)
        self.page.changed()
        self.refresh()
        self.page.restyle_seen(self)

    def show_seen(self, score):
        """score: maior confiança desta classe no último print (None = não viu nada)."""
        thr = self.current()
        if score is None:
            self.seen.setText("não visto agora")
            self.seen.setStyleSheet(f"color:{T.MUTED};font-size:11px")
        elif score >= thr:
            self.seen.setText(f"● visto agora · {score:.2f}")
            self.seen.setStyleSheet(f"color:{T.LIME};font-size:11px")
        else:
            self.seen.setText(f"◐ fraco · {score:.2f} (abaixo de {thr:.2f}: ignorado)")
            self.seen.setStyleSheet(f"color:{T.AMBER};font-size:11px")


class Section(QWidget):
    """Grupo que abre e fecha (ex.: TESOURO (PÁ + DRONE))."""

    def __init__(self, title, cards, open_=False):
        super().__init__()
        self.cards = cards
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.head = QPushButton()
        self.head.setCheckable(True)
        self.head.setChecked(open_)
        self.head.setStyleSheet(
            f"QPushButton {{ text-align:left; padding:8px 12px; border:1px solid {T.rgba(T.AMBER, 0.55)};"
            f" color:{T.TEXT}; background:{T.rgba(T.AMBER, 0.05)}; font-weight:700; letter-spacing:1px; }}"
            f"QPushButton:checked {{ background:{T.rgba(T.AMBER, 0.12)}; border:1px solid {T.AMBER}; color:{T.AMBER}; }}"
            f"QPushButton:hover {{ border:1px solid {T.AMBER}; color:{T.AMBER}; }}")
        self.title = title
        self.head.toggled.connect(self._toggle)
        v.addWidget(self.head)
        self.body = QWidget()
        g = QGridLayout(self.body)
        g.setContentsMargins(0, 2, 0, 6)
        g.setSpacing(6)
        for i, c in enumerate(cards):
            g.addWidget(c, i // 2, i % 2)
        v.addWidget(self.body)
        self._toggle(open_)

    def _toggle(self, on):
        self.body.setVisible(on)
        self.update_head()

    def update_head(self, seen=None):
        arrow = "▾" if self.head.isChecked() else "▸"
        extra = f"   ·   {seen} visto(s) agora" if seen else ""
        self.head.setText(f"{arrow}  {self.title.upper()}   ({len(self.cards)}){extra}")


class VisionPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.engine = win, win.engine
        self.last_scores = {}
        lay = QHBoxLayout(self)
        lay.setSpacing(12)

        left = QVBoxLayout()
        bar = QHBoxLayout()
        bar.addWidget(_btn("⟳ O QUE A IA VÊ AGORA", "accent", self.scan,
                           "Tira um print do jogo e marca em cada cartão o que a IA achou"))
        self.filter = QLineEdit(placeholderText="procurar… (ex.: pá, marchar, chat)")
        self.filter.textChanged.connect(self._filter)
        bar.addWidget(self.filter, 1)
        self.only_seen = QCheckBox("só o que foi visto")
        self.only_seen.toggled.connect(self._filter)
        bar.addWidget(self.only_seen)
        self.count = _muted("")
        bar.addWidget(self.count)
        bar.addWidget(_btn("Redefinir tudo", "ghost", self.reset_all, "Apaga todos os seus ajustes de confiança"))
        left.addLayout(bar)
        intro = _muted(
            "⟳ O QUE A IA VÊ AGORA = um teste: tira um print do jogo do jeito que está na sua tela e mostra o que o "
            "bot consegue enxergar ali (caixas no print à direita e ● verde nos cartões). Abra no jogo a tela que "
            "quer testar e clique. "
            "Cada cartão é uma coisa do jogo que a IA reconhece sozinha — você não precisa capturar nada. "
            "Clique na FOTO para ampliar e trocar (a foto é só exemplo; a IA não depende dela). "
            "A BARRINHA é a confiança: ← para a esquerda se o bot não acha isto na tela; → para a direita se ele "
            "clica no lugar errado. Número laranja = valor mudado por você · borda verde na foto = foto sua.")
        intro.setWordWrap(True)
        left.addWidget(intro)

        self.cards, self.sections = [], []
        holder = QWidget()
        holder.setObjectName("visionHolder")
        holder.setStyleSheet("QWidget#visionHolder { background: transparent; }")
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 6, 0)
        hv.setSpacing(8)
        for i, (title, items) in enumerate(catalog.GROUPS):
            cards = [ItemCard(self, cls, name) for cls, name, _d in items]
            self.cards += cards
            sec = Section(title, cards, open_=(i == 0))
            self.sections.append(sec)
            hv.addWidget(sec)
        hv.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.viewport().setAutoFillBackground(False)  # sem isso o miolo fica com o cinza claro do Windows
        left.addWidget(scroll, 1)
        lay.addLayout(left, 3)

        right = Card("O que a IA viu")
        self.preview = ClickLabel("Clique em  ⟳ O QUE A IA VÊ AGORA\ncom o jogo aberto")
        self.preview.setCursor(Qt.PointingHandCursor)
        self.preview.setToolTip("Clique para ver o print grande")
        self.preview.clicked.connect(self._zoom_preview)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(360, 220)
        self.preview.setStyleSheet(f"background:#04070e;border:1px dashed {T.LINE};color:{T.MUTED}")
        right.lay.addWidget(self.preview, 1)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.lay.addWidget(self.summary)
        right.lay.addWidget(_muted("Verde: passou da confiança e o bot usa.  Laranja: viu, mas fraco demais "
                                   "(ignorado) — se for o botão certo, abaixe a confiança dele."))
        right.setMinimumWidth(380)
        lay.addWidget(right, 2)
        self._last_img = None
        self.changed(save=False)

    @property
    def cfg(self):
        return self.win.cfg.data

    def changed(self, save=True):
        n = len(self.cfg.get("ai_class_thresholds") or {})
        self.count.setText(f"{n} ajuste(s) seu(s)" if n else "valores padrão")
        if save:
            self.win.save_soon()
            if self._last_img is not None:
                self._draw()

    def reset_all(self):
        self.cfg["ai_class_thresholds"] = {}
        for c in self.cards:
            c.refresh()
            self.restyle_seen(c)
        self.changed()

    def restyle_seen(self, card):
        if self.last_scores:
            card.show_seen(self.last_scores.get(card.cls))

    def _filter(self, *_):
        q = self.filter.text().lower().strip()
        only = self.only_seen.isChecked()
        for sec in self.sections:
            vis = 0
            for c in sec.cards:
                ok = (not q or q in c.name.lower() or q in c.cls.lower() or q in sec.title.lower())
                if only:
                    ok = ok and c.cls in self.last_scores
                c.setVisible(ok)
                vis += ok
            sec.setVisible(vis > 0)
            if (q or only) and vis:
                sec.head.setChecked(True)

    def showEvent(self, e):
        """Ao abrir a tela já olha o jogo uma vez (sem precisar descobrir o botão)."""
        super().showEvent(e)
        if self._last_img is None and not getattr(self, "_auto_tried", False):
            self._auto_tried = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(150, self.scan)

    def scan(self):
        img = self.engine.capture()
        if img is None:
            self.summary.setText(f"⚠ Não consegui ver o jogo: {self.engine.backend.describe()}\n"
                                 "Abra o jogo e clique em  ⟳ O QUE A IA VÊ AGORA.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            det = self.engine.yolo.detect(img, self.cfg.get("ai_model", "preciso"), conf=SEEN_MIN)
        except Exception as ex:  # mostra na tela em vez de falhar calado
            self.summary.setText(f"⚠ Erro ao olhar o jogo: {type(ex).__name__}: {ex}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not det and self.engine.yolo.error:
            self.summary.setText(f"⚠ IA indisponível: {self.engine.yolo.error}")
            return
        self._last_img, self._last_det = img, det
        self.last_scores = {cls: max(d[2] for d in ds) for cls, ds in det.items()}
        for c in self.cards:
            c.show_seen(self.last_scores.get(c.cls))
        for sec in self.sections:
            sec.update_head(sum(1 for c in sec.cards if c.cls in self.last_scores
                                and self.last_scores[c.cls] >= c.current()))
        known = set(catalog.LABELS)
        others = sorted(((s, cls) for cls, s in self.last_scores.items() if cls not in known), reverse=True)
        ok = sum(1 for c in self.cards if c.cls in self.last_scores and self.last_scores[c.cls] >= c.current())
        weak = sum(1 for c in self.cards if c.cls in self.last_scores and self.last_scores[c.cls] < c.current())
        txt = (f"Tela {img.shape[1]}×{img.shape[0]} · IA em {self.engine.yolo.last_ms} ms\n"
               f"● {ok} reconhecido(s) e usados · ◐ {weak} fraco(s)")
        if others:
            txt += "\nOutros que a IA também viu: " + ", ".join(f"{cls} {s:.2f}" for s, cls in others[:12])
        self.summary.setText(txt)
        self._draw()
        self._filter()

    def crop_of(self, cls):
        """Recorte do último print onde a IA viu esta classe (a melhor caixa), ou None."""
        img, det = self._last_img, getattr(self, "_last_det", None) or {}
        if img is None or not det.get(cls):
            return None
        x, y, _sc, bw, bh = det[cls][0]
        mx, my = int(bw * 0.15) + 4, int(bh * 0.15) + 4
        H, W = img.shape[:2]
        c = img[max(0, y - bh // 2 - my):min(H, y + bh // 2 + my), max(0, x - bw // 2 - mx):min(W, x + bw // 2 + mx)]
        return c.copy() if c.size else None

    def _draw(self):
        self._pix = annotate(self._last_img, self._last_det, self.cfg)
        self._fit()

    def _zoom_preview(self):
        if getattr(self, "_pix", None) is None:
            return
        d = QDialog(self)
        d.setWindowTitle("O que a IA viu")
        scr = QApplication.primaryScreen().availableGeometry()
        lab = QLabel()
        lab.setPixmap(self._pix.scaled(int(scr.width() * 0.9), int(scr.height() * 0.85), Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
        QVBoxLayout(d).addWidget(lab)
        d.exec()

    def _fit(self):
        if getattr(self, "_pix", None) is not None:
            self.preview.setPixmap(self._pix.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class LiveVision(QWidget):
    """Janela que fica ao lado do jogo e mostra, a cada segundo, o que a IA está vendo. Com o bot rodando usa
    o mesmo print que o bot acabou de olhar (não tira outro); parado, tira um print sozinho. Só olha, nunca clica."""
    got = Signal(object, object, float, str)

    def __init__(self, win, on_close=None):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.win, self.engine, self.on_close = win, win.engine, on_close
        self.setWindowTitle("TOSCO · o que a IA vê (ao vivo)")
        self.setStyleSheet(win.styleSheet())
        scr = QApplication.primaryScreen().availableGeometry()
        self.resize(min(760, scr.width() // 2), min(520, scr.height() // 2))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.status = QLabel("Olhando o jogo…")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(240, 140)
        self.view.setStyleSheet("background:#000; border-radius:6px")
        lay.addWidget(self.view, 1)
        self.found = _muted("")
        self.found.setWordWrap(True)
        lay.addWidget(self.found)
        lay.addWidget(_muted("Verde = o bot usa · Laranja = viu, mas achou fraco (não usa) · "
                             "Só olha: não clica nem mexe no jogo."))
        self._pix, self._busy, self._seen_t = None, False, 0.0
        self.got.connect(self._show)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    @property
    def cfg(self):
        return self.win.cfg.data  # lido sempre: trocar de perfil troca o dicionário

    def showEvent(self, e):
        super().showEvent(e)
        self.timer.start()
        self._tick()

    def closeEvent(self, e):
        self.timer.stop()
        if self.on_close:
            self.on_close()
        super().closeEvent(e)

    def _tick(self):
        if self._busy:
            return
        e = self.engine
        bot = e.running and not e.paused and time.time() - e.last_frame_t < 5
        if bot and e.last_frame_t == self._seen_t:
            return  # o bot ainda não olhou de novo
        self._busy = True
        threading.Thread(target=self._work, args=(bot,), daemon=True).start()

    def _work(self, bot):
        e, t = self.engine, 0.0
        try:
            if bot:
                img, t = e.last_frame, e.last_frame_t
            else:
                img = e.backend.capture()  # direto: não suja o log do bot com "captura falhou"
            if img is None:
                self.got.emit(None, None, t, "Não consegui ver o jogo (fechado ou minimizado?)")
                return
            det = e.yolo.detect(img, self.cfg.get("ai_model", "preciso"), conf=SEEN_MIN)
            self.got.emit(img, det, t, "")
        except Exception as ex:
            self.got.emit(None, None, t, f"Erro: {ex}")

    def _show(self, img, det, t, err):
        self._busy = False
        self._seen_t = t or self._seen_t
        e = self.engine
        who = (f"Bot {e.state()} · fazendo: {e.current} · print do bot" if t else
               f"Bot {e.state()} · print tirado por esta janela")
        if err:
            self.status.setText(f"{who}\n⚠ {err}")
            return
        used, weak = [], []
        for cls, ds in det.items():
            thr = catalog.threshold(cls, self.cfg, catalog.FIXED.get(cls))
            (used if ds[0][2] >= thr else weak).append(catalog.label(cls) + (f" ×{len(ds)}" if len(ds) > 1 else ""))
        self.status.setText(f"{who} · {time.strftime('%H:%M:%S')} · IA {e.yolo.last_ms:.0f} ms")
        self.found.setText((f"✔ Usa: {', '.join(sorted(used))}" if used else "✔ Nada que o bot use agora") +
                           (f"\n◌ Fraco: {', '.join(sorted(weak))}" if weak else ""))
        self._pix = annotate(img, det, self.cfg)
        self._fit()

    def _fit(self):
        if self._pix is not None:
            self.view.setPixmap(self._pix.scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()
