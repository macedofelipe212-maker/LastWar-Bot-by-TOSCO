"""Estúdio visual (IA): o que a IA do TOSCO reconhece no jogo, com miniatura e nome em português de cada coisa,
agrupado por assunto, e a confiança de cada uma num controle deslizante (como o painel do LWFarmBot).
O botão "O QUE A IA VÊ AGORA" tira um print do jogo e marca, em cada cartão e na imagem, o que foi achado."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

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
        self.thumb = QLabel()
        self.thumb.setFixedSize(40, 40)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet(f"background:#04070e;border:1px solid {T.LINE};border-radius:3px")
        p = catalog.thumb(cls)
        if p:
            self.thumb.setPixmap(QPixmap(p).scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb.setText("?")
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
        self.slider.valueChanged.connect(self._changed)
        row.addWidget(self.slider, 1)
        self.default = _muted("")
        row.addWidget(self.default)
        self.reset = _btn("Redefinir", "ghost", self._reset, "Volta para o valor padrão")
        row.addWidget(self.reset)
        v.addLayout(row)
        self.refresh()

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
        left.addWidget(_muted(
            "Cada cartão é uma coisa do jogo que a IA reconhece sozinha — você não precisa capturar nada. "
            "A confiança (0,10–0,95) é o quanto ela precisa ter certeza: abaixe se o bot não acha algo que está na "
            "tela; aumente se ele clica no lugar errado. Laranja = valor mudado por você."))

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
        self.preview = QLabel("Clique em  ⟳ O QUE A IA VÊ AGORA\ncom o jogo aberto")
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

    def scan(self):
        img = self.engine.capture()
        if img is None:
            self.summary.setText(f"⚠ Não consegui capturar o jogo: {self.engine.backend.describe()}")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            det = self.engine.yolo.detect(img, self.cfg.get("ai_model", "preciso"), conf=SEEN_MIN)
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

    def _draw(self):
        img, det = self._last_img, self._last_det
        pix = bgr_to_pixmap(img)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(T.FONT.split(",")[0])
        f.setPixelSize(max(11, img.shape[0] // 60))
        f.setBold(True)
        p.setFont(f)
        for cls, ds in det.items():
            thr = catalog.threshold(cls, self.cfg, catalog.FIXED.get(cls))
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
        self._pix = pix
        self._fit()

    def _fit(self):
        if getattr(self, "_pix", None) is not None:
            self.preview.setPixmap(self._pix.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()
