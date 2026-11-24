# -*- coding: utf-8 -*-
'''Widgets próprios (chaves, spin de τ, quadro flutuante, esquema da célula), eixos e ícone.

Parte do SOI Controller (antes em soi_controller.py).'''

from soi_const import *  # noqa: F401,F403
from soi_analise import *  # noqa: F401,F403
from soi_dsp import *  # noqa: F401,F403
from soi_serial import *  # noqa: F401,F403
from soi_sim import *  # noqa: F401,F403


_SUP = str.maketrans('0123456789-', '⁰¹²³⁴⁵⁶⁷⁸⁹⁻')
_pg_log_tick_strings = pg.AxisItem.logTickStrings


def _log_tick_strings(self, values, scale, spacing):
    """Eixo x logarítmico (frequência): décadas como 10ˣ e, entre elas, só o algarismo (2 … 9) em vez de 2·10ˣ,
    que se sobrepunha em faixas grandes. Com menos de uma década à vista, o valor inteiro (200, 300 …).
    Se as divisões ficam apertadas, mostra só 2 e 5 (ou só as décadas). O eixo y continua como no pyqtgraph."""
    if self.orientation not in ('bottom', 'top') or not len(values):
        return _pg_log_tick_strings(self, values, scale, spacing)
    vals = np.asarray(values, dtype=float) + np.log10(scale)
    lo, hi = self.range if hasattr(self, 'range') else (vals.min(), vals.max())
    span = max(abs(hi - lo), 1e-9)
    exps = np.floor(vals + 1e-6)
    mant = np.round(10 ** (vals - exps), 6)
    decade = np.isclose(mant, 1.0)
    if not decade.any() or span < 1.0:
        return [f'{v:.4g}' for v in 10 ** vals]
    ppd = max(self.width(), 1.0) / span                        # pixels por década
    gap = 16.0                                                 # px entre centros de rótulos vizinhos ("9" e "10¹")
    if ppd * np.log10(10 / 9) >= gap:
        keep = set(range(2, 10))
    elif ppd * np.log10(10 / 8) >= gap:                        # sem o 9, colado no 10ˣ
        keep = set(range(2, 9))
    elif ppd * np.log10(3 / 2) >= gap:
        keep = {2, 3, 5}
    elif ppd * np.log10(5 / 2) >= gap:
        keep = {2, 5}
    else:
        keep = set()
    out = []
    for e, m, d in zip(exps, mant, decade):
        if d:
            out.append('1' if e == 0 else '10' + str(int(e)).translate(_SUP))
        elif abs(m - round(m)) < 1e-3 and int(round(m)) in keep:
            out.append(str(int(round(m))))
        else:
            out.append('')
    return out


pg.AxisItem.logTickStrings = _log_tick_strings


class TimeAxis(pg.AxisItem):
    '''Eixo de tempo com unidade nos rótulos (s ou ms).'''
    lockin_time = True
    base_label = 'Tempo antes do instante atual'
    _unit = None

    def tickStrings(self, values, scale, spacing):
        if not self.lockin_time:
            return super().tickStrings(values, scale, spacing)
        ms = abs(spacing) < 0.1
        unit = 'ms' if ms else 's'
        if unit != self._unit:
            self._unit = unit
            QtCore.QTimer.singleShot(0, lambda: self.lockin_time and self.setLabel(f'{self.base_label} ({self._unit})'))
        return [f'{v * 1000:g}' if ms else f'{v:g}' for v in values]


class ModeSwitch(QtWidgets.QAbstractButton):
    '''Chave vertical: em cima = Lock-In, embaixo = Valor Médio.'''

    def __init__(self, tip='Clique para alternar: cima = Lock-In, baixo = Valor Médio', parent=None):
        super().__init__(parent)
        self.down = False
        self.setFixedSize(34, 64)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip)

    def setDown(self, down):
        self.down = bool(down)
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        track = QtCore.QRectF(3, 3, self.width() - 6, self.height() - 6)
        p.setPen(QtGui.QPen(QtGui.QColor('#777'), 1))
        p.setBrush(QtGui.QColor('#4a90d9' if not self.down else '#3fa34d'))
        p.drawRoundedRect(track, 14, 14)
        d = track.width() - 6
        y = track.bottom() - 3 - d if self.down else track.top() + 3
        p.setBrush(QtGui.QColor('white'))
        p.drawEllipse(QtCore.QRectF(track.left() + 3, y, d, d))


