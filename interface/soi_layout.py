'''Layouts auxiliares da interface do SOI.'''

from pyqtgraph.Qt import QtCore, QtWidgets


def no_widen(label):
    '''Rótulo de texto variável (status, avisos) que nunca alarga a janela: com texto maior que o espaço ele é
    cortado na borda em vez de aumentar a largura mínima (o que fazia a janela passar da tela).'''
    # Largura mínima explícita (1 px) no lugar da largura do texto: com espaço, o layout ainda dá ao rótulo a largura
    # do texto (sizeHint); sem espaço, ele encolhe e corta
    label.setMinimumWidth(1)
    return label


class FlowBar(QtWidgets.QLayout):
    '''Barra de grupos que quebra em mais linhas quando a janela é estreita. A barra superior inteira tem
    ~1600 px numa linha: com a escala do Windows em 125-200 % isso passa da largura da tela, e a janela
    maximizada ficava cortada à direita (a largura mínima do conteúdo era maior que a tela). O último grupo
    fica encostado à direita da sua linha (Simular amostragem / Configurações).'''

    def __init__(self, parent=None, hspace=10, vspace=4, last_right=True):
        super().__init__(parent)
        self._items = []
        self._last_right = last_right
        self._hs, self._vs = hspace, vspace
        self.setContentsMargins(0, 0, 0, 0)

    def group(self):
        '''Novo grupo (QHBoxLayout sem margens) que não se divide ao quebrar a linha.'''
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.addWidget(w)
        return lay

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def _visible(self):
        # Grupos escondidos ou vazios (todos os widgets do grupo escondidos) não ocupam lugar nem espaçamento
        return [it for it in self._items if not (it.widget() and it.widget().isHidden())
                and it.sizeHint().width() > 0]

    def sizeHint(self):
        items = self._visible()
        m = self.contentsMargins()
        w = sum(it.sizeHint().width() for it in items) + self._hs * max(len(items) - 1, 0)
        h = max((it.sizeHint().height() for it in items), default=0)
        return QtCore.QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self):
        m = self.contentsMargins()
        items = self._visible()
        w = max((it.sizeHint().width() for it in items), default=0)
        # Altura mínima = uma linha: a altura real vem de heightForWidth na largura que a barra recebe. Usar a altura
        # na largura mínima (um grupo por linha) inflava a altura mínima da janela até passar da tela.
        h = max((it.sizeHint().height() for it in items), default=0)
        return QtCore.QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def _do_layout(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        lines, line, x = [], [], 0
        for it in self._visible():
            iw = it.sizeHint().width()
            if line and x + self._hs + iw > r.width():
                lines.append(line)
                line, x = [], 0
            x += (self._hs if line else 0) + iw
            line.append(it)
        if line:
            lines.append(line)
        if not test:
            # Grupos vazios (todos os widgets escondidos) não entram nas linhas, mas o QWidget do grupo continua
            # visível: sem geometria ele ficava em (0, 0, 640, 480) por cima do quadro e engolia os cliques
            shown = {id(it) for line in lines for it in line}
            for it in self._items:
                if id(it) not in shown:
                    it.setGeometry(QtCore.QRect(r.x(), r.y(), 0, 0))
        y = r.y()
        for k, line in enumerate(lines):
            lh = max(it.sizeHint().height() for it in line)
            if not test:
                x = r.x()
                for j, it in enumerate(line):
                    sz = it.sizeHint()
                    if self._last_right and k == len(lines) - 1 and j == len(line) - 1 and len(lines[0]) + k > 1:
                        x = max(x, r.right() + 1 - sz.width())        # último grupo à direita
                    it.setGeometry(QtCore.QRect(QtCore.QPoint(x, y + (lh - sz.height()) // 2), sz))
                    x += sz.width() + self._hs
            y += lh + self._vs
        return y - self._vs - r.y() + m.top() + m.bottom() if lines else 0


def avail_geometry(w):
    '''Área útil da tela em que a janela w está (ou da tela principal).'''
    scr = w.screen() if hasattr(w, 'screen') else None
    if scr is None:
        scr = QtWidgets.QApplication.primaryScreen()
    return scr.availableGeometry() if scr is not None else None


def fit_to_screen(w, margin_w=20, margin_h=40):
    '''Reduz a janela w para caber na área útil da tela (escala do Windows alta em 1366×768).'''
    ag = avail_geometry(w)
    if ag is None:
        return
    w.resize(min(w.width(), ag.width() - margin_w), min(w.height(), ag.height() - margin_h))


def scroll_dialog(dlg, keep_last=0):
    '''Põe o conteúdo do diálogo dlg (menos os keep_last últimos itens, p.ex. os botões) numa área com rolagem
    vertical. A altura fica a do conteúdo enquanto couber na tela; numa tela baixa aparece a barra de rolagem
    em vez de a janela passar da tela (2.5.0).'''
    lay = dlg.layout()
    inner = QtWidgets.QWidget()
    il = QtWidgets.QVBoxLayout(inner)
    il.setContentsMargins(0, 0, 0, 0)
    for _ in range(lay.count() - keep_last):
        it = lay.takeAt(0)
        if it.widget() is not None:
            il.addWidget(it.widget())
        elif it.layout() is not None:
            sub = it.layout()
            sub.setParent(None)
            il.addLayout(sub)
        else:
            il.addItem(it)
    sc = QtWidgets.QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    sc.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sc.setWidget(inner)
    lay.insertWidget(0, sc, 1)

    def fit():
        ag = avail_geometry(dlg)
        need = inner.sizeHint().height() + 2
        if ag is not None:
            rest = dlg.sizeHint().height() - sc.sizeHint().height()
            need = min(need, ag.height() - rest - 60)
        sc.setMinimumHeight(max(120, need))
        sc.setMinimumWidth(inner.minimumSizeHint().width() + sc.verticalScrollBar().sizeHint().width())
    dlg.fit_scroll = fit
    return inner


class Section(QtWidgets.QWidget):
    '''Seção recolhível do painel lateral (2.5.0): cabeçalho clicável (▾ aberta, ▸ recolhida) e conteúdo.
    O estado (aberta/recolhida) fica em is_open() e é salvo pela janela nas preferências.'''

    toggled = QtCore.Signal(bool)

    def __init__(self, title, key, opened=True, parent=None):
        super().__init__(parent)
        self.key = key
        from soi_i18n import tr
        self._title = tr(title)            # traduzido uma vez: o cabeçalho leva ▾/▸ na frente
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(0)
        self.head = QtWidgets.QToolButton()
        self.head.setCheckable(True)
        self.head.setChecked(opened)
        self.head.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.head.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.head.setStyleSheet('QToolButton{font-weight:bold;text-align:left;padding:3px 6px;border:1px solid #c8ccd4;'
                                'border-radius:3px;background:#eef2f8;}QToolButton:hover{background:#e0e8f4;}')
        self.head.toggled.connect(self._on_toggle)
        lay.addWidget(self.head)
        self.body = QtWidgets.QWidget()
        self.body.setObjectName('sectionBody')
        self.body.setStyleSheet('#sectionBody{border:1px solid #d6d9df;border-top:none;background:palette(base);}')
        self.form = QtWidgets.QVBoxLayout(self.body)
        self.form.setContentsMargins(6, 4, 6, 4)
        self.form.setSpacing(4)
        lay.addWidget(self.body)
        self._on_toggle(opened)

    def _on_toggle(self, on):
        self.head.setText(('▾ ' if on else '▸ ') + self._title)
        self.body.setVisible(on)
        self.toggled.emit(on)

    def is_open(self):
        return self.head.isChecked()

    def set_open(self, on):
        self.head.setChecked(bool(on))

    def add(self, item, stretch=0):
        '''Acrescenta um widget ou layout ao conteúdo.'''
        if isinstance(item, QtWidgets.QLayout):
            self.form.addLayout(item, stretch)
        else:
            self.form.addWidget(item, stretch)
        return item

    def row(self):
        '''Linha que quebra quando o painel é estreito (FlowBar sem o último grupo à direita).'''
        bar = FlowBar(hspace=8, vspace=4, last_right=False)
        self.form.addLayout(bar)
        return bar


class SidePanel(QtWidgets.QWidget):
    '''Painel lateral (2.5.0): seções empilhadas numa área com rolagem vertical e um rodapé fixo. A rolagem é o
    que impede que qualquer combinação de seções abertas aumente a altura mínima da janela.'''

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QtWidgets.QWidget()
        self.stack = QtWidgets.QVBoxLayout(inner)
        self.stack.setContentsMargins(0, 0, 4, 0)
        self.stack.setSpacing(2)
        self.stack.addStretch(1)
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll, 1)
        self.footer = QtWidgets.QVBoxLayout()
        self.footer.setContentsMargins(0, 0, 4, 0)
        outer.addLayout(self.footer)

    def add(self, w):
        self.stack.insertWidget(self.stack.count() - 1, w)
        return w

    def minimumSizeHint(self):
        # A largura mínima vem do conteúdo (as linhas quebram); a altura mínima é pequena: o resto rola
        w = self.scroll.widget().minimumSizeHint().width() + self.scroll.verticalScrollBar().sizeHint().width() + 6
        return QtCore.QSize(w, 120)


class CurrentStack(QtWidgets.QStackedWidget):
    '''Pilha cujo tamanho é o da página atual (o QStackedWidget usa o da maior página, o que deixaria espaço vazio
    no painel lateral de uma aba com poucas seções).'''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _: self.updateGeometry())

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()

    # Altura pela largura real (textos com quebra e linhas FlowBar): sem isso o painel reservava a altura do sizeHint,
    # calculada para outra largura, e sobrava espaço vazio dentro das seções
    def hasHeightForWidth(self):
        w = self.currentWidget()
        return w is not None and w.hasHeightForWidth()

    def heightForWidth(self, width):
        w = self.currentWidget()
        return w.heightForWidth(width) if w is not None else -1


class PageLayout(QtWidgets.QVBoxLayout):
    '''Coluna de uma página do painel lateral: o que é acrescentado fica acima de um espaço elástico, para a sobra de
    altura nunca ir para dentro das seções.'''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.addStretch(1)

    def addWidget(self, w, stretch=0, *a):
        self.insertWidget(self.count() - 1, w, stretch, *a)

    def addLayout(self, lay, stretch=0):
        self.insertLayout(self.count() - 1, lay, stretch)
