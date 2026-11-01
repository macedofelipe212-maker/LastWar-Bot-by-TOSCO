"""Páginas de módulos em cartões: grade fluida de cartões (ícone, chave, descrição, resumo em verde) e um
painel lateral com as configurações do cartão selecionado."""
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (QFormLayout, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core.engine import DAYS, Card, Field
from ..core.targets import TEXT_TARGETS
from . import theme as T
from .widgets import Toggle

ICON_TINTS = [T.CYAN, T.MAGENTA, T.LIME, T.AMBER, "#8a7dff", "#ff7a59"]

FREQ_FIELDS = [Field("interval_min", "A cada (minutos)", "float", 30.0, minimum=0.1, maximum=10080),
               Field("days", "Dias (" + ",".join(DAYS) + ")", "text", ",".join(DAYS)),
               Field("hours", "Horário (ex.: 08:00-23:00)", "text", "00:00-23:59")]


class FlowLayout(QLayout):
    """Distribui os cartões em linhas que quebram conforme a largura (responsivo)."""

    def __init__(self, parent=None, spacing=12):
        super().__init__(parent)
        self._items, self._sp = [], spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > rect.right() and line > 0:
                x, y, line = rect.x(), y + line + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._sp
            line = max(line, hint.height())
        return y + line - rect.y()


def field_text(f, v):
    if f.kind == "bool":
        return "sim" if v else "não"
    if f.kind == "float":
        return f"{float(v):g}"
    return str(v)


def auto_summary(card, s, fields_by_key):
    if callable(card.summary):
        return card.summary(s)
    if isinstance(card.summary, str):
        try:
            return card.summary.format(**s)
        except (KeyError, ValueError, IndexError):
            return card.summary
    parts = []
    for k in card.fields:
        f = fields_by_key.get(k)
        if f and f.kind != "code":
            parts.append(field_text(f, s.get(k, f.default)))
    return " · ".join(parts)[:70]


def build_cards(task):
    """Cartões do módulo: os definidos à mão, ou gerados (um por chave + um de ajustes)."""
    if task.cards:
        return task.cards
    bools = [f for f in task.fields if f.kind == "bool"]
    others = [f for f in task.fields if f.kind != "bool"]
    sec = [Card(f.label, "◆", f.hint or "", toggle=f.key) for f in bools]
    if others:
        sec.append(Card("Ajustes", "⚙", "Quantidades, ordem e limites.", fields=[f.key for f in others]))
    return [("Opções", sec)] if sec else []


class CardTile(QFrame):
    clicked = Signal(object)

    def __init__(self, page, card, tint, task, s, whole=False):
        """s: dict de configuração do módulo; whole: o cartão representa o módulo inteiro (chave = ligado)."""
        super().__init__()
        self.page, self.card, self.task, self.s, self.whole = page, card, task, s, whole
        self.fields_by_key = {f.key: f for f in task.fields + FREQ_FIELDS}
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(236, 146)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        ic = QLabel(card.icon)
        ic.setFixedSize(30, 30)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(f"background:{T.rgba(tint, 0.13)};border:1px solid {T.rgba(tint, 0.35)};border-radius:7px;color:{tint};font-size:15px")
        head.addWidget(ic)
        title = QLabel(card.title)
        title.setWordWrap(True)
        title.setStyleSheet("font-weight:700;font-size:13px;letter-spacing:0")
        head.addWidget(title, 1)
        self.toggle = None
        if card.toggle:
            self.toggle = Toggle(bool(s.get(card.toggle)))
            self.toggle.toggled.connect(self._toggled)
            head.addWidget(self.toggle, 0, Qt.AlignTop)
        lay.addLayout(head)
        d = QLabel(card.desc)
        d.setWordWrap(True)
        d.setObjectName("muted")
        d.setStyleSheet("font-size:11px")
        lay.addWidget(d, 1)
        foot = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"color:{T.LIME};font-size:10px;font-weight:600")
        foot.addWidget(self.summary, 1)
        if card.fields:
            cfg = QLabel("☰ Configurações")
            cfg.setStyleSheet(f"color:{T.CYAN};background:{T.rgba(T.CYAN, 0.08)};border-radius:4px;padding:1px 6px;font-size:10px")
            foot.addWidget(cfg, 0, Qt.AlignBottom)
        lay.addLayout(foot)
        self.refresh()

    def _toggled(self, on):
        self.s[self.card.toggle] = on
        self.page.changed()
        self.refresh()

    def refresh(self):
        self.summary.setText(auto_summary(self.card, self.s, self.fields_by_key))
        on = (self.s.get(self.card.toggle) if self.card.toggle else True)
        self.setProperty("off", not on)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_selected(self, sel):
        self.setProperty("sel", sel)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        self.clicked.emit(self)
        super().mousePressEvent(e)