class ToggleSwitch(QtWidgets.QAbstractButton):
    '''Chave horizontal liga/desliga.'''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(52, 26)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        track = QtCore.QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QtGui.QPen(QtGui.QColor('#777'), 1))
        p.setBrush(QtGui.QColor('#e0952b' if self.isChecked() else '#b8b8b8'))
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        d = track.height() - 6
        x = track.right() - 3 - d if self.isChecked() else track.left() + 3
        p.setBrush(QtGui.QColor('white'))
        p.drawEllipse(QtCore.QRectF(x, track.top() + 3, d, d))


class RefreshComboBox(QtWidgets.QComboBox):
    '''QComboBox que atualiza a lista (refresh()) logo antes de abrir.'''

    def __init__(self, refresh):
        super().__init__()
        self._refresh = refresh

    def showPopup(self):
        self._refresh()
        super().showPopup()


class TauSpinBox(QtWidgets.QDoubleSpinBox):
    '''Campo de τ (s): mostra "300 ms" / "1 s", aceita valores digitados com ou sem unidade e as setas
    andam pela sequência 1–3–10 de TAU_STEPS.'''

    def __init__(self, value, slot=None, width=90):
        super().__init__()
        self.setDecimals(6)
        self.setRange(TAU_MIN, TAU_MAX)
        self.setValue(value)
        self.setKeyboardTracking(False)   # só dispara ao confirmar (Enter/perder foco)
        self.setFixedWidth(width)
        if slot is not None:
            self.valueChanged.connect(slot)

    def textFromValue(self, v):
        return f'{v * 1e3:.4g} ms' if v < 1.0 else f'{v:.4g} s'

    @staticmethod
    def _parse(text):
        m = re.fullmatch(r'\s*([0-9]*[.,]?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*(ms|s)?\s*', text)
        if not m:
            return None
        v = float(m.group(1).replace(',', '.'))
        return v * 1e-3 if m.group(2) == 'ms' else v

    def valueFromText(self, text):
        v = self._parse(text)
        return self.value() if v is None else v

    def validate(self, text, pos):
        v = self._parse(text)
        if v is not None and TAU_MIN <= v <= TAU_MAX:
            return QtGui.QValidator.State.Acceptable, text, pos
        return QtGui.QValidator.State.Intermediate, text, pos

    def stepBy(self, steps):
        v = self.value()
        for _ in range(abs(steps)):
            if steps > 0:
                v = next((s for s in TAU_STEPS if s > v * (1.0 + 1e-6)), TAU_MAX)
            else:
                v = next((s for s in reversed(TAU_STEPS) if s < v * (1.0 - 1e-6)), TAU_MIN)
        self.setValue(v)


class StepThread(threading.Thread):
    '''Chama step() repetidamente em thread própria até stop().'''

    def __init__(self, step, interval=0.005):
        super().__init__(daemon=True)
        self.step = step
        self.interval = interval
        self._stop_evt = threading.Event()

    def run(self):
        while not self._stop_evt.is_set():
            try:
                self.step()
            except Exception as e:
                print(f"Erro na thread de processamento: {e}")
            self._stop_evt.wait(self.interval)

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=2.0)


