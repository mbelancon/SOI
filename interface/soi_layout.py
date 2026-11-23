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
        w = max((it.sizeHint().width() for it in self._visible()), default=0)
        return QtCore.QSize(w + m.left() + m.right(), self.heightForWidth(w + m.left() + m.right()))

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