class TaskPage(QWidget):
    """Página de um ou mais módulos. tasks: [Task]; com vários (ex.: Tarefas Diárias) cada módulo vira um cartão
    cuja chave liga/desliga o módulo e o painel mostra as opções dele."""

    def __init__(self, win, title, subtitle, tasks, make_editor):
        super().__init__()
        self.win, self.tasks, self.make_editor = win, tasks, make_editor
        self.tiles = []
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 6, 0)
        lv.setSpacing(6)
        h = QLabel(title)
        h.setStyleSheet("font-size:22px;font-weight:800")
        lv.addWidget(h)
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        lv.addWidget(sub)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.b_focus = QPushButton()  # só nas tarefas que podem ser o foco do bot
        self.b_focus.setObjectName("chip")
        self.b_focus.clicked.connect(self._toggle_focus)
        bl = QHBoxLayout()
        bl.setSpacing(8)
        bl.addWidget(self.banner, 1)
        bl.addWidget(self.b_focus)
        lv.addLayout(bl)
        self.single = tasks[0] if len(tasks) == 1 else None
        if self.single:
            self._task_sections(lv, self.single)
        else:
            self._multi_sections(lv)
        lv.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(left)
        left.setStyleSheet("background:transparent")
        outer.addWidget(sa, 1)

        self.panel = QFrame()
        self.panel.setObjectName("sidepanel")
        self.panel.setFixedWidth(330)
        self.pv = QVBoxLayout(self.panel)
        self.pv.setContentsMargins(16, 14, 16, 14)
        psa = QScrollArea()
        psa.setWidgetResizable(True)
        psa.setWidget(self.panel)
        psa.setFixedWidth(344)
        self.panel_scroll = psa
        outer.addWidget(psa)
        if self.tiles:
            self._select(self.tiles[0])
        self.refresh_banner()

    # --- construção ------------------------------------------------------
    def _section(self, lv, name):
        lab = QLabel(name)
        lab.setStyleSheet("font-size:14px;font-weight:700;padding-top:10px")
        lv.addWidget(lab)
        box = QWidget()
        flow = FlowLayout(box)
        lv.addWidget(box)
        return flow

    def _add(self, flow, card, tint, task, s, whole=False):
        t = CardTile(self, card, tint, task, s, whole)
        t.clicked.connect(self._select)
        flow.addWidget(t)
        self.tiles.append(t)

    def _task_sections(self, lv, task):
        self.s = s = self.win.cfg.task(task.id, task.defaults())
        if not task.main_capable:
            flow = self._section(lv, "Módulo")
            self._add(flow, Card(task.name, task.icon, task.description, toggle="enabled",
                                 fields=["interval_min", "days", "hours"],
                                 summary=lambda s: f"a cada {float(s['interval_min']):g} min · {s.get('hours', '')}"),
                      T.CYAN, task, s)
        for i, (sec, cards) in enumerate(build_cards(task)):
            flow = self._section(lv, sec)
            for j, c in enumerate(cards):
                self._add(flow, c, ICON_TINTS[(i * 3 + j) % len(ICON_TINTS)], task, s)
        flow = self._section(lv, "Quando roda e o que reconhece")
        if task.main_capable:
            self._add(flow, Card("Dias e horário", "◷", "Janela em que o foco do bot trabalha.",
                                 fields=["days", "hours"], summary=lambda s: s.get("hours", "")), T.CYAN, task, s)
        self._add(flow, Card("Imagens do jogo", "▣", "O que este módulo precisa reconhecer na tela.",
                             fields=["__images__"], summary=lambda _s: self._image_summary(task)),
                  T.MAGENTA, task, s)

    def _multi_sections(self, lv):
        groups = {}
        for task in self.tasks:
            groups.setdefault(task.group, []).append(task)
        self.s = {}
        for gi, (g, tasks) in enumerate(groups.items()):
            flow = self._section(lv, g)
            for j, task in enumerate(tasks):
                s = self.win.cfg.task(task.id, task.defaults())
                card = Card(task.name, task.icon, task.description, toggle="enabled", fields=["__task__"],
                            summary=lambda s, task=task: f"a cada {float(s['interval_min']):g} min · "
                                                         f"{self._image_summary(task, short=True)}")
                self._add(flow, card, ICON_TINTS[(gi * 3 + j) % len(ICON_TINTS)], task, s, whole=True)

    def _image_summary(self, task, short=False):
        names = [n for n, _ in task.templates]
        if not names:
            return "sem imagens" if short else "não precisa de imagens"
        ok = self._ready(names)
        return f"{len(ok)}/{len(names)} imagens" if short else f"imagens {len(ok)}/{len(names)} prontas"

    def _ready(self, names):
        ocr = self.win.engine.ocr.enabled and self.win.cfg.data.get("ocr_enabled", True)
        return [n for n in names if self.win.engine.vision.has(n) or (ocr and n in TEXT_TARGETS)]

    # --- painel lateral -------------------------------------------------
    def _clear_panel(self):
        while self.pv.count():
            it = self.pv.takeAt(0)
            w = it.widget()
            if w:
                w.hide()  # some já; deleteLater só apaga no próximo ciclo de eventos
                w.deleteLater()
            elif it.layout():
                _clear_layout(it.layout())

    def _select(self, tile):
        for t in self.tiles:
            t.set_selected(t is tile)
        self._clear_panel()
        c, task, s = tile.card, tile.task, tile.s
        head = QHBoxLayout()
        ic = QLabel(c.icon)
        ic.setStyleSheet(f"font-size:22px;color:{T.CYAN}")
        head.addWidget(ic)
        tl = QLabel(c.title)
        tl.setWordWrap(True)
        tl.setStyleSheet("font-size:15px;font-weight:800")
        head.addWidget(tl, 1)
        self.pv.addLayout(head)
        d = QLabel(c.desc)
        d.setWordWrap(True)
        d.setObjectName("muted")
        self.pv.addWidget(d)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setVerticalSpacing(8)
        keys = c.fields
        if keys == ["__task__"]:
            keys = [f.key for f in task.fields] + ["interval_min", "days", "hours"]
        fb = {f.key: f for f in task.fields + FREQ_FIELDS}
        for k in keys:
            if k == "__images__":
                continue
            f = fb.get(k)
            if f:
                lab = QLabel(f.label)
                lab.setObjectName("muted")
                form.addRow(lab, self.make_editor(f, s, lambda tile=tile: (self.changed(), tile.refresh())))
        self.pv.addLayout(form)
        if keys == ["__images__"] or c.fields == ["__task__"]:
            self._images_block(task)
        row = QHBoxLayout()
        b = QPushButton("▶ Executar agora")
        b.setObjectName("go")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False, tid=task.id: self.win.engine.run_now(tid))
        row.addWidget(b)
        row.addStretch()
        self.pv.addSpacing(8)
        self.pv.addLayout(row)
        self.pv.addStretch(1)

    def _images_block(self, task):
        names = task.templates
        if not names:
            return
        lab = QLabel("IMAGENS")
        lab.setObjectName("h")
        self.pv.addWidget(lab)
        ready = set(self._ready([n for n, _ in names]))
        for n, desc in names:
            mark, col = ("●", T.LIME) if self.win.engine.vision.has(n) else \
                (("◐", T.CYAN) if n in ready else ("○", T.MUTED))
            b = QPushButton(f"{mark}  {n}")
            b.setObjectName("ghost")
            b.setStyleSheet(f"color:{col};text-align:left;padding:2px 0")
            b.setToolTip(desc + "\nClique para abrir no Estúdio")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=n: self.win.open_studio(n))
            self.pv.addWidget(b)

    def changed(self):
        self.win.save_soon()
        self.refresh_banner()

    def refresh(self):
        for t in self.tiles:
            t.refresh()
        self.refresh_banner()

    def _toggle_focus(self):
        main = self.win.cfg.data.get("main_task")
        self.win.set_main("" if main == self.single.id else self.single.id)

    def refresh_banner(self):
        self.b_focus.hide()
        if not self.single:
            self.banner.hide()
            return
        task = self.single
        main = self.win.cfg.data.get("main_task")
        if task.main_capable:
            self.b_focus.show()
            if main == task.id:
                txt, col = "🎯 FOCO DO BOT — roda sem parar enquanto o bot está ligado; as outras entram nos intervalos.", T.LIME
                self.b_focus.setText("✕ Tirar do foco")
            else:
                txt, col = "Esta pode ser o foco do bot (a tarefa que ele faz sem parar).", T.MUTED
                self.b_focus.setText("🎯 Tornar o foco do bot")
        else:
            on = self.s.get("enabled")
            txt, col = ("● LIGADO — roda nos intervalos, entre as rodadas do foco do bot." if on else
                        "○ DESLIGADO — ligue no cartão abaixo ou na chave do topo desta página."), \
                (T.LIME if on else T.MUTED)
        self.banner.setText(txt)
        self.banner.setStyleSheet(f"color:{col};border:1px solid {T.rgba(col, 0.35)};background:{T.rgba(col, 0.07)};border-radius:6px;"
                                  f"padding:6px 10px")
        self.banner.show()


def _clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().hide()
            it.widget().deleteLater()
        elif it.layout():
            _clear_layout(it.layout())