class FloatingResults(QtWidgets.QFrame):
    '''Quadro de resultados que flutua sobre os gráficos: arraste pelo título para tirá-lo de cima dos dados;
    ▾/▸ recolhe o conteúdo. Fica sempre dentro do widget pai e some quando todos os textos estão vazios.'''

    def __init__(self, parent, labels, title='Resultados', on_texts=None):
        super().__init__(parent)
        self.labels = labels
        self.on_texts = on_texts        # com on_texts o quadro não aparece: os textos vão para quem chamou
        self.setObjectName('floatres')
        self.setStyleSheet('#floatres{background:rgba(255,255,255,230);border:1px solid #9a9a9a;border-radius:4px;}')
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(6, 2, 6, 4)
        v.setSpacing(1)
        head = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel(f'<b>{title}</b> <span style="color:#808080;">(arraste para mover)</span>')
        self.title.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        head.addWidget(self.title)
        head.addStretch(1)
        self.btn = QtWidgets.QToolButton()
        self.btn.setText('▾')
        self.btn.setAutoRaise(True)
        self.btn.setToolTip('Recolhe ou mostra os resultados.')
        self.btn.clicked.connect(self._toggle)
        head.addWidget(self.btn)
        v.addLayout(head)
        self.body = QtWidgets.QWidget()
        bv = QtWidgets.QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(1)
        for lb in labels:
            lb.setParent(self.body)
            bv.addWidget(lb)
        v.addWidget(self.body)
        self.rel = (0.06, 0.62)                     # canto superior esquerdo, em fração do pai
        self._drag = None
        self._texts = None
        parent.installEventFilter(self)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(300)
        self.hide()

    def _toggle(self):
        self.body.setVisible(not self.body.isVisible())
        self.btn.setText('▾' if self.body.isVisible() else '▸')
        self._fit()

    def refresh(self, force=False):
        texts = tuple(lb.text() for lb in self.labels)
        if texts == self._texts and not force:
            return
        self._texts = texts
        if self.on_texts is not None:
            self.hide()
            self.on_texts(texts)
            return
        for lb, tx in zip(self.labels, texts):
            lb.setVisible(bool(tx.strip()))
        any_txt = any(tx.strip() for tx in texts)
        self.setVisible(any_txt)
        if any_txt:
            self._fit()
            self.raise_()

    def _fit(self):
        par = self.parentWidget()
        w = max(280, min(640, int(par.width() * 0.42)))
        self.setFixedWidth(w)
        lay = self.layout()
        lay.activate()
        self.setFixedHeight(lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else lay.sizeHint().height())
        self._place()

    def _place(self):
        par = self.parentWidget()
        x = int(self.rel[0] * par.width())
        y = int(self.rel[1] * par.height())
        x = min(max(0, x), max(0, par.width() - self.width()))
        y = min(max(0, y), max(0, par.height() - self.height()))
        self.move(x, y)

    def eventFilter(self, obj, ev):
        if obj is self.parentWidget() and ev.type() == QtCore.QEvent.Type.Resize and self.isVisible():
            self._fit()
        return False

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag = ev.position().toPoint()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag is None:
            return
        par = self.parentWidget()
        pos = self.mapToParent(ev.position().toPoint()) - self._drag
        self.rel = (pos.x() / max(1, par.width()), pos.y() / max(1, par.height()))
        self._place()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag = None


