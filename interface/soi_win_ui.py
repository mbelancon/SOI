# -*- coding: utf-8 -*-
'''Montagem da janela: barra de cima e abas OPT101 e INMP441.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class UiMixin:
    def _build_ui(self):
        pg.setConfigOptions(antialias=False, background='w', foreground='k')
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        central_layout = QtWidgets.QHBoxLayout(central)
        central_layout.setContentsMargins(6, 6, 6, 2)
        # 2.5.0: painel lateral (seções recolhíveis numa área com rolagem) à esquerda e as abas com os gráficos à
        # direita; a antiga barra de cima foi para as seções Experimento e Excitação, o SNR para a barra de status e
        # Configurações para o canto das abas. Nenhuma seção aberta aumenta o tamanho mínimo da janela.
        self.side = soi_layout.SidePanel()
        self.side_sections = {}

        def section(title, key, opened=True, page=None):
            sec = soi_layout.Section(title, key, opened)
            self.side_sections[key] = sec
            # Ao abrir uma seção, a rolagem do painel a traz para a vista (cabeçalho e o máximo do conteúdo)
            sec.head.clicked.connect(lambda on, s=sec: on and QtCore.QTimer.singleShot(
                0, lambda: (self.side.scroll.ensureWidgetVisible(s.body, 0, 0),
                            self.side.scroll.ensureWidgetVisible(s.head, 0, 0))))
            if page is None:
                self.side.add(sec)
            else:
                page.addWidget(sec)
            return sec
        self._side_section = section
        sec_exp = section('Experimento', 'exp')
        sec_exc = section('Excitação', 'exc')
        # Seções de cada aba: uma página por aba, trocada junto com a aba
        self.side_pages = soi_layout.CurrentStack()
        self.side.add(self.side_pages)
        self.side_page_lay = []

        # Excitação (comum a todas as abas): frequência e potência
        self.sp_freq = self._dspin(0.0, 5000.0, self.ref_freq, 3, 0.1, self.on_freq)
        self.sp_power = self._dspin(0.0, 100.0, self.laser_power, 1, 0.1, self.on_power)
        exc_row = sec_exc.row()
        excitation = exc_row.group()
        self.cmb_mod = QtWidgets.QComboBox()
        self.cmb_mod.addItems(['Eletrônica', 'Óptica'])
        self.cmb_mod.setToolTip(
            'Eletrônica: o STM32 modula o laser (PWM em PA8) na frequência escolhida e dá a referência dos lock-ins.\n'
            'Óptica: a luz é modulada por fora (chopper, ventilador) e a fonte é alimentada por fora; o SOI acha a\n'
            'frequência no sinal do OPT101 e usa a fase dele como referência dos dois lock-ins (OPT101 e INMP441).\n'
            'O OPT101 precisa ver a luz já modulada. No modo óptico o STM32 fica com PWM 0 e modula só um "farol"\n'
            'de 1 Hz no bit de referência, que alinha o OPT101 ao microfone (não ligue nada em PA8).\n'
            'Vale para as três abas; no Modo Duplo a varredura em frequência vira manual (você muda o chopper).')
        self.cmb_mod.currentIndexChanged.connect(self.on_mod_mode)
        # O seletor fica na janela Configurações (trigger eletrônico ou óptico); este combo guarda o estado
        for label, w in (('Freq (Hz):', self.sp_freq), ('PWM (%):', self.sp_power)):
            lbl = QtWidgets.QLabel(label)
            if w is self.sp_power:
                excitation = exc_row.group()
            excitation.addWidget(lbl)
            if w is self.sp_power:
                self._add_pwm_presets(excitation)
            else:
                excitation.addWidget(w)
                self.w_freq_mains = self._mains_warn(w)
                excitation.addWidget(self.w_freq_mains)
        self.lbl_power = lbl                  # PWM some na modulação óptica (o lugar vai para a frequência detectada)
        self.lbl_ext = QtWidgets.QLabel('')
        self.lbl_ext.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_ext.setVisible(False)
        sec_exc.add(self.lbl_ext)
        exp_grid = QtWidgets.QGridLayout()
        exp_grid.setContentsMargins(0, 0, 0, 0)
        exp_grid.setHorizontalSpacing(6)
        exp_grid.setVerticalSpacing(4)
        exp_grid.setColumnStretch(1, 1)
        sec_exp.add(exp_grid)
        exp_grid.addWidget(QtWidgets.QLabel('Amostra:'), 0, 0)
        self.ed_sample = QtWidgets.QLineEdit()
        self.ed_sample.setPlaceholderText('nome da amostra')
        self.ed_sample.setMinimumWidth(100)
        self.ed_sample.setToolTip('Todos os arquivos salvos na pasta Medidas começam com este nome.\n'
                                  'Caracteres inválidos em nomes de arquivo viram "_". Vazio = sem prefixo.')
        exp_grid.addWidget(self.ed_sample, 0, 1, 1, 2)
        # Calibração do microfone: começa na mais recente da pasta, marcada para uso
        exp_grid.addWidget(QtWidgets.QLabel('Calibração:'), 1, 0)
        self.cmb_mic_cal = RefreshComboBox(self.refresh_mic_cal)
        self.cmb_mic_cal.setMinimumWidth(100)
        self.cmb_mic_cal.setMinimumContentsLength(12)
        self.cmb_mic_cal.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_mic_cal.currentIndexChanged.connect(lambda _: self._show_dual_results())
        exp_grid.addWidget(self.cmb_mic_cal, 1, 1)
        self.chk_mic_cal = QtWidgets.QCheckBox('Usar')
        self.chk_mic_cal.setChecked(True)
        self.chk_mic_cal.setToolTip('Corrige a varredura em frequência do Modo Duplo pela calibração escolhida:\n'
                                    'S é dividido pela sensibilidade relativa e Δφ é descontado da fase do sistema.\n'
                                    'Desmarque para gerar uma calibração nova (ela usa os dados brutos).')
        self.chk_mic_cal.toggled.connect(lambda _: self._show_dual_results())
        exp_grid.addWidget(self.chk_mic_cal, 1, 2)
        # Configuração da célula: a calibração só vale na configuração em que foi feita (acústica diferente)
        # 2.5.0: só a Câmara (modo OPC removido, Marcos 25/11). O combo continua fora da tela: vai para os CSV
        # ("# Celula = Camara") e as funções da calibração o leem.
        self.cmb_cell = QtWidgets.QComboBox(self)
        self.cmb_cell.setVisible(False)
        for key, name in CELLS.items():
            self.cmb_cell.addItem(name, key)
            self.cmb_cell.setItemData(self.cmb_cell.count() - 1, CELL_TIPS[key], QtCore.Qt.ItemDataRole.ToolTipRole)
        self.cmb_cell.setToolTip('Configuração da célula nesta medida:\n' + '\n'.join(CELL_TIPS.values())
                                 + '\nA calibração do microfone só vale na configuração em que foi feita (o volume de gás e a\n'
                                   'acústica mudam); a interface avisa se a calibração escolhida for de outra. Vai para os CSV.')
        self.cmb_cell.currentIndexChanged.connect(lambda _: self._show_dual_results())
        # 2.5.0: só a Câmara. Um índice salvo das versões com OPC (1 = Câmara) deixava o combo sem item (célula
        # "None" no aviso da calibração e nos CSV): qualquer índice inválido volta para a Câmara
        self.cmb_cell.currentIndexChanged.connect(
            lambda i: self.cmb_cell.setCurrentIndex(0) if i < 0 and self.cmb_cell.count() else None)
        self.cmb_cell.setCurrentIndex(0)
        # SNR dos dois lock-ins, a cada segundo: |média de Z| / σ por quadratura de Z = X + jY nos últimos
        # SNR_TOP_WINDOW_S (o mesmo critério do gráfico Ruído/SNR do INMP441)
        self.lbl_snr_top = QtWidgets.QLabel('SNR OPT/INMP: — / — dB')
        self.lbl_snr_top.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_snr_top.setMinimumWidth(QtGui.QFontMetrics(self.lbl_snr_top.font()).horizontalAdvance(
            'SNR OPT/INMP: -10 / 100 dB') + 6)
        self.lbl_snr_top.setToolTip(
            f'Quanto a saída de cada lock-in está acima do ruído, nos últimos 10τ (de {SNR_TOP_WINDOW_S:g} a {SNR_TOP_MAX_S:g} s;\n'
            'atualiza a cada segundo; "—" nos primeiros segundos):\n'
            'SNR = 20·log10(|⟨Z⟩| / σ), com Z = X + jY a saída do lock-in e σ o desvio-padrão de X e de Y (média das\n'
            'duas quadraturas). Inclui tudo o que flutua na janela (ruído e deriva) e melhora com τ maior.\n'
            f'Verde ≥ {SNR_TOP_GOOD_DB:g} dB (erro de uma varredura ≲ 2 %), amarelo {SNR_TOP_OK_DB:g}–{SNR_TOP_GOOD_DB:g} dB\n'
            f'(~2 a 7 %), vermelho abaixo (> ~7 %); o erro cai ~3·10^(−SNR/20) (bateria de 26/11).\n'
            'OPT: precisa do Modo Lock-In na aba OPT101. INMP: precisa do lock-in do INMP441 ligado.')
        self.lbl_snr_top.setStyleSheet('padding:0 8px;')     # 2.5.0: na barra de status (montada no fim de _build_ui)
        self.snr_top_timer = QtCore.QTimer(self)
        self.snr_top_timer.timeout.connect(self._update_snr_top)
        self.snr_top_timer.start(1000)
        self.chk_sim = QtWidgets.QCheckBox('Simular amostragem')
        self.chk_sim.setStyleSheet('QCheckBox{font-weight:bold;color:#006400;}')
        self.chk_sim.setToolTip('Gera um sinal simulado (com ruído) quando não há STM32 conectado.')
        self.chk_sim.toggled.connect(self.on_simulate)
        # 2.5.0: sem caixa na tela (simulado automático sem STM32); o widget guarda o estado e fica escondido
        self.chk_sim.setParent(self)
        self.chk_sim.setVisible(False)
        self.opt_supply = 3.3                 # alimentação do OPT101 (V), escolhida em Configurações
        self.chk_scope_fixed = QtWidgets.QCheckBox('Escala do osciloscópio fixa de 0 a 3,3 V')
        self.chk_scope_fixed.setChecked(False)
        self.chk_scope_fixed.setToolTip('Marcado: o eixo do osciloscópio do OPT101 vai sempre de 0 a 3,3 V (toda a faixa do ADC).\n'
                                        'Desmarcado (padrão): o eixo acompanha o sinal e a linha "Max OPT101 output"\n'
                                        'só entra na vista quando o pico passa de 80 % do teto.')
        self.chk_scope_fixed.toggled.connect(lambda _: self._apply_scope_scale())
        self.btn_settings = QtWidgets.QPushButton('⚙ Configurações')
        self.btn_settings.setStyleSheet('QPushButton{font-weight:bold;padding:3px 12px;background:#e8eef7;'
                                        'border:1px solid #4a6fa5;border-radius:4px;}'
                                        'QPushButton:hover{background:#d3def0;}')
        self.btn_settings.setToolTip('Trigger dos lock-ins (eletrônico pelo STM32 ou óptico pelo OPT101), alimentação do\n'
                                     'OPT101 (3,3 V ou 5 V) e Finalizar experimento.')
        self.btn_settings.clicked.connect(self.open_settings)
        # 2.5.0: Configurações no canto das abas; "Finalizar experimento" na seção Experimento
        self.btn_finish = QtWidgets.QPushButton('Finalizar experimento')
        self.btn_finish.setStyleSheet('QPushButton{font-weight:bold;padding:3px 12px;background:#d4edda;'
                                      'border:1px solid #2e7d32;border-radius:4px;}'
                                      'QPushButton:hover{background:#b8e0c2;}')
        self.btn_finish.setToolTip('Compacta num ZIP (pasta Medidas, nome = amostra + data) todos os arquivos salvos\n'
                                   'desde que a interface abriu (ou desde o último "Finalizar experimento"),\n'
                                   'junto com a calibração do microfone em uso.')
        self.btn_finish.clicked.connect(self.finish_experiment)
        sec_exp.add(self.btn_finish)

        tabs = QtWidgets.QTabWidget()
        self.tabs = tabs
        tabs.setCornerWidget(self.btn_settings, QtCore.Qt.Corner.TopRightCorner)
        self.main_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.main_split.setChildrenCollapsible(True)
        self.main_split.addWidget(self.side)
        self.main_split.addWidget(tabs)
        self.main_split.setStretchFactor(0, 0)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setSizes([320, 1000])
        central_layout.addWidget(self.main_split)
        tabs.currentChanged.connect(self.refresh_mic_cal)
        tabs.currentChanged.connect(lambda i: self.side_pages.setCurrentIndex(i) if i < self.side_pages.count() else None)

        optical_page = QtWidgets.QWidget()
        tabs.addTab(optical_page, 'OPT101')
        root = QtWidgets.QVBoxLayout(optical_page)
        root.setContentsMargins(6, 6, 6, 6)

        # Status
        self.lbl_status = QtWidgets.QLabel('Inicializando...')
        self.lbl_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setTextFormat(QtCore.Qt.TextFormat.RichText)
        root.addWidget(soi_layout.no_widen(self.lbl_status))

        # 2.5.0: controles da aba no painel lateral (página 0); à direita só os gráficos
        opt_side = self._side_page(0)
        sec_scope = self._side_section('Osciloscópio', 'opt_scope', True, opt_side)
        scope_grid = QtWidgets.QGridLayout()
        scope_grid.setContentsMargins(0, 0, 0, 0)
        scope_grid.setHorizontalSpacing(6)
        scope_grid.setColumnStretch(1, 1)
        sec_scope.add(scope_grid)
        self.sp_window = self._dspin(0.005, 30.0, self.raw.window, 3, 0.5, self.on_window)
        scope_grid.addWidget(QtWidgets.QLabel('Janela (s):'), 0, 0)
        scope_grid.addWidget(self.sp_window, 0, 1)
        self.chk_mains = QtWidgets.QCheckBox('Filtro 60 Hz')
        self.chk_mains.setToolTip('Rejeita 60 Hz e múltiplos (até 1,5 kHz) no sinal bruto e no lock-in.\n'
                                  'Notches que caem sobre a frequência de modulação são omitidos.')
        self.chk_mains.setChecked(False)
        self.chk_mains.toggled.connect(self.on_mains)
        if not getattr(self.dsp, 'supports_mains', False):
            self.chk_mains.setEnabled(False)
            self.chk_mains.setToolTip('Disponível apenas no lock-in em Python.')
        # 2.5.0 (Marcos, 25/11): sem o Filtro 60 Hz na tela; a caixa fica escondida e sempre desmarcada
        self.chk_mains.setParent(self)
        self.chk_mains.setVisible(False)
        scope_grid.addWidget(QtWidgets.QLabel('Sobreamostragem:'), 1, 0)
        self.cmb_osr = QtWidgets.QComboBox()
        for osr in OSR_CHOICES:
            self.cmb_osr.addItem(f'{osr}x  ({RAW_FS / osr / 1000:g} kS/s)', osr)
        self.cmb_osr.setCurrentIndex(OSR_CHOICES.index(OSR_DEFAULT))
        self.cmb_osr.setToolTip(
            'O STM32 envia todas as amostras do ADC (12 bits, 200 kS/s). A interface tira a média de\n'
            'OSR amostras seguidas: o ruído branco cai com √OSR (+½ bit a cada dobra) e a taxa\n'
            'cai para 200/OSR kS/s. 16x reproduz a versão 1.0.0 (12,5 kS/s).\n'
            'Bloqueado durante varreduras.')
        self.cmb_osr.currentIndexChanged.connect(lambda i: self.set_osr(self.cmb_osr.itemData(i)))
        scope_grid.addWidget(self.cmb_osr, 1, 1)
        self.chk_scope_fixed.setText('Escala fixa (0 a 3,3 V)')
        scope_grid.addWidget(self.chk_scope_fixed, 2, 0, 1, 2)
        # Faixa em que a frequência do chopper é procurada (modulação óptica)
        self.ext_range_w = QtWidgets.QWidget()
        er = QtWidgets.QGridLayout(self.ext_range_w)
        er.setContentsMargins(0, 4, 0, 0)
        er.setHorizontalSpacing(4)
        lbl = QtWidgets.QLabel('Busca da modulação óptica:')
        lbl.setStyleSheet('font-weight:bold;')
        er.addWidget(lbl, 0, 0, 1, 4)
        self.sp_ext_fmin = self._dspin(1.0, 5000.0, EXT_FMIN_DEFAULT, 1, 5.0, self.on_ext_range, 90, ' Hz')
        self.sp_ext_fmax = self._dspin(1.0, 5000.0, EXT_FMAX_DEFAULT, 1, 50.0, self.on_ext_range, 100, ' Hz')
        for w in (self.sp_ext_fmin, self.sp_ext_fmax):
            w.setToolTip('Faixa em que a frequência do chopper é procurada na FFT do OPT101 (o maior pico).\n'
                         'Com um ventilador de pás desiguais aparece também a frequência de rotação (f/nº de pás):\n'
                         'estreite a faixa em volta da frequência das pás se a busca travar na errada.')
        er.addWidget(QtWidgets.QLabel('de'), 1, 0)
        er.addWidget(self.sp_ext_fmin, 1, 1)
        er.addWidget(QtWidgets.QLabel('a'), 1, 2)
        er.addWidget(self.sp_ext_fmax, 1, 3)
        er.setColumnStretch(4, 1)
        self.btn_ext_search = QtWidgets.QPushButton('Procurar de novo')
        self.btn_ext_search.setToolTip('Esquece a frequência atual e procura de novo na FFT do OPT101.')
        self.btn_ext_search.clicked.connect(lambda: self.on_ext_range(force=True))
        er.addWidget(self.btn_ext_search, 2, 0, 1, 4)
        self.ext_range_w.setVisible(False)
        sec_scope.add(self.ext_range_w)

        # Osciloscópio
        ax_raw = TimeAxis(orientation='bottom')
        ax_raw.base_label = 'Tempo'
        self.plot_raw = pg.PlotWidget(axisItems={'bottom': ax_raw})
        pi = self.plot_raw.getPlotItem()
        # Legenda no título: dentro do gráfico ela ficava em cima do traço
        pi.setTitle('Sinal bruto do ADC (PA0, <span style="color:#000;">preto</span>) e referência do laser '
                    '(<span style="color:#009600;">verde tracejado</span>, 0/1)')
        pi.setLabel('left', 'Tensão no PA0 (V)')
        pi.setLabel('bottom', 'Tempo (s)')
        pi.getAxis('bottom').enableAutoSIPrefix(False)
        pi.showGrid(x=True, y=True, alpha=0.3)
        pi.setMouseEnabled(False, False)
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.setXRange(0, self.raw.window, padding=0)
        pi.setYRange(0, ADC_FULL_SCALE * 1.003, padding=0)
        pi.getAxis('left').enableAutoSIPrefix(False)   # os dados ficam em contagens; o eixo mostra volts
        pi.getAxis('left').setScale(ADC_VREF / ADC_FULL_SCALE)
        # Teto do OPT101 (muda com a alimentação); fora da vista quando o sinal é baixo e o eixo se ajusta a ele
        self.line_opt_max = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen((230, 0, 0), width=2,
                                                                              style=QtCore.Qt.PenStyle.DashLine),
                                            label='Max OPT101 output',
                                            labelOpts={'position': 0.02, 'anchors': [(0, 1), (0, 1)],
                                                       'color': (208, 0, 0)})
        self.line_opt_max.setZValue(50)
        pi.addItem(self.line_opt_max, ignoreBounds=True)
        self.txt_sat = pg.TextItem('Limiar de Saturação', color=(208, 0, 0), anchor=(0.5, 0.5))
        self.txt_sat.setFont(QtGui.QFont('Arial', 20, QtGui.QFont.Weight.Bold))
        self.txt_sat.setZValue(100)
        self.txt_sat.setVisible(False)
        pi.addItem(self.txt_sat, ignoreBounds=True)
        self._apply_scope_scale()             # eixo em % da saturação (alimentação do OPT101)

        pen_adc = pg.mkPen('k', width=1)
        self.c_adc_a = pi.plot(pen=pen_adc)
        self.c_adc_b = pi.plot(pen=pen_adc)
        # Referência do laser em um segundo ViewBox (equivalente ao twinx)
        self.ref_vb = pg.ViewBox()
        pi.scene().addItem(self.ref_vb)
        self.ref_vb.setXLink(pi)
        self.ref_vb.setYRange(-0.05, 1.25, padding=0)
        self.ref_vb.setMouseEnabled(False, False)
        self.ref_vb.setMenuEnabled(False)
        pen_ref = pg.mkPen(color=(0, 150, 0, 140), style=QtCore.Qt.PenStyle.DashLine)
        self.c_ref_a = pg.PlotDataItem(pen=pen_ref)
        self.c_ref_b = pg.PlotDataItem(pen=pen_ref)
        self.ref_vb.addItem(self.c_ref_a)
        self.ref_vb.addItem(self.c_ref_b)
        self.lbl_reduced = pg.TextItem('Visualização reduzida, f>50 Hz', color=(255, 0, 0, 120),
                                       anchor=(0.5, 0.5))
        self.lbl_reduced.setFont(QtGui.QFont('Arial', 22, QtGui.QFont.Weight.Bold))
        self.lbl_reduced.setZValue(100)
        self.lbl_reduced.setVisible(False)
        self.ref_vb.addItem(self.lbl_reduced, ignoreBounds=True)

        def sync_views():
            self.ref_vb.setGeometry(pi.vb.sceneBoundingRect())
            self.ref_vb.linkedViewChanged(pi.vb, self.ref_vb.XAxis)
        pi.vb.sigResized.connect(sync_views)
        sync_views()

        for c in (self.c_adc_a, self.c_adc_b, self.c_ref_a, self.c_ref_b):
            c.setDownsampling(auto=True, method='peak')
            c.setClipToView(True)

        self.cursor = pg.InfiniteLine(pos=0, angle=90,
                                      pen=pg.mkPen((255, 0, 0, 200), style=QtCore.Qt.PenStyle.DashLine))
        pi.addItem(self.cursor)
        # Osciloscópio recolhível (Marcos, 25/11): cabeçalho com botão em cima do gráfico; recolhido, o espaço vai
        # para o gráfico do lock-in/valor médio. A altura entre os dois se ajusta arrastando a divisória.
        self.scope_box = QtWidgets.QWidget()
        sc_lay = QtWidgets.QVBoxLayout(self.scope_box)
        sc_lay.setContentsMargins(0, 0, 0, 0)
        sc_lay.setSpacing(0)
        self.btn_scope = QtWidgets.QToolButton()
        self.btn_scope.setCheckable(True)
        self.btn_scope.setChecked(True)
        self.btn_scope.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.btn_scope.setStyleSheet('QToolButton{text-align:left;padding:1px 6px;border:none;border-bottom:1px solid #d6d9df;'
                                     'font-weight:bold;color:#333;}QToolButton:hover{background:#eef2f8;}')
        self.btn_scope.setToolTip('Mostra ou recolhe o osciloscópio (sinal bruto do ADC). A aquisição continua; o aviso de\n'
                                  'saturação continua na linha de status acima.')
        self.btn_scope.toggled.connect(self.on_scope_toggle)
        sc_lay.addWidget(self.btn_scope)
        sc_lay.addWidget(self.plot_raw, 1)
        self.on_scope_toggle(True)
        self.opt_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.opt_split.setChildrenCollapsible(False)
        self.opt_split.addWidget(self.scope_box)
        root.addWidget(self.opt_split, 1)

        # Magnitude (esquerda, azul) e Fase (direita, vermelho) no mesmo gráfico, na metade esquerda
        self.plot1 = pg.PlotWidget(axisItems={'bottom': TimeAxis(orientation='bottom')})
        p1 = self.plot1.getPlotItem()
        p1.setLabel('left', 'Magnitude (u.a.)', color='b')
        p1.setLabel('bottom', f'{TimeAxis.base_label} (s)')
        p1.getAxis('left').setPen('b')
        p1.getAxis('left').setTextPen('b')
        p1.getAxis('bottom').enableAutoSIPrefix(False)
        p1.showGrid(x=True, y=True, alpha=0.3)
        p1.setMouseEnabled(False, False)
        p1.setMenuEnabled(False)
        p1.hideButtons()
        self.lockin_span = MAX_POINTS * RATE.DECIMATION / RATE.FS
        p1.setXRange(-self.lockin_span, 0, padding=0)
        p1.setYRange(0, 1, padding=0)
        self.line_r = p1.plot(pen=pg.mkPen('b', width=1), symbol='o', symbolSize=4,
                              symbolBrush='b', symbolPen='b')
        p1.showAxis('right')
        ax_r = p1.getAxis('right')
        ax_r.setLabel('Fase (Graus)', color='r')
        ax_r.setPen('r')
        ax_r.setTextPen('r')
        ax_r.setGrid(False)
        self.phase_vb = pg.ViewBox()
        p1.scene().addItem(self.phase_vb)
        ax_r.linkToView(self.phase_vb)
        self.phase_vb.setXLink(p1)
        self.phase_vb.setYRange(-180, 180, padding=0)
        self.phase_vb.setMouseEnabled(False, False)
        self.phase_vb.setMenuEnabled(False)
        self.line_phase = pg.PlotDataItem(pen=pg.mkPen('r', width=1), symbol='o', symbolSize=4,
                                          symbolBrush='r', symbolPen='r')
        self.phase_vb.addItem(self.line_phase)
        self.line_ref_avg = pg.PlotDataItem(pen=pg.mkPen(color=(0, 150, 0, 140),
                                                         style=QtCore.Qt.PenStyle.DashLine))
        self.line_ref_avg.setVisible(False)
        self.phase_vb.addItem(self.line_ref_avg)

        def sync_phase():
            self.phase_vb.setGeometry(p1.vb.sceneBoundingRect())
            self.phase_vb.linkedViewChanged(p1.vb, self.phase_vb.XAxis)
        p1.vb.sigResized.connect(sync_phase)
        sync_phase()

        # Parte de baixo: Lock-In/Valor Médio à esquerda e a FFT (opcional) à direita
        lower = QtWidgets.QWidget()
        bottom = QtWidgets.QHBoxLayout(lower)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(self.plot1, 1)
        self.opt_split.addWidget(lower)
        self.opt_split.setStretchFactor(0, 1)
        self.opt_split.setStretchFactor(1, 2)
        self.opt_split.setSizes([300, 600])
        side = opt_side
        self.side_layout = side
        self.opt_lower_lay = bottom
        self.paused = False
        sec_view = self._side_section('Lock-In e Valor Médio', 'opt_view', True, opt_side)
        view_row = sec_view.row()
        g = view_row.group()
        g.setSpacing(0)
        # Modo do gráfico inferior: botões lado a lado
        self.btn_mode_li = QtWidgets.QPushButton('Lock-In')
        self.btn_mode_avg = QtWidgets.QPushButton('Valor Médio')
        self.btn_mode_li.setToolTip('Magnitude e fase do lock-in ao longo do tempo.')
        self.btn_mode_avg.setToolTip('Forma de onda média do ADC sobre vários pulsos (permite o ajuste exponencial).')
        mode_group = QtWidgets.QButtonGroup(self)
        mode_group.setExclusive(True)
        for b, avg in ((self.btn_mode_li, False), (self.btn_mode_avg, True)):
            b.setCheckable(True)
            b.setStyleSheet('QPushButton{padding:3px 14px;border:1px solid #888;background:#f2f2f2;}'
                            'QPushButton:checked{background:#1f5fbf;color:white;font-weight:bold;}')
            b.clicked.connect(lambda _=False, a=avg: self.set_display_mode(a))
            mode_group.addButton(b)
            g.addWidget(b)
        self.btn_mode_li.setChecked(True)
        g = view_row.group()
        g.addWidget(QtWidgets.QLabel('Pausa:'))
        self.sw_pause = ToggleSwitch()
        self.sw_pause.toggled.connect(self.on_pause)
        g.addWidget(self.sw_pause)
        g = view_row.group()
        self.btn_save_view = QtWidgets.QPushButton('Salvar')
        self.btn_save_view.setToolTip('CSV e PNG serão salvos na pasta Medidas')
        self.btn_save_view.clicked.connect(self.save_view)
        g.addWidget(self.btn_save_view)
        self.chk_opt_fft = QtWidgets.QCheckBox('FFT')
        self.chk_opt_fft.setToolTip('Espectro do sinal bruto do ADC (ao lado do gráfico do lock-in).')
        self.chk_opt_fft.toggled.connect(self.on_opt_fft)
        g.addWidget(self.chk_opt_fft)
        # Varreduras: seção própria do painel; o botão antigo fica escondido e acompanha a seção
        self.btn_opt_sweeps = QtWidgets.QPushButton('Varreduras ▸')
        self.btn_opt_sweeps.setCheckable(True)
        self.btn_opt_sweeps.toggled.connect(self.on_opt_sweeps_panel)
        self.btn_opt_sweeps.setParent(self)
        self.btn_opt_sweeps.setVisible(False)
        # Parâmetros do modo ativo (preenchidos mais abaixo, depois de criar os controles)
        self.mode_params = QtWidgets.QVBoxLayout()
        self.mode_params.setContentsMargins(0, 0, 0, 0)
        sec_view.add(self.mode_params)

        self.sp_tau = TauSpinBox(auto_tau(self.ref_freq), self.on_tau)
        self.sp_hp = self._dspin(0.0001, 500.0, self.cutoff_hp, 4, 0.01, self.on_hp)

        # Análise da curva (acessível apenas com o gráfico pausado no modo Valor Médio)
        self.fit = None
        self._fit_toff = 0.0
        # Painel do ajuste: só aparece no Valor Médio; os controles ficam ativos com o gráfico pausado
        self.fit_panel = QtWidgets.QWidget()
        fit_panel_lay = QtWidgets.QVBoxLayout(self.fit_panel)
        fit_panel_lay.setContentsMargins(0, 0, 0, 0)
        self.fit_hint_row = QtWidgets.QWidget()
        hint_lay = QtWidgets.QHBoxLayout(self.fit_hint_row)
        hint_lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_fit_hint = QtWidgets.QLabel('Para ajustar exponenciais, pause o gráfico:')
        self.lbl_fit_hint.setWordWrap(True)
        hint_lay.addWidget(self.lbl_fit_hint)
        self.btn_fit_pause = QtWidgets.QPushButton('⏸ Pausar e ajustar')
        self.btn_fit_pause.setStyleSheet('background:#cfe2ff;')
        self.btn_fit_pause.clicked.connect(lambda: self.sw_pause.setChecked(True))
        hint_lay.addWidget(self.btn_fit_pause)
        hint_lay.addStretch(1)
        fit_panel_lay.addWidget(self.fit_hint_row)
        self.fit_box = self._group('Análise da curva')
        fit_panel_lay.addWidget(self.fit_box)
        fit_lay = QtWidgets.QVBoxLayout(self.fit_box)
        self.lbl_fit = QtWidgets.QLabel('')
        fit_lay.addWidget(self.lbl_fit)
        row_a = QtWidgets.QHBoxLayout()
        row_a.addWidget(QtWidgets.QLabel('Modelo:'))
        self.cmb_fit = QtWidgets.QComboBox()
        self.cmb_fit.addItems(['1 exponencial', '2 exponenciais'])
        self.cmb_fit.currentIndexChanged.connect(self.on_fit_model)
        row_a.addWidget(self.cmb_fit)
        self.btn_fit = QtWidgets.QPushButton('Fit')
        self.btn_fit.setToolTip('Plota o modelo com os parâmetros atuais (de t=0 até o fim do pulso)')
        self.btn_fit.clicked.connect(self.fit_current)
        self.btn_opt = QtWidgets.QPushButton('Otimizar')
        self.btn_opt.setToolTip('Ajusta por mínimos quadrados usando os valores atuais como ponto de partida')
        self.btn_opt.clicked.connect(self.fit_optimize)
        row_a.addStretch(1)
        fit_lay.addLayout(row_a)
        row_a = QtWidgets.QHBoxLayout()      # 2.5.0: duas linhas (painel lateral estreito)
        row_a.addWidget(self.btn_fit)
        row_a.addWidget(self.btn_opt)
        row_a.addStretch(1)
        self.sw_t0 = ModeSwitch('Clique para alternar: cima = Fit do On, baixo = Fit do Off')
        self.sw_t0.clicked.connect(self.on_t0_mode)
        row_a.addWidget(self.sw_t0)
        t0_lbls = QtWidgets.QVBoxLayout()
        t0_lbls.addWidget(QtWidgets.QLabel('Fit do On'))
        t0_lbls.addStretch(1)
        t0_lbls.addWidget(QtWidgets.QLabel('Fit do Off'))
        row_a.addLayout(t0_lbls)
        fit_lay.addLayout(row_a)
        big = 1e9
        self.sp_fy = self._dspin(-big, big, 0.0, 3, 1.0, None, 80)
        self.sp_fa1 = self._dspin(-big, big, 0.0, 3, 1.0, None, 80)
        self.sp_ft1 = self._dspin(1e-4, 1e6, 1.0, 4, 0.1, None, 80)
        self.sp_fa2 = self._dspin(-big, big, 0.0, 3, 1.0, None, 80)
        self.sp_ft2 = self._dspin(1e-4, 1e6, 1.0, 4, 0.1, None, 80)
        # Parâmetros em três linhas de dois (cabe no painel lateral)
        row_b = QtWidgets.QGridLayout()
        for i, (label, w) in enumerate((('y∞:', self.sp_fy), (None, None), ('A1:', self.sp_fa1),
                                        ('τ1 (ms):', self.sp_ft1), ('A2:', self.sp_fa2), ('τ2 (ms):', self.sp_ft2))):
            if w is None:
                continue
            r, c = divmod(i, 2)
            row_b.addWidget(QtWidgets.QLabel(label), r, 2 * c)
            row_b.addWidget(w, r, 2 * c + 1)
        row_b.setColumnStretch(1, 1)
        row_b.setColumnStretch(3, 1)
        fit_lay.addLayout(row_b)
        self.sp_fa2.setEnabled(False)
        self.sp_ft2.setEnabled(False)
        self.fit_box.setEnabled(False)
        self.fit_panel.setVisible(False)
        side.addWidget(self.fit_panel)
        self.line_fit = self.plot1.getPlotItem().plot(pen=pg.mkPen((255, 120, 0), width=2))
        self.line_fit.setVisible(False)

        pen_rng = pg.mkPen((0, 160, 0), width=2)
        self._region_lock = False
        self.fit_lines = []
        for _ in range(2):
            ln = pg.InfiniteLine(angle=90, movable=True, pen=pen_rng,
                                 hoverPen=pg.mkPen((0, 220, 0), width=3))
            ln.setZValue(50)
            ln.setVisible(False)
            ln.sigPositionChanged.connect(self.on_fit_region_moved)
            self.plot1.getPlotItem().addItem(ln, ignoreBounds=True)
            self.fit_lines.append(ln)
        # Quadros de varredura do OPT101 (2.5.1): o mesmo padrão do Modo Duplo, só com o OPT101:
        # Sinal x f (Hz), Sinal x PWM (%) e Sinal x t (s), num painel recolhível (botão Varreduras)
        self.sweep_kind = 'F'
        self.eta_labels = {}
        self.btn_sweeps = {}
        self.sweep_spins = {}

        self.sweep_bars = {}
        self.opt_sweeps_panel = QtWidgets.QWidget()
        opt_sw_lay = QtWidgets.QVBoxLayout(self.opt_sweeps_panel)
        opt_sw_lay.setContentsMargins(0, 0, 0, 0)

        W = self._build_sw_boxes('OPT', opt_sw_lay)
        # nomes antigos/curtos (preferências, Medidas em Série, scripts)
        self.sp_f0, self.sp_f1, self.sp_df, self.cmb_opt_fspace, self.cmb_opt_order = W.f0, W.f1, W.fn, W.fspace, W.order
        self.chk_opt_adapt, self.sp_opt_tau, self.sp_opt_tol, self.sp_opt_reps = W.adapt, W.tau, W.tol, W.reps
        self.ed_opt_avoid, self.lbl_opt_fn = W.avoid, W.lbl_fn
        self.sp_p0, self.sp_p1, self.sp_dp = W.p0, W.p1, W.dp
        self.sp_ot_f, self.sp_ot_pwm, self.sp_ot_tau, self.sp_ot_dt, self.sp_ot_dur = W.t_f, W.t_pwm, W.t_tau, W.t_dt, W.t_dur
        self.btn_sweep = self.btn_sweeps['F']
        self.btn_sweep_p = self.btn_sweeps['P']
        self.lbl_eta = self.eta_labels['F']
        self.lbl_eta_p = self.eta_labels['P']
        self._set_eta_style(False)
        self.update_eta_idle()
        sec_sw = self._side_section('Varreduras', 'opt_sweeps', False, opt_side)
        sec_sw.add(self.opt_sweeps_panel)
        sec_sw.toggled.connect(self.btn_opt_sweeps.setChecked)
        self.btn_opt_sweeps.toggled.connect(sec_sw.set_open)

        # FFT do sinal bruto do ADC: opções abaixo do gráfico, como no INMP441
        self.opt_fft_panel = QtWidgets.QWidget()
        offt_lay = QtWidgets.QVBoxLayout(self.opt_fft_panel)
        offt_lay.setContentsMargins(0, 0, 0, 0)
        offt_lay.setSpacing(0)
        offt_head = QtWidgets.QHBoxLayout()
        offt_head.addStretch(1)
        self.chk_opt_fft_fit = QtWidgets.QCheckBox('Fit')
        self.chk_opt_fft_fit.setChecked(True)
        self.chk_opt_fft_fit.setToolTip('Ajusta o maior pico perto da referência com a forma exata do pico\n'
                                        'de uma senoide na FFT com janela Hann: frequência e amplitude\n'
                                        'corrigidas, mesmo quando o tom cai entre dois bins.')
        self.chk_opt_fft_fit.toggled.connect(self.on_opt_fft_fit)
        self.chk_opt_fft_full = QtWidgets.QCheckBox('Espectro completo')
        self.chk_opt_fft_full.setToolTip('Desligado: região em torno da frequência de referência, com FFT longa\n'
                                         f'({OPT_FFT_HISTORY_SEC:g} s, resolução fina).\n'
                                         'Ligado: 0 a FS/2 (metade da taxa depois da sobreamostragem),\n'
                                         f'FFT de {OPT_FFT_SIZE} pontos a 12,5 kS/s (cresce com a taxa).')
        self.chk_opt_fft_full.toggled.connect(self.on_opt_fft_full)
        offt_head.addWidget(self.chk_opt_fft_fit)
        offt_head.addSpacing(8)
        offt_head.addWidget(self.chk_opt_fft_full)
        offt_head.addStretch(1)
        self.plot_opt_fft = pg.PlotWidget()
        offt_lay.addWidget(self.plot_opt_fft, 1)
        offt_lay.addLayout(offt_head)      # opções abaixo do gráfico
        opt_fft_item = self.plot_opt_fft.getPlotItem()
        opt_fft_item.setTitle('OPT101 - espectro do ADC (FFT)')
        opt_fft_item.setLabel('left', 'Magnitude (dBFS)')
        opt_fft_item.setLabel('bottom', 'Frequência (Hz)')
        opt_fft_item.getAxis('bottom').enableAutoSIPrefix(False)
        opt_fft_item.showGrid(x=True, y=True, alpha=0.3)
        opt_fft_item.setMouseEnabled(False, False)
        opt_fft_item.setMenuEnabled(False)
        opt_fft_item.hideButtons()
        opt_fft_item.setXRange(0, RATE.FS / 2, padding=0)
        opt_fft_item.setYRange(-140, 0, padding=0)
        self.curve_opt_fft = opt_fft_item.plot(pen=pg.mkPen('#a33a22', width=1))
        self.curve_opt_fft.setDownsampling(auto=True, method='peak')
        self.curve_opt_fft.setClipToView(True)
        self.opt_fft_ref_line = pg.InfiniteLine(angle=90, pen=pg.mkPen('#888', width=1, style=QtCore.Qt.PenStyle.DashLine))
        opt_fft_item.addItem(self.opt_fft_ref_line)
        self.curve_opt_fft_fit = opt_fft_item.plot(pen=pg.mkPen('#1f5fbf', width=2))
        # Resultado do fit em posição fixa (pixels) no canto do gráfico
        self.txt_opt_fft_fit = pg.TextItem(anchor=(0, 0), fill=pg.mkBrush(255, 255, 255, 210),
                                           border=pg.mkPen('#1f5fbf'))
        self.txt_opt_fft_fit.setParentItem(opt_fft_item.vb)
        self.txt_opt_fft_fit.setPos(8, 8)
        self.txt_opt_fft_fit.setVisible(False)
        self.lbl_opt_fft_missing = self._make_fft_missing_label(opt_fft_item)
        self.opt_fft_cursor = self._make_fft_interactive(self.plot_opt_fft, self.curve_opt_fft,
                                                         self.update_opt_fft_range)
        self.opt_fft_panel.setVisible(False)
        bottom.addWidget(self.opt_fft_panel, 1)
        self.update_opt_fft_range()

        # Parâmetros de cada modo, logo acima do gráfico; só o do modo ativo fica visível
        self.li_group = QtWidgets.QWidget()
        li_lay = QtWidgets.QGridLayout(self.li_group)
        li_lay.setContentsMargins(0, 0, 0, 0)
        self.lbl_tau = self._filter_row(li_lay, self.sp_tau, self.sp_hp)
        self.update_tau_labels()
        self.mode_params.addWidget(self.li_group)

        self.avg_group = QtWidgets.QWidget()
        av_lay = QtWidgets.QHBoxLayout(self.avg_group)
        av_lay.setContentsMargins(0, 0, 0, 0)
        av_lay.addWidget(QtWidgets.QLabel('Pulsos:'))
        self.sp_pulses = QtWidgets.QSpinBox()
        self.sp_pulses.setRange(1, 1000)
        self.sp_pulses.setValue(self.avg.pulses)
        self.sp_pulses.setKeyboardTracking(False)
        self.sp_pulses.setToolTip('Número de pulsos somados na média.')
        self.sp_pulses.valueChanged.connect(self.on_pulses)
        av_lay.addWidget(self.sp_pulses)
        av_lay.addSpacing(12)
        btn_pm = QtWidgets.QPushButton('◀')
        btn_pp = QtWidgets.QPushButton('▶')
        btn_pm.setToolTip('Mostra mais tempo antes do início do pulso (+10 ms de pré-trigger).')
        btn_pp.setToolTip('Mostra menos tempo antes do início do pulso (−10 ms de pré-trigger).')
        btn_pm.setFixedWidth(30)
        btn_pp.setFixedWidth(30)
        btn_pm.clicked.connect(lambda: self.adjust_pretrigger(1))
        btn_pp.clicked.connect(lambda: self.adjust_pretrigger(-1))
        self.lbl_pre = QtWidgets.QLabel('Pré: -0.000 s')
        self.lbl_pre.setToolTip('Pré-trigger: tempo exibido antes da borda de subida do laser.')
        av_lay.addWidget(btn_pm)
        av_lay.addWidget(self.lbl_pre)
        av_lay.addWidget(btn_pp)
        av_lay.addStretch(1)
        self.mode_params.addWidget(self.avg_group)
        self.avg_group.setVisible(False)

        audio_panel = QtWidgets.QWidget()
        audio_layout = QtWidgets.QVBoxLayout(audio_panel)
        self.audio_status = QtWidgets.QLabel('Inicializando áudio...')
        self.audio_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.audio_status.setTextFormat(QtCore.Qt.TextFormat.RichText)
        audio_layout.addWidget(soi_layout.no_widen(self.audio_status))
        # 2.5.0: controles da aba no painel lateral (página 1)
        aud_side = self._side_page(1)
        sec_aview = self._side_section('Exibição', 'aud_view', True, aud_side)
        aview_row = sec_aview.row()
        # Varreduras: seção própria; o botão antigo fica escondido e acompanha a seção
        self.btn_audio_sweeps = QtWidgets.QPushButton('Varreduras ▸')
        self.btn_audio_sweeps.setCheckable(True)
        self.btn_audio_sweeps.toggled.connect(self.on_audio_sweeps_panel)
        self.btn_audio_sweeps.setParent(self)
        self.btn_audio_sweeps.setVisible(False)
        self.btn_noise_detect = QtWidgets.QPushButton('Detectar ruídos de fundo...')
        self.btn_noise_detect.setToolTip(
            'Abre uma janela que grava alguns segundos do INMP441 e do OPT101 com o laser parado e procura frequências\n'
            'com sinal acima do fundo e séries harmônicas (ex.: ventoinha do laser em ~170 Hz; no OPT101, a rede).\n'
            'Rápido ou comparativo (sem e com a fonte de ruído). Os tons encontrados são excluídos das próximas\n'
            'varreduras do Modo Duplo (caixa "Excluir ruídos detectados").')
        self.btn_noise_detect.clicked.connect(self.open_noise_dialog)
        g = aview_row.group()
        g.addWidget(QtWidgets.QLabel('Gráficos:'))
        self.chk_audio_lockin = QtWidgets.QCheckBox('Lock-In')
        self.chk_audio_lockin.setChecked(True)
        self.chk_audio_noise = QtWidgets.QCheckBox('Ruído/SNR')
        self.chk_audio_noise.setToolTip('Média e desvio-padrão da saída do lock-in numa janela móvel.\n'
                                        'Use uma janela bem maior que τ (≥ 10τ) para uma estimativa confiável.')
        self.chk_audio_fft = QtWidgets.QCheckBox('FFT')
        for chk in (self.chk_audio_lockin, self.chk_audio_noise, self.chk_audio_fft):
            chk.toggled.connect(self.on_audio_views)
            g.addWidget(chk)

        # Chave R/Fase <-> X/Y, com auto-fase e offset de fase manual
        self.audio_xy_group = QtWidgets.QWidget()
        xy_lay = soi_layout.FlowBar(hspace=8, vspace=4, last_right=False)
        self.audio_xy_group.setLayout(xy_lay)
        xy_g = xy_lay.group()
        xy_g.addWidget(QtWidgets.QLabel('R/θ'))
        self.sw_audio_xy = ToggleSwitch()
        self.sw_audio_xy.setToolTip('Exibição do lock-in: R e Fase (esquerda) ou X e Y (direita).\n'
                                    'Ao passar para X/Y a auto-fase é aplicada.')
        self.sw_audio_xy.toggled.connect(self.on_audio_xy)
        xy_g.addWidget(self.sw_audio_xy)
        xy_g.addWidget(QtWidgets.QLabel('X/Y'))
        self.btn_audio_autophase = QtWidgets.QPushButton('Auto-fase')
        self.btn_audio_autophase.setToolTip(f'Ajusta o offset de fase para que o sinal fique todo em X (θ ≈ 0),\n'
                                            f'usando a média do último {AUTO_PHASE_SPAN:g} s.')
        self.btn_audio_autophase.clicked.connect(self.audio_auto_phase)
        xy_lay.addWidget(self.btn_audio_autophase)
        xy_g = xy_lay.group()
        xy_g.addWidget(QtWidgets.QLabel('Offset (°):'))
        self.sp_audio_phase_off = self._dspin(-180.0, 180.0, 0.0, 1, 1.0, self.on_audio_phase_offset, width=70)
        self.sp_audio_phase_off.setWrapping(True)
        xy_g.addWidget(self.sp_audio_phase_off)
        sec_aview.add(self.audio_xy_group)
        sec_aview.add(self.btn_noise_detect)

        # Parâmetros do lock-in do INMP441 (mesmos do OPT101, porém independentes)
        sec_ali = self._side_section('Lock-In', 'aud_li', True, aud_side)
        self.audio_li_group = QtWidgets.QWidget()
        audio_params = QtWidgets.QGridLayout(self.audio_li_group)
        audio_params.setContentsMargins(0, 0, 0, 0)
        self.sp_audio_tau = TauSpinBox(auto_tau(self.ref_freq), self.on_audio_tau)
        self.sp_audio_hp = self._dspin(0.0001, 500.0, self.audio_cutoff_hp, 4, 0.01, self.on_audio_hp)
        self.lbl_audio_tau = self._filter_row(audio_params, self.sp_audio_tau, self.sp_audio_hp)
        self.update_tau_labels()
        self.chk_audio_mains = QtWidgets.QCheckBox('Filtro 60 Hz')
        self.chk_audio_mains.setToolTip('Rejeita 60 Hz e múltiplos (até 1,5 kHz) no sinal do lock-in.\n'
                                        'Notches que caem sobre a frequência de modulação são omitidos.')
        self.chk_audio_mains.setChecked(False)
        self.chk_audio_mains.toggled.connect(self.on_audio_mains)
        self.chk_audio_mains.setParent(self)            # 2.5.0: sem o Filtro 60 Hz na tela (sempre desligado)
        self.chk_audio_mains.setVisible(False)
        audio_params.addWidget(QtWidgets.QLabel('Janela (s):'), 3, 0)
        self.sp_audio_span = self._dspin(1.0, AUDIO_NOISE_SPAN, self.audio_span, 0, 1.0, self.on_audio_span, width=60)
        self.sp_audio_span.setToolTip(f'Tempo exibido nos gráficos do lock-in e do ruído/SNR (até {AUDIO_NOISE_SPAN:g} s).\nA estatística de ruído/SNR usa esta mesma janela (até {AUDIO_NOISE_SPAN / 2:g} s).')
        audio_params.addWidget(self.sp_audio_span, 3, 1)
        sec_ali.add(self.audio_li_group)

        # Varreduras do INMP441: painel recolhível (na linha dos controles ele obrigava a janela a ter ~1500 px)
        self.btn_sweeps_aud = {}
        self.eta_labels_aud = {}
        self.sweep_spins_aud = {}
        self.audio_sweeps_panel = QtWidgets.QWidget()
        sw_lay = QtWidgets.QVBoxLayout(self.audio_sweeps_panel)
        sw_lay.setContentsMargins(0, 0, 0, 0)

        W = self._build_sw_boxes('AUDIO', sw_lay)
        self.sp_aud_f0, self.sp_aud_f1, self.sp_aud_df, self.cmb_aud_fspace, self.cmb_aud_order = W.f0, W.f1, W.fn, W.fspace, W.order
        self.chk_aud_adapt, self.sp_aud_tau, self.sp_aud_tol, self.sp_aud_reps = W.adapt, W.tau, W.tol, W.reps
        self.ed_aud_avoid, self.lbl_aud_fn = W.avoid, W.lbl_fn
        self.sp_aud_p0, self.sp_aud_p1, self.sp_aud_dp = W.p0, W.p1, W.dp
        self.sp_at_f, self.sp_at_pwm, self.sp_at_tau, self.sp_at_dt, self.sp_at_dur = W.t_f, W.t_pwm, W.t_tau, W.t_dt, W.t_dur
        sec_asw = self._side_section('Varreduras', 'aud_sweeps', False, aud_side)
        sec_asw.add(self.audio_sweeps_panel)
        sec_asw.toggled.connect(self.btn_audio_sweeps.setChecked)
        self.btn_audio_sweeps.toggled.connect(sec_asw.set_open)

        # Sinal, ruído e SNR sempre visíveis enquanto o lock-in roda (atualizam junto com o status, a cada 2 s)
        self.lbl_audio_noise = QtWidgets.QLabel('Ruído/SNR: aguardando dados')
        self.lbl_audio_noise.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_audio_noise.setWordWrap(True)
        self.lbl_audio_noise.setStyleSheet('font-size:11pt;padding:2px 6px;')
        # 2.5.0 (Marcos, 25/11): linha fora da tela (o SNR já está na barra de status e no gráfico Ruído/SNR)
        self.lbl_audio_noise.setParent(self)
        self.lbl_audio_noise.setVisible(False)

        audio_plots = QtWidgets.QHBoxLayout()

        self.plot_audio_wave = pg.PlotWidget()
        audio_wave_item = self.plot_audio_wave.getPlotItem()
        audio_wave_item.setTitle('INMP441 - Lock-In (Magnitude e Fase)')
        audio_wave_item.setLabel('left', 'Magnitude (escala completa 24 bits)', color='b')
        audio_wave_item.setLabel('bottom', 'Tempo relativo (s)')
        audio_wave_item.getAxis('left').setPen('b')
        audio_wave_item.getAxis('left').setTextPen('b')
        audio_wave_item.showGrid(x=True, y=True, alpha=0.3)
        audio_wave_item.setMouseEnabled(False, False)
        audio_wave_item.setMenuEnabled(False)
        audio_wave_item.hideButtons()
        audio_wave_item.setXRange(-self.audio_span, 0, padding=0)
        self.curve_audio_wave = audio_wave_item.plot(pen=pg.mkPen('b', width=1), symbol='o', symbolSize=4,
                                                     symbolBrush='b', symbolPen='b')
        # Fase (direita, vermelho) em um segundo ViewBox, como no gráfico do OPT101
        audio_wave_item.showAxis('right')
        ax_pr = audio_wave_item.getAxis('right')
        ax_pr.setLabel('Fase (Graus)', color='r')
        ax_pr.setPen('r')
        ax_pr.setTextPen('r')
        ax_pr.setGrid(False)
        self.audio_phase_vb = pg.ViewBox()
        audio_wave_item.scene().addItem(self.audio_phase_vb)
        ax_pr.linkToView(self.audio_phase_vb)
        self.audio_phase_vb.setXLink(audio_wave_item)
        self.audio_phase_vb.setYRange(-180, 180, padding=0)
        self.audio_phase_vb.setMouseEnabled(False, False)
        self.audio_phase_vb.setMenuEnabled(False)
        self.curve_audio_phase = pg.PlotDataItem(pen=pg.mkPen('r', width=1), symbol='o', symbolSize=4,
                                                 symbolBrush='r', symbolPen='r')
        self.audio_phase_vb.addItem(self.curve_audio_phase)

        def sync_audio_phase():
            self.audio_phase_vb.setGeometry(audio_wave_item.vb.sceneBoundingRect())
            self.audio_phase_vb.linkedViewChanged(audio_wave_item.vb, self.audio_phase_vb.XAxis)
        audio_wave_item.vb.sigResized.connect(sync_audio_phase)
        sync_audio_phase()
        # X e Y (modo X/Y) no mesmo eixo da magnitude
        self.curve_audio_y = audio_wave_item.plot(pen=pg.mkPen('r', width=1), symbol='o', symbolSize=4,
                                                  symbolBrush='r', symbolPen='r')
        self.curve_audio_y.setVisible(False)
        self.audio_zero_line = pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen('#888', width=1))
        audio_wave_item.addItem(self.audio_zero_line)
        self.audio_zero_line.setVisible(False)
        self.audio_wave_legend = audio_wave_item.addLegend(offset=(10, 10))
        self.audio_wave_legend.addItem(self.curve_audio_wave, 'X')
        self.audio_wave_legend.addItem(self.curve_audio_y, 'Y')
        self.audio_wave_legend.setVisible(False)

        # Ruído e SNR: gráfico abaixo do lock-in, com o mesmo eixo de tempo; parâmetros logo abaixo
        self.audio_noise_panel = QtWidgets.QWidget()
        noise_lay = QtWidgets.QVBoxLayout(self.audio_noise_panel)
        noise_lay.setContentsMargins(0, 0, 0, 0)
        noise_lay.setSpacing(2)
        self.plot_audio_noise = pg.PlotWidget()
        noise_item = self.plot_audio_noise.getPlotItem()
        noise_item.setLabel('left', 'SNR (dB)', color='#2a7d2a')
        noise_item.setLabel('bottom', 'Tempo relativo (s)')
        noise_item.showGrid(x=True, y=True, alpha=0.3)
        noise_item.setMouseEnabled(False, False)
        noise_item.setMenuEnabled(False)
        noise_item.hideButtons()
        noise_item.setXRange(-self.audio_span, 0, padding=0)   # mesmo eixo de tempo do lock-in (on_audio_span)
        # Eixos com a mesma largura nos dois gráficos para os tempos ficarem alinhados
        noise_item.showAxis('right')
        noise_item.getAxis('right').setStyle(showValues=False)
        noise_item.getAxis('right').setPen(pg.mkPen(0, 0, 0, 0))
        for it in (audio_wave_item, noise_item):
            it.getAxis('left').setWidth(70)
            it.getAxis('right').setWidth(60)
        self.curve_audio_snr = noise_item.plot(pen=pg.mkPen('#2a7d2a', width=1.5))
        self.audio_snr_alert_line = pg.InfiniteLine(pos=self.audio_snr_alert, angle=0,
                                                    pen=pg.mkPen('#c0392b', width=1, style=QtCore.Qt.PenStyle.DashLine))
        noise_item.addItem(self.audio_snr_alert_line)
        noise_lay.addWidget(self.plot_audio_noise, 1)

        noise_row = QtWidgets.QHBoxLayout()
        noise_row.addStretch(1)
        noise_row.addWidget(QtWidgets.QLabel('Alerta SNR < (dB):'))
        self.sp_audio_snr_alert = self._dspin(-20.0, 60.0, self.audio_snr_alert, 1, 1.0,
                                              self.on_audio_snr_alert, width=60)
        self.sp_audio_snr_alert.setToolTip('A barra de status fica vermelha com "SINAL BAIXO" quando o SNR da\n'
                                           'janela de ruído cai abaixo deste valor (linha tracejada vermelha).\n'
                                           '10 dB ≈ sinal 3x maior que o desvio-padrão do ruído (limite prático de detecção).')
        noise_row.addWidget(self.sp_audio_snr_alert)
        noise_lay.addLayout(noise_row)
        self.audio_noise_panel.setVisible(False)

        audio_left = QtWidgets.QVBoxLayout()
        audio_left.setSpacing(0)
        audio_left.addWidget(self.plot_audio_wave, 3)
        audio_left.addWidget(self.audio_noise_panel, 2)
        audio_plots.addLayout(audio_left, 1)

        self.audio_fft_panel = QtWidgets.QWidget()
        fft_lay = QtWidgets.QVBoxLayout(self.audio_fft_panel)
        fft_lay.setContentsMargins(0, 0, 0, 0)
        fft_lay.setSpacing(0)
        fft_head = QtWidgets.QHBoxLayout()
        fft_head.addStretch(1)
        self.chk_audio_fft_full = QtWidgets.QCheckBox('Espectro completo')
        self.chk_audio_fft_full.setToolTip('Desligado: região em torno da frequência de referência, com FFT longa\n'
                                           f'({AUDIO_FFT_HISTORY_SEC:g} s, resolução fina).\n'
                                           f'Ligado: 0 a {AUDIO_FS // 2000} kHz, FFT de {AUDIO_FFT_SIZE} pontos.')
        self.chk_audio_fft_full.toggled.connect(self.on_audio_fft_full)
        self.chk_audio_fft_fit = QtWidgets.QCheckBox('Fit')
        self.chk_audio_fft_fit.setChecked(True)
        self.chk_audio_fft_fit.setToolTip('Ajusta o maior pico perto da referência com a forma exata do pico\n'
                                          'de uma senoide na FFT com janela Hann: frequência e amplitude\n'
                                          'corrigidas, mesmo quando o tom cai entre dois bins.')
        self.chk_audio_fft_fit.toggled.connect(self.on_audio_fft_fit)
        fft_head.addWidget(self.chk_audio_fft_fit)
        fft_head.addSpacing(8)
        fft_head.addWidget(self.chk_audio_fft_full)
        fft_head.addStretch(1)
        self.plot_audio_fft = pg.PlotWidget()
        fft_lay.addWidget(self.plot_audio_fft, 1)
        fft_lay.addLayout(fft_head)      # opções abaixo do gráfico
        audio_fft_item = self.plot_audio_fft.getPlotItem()
        audio_fft_item.setTitle('INMP441 - espectro (FFT)')
        audio_fft_item.setLabel('left', 'Magnitude (dBFS)')
        audio_fft_item.setLabel('bottom', 'Frequência (Hz)')
        audio_fft_item.showGrid(x=True, y=True, alpha=0.3)
        audio_fft_item.setMouseEnabled(False, False)
        audio_fft_item.setMenuEnabled(False)
        audio_fft_item.hideButtons()
        audio_fft_item.setXRange(0, AUDIO_FS / 2, padding=0)
        audio_fft_item.setYRange(-120, 0, padding=0)
        self.curve_audio_fft = audio_fft_item.plot(pen=pg.mkPen('#a33a22', width=1))
        self.curve_audio_fft.setDownsampling(auto=True, method='peak')
        self.curve_audio_fft.setClipToView(True)
        self.audio_fft_ref_line = pg.InfiniteLine(angle=90, pen=pg.mkPen('#888', width=1, style=QtCore.Qt.PenStyle.DashLine))
        audio_fft_item.addItem(self.audio_fft_ref_line)
        self.curve_audio_fft_fit = audio_fft_item.plot(pen=pg.mkPen('#1f5fbf', width=2))
        # Resultado do fit em posição fixa (pixels) no canto do gráfico
        self.txt_audio_fft_fit = pg.TextItem(anchor=(0, 0), fill=pg.mkBrush(255, 255, 255, 210),
                                             border=pg.mkPen('#1f5fbf'))
        self.txt_audio_fft_fit.setParentItem(audio_fft_item.vb)
        self.txt_audio_fft_fit.setPos(8, 8)
        self.txt_audio_fft_fit.setVisible(False)
        self.audio_fft_fit_html = None
        self.audio_fft_missing = None
        self.lbl_audio_fft_missing = self._make_fft_missing_label(audio_fft_item)
        self.audio_fft_cursor = self._make_fft_interactive(self.plot_audio_fft, self.curve_audio_fft,
                                                           self.update_audio_fft_range)
        audio_plots.addWidget(self.audio_fft_panel, 1)
        self.audio_fft_panel.setVisible(self.audio_fft_enabled)
        self.update_audio_fft_range()

        audio_layout.addLayout(audio_plots)
        tabs.addTab(audio_panel, 'INMP441')
        self._build_dual_tab(tabs)
        self.series_tab = soi_serie.SeriesTab(self, MEDIDAS_DIR, SERIES_DIR)
        tabs.addTab(self.series_tab, 'Medidas em Série')

        # Barra de status da janela (visível em todas as abas): avisos, tarefa em andamento e conexão
        sb = self.statusBar()
        self.lbl_sb_task = QtWidgets.QLabel('')
        self.lbl_sb_task.setStyleSheet('padding:0 8px;font-weight:bold;color:#b00000;')
        self.lbl_sb_conn = QtWidgets.QLabel('')
        self.lbl_sb_conn.setStyleSheet('padding:0 8px;')
        sb.addPermanentWidget(self.lbl_sb_task)
        sb.addPermanentWidget(self.lbl_snr_top)
        sb.addPermanentWidget(self.lbl_sb_conn)
        # Uma página de seções do painel lateral por aba (as abas que não criaram seções ficam com página vazia)
        while self.side_pages.count() < tabs.count():
            self._side_page(self.side_pages.count())
        self.side_pages.setCurrentIndex(tabs.currentIndex())
        self.last_sb_state = None

    # ------------------------------------------------------------ Modo Duplo

    def _side_page(self, idx):
        '''Layout da página do painel lateral da aba idx (criada na primeira vez).'''
        while self.side_pages.count() <= idx:
            w = QtWidgets.QWidget()
            lay = soi_layout.PageLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            self.side_pages.addWidget(w)
            self.side_page_lay.append(lay)
        return self.side_page_lay[idx]
