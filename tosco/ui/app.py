"""Janela principal TOSCO."""
import datetime as dt
import html
import os
import subprocess
import sys
import time

import cv2
import numpy as np
from PySide6.QtCore import QObject, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPixmap, QTextCharFormat
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
                               QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget)

from ..core import catalog, winapi
from ..core.backends import ADBBackend, find_adb
from ..core.engine import DAYS, AutoClicker, Engine
from ..core.targets import TEXT_TARGETS
from ..core.paths import DATA_DIR, PRINT_DIR, REPORT_DIR, ROOT, TEMPLATE_DIR
from ..core.scanner import CAT_ICONS, CAT_NAMES, CATEGORIES, describe_pos
from ..tasks import ALL_TASKS, all_templates
from . import theme as T
from .i18n import LANGS, set_lang, tr
from .cards import TaskPage
from .vision_page import LiveVision, VisionPage
from .widgets import Card, CaptureCanvas, GridBackground, Radar, StatCard, Toggle, bgr_to_pixmap, make_icon

LEVEL_COLORS = {"info": T.TEXT, "warn": T.AMBER, "error": T.RED}
APP = "TOSCO"
SCANNER = next(t for t in ALL_TASKS if t.id == "map_scanner")


class Bridge(QObject):
    log = Signal(str, str)
    state = Signal()
    hotkey = Signal(str)


