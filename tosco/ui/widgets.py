"""Widgets HUD: fundo em grade, radar animado, cards de métricas, chave neon e tela de recorte."""
import math

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QVBoxLayout, QWidget

from . import theme as T


def make_icon(size=256):
    """Ícone do TOSCO: hexágono neon com um T."""
    from PySide6.QtGui import QIcon, QPolygonF
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c, r = size / 2, size * 0.46
    hexa = QPolygonF([QPointF(c + r * math.cos(math.radians(60 * i - 90)), c + r * math.sin(math.radians(60 * i - 90)))
                      for i in range(6)])
    p.setBrush(QColor("#070c18"))
    p.setPen(QPen(QColor(T.CYAN), size * 0.045))
    p.drawPolygon(hexa)
    f = QFont("Consolas", int(size * 0.42), QFont.Black)
    p.setFont(f)
    p.setPen(QColor(T.MAGENTA))
    p.drawText(QRectF(size * 0.03, size * 0.04, size, size), Qt.AlignCenter, "T")
    p.setPen(QColor(T.CYAN))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "T")
    p.end()
    return QIcon(pm), pm


def bgr_to_pixmap(bgr):
    h, w = bgr.shape[:2]
    rgb = bgr[:, :, ::-1].copy()
    return QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())


class GridBackground(QWidget):
    """Grade de blueprint + vinheta, pintada atrás de todo o conteúdo."""

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.BG))
        minor, major = QColor(0, 229, 255, 10), QColor(0, 229, 255, 22)
        for i, x in enumerate(range(0, self.width(), 24)):
            p.setPen(major if i % 5 == 0 else minor)
            p.drawLine(x, 0, x, self.height())
        for i, y in enumerate(range(0, self.height(), 24)):
            p.setPen(major if i % 5 == 0 else minor)
            p.drawLine(0, y, self.width(), y)


class Radar(QWidget):
    """Radar com varredura; cor e velocidade seguem o estado do motor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.angle = 0.0
        self.state = "PARADO"
        self.label = "—"
        self.blips = []
        self._t = QTimer(self, timeout=self._tick)
        self._t.start(33)

    def set_state(self, state, label, text=None):
        self.state, self.label, self.text = state, label, text or state
        self.update()

    def ping(self):
        import random
        self.blips.append([random.uniform(0, 360), random.uniform(0.25, 0.9), 1.0])

    def _tick(self):
        speed = {"ATIVO": 4.0, "PAUSADO": 0.6, "PARADO": 0.25}[self.state]
        self.angle = (self.angle + speed) % 360
        for b in self.blips:
            b[2] -= 0.012
        self.blips = [b for b in self.blips if b[2] > 0]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 10
        c = QPointF(self.width() / 2, self.height() / 2)
        r = side / 2
        col = QColor(T.STATE_COLORS[self.state])
        # anéis
        for k in range(1, 5):
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 35 + 15 * k), 1))
            p.drawEllipse(c, r * k / 4, r * k / 4)
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 40), 1))
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        # marcas de grau
        for d in range(0, 360, 10):
            a = math.radians(d)
            r1 = r - (8 if d % 30 == 0 else 4)
            p.drawLine(QPointF(c.x() + r1 * math.cos(a), c.y() + r1 * math.sin(a)),
                       QPointF(c.x() + r * math.cos(a), c.y() + r * math.sin(a)))
        # varredura
        g = QConicalGradient(c, -self.angle)
        g.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(), 150))
        g.setColorAt(0.12, QColor(col.red(), col.green(), col.blue(), 0))
        g.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, r, r)
        # blips
        for ang, dist, life in self.blips:
            a = math.radians(ang)
            p.setBrush(QColor(255, 43, 214, int(255 * life)))
            p.drawEllipse(QPointF(c.x() + r * dist * math.cos(a), c.y() + r * dist * math.sin(a)), 4, 4)
        # centro
        p.setBrush(QColor(T.BG))
        p.setPen(QPen(col, 1.5))
        p.drawEllipse(c, r * 0.36, r * 0.36)
        p.setPen(col)
        f = QFont("Consolas", 13, QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        p.setFont(f)
        p.drawText(QRectF(c.x() - r, c.y() - 20, 2 * r, 22), Qt.AlignCenter, getattr(self, "text", self.state))
        p.setPen(QColor(T.MUTED))
        p.setFont(QFont("Consolas", 8))
        txt = self.label if len(self.label) < 22 else self.label[:21] + "…"
        p.drawText(QRectF(c.x() - r, c.y() + 2, 2 * r, 18), Qt.AlignCenter, txt.upper())


class Card(QFrame):
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 12)
        self.lay.setSpacing(8)
        if title:
            h = QLabel(f"▸ {title.upper()}")
            h.setObjectName("h")
            self.lay.addWidget(h)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setPen(QPen(QColor(T.CYAN), 2))
        w, h, k = self.width() - 1, self.height() - 1, 9
        for x, y, dx, dy in ((0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1), (w, h, -1, -1)):
            p.drawLine(x, y, x + dx * k, y)
            p.drawLine(x, y, x, y + dy * k)


class StatCard(Card):
    def __init__(self, label, color=T.CYAN):
        super().__init__()
        self.value = QLabel("0")
        self.value.setObjectName("big")
        self.value.setStyleSheet(f"color:{color}")
        cap = QLabel(label.upper())
        cap.setObjectName("muted")
        self.lay.addWidget(self.value)
        self.lay.addWidget(cap)

    def set(self, v):
        self.value.setText(str(v))


class Toggle(QAbstractButton):
    """Chave on/off neon com animação."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 20)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)  # não "pos": no Qt isso é a posição do widget
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._go)

    def _go(self, on):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = QColor(T.CYAN)
        track = QColor(on.red(), on.green(), on.blue(), int(40 + 60 * self._pos))
        p.setPen(QPen(on if self._pos > 0.5 else QColor(T.MUTED), 1))
        p.setBrush(track if self._pos > 0.01 else QColor("#060b16"))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 3, 3)
        x = 3 + (self.width() - 20) * self._pos
        p.setPen(Qt.NoPen)
        p.setBrush(on if self._pos > 0.5 else QColor(T.MUTED))
        p.drawRoundedRect(QRectF(x, 3, 14, self.height() - 6), 2, 2)


