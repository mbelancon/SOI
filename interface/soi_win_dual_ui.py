# -*- coding: utf-8 -*-
'''Montagem da aba Modo Duplo.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class DualUiMixin:
    def _build_dual_tab(self, tabs):
        '''Aba Modo Duplo: varreduras em que o R do OPT101 (linear na intensidade) é a referência de
        potência óptica e o R do INMP441 (fotoacústico) é medido no mesmo passo.
        'P' = varredura casada em PWM; 'F' = varredura em frequência normalizada pelo OPT101.'''
        self.dual_active = False
        self.dual_state = 'IDLE'
        self.dual_kind = 'F'
        self.dual_src = 'F'         # quadro que iniciou a varredura: 'P', 'F' (calibração) ou 'M' (medidas em frequência)
        self.dual_values = []
        self.dual_idx = 0
        self.dual_timer = 0.0
        self.dual_settle = self.dual_measure = 1.0
        self.dual_opt = []          # (r, fase, dc) do OPT101 durante a medida
        self.dual_aud = []          # (r, fase) do INMP441 durante a medida (thread de áudio)
        self.dual_results = []
        self.dual_excluded = set()  # índices de dual_results tirados do ajuste com um clique no gráfico
        self.dual_ref_cfg = []      # (corte do passa-altas, notch de rede) do OPT101 em cada ponto
        self.dual_opt_tau = None    # ajuste do τ efetivo do canal óptico (varredura em frequência)
        self.dual_tau_sensor = 0.0  # τ do sensor descontado do OPT101 na última exibição (s)
        self.dual_sensor_fit_txt = None   # resultado do último "Medir…" do τ do sensor
        self.dual_saved_cutoffs = None
        self.dual_fit = None

        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)

        # Medida: cada varredura tem a sua (a calibração pede integração longa; a casada em PWM, em geral, não)
        self.dual_mode_w, self.dual_tau_w = {}, {}
        for kind in ('P', 'F', 'M'):
            cmb = QtWidgets.QComboBox()
            cmb.addItems(list(DUAL_MODE_NAMES))
            cmb.setToolTip(
                'Média no tempo: usa os filtros dos dois lock-ins (na varredura em frequência, os cortes automáticos\n'
                'de cada frequência); espera 9τ do mais lento e faz a média por 4τ.\n'
                'Integração longa: durante a varredura os dois passa-baixas passam a ter o τ escolhido (restaurados no fim);\n'
                'espera 9τ e faz a média por 1τ. Menos ruído por ponto, varredura mais lenta.')
            self.dual_mode_w[kind] = cmb
            self.dual_tau_w[kind] = TauSpinBox(1.0, None, width=80)
        # Nomes fixos: usados pelas preferências (QSettings)
        self.cmb_dual_mode_p, self.cmb_dual_mode_f = self.dual_mode_w['P'], self.dual_mode_w['F']
        self.sp_dual_tau_p, self.sp_dual_tau_f = self.dual_tau_w['P'], self.dual_tau_w['F']
        self.cmb_dual_mode_m, self.sp_dual_tau_m = self.dual_mode_w['M'], self.dual_tau_w['M']
        # Varreduras em frequência: "τ" com o τ adaptativo desligado; "τ max" (teto do adaptativo) com ele ligado
        self.dual_tau_lbl = {k: QtWidgets.QLabel('τ:') for k in ('F', 'M')}

        def sweep_box(title, fields, kind, mid=(), adapt=()):
            # Varreduras em frequência: sempre integração longa, com o τ do INMP441 (os campos andam juntos)
            meas = ((('Medida:', self.dual_mode_w[kind]),) if kind == 'P' else ()) + (
                (self.dual_tau_lbl.get(kind, 'τ:'), self.dual_tau_w[kind]),)
            box, btn, eta, bar = self._make_sweep_box(
                title, fields, lambda _=False, k=kind: self.toggle_dual_sweep(k),
                extra=mid if mid else meas, more=((meas + tuple(adapt)),) if mid else (),
                warm_pwm=(lambda: max(self.sp_dual_p0.value(), self.sp_dual_p1.value())) if kind == 'P' else None)
            self.dual_bars[kind] = bar
            return box, btn, eta

        self.dual_bars = {}
        self.sp_dual_p0 = self._dspin(0.0, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        self.sp_dual_p1 = self._dspin(0.0, 100.0, 100.0, 1, 1.0, None, 110, ' %')
        self.sp_dual_dp = self._dspin(0.1, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        box_p, btn_p, eta_p = sweep_box('Sinal x PWM (%)',
                                        (('Início:', self.sp_dual_p0), ('Fim:', self.sp_dual_p1),
                                         ('Passo:', self.sp_dual_dp)), 'P')
        self.sp_dual_f0 = self._dspin(0.1, 5000.0, SWEEP_F0_DEF, 2, 1.0, None, 110, ' Hz')
        self.sp_dual_f1 = self._dspin(0.1, 5000.0, CAL_SWEEP_F1, 2, 10.0, None, 110, ' Hz')
        self.cmb_dual_fspace = QtWidgets.QComboBox()
        self.cmb_dual_fspace.addItems(['Logarítmico', 'Linear'])
        self.sp_dual_fn = self._dspin(1.0, 5000.0, CAL_SWEEP_N, 1, 1.0, None, 90)
        # Sem caixa na janela desde 19/11: a rede entra na detecção de ruídos (OPT101); sem detecção, os múltiplos de
        # 60 Hz são excluídos por segurança (_mains_fixed). Fica como estado interno (--sem-evitar-rede desliga).
        self.chk_dual_avoid60 = QtWidgets.QCheckBox('Excluir múltiplos de 60 Hz')
        self.chk_dual_avoid60.setChecked(True)
        self.lbl_dual_mains = QtWidgets.QLabel('')
        self.lbl_dual_mains.setStyleSheet(f'color:{LOWF_WARN_COLOR};font-weight:bold;')
        self.lbl_dual_mains.setVisible(False)
        self.ed_dual_avoid = QtWidgets.QLineEdit('')
        self.ed_dual_avoid.setPlaceholderText('ex.: 170,7')
        self.ed_dual_avoid.setFixedWidth(90)
        self._avoid_tip = (
            'Frequências de fontes de ruído conhecidas (ex.: ventoinha do laser em ~170 Hz), separadas por ";", que\n'
            'ficam sempre excluídas (o campo é salvo). Em volta de cada uma, ±2 % da frequência (mínimo ±3 Hz), nenhum\n'
            'ponto é medido: um ponto que cairia nessa faixa vai para 1 Hz além da borda, do lado em que estava (a faixa\n'
            'cresce com a frequência: o harmônico k de uma fonte que varia δ varia k·δ), e fica listado no cabeçalho\n'
            'do CSV. Os ruídos detectados (caixa ao lado) somam-se a estas sem mudar o campo. Vazio = nenhuma.\n'
            'Rede: os múltiplos de 60 Hz achados pela detecção (INMP441 ou OPT101) são excluídos; sem nenhuma\n'
            'detecção em uso, todos os múltiplos de 60 Hz são excluídos (k·60 ± 3 Hz), por segurança.')
        self.ed_dual_avoid.setToolTip(self._avoid_tip)
        self.lbl_dual_fn = QtWidgets.QLabel('N pontos:')
        # τ adaptativo (vale para as duas varreduras em frequência; o quadro 'M' fica escondido)
        self.chk_dual_adapt = QtWidgets.QCheckBox('τ adaptativo')
        self.chk_dual_adapt.setChecked(False)          # padrão desde 18/11: τ fixo + repetições com mediana
        self.chk_dual_adapt.setToolTip(
            'Ligado: o campo do quadro vira "τ max" (padrão 4 s; o ruído em baixa frequência é lento): a varredura começa\n'
            'nele e o τ muda ao longo dela sem passar desse valor.\n'
            'Em cada ponto o SOI mede a flutuação da saída dos lock-ins (desvio-padrão de S e de Δφ durante\n'
            'a medida e a diferença entre a 1ª e a 2ª metade). Bem abaixo da Precisão, o τ do ponto seguinte diminui (a\n'
            'flutuação cai com 1/√τ), até ~3 períodos (mínimo 100 ms); acima de 2× a Precisão, o ponto é refeito com τ\n'
            'maior (até o τ max). Cada ponto espera 7τ e faz a média por max(1 s, 3τ). Em alta frequência, com\n'
            'sinal limpo, o τ cai para ~0,1 s e o ponto leva ~2 s.\n'
            'Desligado: o campo volta a ser "τ", fixo na varredura toda; espera 9τ e média por 1τ (como antes).')
        self.chk_dual_adapt40 = QtWidgets.QCheckBox(f'só f > {LOWF_FMAX:g} Hz')
        self.chk_dual_adapt40.setChecked(True)
        self.chk_dual_adapt40.setToolTip(
            f'Ligado (padrão): o τ adaptativo só vale acima de {LOWF_FMAX:g} Hz. Abaixo, o τ é pré-definido\n'
            f'(o τ max do quadro; espera 7τ e média por 3τ), e acima de {LOWF_FMAX:g} Hz o\n'
            f'adaptativo recomeça de {LOWF_TAU_ABOVE:g} s. Motivo: abaixo de ~{LOWF_FMAX:g} Hz o ruído é acústico, do\n'
            'ambiente, lento; a flutuação medida no ponto subestima o erro e o τ adaptativo não converge.\n'
            'Desligado: τ adaptativo em todas as frequências.')
        self.sp_dual_adapt_tol = self._dspin(0.1, 20.0, ADAPT_TOL_DEF, 1, 0.5, None, 80, ' %')
        self.sp_dual_adapt_tol.setToolTip('Flutuação aceitável da saída em cada ponto: S em %, Δφ na mesma fração em radianos\n'
                                          '(2 % = 1,15°; padrão 2 %). Menor = τ maior e varredura mais lenta.')
        self.chk_dual_blocks = QtWidgets.QCheckBox('Permitir médias')
        self.chk_dual_blocks.setToolTip(
            f'Com o τ adaptativo no τ max do quadro e a flutuação ainda acima da Precisão, em vez de subir o τ\n'
            f'o ponto faz mais medidas seguidas com o mesmo τ (até o número indicado) e grava a média de todas.\n'
            f'Abaixo de {LOWF_FMAX:g} Hz (τ pré-definido) cada ponto faz sempre esse número de medidas.\n'
            'Motivo: acima de alguns segundos o que sobra é deriva lenta, que um τ maior não remove; médias de\n'
            'medidas independentes reduzem o ruído (~1/√N) sem esperar o assentamento de um τ longo.')
        self.sp_dual_blocks = QtWidgets.QSpinBox()
        self.sp_dual_blocks.setRange(2, 10)
        self.sp_dual_blocks.setValue(ADAPT_BLOCKS_DEF)
        self.sp_dual_blocks.setPrefix('× ')
        self.sp_dual_blocks.setFixedWidth(55)
        self.sp_dual_blocks.setToolTip('Número máximo de medidas (com o mesmo τ) somadas num ponto.')
        self.sp_dual_blocks.setEnabled(False)
        self.chk_dual_blocks.toggled.connect(lambda _: (self._apply_adapt_ui(), self.update_dual_eta()))
        self.sp_dual_blocks.valueChanged.connect(self.update_dual_eta)
        for w in (self.chk_dual_blocks, self.sp_dual_blocks):    # 2.5.0: fora da tela (Permitir médias saiu)
            w.setParent(self)
            w.setVisible(False)
        self.sp_dual_reps = QtWidgets.QSpinBox()
        self.sp_dual_reps.setRange(1, 20)
        self.sp_dual_reps.setValue(SWEEP_REPS_DEF)
        self.sp_dual_reps.setSuffix(' ×')
        self.sp_dual_reps.setFixedWidth(60)
        self.sp_dual_reps.setToolTip(
            'Repetições: a varredura é feita N vezes seguidas (laser ligado entre elas; warm-up só antes da 1ª).\n'
            'Cada repetição grava o CSV normal (_rep1, _rep2...) e no fim um CSV _mediana com a mediana ponto a ponto\n'
            'e a incerteza u = 1,25·DP/√N (colunas Incerteza_S_Pct e Incerteza_Fase_Graus). 1 = uma varredura só.\n'
            'Entre 40 e 200 Hz os erros são pontos isolados (sons do ambiente de alguns segundos), em frequências\n'
            'diferentes a cada varredura: a mediana os descarta, e um τ maior não (campanha de ruído de 18/11).')
        self.sp_dual_reps.valueChanged.connect(self.update_dual_eta)
        self.chk_dual_warm_noise = QtWidgets.QCheckBox('Excluir ruídos detectados')
        self.chk_dual_warm_noise.setChecked(True)
        self._warm_noise_tip = (
            'Marcada (padrão), a varredura exclui os ruídos detectados (faixa de ±2 %, mínimo ±3 Hz, em volta de cada\n'
            'um), sem mudar o campo Faixas excluídas (Hz):\n'
            '- os da última detecção feita na janela "Detectar ruídos de fundo" (valem até a próxima detecção\n'
            '  ou até fechar a interface; não precisa clicar em "Enviar");\n'
            '- com "Aguardar warm-up", os do áudio do INMP441 durante a espera (os últimos 3 min, no máximo),\n'
            '  ignorando a frequência do laser e os harmônicos dela (±0,15 Hz); valem nessa varredura e nas repetições.\n'
            'Tons de uma série harmônica entram com a série inteira (k·f0, k ≤ 10). A rede (60 Hz e múltiplos) entra\n'
            'pelo que a detecção achou no INMP441 e no OPT101; sem detecção, todos os múltiplos de 60 Hz são excluídos.\n'
            'Vão para o cabeçalho do CSV ("# Ruidos detectados = ..."). Desmarcada: nenhuma detecção é usada.')
        self.chk_dual_warm_noise.setToolTip(self._warm_noise_tip)
        self.chk_dual_warm_noise.toggled.connect(lambda _: self._noise_det_ui())
        self.cmb_dual_order = QtWidgets.QComboBox()
        for txt, key in (('Crescente', 'crescente'), ('Decrescente', 'decrescente'), ('Embaralhada', 'embaralhada')):
            self.cmb_dual_order.addItem(txt, key)
        self.cmb_dual_order.setCurrentIndex(2)          # padrão desde 19/11: embaralhada (blocos casualizados)
        self.cmb_dual_order.setToolTip(
            'Ordem em que as frequências são medidas. Crescente ou decrescente: uma deriva lenta (aquecimento)\n'
            'vira uma inclinação falsa na curva. Embaralhada (padrão): nova ordem aleatória a cada repetição, e a deriva vira\n'
            'ruído que a mediana das repetições reduz. A semente fica no cabeçalho do CSV (a ordem pode ser refeita).\n'
            'Os CSV continuam em ordem de frequência, com as colunas Ordem_medida (posição em que o ponto foi medido)\n'
            'e Hora_ponto (fim do ponto).')
        self.lbl_dual_taumax = QtWidgets.QLabel(f'τ > {TAU_USEFUL_MAX:g} s não melhora: use repetições')
        self.lbl_dual_taumax.setStyleSheet(f'color:{LOWF_WARN_COLOR};font-weight:bold;')
        self.lbl_dual_taumax.setToolTip(
            f'Acima de τ ≈ {TAU_USEFUL_MAX:g} s o S para de melhorar: o desvio de Allan para de cair após ~1 min de média\n'
            'em 113 Hz e ~3–4 min em 37 Hz (a deriva do aquecimento da célula passa a dominar). O tempo rende mais\n'
            'em repetições (mediana) do que em τ.')
        self.lbl_dual_taumax.setVisible(False)
        self.chk_dual_nb = QtWidgets.QCheckBox('Descartar trechos com som da sala')
        self.chk_dual_nb.setChecked(False)             # desligado por padrão desde 19/11 (não ajudou à noite)
        self.chk_dual_nb.setVisible(False)             # só aparece com a opção ligada em Configurações
        self.chk_dual_nb.setToolTip(
            f'A cada 1 s o SOI compara o sinal do INMP441 nas frequências vizinhas (f ± {100 * NB_REL:.0f} %) com o sinal em f\n'
            f'(q = vizinhas / f). Um som da sala (porta, voz, carro) sobe as vizinhas junto com o sinal: o segundo em que q\n'
            f'passa de {NB_K:g} × o q típico do ponto sai da média e, com mais de {100 * NB_REDO_FRAC:.0f} % descartado, o ponto é medido\n'
            f'de novo (até {NB_MAX_REDO}×). Campanha de 18/11 (tarde): o desvio caiu de 27 para 15 % em 37 Hz e de 14 para 7 % em\n'
            '113 Hz; acima de ~500 Hz quase nada é descartado. À noite (19/11) não ajudou. O CSV ganha as colunas\n'
            'Ruido_vizinhas_q, Descartado_Pct e Refeito_ruido.')
        adapt_row = (('Repetições:', self.sp_dual_reps), ('', self.chk_dual_nb), ('', self.chk_dual_adapt), ('', self.chk_dual_adapt40),
                     ('Precisão:', self.sp_dual_adapt_tol),
                     ('', self.lbl_dual_taumax))
        # aviso em laranja ao lado do range quando ele desce abaixo de LOWF_FMAX
        self.lbl_dual_lowf = {}
        for k in ('F', 'M'):
            lb = QtWidgets.QLabel(f'alto SNR em f < {LOWF_FMAX:g} Hz')
            lb.setStyleSheet(f'color:{LOWF_WARN_COLOR};font-weight:bold;')
            lb.setToolTip(f'Abaixo de {LOWF_FMAX:g} Hz o ruído acústico do ambiente é alto: cada ponto tem alguns % de\n'
                          'incerteza (até ~10 % em 5–10 Hz com amostra de pouco sinal, como o alumínio). Use uma amostra\n'
                          'que dê bastante sinal (ex.: inox) ou comece a varredura acima desse limite.')
            lb.setVisible(False)
            self.lbl_dual_lowf[k] = lb
        # 1ª linha: faixa, espaçamento, pontos e ordem (Marcos, 19/11: a janela passava da largura da tela)
        box_f, btn_f, eta_f = sweep_box('Sinal x f (Hz)',
                                        (('Início:', self.sp_dual_f0), ('Fim:', self.sp_dual_f1),
                                         ('Espaçamento:', self.cmb_dual_fspace), (self.lbl_dual_fn, self.sp_dual_fn),
                                         ('Ordem:', self.cmb_dual_order), ('', self.lbl_dual_lowf['F'])), 'F',
                                        mid=(('', self.chk_dual_warm_noise), ('Faixas excluídas (Hz):', self.ed_dual_avoid),
                                             ('', self.lbl_dual_mains)),
                                        adapt=adapt_row)
        # Varredura em frequência das medidas (painel "Varreduras"): parâmetros próprios, para não mexer nos da calibração
        self.sp_dual_m_f0 = self._dspin(0.1, 5000.0, SWEEP_F0_DEF, 2, 1.0, None, 110, ' Hz')
        self.sp_dual_m_f1 = self._dspin(0.1, 5000.0, 2000.0, 2, 10.0, None, 110, ' Hz')
        self.cmb_dual_m_fspace = QtWidgets.QComboBox()
        self.cmb_dual_m_fspace.addItems(['Logarítmico', 'Linear'])
        self.sp_dual_m_fn = self._dspin(1.0, 5000.0, 30.0, 1, 1.0, None, 90)
        self.lbl_dual_m_fn = QtWidgets.QLabel('N pontos:')
        box_m, btn_m, eta_m = sweep_box('Varredura em frequência (normalizada pelo OPT101)',
                                        (('Início:', self.sp_dual_m_f0), ('Fim:', self.sp_dual_m_f1),
                                         ('', self.lbl_dual_lowf['M'])), 'M',
                                        mid=(('Espaçamento:', self.cmb_dual_m_fspace), (self.lbl_dual_m_fn, self.sp_dual_m_fn)))
        self.dual_fw = {'F': (self.sp_dual_f0, self.sp_dual_f1, self.cmb_dual_fspace, self.sp_dual_fn, self.lbl_dual_fn),
                        'M': (self.sp_dual_m_f0, self.sp_dual_m_f1, self.cmb_dual_m_fspace, self.sp_dual_m_fn,
                              self.lbl_dual_m_fn)}
        for k in ('F', 'M'):
            self.dual_fw[k][2].currentIndexChanged.connect(lambda i, k=k: self._on_dual_fspace(i, k))
            for w in self.dual_fw[k][:2]:
                w.valueChanged.connect(lambda _=0, k=k: self._update_lowf_warn(k))
            self._update_lowf_warn(k)
        self.dual_btns = {'P': btn_p, 'F': btn_f, 'M': btn_m}
        # Refinar ressonância: ajusta a ressonância na varredura atual e mede mais pontos em volta do f0 ajustado
        row_ref = soi_layout.FlowBar(hspace=6, vspace=3, last_right=False)
        self.btn_dual_refine = QtWidgets.QPushButton('Refinar ressonância')
        self.btn_dual_refine.setToolTip(
            'Ajusta a ressonância da célula (oscilador amortecido + fundo, acima de 250 Hz) na varredura atual\n'
            'e mede mais pontos, igualmente espaçados, dentro do pico, f0 ± f0/(2Q). Os pontos novos entram na\n'
            'mesma varredura (em ordem de frequência) e o CSV é gravado de novo com todos. Usa a Medida e o τ\n'
            'deste quadro. Serve também para uma varredura aberta do disco.')
        self.btn_dual_refine.clicked.connect(self.refine_dual_resonance)
        row_ref.addWidget(self.btn_dual_refine)
        g_ref = row_ref.group()
        g_ref.addWidget(QtWidgets.QLabel('Pontos novos:'))
        self.sp_dual_refine_n = self._dspin(3.0, 100.0, 12.0, 0, 1.0, None, 70)
        g_ref.addWidget(self.sp_dual_refine_n)
        self.lbl_dual_refine = QtWidgets.QLabel('')
        self.lbl_dual_refine.setStyleSheet('color:#606060;')
        self.lbl_dual_refine.setWordWrap(True)
        box_f.layout().addLayout(row_ref)
        box_f.layout().addWidget(self.lbl_dual_refine)
        self.dual_etas = {'P': eta_p, 'F': eta_f, 'M': eta_m}
        # Topo da aba: "Calibração" (referência, esquema da célula, passos e a varredura em frequência),
        # "Varredura" (casada em PWM, pouco usada) e abrir uma varredura salva para analisar
        top_row = QtWidgets.QHBoxLayout()
        self.dual_top_row = top_row
        self.btn_dual_pwm_panel = QtWidgets.QPushButton('Sinal x f (Hz) ▸')
        self.btn_dual_pwm_panel.setCheckable(True)
        self.btn_dual_pwm_panel.setToolTip('Varredura em frequência (calibrar e medir) e Refinar ressonância.')
        self.btn_dual_pwm_panel.toggled.connect(self.on_dual_pwm_panel)
        top_row.addWidget(self.btn_dual_pwm_panel)
        self.btn_dual_sweeps_panel = QtWidgets.QPushButton('Calibração ▸')
        self.btn_dual_sweeps_panel.setCheckable(True)
        self.btn_dual_sweeps_panel.setToolTip('Calibração do microfone com duas amostras (A e B) de materiais diferentes:\n'
                                              'medir ou abrir as duas varreduras e Gerar calibração (já sai verificada ou não).')
        self.btn_dual_sweeps_panel.toggled.connect(self.on_dual_sweeps_panel)
        self.btn_dual_open = QtWidgets.QPushButton('Abrir varredura…')
        self.btn_dual_open.setToolTip('Carrega uma varredura do Modo Duplo já salva (CSV da pasta Medidas) para analisar:\n'
                                      'calibração, ajuste com modelos, exclusão de pontos, Fitar padrão e Salvar de novo.')
        self.btn_dual_open.clicked.connect(self.open_dual_sweep)
        top_row.addWidget(self.btn_dual_open)
        top_row.addWidget(self.btn_dual_sweeps_panel)
        # Depois da Calibração: sinal × PWM (linearidade com a potência) e sinal × tempo (deriva)
        self.btn_dual_p_panel = QtWidgets.QPushButton('Sinal x PWM (%) ▸')
        self.btn_dual_p_panel.setCheckable(True)
        self.btn_dual_p_panel.setToolTip('Varredura casada em PWM: S e o OPT101 em função da potência do laser (linearidade).')
        top_row.addWidget(self.btn_dual_p_panel)
        self.btn_dual_t_panel = QtWidgets.QPushButton('Sinal x t (s) ▸')
        self.btn_dual_t_panel.setCheckable(True)
        self.btn_dual_t_panel.setToolTip('Monitora S, Δφ, OPT101 e microfone ao longo do tempo, com frequência e PWM fixos\n'
                                         '(deriva térmica, aquecimento da amostra/célula, estabilidade do laser).')
        top_row.addWidget(self.btn_dual_t_panel)
        self.btn_noise_detect2 = QtWidgets.QPushButton('Detectar ruídos de fundo...')
        self.btn_noise_detect2.setToolTip(self.btn_noise_detect.toolTip())
        self.btn_noise_detect2.clicked.connect(self.open_noise_dialog)
        top_row.addWidget(self.btn_noise_detect2)
        top_row.addStretch(1)
        # 2.5.0: as medidas viram seções do painel lateral (página 2); os botões antigos ficam escondidos e acompanham
        # as seções (o estado deles ainda decide, p.ex., se a calibração está em uso)
        dual_side = self._side_page(2)
        tools = QtWidgets.QWidget()
        tools_bar = soi_layout.FlowBar(hspace=6, vspace=4, last_right=False)
        tools.setLayout(tools_bar)
        tools_bar.setContentsMargins(0, 2, 0, 4)
        for b in (self.btn_dual_pwm_panel, self.btn_dual_sweeps_panel, self.btn_dual_p_panel, self.btn_dual_t_panel):
            b.setParent(page)
            b.setVisible(False)
        tools_bar.addWidget(self.btn_dual_open)
        tools_bar.addWidget(self.btn_noise_detect2)
        dual_side.addWidget(tools)
        dual_secs = {}
        for key, title, btn in (('dual_f', 'Sinal x f (Hz)', self.btn_dual_pwm_panel),
                                ('dual_fit', 'Ajuste', None),
                                ('dual_cal', 'Calibração', self.btn_dual_sweeps_panel),
                                ('dual_p', 'Sinal x PWM (%)', self.btn_dual_p_panel),
                                ('dual_t', 'Sinal x t (s)', self.btn_dual_t_panel)):
            sec = self._side_section(title, key, key in ('dual_f', 'dual_fit'), dual_side)
            dual_secs[key] = sec
            if btn is not None:
                btn.setChecked(sec.is_open())
                sec.toggled.connect(btn.setChecked)
                btn.toggled.connect(sec.set_open)
        # Painel "Calibração": o quadro da calibração (preenchido mais abaixo) à esquerda e a varredura em
        # frequência à direita
        self.dual_sweeps_panel = QtWidgets.QWidget()
        self.dual_cal_boxes = QtWidgets.QVBoxLayout(self.dual_sweeps_panel)
        self.dual_cal_boxes.setContentsMargins(0, 0, 0, 0)
        self.dual_box_f = box_f
        # Flutuação do ponto em medida e do último ponto (S e Δφ), embaixo dos campos
        self.lbl_dual_fluct = QtWidgets.QLabel('')
        self.lbl_dual_fluct.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_fluct.setStyleSheet('color:#404040;')
        self.lbl_dual_fluct.setToolTip('Flutuação de S = R_INMP441/R_OPT101 e de Δφ durante a medida de cada ponto: desvio-padrão\n'
                                       '(ou, se maior, a diferença entre a 1ª e a 2ª metade). Com τ adaptativo, é o que define o τ.')
        self.lbl_dual_fluct.setVisible(False)          # a flutuação vai na barra de status do topo da aba
        # Campos à esquerda e o esquema da montagem (Câmara/OPC, preenchido no quadro da calibração) à direita
        inner = QtWidgets.QWidget()
        inner.setLayout(box_f.layout())
        self.dual_box_f_h = QtWidgets.QHBoxLayout(box_f)
        self.dual_box_f_h.setContentsMargins(0, 0, 4, 2)
        self.dual_box_f_h.addWidget(inner, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        box_f.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Preferred)
        self.dual_cal_scroll = None          # 2.5.0: o painel fica na seção Calibração (o painel lateral rola)
        dual_secs['dual_cal'].add(self.dual_sweeps_panel)
        self.dual_pwm_panel = QtWidgets.QWidget()
        pbox = QtWidgets.QVBoxLayout(self.dual_pwm_panel)
        pbox.setContentsMargins(0, 0, 0, 0)
        box_m.setVisible(False)          # uma varredura em frequência só (a da calibração serve para medir)
        box_m.setParent(self.dual_pwm_panel)
        pbox.addWidget(box_f)          # sem AlignTop: Sinal x f e Ajuste com a mesma altura (a da linha)
        self.dual_manual_box = self._build_manual_sweep_box()
        self.dual_manual_box.setVisible(False)
        pbox.addWidget(self.dual_manual_box)
        box_f.setTitle('')
        dual_secs['dual_f'].add(self.dual_pwm_panel)
        # Painéis "Sinal x PWM (%)" e "Sinal x t (s)" (botões depois da Calibração)
        self.dual_p_panel = QtWidgets.QWidget()
        pp = QtWidgets.QVBoxLayout(self.dual_p_panel)
        pp.setContentsMargins(0, 0, 0, 0)
        box_p.setTitle('')
        pp.addWidget(box_p)
        pfit = self._group('Ajuste')
        pv = QtWidgets.QVBoxLayout(pfit)
        pv.setContentsMargins(6, 2, 6, 2)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel('Polinômio:'))
        self.cmb_dual_p_deg = QtWidgets.QComboBox()
        for name, d in (('Nenhum', 0), ('Grau 1 (reta)', 1), ('Grau 2', 2), ('Grau 3', 3)):
            self.cmb_dual_p_deg.addItem(name, d)
        self.cmb_dual_p_deg.setCurrentIndex(1)
        prow.addWidget(self.cmb_dual_p_deg)
        prow.addStretch(1)
        pv.addLayout(prow)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel('Ajustar:'))
        self.cmb_dual_p_target = QtWidgets.QComboBox()
        for name, k in (('INMP441 × OPT101', 'a'), ('OPT101 × PWM', 'b'), ('Os dois', 'ab')):
            self.cmb_dual_p_target.addItem(name, k)
        self.cmb_dual_p_target.setToolTip('INMP441 × OPT101: linearidade do fotoacústico com a luz (gráfico da esquerda).\n'
                                          'OPT101 × PWM: resposta do laser ao PWM (gráfico da direita).')
        prow.addWidget(self.cmb_dual_p_target)
        prow.addStretch(1)
        pv.addLayout(prow)
        self.lbl_dual_p_fit = QtWidgets.QLabel('')
        self.lbl_dual_p_fit.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_p_fit.setWordWrap(True)
        pv.addWidget(self.lbl_dual_p_fit)
        for c in (self.cmb_dual_p_deg, self.cmb_dual_p_target):
            c.currentIndexChanged.connect(lambda _: self.dual_kind == 'P' and self._show_dual_results())
        pp.addWidget(pfit)
        dual_secs['dual_p'].add(self.dual_p_panel)
        self.dual_t_panel = QtWidgets.QWidget()
        tp = QtWidgets.QVBoxLayout(self.dual_t_panel)
        tp.setContentsMargins(0, 0, 0, 0)
        tbox = self._build_time_box()
        tbox.setTitle('')
        tp.addWidget(tbox)
        dual_secs['dual_t'].add(self.dual_t_panel)
        # Barra de status no topo da aba (como nas abas dos sensores): varredura, τ e flutuação de S e Δφ
        self.lbl_dual_status = QtWidgets.QLabel('Modo Duplo: escolha uma medida (Sinal x f, Calibração, Sinal x PWM ou Sinal x t).')
        self.lbl_dual_status.setTextFormat(QtCore.Qt.TextFormat.RichText)
        # Uma linha: andamento à esquerda, flutuação de S e Δφ à direita
        self.lbl_dual_fl = QtWidgets.QLabel('')
        self.lbl_dual_fl.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_fl.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.dual_bar = QtWidgets.QFrame()
        self.dual_bar.setObjectName('dualBar')
        bar_h = QtWidgets.QHBoxLayout(self.dual_bar)
        bar_h.setContentsMargins(6, 3, 6, 3)
        self.lbl_dual_now = QtWidgets.QLabel('')         # flutuação do ponto em medida, no meio
        self.lbl_dual_now.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_now.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        for lb in (self.lbl_dual_status, self.lbl_dual_now, self.lbl_dual_fl):   # textos longos não alargam a janela
            bar_h.addWidget(soi_layout.no_widen(lb), 1)
        self.lbl_dual_fl.setToolTip('Flutuação de S = R_INMP441/R_OPT101 e de Δφ durante a medida de cada ponto: desvio-padrão\n'
                                        '(ou, se maior, a diferença entre a 1ª e a 2ª metade). Com τ adaptativo, é o que define o τ.\n'
                                        'Verde: dentro da Precisão; amarelo: até 2×; vermelho: acima.')
        self._dual_bar_color(OK_COLOR)
        lay.insertWidget(0, self.dual_bar)

        self.dual_plots = QtWidgets.QWidget()
        # Grade: lado a lado, empilhado ou sobrepostos (mesma célula), escolhido no menu do botão direito
        self.dual_plot_grid = QtWidgets.QGridLayout(self.dual_plots)
        self.dual_plot_grid.setContentsMargins(0, 0, 0, 0)
        self.dual_layout = 'side'
        self.pw_dual_a, self.pw_dual_b = pg.PlotWidget(), pg.PlotWidget()
        for pw in (self.pw_dual_a, self.pw_dual_b):
            pw.showGrid(x=True, y=True, alpha=0.3)
        self.dual_layout_actions = {}
        grp = QtGui.QActionGroup(self)
        for pw in (self.pw_dual_a, self.pw_dual_b):
            menu = pw.getPlotItem().vb.menu
            menu.addSeparator()
            sub = menu.addMenu('Arranjo dos gráficos')
            for key, name in (('side', 'Lado a lado'), ('stacked', 'Empilhado'),
                              ('overlay', 'Sobrepostos (fase no eixo da direita)')):
                act = sub.addAction(name)
                act.setCheckable(True)
                act.setChecked(key == 'side')
                grp.addAction(act)
                act.triggered.connect(lambda _=False, k=key: self.set_dual_layout(k))
                self.dual_layout_actions.setdefault(key, []).append(act)
        grp.setExclusive(False)                      # dois menus: a marcação é feita à mão em set_dual_layout
        self._place_dual_plots()
        self.c_dual_a = self.pw_dual_a.plot([], [], pen=None, symbol='o', symbolSize=7,
                                            symbolBrush='royalblue', symbolPen='royalblue')
        self.c_dual_a.setZValue(10)         # acima do fit e dos "x" vermelhos: recebe o clique
        self.c_dual_a.sigPointsClicked.connect(self._on_dual_point_clicked)
        # incerteza da calibração (verde, larga, atrás) e da medida (cinza, por cima)
        self.e_dual_a_cal = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), pen=pg.mkPen(DUAL_CAL_ERR_COLOR, width=4))
        self.pw_dual_a.addItem(self.e_dual_a_cal)
        self.e_dual_a = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), pen=pg.mkPen((120, 120, 120)))
        self.pw_dual_a.addItem(self.e_dual_a)
        self.c_dual_a_fit = self.pw_dual_a.plot([], [], pen=pg.mkPen('#e67e22', width=2,
                                                                     style=QtCore.Qt.PenStyle.DashLine))
        # Curva teórica da referência de calibração (S ∝ f^-n com o passa-altas fc do ajuste), para comparar
        self.c_dual_a_theory = self.pw_dual_a.plot([], [], pen=pg.mkPen('#7f7f7f', width=1.5,
                                                                        style=QtCore.Qt.PenStyle.DotLine))
        self.c_dual_a_bad = self.pw_dual_a.plot([], [], pen=None, symbol='x', symbolSize=12,
                                                symbolBrush='#d00000', symbolPen=pg.mkPen('#d00000', width=2))
        self.c_dual_b = self.pw_dual_b.plot([], [], pen=pg.mkPen('firebrick', width=1.5), symbol='s', symbolSize=6,
                                            symbolBrush='firebrick', symbolPen='firebrick')
        # Fora da faixa da calibração aplicada: pontos vazados (corrigidos pelo valor da borda) e fundo avermelhado
        self.c_dual_a_out = self.pw_dual_a.plot([], [], pen=None, symbol='o', symbolSize=7, symbolBrush=None,
                                                symbolPen=pg.mkPen(DUAL_OUT_CAL_COLOR, width=1.5))
        self.c_dual_b_out = self.pw_dual_b.plot([], [], pen=None, symbol='s', symbolSize=6, symbolBrush=None,
                                                symbolPen=pg.mkPen(DUAL_OUT_CAL_COLOR, width=1.5))
        self.rg_dual_out = []
        for pw in (self.pw_dual_a, self.pw_dual_b):
            for _ in range(2):
                rg = pg.LinearRegionItem(values=(0, 1), movable=False, brush=pg.mkBrush(230, 60, 50, 38),
                                         pen=pg.mkPen(None))
                rg.setZValue(-10)
                rg.setVisible(False)
                pw.addItem(rg, ignoreBounds=True)
                self.rg_dual_out.append((pw, rg))
        self.e_dual_b_cal = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), pen=pg.mkPen(DUAL_CAL_ERR_COLOR, width=4))
        self.pw_dual_b.addItem(self.e_dual_b_cal)
        self.e_dual_b = pg.ErrorBarItem(x=np.empty(0), y=np.empty(0), pen=pg.mkPen((120, 120, 120)))
        self.pw_dual_b.addItem(self.e_dual_b)
        self.c_dual_b_fit = self.pw_dual_b.plot([], [], pen=pg.mkPen('#e67e22', width=2,
                                                                     style=QtCore.Qt.PenStyle.DashLine))
        # Linha que quebra em vez de alargar a janela quando aparecem os avisos (ex.: Ressonância deslocada)
        excl_bar = soi_layout.FlowBar(hspace=12, vspace=3, last_right=False)
        excl_row = excl_bar.group()
        excl_hint = QtWidgets.QLabel('Clique num ponto para tirá-lo do ajuste.')
        excl_hint.setToolTip('Clique num ponto do gráfico da esquerda para tirá-lo do ajuste; clique de novo para incluí-lo.')
        excl_hint.setStyleSheet('color:#606060;')
        excl_row.addWidget(excl_hint)
        self.btn_dual_incl = QtWidgets.QPushButton('Incluir todos')
        self.btn_dual_incl.setToolTip('Volta a usar no ajuste todos os pontos excluídos com clique.')
        self.btn_dual_incl.clicked.connect(self._dual_include_all)
        self.btn_dual_incl.setEnabled(False)
        excl_row.addWidget(self.btn_dual_incl)
        self.btn_dual_resave = QtWidgets.QPushButton('Salvar de novo')
        self.btn_dual_resave.setToolTip('Grava CSV e PNG novos (sufixo _editado) com o ajuste, os pontos excluídos e a\n'
                                        'calibração atuais. O arquivo salvo no fim da varredura não é alterado.')
        self.btn_dual_resave.clicked.connect(lambda: self._export_dual(resave=True))
        self.btn_dual_resave.setEnabled(False)
        excl_row.addWidget(self.btn_dual_resave)
        self.btn_dual_diag = QtWidgets.QPushButton('Diagnóstico')
        self.btn_dual_diag.setCheckable(True)
        self.btn_dual_diag.setToolTip(
            'Varredura em frequência: separa o sinal fotoacústico (S ∝ f^-n, fase constante) de um fundo plano\n'
            '(luz chegando ao microfone, chiado do driver, acoplamento elétrico), ajustando amplitude e fase juntas,\n'
            'com o passa-alta do microfone, o atraso do sistema e a ressonância da célula. Desenha as componentes\n'
            '(vermelho: fotoacústico; roxo: fundo; preto: soma) e diz o que encontrou. Leva alguns segundos.')
        self.btn_dual_diag.toggled.connect(lambda _: self._show_dual_results())
        self.btn_dual_diag.setEnabled(False)
        excl_row.addWidget(self.btn_dual_diag)
        excl_row = excl_bar.group()
        self.chk_dual_norm = QtWidgets.QCheckBox('Normalizar pelo OPT101')
        self.chk_dual_norm.setChecked(True)
        self.chk_dual_norm.setToolTip(
            'Varredura em frequência. Marcado: S = R_INMP441 / R_OPT101 e Δφ = φ_INMP441 − φ_OPT101 (desconta a\n'
            'variação da potência e da fase da luz com a frequência). Desmarcado: só o INMP441 (R e fase brutos).\n'
            'Fitar padrão, gerar calibração e aplicar a calibração pedem a normalização. Os CSV guardam sempre os dois sensores.')
        self.chk_dual_norm.toggled.connect(lambda _: self._show_dual_results())
        excl_row.addWidget(self.chk_dual_norm)
        self.chk_dual_sensors = QtWidgets.QCheckBox('Mostrar sinais de cada sensor')
        self.chk_dual_sensors.setToolTip('Mostra abaixo, além da curva principal, a amplitude R e a fase de cada sensor\n'
                                         '(INMP441 e OPT101) em função da variável da varredura.')
        self.chk_dual_sensors.toggled.connect(self._on_dual_sensors)
        excl_row.addWidget(self.chk_dual_sensors)
        # O quadro flutuante "Resultados" saiu (17/11): os avisos dele ficam aqui, num indicador com o texto no tooltip
        self.lbl_dual_warn = QtWidgets.QLabel('')
        self.lbl_dual_warn.setStyleSheet(f'color:{LOWF_WARN_COLOR};font-weight:bold;')
        self.lbl_dual_warn.setVisible(False)
        excl_bar.group().addWidget(self.lbl_dual_warn)
        # Textos informativos que ficavam no quadro "Resultados" (Diagnóstico, Sinal x t, ajuste do PWM, pontos
        # excluídos...): indicador "ℹ Resultados", com o texto no tooltip
        self.lbl_dual_info = QtWidgets.QLabel('')
        self.lbl_dual_info.setStyleSheet('color:#1f4e9c;font-weight:bold;')
        self.lbl_dual_info.setVisible(False)
        excl_bar.group().addWidget(self.lbl_dual_info)
        # Ressonância da medida longe da calibração (ou só numa delas): aviso vermelho bem visível
        self.lbl_dual_res_shift = QtWidgets.QLabel('')
        self.lbl_dual_res_shift.setStyleSheet('color:white;background:#d00000;font-weight:bold;'
                                              'padding:2px 8px;border-radius:3px;')
        self.lbl_dual_res_shift.setVisible(False)
        excl_bar.group().addWidget(self.lbl_dual_res_shift)
        lay.addLayout(excl_bar)
        lay.addWidget(self.dual_plots, 1)
        # Sinais de cada sensor (recolhível): amplitude relativa (÷ mediana) e fase de cada um
        self.dual_sensor_plots = QtWidgets.QWidget()
        sl = QtWidgets.QHBoxLayout(self.dual_sensor_plots)
        sl.setContentsMargins(0, 0, 0, 0)
        self.pw_dual_c, self.pw_dual_d = pg.PlotWidget(), pg.PlotWidget()
        # Zoom/arraste à mão num gráfico do Modo Duplo: a faixa fica como o usuário deixou até um duplo clique ou
        # uma nova medida (sem isso, cada ponto novo refazia o ajuste automático)
        self.dual_view_manual = False
        for pw in (self.pw_dual_a, self.pw_dual_b, self.pw_dual_c, self.pw_dual_d):
            pw.getPlotItem().vb.sigRangeChangedManually.connect(
                lambda *_: setattr(self, 'dual_view_manual', True))
        for pw in (self.pw_dual_c, self.pw_dual_d):
            pw.showGrid(x=True, y=True, alpha=0.3)
            pw.addLegend(offset=(10, 10))
            sl.addWidget(pw, 1)
        self.pw_dual_c.setTitle('Amplitude de cada sensor (R ÷ mediana da varredura)')
        self.pw_dual_c.setLabel('left', 'R relativo')
        self.pw_dual_d.setTitle('Fase de cada sensor (desenrolada)')
        self.pw_dual_d.setLabel('left', 'fase (graus)')
        sty = {'INMP441': ('#c0392b', 'o'), 'OPT101': ('#1f77b4', 's')}
        self.c_dual_sens = {}
        for name, (col, sym) in sty.items():
            self.c_dual_sens[name] = (
                self.pw_dual_c.plot([], [], pen=pg.mkPen(col, width=1.5), symbol=sym, symbolSize=5,
                                    symbolBrush=col, symbolPen=col, name=name),
                self.pw_dual_d.plot([], [], pen=pg.mkPen(col, width=1.5), symbol=sym, symbolSize=5,
                                    symbolBrush=col, symbolPen=col, name=name))
        self.dual_sensor_plots.setVisible(False)
        lay.addWidget(self.dual_sensor_plots, 1)
        # Aviso enquanto não há resultados (posição fixa em pixels, como o texto do fit da FFT)
        self.txt_dual_empty = []
        for pw in (self.pw_dual_a, self.pw_dual_b):
            t = pg.TextItem('Sem dados: escolha uma medida no painel à esquerda e clique em ▶ Varredura.',
                            color=(110, 110, 110), anchor=(0, 0))
            vb = pw.getPlotItem().vb
            t.setParentItem(vb)
            t.setPos(12, 12)
            vb.sigResized.connect(lambda v, t=t: t.setTextWidth(max(100.0, v.rect().width() - 24)))   # quebra a linha
            self.txt_dual_empty.append(t)

        # Calibração do microfone em passos numerados, num painel recolhível. A referência escolhida define a
        # curva teórica (S ∝ f^-n, fase constante) e a célula (OPC ou câmara) em que a calibração vale.
        self.btn_dual_cal_panel = QtWidgets.QPushButton('Calibração do microfone ▸')
        self.btn_dual_cal_panel.setCheckable(True)
        self.btn_dual_cal_panel.setToolTip(
            'Mostra ou esconde a calibração do microfone.\n'
            'Escolha a referência (padrão de calibração): ela define a curva teórica esperada e a célula (OPC ou câmara).\n'
            'Com o painel fechado, "Fitar padrão" não é aplicado.')
        self.btn_dual_cal_panel.toggled.connect(self.on_dual_cal_panel)
        self.btn_dual_cal_panel.setParent(page)
        self.btn_dual_cal_panel.setVisible(False)      # o estado segue o botão "Calibração" do topo
        cal_box = QtWidgets.QWidget()
        cal_box.setToolTip('Calibração do microfone com duas amostras (A e B) de materiais diferentes.')
        self.dual_cal_box = cal_box
        # Passos à esquerda (amostras A e B, medir ou abrir, gerar); esquema da montagem à direita
        cal_h = QtWidgets.QHBoxLayout(cal_box)
        cal_h.setContentsMargins(0, 0, 0, 0)
        cal_v = QtWidgets.QVBoxLayout()
        cal_v.setSpacing(2)
        cal_h.addLayout(cal_v, 1)
        # Widgets da calibração antiga com uma referência (fora do layout, nunca exibidos): mantidos para as
        # preferências salvas e para o código que ainda lê a referência (_cal_ref segue a célula)
        self.cmb_cal_ref = QtWidgets.QComboBox()
        for key, ref in CAL_REFS.items():
            self.cmb_cal_ref.addItem(ref['name'], key)
        self.lbl_cal_L, self.lbl_cal_alpha, self.lbl_cal_n = QtWidgets.QLabel(), QtWidgets.QLabel(), QtWidgets.QLabel()
        self.sp_cal_L = self._dspin(0.1, 100000.0, 12.0, 1, 1.0, None, 100, ' µm')
        self.sp_cal_alpha = self._dspin(0.001, 10.0, 0.97, 3, 0.01, None, 110, ' cm²/s')
        self.sp_cal_n = self._dspin(0.0, 3.0, 1.0, 2, 0.05, None, 80)
        self.cal_slots = {'A': None, 'B': None}     # varreduras guardadas de cada amostra
        self.cal_pending = None                     # 'A' ou 'B' enquanto "Medir" roda a varredura
        self.cmb_cal_s, self.sp_cal_s_L, self.lbl_cal_s_state = {}, {}, {}
        thick_tip = ('Espessura da amostra. Câmara (mm): deve ser ≥ 2μ na frequência mínima, μ = √(α/πf).\n'
                     'OPC (µm): a folha deve ser termicamente fina, f_c = α/(πL²) ≥ 10× a frequência máxima.')
        for slot in ('A', 'B'):
            # 2.5.0: cada amostra em três linhas (material e espessura; Medir/Usar/Abrir; estado)
            grid = QtWidgets.QGridLayout()
            grid.setContentsMargins(0, 4 if slot == 'B' else 0, 0, 0)
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(2)
            grid.setColumnStretch(1, 1)
            cal_v.addLayout(grid)
            grid.addWidget(QtWidgets.QLabel(f'<b>Amostra {slot}:</b>'), 0, 0)
            cmb = QtWidgets.QComboBox()
            cmb.setMinimumWidth(110)
            cmb.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cmb.setMinimumContentsLength(10)
            cmb.setToolTip('Material da amostra A (filtrado pela célula escolhida no topo).' if slot == 'A' else
                           'Material da amostra B. Verde: indicado para o par com a amostra A (α ou f_c pelo menos '
                           f'{CAL_PAIR_MIN_RATIO:g}× diferente).\nVermelho: não indicado (o motivo aparece sobre cada item); '
                           'pode ser usado, mas a calibração sai com aviso.')
            grid.addWidget(cmb, 0, 1, 1, 2)
            self.cmb_cal_s[slot] = cmb
            grid.addWidget(QtWidgets.QLabel('espessura:'), 1, 0)
            sp = self._dspin(0.001, 100000.0, 5.0, 3, 0.5, lambda _: self._on_cal_samples(fill=False), 100, ' mm')
            sp.setToolTip(thick_tip)
            grid.addWidget(sp, 1, 1)
            self.sp_cal_s_L[slot] = sp
            brow = QtWidgets.QHBoxLayout()
            grid.addLayout(brow, 2, 0, 1, 3)
            btn = QtWidgets.QPushButton(f'▶ Medir {slot}')
            btn.setToolTip(f'Roda a varredura em frequência (parâmetros da calibração) com a amostra {slot} montada e a '
                           f'guarda como amostra {slot}.\nTroque de amostra sem mexer em mais nada (laser, foco, janela, vedação).')
            btn.clicked.connect(lambda _=False, sl=slot: self._cal_measure(sl))
            brow.addWidget(btn)
            setattr(self, f'btn_cal_measure_{slot.lower()}', btn)
            btn = QtWidgets.QPushButton('Usar a atual')
            btn.setToolTip(f'Guarda como amostra {slot} a varredura em frequência que está na tela (medida ou aberta).')
            btn.clicked.connect(lambda _=False, sl=slot: self._cal_take(sl))
            brow.addWidget(btn)
            btn = QtWidgets.QPushButton('Abrir…')
            btn.setToolTip(f'Usa como amostra {slot} uma varredura em frequência já salva (arquivo *DUPLO_freq_*.csv).')
            btn.clicked.connect(lambda _=False, sl=slot: self._cal_open(sl))
            brow.addWidget(btn)
            lbl = QtWidgets.QLabel('—')
            lbl.setStyleSheet('color:#606060;')
            lbl.setWordWrap(True)
            grid.addWidget(lbl, 3, 0, 1, 3)
            self.lbl_cal_s_state[slot] = lbl
        self.cmb_cal_a, self.cmb_cal_b = self.cmb_cal_s['A'], self.cmb_cal_s['B']
        self.sp_cal_a_L, self.sp_cal_b_L = self.sp_cal_s_L['A'], self.sp_cal_s_L['B']
        self.cmb_cal_a.currentIndexChanged.connect(lambda _: self._on_cal_samples(fill_b=True))
        self.cmb_cal_b.currentIndexChanged.connect(lambda _: self._on_cal_samples(fill=False))
        self.lbl_cal_ref_info = QtWidgets.QLabel('')
        self.lbl_cal_ref_info.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_cal_ref_info.setWordWrap(True)
        cal_v.addWidget(self.lbl_cal_ref_info)
        # 2.5.0 (Marcos, 25/11): sem o esquema da montagem e sem as dicas de montagem; os widgets continuam (fora da
        # tela) porque _on_cal_samples ainda os atualiza
        self.cal_schematic = CellSchematic()
        self.lbl_cal_tips = QtWidgets.QLabel('')
        # Widgets do antigo "Fitar padrão" (fora do layout): a calibração agora é M = S·fⁿ, sem ajuste de modelo,
        # e a faixa com S ∝ f⁻ⁿ é procurada no painel Ajuste
        self.chk_dual_std = QtWidgets.QCheckBox()
        self.chk_dual_std.setChecked(True)
        self.chk_dual_std_phase = QtWidgets.QCheckBox()
        self.sp_dual_std_fmin = self._dspin(0.0, 5000.0, 0.0, 0, 10.0, None, 90, ' Hz')
        self.sp_dual_std_fmax = self._dspin(0.0, 5000.0, 0.0, 0, 10.0, None, 90, ' Hz')
        frow = QtWidgets.QHBoxLayout()
        cal_v.addLayout(frow)
        self.lbl_cal_steps = QtWidgets.QLabel(
            'Monte a <b>A</b> como no esquema (quadro Varredura) e clique em <b>Medir A</b>; troque pela <b>B</b> sem mexer em mais nada e '
            'clique em <b>Medir B</b>; depois, <b>Gerar calibração</b> (verificada se a razão A/B for constante em ≥ 1 década).')
        self.lbl_cal_steps.setWordWrap(True)          # 2.5.0: texto de instruções fora da tela (Marcos, 25/11)
        frow = QtWidgets.QVBoxLayout()           # 2.5.0: Gerar calibração e as opções, uma por linha
        frow.setContentsMargins(0, 4, 0, 0)
        cal_v.addLayout(frow)
        self.btn_dual_adv = QtWidgets.QPushButton('Avançado ▸')
        self.btn_dual_adv.setCheckable(True)
        self.btn_dual_adv.setFlat(True)
        self.btn_dual_adv.setToolTip('Correção do polo do OPT101: só é necessária se você trocar o resistor de\n'
                                     'realimentação do OPT101 entre a calibração e a medida.')
        # Linha avançada (oculta): τ do sensor OPT101
        self.dual_adv_row = QtWidgets.QWidget()
        arow = soi_layout.FlowBar(hspace=6, vspace=3, last_right=False)
        self.dual_adv_row.setLayout(arow)
        arow.setContentsMargins(0, 0, 0, 0)
        tau_tip = ('Polo do OPT101, que depende do resistor de realimentação. É descontado do OPT101 antes de S e Δφ:\n'
                   'fase + atan(2π·f·τ) e amplitude × √(1 + (2π·f·τ)²).\n'
                   'Não precisa ser calibrado no uso normal: com o mesmo resistor na calibração e na medida, a calibração\n'
                   'do microfone já absorve esse polo. Preencha só se trocar o resistor (0 = sem correção), e então\n'
                   'gere a calibração de novo com o mesmo valor.\n'
                   'Medir…: compara a varredura em frequência atual com outra já salva (mesma luz, outro resistor) e preenche τ.\n'
                   'O atraso do driver/laser não entra aqui: é comum ao microfone e se cancela em Δφ.')
        lbl = QtWidgets.QLabel('τ do sensor OPT101:')
        lbl.setToolTip(tau_tip)
        arow.addWidget(lbl)
        self.sp_dual_tau_sensor = self._dspin(0.0, 500.0, 0.0, 2, 0.5, lambda _: self._show_dual_results(), 110, ' µs')
        self.sp_dual_tau_sensor.setSpecialValueText('0 (sem correção)')
        self.sp_dual_tau_sensor.setToolTip(tau_tip)
        arow.addWidget(self.sp_dual_tau_sensor)
        self.btn_dual_tau_measure = QtWidgets.QPushButton('Medir…')
        self.btn_dual_tau_measure.setToolTip(tau_tip)
        self.btn_dual_tau_measure.clicked.connect(self.measure_sensor_tau)
        arow.addWidget(self.btn_dual_tau_measure)
        hint = QtWidgets.QLabel('Só se trocar o resistor do OPT101 entre a calibração e a medida; '
                                'com o mesmo resistor, deixe 0.')
        hint.setStyleSheet('color:#606060;')
        hint.setWordWrap(True)
        self.dual_adv_row.setVisible(False)
        self.btn_dual_adv.toggled.connect(self._on_dual_adv)
        # Botões da calibração com uma referência (fora do layout): o fluxo agora é o de duas amostras
        self.btn_dual_cal = QtWidgets.QPushButton()
        self.btn_dual_cal.setEnabled(False)
        self.btn_cal_verify = QtWidgets.QPushButton()
        self.btn_cal_verify.setEnabled(False)
        self.btn_cal_make = QtWidgets.QPushButton('Gerar calibração')
        self.btn_cal_make.setToolTip(
            'Disponível com as varreduras das amostras A e B.\n\n'
            'As duas seguem S = K·H(f)·f⁻ⁿ (n = 1 na câmara, 1,5 no OPC), com K da amostra e H(f) do sistema\n'
            'microfone + célula. A razão S_A/S_B deve ser constante (amplitude e fase): a maior faixa em que isso vale\n'
            f'é a verificação (|inclinação| ≤ {CAL_N_TOL:g}, ≤ {CAL_VER_DB:g} dB rms, fase ± {CAL_VER_DEG:g}° rms, ≥ 1 década).\n'
            'A calibração é M(f) = √(S_A·S_B)·fⁿ normalizada pela faixa plana, e a fase do sistema é a média das duas.\n'
            'Salva CSV e PNG na pasta Medidas (prefixo CAL_), já marcada como verificada ou não.')
        self.btn_cal_make.setEnabled(False)
        self.btn_cal_make.clicked.connect(self._make_two_sample_calibration)
        frow.addWidget(self.btn_cal_make)
        self.lbl_flat_tol = QtWidgets.QLabel('Faixa plana ±')
        self.sp_dual_flat_tol = QtWidgets.QDoubleSpinBox()
        self.sp_dual_flat_tol.setRange(0.1, 6.0)
        self.sp_dual_flat_tol.setDecimals(1)
        self.sp_dual_flat_tol.setSingleStep(0.5)
        self.sp_dual_flat_tol.setValue(1.0)
        self.sp_dual_flat_tol.setSuffix(' dB')
        self.sp_dual_flat_tol.setToolTip('Tolerância para a faixa em que a sensibilidade do microfone é constante '
                                         '(±1 dB ≈ ±12 %). A calibração procura o maior trecho de frequências dentro dela.')
        g_flat = arow.group()                                         # tolerância da faixa plana: no Avançado
        g_flat.addWidget(self.lbl_flat_tol)
        g_flat.addWidget(self.sp_dual_flat_tol)
        adv_v = QtWidgets.QWidget()
        adv_l = QtWidgets.QVBoxLayout(adv_v)
        adv_l.setContentsMargins(0, 0, 0, 0)
        adv_l.addWidget(self.dual_adv_row)
        adv_l.addWidget(hint)
        self.dual_adv_row.setVisible(True)
        self.dual_adv_row = adv_v               # o conjunto (linha + dica) aparece e some junto
        self.dual_adv_row.setVisible(False)
        # "Avançado" saiu da tela (17/11): a linha do τ do sensor só aparece se houver um τ salvo (≠ 0)
        self.btn_dual_adv.setVisible(False)
        self.chk_dual_cal_err = QtWidgets.QCheckBox('Mostrar barra de erro da calibração')
        self.chk_dual_cal_err.setChecked(False)
        self.chk_dual_cal_err.setToolTip('Barras verdes (±1 DP da calibração aplicada) atrás das barras cinza da medida.')
        self.chk_dual_cal_err.toggled.connect(lambda _: self._show_dual_results())
        frow.addWidget(self.chk_dual_cal_err)
        self.chk_dual_out_red = QtWidgets.QCheckBox('Região não calibrada em vermelho')
        self.chk_dual_out_red.setChecked(False)
        self.chk_dual_out_red.setToolTip('Fundo avermelhado nos gráficos de S e Δφ fora da faixa da calibração aplicada, e os\n'
                                         'pontos dessa região em vermelho. Desligado: os pontos aparecem vazados, na cor normal.\n'
                                         'Nos dois casos eles usam a correção da borda e ficam fora dos ajustes.')
        self.chk_dual_out_red.toggled.connect(lambda _: (self._dual_cal_regions(self._applied_cal()
                                                                                if self.dual_kind == 'F' else None),
                                                         self._show_dual_results()))
        frow.addWidget(self.chk_dual_out_red)
        self.lbl_cal_verify = QtWidgets.QLabel('')
        self.lbl_cal_verify.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_cal_verify.setWordWrap(True)
        cal_v.addWidget(self.lbl_cal_verify)
        cal_v.addWidget(self.dual_adv_row)
        self.dual_cal_boxes.addWidget(cal_box, 1)

        # Ajuste da varredura em frequência com modelos físicos conhecidos (painel recolhível)
        self.btn_dual_model_panel = QtWidgets.QPushButton('Ajuste ▸')
        self.btn_dual_model_panel.setCheckable(True)
        self.btn_dual_model_panel.setToolTip('Ajusta a varredura em frequência (magnitude, fase ou as duas) com modelos\n'
                                             'físicos de célula aberta. Use com a calibração aplicada ("Usar").')
        self.btn_dual_model_panel.toggled.connect(self.on_dual_model_panel)
        # Sem botão próprio (2.3.0): o quadro fica à direita do Sinal x f e o ajuste vale sempre que há um modelo
        self.btn_dual_model_panel.setParent(page)
        self.btn_dual_model_panel.setVisible(False)
        self.btn_dual_model_panel.blockSignals(True)
        self.btn_dual_model_panel.setChecked(True)
        self.btn_dual_model_panel.blockSignals(False)
        self.dual_model_box = QtWidgets.QWidget()
        mv = QtWidgets.QVBoxLayout(self.dual_model_box)
        mv.setContentsMargins(0, 0, 0, 0)
        mgrid = QtWidgets.QGridLayout()
        mgrid.setColumnStretch(1, 1)
        mv.addLayout(mgrid)
        mgrid.addWidget(QtWidgets.QLabel('Modelo:'), 0, 0)
        self.cmb_dual_model = QtWidgets.QComboBox()
        self.cmb_dual_model.addItem('Nenhum', None)
        for key, name in FREQ_MODELS.items():
            self.cmb_dual_model.addItem(name, key)
            self.cmb_dual_model.setItemData(self.cmb_dual_model.count() - 1, FREQ_MODEL_TIPS[key],
                                            QtCore.Qt.ItemDataRole.ToolTipRole)
        self.cmb_dual_model.currentIndexChanged.connect(self._on_dual_model)
        # não alarga o quadro Ajuste pelo nome mais longo de modelo (a janela passava da largura da tela, 19/11)
        self.cmb_dual_model.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_dual_model.setMinimumContentsLength(14)
        self.cmb_dual_model.view().setMinimumWidth(self.cmb_dual_model.view().sizeHintForColumn(0) + 20)
        mgrid.addWidget(self.cmb_dual_model, 0, 1)
        mgrid.addWidget(QtWidgets.QLabel('Ajustar:'), 1, 0)
        self.cmb_dual_model_target = QtWidgets.QComboBox()
        for name, key in (('Fase', 'phase'), ('Magnitude', 'mag'), ('Fase e magnitude', 'both')):
            self.cmb_dual_model_target.addItem(name, key)
        self.cmb_dual_model_target.setToolTip(
            'Fase: em geral a grandeza mais robusta (não depende da escala da luz nem da absorção da amostra).\n'
            'Magnitude: sensível a desvios de amplitude da referência e da calibração.\n'
            'Na lei de potência só a magnitude é ajustada (o modelo tem fase constante).')
        self.cmb_dual_model_target.currentIndexChanged.connect(lambda _: self._show_dual_results())
        self.cmb_dual_model_target.setEnabled(False)       # habilitado ao escolher um modelo (_on_dual_model)
        mgrid.addWidget(self.cmb_dual_model_target, 1, 1)
        mgrid.addWidget(QtWidgets.QLabel('Espessura L:'), 2, 0)
        self.sp_dual_thick = self._dspin(0.0, 100000.0, 0.0, 1, 10.0, lambda _: self._show_dual_results(), 110, ' µm')
        self.sp_dual_thick.setSpecialValueText('não informada')
        self.sp_dual_thick.setToolTip('Espessura da amostra (meça com micrômetro). Com ela, a difusividade térmica sai\n'
                                      'de f1: α = π·f1·L². Referências: Ti puro ≈ 9,3e-6 m²/s; Ti-6Al-4V ≈ 2,9e-6 m²/s;\n'
                                      'aço inox ≈ 4e-6 m²/s; alumínio ≈ 9,7e-5 m²/s; cobre ≈ 1,1e-4 m²/s.')
        mgrid.addWidget(self.sp_dual_thick, 2, 1)
        self.lbl_dual_model_n = QtWidgets.QLabel('n esperado:')
        mgrid.addWidget(self.lbl_dual_model_n, 3, 0)
        self.sp_dual_model_n = self._dspin(0.0, 3.0, 1.0, 2, 0.5, lambda _: self._show_dual_results(), 70)
        self.sp_dual_model_n.setToolTip('Expoente esperado da amostra: 1 (opaca na câmara) ou 1,5 (folha fina em OPC).')
        mgrid.addWidget(self.sp_dual_model_n, 3, 1)
        self.lbl_dual_model_n.setVisible(False)
        self.sp_dual_model_n.setVisible(False)
        mrow = QtWidgets.QHBoxLayout()
        mrow.addWidget(QtWidgets.QLabel('Faixa: de'))
        range_tip = ('Limita o ajuste do modelo a esta faixa de frequência (os outros pontos continuam no gráfico).\n'
                     'Use quando o modelo só vale numa região da varredura. Pontos excluídos com clique também\n'
                     'ficam fora. A curva verde é desenhada só na faixa ajustada.')
        self.sp_dual_model_f0 = self._dspin(0.0, 5000.0, 0.0, 1, 1.0, lambda _: self._show_dual_results(), 90, ' Hz')
        self.sp_dual_model_f0.setSpecialValueText('início')
        self.sp_dual_model_f1 = self._dspin(0.0, 5000.0, 0.0, 1, 10.0, lambda _: self._show_dual_results(), 90, ' Hz')
        self.sp_dual_model_f1.setSpecialValueText('fim')
        for sp in (self.sp_dual_model_f0, self.sp_dual_model_f1):
            sp.setToolTip(range_tip)
        mrow.addWidget(self.sp_dual_model_f0)
        mrow.addWidget(QtWidgets.QLabel('a'))
        mrow.addWidget(self.sp_dual_model_f1)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        mrow = QtWidgets.QHBoxLayout()
        self.btn_dual_peak = QtWidgets.QPushButton('Marcar pico (2 cliques)')
        self.btn_dual_peak.setCheckable(True)
        self.btn_dual_peak.setToolTip('Para o modelo de ressonância: clique no gráfico da esquerda um pouco abaixo e um pouco\n'
                                      'acima do pico; os dois cliques preenchem a Faixa. Com a Faixa vazia (início/fim),\n'
                                      'o pico é achado sozinho.')
        self.btn_dual_peak.toggled.connect(self._on_dual_peak_mode)
        self.btn_dual_peak.setEnabled(False)
        mrow.addWidget(self.btn_dual_peak)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        # Aviso (os ajustes continuam permitidos, p.ex. durante o desenvolvimento)
        self.lbl_dual_model_nocal = QtWidgets.QLabel(
            '⚠ Calibração não aplicada ("Usar" desmarcado na linha de cima): os modelos só fazem sentido com o sinal '
            'calibrado. O ajuste é feito assim mesmo, sobre o sinal bruto.')
        self.lbl_dual_model_nocal.setStyleSheet(f'color:{LOWF_WARN_COLOR};font-weight:bold;')
        self.lbl_dual_model_nocal.setWordWrap(True)
        # quebra na largura do quadro (não o alarga)
        self.lbl_dual_model_nocal.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                                QtWidgets.QSizePolicy.Policy.MinimumExpanding)
        mv.addWidget(self.lbl_dual_model_nocal)
        self.chk_mic_cal.toggled.connect(lambda _: self._update_model_nocal())
        self.chk_dual_norm.toggled.connect(lambda _: self._update_model_nocal())
        self._update_model_nocal()
        self.lbl_dual_model = QtWidgets.QLabel('')
        self.lbl_dual_model.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_model.setWordWrap(True)
        mv.addWidget(self.lbl_dual_model)
        dual_secs['dual_fit'].add(self.dual_model_box)
        self.dual_model_txt = None
        pen_model = pg.mkPen('#2e7d32', width=2, style=QtCore.Qt.PenStyle.DashLine)
        self.c_dual_a_model = self.pw_dual_a.plot([], [], pen=pen_model)
        self.c_dual_b_model = self.pw_dual_b.plot([], [], pen=pen_model)
        self.reg_dual = []
        for pw in (self.pw_dual_a, self.pw_dual_b):        # faixa encontrada pelo modelo "Faixa com S ∝ f⁻ⁿ"
            reg = pg.LinearRegionItem((0, 1), movable=False, brush=pg.mkBrush(46, 125, 50, 35),
                                      pen=pg.mkPen(46, 125, 50, 110))
            reg.setZValue(-10)
            reg.setVisible(False)
            pw.addItem(reg, ignoreBounds=True)
            self.reg_dual.append(reg)
        self.ln_dual_break = pg.InfiniteLine(angle=90, pen=pg.mkPen('#2e7d32', width=1, style=QtCore.Qt.PenStyle.DotLine))
        self.ln_dual_break.setVisible(False)
        self.pw_dual_a.addItem(self.ln_dual_break, ignoreBounds=True)
        self.dual_peak_clicks = None        # lista de frequências enquanto "Marcar pico" está ativo
        self.pw_dual_a.scene().sigMouseClicked.connect(self._on_dual_plot_clicked)
        self.lbl_dual_tau = QtWidgets.QLabel('')
        self.lbl_dual_tau.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_tau.setWordWrap(True)
        lay.addWidget(self.lbl_dual_tau)
        self.lbl_dual_fit = QtWidgets.QLabel('')
        self.lbl_dual_fit.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_fit.setWordWrap(True)
        lay.addWidget(self.lbl_dual_fit)
        self.lbl_dual_diag = QtWidgets.QLabel('')
        self.lbl_dual_diag.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_diag.setWordWrap(True)
        self.lbl_dual_diag.setVisible(False)
        lay.addWidget(self.lbl_dual_diag)
        self.dual_diag = None               # (chave dos dados, resultado de diagnose_freq)
        self.dual_diag_txt = None
        pen = lambda c, st: pg.mkPen(c, width=2, style=st)
        D, S_ = QtCore.Qt.PenStyle.DashLine, QtCore.Qt.PenStyle.SolidLine
        self.c_dual_diag = (self.pw_dual_a.plot([], [], pen=pen('#202020', S_)),
                            self.pw_dual_a.plot([], [], pen=pen('#c0392b', D)),
                            self.pw_dual_a.plot([], [], pen=pen('#8e44ad', D)),
                            self.pw_dual_b.plot([], [], pen=pen('#202020', S_)))
        # Legendas do Diagnóstico (só aparecem com ele ligado)
        self.dual_diag_leg = tuple(pw.getPlotItem().addLegend(offset=(-10, 10), brush=(255, 255, 255, 220),
                                                              pen=(160, 160, 160))
                                   for pw in (self.pw_dual_a, self.pw_dual_b))
        for lg in self.dual_diag_leg:
            lg.setVisible(False)
        self.lbl_dual_cal = QtWidgets.QLabel('')
        self.lbl_dual_cal.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_dual_cal.setWordWrap(True)
        lay.addWidget(self.lbl_dual_cal)
        self.dual_cal = None
        # Gráficos em cima e, embaixo, os resultados em texto (os painéis abrem no topo da aba)
        idx = lay.indexOf(self.dual_plots)
        taken = [lay.takeAt(idx) for _ in range(lay.count() - idx)]
        results = (self.lbl_dual_fit, self.lbl_dual_diag, self.lbl_dual_cal, self.lbl_dual_tau)
        top = QtWidgets.QWidget()
        tv = QtWidgets.QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(self.dual_plots, 1)
        tv.addWidget(self.dual_sensor_plots, 1)
        bottom = QtWidgets.QWidget()
        bv = QtWidgets.QVBoxLayout(bottom)
        bv.setContentsMargins(0, 2, 4, 0)
        # Resultados num quadro flutuante sobre os gráficos (arrastável): os gráficos ficam fixos
        self.dual_float = FloatingResults(self.dual_plots, results, on_texts=self._dual_warn_texts)
        for it in taken:
            wdg, sub = it.widget(), it.layout()
            if wdg is not None and wdg not in results and wdg not in (self.dual_plots, self.dual_sensor_plots):
                bv.addWidget(wdg)
            elif sub is not None:
                bv.addLayout(sub)
        # Embaixo só há texto: ele ocupa a altura que precisa e os gráficos ficam com o resto da tela
        bottom.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        top.setMinimumHeight(220)
        lay.addWidget(top, 1)
        lay.addWidget(bottom, 0)
        tabs.addTab(page, 'Modo Duplo')

        for sb in (self.sp_dual_p0, self.sp_dual_p1, self.sp_dual_dp,
                   self.sp_dual_f0, self.sp_dual_f1, self.sp_dual_fn,
                   self.sp_dual_m_f0, self.sp_dual_m_f1, self.sp_dual_m_fn):
            sb.valueChanged.connect(self.update_dual_eta)
        self.cmb_dual_fspace.currentIndexChanged.connect(self.update_dual_eta)
        self.chk_dual_avoid60.toggled.connect(self.update_dual_eta)
        self.ed_dual_avoid.editingFinished.connect(self.update_dual_eta)
        self.cmb_dual_m_fspace.currentIndexChanged.connect(self.update_dual_eta)
        # τ escolhido para a integração longa de cada varredura
        self.dual_user_tau = {k: w.value() for k, w in self.dual_tau_w.items()}
        for kind in ('P', 'F'):
            self.dual_tau_w[kind].valueChanged.connect(self.update_dual_eta)
            self.dual_tau_w[kind].valueChanged.connect(lambda v, k=kind: self._on_dual_tau(k, v))
            self.dual_mode_w[kind].currentIndexChanged.connect(lambda i, k=kind: self._on_dual_mode(k, i))
            self.dual_tau_w[kind].setEnabled(False)
        # Varreduras em frequência (calibração e medidas): sem a escolha de "Medida"; sempre integração longa,
        # com o τ ligado ao τ do INMP441: mudar qualquer um dos três campos muda os outros
        for kind in ('F', 'M'):
            self.dual_mode_w[kind].setCurrentIndex(1)
            sp = self.dual_tau_w[kind]
            self._set_spin(sp, self.sp_audio_tau.value())
            self.dual_user_tau[kind] = sp.value()
            sp.setEnabled(True)
            sp.setToolTip('τ dos dois lock-ins durante a varredura (integração longa): espera 9τ e faz a média por 1τ em\n'
                          'cada ponto. É o mesmo τ do INMP441: mudar aqui muda lá e vice-versa (e na outra varredura).')
            sp.valueChanged.connect(lambda v, k=kind: self._on_sweep_tau_edit(k, v))
        self.dual_tau_w['M'].valueChanged.connect(self.update_dual_eta)
        self.dual_tau_w['F'].valueChanged.connect(
            lambda v: self.lbl_dual_taumax.setVisible(v > TAU_USEFUL_MAX + 1e-9))
        self.sp_dual_adapt_tol.valueChanged.connect(self.update_dual_eta)
        self.chk_dual_adapt.toggled.connect(lambda _: (self._apply_adapt_ui(), self.update_dual_eta()))
        self.sp_audio_tau.valueChanged.connect(self._sync_sweep_tau)
        self.cmb_cell.currentIndexChanged.connect(lambda _: self._on_cal_cell())
        self._on_cal_cell()
        self._setup_dual_plots('F')
        self._apply_adapt_ui()
        self.update_dual_eta()
        self.refresh_mic_cal()