class CellSchematic(QtWidgets.QWidget):
    '''Esquema genérico da montagem para a referência de calibração escolhida: a amostra fecha a abertura
    da célula (OPC) ou fica dentro dela, sob uma janela de vidro (câmara). Desenho vetorial, sem imagens.'''

    SAMPLE_COLORS = {'al': '#a8adb3', 'black_plate': '#a8adb3', 'black': '#1e1e1e', 'generic': '#c9a36b',
                     'foil': '#e8dcc0'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cell, self.sample = 'OPC', 'al'
        # Tamanho proporcional à fonte da interface (escala do Windows), entre 1× e 1,5×, em 85 % do desenho
        # original (300 × 160): o esquema define a altura do quadro da calibração, então fica compacto
        k = 0.85 * min(1.5, max(1.0, QtGui.QFontMetrics(self.font()).height() / 16.0))
        self.setFixedSize(round(300 * k), round(160 * k))

    def set_setup(self, cell, sample):
        self.cell, self.sample = cell or 'OPC', sample
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor('#ffffff'))
        # Desenho em coordenadas fixas (300 × 160) e fontes em pixels: o texto escala junto com o desenho,
        # sem depender da escala do Windows nem da fonte do sistema
        p.scale(self.width() / 300.0, self.height() / 160.0)
        pen = QtGui.QPen(QtGui.QColor('#404040'), 1.5)
        body = QtGui.QColor('#d9dde2')
        gas = QtGui.QColor('#eef6ff')
        x0, x1, y0, y1 = 52, 202, 38, 132          # corpo da célula
        cx0, cx1, cy0, cy1 = 82, 172, 50, 120      # cavidade
        p.setPen(pen)
        p.setBrush(body)
        p.drawRect(x0, y0, x1 - x0, y1 - y0)
        p.setBrush(gas)
        p.drawRect(cx0, cy0, cx1 - cx0, cy1 - cy0)
        # Abertura no topo (por onde a luz entra)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(gas)
        p.drawRect(cx0 + 15, y0 - 1, cx1 - cx0 - 30, cy0 - y0 + 2)
        p.setPen(pen)
        p.drawLine(cx0 + 15, y0, cx0 + 15, cy0)
        p.drawLine(cx1 - 15, y0, cx1 - 15, cy0)
        lx = cx0 + 28                              # feixe do laser
        col = QtGui.QColor(self.SAMPLE_COLORS.get(self.sample, '#a8adb3'))
        font = QtGui.QFont(p.font())
        font.setPixelSize(10)
        p.setFont(font)
        if self.cell == 'OPC':
            # Amostra fina tampando a abertura, por fora
            p.setBrush(col)
            p.drawRect(cx0 + 5, y0 - 5, cx1 - cx0 - 10, 5)
            p.setPen(QtGui.QColor('#202020'))
            p.drawText(QtCore.QRectF(x1 + 4, y0 - 12, 94, 26), QtCore.Qt.AlignmentFlag.AlignLeft, 'amostra\n(fecha)')
            title = 'OPC: a amostra fecha a célula'
            hit_y = y0 - 5
        else:
            # Janela de vidro fechando a abertura e amostra no fundo da cavidade
            p.setBrush(QtGui.QColor(170, 215, 240, 170))
            p.drawRect(cx0 + 5, y0 - 5, cx1 - cx0 - 10, 5)
            sh = 9
            p.setBrush(col)
            p.drawRect(cx0 + 12, cy1 - sh, cx1 - cx0 - 24, sh)
            if self.sample == 'black_plate':            # face de cima pintada de preto
                p.setBrush(QtGui.QColor('#1e1e1e'))
                p.drawRect(cx0 + 12, cy1 - sh, cx1 - cx0 - 24, 3)
            elif self.sample == 'foil':                 # folha de Al fina sobre apoio isolante (bege)
                p.setBrush(QtGui.QColor('#a8adb3'))
                p.drawRect(cx0 + 12, cy1 - sh - 2, cx1 - cx0 - 24, 2)
            p.setPen(QtGui.QColor('#202020'))
            p.drawText(QtCore.QRectF(x1 + 4, y0 - 12, 94, 26), QtCore.Qt.AlignmentFlag.AlignLeft, 'janela\nde vidro')
            p.drawText(QtCore.QRectF(x1 + 4, cy1 - 16, 94, 26), QtCore.Qt.AlignmentFlag.AlignLeft, 'amostra\n(dentro)')
            # folga de ar sobre a amostra
            p.setPen(QtGui.QPen(QtGui.QColor('#2e7d32'), 1))
            ax = cx1 - 8
            p.drawLine(ax, cy1 - sh - 1, ax, cy0 + 2)
            p.drawText(QtCore.QRectF(lx + 4, cy0 + 12, cx1 - lx - 14, 26), QtCore.Qt.AlignmentFlag.AlignRight, 'ar\n≥ 2–3 mm')
            title = 'Câmara: amostra dentro, janela de vidro'
            hit_y = cy1 - sh
        # Laser vindo de cima
        lp = QtGui.QPen(QtGui.QColor('#d00000'), 2.5)
        p.setPen(lp)
        p.drawLine(lx, 4, lx, hit_y)
        p.setBrush(QtGui.QColor('#d00000'))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(lx - 4, hit_y - 7), QtCore.QPointF(lx + 4, hit_y - 7),
                                       QtCore.QPointF(lx, hit_y)]))
        p.setPen(QtGui.QColor('#d00000'))
        p.drawText(QtCore.QRectF(lx + 5, 1, 50, 14), QtCore.Qt.AlignmentFlag.AlignLeft, 'laser')
        # Microfone na parede esquerda da cavidade
        p.setPen(pen)
        p.setBrush(QtGui.QColor('#505050'))
        p.drawRect(x0 + 6, (cy0 + cy1) // 2 - 9, cx0 - x0 - 6, 18)
        p.setPen(QtGui.QColor('#202020'))
        p.drawText(QtCore.QRectF(0, (cy0 + cy1) // 2 - 7, x0 - 3, 14), QtCore.Qt.AlignmentFlag.AlignRight, 'mic')
        font.setBold(True)
        while font.pixelSize() > 7 and QtGui.QFontMetrics(font).horizontalAdvance(title) > 296:
            font.setPixelSize(font.pixelSize() - 1)
        p.setFont(font)
        p.drawText(QtCore.QRectF(0, y1 + 6, 300, 18), QtCore.Qt.AlignmentFlag.AlignHCenter, title)
        p.end()


def resource_path(*parts):
    """Caminho de um arquivo que acompanha a interface (pasta interface/ ou executável PyInstaller)."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_icon():
    """Ícone do SOI (logo do LCTM): .ico com 16 a 256 px; PNG se o .ico não puder ser lido."""
    icon = QtGui.QIcon()
    for name in ('soi.ico', 'soi_256.png'):
        path = resource_path('icones', name)
        if os.path.exists(path):
            icon = QtGui.QIcon(path)
            if not icon.isNull():
                break
    return icon


# Exporta tudo (inclusive nomes com _) para os módulos que fazem import *
__all__ = [_n for _n in dir() if not _n.startswith('__')]