class CaptureCanvas(QLabel):
    """Mostra a captura do jogo; arraste para selecionar a área do template.
    Também desenha caixas de resultado de teste."""

    selected = Signal(QRect)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 270)
        self.setAlignment(Qt.AlignCenter)
        self.setText("Sem imagem — clique em CAPTURAR JOGO ou ABRIR IMAGEM\n"
                     "Depois arraste o mouse sobre o botão/ícone para recortar")
        self.setStyleSheet(f"background:#04070e;border:1px dashed {T.LINE};color:{T.MUTED}")
        self.src = None
        self._a = self._b = None
        self.hits = []

    def set_frame(self, bgr):
        self.src = bgr
        self._a = self._b = None
        self.hits = []
        self.update()

    def _geom(self):
        h, w = self.src.shape[:2]
        s = min(self.width() / w, self.height() / h)
        return s, (self.width() - w * s) / 2, (self.height() - h * s) / 2

    def _to_src(self, pt):
        s, ox, oy = self._geom()
        h, w = self.src.shape[:2]
        return QPointF(min(max((pt.x() - ox) / s, 0), w - 1), min(max((pt.y() - oy) / s, 0), h - 1))

    def mousePressEvent(self, e):
        if self.src is not None:
            self._a = self._b = self._to_src(e.position())
            self.hits = []
            self.update()

    def mouseMoveEvent(self, e):
        if self._a is not None and e.buttons():
            self._b = self._to_src(e.position())
            self.update()
            self.selected.emit(self.selection())

    def mouseReleaseEvent(self, e):
        if self._a is not None:
            self.selected.emit(self.selection())

    def selection(self):
        """Retângulo selecionado em pixels da imagem (largura/altura exatas, sem o +1 do QRect por pontos)."""
        if self._a is None or self._b is None or self.src is None:
            return QRect()
        x0, x1 = sorted((int(self._a.x()), int(self._b.x())))
        y0, y1 = sorted((int(self._a.y()), int(self._b.y())))
        return QRect(x0, y0, x1 - x0, y1 - y0)

    def set_selection(self, x, y, w, h):
        """Ajuste fino pelos números (X, Y, largura, altura)."""
        if self.src is None:
            return
        H, W = self.src.shape[:2]
        x, y = max(0, min(x, W - 1)), max(0, min(y, H - 1))
        w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
        self._a, self._b = QPointF(x, y), QPointF(x + w, y + h)
        self.update()

    def crop(self):
        """Recorte selecionado (BGR) ou None."""
        sel = self.selection()
        if self.src is None or sel.width() < 6 or sel.height() < 6:
            return None
        return self.src[sel.y():sel.y() + sel.height(), sel.x():sel.x() + sel.width()].copy()

    def paintEvent(self, e):
        if self.src is None:
            return super().paintEvent(e)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#04070e"))
        s, ox, oy = self._geom()
        h, w = self.src.shape[:2]
        p.drawPixmap(QRectF(ox, oy, w * s, h * s), bgr_to_pixmap(self.src), QRectF(0, 0, w, h))
        sel = self.selection()
        if sel.width() > 2:
            r = QRectF(ox + sel.x() * s, oy + sel.y() * s, sel.width() * s, sel.height() * s)
            p.fillRect(r, QColor(0, 229, 255, 40))
            p.setPen(QPen(QColor(T.CYAN), 1.5, Qt.DashLine))
            p.drawRect(r)
            p.setPen(QColor(T.CYAN))
            p.drawText(r.bottomLeft() + QPointF(0, 14), f"{sel.width()}×{sel.height()} @ {sel.x()},{sel.y()}")
        for (cx, cy, score, tw, th) in self.hits:
            r = QRectF(ox + (cx - tw / 2) * s, oy + (cy - th / 2) * s, tw * s, th * s)
            p.setPen(QPen(QColor(T.MAGENTA), 2))
            p.drawRect(r)
            p.drawText(r.topLeft() + QPointF(0, -4), f"{score:.2f}")