def button(text, kind=None, slot=None, tip=None):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    b.setCursor(Qt.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def muted(text):
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


def scroll(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(widget)
    widget.setStyleSheet("background:transparent")
    return sa


def repolish(w, name):
    w.setObjectName(name)
    w.style().unpolish(w)
    w.style().polish(w)


class FieldEditor:
    """Cria o widget certo para um Field e grava a mudança direto no dict de configuração."""

    @staticmethod
    def make(field, store, on_change):
        k, v = field.key, store.get(field.key, field.default)
        if field.kind == "bool":
            w = Toggle(bool(v))
            w.toggled.connect(lambda x: (store.__setitem__(k, x), on_change()))
        elif field.kind == "int":
            w = QSpinBox()
            w.setRange(field.minimum, field.maximum)
            w.setValue(int(v))
            w.valueChanged.connect(lambda x: (store.__setitem__(k, x), on_change()))
        elif field.kind == "float":
            w = QDoubleSpinBox()
            w.setDecimals(2)
            w.setRange(field.minimum, field.maximum)
            w.setSingleStep(0.05)
            w.setValue(float(v))
            w.valueChanged.connect(lambda x: (store.__setitem__(k, x), on_change()))
        elif field.kind == "choice":
            w = QComboBox()
            w.addItems(field.options)
            w.setCurrentText(str(v))
            w.currentTextChanged.connect(lambda x: (store.__setitem__(k, x), on_change()))
        elif field.kind == "code":
            w = QPlainTextEdit(str(v))
            w.setMinimumHeight(120)
            w.textChanged.connect(lambda: (store.__setitem__(k, w.toPlainText()), on_change()))
        else:
            w = QLineEdit(str(v))
            w.textChanged.connect(lambda x: (store.__setitem__(k, x), on_change()))
        if field.hint:
            w.setToolTip(field.hint)
        return w


DAILY_TASKS = ["survivors", "idle_rewards", "resources", "base_care", "heroes", "alliance", "daily", "secret_squad",
               "trucks", "farm", "arena"]
ADVANCED_TASKS = ["routine_1", "routine_2", "routine_3", "map_scanner"]

# (seção, [(chave, ícone, nome, subtítulo)]); "t:<id>" = página de um módulo
NAV = [
    (None, [("dash", "◉", "Painel", "Radar, contadores do dia, visão ao vivo do jogo e fila de módulos.")]),
    ("TAREFA PRINCIPAL (SÓ UMA)", [
        ("t:auto_digs", "⛏", "Escavações & Ovos", "Espera no chat da aliança e pega escavações, ovos e festas."),
        ("t:hunt", "☣", "Zumbis Dourados & Rally", "Caça zumbis e chefes com a energia que você escolher."),
        ("t:auto_join", "⚔", "Auto-Entrar em Rallies", "Entra nos rallies dos chefes que você escolher."),
    ]),
    ("TAREFAS EXTRAS (ÀS VEZES)", [
        ("daily", "✉", "Tarefas Diárias", "Pequenas tarefas que entram entre as rodadas do foco do bot."),
        ("t:arms_race", "🏁", "Corrida Armamentista", "Ganha pontos da Corrida com o que você permitir."),
        ("t:marshal_guard", "♜", "Guarda do Marechal", "Inicia e entra nos rallies do evento do Marechal."),
        ("t:first_lady", "♛", "Primeira-Dama", "Aprova pedidos de cargos do capitólio."),
    ]),
    ("FERRAMENTAS", [
        ("t:reports", "▤", "Relatórios R4/R5", "VS, doações e abates da aliança salvos em planilha."),
        ("map", "◎", "Scanner de mapa", "Lista o que há em volta da sua cidade, com botão IR."),
        ("clicker", "⌖", "Clique automático", "Clica sem parar num ponto da tela."),
        ("advanced", "⌘", "Rotinas", "Seus próprios passos e varredura agendada do mapa."),
        ("vision", "◉", "Estúdio visual (IA)", "O que a IA reconhece no jogo, com miniatura e nome de cada coisa. "
                                                "Ajuste a confiança e veja ao vivo o que ela enxerga."),
        ("studio", "▣", "Estúdio de imagens", "Suas próprias imagens: capture, recorte, importe e teste."),
    ]),
    ("CONFIGURAÇÃO", [
        ("t:shield", "⛨", "Escudo Automático", "Ativa e renova o escudo."),
        ("agenda", "◷", "Agendar eventos", "Liga, desliga ou roda módulos nos horários que você definir."),
        ("phone", "✆", "Controle pelo celular", "Avisos e comandos pelo Telegram."),
        ("system", "⚙", "Configurações", "Plataforma, OCR, comportamento humano, interface e atalhos."),
        ("log", "≡", "Registro", "Tudo o que o TOSCO fez."),
    ]),
]


def titled(title, subtitle, widget):
    """Cabeçalho grande da página + conteúdo."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    h = QLabel(title)
    h.setStyleSheet("font-size:22px;font-weight:800")
    v.addWidget(h)
    s = QLabel(subtitle)
    s.setObjectName("muted")
    v.addWidget(s)
    v.addSpacing(6)
    v.addWidget(widget, 1)
    return w


class MainWindow(QMainWindow):

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        set_lang(cfg.data["ui"].get("language", "pt"))
        self.bridge = Bridge()
        self.bridge.log.connect(self._on_log)
        self.bridge.state.connect(self._on_state)
        self.bridge.hotkey.connect(self._on_hotkey)
        self.engine = Engine(cfg, ALL_TASKS, self.bridge.log.emit, self.bridge.state.emit)
        self.clicker = AutoClicker(self.engine.log)
        self.engine.clicker = self.clicker
        self.engine.telegram.handler = self._telegram_cmd
        self.engine.telegram.start_polling()
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self.cfg.save)
        self._events_done = set()
        self._map_version = -1

        self.icon, _ = make_icon()
        self.setWindowIcon(self.icon)
        self.setWindowTitle(f"{APP} // Last War: Survival Game")
        self.setMinimumSize(900, 600)
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1440, int(scr.width() * 0.9)), min(900, int(scr.height() * 0.9)))
        root = GridBackground()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # páginas
        self.stack = QStackedWidget()
        self.page_index, self.task_pages = {}, []
        builders = {"dash": self._page_dash, "map": self._page_map, "agenda": self._page_agenda,
                    "clicker": self._page_clicker, "studio": self._page_studio, "system": self._page_system,
                    "vision": self._page_vision,
                    "log": self._page_log, "phone": self._page_phone}
        tasks = {t.id: t for t in ALL_TASKS}
        for _, items in NAV:
            for key, icon, name, sub in items:
                if key.startswith("t:"):
                    page = TaskPage(self, f"{icon}  {name}", sub, [tasks[key[2:]]], FieldEditor.make)
                    self.task_pages.append(page)
                elif key in ("daily", "advanced"):
                    ids = DAILY_TASKS if key == "daily" else ADVANCED_TASKS
                    page = TaskPage(self, f"{icon}  {name}", sub, [tasks[i] for i in ids], FieldEditor.make)
                    self.task_pages.append(page)
                else:
                    inner = builders[key]()
                    page = titled(f"{icon}  {name}", sub, inner) if key != "dash" else inner
                self.page_index[key] = self.stack.addWidget(page)

        outer.addWidget(self._sidebar())
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self._topbar())
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 16, 16, 12)
        wl.addWidget(self.stack)
        main.addWidget(wrap, 1)
        self.statusline = QLabel()
        self.statusline.setObjectName("statusline")
        self.statusline.setStyleSheet(f"color:{T.MUTED};background:#060a14;border-top:1px solid {T.LINE};"
                                      f"padding:4px 14px;font-size:11px")
        main.addWidget(self.statusline)
        outer.addLayout(main, 1)
        self._tray()

        self._tick = QTimer(self, timeout=self._refresh, interval=1000)
        self._tick.start()
        self._agenda_timer = QTimer(self, timeout=self._check_events, interval=15000)
        self._agenda_timer.start()
        self._register_hotkeys()
        self._on_state()
        self._mark_main()
        ocr, yolo = self.engine.ocr, self.engine.yolo
        ai = "desligada"
        if self.cfg.data.get("ai_enabled", True):
            ai = (f"ativa ({len(yolo.names)} tipos de botão)" if yolo._load(self.cfg.data.get("ai_model", "rapido"))
                  else yolo.error or "indisponível")
        from ..core import rapid, tesseract
        # installed() não carrega nada: carregar o RapidOCR aqui travaria a janela; o motor aquece ao iniciar
        nums = "RapidOCR" if rapid.installed() else ("Tesseract" if tesseract.available() else "OCR do Windows")
        self.engine.log(f"{APP} online · OCR: " + (f"ativo ({ocr.language})" if ocr.enabled else "indisponível") +
                        f" · números/cronômetros: {nums} · IA: {ai} · plataforma: {self.engine.backend.name.upper()}")
        if cfg.data["ui"].get("autostart_engine"):
            QTimer.singleShot(3000, self.engine.start)

    # --- estrutura ------------------------------------------------------
    def _sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        self.side = side
        side.setFixedWidth(248)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 10)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(14, 14, 14, 4)
        logo_img = QLabel()
        logo_img.setPixmap(self.icon.pixmap(38, 38))
        head.addWidget(logo_img)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.logo = QLabel(APP)
        self.logo.setObjectName("logo")
        self.logo.setStyleSheet("padding:0;font-size:18px")
        self.logo_sub = QLabel("LAST WAR: SURVIVAL GAME")
        self.logo_sub.setObjectName("logoSub")
        self.logo_sub.setWordWrap(True)
        self.logo_sub.setStyleSheet("padding:0;letter-spacing:2px")  # nome é mais longo: menos espaçamento p/ caber
        col.addWidget(self.logo)
        col.addWidget(self.logo_sub)
        head.addLayout(col, 1)
        outer.addLayout(head)

        self.profile_box = QWidget()
        pl = QHBoxLayout(self.profile_box)
        pl.setContentsMargins(14, 6, 14, 6)
        pl.addWidget(muted(tr("profile")))
        self.profile = QComboBox()
        self.profile.addItems(sorted(self.cfg.profiles))
        self.profile.setCurrentText(self.cfg.active)
        self.profile.currentTextChanged.connect(self._switch_profile)
        pl.addWidget(self.profile, 1)
        pl.addWidget(button("＋", "ghost", self._new_profile, "Novo perfil (ex.: outra conta)"))
        outer.addWidget(self.profile_box)

        navw = QWidget()
        lay = QVBoxLayout(navw)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.nav = QButtonGroup(self)
        self.nav_btns, self.nav_secs = [], []
        for sec, items in NAV:
            if sec:
                s = QLabel(sec)
                s.setObjectName("navsec")
                self.nav_secs.append(s)
                lay.addWidget(s)
            for key, icon, name, _ in items:
                b = QPushButton(f"{icon}   {name}".replace("&", "&&"))  # && = '&' literal (senão vira atalho)
                b.setObjectName("nav")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(name)
                self.nav.addButton(b, self.page_index[key])
                self.nav_btns.append((b, icon, name, key))
                lay.addWidget(b)
        lay.addStretch(1)
        self.nav.button(0).setChecked(True)
        self.nav.idClicked.connect(self._go_page)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(navw)
        navw.setStyleSheet("background:transparent")
        outer.addWidget(sa, 1)
        ver = muted("v3.0")
        ver.setAlignment(Qt.AlignCenter)
        outer.addWidget(ver)
        return side

    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(58)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(8)
        # foco = a tarefa que roda sem parar; fica antes do INICIAR porque é escolhida antes de ligar
        self.main_combo = QComboBox()
        self.main_combo.addItem("🎯 Sem foco (só extras)", "")
        for t in ALL_TASKS:
            if t.main_capable:
                self.main_combo.addItem(f"🎯 {t.name}", t.id)
        self.main_combo.setCurrentIndex(max(0, self.main_combo.findData(self.cfg.data.get("main_task", ""))))
        self.main_combo.currentIndexChanged.connect(self._set_main)
        self.main_combo.setMinimumWidth(220)
        self.main_combo.setToolTip("Foco do bot: a tarefa que ele faz SEM PARAR enquanto está ligado.\n"
                                   "As outras tarefas ligadas são extras: entram só nos intervalos de cada uma\n"
                                   "e depois o bot volta para o foco. 'Nenhum' = só as extras, nos intervalos.")
        lay.addWidget(self.main_combo)
        self.b_start = button(tr("btn.start"), "go", self.engine.start)
        self.b_start.setToolTip("Atalho: Alt+S")
        lay.addWidget(self.b_start)
        self.b_pause = button(tr("btn.pause"), "warn", self._pause_resume)
        self.b_pause.setToolTip("Pausar: Alt+P · Retomar: Alt+R")
        self.b_stop = button(tr("btn.stop"), "danger", self.engine.stop)
        self.b_stop.setToolTip("Atalho: Alt+Q")
        lay.addWidget(self.b_pause)
        lay.addWidget(self.b_stop)
        # liga/desliga na hora a pausa quando você mexe no mouse/teclado (também em Configurações)
        self.b_userpause = QPushButton()
        self.b_userpause.setObjectName("chip")
        self.b_userpause.setCheckable(True)
        self.b_userpause.setChecked(bool(self.cfg.data.get("pause_on_user", True)))
        self.b_userpause.toggled.connect(self._toggle_userpause)
        self._toggle_userpause(self.b_userpause.isChecked(), log=False)
        lay.addWidget(self.b_userpause)
        # liga/desliga uma janelinha que mostra ao vivo o que a IA está vendo
        self.live = None
        self.b_live = QPushButton("👁 Ver o que a IA vê")
        self.b_live.setObjectName("chip")
        self.b_live.setCheckable(True)
        self.b_live.setToolTip("Abre uma janela por cima de tudo que se atualiza sozinha a cada segundo com o que a\n"
                               "IA reconhece no jogo (com o bot rodando, é o mesmo print que o bot acabou de olhar).\n"
                               "Só olha: não clica nem mexe no jogo. Clique de novo (ou feche a janela) para desligar.")
        self.b_live.toggled.connect(self._toggle_live)
        lay.addWidget(self.b_live)
        lay.addStretch(1)
        self.pill = QLabel()
        self.pill.setFixedHeight(30)
        self.pill.setMaximumWidth(240)
        lay.addWidget(self.pill)
        return bar

    def _toggle_userpause(self, on, log=True):
        self.cfg.data["pause_on_user"] = bool(on)
        self.b_userpause.setText("✋ Pausar se eu mexer")  # aceso = ligado (estado pela cor)
        self.b_userpause.setToolTip(
            "LIGADO: quando você mexe no mouse/teclado, o TOSCO solta o controle e volta após uns segundos parado.\n"
            "DESLIGADO: o TOSCO continua mesmo com você no PC (o mouse é o mesmo: vocês dois vão disputar).")
        if log:
            self.save_soon()
            self.engine.log("✋ Pausa quando você mexe: " + ("ligada" if on else "DESLIGADA — o bot não espera você"))

    def _toggle_live(self, on):
        # o estado (aceso = ligado) aparece pela cor do botão; o texto fica fixo
        if on and self.live is None:
            self.live = LiveVision(self, on_close=lambda: self.b_live.setChecked(False))
            self.live.show()
        elif not on and self.live is not None:
            live, self.live = self.live, None
            live.on_close = None
            live.close()
            live.deleteLater()

    def set_main(self, task_id):
        """Escolhe o foco do bot (também usado pelo botão '★ Tornar o foco' na página da tarefa)."""
        self.main_combo.setCurrentIndex(max(0, self.main_combo.findData(task_id or "")))

    def _set_main(self, _=None):
        self.cfg.data["main_task"] = self.main_combo.currentData()
        self.save_soon()
        self._mark_main()
        self.engine.log(f"🎯 Foco do bot: {self.main_combo.currentText().replace('🎯 ', '')}")

    def _mark_main(self):
        main = self.cfg.data.get("main_task")
        for b, icon, name, key in self.nav_btns:
            star = key == f"t:{main}"
            b.setProperty("main", star)
            txt = icon if self.side.width() < 100 else f"{icon}   {name}" + ("   ★" if star else "")
            b.setText(txt.replace("&", "&&"))
        for p in self.task_pages:
            p.refresh_banner()

    def open_studio(self, name):
        self._go_page(self.page_index["studio"])
        self.nav.button(self.page_index["studio"]).setChecked(True)
        self.tpl_filter.clear()
        self._fill_templates()
        for i in range(self.tpl_list.count()):
            if self.tpl_list.item(i).data(Qt.UserRole) == name:
                self.tpl_list.setCurrentRow(i)
                break

    def _page_vision(self):
        self.vision_page = VisionPage(self)
        return self.vision_page

    def open_vision(self, cls):
        """Estúdio de imagens -> Estúdio visual, já filtrado no tipo da IA ligado a este nome."""
        self._go_page(self.page_index["vision"])
        self.nav.button(self.page_index["vision"]).setChecked(True)
        self.vision_page.filter.setText(catalog.label(cls))

    def refresh_studio(self):
        """Depois que o Estúdio visual salva uma imagem: atualiza a lista e as miniaturas do Estúdio de imagens."""
        self._fill_templates()
        self._tpl_selected(self.tpl_list.currentItem())

    def _studio_open_vision(self):
        cls = catalog.target_class(self._current_tpl() or "")
        if not cls:
            self._studio_msg("Este nome não é reconhecido pela IA — use as imagens daqui (capturar/importar).", False)
            return
        self.open_vision(cls)

    def _go_page(self, i):
        self.stack.setCurrentIndex(i)
        page = self.stack.widget(i)
        if isinstance(page, TaskPage):
            page.refresh()
        if i == self.page_index.get("map"):
            self._fill_map(force=True)
        if i == self.page_index.get("studio"):
            self._fill_templates()

    def resizeEvent(self, e):
        """Responsivo: em telas estreitas o menu vira só ícones e o painel do Painel vira duas colunas."""
        super().resizeEvent(e)
        if not hasattr(self, "side"):
            return
        narrow = self.width() < 1180
        self.side.setFixedWidth(64 if narrow else 248)
        self.logo.setVisible(not narrow)
        self.logo_sub.setVisible(not narrow)
        self.profile_box.setVisible(not narrow)
        for s in self.nav_secs:
            s.setVisible(not narrow)
        self._mark_main()
        if hasattr(self, "dash_grid"):
            self._layout_dash(self.width() < 1300)

    def _tray(self):
        self.tray = QSystemTrayIcon(self.icon, self)
        m = QMenu()
        m.addAction("Mostrar", self._show_from_tray)
        m.addAction(tr("btn.start"), self.engine.start)
        m.addAction(tr("btn.stop"), self.engine.stop)
        m.addSeparator()
        m.addAction("Sair", self._quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self._show_from_tray() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip(APP)
        self.tray.show()

    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def _quit(self):
        self._really_quit = True
        self.close()

    # --- páginas --------------------------------------------------------
    def _page_dash(self):
        w = QWidget()
        self.dash_grid = QGridLayout(w)
        self.dash_grid.setSpacing(12)
        self.dash_radar = Card(tr("card.engine"))
        self.radar = Radar()
        self.dash_radar.lay.addWidget(self.radar, 1)
        self.uptime = muted("")
        self.uptime.setAlignment(Qt.AlignCenter)
        self.dash_radar.lay.addWidget(self.uptime)

        stats = QGridLayout()
        stats.setSpacing(12)
        self.stat = {}
        for i, (key, label, color) in enumerate([
                ("runs", "stat.runs", T.CYAN), ("taps", "stat.taps", T.MAGENTA), ("errors", "stat.errors", T.RED),
                ("digs", "stat.digs", T.LIME), ("joins_total", "stat.joins", T.AMBER), ("hunts", "stat.hunts", T.CYAN)]):
            self.stat[key] = StatCard(tr(label), color)
            stats.addWidget(self.stat[key], i // 3, i % 3)
        # rendimento desde o último INICIAR (por hora) e problemas: quedas, conta no celular, relançamentos
        self.session_lbl = QLabel()
        self.session_lbl.setWordWrap(True)
        self.session_lbl.setTextFormat(Qt.RichText)
        self.session_lbl.setStyleSheet(f"border:1px solid {T.LINE};border-radius:6px;padding:8px 10px")
        stats.addWidget(self.session_lbl, 2, 0, 1, 3)
        self.dash_stats = QWidget()
        self.dash_stats.setLayout(stats)

        self.dash_view = Card(tr("card.view"))
        self.preview = QLabel("…")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(180)
        self.preview.setStyleSheet(f"background:#04070e;border:1px solid {T.LINE};color:{T.MUTED}")
        self.dash_view.lay.addWidget(self.preview, 1)
        r = QHBoxLayout()
        self.win_lbl = muted("")
        r.addWidget(self.win_lbl, 1)
        r.addWidget(button("⟳", None, self._capture_preview, "Capturar agora"))
        self.dash_view.lay.addLayout(r)

        self.dash_queue = Card(tr("card.queue"))
        self.queue = QListWidget()
        self.queue.setMinimumHeight(120)
        self.dash_queue.lay.addWidget(self.queue)
        self.dash_log = Card(tr("card.events"))
        self.mini_log = QPlainTextEdit(readOnly=True)
        self.mini_log.setMaximumBlockCount(200)
        self.dash_log.lay.addWidget(self.mini_log)
        self._dash_mode = None
        self._layout_dash(False)
        return scroll(w)

    def _layout_dash(self, narrow):
        if self._dash_mode == narrow:
            return
        self._dash_mode = narrow
        g = self.dash_grid
        for wdg in (self.dash_radar, self.dash_stats, self.dash_view, self.dash_queue, self.dash_log):
            g.removeWidget(wdg)
        for i in range(4):
            g.setColumnStretch(i, 0)
            g.setRowStretch(i, 0)
        if narrow:
            g.addWidget(self.dash_stats, 0, 0, 1, 2)
            g.addWidget(self.dash_radar, 1, 0)
            g.addWidget(self.dash_view, 1, 1)
            g.addWidget(self.dash_queue, 2, 0)
            g.addWidget(self.dash_log, 2, 1)
            g.setColumnStretch(0, 1)
            g.setColumnStretch(1, 1)
            self.radar.setMinimumSize(200, 200)
        else:
            g.addWidget(self.dash_radar, 0, 0, 2, 1)
            g.addWidget(self.dash_stats, 0, 1)
            g.addWidget(self.dash_view, 1, 1)
            g.addWidget(self.dash_queue, 2, 0)
            g.addWidget(self.dash_log, 2, 1)
            g.setColumnStretch(0, 2)
            g.setColumnStretch(1, 3)
            g.setRowStretch(1, 1)
        g.setRowStretch(2, 1)

    # ----- mapa
    def _page_map(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        top = Card("Varredura")
        bar = QHBoxLayout()
        bar.addWidget(button("◎ ESCANEAR AGORA", "go", lambda: self.engine.run_now("map_scanner")))
        bar.addWidget(muted("Varre em volta da sua cidade. Posições em 'telas' a partir dela; IR volta à cidade e "
                            "anda medindo até o alvo. Ajuste linhas/colunas em MÓDULOS › Scanner de Mapa."), 1)
        bar.addWidget(button("Restaurar ocultos", "ghost", lambda: (SCANNER.store.restore_hidden(),
                                                                     self._fill_map(True))))
        bar.addWidget(button("Limpar", "ghost", lambda: (SCANNER.store.clear(), self._fill_map(True))))
        top.lay.addLayout(bar)
        self.map_info = muted("")
        top.lay.addWidget(self.map_info)
        lay.addWidget(top)

        filt = QHBoxLayout()
        self.map_chips = {}
        for key, name, icon in CATEGORIES:
            b = QPushButton(f"{icon} {name}")
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(True)
            b.setCursor(Qt.PointingHandCursor)
            b.toggled.connect(lambda _=None: self._fill_map(True))
            self.map_chips[key] = b
        chips = QWidget()
        cg = QGridLayout(chips)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setSpacing(6)
        for i, b in enumerate(self.map_chips.values()):
            cg.addWidget(b, i // 7, i % 7)
        filt.addWidget(chips, 1)
        lay.addLayout(filt)
        row = QHBoxLayout()
        self.map_search = QLineEdit(placeholderText="filtrar por texto, nível, nome…")
        self.map_search.textChanged.connect(lambda _: self._fill_map(True))
        row.addWidget(self.map_search, 1)
        self.map_pinned = Toggle(False)
        self.map_pinned.toggled.connect(lambda _: self._fill_map(True))
        row.addWidget(muted("só fixados"))
        row.addWidget(self.map_pinned)
        lay.addLayout(row)

        self.map_table = QTableWidget(0, 7)
        self.map_table.setHorizontalHeaderLabels(["★", "TIPO", "POSIÇÃO (da cidade)", "DIST.", "INFO", "VISTO",
                                                  "AÇÕES"])
        hh = self.map_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self.map_table.verticalHeader().setVisible(False)
        self.map_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.map_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.map_table.setSortingEnabled(True)
        lay.addWidget(self.map_table, 1)
        return w

    def _fill_map(self, force=False):
        st = SCANNER.store
        if not force and st.version == self._map_version:
            return
        self._map_version = st.version
        last = dt.datetime.fromtimestamp(st.last_scan).strftime("%d/%m %H:%M") if st.last_scan else "nunca"
        n_icons = sum(self.engine.vision.has(f"map_{k}") for k, _, _ in CATEGORIES)
        self.map_info.setText(f"{len(st.items)} itens · última varredura: {last} · {n_icons}/{len(CATEGORIES)} "
                              f"ícones de mapa capturados (ESTÚDIO › map_…)")
        q = self.map_search.text().lower().strip()
        cats = {k for k, b in self.map_chips.items() if b.isChecked()}
        rows = [(k, v) for k, v in st.items.items()
                if k not in st.hidden and "px" in v and v["cat"] in cats and (not self.map_pinned.isChecked() or k in st.pinned)
                and (not q or q in (v.get("label", "") + CAT_NAMES.get(v["cat"], "")).lower())]
        rows.sort(key=lambda kv: (kv[0] not in st.pinned, kv[1]["cat"], kv[1].get("dist", 0)))
        t = self.map_table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            pin = button("★" if k in st.pinned else "☆", "ghost", lambda _=False, k=k: (st.toggle_pin(k),
                                                                                         self._fill_map(True)))
            t.setCellWidget(i, 0, pin)
            t.setItem(i, 1, QTableWidgetItem(f"{CAT_ICONS.get(v['cat'], '')} {CAT_NAMES.get(v['cat'], v['cat'])}"))
            if "px" not in v:  # resultado de versão antiga do scanner
                continue
            pos = describe_pos(v["px"], v["py"], v.get("w", 1))
            if v.get("gx") is not None:
                pos = f"X:{v['gx']} Y:{v['gy']}" + ("  ★ favorito" if v.get("fav") else "") + f"   ({pos})"
            pit = QTableWidgetItem(pos)
            if v.get("fav"):
                pit.setForeground(QColor(T.LIME))
                pit.setToolTip("Salvo nos favoritos do jogo: o IR vai direto pela lista de favoritos")
            t.setItem(i, 2, pit)
            it = QTableWidgetItem()
            it.setData(Qt.DisplayRole, float(v.get("dist", 0)))
            t.setItem(i, 3, it)
            t.setItem(i, 4, QTableWidgetItem(v.get("label", "")))
            t.setItem(i, 5, QTableWidgetItem(dt.datetime.fromtimestamp(v["seen"]).strftime("%H:%M")))
            acts = QWidget()
            al = QHBoxLayout(acts)
            al.setContentsMargins(2, 0, 2, 0)
            name = CAT_NAMES.get(v["cat"], v["cat"])
            al.addWidget(button("IR", "go", lambda _=False, v=v, name=name: self.engine.run_job(
                f"◎ Indo até {name}", lambda ctx, v=v: SCANNER.go(ctx, v))))
            al.addWidget(button("✕", "ghost", lambda _=False, k=k: (st.hide(k), self._fill_map(True)), "Ocultar"))
            t.setCellWidget(i, 6, acts)
        t.setSortingEnabled(True)

    # ----- agenda
    ACTIONS = [("start", "Iniciar bot"), ("stop", "Parar bot"), ("pause", "Pausar"), ("resume", "Retomar"),
               ("open_game", "Abrir jogo"), ("close_game", "Fechar jogo"), ("run", "Executar módulo")]

    def _page_agenda(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        c = Card("Eventos agendados")
        c.lay.addWidget(muted("Rode qualquer módulo, abra/feche o jogo ou ligue/desligue o bot no dia e horário "
                              "escolhidos. Dias: " + ",".join(DAYS) + ". Cada módulo também tem dias/horário próprios "
                              "em ⚙ AJUSTES."))
        self.ev_table = QTableWidget(0, 6)
        self.ev_table.setHorizontalHeaderLabels(["ATIVO", "HORA", "DIAS", "AÇÃO", "MÓDULO", ""])
        self.ev_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ev_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.ev_table.verticalHeader().setVisible(False)
        c.lay.addWidget(self.ev_table, 1)
        r = QHBoxLayout()
        r.addWidget(button("+ ADICIONAR EVENTO", "go", self._add_event))
        r.addStretch()
        c.lay.addLayout(r)
        lay.addWidget(c, 1)
        self._fill_events()
        return w

    def _fill_events(self):
        evs = self.cfg.data["events"]
        t = self.ev_table
        t.setRowCount(len(evs))
        for i, ev in enumerate(evs):
            tg = Toggle(ev.get("enabled", True))
            tg.toggled.connect(lambda v, ev=ev: (ev.__setitem__("enabled", v), self.save_soon()))
            t.setCellWidget(i, 0, tg)
            te = QTimeEdit(QTime.fromString(ev.get("time", "08:00"), "HH:mm"))
            te.setDisplayFormat("HH:mm")
            te.timeChanged.connect(lambda v, ev=ev: (ev.__setitem__("time", v.toString("HH:mm")), self.save_soon()))
            t.setCellWidget(i, 1, te)
            de = QLineEdit(ev.get("days", ",".join(DAYS)))
            de.textChanged.connect(lambda v, ev=ev: (ev.__setitem__("days", v), self.save_soon()))
            t.setCellWidget(i, 2, de)
            ac = QComboBox()
            for k, n in self.ACTIONS:
                ac.addItem(n, k)
            ac.setCurrentIndex(max(0, [k for k, _ in self.ACTIONS].index(ev.get("action", "start"))))
            ac.currentIndexChanged.connect(lambda _, ev=ev, ac=ac: (ev.__setitem__("action", ac.currentData()),
                                                                   self.save_soon()))
            t.setCellWidget(i, 3, ac)
            mo = QComboBox()
            for task in ALL_TASKS:
                mo.addItem(task.name, task.id)
            idx = mo.findData(ev.get("target", ""))
            mo.setCurrentIndex(max(0, idx))
            mo.currentIndexChanged.connect(lambda _, ev=ev, mo=mo: (ev.__setitem__("target", mo.currentData()),
                                                                   self.save_soon()))
            t.setCellWidget(i, 4, mo)
            t.setCellWidget(i, 5, button("✕", "ghost", lambda _=False, ev=ev: (evs.remove(ev), self.save_soon(),
                                                                               self._fill_events())))

    def _add_event(self):
        self.cfg.data["events"].append({"enabled": True, "time": QTime.currentTime().addSecs(300).toString("HH:mm"),
                                        "days": ",".join(DAYS), "action": "start", "target": ALL_TASKS[0].id})
        self.save_soon()
        self._fill_events()

    def _check_events(self):
        now = dt.datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M")
        day = DAYS[now.weekday()]
        for i, ev in enumerate(self.cfg.data["events"]):
            key = (i, stamp)
            if not ev.get("enabled", True) or ev.get("time") != now.strftime("%H:%M") or key in self._events_done:
                continue
            if day not in [d.strip()[:3] for d in ev.get("days", "").split(",")]:
                continue
            self._events_done.add(key)
            a = ev.get("action")
            self.engine.log(f"◷ Agenda: {dict(self.ACTIONS).get(a, a)}")
            if a == "start":
                self.engine.start()
            elif a == "stop":
                self.engine.stop()
            elif a == "pause":
                self.engine.pause()
            elif a == "resume":
                self.engine.resume()
            elif a == "run":
                self.engine.run_now(ev.get("target"))
            elif a == "open_game":
                exe = self.cfg.data.get("game_exe_path")
                if exe and os.path.exists(exe):
                    subprocess.Popen([exe], cwd=os.path.dirname(exe))
            elif a == "close_game":
                self.engine.stop()
                h = winapi.find_window(self.cfg.data["game_window_title"])
                if h:
                    winapi.user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE

    # ----- clicker
    def _page_clicker(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        c = Card("Alvo")
        f = QFormLayout()
        self.ck_x, self.ck_y = QSpinBox(), QSpinBox()
        for s in (self.ck_x, self.ck_y):
            s.setRange(0, 20000)
        pick = QHBoxLayout()
        pick.addWidget(self.ck_x)
        pick.addWidget(self.ck_y)
        pick.addWidget(button("⌖ PEGAR POSIÇÃO (3s)", "accent", self._pick_point))
        f.addRow(muted("X / Y na tela"), pick)
        self.ck_cd = QDoubleSpinBox(decimals=3, minimum=0.005, maximum=10, singleStep=0.01, value=0.05)
        self.ck_j = QDoubleSpinBox(decimals=3, minimum=0, maximum=1, singleStep=0.005, value=0.005)
        self.ck_stop = QSpinBox(minimum=0, maximum=86400, value=60, suffix=" s")
        f.addRow(muted("Intervalo (s)"), self.ck_cd)
        f.addRow(muted("Variação aleatória (s)"), self.ck_j)
        f.addRow(muted("Parar após (0 = nunca)"), self.ck_stop)
        c.lay.addLayout(f)
        r = QHBoxLayout()
        self.ck_btn = button("▶ INICIAR CLICKER", "go", self._toggle_clicker)
        r.addWidget(self.ck_btn)
        r.addStretch()
        r.addWidget(muted(f"atalho: {self.cfg.data['hotkeys']['clicker'].upper()} (clica onde o mouse estiver)"))
        c.lay.addLayout(r)
        lay.addWidget(c)
        lay.addWidget(muted("Para interromper: atalho, botão, ou leve o mouse ao canto superior esquerdo da tela."))
        lay.addStretch(1)
        return w

    # ----- estúdio
    def _page_studio(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setSpacing(12)
        left = Card("Biblioteca de imagens")
        self.tpl_filter = QLineEdit(placeholderText="filtrar…")
        self.tpl_filter.textChanged.connect(lambda _: self._fill_templates())
        left.lay.addWidget(self.tpl_filter)
        self.tpl_list = QListWidget()
        self.tpl_list.currentItemChanged.connect(self._tpl_selected)
        left.lay.addWidget(self.tpl_list, 1)
        self.tpl_info = muted("")
        left.lay.addWidget(self.tpl_info)
        self.tpl_thumb = QLabel()
        self.tpl_thumb.setFixedHeight(80)
        self.tpl_thumb.setAlignment(Qt.AlignCenter)
        self.tpl_thumb.setStyleSheet(f"background:#04070e;border:1px solid {T.LINE}")
        left.lay.addWidget(self.tpl_thumb)
        left.setMinimumWidth(280)
        left.setMaximumWidth(380)
        lay.addWidget(left, 1)

        left.lay.addWidget(muted("Imagens salvas deste nome (clique para ver; apague a errada):"))
        self.tpl_variants = QListWidget()
        self.tpl_variants.setViewMode(QListWidget.IconMode)
        self.tpl_variants.setIconSize(QSize(64, 64))
        self.tpl_variants.setFixedHeight(96)
        self.tpl_variants.setMovement(QListWidget.Static)
        left.lay.addWidget(self.tpl_variants)
        vb = QHBoxLayout()
        vb.addWidget(button("🗑 Apagar esta", None, self._studio_delete_variant, "Apaga só a imagem selecionada acima"))
        vb.addWidget(button("🗑 Todas", None, self._studio_delete, "Apaga todas as imagens deste nome"))
        vb.addWidget(button("↺ Reaprender", None, self._studio_relearn,
                            "Apaga e deixa o bot aprender sozinho de novo pelo texto do botão"))
        left.lay.addLayout(vb)
        vb2 = QHBoxLayout()
        vb2.addWidget(button("✦ Esquecer aprendidas", "ghost", self._studio_forget_learned,
                             "Apaga todas as imagens que o bot aprendeu sozinho (✦); ele reaprende quando precisar"))
        vb2.addWidget(button("📁 Pasta", "ghost", lambda: self._open_dir(TEMPLATE_DIR), "Abre data\\templates"))
        vb2.addWidget(button("◉ IA", "ghost", self._studio_open_vision,
                             "Abre este nome no Estúdio visual (IA): foto, confiança e o que a IA vê agora"))
        left.lay.addLayout(vb2)
        left.lay.addWidget(button("✚ NOVO NOME…", None, self._studio_new_name,
                                  "Cria um nome seu (ex.: para usar em 'toque <nome>' nas Rotinas)"))

        right = Card("Recorte")
        # 1 · imagem de onde recortar
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("1 · IMAGEM"))
        r1.addWidget(button("⟳ CAPTURAR JOGO", "accent", self._studio_capture, "Tira um print do jogo agora"))
        r1.addWidget(button("📷 SALVAR PRINT", None, self._studio_save_print,
                            "Guarda o print atual em data\\prints para recortar depois"))
        r1.addWidget(button("📂 ABRIR IMAGEM…", None, self._studio_open_image,
                            "Abre um print salvo (PNG/JPG) para recortar"))
        r1.addWidget(button("📁 prints", "ghost", lambda: self._open_dir(PRINT_DIR), "Abre data\\prints"))
        r1.addStretch()
        right.lay.addLayout(r1)
        self.canvas = CaptureCanvas()
        self.canvas.selected.connect(self._studio_sel_changed)
        right.lay.addWidget(self.canvas, 1)
        # 2 · recorte: arrastar na imagem ou ajustar os números
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("2 · RECORTE"))
        self.sel_spins = []
        for lab in ("X", "Y", "L", "A"):
            sp = QSpinBox(minimum=0, maximum=9999)
            sp.setPrefix(lab + " ")
            sp.valueChanged.connect(self._studio_spins_changed)
            self.sel_spins.append(sp)
            r2.addWidget(sp)
        self.sel_preview = QLabel("—")
        self.sel_preview.setFixedSize(150, 64)
        self.sel_preview.setAlignment(Qt.AlignCenter)
        self.sel_preview.setStyleSheet(f"background:#04070e;border:1px solid {T.LINE}")
        r2.addWidget(self.sel_preview)
        r2.addStretch()
        right.lay.addLayout(r2)
        # 3 · salvar no nome escolhido na lista
        r3 = QHBoxLayout()
        self.save_target = QLabel("3 · SALVAR EM: (escolha um nome na lista)")
        r3.addWidget(self.save_target, 1)
        r3.addWidget(button("✔ SALVAR", "go", lambda: self._studio_save(False), "Substitui a imagem principal"))
        r3.addWidget(button("+ VARIANTE", None, lambda: self._studio_save(True),
                             "Guarda mais uma versão (outro idioma, tema, tamanho) sem apagar as outras"))
        r3.addWidget(button("⬆ IMPORTAR IMAGENS…", None, self._studio_import,
                            "Adiciona imagens já recortadas (PNG/JPG) ao nome escolhido ou como nomes novos"))
        right.lay.addLayout(r3)
        # 4 · testar
        bar = QHBoxLayout()
        bar.addWidget(QLabel("4 · TESTAR"))
        bar.addWidget(button("◎ TESTAR NA IMAGEM", None, self._studio_test, "Procura o nome escolhido na imagem acima"))
        self.th = QDoubleSpinBox(decimals=2, minimum=0.5, maximum=0.99, singleStep=0.01, value=0.85)
        bar.addWidget(muted("limiar"))
        bar.addWidget(self.th)
        bar.addStretch()
        right.lay.addLayout(bar)
        self.studio_status = QLabel("")
        self.studio_status.setStyleSheet(f"color:{T.LIME}")
        right.lay.addWidget(self.studio_status)
        f8 = QHBoxLayout()
        self.f8_size = QSpinBox(minimum=16, maximum=400, value=60, suffix=" px")
        f8.addWidget(muted(f"Captura rápida: escolha o nome na lista, ponha o mouse sobre o elemento no jogo e aperte "
                           f"{self.cfg.data['hotkeys'].get('capture', 'f8').upper()}. Tamanho do quadrado:"), 1)
        f8.addWidget(self.f8_size)
        right.lay.addLayout(f8)
        right.lay.addWidget(muted("● imagem sua   ◉ a IA já reconhece sozinha (miniatura = como é no jogo)   "
                                  "◐ acha pelo texto (OCR)   ◇ só exemplo (capture a sua)   ○ falta capturar"))
        lay.addWidget(right, 3)
        self._fill_templates()
        return w

    # ----- sistema
    def _page_system(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        d = self.cfg.data

        def tg(store, key, label, form, cb=None):
            t = Toggle(bool(store.get(key)))
            t.toggled.connect(lambda v: (store.__setitem__(key, v), self.save_soon(), cb and cb(v)))
            form.addRow(muted(label), t)
            return t

        g = Card("Plataforma")
        f = QFormLayout()
        plat = QComboBox()
        plat.addItem("PC — jogo oficial para Windows", "pc")
        plat.addItem("Emulador Android (ADB) — roda em segundo plano", "adb")
        plat.setCurrentIndex(0 if d["backend"] == "pc" else 1)
        plat.currentIndexChanged.connect(lambda _: (self._set("backend", plat.currentData()),
                                                    self.engine.reload_backend()))
        f.addRow(muted("Onde o jogo roda"), plat)
        self.f_title = QComboBox(editable=True)
        self.f_title.addItem(d["game_window_title"])
        self.f_title.lineEdit().textChanged.connect(lambda v: self._set("game_window_title", v))
        trow = QHBoxLayout()
        trow.addWidget(self.f_title, 1)
        trow.addWidget(button("listar janelas", "ghost", self._list_windows))
        f.addRow(muted("Janela do jogo (PC)"), trow)
        exe = QHBoxLayout()
        self.f_exe = QLineEdit(d["game_exe_path"])
        self.f_exe.textChanged.connect(lambda v: self._set("game_exe_path", v))
        exe.addWidget(self.f_exe)
        exe.addWidget(button("…", None, self._pick_exe))
        f.addRow(muted("Executável (reabrir após crash)"), exe)
        res = QComboBox()
        for val, txt in (("auto", "Automático — tamanho padrão 16:9 que cabe na tela (recomendado)"),
                         ("", "Não mexer na janela"), ("1920x1080", "1920x1080"), ("1600x900", "1600x900"),
                         ("1280x720", "1280x720")):
            res.addItem(txt, val)
        res.setCurrentIndex(max(0, res.findData(d.get("resize_to", "auto"))))
        res.currentIndexChanged.connect(lambda _: self._set("resize_to", res.currentData()))
        f.addRow(muted("Tamanho da janela do jogo (ajusta ao INICIAR)"), res)
        adb = QHBoxLayout()
        self.f_adb = QLineEdit(d["adb_path"] or (find_adb() or ""))
        self.f_adb.setPlaceholderText("detectado automaticamente (MuMu, LDPlayer, BlueStacks, Nox, MEmu)")
        self.f_adb.textChanged.connect(lambda v: self._set("adb_path", v))
        adb.addWidget(self.f_adb)
        adb.addWidget(button("…", None, lambda: self._pick_file(self.f_adb, "adb (*.exe)")))
        f.addRow(muted("adb.exe (emulador)"), adb)
        ser = QHBoxLayout()
        self.f_serial = QComboBox(editable=True)
        self.f_serial.addItem(d["adb_serial"])
        self.f_serial.lineEdit().textChanged.connect(lambda v: self._set("adb_serial", v))
        ser.addWidget(self.f_serial, 1)
        ser.addWidget(button("detectar", "ghost", self._adb_detect))
        ser.addWidget(button("conectar…", "ghost", self._adb_connect))
        f.addRow(muted("Emulador (serial)"), ser)
        rt = QLineEdit(d["reset_time"])
        rt.setInputMask("99:99")
        rt.textChanged.connect(lambda v: self._set("reset_time", v))
        f.addRow(muted("Horário de reset diário do servidor"), rt)
        ld = QDoubleSpinBox(minimum=0.2, maximum=60, value=float(d["loop_delay"]), suffix=" s")
        ld.valueChanged.connect(lambda v: self._set("loop_delay", v))
        f.addRow(muted("Pausa entre ciclos"), ld)
        g.lay.addLayout(f)
        lay.addWidget(g)

        v = Card("Visão: OCR e imagens")
        f = QFormLayout()
        tg(d, "ocr_enabled", "Ler textos da tela (OCR do Windows)", f)
        lang = QComboBox()
        lang.addItem("idioma do Windows", "")
        for l in self.engine.ocr.languages():
            lang.addItem(l, l)
        lang.setCurrentIndex(max(0, lang.findData(d.get("ocr_language", ""))))
        lang.currentIndexChanged.connect(lambda _: (self._set("ocr_language", lang.currentData()),
                                                    self.engine.ocr.set_language(lang.currentData() or None)))
        f.addRow(muted("Idioma do OCR"), lang)
        f.addRow(muted(""), muted("Para ler o jogo em outro idioma (ex.: inglês), instale o pacote de idioma no Windows: "
                                  "Configurações › Hora e idioma › Idioma › Adicionar idioma."))
        tg(d, "auto_learn", "Aprender botões sozinho (salva imagem ao achar pelo texto)", f)
        th = QDoubleSpinBox(decimals=2, minimum=0.6, maximum=0.98, singleStep=0.01, value=float(d["match_threshold"]))
        th.valueChanged.connect(lambda x: self._set("match_threshold", x))
        f.addRow(muted("Limiar padrão de reconhecimento"), th)
        y = self.engine.yolo
        tg(d, "ai_enabled", "IA de reconhecimento (acha botões sem capturar imagens)", f)
        am = QComboBox()
        am.addItem("rápido (~0,1 s por tela)", "rapido")
        am.addItem("preciso (~0,4 s por tela)", "preciso")
        am.setCurrentIndex(max(0, am.findData(d.get("ai_model", "rapido"))))
        am.currentIndexChanged.connect(lambda _: self._set("ai_model", am.currentData()))
        f.addRow(muted("Modelo da IA"), am)
        at = QDoubleSpinBox(decimals=2, minimum=0.2, maximum=0.95, singleStep=0.05, value=float(d.get("ai_threshold", 0.5)))
        at.valueChanged.connect(lambda x: self._set("ai_threshold", x))
        f.addRow(muted("Confiança mínima da IA"), at)
        f.addRow(muted(""), muted("IA pronta: modelo encontrado em data/modelos." if y.available() else
                                  "IA desligada: coloque lw_rapido.onnx em data/modelos ao lado do TOSCO.exe."))
        tg(d, "guard_clicks", "Proteção da conta: nunca tocar perto de Comprar, preço ou Terminar agora", f)
        rw = QSpinBox(minimum=1, maximum=240, value=int(d.get("relog_wait_min", 10)))
        rw.valueChanged.connect(lambda x: self._set("relog_wait_min", x))
        f.addRow(muted("Conta aberta no celular: reconectar após (min)"), rw)
        tg(d, "pause_on_user", "Pausar quando eu mexer no mouse/teclado", f)
        ur = QSpinBox(minimum=3, maximum=600, value=int(d.get("user_resume_s", 20)))
        ur.valueChanged.connect(lambda x: self._set("user_resume_s", x))
        f.addRow(muted("Voltar depois de (s) sem mexer"), ur)
        v.lay.addLayout(f)
        lay.addWidget(v)

        hcard = Card("Comportamento humano")
        f = QFormLayout()
        h = d["human"]
        tg(h, "mouse_curve", "Mouse em curva natural até o alvo", f)
        df = QDoubleSpinBox(decimals=2, minimum=0.5, maximum=3, singleStep=0.1, value=float(h["delay_factor"]))
        df.valueChanged.connect(lambda x: (h.__setitem__("delay_factor", x), self.save_soon()))
        f.addRow(muted("Velocidade (1 = normal, 2 = mais lento)"), df)
        sp = QDoubleSpinBox(decimals=2, minimum=0, maximum=1, singleStep=0.05, value=float(h["tap_spread"]))
        sp.valueChanged.connect(lambda x: (h.__setitem__("tap_spread", x), self.save_soon()))
        f.addRow(muted("Dispersão dos toques"), sp)
        tg(h, "breaks_enabled", "Fazer pausas de descanso", f)
        be = QSpinBox(minimum=10, maximum=600, value=int(h["break_every_min"]), suffix=" min")
        be.valueChanged.connect(lambda x: (h.__setitem__("break_every_min", x), self.save_soon()))
        f.addRow(muted("…a cada ~"), be)
        bm = QSpinBox(minimum=1, maximum=120, value=int(h["break_minutes"]), suffix=" min")
        bm.valueChanged.connect(lambda x: (h.__setitem__("break_minutes", x), self.save_soon()))
        f.addRow(muted("…durando ~"), bm)
        hcard.lay.addLayout(f)
        lay.addWidget(hcard)


        ui = Card("Interface e inicialização")
        f = QFormLayout()
        u = d["ui"]
        lg = QComboBox()
        for k, n in LANGS.items():
            lg.addItem(n, k)
        lg.setCurrentIndex(max(0, lg.findData(u.get("language", "pt"))))
        lg.currentIndexChanged.connect(lambda _: (u.__setitem__("language", lg.currentData()), self.save_soon(),
                                                  self._need_restart()))
        f.addRow(muted("Idioma da interface"), lg)
        sc = QComboBox()
        for p in (80, 90, 100, 110, 125, 150):
            sc.addItem(f"{p}%", p)
        sc.setCurrentIndex(max(0, sc.findData(int(u.get("scale", 100)))))
        sc.currentIndexChanged.connect(lambda _: (u.__setitem__("scale", sc.currentData()), self.save_soon(),
                                                  self._need_restart()))
        f.addRow(muted("Tamanho da interface"), sc)
        tg(u, "start_with_windows", "Iniciar com o Windows", f, self._set_startup)
        tg(u, "start_minimized", "Iniciar minimizado na bandeja", f)
        tg(u, "autostart_engine", "Ligar o motor ao abrir", f)
        tg(d, "logging_enabled", "Salvar registro em arquivo", f)
        f.addRow(muted(""), button("Abrir pasta de dados", "ghost", lambda: os.startfile(DATA_DIR)))
        ui.lay.addLayout(f)
        lay.addWidget(ui)

        hk = Card("Atalhos globais")
        f = QFormLayout()
        for k, label in [("start", "Iniciar"), ("stop", "Parar"), ("pause", "Pausar"), ("resume", "Retomar"),
                         ("clicker", "Clicker"), ("capture", "Captura rápida (Estúdio)")]:
            e = QLineEdit(d["hotkeys"].get(k, ""))
            e.editingFinished.connect(lambda k=k, e=e: (d["hotkeys"].__setitem__(k, e.text().strip().lower()),
                                                        self.save_soon(), self._register_hotkeys()))
            f.addRow(muted(label), e)
        hk.lay.addLayout(f)
        lay.addWidget(hk)

        dg = Card("Diagnóstico (quando der problema)")
        dg.lay.addWidget(muted("Junta num .zip o registro de hoje e de ontem, os contadores, a configuração SEM o "
                               "token do Telegram e os últimos prints do jogo. É só mandar o arquivo para quem "
                               "for ajudar."))
        r = QHBoxLayout()
        r.addWidget(button("📦 Gerar pacote de diagnóstico", "accent", self._make_diag))
        r.addWidget(button("📁 Pasta", "ghost", lambda: os.startfile(self._diag_dir())))
        r.addStretch(1)
        dg.lay.addLayout(r)
        lay.addWidget(dg)
        lay.addStretch(1)
        return scroll(w)

    def _diag_dir(self):
        from ..core import diag
        os.makedirs(diag.DIAG_DIR, exist_ok=True)
        return diag.DIAG_DIR

    def _make_diag(self):
        from ..core import diag
        n = len(self.engine.recent_frames)
        prints = False
        if n:
            ans = QMessageBox.question(
                self, APP, f"Incluir os últimos {n} prints do jogo?\n\nAjudam muito a achar o problema, mas mostram "
                           "a sua tela (nome, aliança, recursos). Mande só para quem você confia.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel:
                return
            prints = ans == QMessageBox.Yes
        try:
            path = diag.make(self.engine, include_prints=prints)
        except Exception as ex:
            QMessageBox.warning(self, APP, f"Não consegui gerar o pacote: {ex}")
            return
        self.engine.log(f"📦 Pacote de diagnóstico: {os.path.basename(path)}" + (" (com prints)" if prints else ""))
        subprocess.Popen(["explorer", "/select,", path])

    def _page_phone(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        d = self.cfg.data

        def tg(store, key, label, form):
            t = Toggle(bool(store.get(key)))
            t.toggled.connect(lambda v: (store.__setitem__(key, v), self.save_soon()))
            form.addRow(muted(label), t)
            return t

        tgc = Card("Telegram — controle pelo celular")
        f = QFormLayout()
        t = d["telegram"]
        f.addRow(muted(""), muted("1) No Telegram, fale com @BotFather → /newbot → copie o token.  "
                                  "2) Mande qualquer mensagem para o seu bot.  3) Clique em 'descobrir meu chat ID'."))
        tg(t, "enabled", "Ativar", f)
        tok = QLineEdit(t["token"], echoMode=QLineEdit.Password)
        tok.textChanged.connect(lambda x: (t.__setitem__("token", x.strip()), self.save_soon()))
        f.addRow(muted("Token do bot"), tok)
        cid_row = QHBoxLayout()
        self.f_chat = QLineEdit(t["chat_id"])
        self.f_chat.textChanged.connect(lambda x: (t.__setitem__("chat_id", x.strip()), self.save_soon()))
        cid_row.addWidget(self.f_chat, 1)
        cid_row.addWidget(button("descobrir meu chat ID", "ghost", self._tg_find_chat))
        f.addRow(muted("Chat ID"), cid_row)
        tg(t, "commands", "Aceitar comandos (/status, /print, /iniciar…)", f)
        tg(t, "notify_digs", "Avisar escavações", f)
        tg(t, "notify_errors", "Avisar erros e quedas", f)
        sm = QSpinBox(minimum=0, maximum=1440, value=int(t["status_minutes"]), suffix=" min")
        sm.valueChanged.connect(lambda x: (t.__setitem__("status_minutes", x), self.save_soon()))
        f.addRow(muted("Status periódico (0 = desligado)"), sm)
        f.addRow(muted(""), button("Enviar teste + print", None, self._tg_test))
        tgc.lay.addLayout(f)
        lay.addWidget(tgc)
        cmds = Card("Comandos no Telegram")
        cmds.lay.addWidget(muted("/status · /print (foto do jogo) · /iniciar · /parar · /pausar · /retomar · /log · "
                                 "/modulos · /ligar <id> · /desligar <id> · /agora <id> · /clicker · /ajuda"))
        lay.addWidget(cmds)
        lay.addStretch(1)
        return scroll(w)

    def _page_log(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.full_log = QPlainTextEdit(readOnly=True)
        self.full_log.setMaximumBlockCount(5000)
        lay.addWidget(self.full_log)
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(button("Relatórios", "ghost", lambda: os.startfile(REPORT_DIR)))
        r.addWidget(button("Limpar", None, self.full_log.clear))
        lay.addLayout(r)
        return w

    # --- ações ----------------------------------------------------------
    def save_soon(self):
        self._save_timer.start()

    def _set(self, key, value):
        self.cfg.data[key] = value
        self.save_soon()

    def _need_restart(self):
        self.engine.log(f"Reabra o {APP} para aplicar idioma/tamanho da interface")

    def _pause_resume(self):
        (self.engine.resume if self.engine.paused else self.engine.pause)()

    def _switch_profile(self, name):
        if not name or name == self.cfg.active:
            return
        if self.engine.running:
            self.engine.stop()
        self.cfg.switch(name)
        self.cfg.save()
        QMessageBox.information(self, APP, f"Perfil '{name}' ativo. Reabra o {APP} para recarregar os formulários.")

    def _new_profile(self):
        name, ok = QInputDialog.getText(self, "Novo perfil", "Nome (ex.: conta 2):")
        if ok and name.strip():
            self.cfg.profiles.setdefault(name.strip(), {})
            self.profile.addItem(name.strip())
            self.profile.setCurrentText(name.strip())

    def _capture_preview(self):
        if self.engine.capture() is None:
            self.win_lbl.setText(self.engine.backend.describe())

    def _pick_point(self):
        self.engine.log("⌖ Posicione o mouse sobre o alvo…")
        QTimer.singleShot(3000, self._grab_cursor)

    def _grab_cursor(self):
        pt = winapi.wintypes.POINT()
        winapi.user32.GetCursorPos(winapi.ctypes.byref(pt))
        self.ck_x.setValue(pt.x)
        self.ck_y.setValue(pt.y)
        self.engine.log(f"⌖ Alvo definido em ({pt.x}, {pt.y})")

    def _toggle_clicker(self, at_cursor=False):
        if self.clicker.active:
            self.clicker.stop()
            return
        if at_cursor:
            pt = winapi.wintypes.POINT()
            winapi.user32.GetCursorPos(winapi.ctypes.byref(pt))
            self.ck_x.setValue(pt.x)
            self.ck_y.setValue(pt.y)
        self.clicker.start(self.ck_x.value(), self.ck_y.value(), self.ck_cd.value(), self.ck_j.value(),
                           self.ck_stop.value() or None)

    # ----- estúdio
    def _fill_templates(self):
        cur = self.tpl_list.currentItem().data(Qt.UserRole) if self.tpl_list.currentItem() else None
        q = self.tpl_filter.text().lower().strip()
        self.tpl_list.clear()
        self.tpl_list.setIconSize(QSize(28, 28))
        for name, desc, owner, auto in self._studio_names():
            cls = catalog.target_class(name)
            pt = catalog.label(cls) if cls else ""
            if q and q not in (name + desc + owner + pt).lower():
                continue
            n = self.engine.vision.count(name)
            ex = catalog.example(name)
            # ● imagem sua · ◉ a IA reconhece sozinha · ◐ acha pelo texto · ◇ só exemplo · ○ falta capturar
            mark, col = (("●", T.LIME) if n else ("◉", T.CYAN) if cls and self.engine.yolo.available()
                         else ("◐", T.CYAN) if auto else ("◇", T.AMBER) if ex else ("○", T.MUTED))
            it = QListWidgetItem(f"{mark}  {pt or desc or name}" + (f"  ×{n}" if n > 1 else "")
                                 + (f"\n      {name}" if (pt or desc) else ""))
            own = self.engine.vision.files(name)
            icon = own[0] if own else (catalog.thumb(cls) if cls else None) or ex
            if icon:
                it.setIcon(QIcon(icon))
            it.setData(Qt.UserRole, name)
            it.setToolTip(f"{owner}: {desc}" + (f"\nIA: {pt}" if pt else ""))
            it.setForeground(QColor(col))
            self.tpl_list.addItem(it)
            if name == cur:
                self.tpl_list.setCurrentItem(it)

    def _studio_names(self):
        """Nomes do TOSCO + nomes criados por você (imagens na pasta que não são de nenhuma tarefa)."""
        out = list(all_templates())
        known = {n for n, *_ in out}
        mine = set(self.engine.vision.available()) | getattr(self, "_extra_names", set())
        out += [(n, "Nome criado por você", "Meus", False) for n in sorted(mine) if n not in known]
        return out

    def _studio_msg(self, text, ok=True):
        self.studio_status.setStyleSheet(f"color:{T.LIME if ok else T.AMBER}")
        self.studio_status.setText(text)
        self.engine.log(text, "info" if ok else "warn")

    def _open_dir(self, path):
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _tpl_selected(self, it, _=None):
        if not it:
            return
        name = it.data(Qt.UserRole)
        desc, owner, auto = next(((d, o, a) for n, d, o, a in self._studio_names() if n == name),
                                 ("", "Meus", False))
        cls = catalog.target_class(name)
        ex = catalog.example(name)
        ia = (f"\n◉ A IA já reconhece isto sozinha: {catalog.label(cls)} — capturar é opcional" if cls else "")
        exm = ("\n◇ A foto abaixo é só EXEMPLO (de outro bot) para você saber o que é — o bot não usa. "
               "Capture a sua do seu jogo." if ex and not cls and not self.engine.vision.has(name) else "")
        self.tpl_info.setText(f"{name}\n{desc} · {owner}" + ("\n(acha pelo texto; capturar é opcional)" if auto else "")
                              + ia + exm)
        self.save_target.setText(f"3 · SALVAR EM:  {name}")
        img = self.engine.vision.load(name)
        thumb = catalog.thumb(cls) if cls else None
        if img is not None:
            self.tpl_thumb.setPixmap(bgr_to_pixmap(img).scaled(330, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        elif thumb or ex:  # sem imagem sua: mostra como é (foto da IA ou exemplo) para você saber do que se trata
            self.tpl_thumb.setPixmap(QPixmap(thumb or ex).scaled(330, 76, Qt.KeepAspectRatio,
                                                                 Qt.SmoothTransformation))
        else:
            self.tpl_thumb.clear()
            self.tpl_thumb.setText("sem imagem")
        self.tpl_variants.clear()
        for p in self.engine.vision.files(name):
            im = self.engine.vision._load_file(p)
            if im is None:
                continue
            learned = self.engine.vision.is_learned(p)
            tag = os.path.basename(p)[:-4].replace(name, "") or "principal"
            vi = QListWidgetItem(QIcon(bgr_to_pixmap(im)), ("✦ aprendida " if learned else "") + tag)
            vi.setData(Qt.UserRole, p)
            vi.setToolTip(f"{os.path.basename(p)} · {im.shape[1]}×{im.shape[0]} px · "
                          f"tela de origem {self.engine.vision.file_width(p)} px"
                          + ("\n✦ o bot aprendeu sozinho pelo texto — apague se estiver errada" if learned else ""))
            self.tpl_variants.addItem(vi)
        if self.tpl_variants.count():
            self.tpl_variants.setCurrentRow(0)  # já selecionada: "apagar" funciona direto

    def _studio_capture(self):
        img = self.engine.capture()
        if img is None:
            QMessageBox.warning(self, APP, self.engine.backend.describe())
            return
        self.canvas.set_frame(img)
        self._studio_msg(f"Print do jogo capturado ({img.shape[1]}×{img.shape[0]}). Arraste sobre o elemento.")

    def _studio_save_print(self):
        if self.canvas.src is None:
            self._studio_capture()
        if self.canvas.src is None:
            return
        fname = os.path.join(PRINT_DIR, time.strftime("print_%Y-%m-%d_%H-%M-%S.png"))
        cv2.imencode(".png", self.canvas.src)[1].tofile(fname)
        self._studio_msg(f"📷 Print salvo: data\\prints\\{os.path.basename(fname)}")

    def _studio_open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir imagem para recortar", PRINT_DIR,
                                              "Imagens (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            self._studio_msg(f"Não consegui abrir {os.path.basename(path)}", False)
            return
        self.canvas.set_frame(img)
        self._studio_msg(f"Imagem aberta: {os.path.basename(path)} ({img.shape[1]}×{img.shape[0]}). Arraste para recortar.")

    def _studio_sel_changed(self, sel):
        for sp, v in zip(self.sel_spins, (sel.x(), sel.y(), sel.width(), sel.height())):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        self._studio_preview()

    def _studio_spins_changed(self, _=None):
        self.canvas.set_selection(*(sp.value() for sp in self.sel_spins))
        self._studio_preview()

    def _studio_preview(self):
        crop = self.canvas.crop()
        if crop is None:
            self.sel_preview.setText("—")
            return
        self.sel_preview.setPixmap(bgr_to_pixmap(crop).scaled(148, 62, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _current_tpl(self):
        it = self.tpl_list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _select_tpl(self, name):
        self.tpl_filter.clear()
        self._fill_templates()
        for i in range(self.tpl_list.count()):
            if self.tpl_list.item(i).data(Qt.UserRole) == name:
                self.tpl_list.setCurrentRow(i)
                break

    def _studio_save(self, variant):
        name, crop = self._current_tpl(), self.canvas.crop()
        if not name:
            self._studio_msg("Escolha na lista (à esquerda) o nome onde salvar — ou crie um com ✚ NOVO NOME.", False)
            return
        if crop is None:
            self._studio_msg("Arraste sobre a imagem para recortar (mínimo 6×6 px).", False)
            return
        v = self.engine.vision.next_variant(name) if variant else None
        if not variant:
            main = self.engine.vision.path(name)
            if os.path.exists(main):
                self.engine.vision.delete_file(main)
        fname = self.engine.vision.save(name, crop, self.canvas.src.shape[1], v, source_height=self.canvas.src.shape[0])
        self._fill_templates()
        self._tpl_selected(self.tpl_list.currentItem())
        self._studio_msg(f"✔ Salvo: data\\templates\\{fname}.png ({crop.shape[1]}×{crop.shape[0]} px)")

    def _studio_new_name(self):
        name, ok = QInputDialog.getText(self, APP, "Nome novo (letras, números e _; ex.: meu_botao):")
        name = "".join(c for c in (name or "").strip().lower().replace(" ", "_") if c.isalnum() or c == "_")
        if not ok or not name:
            return
        crop = self.canvas.crop()
        if crop is not None:
            self.engine.vision.save(name, crop, self.canvas.src.shape[1], source_height=self.canvas.src.shape[0])
            self._studio_msg(f"✔ Nome '{name}' criado com o recorte atual")
        else:
            self._studio_msg(f"Nome '{name}' criado — recorte algo e clique em SALVAR (ou importe imagens)")
        self._extra_names = getattr(self, "_extra_names", set()) | {name}
        self._select_tpl(name)

    def _studio_import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Importar imagens já recortadas", ROOT,
                                                "Imagens (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not paths:
            return
        name = self._current_tpl()
        box = QMessageBox(self)
        box.setWindowTitle(APP)
        box.setText(f"{len(paths)} imagem(ns). Como adicionar?")
        b_var = box.addButton(f"Como imagens de '{name}'", QMessageBox.AcceptRole) if name else None
        b_new = box.addButton("Cada uma como nome novo (nome do arquivo)", QMessageBox.AcceptRole)
        b_cut = box.addButton("Abrir para recortar", QMessageBox.ActionRole) if len(paths) == 1 else None
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked.text() == "Cancelar":
            return
        if b_cut is not None and clicked is b_cut:
            img = cv2.imdecode(np.fromfile(paths[0], dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                self.canvas.set_frame(img)
                self._studio_msg(f"Imagem aberta: {os.path.basename(paths[0])}. Arraste para recortar.")
            return
        # largura da tela de onde as imagens vieram: o tamanho atual do jogo é o melhor palpite
        src_w = self.engine.last_frame.shape[1] if self.engine.last_frame is not None else 1920
        src_w, ok = QInputDialog.getInt(self, APP, "Largura (px) da tela do jogo de onde estes recortes saíram\n"
                                        "(serve para reescalar; na dúvida, deixe o valor sugerido):",
                                        src_w, 320, 7680)
        if not ok:
            return
        done, last = 0, name
        for p in paths:
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None or min(img.shape[:2]) < 6:
                continue
            if b_var is not None and clicked is b_var:
                self.engine.vision.save(name, img, src_w, self.engine.vision.next_variant(name))
            else:
                base = os.path.splitext(os.path.basename(p))[0].lower().replace(" ", "_").replace("@", "_")
                last = "".join(c for c in base if c.isalnum() or c == "_") or "imagem"
                self.engine.vision.save(last, img, src_w, self.engine.vision.next_variant(last))
            done += 1
        self._studio_msg(f"⬆ {done} imagem(ns) importada(s) para data\\templates")
        self._select_tpl(last) if last else self._fill_templates()

    def _studio_relearn(self):
        """Apaga as imagens do nome e deixa o bot aprender de novo sozinho (pelo texto, na próxima vez que vir)."""
        name = self._current_tpl()
        if not name or not self.engine.vision.has(name):
            self._studio_msg("Este nome não tem imagem para apagar.", False)
            return
        if name not in TEXT_TARGETS:
            self._studio_msg(f"'{name}' não tem texto para o bot reaprender sozinho — apague e capture de novo.", False)
            return
        if QMessageBox.question(self, APP, f"Apagar as imagens de '{name}' e deixar o bot aprender de novo "
                                           "sozinho (pelo texto) na próxima vez que vir o botão?") != QMessageBox.Yes:
            return
        self.engine.vision.delete(name)
        self.refresh_studio()
        self._studio_msg(f"↺ '{name}' apagada — o bot vai reaprender sozinho quando achar o botão pelo texto")

    def _studio_forget_learned(self):
        files = self.engine.vision.learned_files()
        if not files:
            self._studio_msg("Nenhuma imagem aprendida sozinha (✦) para apagar.", False)
            return
        if QMessageBox.question(self, APP, f"Apagar as {len(files)} imagem(ns) que o bot aprendeu sozinho (✦)? "
                                           "Ele reaprende pelo texto quando precisar.") != QMessageBox.Yes:
            return
        for p in files:
            self.engine.vision.delete_file(p)
        self.refresh_studio()
        self._studio_msg(f"↺ {len(files)} imagem(ns) aprendida(s) apagada(s) — serão reaprendidas sozinhas")

    def _studio_delete_variant(self):
        it = self.tpl_variants.currentItem() or (self.tpl_variants.item(0) if self.tpl_variants.count() == 1 else None)
        if not it:
            self._studio_msg("Este nome não tem imagem salva para apagar." if not self.tpl_variants.count()
                             else "Clique numa das imagens salvas (miniaturas) para apagar só ela.", False)
            return
        p = it.data(Qt.UserRole)
        if QMessageBox.question(self, APP, f"Apagar {os.path.basename(p)}?") == QMessageBox.Yes:
            self.engine.vision.delete_file(p)
            self._fill_templates()
            self._tpl_selected(self.tpl_list.currentItem())
            self._studio_msg(f"🗑 {os.path.basename(p)} apagada")

    def _studio_delete(self):
        name = self._current_tpl()
        if name and self.engine.vision.has(name) and QMessageBox.question(
                self, APP, f"Apagar as imagens de '{name}'?") == QMessageBox.Yes:
            self.engine.vision.delete(name)
            self._fill_templates()
            self._tpl_selected(self.tpl_list.currentItem())
            self._studio_msg(f"🗑 Imagens de '{name}' apagadas")

    def _studio_test(self):
        name = self._current_tpl()
        if self.canvas.src is None or not name:
            self._studio_msg("Precisa de uma imagem (CAPTURAR JOGO/ABRIR IMAGEM) e um nome escolhido na lista.", False)
            return
        hits = self.engine.vision.find_all(self.canvas.src, name, self.th.value())
        how = "imagem"
        if not hits and self.engine.ocr.enabled:
            from ..core.targets import TEXT_TARGETS
            if name in TEXT_TARGETS:
                h = self.engine.ocr.find(self.canvas.src, TEXT_TARGETS[name])
                if h:
                    hits = [(h[0], h[1], 1.0, h[3][2], h[3][3])]
                    how = f"texto '{h[2]}'"
        self.canvas.hits = hits
        self.canvas._a = self.canvas._b = None
        self.canvas.update()
        self._studio_msg(f"◎ '{name}': {len(hits)} ocorrência(s) por {how}" +
                         ("" if hits else " — tente baixar o limiar ou salvar uma variante"), bool(hits))

    def _quick_capture(self):
        """F8: recorta um quadrado em volta do mouse direto do jogo e salva no template selecionado."""
        name = self._current_tpl()
        if not name:
            self.engine.log("Captura rápida: escolha um nome no ESTÚDIO antes", "warn")
            return
        if self.engine.backend.name != "pc":
            self.engine.log("Captura rápida funciona no PC; no emulador use CAPTURAR JOGO", "warn")
            return
        r = self.engine.backend.rect()
        img = self.engine.capture()
        if not r or img is None:
            return
        pt = winapi.wintypes.POINT()
        winapi.user32.GetCursorPos(winapi.ctypes.byref(pt))
        cx, cy, half = pt.x - r[0], pt.y - r[1], self.f8_size.value() // 2
        if not (0 <= cx < img.shape[1] and 0 <= cy < img.shape[0]):
            self.engine.log("Captura rápida: o mouse não está sobre o jogo", "warn")
            return
        crop = img[max(0, cy - half):cy + half, max(0, cx - half):cx + half].copy()
        v = self.engine.vision.next_variant(name)
        fname = self.engine.vision.save(name, crop, img.shape[1], v, source_height=img.shape[0])
        self.engine.log(f"▣ Captura rápida: '{fname}'")
        self.canvas.set_frame(img)
        self._fill_templates()
        self._tpl_selected(self.tpl_list.currentItem())
        QApplication.beep()

    # ----- sistema
    def _pick_exe(self):
        self._pick_file(self.f_exe, "Programas (*.exe)")

    def _pick_file(self, edit, filt):
        p, _ = QFileDialog.getOpenFileName(self, APP, "", filt)
        if p:
            edit.setText(p)

    def _list_windows(self):
        titles = sorted({t for _, t in winapi.list_windows() if t.strip() and not t.startswith(APP)})
        self.f_title.clear()
        self.f_title.addItems([self.cfg.data["game_window_title"]] + titles)

    def _adb_detect(self):
        devs = ADBBackend(self.cfg).devices()
        self.f_serial.clear()
        self.f_serial.addItems(devs or [""])
        self.engine.log(f"ADB: {len(devs)} emulador(es): {', '.join(devs) or '—'}")

    def _adb_connect(self):
        addr, ok = QInputDialog.getText(self, "Conectar emulador",
                                        "Endereço (MuMu 12: 127.0.0.1:16384 · LDPlayer: 127.0.0.1:5555 · "
                                        "BlueStacks: 127.0.0.1:5555):", text="127.0.0.1:16384")
        if ok and addr:
            try:
                self.engine.log("ADB: " + ADBBackend(self.cfg).connect(addr.strip()).strip())
            except Exception as ex:
                self.engine.log(f"ADB: {ex}", "warn")
            self._adb_detect()

    def _set_startup(self, on):
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        try:
            if on:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    pyw = sys.executable.replace("python.exe", "pythonw.exe")
                    cmd = f'"{pyw}" "{os.path.join(ROOT, "main.py")}"'
                winreg.SetValueEx(key, APP, 0, winreg.REG_SZ, cmd + " --minimized")
            else:
                try:
                    winreg.DeleteValue(key, APP)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        self.engine.log("Iniciar com o Windows: " + ("ligado" if on else "desligado"))

    def _tg_find_chat(self):
        try:
            res = self.engine.telegram._api("getUpdates", {})
            chats = [u.get("message", {}).get("chat", {}) for u in res.get("result", [])]
            chats = [c for c in chats if c.get("id")]
            if not chats:
                QMessageBox.information(self, APP, "Mande uma mensagem para o seu bot no Telegram e tente de novo.")
                return
            self.f_chat.setText(str(chats[-1]["id"]))
            self.engine.log(f"Telegram: chat de {chats[-1].get('first_name', '?')} configurado")
        except Exception as ex:
            QMessageBox.warning(self, APP, f"Não consegui falar com o Telegram: {ex}\nConfira o token.")

    def _tg_test(self):
        tgm = self.engine.telegram
        if not tgm.configured():
            self.engine.log("Telegram: ative e preencha token e chat ID", "warn")
            return
        tgm.send(f"[{APP}] teste ✔ — mande /ajuda para ver os comandos")
        img = self.engine.capture()
        if img is not None:
            tgm.send_photo(img, "tela do jogo agora")
        self.engine.log("Telegram: teste enviado")

    def _telegram_cmd(self, cmd, arg):
        """Roda na thread do Telegram: só agenda na UI ou lê estado."""
        e = self.engine
        act = {"iniciar": "start", "parar": "stop", "pausar": "pause", "retomar": "resume", "clicker": "clicker"}
        if cmd in act:
            self.bridge.hotkey.emit(act[cmd])
            return f"ok: {cmd}"
        if cmd == "status":
            return e.status_text()
        if cmd == "print":
            img = e.capture()
            return ("photo", img, e.state()) if img is not None else "jogo não encontrado"
        if cmd == "log":
            return "\n".join(e.lines[-20:]) or "vazio"
        if cmd == "modulos":
            return "\n".join(f"{'🟢' if self.cfg.task(t.id, t.defaults())['enabled'] else '⚪'} {t.id} — {t.name}"
                             for t in ALL_TASKS)
        if cmd in ("ligar", "desligar", "agora"):
            t = e.task_by_id(arg)
            if not t:
                return "id desconhecido — veja /modulos"
            if cmd == "agora":
                e.run_now(t.id)
                return f"executando {t.name}"
            self.cfg.task(t.id, t.defaults())["enabled"] = cmd == "ligar"
            self.cfg.save()
            return f"{t.name}: {'ligado' if cmd == 'ligar' else 'desligado'}"
        return "comando desconhecido — /ajuda"

    # --- atalhos --------------------------------------------------------
    def _register_hotkeys(self):
        try:
            import keyboard
        except ImportError:
            return
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        for action, combo in self.cfg.data["hotkeys"].items():
            if combo:
                try:
                    keyboard.add_hotkey(combo, lambda a=action: self.bridge.hotkey.emit(a))
                except Exception as ex:
                    self.engine.log(f"Atalho '{combo}' inválido: {ex}", "warn")

    def _on_hotkey(self, action):
        {"start": self.engine.start, "stop": self.engine.stop, "pause": self.engine.pause,
         "resume": self.engine.resume, "clicker": lambda: self._toggle_clicker(at_cursor=True),
         "capture": self._quick_capture}[action]()

    # --- atualização ----------------------------------------------------
    def _on_log(self, line, level):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(LEVEL_COLORS.get(level, T.TEXT)))
        for box in (self.full_log, self.mini_log):
            cur = box.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(line + "\n", fmt)
            box.setTextCursor(cur)
            box.ensureCursorVisible()
        self.statusline.setText("›_ " + line)
        self.statusline.setStyleSheet(self.statusline.styleSheet().split("color:")[0] +
                                      f"color:{LEVEL_COLORS.get(level, T.MUTED) if level != 'info' else T.MUTED};"
                                      f"background:#060a14;border-top:1px solid {T.LINE};padding:4px 14px;"
                                      f"font-size:11px")
        if any(m in line for m in ("⚔", "⛏", "▣", "◎")):
            self.radar.ping()
        if "◎ Varredura" in line or "Aprendi" in line:
            self._fill_templates() if "Aprendi" in line else self._fill_map(True)

    def _on_state(self):
        st = self.engine.state()
        col = T.STATE_COLORS[st]
        cur = self.engine.current
        self.pill.setText(f"● {tr('state.' + st)}  ·  {cur[:26]}")
        self.pill.setStyleSheet(f"color:{col};border:1px solid {col};padding:5px 12px;border-radius:3px;"
                                f"letter-spacing:2px")
        self.radar.set_state(st, cur, tr("state." + st))
        self.b_start.setEnabled(not self.engine.running)
        self.b_pause.setEnabled(self.engine.running)
        self.b_pause.setText(tr("btn.resume") if self.engine.paused else tr("btn.pause"))
        self.b_stop.setEnabled(self.engine.running)
        self.tray.setToolTip(f"{APP} · {tr('state.' + st)}")

    def _refresh(self):
        e = self.engine
        for k in ("runs", "taps", "errors"):
            self.stat[k].set(e.stats[k])
        for k in ("digs", "joins_total", "hunts"):
            self.stat[k].set(e.counters.get(k))
        lines = e.session_lines()
        parts = [f"<span style='color:{T.RED if bad else T.TEXT}'>{html.escape(t)}</span>" for t, bad in lines]
        self.session_lbl.setText(f"<b style='color:{T.CYAN}'>ESTA SESSÃO</b>&nbsp;&nbsp;" +
                                 ("&nbsp;·&nbsp; ".join(parts) if parts else
                                  f"<span style='color:{T.MUTED}'>nada ainda — aparece depois do INICIAR</span>"))
        if e.running and e.started_at:
            s = int(time.time() - e.started_at)
            self.uptime.setText(f"{tr('uptime')} {s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")
        page = self.stack.currentIndex()
        if page == self.page_index["dash"]:
            if not e.running and e.backend.name == "pc" and e.backend.ready():
                e.capture()  # pré-visualização ao vivo com o motor parado (~20 ms)
            self.win_lbl.setText(e.backend.describe())
            if e.last_frame is not None:
                pm = bgr_to_pixmap(e.last_frame)
                self.preview.setPixmap(pm.scaled(max(50, self.preview.width() - 4), max(50, self.preview.height() - 4),
                                                 Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.queue.clear()
            now = time.time()
            for t in ALL_TASKS:
                s = self.cfg.task(t.id, t.defaults())
                if not s["enabled"]:
                    continue
                last = e.last_run.get(t.id)
                left = 0 if last is None else max(0, last + float(s["interval_min"]) * 60 - now)
                mark = "▶" if e.current == t.name else " "
                eta = tr("now") if left == 0 else f"{int(left // 60)}m{int(left % 60):02d}s"
                self.queue.addItem(f"{mark}{t.icon} {eta:>7}  {t.name}")
        elif page == self.page_index["map"]:
            self._fill_map()
        active = self.clicker.active
        self.ck_btn.setText("■ PARAR CLICKER" if active else "▶ INICIAR CLICKER")
        if self.ck_btn.objectName() != ("danger" if active else "go"):
            repolish(self.ck_btn, "danger" if active else "go")

    def changeEvent(self, ev):
        if ev.type() == ev.Type.WindowStateChange and self.isMinimized() and self.cfg.data["ui"].get("start_minimized"):
            QTimer.singleShot(0, self.hide)  # minimizar = ir para a bandeja
        super().changeEvent(ev)

    def closeEvent(self, ev):
        if self.engine.running and not getattr(self, "_really_quit", False):
            if QMessageBox.question(self, APP, "O motor está rodando. Fechar mesmo assim?") != QMessageBox.Yes:
                ev.ignore()
                return
        self.b_live.setChecked(False)
        self.engine.stop()
        self.clicker.stop()
        self.engine.telegram.stop_polling()
        self.cfg.save()
        self.tray.hide()
        super().closeEvent(ev)


class NoWheelFilter(QObject):
    """A roda do mouse rolando a página não pode mudar campos por onde passa (já mudou o tamanho da janela
    do jogo sem querer). Campos numéricos/listas só aceitam a roda depois de clicados."""

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QAbstractSpinBox
        if ev.type() == QEvent.Wheel and isinstance(obj, (QAbstractSpinBox, QComboBox, QTimeEdit)) \
                and not obj.hasFocus():
            ev.ignore()
            return True
        if ev.type() == QEvent.Polish and isinstance(obj, (QAbstractSpinBox, QComboBox)):
            obj.setFocusPolicy(Qt.StrongFocus)
        return False


def run(cfg):
    scale = int(cfg.data["ui"].get("scale", 100))
    if scale != 100:
        os.environ["QT_SCALE_FACTOR"] = str(scale / 100)
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyleSheet(T.QSS)
    app._nowheel = NoWheelFilter()
    app.installEventFilter(app._nowheel)
    w = MainWindow(cfg)
    if "--minimized" in sys.argv or cfg.data["ui"].get("start_minimized"):
        w.hide()
        w.tray.showMessage(APP, "Rodando na bandeja", w.icon, 3000)
    else:
        w.show()
    return app.exec()
