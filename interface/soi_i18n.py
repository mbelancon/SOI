#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interface language for the SOI Controller (Portuguese or English).

The interface is written in Portuguese. When the language is English, `install()` wraps the Qt and
pyqtgraph calls that put text on screen (labels, buttons, tooltips, titles, combo items, dialogs, plot
labels, legends) so that each text goes through `tr()` first. Only what is shown changes: the strings
inside the program stay in Portuguese, so data files (names, CSV columns and header keys) are the same
in both languages and old files keep loading.

Language choice: the SOI_LANG environment variable (pt or en) wins; otherwise the Windows display
language (Portuguese -> pt, anything else -> en); on other systems, the locale.

To translate a new text, add it to EN below (the Portuguese text exactly as in the code). Texts built
from pieces (f-strings) are translated piece by piece, so add the fixed pieces.
"""

import os
import re
import sys


def _detect_language():
    v = os.environ.get('SOI_LANG', '').strip().lower()[:2]
    if v in ('pt', 'en'):
        return v
    if sys.platform == 'win32':
        try:
            import ctypes
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return 'pt' if (lid & 0x3FF) == 0x16 else 'en'      # 0x16 = Portuguese (Brazil and Portugal)
        except Exception:
            pass
    for k in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE'):
        v = os.environ.get(k, '')
        if v and v not in ('C', 'POSIX', 'C.UTF-8'):
            return 'pt' if v.lower().startswith('pt') else 'en'
    try:
        import locale
        loc = (locale.getlocale()[0] or '').lower()
    except Exception:
        loc = ''
    return 'pt' if loc.startswith('pt') else 'en'


LANG = _detect_language()

_cache = {}
_frag_re = None
# Applied after the piece-by-piece translation (English only)
_POST = (
    (re.compile(r'(\d),(\d)'), r'\1.\2'),                  # decimal comma
    (re.compile(r'(\d(?: ?[kKmµ]?Hz)?) a (\d)'), r'\1 to \2'),
    (re.compile(r'\bde (?=[\d.]+(?: ?[kKmµ]?Hz)? to \d)'), 'from '),
    (re.compile(r'(\d) de (\d)'), r'\1 of \2'),
    (re.compile(r'(\d %) em '), r'\1 at '),
    (re.compile(r'(\d) em (\d)'), r'\1 in \2'),
)


# Short words translated only when they are the whole text (never inside a sentence)
EN_EXACT = {
    'a': 'to',
    'fim': 'end',
}


def _build():
    global _frag_re
    keys = sorted((k for k in EN if re.search(r'[A-Za-zÀ-ÿ]', k)), key=len, reverse=True)
    parts = []
    for k in keys:
        p = re.escape(k)
        if re.match(r'\w', k):
            p = r'(?<!\w)' + p
        if re.search(r'\w$', k):
            p = p + r'(?!\w)'
        parts.append(p)
    _frag_re = re.compile('|'.join(parts))


def _frag(m):
    return EN[m.group(0)]


def tr(s):
    '''Text s in the interface language.'''
    if LANG == 'pt' or not isinstance(s, str) or not s:
        return s
    r = _cache.get(s)
    if r is None:
        r = EN.get(s) or EN_EXACT.get(s)
        if r is None:
            if _frag_re is None:
                _build()
            r = _frag_re.sub(_frag, s)
            for rx, rep in _POST:
                r = rx.sub(rep, r)
        if len(_cache) > 5000:
            _cache.clear()
        _cache[s] = r
    return r


def _wrap(cls, name, idx=(0,), kw=(), lists=False):
    '''Make cls.name translate its positional arguments idx (and keywords kw) that are strings.'''
    orig = getattr(cls, name, None)
    if orig is None or getattr(orig, '_soi_tr', False):
        return

    def f(*a, **k):
        a = list(a)
        for i in idx:
            if i < len(a):
                if isinstance(a[i], str):
                    a[i] = tr(a[i])
                elif lists and isinstance(a[i], (list, tuple)):
                    a[i] = [tr(x) for x in a[i]]
        for n in kw:
            if isinstance(k.get(n), str):
                k[n] = tr(k[n])
        return orig(*a, **k)
    f._soi_tr = True
    setattr(cls, name, f)


def _tr_ctor(module, name):
    '''Replace module.name with a subclass whose constructor translates its first text argument.'''
    base = getattr(module, name)
    if getattr(base, '_soi_tr', False):
        return

    def __init__(self, *a, **k):
        a = [tr(x) if isinstance(x, str) else x for x in a]
        if isinstance(k.get('text'), str):
            k['text'] = tr(k['text'])
        if isinstance(k.get('title'), str):
            k['title'] = tr(k['title'])
        base.__init__(self, *a, **k)
    sub = type(name, (base,), {'__init__': __init__, '_soi_tr': True})
    setattr(module, name, sub)


def install(QtWidgets, QtGui, pg):
    '''Translate everything the interface puts on screen (does nothing in Portuguese).'''
    if LANG == 'pt':
        return
    W = QtWidgets
    # Methods are patched first (self is argument 0, so the text is argument 1)
    for cls, name in ((W.QLabel, 'setText'), (W.QAbstractButton, 'setText'), (W.QWidget, 'setToolTip'),
                      (W.QWidget, 'setWindowTitle'), (W.QGroupBox, 'setTitle'), (W.QLineEdit, 'setPlaceholderText'),
                      (W.QAbstractSpinBox, 'setSpecialValueText'), (W.QMessageBox, 'setText'),
                      (W.QMessageBox, 'setInformativeText'), (W.QTextEdit, 'setHtml'), (W.QTextEdit, 'setPlainText'),
                      (W.QMenu, 'addMenu'), (W.QMenu, 'addAction'), (W.QMenu, 'setTitle'), (QtGui.QAction, 'setText')):
        _wrap(cls, name, idx=(1,))
    _wrap(W.QMessageBox, 'addButton', idx=(1,))
    _wrap(W.QTabWidget, 'addTab', idx=(2,))
    _wrap(W.QTabWidget, 'setTabText', idx=(2,))
    _wrap(W.QTabWidget, 'setTabToolTip', idx=(2,))
    _wrap(W.QComboBox, 'addItem', idx=(1, 2))
    _wrap(W.QComboBox, 'addItems', idx=(1,), lists=True)
    _wrap(W.QComboBox, 'insertItem', idx=(2, 3))
    _wrap(W.QComboBox, 'setItemText', idx=(2,))
    _wrap(W.QComboBox, 'setItemData', idx=(2,))
    _wrap(QtGui.QPainter, 'drawText', idx=(1, 2, 3, 4, 5, 6))
    for name in ('information', 'warning', 'critical', 'question'):
        orig = getattr(W.QMessageBox, name)

        def box(*a, _orig=orig, **k):
            return _orig(*[tr(x) if isinstance(x, str) else x for x in a], **k)
        setattr(W.QMessageBox, name, staticmethod(box))
    for name in ('getOpenFileName', 'getSaveFileName'):
        orig = getattr(W.QFileDialog, name)

        def dlg(*a, _orig=orig, **k):
            a = list(a)
            for i in (1, 3):                    # caption and filter (not the folder)
                if i < len(a) and isinstance(a[i], str):
                    a[i] = tr(a[i])
            for n in ('caption', 'filter'):
                if isinstance(k.get(n), str):
                    k[n] = tr(k[n])
            return _orig(*a, **k)
        setattr(W.QFileDialog, name, staticmethod(dlg))
    for name in ('QLabel', 'QPushButton', 'QCheckBox', 'QRadioButton', 'QGroupBox'):
        base = getattr(W, name)
        _tr_ctor(W, name)
        try:                                    # pyqtgraph looks some widget types up by exact class
            from pyqtgraph.WidgetGroup import WidgetGroup
            if base in WidgetGroup.classes:
                WidgetGroup.classes[getattr(W, name)] = WidgetGroup.classes[base]
        except Exception:
            pass
    # pyqtgraph
    _wrap(pg.PlotItem, 'setLabel', idx=(2,), kw=('text',))
    _wrap(pg.PlotItem, 'setTitle', idx=(1,), kw=('title',))
    _wrap(pg.AxisItem, 'setLabel', idx=(1,), kw=('text',))
    _wrap(pg.LegendItem, 'addItem', idx=(2,))
    _wrap(pg.TextItem, 'setText', idx=(1,))
    _wrap(pg.TextItem, 'setHtml', idx=(1,))
    _wrap(pg.LabelItem, 'setText', idx=(1,))

# Portuguese text -> English text (exact strings and pieces of composed messages)
EN = {
    ' - problemas: ':
        ' - problems: ',
    ' (esperado ':
        ' (expected ',
    '), desvio de f<sup>−':
        '), deviation from f<sup>−',
    ' dB rms, fase constante ± ':
        ' dB rms, constant phase ± ',
    ' pontos, ':
        ' points, ',
    'arquivo sem dados':
        'file has no data',
    'não é uma varredura do Modo Duplo (colunas de OPT101 e INMP441 não encontradas)':
        'not a Dual Mode sweep (OPT101 and INMP441 columns not found)',
    'arquivo sem pontos':
        'file has no points',
    'não registrada':
        'not recorded',
    'Corte PAS = ':
        'PAS cutoff = ',
    'Corte PAS < ':
        'PAS cutoff < ',
    ': n esperado ':
        ': expected n ',
    'Referência':
        'Reference',
    'Amostra fina sobre suporte espesso':
        'Thin sample on a thick backing',
    'Amostra fina livre':
        'Free thin sample',
    'Fora dos regimes padrão (n ≈ 1 ou 1,5)':
        'Outside the standard regimes (n ≈ 1 or 1.5)',
    '<b>Fit padrão:</b> <b>':
        '<b>Standard fit:</b> <b>',
    ' &nbsp; Atraso do sistema (td) = ':
        ' &nbsp; System delay (td) = ',
    '<br>Faixa confiável: ':
        '<br>Reliable range: ',
    ' pontos); x vermelho = ponto excluído':
        ' points); red x = excluded point',
    'Câmara':
        'Chamber',
    'OPC: a amostra fecha a abertura da célula; a luz chega pelo lado de fora e o microfone fica do outro lado.':
        'OPC: the sample closes the cell opening; the light arrives from outside and the microphone is on the other side.',
    'Câmara: a amostra fica dentro da célula, iluminada através de uma janela de vidro.':
        'Chamber: the sample sits inside the cell, illuminated through a glass window.',
    'Folha de Al fina (modo OPC)':
        'Thin Al foil (OPC mode)',
    'Folha de alumínio fina (papel alumínio, ~12 µm) tampando a abertura, bem esticada e vedada nas bordas (graxa ou fita). O laser incide na face de fora; o microfone fica do lado de dentro.':
        'Thin aluminum foil (kitchen foil, ~12 µm) covering the opening, well stretched and sealed at the edges (grease or tape). The laser hits the outer face; the microphone is on the inside.',
    'Al espesso dentro da câmara':
        'Thick Al inside the chamber',
    'Placa de alumínio (1 mm ou mais) no fundo da câmara, com a face lixada (fosca) para o laser. Feche com a janela de vidro e deixe 2–3 mm de ar ou mais sobre a amostra. Sinal fraco: o alumínio reflete ~90 % da luz.':
        'Aluminum plate (1 mm or more) at the bottom of the chamber, with the face toward the laser sanded (matte). Close with the glass window and leave 2–3 mm of air or more above the sample. Weak signal: aluminum reflects ~90 % of the light.',
    'Folha de Al fina dentro da câmara':
        'Thin Al foil inside the chamber',
    'Folha de alumínio (papel alumínio) com o lado fosco para o laser, lisa e colada sobre um apoio isolante (papel, plástico ou fita dupla face) no fundo da câmara, sob a janela de vidro, com 2–3 mm de ar ou mais por cima. Sem rugas nem bolhas: o sinal depende do contato com o apoio. Sinal fraco (reflete ~90 %); o Al pintado de preto dá mais sinal.':
        'Aluminum foil (kitchen foil), matte side toward the laser, flat and glued onto an insulating backing (paper, plastic or double-sided tape) at the bottom of the chamber, under the glass window, with 2–3 mm of air or more above. No wrinkles or bubbles: the signal depends on the contact with the backing. Weak signal (reflects ~90 %); black-painted Al gives more signal.',
    'Al pintado de preto fosco (câmara)':
        'Matte black painted Al (chamber)',
    'Placa de alumínio com a face voltada para o laser pintada de preto fosco (spray), no fundo da câmara, sob a janela de vidro, com 2–3 mm de ar ou mais por cima. A tinta é uma camada isolante sobre o Al: abaixo de ~10–100 Hz (depende da espessura da tinta) parte do calor vai para o Al e o sinal cai; acima disso segue f⁻¹ como a fita preta.':
        'Aluminum plate with the face toward the laser painted matte black (spray), at the bottom of the chamber, under the glass window, with 2–3 mm of air or more above. The paint is an insulating layer on the Al: below ~10–100 Hz (depends on the paint thickness) part of the heat goes into the Al and the signal drops; above that it follows f⁻¹ like the black tape.',
    'Negro de fumo (câmara)':
        'Carbon black (chamber)',
    'Fuligem de vela sobre um pedaço de lâmina de vidro (apoio isolante, não metal), em camada grossa (~0,1 mm, preto fosco e opaco contra a luz), na mesma altura das amostras, no fundo da câmara, com 2–3 mm de ar ou mais por cima. É o padrão clássico da fotoacústica: o mais próximo de f⁻¹ ideal. Frágil: não toque nem sopre.':
        'Candle soot on a piece of glass slide (insulating backing, not metal), in a thick layer (~0.1 mm, matte black and opaque against the light), at the same height as the samples, at the bottom of the chamber, with 2–3 mm of air or more above. The classic photoacoustic standard: the closest to an ideal f⁻¹. Fragile: do not touch or blow on it.',
    'Fita preta fosca (câmara)':
        'Matte black tape (chamber)',
    'Fita isolante preta (lado fosco) colada numa placa rígida, no fundo da câmara, sob a janela, com 2–3 mm de ar ou mais por cima. Rápida de montar e com sinal alto; boa para gerar a calibração ou para conferir a do negro de fumo. Limite a "Faixa" a ~1 kHz.':
        'Black electrical tape (matte side) stuck to a rigid plate, at the bottom of the chamber, under the window, with 2–3 mm of air or more above. Quick to set up and with a high signal; good for generating the calibration or for checking the carbon black one. Limit the "Range" to ~1 kHz.',
    'Personalizada (lei de potência)':
        'Custom (power law)',
    'Use um padrão cujo expoente n você conheça (S ∝ f⁻ⁿ, fase constante). A célula é a escolhida em "Célula" na linha superior.':
        'Use a standard whose exponent n you know (S ∝ f⁻ⁿ, constant phase). The cell is the one chosen in "Cell" on the top row.',
    '<b>Curva esperada:</b> S ∝ f<sup>−':
        '<b>Expected curve:</b> S ∝ f<sup>−',
    '</sup>, fase constante':
        '</sup>, constant phase',
    '<span style="color:#d00000;">⚠ acima de f₁/10 (':
        '<span style="color:#d00000;">⚠ above f₁/10 (',
    ') a folha deixa de ser termicamente fina e f<sup>−1,5</sup> não vale: use folha mais fina ou limite a faixa</span>':
        ') the foil is no longer thermally thin and f<sup>−1.5</sup> does not hold: use a thinner foil or limit the range</span>',
    'folha termicamente fina na faixa ✓':
        'foil thermally thin over the range ✓',
    'tinta isolante sobre Al: f<sup>−1</sup> acima de ~100 Hz (abaixo, o calor chega ao Al e o sinal cai)':
        'insulating paint on Al: f<sup>−1</sup> above ~100 Hz (below, the heat reaches the Al and the signal drops)',
    'termicamente grossa acima de f₁ = α/(πL²) = ':
        'thermally thick above f₁ = α/(πL²) = ',
    'opaca: f<sup>−1</sup> nos dois regimes, não depende de L nem de α':
        'opaque: f<sup>−1</sup> in both regimes, independent of L and α',
    'termicamente fina até f₁ = α/(πL²) = ':
        'thermally thin up to f₁ = α/(πL²) = ',
    ': o sinal vem da folha e do apoio, e continua f<sup>−1</sup> com o apoio termicamente grosso (papel ou plástico de ~0,1 mm ou mais)':
        ': the signal comes from the foil and the backing, and stays f<sup>−1</sup> with a thermally thick backing (paper or plastic of ~0.1 mm or more)',
    'opaca (Rosencwaig–Gersho): não depende da espessura nem da difusividade':
        'opaque (Rosencwaig–Gersho): independent of thickness and diffusivity',
    'expoente n = ':
        'exponent n = ',
    ', esperado ':
        ', expected ',
    ' (diferença ':
        ' (difference ',
    '; fase: ±':
        '; phase: ±',
    '° em torno do modelo':
        '° around the model',
    'a fase varia ±':
        'the phase varies ±',
    '° (descontados fc e td), esperado constante (±':
        '° (fc and td removed), expected constant (±',
    'faixa confiável de só ':
        'reliable range of only ',
    ' década(s), mínimo ':
        ' decade(s), minimum ',
    '; faixa confiável ':
        '; reliable range ',
    ' década(s)':
        ' decade(s)',
    'vazamento na célula, amostra solta ou mal vedada, folga de ar pequena sobre a amostra, sinal fraco (SNR baixo), absorção da janela de vidro, ou uma ressonância dentro da faixa do ajuste (limite com a "Faixa")':
        'leak in the cell, loose or poorly sealed sample, small air gap above the sample, weak signal (low SNR), absorption by the glass window, or a resonance inside the fit range (limit it with "Range")',
    '<b>Fotoacústico:</b> n = ':
        '<b>Photoacoustic:</b> n = ',
    'domina ':
        'dominates ',
    'domina a faixa toda':
        'dominates the whole range',
    'até ':
        'up to ',
    '× o fotoacústico':
        '× the photoacoustic',
    ';"><b>⚠ Fundo plano não fotoacústico detectado</b> (':
        ';"><b>⚠ Flat non-photoacoustic background detected</b> (',
    '). Verifique a montagem antes de seguir; não gere calibração com ele presente.</span>':
        '). Check the setup before going on; do not generate a calibration while it is present.</span>',
    '<span style="color:#2e7d32;">Sem fundo plano.</span>':
        '<span style="color:#2e7d32;">No flat background.</span>',
    'atraso = ':
        'delay = ',
    'ressonância ':
        'resonance ',
    '<b>Sistema:</b> ':
        '<b>System:</b> ',
    ';">⚠ Ajuste ruim: use só como indicação.</span>':
        ';">⚠ Poor fit: use only as an indication.</span>',
    'Fotoacústico: S ∝ f^-n, n = ':
        'Photoacoustic: S ∝ f^-n, n = ',
    ', fase constante.\n':
        ', constant phase.\n',
    'Fundo plano (amplitude e fase constantes): fundo/fotoacústico = ':
        'Flat background (constant amplitude and phase): background/photoacoustic = ',
    '; fase fundo − fotoacústico = ':
        '; phase background − photoacoustic = ',
    'fc = passa-alta do microfone (':
        'fc = microphone high-pass (',
    ' Hz).\nAtraso = atraso puro da cadeia do microfone em relação à do OPT101 (':
        ' Hz).\nDelay = pure delay of the microphone chain relative to the OPT101 chain (',
    ' µs), quase todo do filtro digital do INMP441;\nnão é o tempo de voo do som nem o atraso térmico da amostra. O atraso do driver/laser se cancela em Δφ.\n':
        ' µs), almost all from the INMP441 digital filter;\nit is not the sound time of flight nor the thermal delay of the sample. The driver/laser delay cancels in Δφ.\n',
    'Ressonância: f0 = ':
        'Resonance: f0 = ',
    ', pico em ':
        ', peak at ',
    'Resíduo rms: magnitude ':
        'Residual rms: magnitude ',
    ' %, fase ':
        ' %, phase ',
    '\nCom a calibração aplicada, o esperado é fc, atraso e ressonância quase nulos.':
        '\nWith the calibration applied, fc, delay and resonance are expected to be almost zero.',
    '<b>Canal óptico (sensor + driver/laser):</b> τ efetivo = ':
        '<b>Optical channel (sensor + driver/laser):</b> effective τ = ',
    ' µs pela fase (1 polo) &nbsp; banda (-3 dB) = ':
        ' µs from the phase (1 pole) &nbsp; bandwidth (-3 dB) = ',
    ' kHz &nbsp; subida 10–90 % = ':
        ' kHz &nbsp; rise 10–90 % = ',
    '° &nbsp; resíduo rms = ':
        '° &nbsp; residual rms = ',
    '<br><span style="color:#d00000;">τ não determinado: a fase até ':
        '<br><span style="color:#d00000;">τ not determined: the phase up to ',
    ' Hz não separa o polo do ruído (varra até frequências maiores).</span>':
        ' Hz does not separate the pole from the noise (sweep to higher frequencies).</span>',
    '<br>Verificação: τ pela queda de amplitude = ':
        '<br>Check: τ from the amplitude drop = ',
    ' &nbsp; <span style="color:#d00000;">⚠ fase e amplitude incompatíveis com um polo único: atraso puro (driver/laser) ou potência do laser variando com a frequência. O τ da fase é efetivo e inclui esse atraso.</span>':
        ' &nbsp; <span style="color:#d00000;">⚠ phase and amplitude not consistent with a single pole: pure delay (driver/laser) or laser power changing with frequency. The τ from the phase is effective and includes that delay.</span>',
    '<b>Luz (OPT101):</b> R = ':
        '<b>Light (OPT101):</b> R = ',
    ' em baixa frequência, ':
        ' at low frequency, ',
    ' (variação total ':
        ' (total change ',
    'estável':
        'stable',
    'a normalização desconta essa variação':
        'normalization removes this change',
    'Canal óptico = driver + laser + OPT101. Só o polo do OPT101 não é comum ao microfone; o atraso do\ndriver/laser se cancela em Δφ, e a calibração do microfone absorve o polo do OPT101 enquanto o\nresistor de realimentação for o mesmo. Nada aqui precisa ser calibrado no uso normal.':
        'Optical channel = driver + laser + OPT101. Only the OPT101 pole is not shared with the microphone; the\ndriver/laser delay cancels in Δφ, and the microphone calibration absorbs the OPT101 pole as long as the\nfeedback resistor stays the same. Nothing here needs calibrating in normal use.',
    'banda do canal óptico ≈ ':
        'optical channel bandwidth ≈ ',
    '<br><span style="color:#b35c00;">A varredura passa de metade da banda óptica: perto de ':
        '<br><span style="color:#b35c00;">The sweep goes past half the optical bandwidth: near ',
    ' parte da queda da luz pode ser do sensor. Se trocar o resistor do OPT101, use Calibração do microfone → Avançado.</span>':
        ' part of the light drop may come from the sensor. If you change the OPT101 resistor, use Microphone calibration → Advanced.</span>',
    'τ do sensor: os ganhos das duas varreduras são próximos demais (razão ':
        'Sensor τ: the gains of the two sweeps are too close (ratio ',
    '); use resistores que mudem o ganho pelo menos 1,3×.':
        '); use resistors that change the gain by at least 1.3×.',
    'τ do sensor = ':
        'Sensor τ = ',
    ' µs nesta varredura (':
        ' µs in this sweep (',
    ' µs na de referência; razão de ganho ':
        ' µs in the reference one; gain ratio ',
    ' frequências em comum)':
        ' common frequencies)',
    'Faixa com S ∝ f⁻ⁿ (n esperado da amostra)':
        'Range with S ∝ f⁻ⁿ (expected n of the sample)',
    'Lei de potência  S ∝ f⁻ⁿ':
        'Power law  S ∝ f⁻ⁿ',
    'Duas leis de potência (com quebra)':
        'Two power laws (with break)',
    'Difusão térmica (placa, detecção traseira)':
        'Thermal diffusion (plate, rear detection)',
    'Flexão termoelástica (Perondi–Miranda)':
        'Thermoelastic bending (Perondi–Miranda)',
    'Câmara: amostra opaca (RG, S ∝ f⁻¹)':
        'Chamber: opaque sample (RG, S ∝ f⁻¹)',
    'Câmara: transparente e termicamente grossa (RG, S ∝ f⁻¹·⁵)':
        'Chamber: transparent and thermally thick (RG, S ∝ f⁻¹·⁵)',
    'Ressonância da célula (oscilador amortecido + fundo)':
        'Cell resonance (damped oscillator + background)',
    'Escolha o n esperado da amostra (1: opaca na câmara; 1,5: folha fina em OPC ou transparente). O ajuste\nprocura a maior faixa contínua em que S segue f⁻ⁿ (n livre dentro de ±0,15 do esperado, desvio ≤ 1,5 dB rms\ne fase constante ± 10°) e a mostra sombreada. Fora dela, a forma vem do sistema (vazamento, ressonância)\nou a amostra não é a esperada. Com a calibração aplicada ("Usar"), a faixa mostra onde a calibração vale.':
        'Choose the expected n of the sample (1: opaque in the chamber; 1.5: thin foil in OPC or transparent). The fit\nlooks for the widest continuous range where S follows f⁻ⁿ (n free within ±0.15 of the expected, deviation ≤ 1.5 dB rms\nand constant phase ± 10°) and shows it shaded. Outside it, the shape comes from the system (leak, resonance)\nor the sample is not the expected one. With the calibration applied ("Use"), the range shows where the calibration holds.',
    'S ∝ f⁻ⁿ com fase constante. Ajusta só o expoente n (descritivo, sem modelo físico).':
        'S ∝ f⁻ⁿ with constant phase. Fits only the exponent n (descriptive, no physical model).',
    'Duas retas em log-log, contínuas na frequência de quebra fb: S ∝ f^-n1 abaixo de fb e f^-n2 acima.\nAjusta n1, n2 e fb (só a magnitude). Útil para separar regimes: por exemplo, a flexão termoelástica\nde uma placa grossa (n ≈ 1) e uma contribuição de fundo que domina em frequência alta (n ≈ 0).\nUse a Faixa para analisar cada parte com mais cuidado.':
        'Two straight lines in log-log, continuous at the break frequency fb: S ∝ f^-n1 below fb and f^-n2 above.\nFits n1, n2 and fb (magnitude only). Useful to separate regimes: for example, the thermoelastic bending\nof a thick plate (n ≈ 1) and a background contribution that dominates at high frequency (n ≈ 0).\nUse the Range to analyze each part more carefully.',
    'Difusão do calor através de uma placa iluminada numa face, com o gás do microfone na outra\n(célula aberta, OPC): S ∝ f^-0,5 / [σL·sinh(σL)], σL = (1+i)·√(f/f1).\nBaixa frequência (placa termicamente fina): S ∝ f^-1,5, como a folha de alumínio.\nAlta frequência: a amplitude cai como exp(−√(f/f1)) e a fase atrasa √(f/f1) radianos.':
        'Heat diffusion through a plate illuminated on one face, with the microphone gas on the other\n(open cell, OPC): S ∝ f^-0.5 / [σL·sinh(σL)], σL = (1+i)·√(f/f1).\nLow frequency (thermally thin plate): S ∝ f^-1.5, like the aluminum foil.\nHigh frequency: the amplitude drops as exp(−√(f/f1)) and the phase lags √(f/f1) radians.',
    'Flexão termoelástica de uma placa termicamente grossa em célula aberta (OPC):\nS ∝ f⁻¹·[(1 − 1/x) + i/x], x = √(f/f1). Costuma dominar em placas metálicas.\nA fase cai ~90° em torno de f1 e se estabiliza acima dela.\nRef.: L. F. Perondi, L. C. M. Miranda, J. Appl. Phys. 62, 2955 (1987);\nG. Rousset, F. Lepoutre, L. Bertrand, J. Appl. Phys. 54, 2383 (1983).':
        'Thermoelastic bending of a thermally thick plate in an open cell (OPC):\nS ∝ f⁻¹·[(1 − 1/x) + i/x], x = √(f/f1). Usually dominates in metal plates.\nThe phase drops ~90° around f1 and levels off above it.\nRef.: L. F. Perondi, L. C. M. Miranda, J. Appl. Phys. 62, 2955 (1987);\nG. Rousset, F. Lepoutre, L. Bertrand, J. Appl. Phys. 54, 2383 (1983).',
    'Célula fechada com a amostra dentro (Rosencwaig–Gersho). Amostra opaca: S ∝ f⁻¹ com fase constante,\nseja ela termicamente fina ou grossa. Sem parâmetro de forma: o ajuste mede só o quanto os dados\nse afastam do modelo (resíduos). Use com a calibração aplicada.\nRef.: A. Rosencwaig, A. Gersho, J. Appl. Phys. 47, 64 (1976).':
        'Closed cell with the sample inside (Rosencwaig–Gersho). Opaque sample: S ∝ f⁻¹ with constant phase,\nwhether thermally thin or thick. No shape parameter: the fit only measures how far the data\ndeviate from the model (residuals). Use with the calibration applied.\nRef.: A. Rosencwaig, A. Gersho, J. Appl. Phys. 47, 64 (1976).',
    'Célula fechada com a amostra dentro (Rosencwaig–Gersho). Amostra transparente (absorção fraca) e\ntermicamente grossa: S ∝ f⁻¹·⁵, fase constante (−90° em relação à opaca). Se a amostra for\nsemitransparente, o expoente fica entre 1 e 1,5. Sem parâmetro de forma: veja os resíduos.':
        'Closed cell with the sample inside (Rosencwaig–Gersho). Transparent (weakly absorbing) and\nthermally thick sample: S ∝ f⁻¹·⁵, constant phase (−90° relative to the opaque one). If the sample is\nsemitransparent, the exponent lies between 1 and 1.5. No shape parameter: look at the residuals.',
    'Ressonância acústica da célula: z(f) = A·e^{i(φ0 − 2πfτ)}·[f0²/(f0² − f² + i·f·f0/Q) + b·e^{iβ}].\nAjusta f0, Q, a largura (f0/Q) e o ganho do pico sobre o fundo. Sem "Faixa", o pico é achado sozinho;\nou use "Marcar pico" e clique dos dois lados dele no gráfico da esquerda.\nMeça com "Usar" desmarcado: a calibração do microfone remove a ressonância da célula.':
        'Acoustic resonance of the cell: z(f) = A·e^{i(φ0 − 2πfτ)}·[f0²/(f0² − f² + i·f·f0/Q) + b·e^{iβ}].\nFits f0, Q, the width (f0/Q) and the peak gain over the background. Without "Range", the peak is found automatically;\nor use "Mark peak" and click on both sides of it in the left plot.\nMeasure with "Use" unchecked: the microphone calibration removes the cell resonance.',
    '   espera: ':
        '   settling: ',
    'Constante de tempo de cada polo do passa-baixas aplicado depois da demodulação (2 polos em cascata).\nτ maior = menos ruído e leitura mais estável, porém resposta mais lenta.\nAs setas andam na sequência 1–3–10: 1 ms, 3 ms, 10 ms … 30 s, 100 s. Também aceita um valor digitado\n(ex.: 0,5 s ou 200 ms).\nUse τ de pelo menos ~3 períodos da modulação (τ ≥ 3/f) para rejeitar o resíduo em 2f.\nAo mudar a frequência, volta ao automático: ~3 períodos, arredondado para 0,3 s, 1 s ou 3 s.':
        'Time constant of each pole of the low-pass applied after demodulation (2 poles in cascade).\nLarger τ = less noise and steadier reading, but slower response.\nThe arrows step in the 1–3–10 sequence: 1 ms, 3 ms, 10 ms … 30 s, 100 s. A typed value is also accepted\n(e.g. 0.5 s or 200 ms).\nUse τ of at least ~3 modulation periods (τ ≥ 3/f) to reject the 2f residue.\nWhen the frequency changes, it returns to automatic: ~3 periods, rounded to 0.3 s, 1 s or 3 s.',
    'Passa-altas de 1 polo antes da demodulação: estima e remove o nível DC do sinal\n(luz ambiente, offset do sensor), deixando só a parte modulada.\nPrecisa ficar bem abaixo da frequência de modulação: corte alto atenua e adianta a fase do sinal.\nNo OPT101 o DC estimado também é o usado em R/DC e na coluna DC_Offset das varreduras.\nAo mudar a frequência, volta ao automático: 2 % da frequência, entre 0,01 e 0,05 Hz.':
        '1-pole high-pass before demodulation: estimates and removes the DC level of the signal\n(ambient light, sensor offset), leaving only the modulated part.\nIt must stay well below the modulation frequency: a high cutoff attenuates and advances the signal phase.\nOn the OPT101 the estimated DC is also the one used in R/DC and in the DC_Offset column of the sweeps.\nWhen the frequency changes, it returns to automatic: 2 % of the frequency, between 0.01 and 0.05 Hz.',
    'Calculados a partir do τ (2 polos em cascata, 12 dB/oitava):\n−3 dB: frequência de corte do filtro, 0,644/(2πτ).\nENBW: banda equivalente de ruído, 1/(8τ). O ruído na saída cresce com √ENBW.\nespera: 9τ, tempo para a saída chegar a ~0,1 % do valor final após um degrau\n(~95 % em 4,7τ e ~99 % em 6,6τ). É o que as varreduras esperam em cada ponto.':
        'Computed from τ (2 poles in cascade, 12 dB/octave):\n−3 dB: filter cutoff frequency, 0.644/(2πτ).\nENBW: equivalent noise bandwidth, 1/(8τ). The output noise grows with √ENBW.\nsettling: 9τ, time for the output to reach ~0.1 % of the final value after a step\n(~95 % at 4.7τ and ~99 % at 6.6τ). This is what the sweeps wait at each point.',
    'poucas amostras para o teste (mínimo 1024)':
        'too few samples for the test (minimum 1024)',
    '<b style="color:#d00000;">O laser estava modulando durante a medida.</b> O sinal entra como "ruído" e o resultado não vale; repita com PWM 0 % ou luz constante.':
        '<b style="color:#d00000;">The laser was modulating during the measurement.</b> The signal counts as "noise" and the result is not valid; repeat with PWM 0 % or constant light.',
    '<b style="color:#d00000;">Sem dither:</b> σ = ':
        '<b style="color:#d00000;">No dither:</b> σ = ',
    ' LSB, quase todas as amostras caem no mesmo código (':
        ' LSB, almost all samples fall on the same code (',
    ' códigos distintos). O ruído das médias até cai, mas a média converge para o código errado (viés de até ~½ LSB): não há resolução nova. A sobreamostragem precisa de ruído de ~0,5 LSB ou mais (ganho maior no OPT101 ajuda).':
        ' distinct codes). The noise of the averages still drops, but the average converges to the wrong code (bias of up to ~½ LSB): there is no new resolution. Oversampling needs noise of ~0.5 LSB or more (a higher OPT101 gain helps).',
    '<b style="color:#e07000;">Dither marginal:</b> σ = ':
        '<b style="color:#e07000;">Marginal dither:</b> σ = ',
    ' LSB. O ganho pode ficar abaixo do ideal; ruído um pouco maior (ou ganho maior no OPT101) ajudaria.':
        ' LSB. The gain may fall short of ideal; a bit more noise (or a higher OPT101 gain) would help.',
    'Dither suficiente: σ = ':
        'Enough dither: σ = ',
    ' LSB por amostra (':
        ' LSB per sample (',
    ' códigos distintos).':
        ' distinct codes).',
    'O ruído cai como 1/√N até <b>N = ':
        'The noise falls as 1/√N up to <b>N = ',
    '): ganho de ':
        '): gain of ',
    ' bits efetivos.':
        ' effective bits.',
    'Acima disso a curva se afasta do ideal: ruído 1/f, interferência ou deriva dominam e aumentar o OSR quase não melhora a resolução (o lock-in continua filtrando pela banda do τ).':
        'Above that the curve departs from ideal: 1/f noise, interference or drift dominate and raising the OSR barely improves the resolution (the lock-in keeps filtering by the τ bandwidth).',
    'Conexão com o STM32 perdida ao escrever: ':
        'Connection to the STM32 lost while writing: ',
    'Conexão com o STM32 perdida ao ler: ':
        'Connection to the STM32 lost while reading: ',
    '] Perda USB no OPT101: ':
        '] USB loss on the OPT101: ',
    ' vezes':
        ' times',
    'Conexão com o Arduino perdida ao escrever: ':
        'Connection to the board lost while writing: ',
    'Processo de leitura da serial terminou; voltando à leitura em thread.':
        'Serial reader process ended; switching back to reading in a thread.',
    'Conectando à porta ':
        'Connecting to port ',
    'Conectado! Parâmetros enviados: F=':
        'Connected! Parameters sent: F=',
    'Erro ao abrir porta serial (':
        'Error opening serial port (',
    'Leitura da serial em processo separado indisponível (':
        'Serial reading in a separate process unavailable (',
    '); usando thread.':
        '); using a thread.',
    'Conexão com o Arduino perdida ao ler: ':
        'Connection to the board lost while reading: ',
    'Tempo antes do instante atual':
        'Time before the current instant',
    'Clique para alternar: cima = Lock-In, baixo = Valor Médio':
        'Click to toggle: up = Lock-In, down = Average',
    'Erro na thread de processamento: ':
        'Error in the processing thread: ',
    'Resultados':
        'Results',
    '</b> <span style="color:#808080;">(arraste para mover)</span>':
        '</b> <span style="color:#808080;">(drag to move)</span>',
    'Recolhe ou mostra os resultados.':
        'Collapses or shows the results.',
    'amostra\n(fecha)':
        'sample\n(closes)',
    'OPC: a amostra fecha a célula':
        'OPC: the sample closes the cell',
    'janela\nde vidro':
        'glass\nwindow',
    'amostra\n(dentro)':
        'sample\n(inside)',
    'Câmara: amostra dentro, janela de vidro':
        'Chamber: sample inside, glass window',
    'Excitação:':
        'Excitation:',
    'Amostra:':
        'Sample:',
    'nome da amostra':
        'sample name',
    'Todos os arquivos salvos na pasta Medidas começam com este nome.\nCaracteres inválidos em nomes de arquivo viram "_". Vazio = sem prefixo.':
        'All files saved in the Medidas folder start with this name.\nCharacters not allowed in file names become "_". Empty = no prefix.',
    'Calibração:':
        'Calibration:',
    'Usar':
        'Use',
    'Corrige a varredura em frequência do Modo Duplo pela calibração escolhida:\nS é dividido pela sensibilidade relativa e Δφ é descontado da fase do sistema.\nDesmarque para gerar uma calibração nova (ela usa os dados brutos).':
        'Corrects the Dual Mode frequency sweep with the chosen calibration:\nS is divided by the relative sensitivity and Δφ has the system phase removed.\nUncheck to generate a new calibration (it uses the raw data).',
    'Célula:':
        'Cell:',
    'Configuração da célula nesta medida:\n':
        'Cell configuration for this measurement:\n',
    '\nA calibração do microfone só vale na configuração em que foi feita (o volume de gás e a\nacústica mudam); a interface avisa se a calibração escolhida for de outra. Vai para os CSV.':
        '\nThe microphone calibration only holds in the configuration it was made in (the gas volume and the\nacoustics change); the interface warns if the chosen calibration is from another one. Goes into the CSV files.',
    'Simular amostragem':
        'Simulate sampling',
    'Gera um sinal simulado (com ruído) quando não há STM32 conectado.':
        'Generates a simulated (noisy) signal when no STM32 is connected.',
    'Finalizar experimento':
        'Finish experiment',
    'Compacta num ZIP (pasta Medidas, nome = amostra + data) todos os arquivos salvos\ndesde que a interface abriu (ou desde o último "Finalizar experimento"),\njunto com a calibração do microfone em uso.':
        'Packs into a ZIP (Medidas folder, name = sample + date) all files saved\nsince the interface opened (or since the last "Finish experiment"),\ntogether with the microphone calibration in use.',
    'Inicializando...':
        'Initializing...',
    'Janela (s):':
        'Window (s):',
    'Filtro 60 Hz':
        '60 Hz filter',
    'Rejeita 60 Hz e múltiplos (até 1,5 kHz) no sinal bruto e no lock-in.\nNotches que caem sobre a frequência de modulação são omitidos.':
        'Rejects 60 Hz and its multiples (up to 1.5 kHz) in the raw signal and in the lock-in.\nNotches that fall on the modulation frequency are skipped.',
    'Disponível apenas no lock-in em Python.':
        'Only available in the Python lock-in.',
    'Sobreamostragem:':
        'Oversampling:',
    'O STM32 envia todas as amostras do ADC (12 bits, 200 kS/s). A interface tira a média de\nOSR amostras seguidas: o ruído branco cai com √OSR (+½ bit a cada dobra) e a taxa\ncai para 200/OSR kS/s. 16x reproduz a versão 1.0.0 (12,5 kS/s).\nUse "Teste de resolução" para ver até onde o ganho é real no seu sinal.\nBloqueado durante varreduras.':
        'The STM32 sends every ADC sample (12 bits, 200 kS/s). The interface averages\nOSR consecutive samples: white noise falls with √OSR (+½ bit per doubling) and the rate\nfalls to 200/OSR kS/s. 16x reproduces version 1.0.0 (12.5 kS/s).\nUse "Resolution test" to see how far the gain is real on your signal.\nLocked during sweeps.',
    'Teste de resolução':
        'Resolution test',
    'Mede, com sinal estável (laser desligado ou luz constante), quanto a sobreamostragem\nreduz o ruído de fato: ruído × OSR comparado com o ideal 1/√OSR, bits efetivos e\nhistograma dos códigos crus do ADC.':
        'Measures, with a steady signal (laser off or constant light), how much oversampling\nactually reduces the noise: noise × OSR compared with the ideal 1/√OSR, effective bits and\nhistogram of the raw ADC codes.',
    'Sinal bruto do ADC (PA0, <span style="color:#000;">preto</span>) e referência do laser (<span style="color:#009600;">verde tracejado</span>, 0/1) - osciloscópio em tempo real':
        'Raw ADC signal (PA0, <span style="color:#000;">black</span>) and laser reference (<span style="color:#009600;">green dashed</span>, 0/1) - real-time oscilloscope',
    'Tempo (s)':
        'Time (s)',
    'Limiar de Saturação':
        'Saturation threshold',
    'Visualização reduzida, f>50 Hz':
        'Reduced view, f>50 Hz',
    'Magnitude (u.a.)':
        'Magnitude (a.u.)',
    'Fase (Graus)':
        'Phase (degrees)',
    'Valor Médio':
        'Average',
    'Magnitude e fase do lock-in ao longo do tempo.':
        'Lock-in magnitude and phase over time.',
    'Forma de onda média do ADC sobre vários pulsos (permite o ajuste exponencial).':
        'Average ADC waveform over several pulses (allows the exponential fit).',
    'Pausa:':
        'Pause:',
    'Salvar':
        'Save',
    'CSV e PNG serão salvos na pasta Medidas':
        'CSV and PNG will be saved in the Medidas folder',
    'Espectro do sinal bruto do ADC (coluna da direita).':
        'Raw ADC signal spectrum (right column).',
    'Varreduras ▸':
        'Sweeps ▸',
    'Mostra ou esconde as varreduras em frequência e PWM do OPT101.':
        'Shows or hides the OPT101 frequency and PWM sweeps.',
    'Para ajustar exponenciais, pause o gráfico:':
        'To fit exponentials, pause the plot:',
    '⏸ Pausar e ajustar':
        '⏸ Pause and fit',
    'Análise da curva':
        'Curve analysis',
    'Modelo:':
        'Model:',
    '1 exponencial':
        '1 exponential',
    '2 exponenciais':
        '2 exponentials',
    'Plota o modelo com os parâmetros atuais (de t=0 até o fim do pulso)':
        'Plots the model with the current parameters (from t=0 to the end of the pulse)',
    'Otimizar':
        'Optimize',
    'Ajusta por mínimos quadrados usando os valores atuais como ponto de partida':
        'Least-squares fit using the current values as the starting point',
    'Clique para alternar: cima = Fit do On, baixo = Fit do Off':
        'Click to toggle: up = On fit, down = Off fit',
    'Fit do On':
        'On fit',
    'Fit do Off':
        'Off fit',
    'Requer o Modo Lock-In.':
        'Requires Lock-In mode.',
    'Varredura em frequência (OPT101)':
        'Frequency sweep (OPT101)',
    'Início:':
        'Start:',
    'Fim:':
        'End:',
    'Varredura em PWM (OPT101)':
        'PWM sweep (OPT101)',
    'Ajusta o maior pico perto da referência com a forma exata do pico\nde uma senoide na FFT com janela Hann: frequência e amplitude\ncorrigidas, mesmo quando o tom cai entre dois bins.':
        'Fits the largest peak near the reference with the exact peak shape\nof a sine wave in a Hann-windowed FFT: corrected frequency and amplitude,\neven when the tone falls between two bins.',
    'Espectro completo':
        'Full spectrum',
    'Desligado: região em torno da frequência de referência, com FFT longa\n(':
        'Off: region around the reference frequency, with a long FFT\n(',
    ' s, resolução fina).\nLigado: 0 a FS/2 (metade da taxa depois da sobreamostragem),\nFFT de ':
        ' s, fine resolution).\nOn: 0 to FS/2 (half the rate after oversampling),\nFFT of ',
    ' pontos a 12,5 kS/s (cresce com a taxa).':
        ' points at 12.5 kS/s (grows with the rate).',
    'OPT101 - espectro do ADC (FFT)':
        'OPT101 - ADC spectrum (FFT)',
    'Frequência (Hz)':
        'Frequency (Hz)',
    'Pulsos:':
        'Pulses:',
    'Número de pulsos somados na média.':
        'Number of pulses summed in the average.',
    'Mostra mais tempo antes do início do pulso (+10 ms de pré-trigger).':
        'Shows more time before the pulse start (+10 ms of pre-trigger).',
    'Mostra menos tempo antes do início do pulso (−10 ms de pré-trigger).':
        'Shows less time before the pulse start (−10 ms of pre-trigger).',
    'Pré: -0.000 s':
        'Pre: -0.000 s',
    'Pré-trigger: tempo exibido antes da borda de subida do laser.':
        'Pre-trigger: time shown before the laser rising edge.',
    'Inicializando áudio...':
        'Initializing audio...',
    'Exibição':
        'Display',
    'Mostra ou esconde as varreduras em frequência e PWM do INMP441.':
        'Shows or hides the INMP441 frequency and PWM sweeps.',
    'Gráficos:':
        'Plots:',
    'Ruído/SNR':
        'Noise/SNR',
    'Média e desvio-padrão da saída do lock-in numa janela móvel.\nUse uma janela bem maior que τ (≥ 10τ) para uma estimativa confiável.':
        'Mean and standard deviation of the lock-in output over a moving window.\nUse a window much longer than τ (≥ 10τ) for a reliable estimate.',
    'Exibição do lock-in: R e Fase (esquerda) ou X e Y (direita).\nAo passar para X/Y a auto-fase é aplicada.':
        'Lock-in display: R and Phase (left) or X and Y (right).\nSwitching to X/Y applies auto-phase.',
    'Auto-fase':
        'Auto-phase',
    'Ajusta o offset de fase para que o sinal fique todo em X (θ ≈ 0),\nusando a média do último ':
        'Adjusts the phase offset so the signal lies entirely in X (θ ≈ 0),\nusing the average of the last ',
    'Rejeita 60 Hz e múltiplos (até 1,5 kHz) no sinal do lock-in.\nNotches que caem sobre a frequência de modulação são omitidos.':
        'Rejects 60 Hz and its multiples (up to 1.5 kHz) in the lock-in signal.\nNotches that fall on the modulation frequency are skipped.',
    'Tempo exibido nos gráficos do lock-in e do ruído/SNR (até ':
        'Time shown in the lock-in and noise/SNR plots (up to ',
    ' s).\nA estatística de ruído/SNR usa esta mesma janela (até ':
        ' s).\nThe noise/SNR statistics use this same window (up to ',
    'Varredura em frequência (INMP441)':
        'Frequency sweep (INMP441)',
    'Varredura em PWM (INMP441)':
        'PWM sweep (INMP441)',
    'Ruído/SNR: aguardando dados':
        'Noise/SNR: waiting for data',
    'INMP441 - Lock-In (Magnitude e Fase)':
        'INMP441 - Lock-In (Magnitude and Phase)',
    'Magnitude (escala completa 24 bits)':
        'Magnitude (24-bit full scale)',
    'Tempo relativo (s)':
        'Relative time (s)',
    'Alerta SNR < (dB):':
        'SNR alert < (dB):',
    'A barra de status fica vermelha com "SINAL BAIXO" quando o SNR da\njanela de ruído cai abaixo deste valor (linha tracejada vermelha).\n10 dB ≈ sinal 3x maior que o desvio-padrão do ruído (limite prático de detecção).':
        'The status bar turns red with "LOW SIGNAL" when the SNR of the\nnoise window drops below this value (dashed red line).\n10 dB ≈ signal 3x larger than the noise standard deviation (practical detection limit).',
    ' s, resolução fina).\nLigado: 0 a ':
        ' s, fine resolution).\nOn: 0 to ',
    ' kHz, FFT de ':
        ' kHz, FFT of ',
    ' pontos.':
        ' points.',
    'INMP441 - espectro (FFT)':
        'INMP441 - spectrum (FFT)',
    'Média no tempo (τ atual)':
        'Time average (current τ)',
    'Integração longa (τ da varredura)':
        'Long integration (sweep τ)',
    'Média no tempo: usa os filtros dos dois lock-ins (na varredura em frequência, os cortes automáticos\nde cada frequência); espera 9τ do mais lento e faz a média por 4τ.\nIntegração longa: durante a varredura os dois passa-baixas passam a ter o τ escolhido (restaurados no fim);\nespera 9τ e faz a média por 1τ. Menos ruído por ponto, varredura mais lenta.':
        'Time average: uses the filters of both lock-ins (in the frequency sweep, the automatic cutoffs\nfor each frequency); waits 9τ of the slower one and averages for 4τ.\nLong integration: during the sweep both low-pass filters take the chosen τ (restored at the end);\nwaits 9τ and averages for 1τ. Less noise per point, slower sweep.',
    'Medida:':
        'Measurement:',
    'Varredura casada em PWM':
        'Matched PWM sweep',
    'Logarítmico':
        'Logarithmic',
    'N pontos:':
        'N points:',
    'Varredura em frequência':
        'Frequency sweep',
    'Espaçamento:':
        'Spacing:',
    'Varredura em frequência (normalizada pelo OPT101)':
        'Frequency sweep (normalized by the OPT101)',
    'Refinar ressonância':
        'Refine resonance',
    'Ajusta a ressonância da célula (oscilador amortecido + fundo, acima de 250 Hz) na varredura atual\ne mede mais pontos, igualmente espaçados, dentro do pico, f0 ± f0/(2Q). Os pontos novos entram na\nmesma varredura (em ordem de frequência) e o CSV é gravado de novo com todos. Usa a Medida e o τ\ndeste quadro. Serve também para uma varredura aberta do disco.':
        'Fits the cell resonance (damped oscillator + background, above 250 Hz) on the current sweep\nand measures more points, evenly spaced, inside the peak, f0 ± f0/(2Q). The new points join the\nsame sweep (in frequency order) and the CSV is written again with all of them. Uses the Measurement and the τ\nof this panel. Also works for a sweep opened from disk.',
    'Pontos novos:':
        'New points:',
    'Varredura ▸':
        'Sweep ▸',
    'Varredura em frequência (calibrar e medir), Refinar ressonância e, recolhida,\na varredura casada em PWM (linearidade com a potência do laser).':
        'Frequency sweep (calibrate and measure), Refine resonance and, collapsed,\nthe matched PWM sweep (linearity with the laser power).',
    'Calibração ▸':
        'Calibration ▸',
    'Calibração do microfone: referência, esquema da montagem, Gerar curva de calibração e\nVerificar com outra referência.':
        'Microphone calibration: reference, setup diagram, Generate calibration curve and\nVerify with another reference.',
    'Abrir varredura…':
        'Open sweep…',
    'Carrega uma varredura do Modo Duplo já salva (CSV da pasta Medidas) para analisar:\ncalibração, ajuste com modelos, exclusão de pontos, Fitar padrão e Salvar de novo.':
        'Loads a saved Dual Mode sweep (CSV from the Medidas folder) for analysis:\ncalibration, model fitting, point exclusion, standard Fit and Save again.',
    'Casada em PWM ▸':
        'Matched PWM ▸',
    'Casada em PWM ':
        'Matched PWM ',
    'Arranjo dos gráficos':
        'Plot arrangement',
    'Lado a lado':
        'Side by side',
    'Empilhado':
        'Stacked',
    'Sobrepostos (fase no eixo da direita)':
        'Overlaid (phase on the right axis)',
    'Clique num ponto para tirá-lo do ajuste.':
        'Click a point to remove it from the fit.',
    'Clique num ponto do gráfico da esquerda para tirá-lo do ajuste; clique de novo para incluí-lo.':
        'Click a point in the left plot to remove it from the fit; click again to include it.',
    'Incluir todos':
        'Include all',
    'Volta a usar no ajuste todos os pontos excluídos com clique.':
        'Uses again in the fit all points excluded by clicking.',
    'Salvar de novo':
        'Save again',
    'Grava CSV e PNG novos (sufixo _editado) com o ajuste, os pontos excluídos e a\ncalibração atuais. O arquivo salvo no fim da varredura não é alterado.':
        'Writes new CSV and PNG files (suffix _editado) with the current fit, excluded points and\ncalibration. The file saved at the end of the sweep is not changed.',
    'Diagnóstico':
        'Diagnostics',
    'Varredura em frequência: separa o sinal fotoacústico (S ∝ f^-n, fase constante) de um fundo plano\n(luz chegando ao microfone, chiado do driver, acoplamento elétrico), ajustando amplitude e fase juntas,\ncom o passa-alta do microfone, o atraso do sistema e a ressonância da célula. Desenha as componentes\n(vermelho: fotoacústico; roxo: fundo; preto: soma) e diz o que encontrou. Leva alguns segundos.':
        'Frequency sweep: separates the photoacoustic signal (S ∝ f^-n, constant phase) from a flat background\n(light reaching the microphone, driver whine, electrical coupling), fitting amplitude and phase together,\nwith the microphone high-pass, the system delay and the cell resonance. Draws the components\n(red: photoacoustic; purple: background; black: sum) and reports what it found. Takes a few seconds.',
    'Normalizar pelo OPT101':
        'Normalize by the OPT101',
    'Varredura em frequência. Marcado: S = R_INMP441 / R_OPT101 e Δφ = φ_INMP441 − φ_OPT101 (desconta a\nvariação da potência e da fase da luz com a frequência). Desmarcado: só o INMP441 (R e fase brutos).\nFitar padrão, gerar calibração e aplicar a calibração pedem a normalização. Os CSV guardam sempre os dois sensores.':
        'Frequency sweep. Checked: S = R_INMP441 / R_OPT101 and Δφ = φ_INMP441 − φ_OPT101 (removes the\nchange of light power and phase with frequency). Unchecked: INMP441 only (raw R and phase).\nStandard fit, generating and applying the calibration require normalization. The CSV files always keep both sensors.',
    'Mostrar sinais de cada sensor':
        "Show each sensor's signals",
    'Mostra abaixo, além da curva principal, a amplitude R e a fase de cada sensor\n(INMP441 e OPT101) em função da variável da varredura.':
        'Shows below the main curve the amplitude R and the phase of each sensor\n(INMP441 and OPT101) as a function of the sweep variable.',
    'Amplitude de cada sensor (R ÷ mediana da varredura)':
        'Amplitude of each sensor (R ÷ sweep median)',
    'R relativo':
        'Relative R',
    'Fase de cada sensor (desenrolada)':
        'Phase of each sensor (unwrapped)',
    'fase (graus)':
        'phase (degrees)',
    'Sem dados: escolha uma varredura acima e clique em ▶ Varredura.':
        'No data: choose a sweep above and click ▶ Sweep.',
    'Calibração do microfone ▸':
        'Microphone calibration ▸',
    'Mostra ou esconde a calibração do microfone.\nEscolha a referência (padrão de calibração): ela define a curva teórica esperada e a célula (OPC ou câmara).\nCom o painel fechado, "Fitar padrão" não é aplicado.':
        'Shows or hides the microphone calibration.\nChoose the reference (calibration standard): it sets the expected theoretical curve and the cell (OPC or chamber).\nWith the panel closed, "Standard fit" is not applied.',
    'Calibração do microfone (com uma referência de comportamento conhecido)':
        'Microphone calibration (with a reference of known behavior)',
    '<b>Referência:</b>':
        '<b>Reference:</b>',
    'Padrão usado na calibração. Cada um tem a sua curva teórica (S ∝ f⁻ⁿ, fase constante)\ne vale numa configuração da célula (escolhida automaticamente em "Célula", no topo).':
        'Standard used in the calibration. Each one has its theoretical curve (S ∝ f⁻ⁿ, constant phase)\nand holds in one cell configuration (chosen automatically in "Cell", at the top).',
    'Espessura da referência (micrômetro). No modo OPC define f₁ = α/(πL²), o limite da\nfolha termicamente fina; dentro da câmara é só informativa (opaca: f⁻¹ nos dois regimes).':
        'Reference thickness (micrometer). In OPC mode it sets f₁ = α/(πL²), the limit of the\nthermally thin foil; inside the chamber it is informative only (opaque: f⁻¹ in both regimes).',
    'Difusividade térmica da referência. Alumínio puro ≈ 0,97 cm²/s; ligas de folha\n(1235, 8079) ≈ 0,9; liga 6061 ≈ 0,65 cm²/s.':
        'Thermal diffusivity of the reference. Pure aluminum ≈ 0.97 cm²/s; foil alloys\n(1235, 8079) ≈ 0.9; 6061 alloy ≈ 0.65 cm²/s.',
    'Expoente esperado da referência personalizada: S ∝ f⁻ⁿ com fase constante.':
        'Expected exponent of the custom reference: S ∝ f⁻ⁿ with constant phase.',
    'Monte a referência como no esquema, rode a <b>Varredura</b> e clique em <b>Gerar curva de calibração</b>. Para conferir: monte outra referência, escolha-a acima, meça com <b>Usar</b> marcado e clique em <b>Verificar</b>.':
        'Set up the reference as in the diagram, run the <b>Sweep</b> and click <b>Generate calibration curve</b>. To check it: set up another reference, choose it above, measure with <b>Use</b> checked and click <b>Verify</b>.',
    'Avançado ▸':
        'Advanced ▸',
    'Correção do polo do OPT101: só é necessária se você trocar o resistor de\nrealimentação do OPT101 entre a calibração e a medida.':
        'OPT101 pole correction: only needed if you change the OPT101 feedback\nresistor between the calibration and the measurement.',
    'Polo do OPT101, que depende do resistor de realimentação. É descontado do OPT101 antes de S e Δφ:\nfase + atan(2π·f·τ) e amplitude × √(1 + (2π·f·τ)²).\nNão precisa ser calibrado no uso normal: com o mesmo resistor na calibração e na medida, a calibração\ndo microfone já absorve esse polo. Preencha só se trocar o resistor (0 = sem correção), e então\ngere a calibração de novo com o mesmo valor.\nMedir…: compara a varredura em frequência atual com outra já salva (mesma luz, outro resistor) e preenche τ.\nO atraso do driver/laser não entra aqui: é comum ao microfone e se cancela em Δφ.':
        'OPT101 pole, which depends on the feedback resistor. It is removed from the OPT101 before S and Δφ:\nphase + atan(2π·f·τ) and amplitude × √(1 + (2π·f·τ)²).\nNo calibration needed in normal use: with the same resistor in the calibration and the measurement, the\nmicrophone calibration already absorbs this pole. Fill it in only if you change the resistor (0 = no correction), and then\ngenerate the calibration again with the same value.\nMeasure…: compares the current frequency sweep with another saved one (same light, another resistor) and fills in τ.\nThe driver/laser delay does not belong here: it is shared with the microphone and cancels in Δφ.',
    'τ do sensor OPT101:':
        'OPT101 sensor τ:',
    '0 (sem correção)':
        '0 (no correction)',
    'Medir…':
        'Measure…',
    'Só se trocar o resistor do OPT101 entre a calibração e a medida; com o mesmo resistor, deixe 0.':
        'Only if you change the OPT101 resistor between the calibration and the measurement; with the same resistor, leave 0.',
    'Gerar curva de calibração':
        'Generate calibration curve',
    'Disponível depois de uma varredura em frequência da referência, com "Usar" (linha superior) desmarcado.\n\nEm teoria a referência dá S ∝ f⁻ⁿ (n da referência escolhida); então M(f) = S(f)·fⁿ é a resposta relativa\ndo sistema microfone + célula, normalizada pela faixa plana. A fase do sistema é Δφ(f) − φ0, com φ0 a fase\nmédia na faixa plana. Entram todos os pontos com SNR suficiente (inclusive a ressonância).\nO arquivo registra a referência, a célula e se o comportamento foi verificado.\nSalva CSV e PNG na pasta Medidas (prefixo CAL_). Nada é guardado sem este clique: guarde só as\ncalibrações que valerem a pena (curva limpa, repetível).':
        'Available after a frequency sweep of the reference, with "Use" (top row) unchecked.\n\nIn theory the reference gives S ∝ f⁻ⁿ (n of the chosen reference); so M(f) = S(f)·fⁿ is the relative response\nof the microphone + cell system, normalized by the flat range. The system phase is Δφ(f) − φ0, with φ0 the mean\nphase over the flat range. All points with enough SNR are included (resonance too).\nThe file records the reference, the cell and whether the behavior was verified.\nSaves CSV and PNG in the Medidas folder (prefix CAL_). Nothing is stored without this click: keep only the\ncalibrations worth keeping (clean, repeatable curve).',
    'Faixa plana ±':
        'Flat range ±',
    'Tolerância para a faixa em que a sensibilidade do microfone é constante (±1 dB ≈ ±12 %). A calibração procura o maior trecho de frequências dentro dela.':
        'Tolerance for the range where the microphone sensitivity is constant (±1 dB ≈ ±12 %). The calibration looks for the widest stretch of frequencies within it.',
    'Verificar com esta medida':
        'Verify with this measurement',
    'Com a calibração em uso ("Usar"), meça uma SEGUNDA referência (escolha-a em Referência: ex. calibrou com o\nnegro de fumo, confira com a fita preta). Corrigida, ela deve seguir f⁻ⁿ com fase constante numa faixa\nde pelo menos uma década (|n − n esperado| ≤ ':
        'With the calibration in use ("Use"), measure a SECOND reference (choose it in Reference: e.g. calibrated with\ncarbon black, check with the black tape). Once corrected, it should follow f⁻ⁿ with constant phase over a range\nof at least one decade (|n − expected n| ≤ ',
    '° rms).\nSe seguir, a calibração passa a "verificada" e a faixa fica registrada no arquivo dela.':
        '° rms).\nIf it does, the calibration becomes "verified" and the range is recorded in its file.',
    'Ajuste ▸':
        'Fit ▸',
    'Ajusta a varredura em frequência (magnitude, fase ou as duas) com modelos\nfísicos de célula aberta. Use com a calibração aplicada ("Usar").':
        'Fits the frequency sweep (magnitude, phase or both) with physical\nopen-cell models. Use with the calibration applied ("Use").',
    'Ajuste da varredura em frequência':
        'Frequency sweep fit',
    'Nenhum':
        'None',
    'Ajustar:':
        'Fit:',
    'Fase':
        'Phase',
    'Fase e magnitude':
        'Phase and magnitude',
    'Fase: em geral a grandeza mais robusta (não depende da escala da luz nem da absorção da amostra).\nMagnitude: sensível a desvios de amplitude da referência e da calibração.\nNa lei de potência só a magnitude é ajustada (o modelo tem fase constante).':
        'Phase: usually the most robust quantity (independent of the light scale and of the sample absorption).\nMagnitude: sensitive to amplitude deviations of the reference and of the calibration.\nIn the power law only the magnitude is fitted (the model has constant phase).',
    'Espessura L:':
        'Thickness L:',
    'não informada':
        'not given',
    'Espessura da amostra (meça com micrômetro). Com ela, a difusividade térmica sai\nde f1: α = π·f1·L². Referências: Ti puro ≈ 9,3e-6 m²/s; Ti-6Al-4V ≈ 2,9e-6 m²/s;\naço inox ≈ 4e-6 m²/s; alumínio ≈ 9,7e-5 m²/s; cobre ≈ 1,1e-4 m²/s.':
        'Sample thickness (measure with a micrometer). With it, the thermal diffusivity comes\nfrom f1: α = π·f1·L². References: pure Ti ≈ 9.3e-6 m²/s; Ti-6Al-4V ≈ 2.9e-6 m²/s;\nstainless steel ≈ 4e-6 m²/s; aluminum ≈ 9.7e-5 m²/s; copper ≈ 1.1e-4 m²/s.',
    'n esperado:':
        'Expected n:',
    'Expoente esperado da amostra: 1 (opaca na câmara) ou 1,5 (folha fina em OPC).':
        'Expected exponent of the sample: 1 (opaque in the chamber) or 1.5 (thin foil in OPC).',
    'Faixa: de':
        'Range: from',
    'Limita o ajuste do modelo a esta faixa de frequência (os outros pontos continuam no gráfico).\nUse quando o modelo só vale numa região da varredura. Pontos excluídos com clique também\nficam fora. A curva verde é desenhada só na faixa ajustada.':
        'Limits the model fit to this frequency range (the other points stay on the plot).\nUse it when the model only holds in one region of the sweep. Points excluded by clicking also\nstay out. The green curve is drawn only over the fitted range.',
    'início':
        'start',
    'Marcar pico (2 cliques)':
        'Mark peak (2 clicks)',
    'Para o modelo de ressonância: clique no gráfico da esquerda um pouco abaixo e um pouco\nacima do pico; os dois cliques preenchem a Faixa. Com a Faixa vazia (início/fim),\no pico é achado sozinho.':
        'For the resonance model: click in the left plot a little below and a little\nabove the peak; the two clicks fill in the Range. With the Range empty (start/end),\nthe peak is found automatically.',
    'Modo Duplo':
        'Dual Mode',
    'τ dos dois lock-ins durante a varredura (integração longa): espera 9τ e faz a média por 1τ em\ncada ponto. É o mesmo τ do INMP441: mudar aqui muda lá e vice-versa (e na outra varredura).':
        'τ of both lock-ins during the sweep (long integration): waits 9τ and averages for 1τ at\neach point. It is the same τ as the INMP441: changing it here changes it there and vice versa (and in the other sweep).',
    ' &nbsp; <b>Célula:</b> ':
        ' &nbsp; <b>Cell:</b> ',
    'Termine ou cancele a varredura em andamento antes de carregar os parâmetros.':
        'Finish or cancel the running sweep before loading the parameters.',
    'Parâmetros de calibração carregados (PWM ':
        'Calibration parameters loaded (PWM ',
    ' %): confira o %ADC do OPT101 antes de rodar a varredura.':
        ' %): check the OPT101 %ADC before running the sweep.',
    'Fotoacústico × intensidade óptica':
        'Photoacoustic × optical intensity',
    'INMP441 R (escala completa 24 bits)':
        'INMP441 R (24-bit full scale)',
    'OPT101 R (u.a., ∝ intensidade)':
        'OPT101 R (a.u., ∝ intensity)',
    'Calibração: intensidade óptica × PWM':
        'Calibration: optical intensity × PWM',
    'OPT101 R (u.a.)':
        'OPT101 R (a.u.)',
    'PWM do laser (%)':
        'Laser PWM (%)',
    '  +  fase (eixo da direita)':
        '  +  phase (right axis)',
    'Sinal fotoacústico normalizado (INMP441 R / OPT101 R)':
        'Normalized photoacoustic signal (INMP441 R / OPT101 R)',
    'Diferença de fase INMP441 − OPT101':
        'Phase difference INMP441 − OPT101',
    'Δφ (graus)':
        'Δφ (degrees)',
    'Sinal fotoacústico sem normalização (INMP441 R)':
        'Photoacoustic signal without normalization (INMP441 R)',
    'R_INMP441 (escala completa 24 bits)':
        'R_INMP441 (24-bit full scale)',
    'Fase do INMP441 (sem descontar o OPT101)':
        'INMP441 phase (OPT101 not removed)',
    'φ_INMP441 (graus)':
        'φ_INMP441 (degrees)',
    ' (mediana R = ':
        ' (median R = ',
    'Tempo estimado: ':
        'Estimated time: ',
    ' pontos':
        ' points',
    'Espere a varredura atual terminar (ou cancele) antes de refinar.':
        'Wait for the current sweep to finish (or cancel it) before refining.',
    'Rode (ou abra) uma varredura em frequência antes de refinar a ressonância.':
        'Run (or open) a frequency sweep before refining the resonance.',
    'Não achei um pico de ressonância acima de 250 Hz nesta varredura.':
        'No resonance peak found above 250 Hz in this sweep.',
    'sem pico claro acima de 250 Hz':
        'no clear peak above 250 Hz',
    'pelo pico':
        'from the peak',
    'ajuste: Q = ':
        'fit: Q = ',
    'Os pontos em volta da ressonância já foram medidos.':
        'The points around the resonance have already been measured.',
    'Refino da ressonância: +':
        'Resonance refinement: +',
    ' pontos de ':
        ' points from ',
    ' Hz em torno de f0 = ':
        ' Hz around f0 = ',
    ' Hz (largura ':
        ' Hz (width ',
    '); medidos com ':
        '); measured with ',
    'PWM do laser em ':
        'Laser PWM at ',
    ' % (recomendado ':
        ' % (recommended ',
    ' %, mais sinal).':
        ' %, more signal).',
    '): desloca a fase':
        '): shifts the phase',
    'Filtro de 60 Hz ligado (':
        '60 Hz filter on (',
    ' de um lock-in e contamina Δφ.':
        ' of one lock-in and contaminates Δφ.',
    ' e a amplitude perto de 60 Hz.':
        ' and the amplitude near 60 Hz.',
    '"Usar" da calibração marcado: a calibração nova precisa dos dados brutos.':
        'Calibration "Use" checked: the new calibration needs the raw data.',
    'Varredura da calibração':
        'Calibration sweep',
    'Antes de calibrar, confira:':
        'Before calibrating, check:',
    'Corrigir e rodar':
        'Fix and run',
    'Rodar assim':
        'Run as is',
    'Cancelar':
        'Cancel',
    ' %, filtros de 60 Hz desligados e calibração desmarcada: confira o %ADC do OPT101.':
        ' %, 60 Hz filters off and calibration unchecked: check the OPT101 %ADC.',
    'Varredura do Modo Duplo cancelada pelo usuário.':
        'Dual Mode sweep cancelled by the user.',
    'As varreduras do Modo Duplo precisam do OPT101 no Modo Lock-In.':
        'Dual Mode sweeps need the OPT101 in Lock-In mode.',
    'Já existe uma varredura em andamento.':
        'A sweep is already running.',
    '⏹ Cancelar':
        '⏹ Cancel',
    'Restante: ':
        'Remaining: ',
    ' | estabilizando os lock-ins (':
        ' | settling the lock-ins (',
    ' | medindo (':
        ' | measuring (',
    'Modo Duplo: sem dados em ':
        'Dual Mode: no data at ',
    ' (OPT101 e INMP441 conectados?)':
        ' (OPT101 and INMP441 connected?)',
    'O ajuste com modelos vale só para a varredura em frequência.':
        'Model fitting only applies to the frequency sweep.',
    '<span style="color:#606060;">OPT101 corrigido pelo τ do sensor = ':
        '<span style="color:#606060;">OPT101 corrected by the sensor τ = ',
    ' µs (Calibração do microfone → Avançado).</span>':
        ' µs (Microphone calibration → Advanced).</span>',
    '<span style="color:#606060;">Calibração não aplicada: ela vale para o sinal normalizado (marque "Normalizar pelo OPT101").</span>':
        '<span style="color:#606060;">Calibration not applied: it holds for the normalized signal (check "Normalize by the OPT101").</span>',
    '<b>Calibração INMP441:</b> nenhuma calibração válida selecionada na linha superior.':
        '<b>INMP441 calibration:</b> no valid calibration selected on the top row.',
    '<b>Calibração INMP441:</b> ':
        '<b>INMP441 calibration:</b> ',
    ' ponto(s) fora da faixa ':
        ' point(s) outside the range ',
    ' Hz ocultados)':
        ' Hz hidden)',
    '<br><span style="color:#d00000;">⚠ Calibração antiga: feita antes do firmware com o marcador de modulação corrigido (23/10/2026 14:43) ou com a correção pelo τ efetivo. A fase do sistema não é comparável (td ~100 µs maior); gere uma calibração nova.</span>':
        '<br><span style="color:#d00000;">⚠ Old calibration: made before the firmware with the corrected modulation marker (2026-10-23 14:43) or with the effective-τ correction. The system phase is not comparable (td ~100 µs larger); generate a new calibration.</span>',
    '<br><span style="color:#d00000;">⚠ A calibração foi gerada ':
        '<br><span style="color:#d00000;">⚠ The calibration was generated ',
    ' a correção pelo τ do sensor, e esta varredura está ':
        ' the sensor τ correction, and this sweep is ',
    ' ela: S e a fase do sistema ficam inconsistentes.</span>':
        ' it: S and the system phase become inconsistent.</span>',
    '<br><span style="color:#d00000;">⚠ A calibração foi feita na configuração ':
        '<br><span style="color:#d00000;">⚠ The calibration was made in the configuration ',
    ' e a célula escolhida é ':
        ' and the chosen cell is ',
    ': a acústica muda e a correção não vale. Gere uma calibração nesta configuração.</span>':
        ': the acoustics change and the correction does not hold. Generate a calibration in this configuration.</span>',
    '<br><span style="color:#d00000;">⚠ A ressonância desta medida (':
        '<br><span style="color:#d00000;">⚠ The resonance of this measurement (',
    ') difere da calibração (':
        ') differs from the calibration (',
    '): perto dela a correção não vale. A amostra tem altura diferente da referência? Use amostras da mesma altura ou ignore a região da ressonância.</span>':
        '): near it the correction does not hold. Does the sample have a different height from the reference? Use samples of the same height or ignore the resonance region.</span>',
    '<br><span style="color:#d00000;">⚠ Calibração ainda não verificada experimentalmente: confira com uma segunda referência ("Verificar com esta medida", no painel Calibração).</span>':
        '<br><span style="color:#d00000;">⚠ Calibration not yet verified experimentally: check it with a second reference ("Verify with this measurement", in the Calibration panel).</span>',
    'Calibração: marque "Normalizar pelo OPT101" (a referência é comparada com o sinal normalizado).':
        'Calibration: check "Normalize by the OPT101" (the reference is compared with the normalized signal).',
    'Calibração: são necessários pelo menos 4 pontos com SNR suficiente.':
        'Calibration: at least 4 points with enough SNR are needed.',
    'sistema plano (±':
        'flat system (±',
    'nenhuma faixa com o sistema plano (±':
        'no range with a flat system (±',
    '<b>Calibração em uso</b> (':
        '<b>Calibration in use</b> (',
    '): os dados já estão corrigidos. Para guardar uma calibração nova, desmarque "Usar".':
        '): the data are already corrected. To store a new calibration, uncheck "Use".',
    '<b>Referência ':
        '<b>Reference ',
    '</sup>): a calibração guarda M = S·f<sup>':
        '</sup>): the calibration stores M = S·f<sup>',
    ' pontos com SNR suficiente), normalizada onde o ':
        ' points with enough SNR), normalized where the ',
    ' (linha laranja, f<sup>−':
        ' (orange line, f<sup>−',
    '</sup>). O resto da forma é a resposta da célula, que a calibração corrige.':
        '</sup>). The rest of the shape is the cell response, which the calibration corrects.',
    ' ponto(s) excluído(s) do ajuste com clique: ':
        ' point(s) excluded from the fit by clicking: ',
    '\nReferência: ':
        '\nReference: ',
    '; célula: ':
        '; cell: ',
    '; NÃO verificada':
        '; NOT verified',
    '(nenhuma calibração na pasta Medidas)':
        '(no calibration in the Medidas folder)',
    'Nenhuma calibração encontrada (CAL_*microfone_*.csv na pasta Medidas).\nGere uma na aba Modo Duplo: varredura em frequência → Fitar padrão → Gerar curva de calibração.':
        'No calibration found (CAL_*microfone_*.csv in the Medidas folder).\nGenerate one in the Dual Mode tab: frequency sweep → Standard fit → Generate calibration curve.',
    '\nA lista é relida da pasta Medidas ao abrir.':
        '\nThe list is reread from the Medidas folder when opened.',
    'Faixa plana (±':
        'Flat range (±',
    ' dB): não encontrada (normalizada pela mediana)':
        ' dB): not found (normalized by the median)',
    '<span style="color:#b35c00;">não verificada</span>':
        '<span style="color:#b35c00;">not verified</span>',
    'Sensibilidade relativa do microfone + célula (M = S·f<sup>':
        'Relative sensitivity of microphone + cell (M = S·f<sup>',
    ', célula ':
        ', cell ',
    'M(f) relativa':
        'Relative M(f)',
    'Fase do sistema (Δφ − φ0)':
        'System phase (Δφ − φ0)',
    'Calibração do microfone salva: ':
        'Microphone calibration saved: ',
    '. Confira com uma segunda referência ("Verificar com esta medida").':
        '. Check it with a second reference ("Verify with this measurement").',
    'Calibração salva: ':
        'Calibration saved: ',
    'Erro ao salvar a calibração: ':
        'Error saving the calibration: ',
    'Calibração do microfone':
        'Microphone calibration',
    'São necessários pelo menos 5 pontos válidos.':
        'At least 5 valid points are needed.',
    'não segue':
        'does not follow',
    ' década(s); mínimo 1): n = ':
        ' decade(s); minimum 1): n = ',
    'varredura atual':
        'current sweep',
    '<span style="color:#b35c00;">Mesma referência da calibração (':
        '<span style="color:#b35c00;">Same reference as the calibration (',
    '): isso mede só a repetibilidade (':
        '): this only measures the repeatability (',
    '° rms). Para verificar, use outra referência.</span>':
        '° rms). To verify, use another reference.</span>',
    'aprovada - ':
        'passed - ',
    'reprovada - ':
        'failed - ',
    'Não foi possível gravar o resultado na calibração: ':
        'Could not write the result into the calibration: ',
    '<span style="color:#2e7d32;"><b>✓ Calibração verificada</b> com ':
        '<span style="color:#2e7d32;"><b>✓ Calibration verified</b> with ',
    '<span style="color:#d00000;"><b>⚠ Não passou</b> com ':
        '<span style="color:#d00000;"><b>⚠ Did not pass</b> with ',
    '. As duas referências discordam: uma delas não é ideal nesta faixa ou a montagem mudou (altura, vedação, posição do feixe). Refaça a medida ou use uma terceira referência para decidir qual vale.</span>':
        '. The two references disagree: one of them is not ideal in this range or the setup changed (height, sealing, beam position). Repeat the measurement or use a third reference to decide which one holds.</span>',
    'Avançado ▾':
        'Advanced ▾',
    'Medir τ do sensor: rode antes uma varredura em frequência do Modo Duplo com o resistor atual.':
        'Measure sensor τ: first run a Dual Mode frequency sweep with the current resistor.',
    'Varredura de referência (mesma luz, outro resistor)':
        'Reference sweep (same light, another resistor)',
    'Modo Duplo em frequência (*DUPLO_freq_*.csv)':
        'Dual Mode frequency sweep (*DUPLO_freq_*.csv)',
    'Medir τ do sensor: arquivo inválido (':
        'Measure sensor τ: invalid file (',
    'Medir τ do sensor: menos de 4 frequências em comum, ou o ajuste não convergiu.':
        'Measure sensor τ: fewer than 4 common frequencies, or the fit did not converge.',
    ' — referência: ':
        ' — reference: ',
    'Varredura casada em PWM ':
        'Matched PWM sweep ',
    ' pontos), modulação ':
        ' points), modulation ',
    'Varredura em frequência ':
        'Frequency sweep ',
    ' pontos), PWM ':
        ' points), PWM ',
    'Varredura do Modo Duplo salva de novo: ':
        'Dual Mode sweep saved again: ',
    'Salva de novo: ':
        'Saved again: ',
    'Varredura do Modo Duplo concluída: ':
        'Dual Mode sweep finished: ',
    'Concluída: ':
        'Finished: ',
    'Erro ao salvar a varredura do Modo Duplo: ':
        'Error saving the Dual Mode sweep: ',
    '▶ Varredura':
        '▶ Sweep',
    'Tempo estimado: --:--':
        'Estimated time: --:--',
    'Varreduras ▾':
        'Sweeps ▾',
    'Calibração ':
        'Calibration ',
    'Varredura ':
        'Sweep ',
    'Termine ou cancele a varredura em andamento antes de abrir outra.':
        'Finish or cancel the running sweep before opening another.',
    'Abrir varredura do Modo Duplo':
        'Open Dual Mode sweep',
    'Varreduras do Modo Duplo (*DUPLO*.csv);;Todos os CSV (*.csv)':
        'Dual Mode sweeps (*DUPLO*.csv);;All CSV files (*.csv)',
    'Abrir varredura':
        'Open sweep',
    'Não foi possível abrir ':
        'Could not open ',
    'em frequência':
        'frequency',
    'casada em PWM':
        'matched PWM',
    'Varredura aberta (':
        'Opened sweep (',
    ' pontos): ':
        ' points): ',
    'Ajuste ':
        'Fit ',
    'Escolha um modelo para ajustar à varredura em frequência.':
        'Choose a model to fit to the frequency sweep.',
    '<b>Diagnóstico:</b> são necessários pelo menos 12 pontos cobrindo uma década de frequência.':
        '<b>Diagnostics:</b> at least 12 points covering one decade of frequency are needed.',
    'Modelo (soma)':
        'Model (sum)',
    'Fotoacústico (∝ f⁻ⁿ, n = ':
        'Photoacoustic (∝ f⁻ⁿ, n = ',
    'Fundo plano (não fotoacústico)':
        'Flat background (not photoacoustic)',
    '<br><span style="color:#606060;">Sem calibração aplicada, a resposta da célula + microfone entra no ajuste e parte do "fundo" pode ser dela. Para separar componentes da amostra, aplique a calibração.</span>':
        '<br><span style="color:#606060;">Without the calibration applied, the cell + microphone response enters the fit and part of the "background" may come from it. To separate sample components, apply the calibration.</span>',
    '<b>Diagnóstico</b> &nbsp; ':
        '<b>Diagnostics</b> &nbsp; ',
    'Marcar pico: clique no gráfico da esquerda um pouco abaixo e depois um pouco acima do pico.':
        'Mark peak: click in the left plot a little below and then a little above the peak.',
    'Marcar pico: ':
        'Mark peak: ',
    ' Hz; agora clique do outro lado do pico.':
        ' Hz; now click on the other side of the peak.',
    'Faixa da ressonância: ':
        'Resonance range: ',
    'Ajuste com modelo: são necessários pelo menos ':
        'Model fit: at least ',
    ' pontos válidos.':
        ' valid points are needed.',
    'Ajuste com modelo: não convergiu.':
        'Model fit: did not converge.',
    'fase e magnitude':
        'phase and magnitude',
    '</b> (ajuste da ':
        '</b> (fit of the ',
    ' (abaixo da quebra)':
        ' (below the break)',
    ' (acima)':
        ' (above)',
    '<b>quebra fb = ':
        '<b>break fb = ',
    'expoente fixo n = ':
        'fixed exponent n = ',
    ' (sem parâmetro de forma)':
        ' (no shape parameter)',
    ' µm; sem incluir o erro de L, que conta em dobro)':
        ' µm; not including the error in L, which counts double)',
    'informe L para obter α':
        'give L to get α',
    'resíduo rms da magnitude ':
        'magnitude residual rms ',
    'resíduo rms da fase ':
        'phase residual rms ',
    '"Usar" desmarcado':
        '"Use" unchecked',
    'sinal sem normalização pelo OPT101':
        'signal not normalized by the OPT101',
    '<br><span style="color:#d00000;">⚠ Sem calibração aplicada (':
        '<br><span style="color:#d00000;">⚠ No calibration applied (',
    '): magnitude e fase incluem a resposta do microfone/célula e o atraso do sistema.</span>':
        '): magnitude and phase include the microphone/cell response and the system delay.</span>',
    'Faixa com S ∝ f⁻ⁿ: são necessários pelo menos 5 pontos válidos na faixa.':
        'Range with S ∝ f⁻ⁿ: at least 5 valid points in the range are needed.',
    ', desvio de f<sup>−':
        ', deviation from f<sup>−',
    ' dB rms, fase ± ':
        ' dB rms, phase ± ',
    ' pontos)':
        ' points)',
    '</sup> de ':
        '</sup> from ',
    ' década(s)): ':
        ' decade(s)): ',
    '<span style="color:#b35c00;"><b>Nenhuma faixa segue f<sup>−':
        '<span style="color:#b35c00;"><b>No range follows f<sup>−',
    '</sup></b> (critério: n ± 0,15, ≤ 1,5 dB rms, fase ± 10° rms). Mais próxima: ':
        '</sup></b> (criterion: n ± 0.15, ≤ 1.5 dB rms, phase ± 10° rms). Closest: ',
    '<br><span style="color:#d00000;">⚠ Sem calibração aplicada: a forma inclui a resposta do microfone/célula.</span>':
        '<br><span style="color:#d00000;">⚠ No calibration applied: the shape includes the microphone/cell response.</span>',
    'Ressonância: nenhum pico claro encontrado (ou menos de 6 pontos na faixa). Use "Marcar pico" e clique dos dois lados dele.':
        'Resonance: no clear peak found (or fewer than 6 points in the range). Use "Mark peak" and click on both sides of it.',
    'Ressonância: o ajuste não convergiu (são necessários pelo menos 6 pontos na faixa).':
        'Resonance: the fit did not converge (at least 6 points in the range are needed).',
    'pico achado automaticamente':
        'peak found automatically',
    'faixa escolhida':
        'chosen range',
    'largura (f0/Q) = ':
        'width (f0/Q) = ',
    'ganho do pico sobre o fundo = ':
        'peak gain over the background = ',
    ' dB (máximo em ':
        ' dB (maximum at ',
    '°; atraso τ = ':
        '°; delay τ = ',
    '<br><span style="color:#b35c00;">Poucos pontos no pico: para f0 e Q confiáveis, faça uma varredura linear em volta dele (passo ≤ largura/5).</span>':
        '<br><span style="color:#b35c00;">Few points on the peak: for reliable f0 and Q, run a linear sweep around it (step ≤ width/5).</span>',
    '<br><span style="color:#d00000;">⚠ Com a calibração aplicada ("Usar"), a ressonância da célula é removida dos dados: desmarque "Usar" para medir a ressonância da célula.</span>':
        '<br><span style="color:#d00000;">⚠ With the calibration applied ("Use"), the cell resonance is removed from the data: uncheck "Use" to measure the cell resonance.</span>',
    'Calibração do microfone ':
        'Microphone calibration ',
    'Passo:':
        'Step:',
    "<span style='color:#1a7f1a;'>●</span> STM32 conectado (":
        "<span style='color:#1a7f1a;'>●</span> STM32 connected (",
    "<span style='color:#1f5fbf;'>●</span> Simulação (sem STM32)":
        "<span style='color:#1f5fbf;'>●</span> Simulation (no STM32)",
    "<span style='color:#d07000;'>●</span> STM32 desconectado, procurando...":
        "<span style='color:#d07000;'>●</span> STM32 disconnected, searching...",
    'Nenhuma porta do STM32 (USB VID 0x0483) encontrada.':
        'No STM32 port (USB VID 0x0483) found.',
    'frequência':
        'frequency',
    ': ponto ':
        ': point ',
    ', restante ':
        ', remaining ',
    'Modo Duplo em ':
        'Dual Mode in ',
    'Pré: -':
        'Pre: -',
    'Teste de resolução da sobreamostragem':
        'Oversampling resolution test',
    'Deixe o sinal <b>estável</b>: laser desligado (PWM 0 %) ou luz constante, sem mexer na montagem. A interface grava as amostras cruas do ADC (200 kS/s) e calcula o ruído das médias de N amostras (desvio de Allan, em LSB do ADC de 12 bits). Enquanto os pontos seguem a reta tracejada (1/√N), a sobreamostragem está entregando resolução de verdade.':
        'Keep the signal <b>steady</b>: laser off (PWM 0 %) or constant light, without touching the setup. The interface records the raw ADC samples (200 kS/s) and computes the noise of averages of N samples (Allan deviation, in LSB of the 12-bit ADC). While the points follow the dashed line (1/√N), oversampling is delivering real resolution.',
    'Duração (s):':
        'Duration (s):',
    'Medir':
        'Measure',
    'Salvar CSV e PNG':
        'Save CSV and PNG',
    'N (amostras por média = OSR)':
        'N (samples per average = OSR)',
    'Ruído σ (LSB do ADC de 12 bits)':
        'Noise σ (LSB of the 12-bit ADC)',
    'OSR em uso':
        'OSR in use',
    'Código do ADC (12 bits)':
        'ADC code (12 bits)',
    'Amostras':
        'Samples',
    'Histograma dos códigos crus':
        'Histogram of the raw codes',
    'Sem dados: conecte o STM32 ou ligue a simulação.':
        'No data: connect the STM32 or turn on the simulation.',
    'Gravando...':
        'Recording...',
    'Gravando... ':
        'Recording... ',
    'Os dados não chegaram a tempo (STM32 desconectado?).':
        'The data did not arrive in time (STM32 disconnected?).',
    'Houve perda de amostras no USB durante a gravação: o resultado não vale. Meça de novo.':
        'Samples were lost on USB during the recording: the result is not valid. Measure again.',
    'Erro na análise: ':
        'Analysis error: ',
    ' amostras (':
        ' samples (',
    ' s) sem perdas, média = código ':
        ' s) without losses, mean = code ',
    '<table border="1" cellspacing="0" cellpadding="3"><tr><th>N</th><th>kS/s</th><th>σ (LSB)</th><th>ideal</th><th>ganho (bit)</th><th>ideal (bit)</th><th>bits efetivos</th></tr>':
        '<table border="1" cellspacing="0" cellpadding="3"><tr><th>N</th><th>kS/s</th><th>σ (LSB)</th><th>ideal</th><th>gain (bit)</th><th>ideal (bit)</th><th>effective bits</th></tr>',
    '<br><small>Bits efetivos = 12 − log₂(σ·√12): resolução de um conversor ideal com o mesmo ruído. Linhas em cinza: N fora das opções de sobreamostragem (mostram a tendência para médias mais longas, como as do lock-in).</small>':
        '<br><small>Effective bits = 12 − log₂(σ·√12): resolution of an ideal converter with the same noise. Gray rows: N outside the oversampling options (they show the trend for longer averages, like those of the lock-in).</small>',
    'Salvo: ':
        'Saved: ',
    'Erro ao salvar: ':
        'Error saving: ',
    'A sobreamostragem não pode mudar durante uma varredura.':
        'Oversampling cannot change during a sweep.',
    'Sobreamostragem ':
        'Oversampling ',
    ' kS/s no OPT101 (lock-in, osciloscópio, FFT e Valor Médio). O INMP441 não muda.':
        ' kS/s on the OPT101 (lock-in, oscilloscope, FFT and Average). The INMP441 does not change.',
    'Passa-Altas (Hz):':
        'High-pass (Hz):',
    'Não há dados para ajustar.':
        'No data to fit.',
    'Poucos pontos na janela selecionada (laser Off).':
        'Too few points in the selected window (laser Off).',
    'Poucos pontos na janela selecionada (laser On).':
        'Too few points in the selected window (laser On).',
    'Sem ajuste.':
        'No fit.',
    'Falha no ajuste: ':
        'Fit failed: ',
    'Termine ou cancele a varredura em andamento antes de finalizar o experimento.':
        'Finish or cancel the running sweep before finishing the experiment.',
    'Nenhum arquivo foi salvo desde o início da sessão (ou desde o último "Finalizar experimento").':
        'No file has been saved since the session started (or since the last "Finish experiment").',
    'Erro ao criar o ZIP:\n':
        'Error creating the ZIP:\n',
    'Experimento finalizado':
        'Experiment finished',
    ' arquivo(s) compactado(s) em:\n':
        ' file(s) packed into:\n',
    '\n\nOs originais continuam na pasta Medidas. Os próximos arquivos salvos começam um novo experimento.':
        '\n\nThe originals stay in the Medidas folder. The next saved files start a new experiment.',
    'Não há dados para salvar.':
        'No data to save.',
    'Gráfico salvo: ':
        'Plot saved: ',
    'ADC médio':
        'Average ADC',
    'Tempo desde o início do pulso (s)':
        'Time since the pulse start (s)',
    'Forma de Onda Média do ADC':
        'Average ADC Waveform',
    'A varredura está disponível apenas no Modo Lock-In.':
        'The sweep is only available in Lock-In mode.',
    'A varredura casada (Modo Duplo) está em andamento.':
        'The matched sweep (Dual Mode) is running.',
    'Varredura cancelada pelo usuário.':
        'Sweep cancelled by the user.',
    ' | Estabilizando (':
        ' | Settling (',
    ' | Medindo (':
        ' | Measuring (',
    ' amostras)...':
        ' samples)...',
    'Normalizado (R/DC %)':
        'Normalized (R/DC %)',
    'Bruto (u.a.)':
        'Raw (a.u.)',
    'Varredura concluída! Dados em: ':
        'Sweep finished! Data in: ',
    'Erro ao salvar arquivo CSV: ':
        'Error saving CSV file: ',
    'Varredura concluída: ':
        'Sweep finished: ',
    'Frequência':
        'Frequency',
    'Resposta em ':
        'Response vs ',
    'Eixo X (':
        'X axis (',
    ') em Escala Logarítmica':
        ') on a logarithmic scale',
    'Eixo Y (Amplitude) em Escala Logarítmica':
        'Y axis (Amplitude) on a logarithmic scale',
    'Lei de potência (A·xⁿ)':
        'Power law (A·xⁿ)',
    'Sem fit':
        'No fit',
    'Lei de potência: reta em log-log (n = -1 para 1/f). Ajustada nos dados, independe da escala.\nLinear: reta nos eixos lineares.':
        'Power law: straight line in log-log (n = -1 for 1/f). Fitted to the data, independent of the scale.\nLinear: straight line on linear axes.',
    'Resposta em Frequência (':
        'Frequency response (',
    ' Hz, passo ':
        ' Hz, step ',
    'Resposta em PWM (':
        'PWM response (',
    ' %, passo ':
        ' %, step ',
    ' %, modulação ':
        ' %, modulation ',
    'Frequência do Laser (Hz)':
        'Laser frequency (Hz)',
    'PWM do Laser (%)':
        'Laser PWM (%)',
    'Erro ao salvar imagem PNG: ':
        'Error saving PNG image: ',
    'Clique: frequência e magnitude do ponto mais próximo (o marcador acompanha o espectro)\nRoda do mouse: zoom (sobre um eixo: só naquele eixo) | Arrastar: mover\nDuplo clique: volta à escala automática | Botão direito: apaga o marcador':
        'Click: frequency and magnitude of the nearest point (the marker follows the spectrum)\nMouse wheel: zoom (over an axis: that axis only) | Drag: pan\nDouble click: back to auto scale | Right button: clears the marker',
    'INMP441 - espectro (FFT) em torno de ':
        'INMP441 - spectrum (FFT) around ',
    'OPT101 - espectro do ADC (FFT) em torno de ':
        'OPT101 - ADC spectrum (FFT) around ',
    ' contagens do ADC<br>':
        ' ADC counts<br>',
    ' Hz perto do DC nesta resolução (desligue Espectro completo)':
        ' Hz near DC at this resolution (turn off Full spectrum)',
    ' Hz fora da faixa da FFT':
        ' Hz outside the FFT range',
    'sinal muito baixo em ':
        'signal too low at ',
    ' Hz (fixo)<br>A = ':
        ' Hz (fixed)<br>A = ',
    'SNR pico/piso = ':
        'Peak/floor SNR = ',
    '<div style="text-align:center;color:#d00000;"><span style="font-size:18pt;font-weight:bold;">Pico em f0 não encontrado</span><br><span style="font-size:11pt;">':
        '<div style="text-align:center;color:#d00000;"><span style="font-size:18pt;font-weight:bold;">Peak at f0 not found</span><br><span style="font-size:11pt;">',
    'INMP441 - Lock-In (X e Y)':
        'INMP441 - Lock-In (X and Y)',
    'X, Y (escala completa 24 bits)':
        'X, Y (24-bit full scale)',
    'Auto-fase: sem dados do lock-in ainda':
        'Auto-phase: no lock-in data yet',
    'Ruído/SNR: acumulando ':
        'Noise/SNR: accumulating ',
    ' s de dados (':
        ' s of data (',
    ' <span style="color:#b36b00;">(janela &lt; 10τ: estimativa imprecisa)</span>':
        ' <span style="color:#b36b00;">(window &lt; 10τ: imprecise estimate)</span>',
    '<b>Sinal</b> |⟨Z⟩| = ':
        '<b>Signal</b> |⟨Z⟩| = ',
    ' FS &nbsp; <b>Ruído</b> σ(X,Y) = ':
        ' FS &nbsp; <b>Noise</b> σ(X,Y) = ',
    ' dB &nbsp; <b>Densidade</b> ≈ ':
        ' dB &nbsp; <b>Density</b> ≈ ',
    'Status INMP441 (Simulado) | Taxa: ':
        'INMP441 status (Simulated) | Rate: ',
    ' amostras/s | 24 bits':
        ' samples/s | 24 bits',
    'Status INMP441: Aguardando conexão com o STM32 (I2S2, ':
        'INMP441 status: Waiting for the STM32 connection (I2S2, ',
    ' kHz, PCM 24 bits)':
        ' kHz, 24-bit PCM)',
    'Status INMP441: Nenhum pacote recebido; verifique a inicialização I2S e fios PB13/PB12/PB15':
        'INMP441 status: No packet received; check the I2S initialization and the PB13/PB12/PB15 wires',
    'Status INMP441: Aguardando pacotes I2S...':
        'INMP441 status: Waiting for I2S packets...',
    'Status INMP441: Conectado | Taxa de dados: ':
        'INMP441 status: Connected | Data rate: ',
    ' | ⚠ SINAL BAIXO: SNR = ':
        ' | ⚠ LOW SIGNAL: SNR = ',
    ' dB (limiar ':
        ' dB (threshold ',
    'PLL do OPT101 sem travar: frequência ':
        'OPT101 PLL not locked: frequency ',
    ' Hz reenviada ao STM32.':
        ' Hz resent to the STM32.',
    'PLL sem travar: F':
        'PLL not locked: F',
    ' reenviado':
        ' resent',
    'reduza a frequência':
        'lower the frequency',
    'x ou menor':
        'x or lower',
    'Modulação acima do limite para OSR ':
        'Modulation above the limit for OSR ',
    'x (seguro até ':
        'x (safe up to ',
    'Modulação perto do limite para OSR ':
        'Modulation near the limit for OSR ',
    'Acima de 1 kHz use PWM 100 % (a portadora de 5 kHz tem poucos ciclos por meio período)':
        'Above 1 kHz use PWM 100 % (the 5 kHz carrier has few cycles per half-period)',
    'Status: STM32 NÃO conectado - tentando reconectar automaticamente...':
        'Status: STM32 NOT connected - trying to reconnect automatically...',
    'Modo Valor Médio: ':
        'Average mode: ',
    ' pulsos | Ciclo atual: ':
        ' pulses | Current cycle: ',
    '<b>[SATURAÇÃO DO ADC]</b>':
        '<b>[ADC SATURATION]</b>',
    '[Sinal baixo: nível médio &lt; 5 % do ADC]':
        '[Low signal: mean level &lt; 5 % of the ADC]',
    '[Sinal OK]':
        '[Signal OK]',
    'Freq Real (PLL): ':
        'Real freq (PLL): ',
    '<b>PLL destravado</b>':
        '<b>PLL unlocked</b>',
    " | <span style='color:#d00000;'>Perdas USB: ":
        " | <span style='color:#d00000;'>USB losses: ",
    'Falha ao abrir a porta serial':
        'Failed to open the serial port',
    'A porta foi encontrada, mas não pôde ser aberta:\n':
        'The port was found, but could not be opened:\n',
    '\n\nFeche outros programas que usem a porta (monitor serial, outra instância deste script) e reconecte o USB. A interface tentará reconectar sozinha.':
        '\n\nClose other programs using the port (serial monitor, another instance of this script) and reconnect the USB. The interface will try to reconnect on its own.',
    'Preferências ignoradas (':
        'Preferences ignored (',
    'Medida em curso: o Windows não vai suspender por inatividade até ela terminar (a tela ainda pode apagar; não feche a tampa do notebook).':
        'Measurement running: Windows will not sleep from inactivity until it ends (the screen may still turn off; do not close the laptop lid).',
    'Preferências não salvas (':
        'Preferences not saved (',
    'ar\n≥ 2–3 mm':
        'air\n≥ 2–3 mm',
    'fase':
        'phase',
    'Varredura OPT101 em ':
        'OPT101 sweep in ',
    'Varredura INMP441 em ':
        'INMP441 sweep in ',
    'ponto ':
        'point ',
    'restante ':
        'remaining ',
    'Faixa confiável':
        'Reliable range',
    # Calibração por duas amostras (2.2.0)
    'Calibração do microfone (duas amostras de materiais diferentes)': 'Microphone calibration (two samples of different materials)',
    'Amostra A:': 'Sample A:',
    'Amostra B:': 'Sample B:',
    'espessura:': 'thickness:',
    '▶ Medir A': '▶ Measure A',
    '▶ Medir B': '▶ Measure B',
    'Usar a atual': 'Use current',
    'Gerar calibração': 'Generate calibration',
    'medindo…': 'measuring…',
    'Alumínio': 'Aluminium',
    'Inox (304/316)': 'Stainless steel (304/316)',
    'Titânio': 'Titanium',
    'Níquel': 'Nickel',
    'Latão': 'Brass',
    'Grafite': 'Graphite',
    'Folha de Al 12 µm': 'Al foil 12 µm',
    'Folha de Al 25 µm': 'Al foil 25 µm',
    'Folha de Cu 35 µm': 'Cu foil 35 µm',
    'Curva esperada nas duas:': 'Expected curve for both:',
    '✓ par indicado: ': '✓ recommended pair: ',
    '✗ par não indicado: ': '✗ pair not recommended: ',
    '✓ Calibração verificada': '✓ Calibration verified',
    '⚠ Não verificada': '⚠ Not verified',
    'razão A/B constante de ': 'A/B ratio constant from ',
    ' pontos (': ' points (',
    # Modulação externa (2.3.0)
    'Modulação interna (STM32)': 'Internal modulation (STM32)',
    'Modulação externa (chopper)': 'External modulation (chopper)',
    'Interna: o STM32 modula o laser (PWM em PA8) na frequência escolhida e dá a referência dos lock-ins.\nExterna: a luz é modulada por fora (chopper, ventilador) e a fonte é alimentada por fora; o SOI acha a\nfrequência no sinal do OPT101 e usa a fase dele como referência dos dois lock-ins (OPT101 e INMP441).\nO OPT101 precisa ver a luz já modulada. No modo externo o STM32 fica com PWM 0 e modula só um "farol"\nde 1 Hz no bit de referência, que alinha o OPT101 ao microfone (não ligue nada em PA8).\nVale para as três abas; no Modo Duplo a varredura em frequência vira manual (você muda o chopper).': 'Internal: the STM32 modulates the laser (PWM on PA8) at the chosen frequency and gives the lock-in reference.\nExternal: the light is modulated outside (chopper, fan) and the source is powered separately; SOI finds the\nfrequency in the OPT101 signal and uses its phase as the reference of both lock-ins (OPT101 and INMP441).\nThe OPT101 must see the light after modulation. In external mode the STM32 stays at PWM 0 and only modulates a\n1 Hz "beacon" on the reference bit, which aligns the OPT101 with the microphone (connect nothing to PA8).\nApplies to all three tabs; in Dual Mode the frequency sweep becomes manual (you change the chopper).',
    'Busca da modulação externa:': 'External modulation search:',
    'Faixa em que a frequência do chopper é procurada na FFT do OPT101 (o maior pico).\nCom um ventilador de pás desiguais aparece também a frequência de rotação (f/nº de pás):\nestreite a faixa em volta da frequência das pás se a busca travar na errada.': 'Range where the chopper frequency is searched in the OPT101 FFT (largest peak).\nA fan with uneven blades also shows the rotation frequency (f/number of blades):\nnarrow the range around the blade frequency if the search locks on the wrong one.',
    'Procurar de novo': 'Search again',
    'Esquece a frequência atual e procura de novo na FFT do OPT101.': 'Forgets the current frequency and searches the OPT101 FFT again.',
    'Termine ou cancele a varredura antes de trocar a modulação.': 'Finish or cancel the sweep before changing the modulation.',
    'Modulação externa: procurando a frequência no sinal do OPT101. O STM32 fica com PWM 0 (farol de 1 Hz só no bit de referência).': 'External modulation: searching for the frequency in the OPT101 signal. The STM32 stays at PWM 0 (1 Hz beacon on the reference bit only).',
    'Simulação do modo externo: frequência nominal do chopper simulado (o "botão" do ventilador).': 'External mode simulation: nominal frequency of the simulated chopper (the fan "knob").',
    'Modo externo: frequência detectada no OPT101.': 'External mode: frequency detected in the OPT101.',
    'Frequência da modulação do laser (STM32).': 'Laser modulation frequency (STM32).',
    'Use o Modo Duplo (varredura manual) na modulação externa.': 'Use Dual Mode (manual sweep) with external modulation.',
    'Externa: STM32 não conectado': 'External: STM32 not connected',
    '● travado': '● locked',
    'travado': 'locked',
    ' | microfone: aguardando o farol do STM32': ' | microphone: waiting for the STM32 beacon',
    'Frequência detectada no OPT101 (média do último segundo), desvio padrão dela e\noscilação rms da fase da luz em relação ao PLL. O INMP441 usa a mesma referência depois\nque o farol do STM32 alinha os dois fluxos (alguns segundos depois de conectar).': 'Frequency detected in the OPT101 (mean of the last second), its standard deviation and\nrms phase wander of the light relative to the PLL. The INMP441 uses the same reference once\nthe STM32 beacon aligns both streams (a few seconds after connecting).',
    'procurando a frequência no sinal do OPT101': 'searching for the frequency in the OPT101 signal',
    'faixa de busca fora da taxa de amostragem (reduza o OSR)': 'search range beyond the sampling rate (lower the OSR)',
    'sem pico claro na faixa ': 'no clear peak in the range ',
    ' (a luz está modulada? o OPT101 vê o feixe?)': ' (is the light modulated? does the OPT101 see the beam?)',
    'frequência encontrada: ': 'frequency found: ',
    '; travando': '; locking',
    'referência perdida; procurando de novo': 'reference lost; searching again',
    'seguindo, mas a fase oscila muito (sinal fraco ou chopper instável)': 'tracking, but the phase wanders a lot (weak signal or unstable chopper)',
    'Ref. externa: ': 'External ref.: ',
    '(travada)': '(locked)',
    '<b>(travando)</b>': '<b>(locking)</b>',
    '<b>Ref. externa: procurando</b>': '<b>External ref.: searching</b>',
    'Varredura em frequência manual (modulação externa)': 'Manual frequency sweep (external modulation)',
    'Gravar sozinho quando a frequência estabilizar': 'Record automatically when the frequency settles',
    'Grava um ponto quando o PLL está travado, a frequência fica estável (desvio no\núltimo segundo ≤ "estável") e ela está longe o bastante do último ponto ("passo mínimo").\nDesmarcado: só grava com "Gravar ponto".': 'Records a point when the PLL is locked, the frequency is stable (deviation in the\nlast second ≤ "stable") and far enough from the last point ("minimum step").\nUnchecked: records only with "Record point".',
    'Passo mínimo:': 'Minimum step:',
    'Distância mínima (em %) entre a frequência de um ponto novo e a do último gravado.': 'Minimum distance (in %) between the frequency of a new point and the last recorded one.',
    'estável:': 'stable:',
    'Desvio padrão máximo da frequência (último segundo, em % dela) para considerá-la estável.\nDurante a espera e a medida do ponto, ela pode mudar no máximo 2× isso (mínimo 1 %).': 'Maximum standard deviation of the frequency (last second, in % of it) to consider it stable.\nDuring the wait and the measurement of a point it may change at most 2× this (minimum 1 %).',
    'τ dos dois lock-ins durante a varredura manual (restaurado no fim). Cada ponto espera\n9τ depois que a frequência estabiliza e faz a média por 1τ.': 'τ of both lock-ins during the manual sweep (restored at the end). Each point waits\n9τ after the frequency settles and averages for 1τ.',
    '▶ Iniciar': '▶ Start',
    '⏹ Concluir': '⏹ Finish',
    'Começa uma varredura manual. Mude a frequência do chopper aos poucos; cada ponto\nespera 9τ e mede por 1τ. "Concluir" salva o CSV (DUPLO_freq_…_externa_…).': 'Starts a manual sweep. Change the chopper frequency gradually; each point\nwaits 9τ and measures for 1τ. "Finish" saves the CSV (DUPLO_freq_…_externa_…).',
    'Gravar ponto': 'Record point',
    'Mede um ponto na frequência atual agora, mesmo perto do último.': 'Measures a point at the current frequency now, even close to the last one.',
    'Varredura manual: ajuste o chopper; o ponto é gravado quando a frequência estabilizar.': 'Manual sweep: adjust the chopper; a point is recorded when the frequency settles.',
    'Já há um ponto sendo medido.': 'A point is already being measured.',
    'Ponto em andamento descartado.': 'Point in progress discarded.',
    'Varredura manual concluída sem pontos.': 'Manual sweep finished with no points.',
    ' pontos | esperando o PLL travar': ' points | waiting for the PLL to lock',
    ' pontos | f = ': ' points | f = ',
    'estável': 'stable',
    'variando': 'changing',
    ' | último: ': ' | last: ',
    'A frequência mudou (ou o PLL destravou) durante o ponto: descartado; esperando estabilizar.': 'The frequency changed (or the PLL unlocked) during the point: discarded; waiting for it to settle.',
    ': estabilizando (': ': settling (',
    ': medindo (': ': measuring (',
    'Varredura manual: sem dados do OPT101 ou do INMP441 (o microfone já está alinhado?).': 'Manual sweep: no OPT101 or INMP441 data (is the microphone aligned yet?).',
    'Ponto gravado: ': 'Point recorded: ',
    ' pontos).': ' points).',
    'Modulação externa: use a varredura manual (o STM32 não muda a frequência do chopper).': 'External modulation: use the manual sweep (the STM32 does not change the chopper frequency).',
    'Modulação externa: meça os pontos da ressonância na varredura manual.': 'External modulation: measure the resonance points in the manual sweep.',
    'Varra o chopper pela faixa da calibração e clique em Concluir (amostra ': 'Sweep the chopper over the calibration range and click Finish (sample ',
    'Modo Duplo, varredura manual: ': 'Dual Mode, manual sweep: ',
    ' pontos': ' points',
    'Modulação externa: a referência é o próprio OPT101 (a fase dele fica perto de −90° por construção; S e Δφ valem como na interna).': 'External modulation: the reference is the OPT101 itself (its phase stays near −90° by construction; S and Δφ are valid as with internal modulation).',
    'Sinal bruto do ADC (PA0, <span style="color:#000;">preto</span>) e referência do PLL externo (<span style="color:#009600;">verde tracejado</span>, cos θ ≥ 0) - osciloscópio em tempo real': 'Raw ADC signal (PA0, <span style="color:#000;">black</span>) and external PLL reference (<span style="color:#009600;">dashed green</span>, cos θ ≥ 0) - real-time oscilloscope',
    'Interna': 'Internal',
    'Externa': 'External',
    '○ procurando': '○ searching',
    ' rms: ': ' rms: ',
    '\nMicrofone: aguardando o farol do STM32 (alinhamento com o OPT101).': '\nMicrophone: waiting for the STM32 beacon (alignment with the OPT101).',
    '\n\nFrequência detectada no OPT101 (média do último segundo), desvio padrão dela e\noscilação rms da fase da luz em relação ao PLL (● travado). O INMP441 usa a mesma referência\ndepois que o farol do STM32 alinha os dois fluxos (alguns segundos depois de conectar).': '\n\nFrequency detected in the OPT101 (mean of the last second), its standard deviation and\nrms phase wander of the light relative to the PLL (● locked). The INMP441 uses the same reference\nonce the STM32 beacon aligns both streams (a few seconds after connecting).',
    ', fase ±': ', phase ±',
}
