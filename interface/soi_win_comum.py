# -*- coding: utf-8 -*-
'''Controles comuns: SNR do topo, PWM, warm-up, frequência, Configurações, modulação óptica, simulação.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class CommonMixin:
    def _update_snr_top(self):
        """Indicador "SNR OPT/INMP (dB)" da barra superior, a cada segundo."""
        def snr_db(z):
            z = np.asarray(z, dtype=np.complex128)
            if z.size < 5:
                return None
            sig, sigma = rolling_noise(z, z.size)
            if sig.size == 0 or not np.isfinite(sig[-1]) or sigma[-1] <= 0:
                return None
            return 20.0 * np.log10(max(float(sig[-1]), 1e-30) / float(sigma[-1]))

        def fmt(v):
            if v is None:
                return '<span style="color:#808080;">—</span>'
            col = ('#1e8c1e' if v >= SNR_TOP_GOOD_DB else '#c99a00' if v >= SNR_TOP_OK_DB else '#d00000')
            return f'<b style="color:{col};">{v:.0f}</b>'

        opt = aud = None
        connected = self.link.connected or self.simulating
        win = lambda tau: min(SNR_TOP_MAX_S, max(SNR_TOP_WINDOW_S, 10.0 * tau))   # ~10 amostras independentes
        zo = getattr(self, 'snr_opt_z', None)
        if connected and not self.average_mode and zo is not None and zo.size:
            n = int(win(lp_tau(self.cutoff_lp, RATE.FS)) * LOCKIN_OUT_HZ)
            if zo.size >= int(SNR_TOP_WINDOW_S * LOCKIN_OUT_HZ):      # enquanto enche, usa o que houver
                opt = snr_db(zo[-n:])
        if connected and self.audio_lockin_enabled:
            n = int(win(lp_tau(self.audio_cutoff_lp, AUDIO_FS_REAL)) / self.audio_block_sec)
            with self.audio_lock:
                z = (np.array(self.audio_z[-n:]) if len(self.audio_z) * self.audio_block_sec >= SNR_TOP_WINDOW_S
                     else None)
            aud = snr_db(z) if z is not None else None
        self.lbl_snr_top.setText(f'SNR OPT/INMP: {fmt(opt)} / {fmt(aud)} dB')

    def _add_pwm_presets(self, layout):
        """Botões segmentados 0 / 10 / [campo do PWM] / 100: um clique aplica o PWM (desligar, alinhamento, potência
        máxima); o botão do valor atual fica azul e, com um valor digitado, nenhum acende. Os botões seguem o campo
        (habilitado, visível) e acompanham o valor mesmo quando o programa muda o PWM sem sinais."""
        on = 'QPushButton{background:#1f6fd1;color:white;font-weight:bold;border:1px solid #1f6fd1;padding:1px 6px;}'
        off = ('QPushButton{background:#f4f4f4;color:#222;border:1px solid #b9b9b9;padding:1px 6px;}'
               'QPushButton:hover{background:#e3edfb;}QPushButton:disabled{color:#a0a0a0;}')
        self.pwm_presets = {}
        for v in PWM_PRESETS:
            b = QtWidgets.QPushButton(f'{v:g}')
            b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            b.setFixedWidth(QtGui.QFontMetrics(b.font()).horizontalAdvance('100') + 18)
            b.setToolTip(f'PWM {v:g} % com um clique' + (' (laser parado)' if v == 0 else ''))
            b.clicked.connect(lambda _=False, val=v: self.sp_power.setValue(val))
            self.pwm_presets[v] = b
        for v in PWM_PRESETS:
            if v == PWM_PRESETS[-1]:
                layout.addWidget(self.sp_power)
            layout.addWidget(self.pwm_presets[v])

        def refresh(*_):
            val = self.sp_power.value()
            for v, b in self.pwm_presets.items():
                b.setStyleSheet(on if abs(val - v) < 1e-6 else off)
        self._pwm_presets_refresh = refresh
        self.sp_power.valueChanged.connect(refresh)
        self.sp_power._after_set = refresh       # _set_spin muda o valor com os sinais bloqueados
        refresh()

        sp, btns = self.sp_power, self.pwm_presets

        class _Mirror(QtCore.QObject):
            def eventFilter(self, obj, ev):
                t = ev.type()
                if t == QtCore.QEvent.Type.EnabledChange:
                    for bb in btns.values():
                        bb.setEnabled(sp.isEnabled())
                elif t in (QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.ShowToParent,
                           QtCore.QEvent.Type.HideToParent):
                    for bb in btns.values():
                        bb.setVisible(not sp.isHidden())
                return False
        self._pwm_mirror = _Mirror(self)
        sp.installEventFilter(self._pwm_mirror)

    def _dspin(self, lo, hi, val, dec, step, slot, width=90, suffix=''):
        sb = QtWidgets.QDoubleSpinBox()
        sb.setRange(lo, hi)
        if suffix:
            sb.setSuffix(suffix)
        sb.setDecimals(dec)
        sb.setSingleStep(step)
        sb.setValue(val)
        sb.setKeyboardTracking(False)   # só dispara ao confirmar (Enter/perder foco)
        sb.setFixedWidth(width)
        if slot is not None:
            sb.valueChanged.connect(slot)
        return sb

    @staticmethod
    def _set_spin(sb, v):
        sb.blockSignals(True)
        sb.setValue(v)
        sb.blockSignals(False)
        hook = getattr(sb, '_after_set', None)
        if hook is not None:
            hook()

    def _warm_click(self, btn, start):
        """Botão de um quadro de varredura: com "Aguardar warm-up" marcado, o 1º clique liga o laser e espera; o
        clique durante a espera cancela; no fim da espera a varredura começa (start). Sem a opção, start direto."""
        warm = getattr(self, 'warm_state', None)
        if warm is not None:
            if warm['btn'] is btn:
                self._warm_stop()
                self.dual_prechecked = None             # o próximo clique pergunta de novo
                self.flash('Warm-up cancelado pelo usuário.')
            else:
                self.flash('Aguarde o fim do warm-up em andamento (ou cancele-o).')
            return
        chk_w, sp_w, warm_pwm, eta = self.warm_w.get(btn, (None, None, None, None))
        busy = getattr(self, 'dual_active', False) or getattr(self, 'sweep_active', False)
        if chk_w is None or not chk_w.isChecked() or busy or not btn.text().startswith('▶'):
            start()
            return
        if self.average_mode:
            self.flash('As varreduras precisam do Modo Lock-In.')
            return
        # Avisos com confirmação (pontos abaixo de 40 Hz, condições da calibração) ANTES do warm-up, com o usuário
        # ainda na frente do PC: antes eles abriam no fim da espera e a medida ficava parada esperando o OK
        kind = next((k for k, b in getattr(self, 'dual_btns', {}).items() if b is btn), None)
        if kind is not None and not self._dual_prechecks(kind):
            return
        pwm = warm_pwm() if warm_pwm else self.sp_power.value()
        if pwm <= 0:
            pwm = 100.0
        self.sp_power.setValue(pwm)
        self.on_power(self.sp_power.value())
        dur = sp_w.value()
        self.warm_state = {'btn': btn, 'start': start, 'until': time.perf_counter() + dur, 'eta': eta,
                           'text': btn.text(), 'style': btn.styleSheet(), 'dur': dur, 'rest': dur}
        if btn in (self.dual_btns.get('F'), self.dual_btns.get('M')):
            self.noise_warm_begin()
        print(f'Warm-up: laser em PWM {pwm:g} % por {dur:g} s antes da varredura.')
        btn.setStyleSheet('background:#fff3cd;')
        for b in self.warm_w:
            if b is not btn:
                b.setEnabled(False)
        self.warm_timer = QtCore.QTimer(self)
        self.warm_timer.timeout.connect(self._warm_tick)
        self.warm_timer.start(500)
        self._warm_tick()

    def _dual_prechecks(self, kind):
        '''Confirmações da varredura do Modo Duplo feitas no clique, antes do warm-up. Marca dual_prechecked para
        toggle_dual_sweep não perguntar de novo quando a espera acabar.'''
        self.dual_prechecked = None
        if getattr(self, 'series_active', False):
            return True
        values = self._dual_planned(kind)
        if not values:
            return True
        if (kind == 'F' and self.btn_dual_sweeps_panel.isChecked() and not self._check_cal_conditions()):
            return False
        if not self._confirm_lowf(kind, values):
            return False
        self.dual_prechecked = kind
        return True

    def _warm_tick(self):
        warm = getattr(self, 'warm_state', None)
        if warm is None:
            return
        rest = warm['until'] - time.perf_counter()
        if rest > 0:
            warm['btn'].setText(f'⏹ Warm-up {self._fmt_time(rest)}')
            warm['rest'] = rest
            self._eta_render(warm['eta'])
            return
        start = warm['start']
        self.noise_warm_end()
        self._warm_stop()
        print('Warm-up concluído: começando a varredura.')
        start()

    def _warm_stop(self):
        warm = getattr(self, 'warm_state', None)
        if warm is None:
            return
        if getattr(self, 'noise_warm_on', False):      # warm-up cancelado: descarta o áudio
            self.noise_warm_on = False
            self.noise_capture_end()
        if getattr(self, 'warm_timer', None) is not None:
            self.warm_timer.stop()
            self.warm_timer = None
        warm['btn'].setText(warm['text'])
        warm['btn'].setStyleSheet(warm['style'])
        for b in self.warm_w:
            b.setEnabled(True)
        self.warm_state = None
        self._eta_render(warm['eta'])

    def _eta_set(self, lbl, base):
        """Texto do tempo de um quadro de varredura parado: 'Tempo estimado: xx:xx' + '(+warm-up yy:yy)' quando
        "Aguardar warm-up" está marcado (contando para baixo durante a espera). Um texto só, sem alternar."""
        if not hasattr(self, 'eta_base'):
            self.eta_base = {}
        self.eta_base[lbl] = base
        self._eta_render(lbl)

    def _eta_render(self, lbl):
        base = getattr(self, 'eta_base', {}).get(lbl)
        if base is None:
            return
        warm = getattr(self, 'warm_state', None)
        suffix = ''
        if warm is not None and warm['eta'] is lbl:
            suffix = f"+warm\u2011up\u00a0{self._fmt_time(warm['rest'])}"
        elif warm is None:
            for chk_w, sp_w, _, eta in getattr(self, 'warm_w', {}).values():
                if eta is lbl and chk_w.isChecked():
                    suffix = f'+warm\u2011up\u00a0{self._fmt_time(sp_w.value())}'
                    break
        if suffix:
            lbl.setText(f'{base} ({suffix})' if base else suffix[0].upper() + suffix[1:])
        else:
            lbl.setText(base)

    def warming_up(self):
        return getattr(self, 'warm_state', None) is not None

    def _make_sweep_box(self, title, fields, on_click, extra=(), more=(), warm_pwm=None):
        '''Quadro de varredura padrão (mesmo em todas as abas): campos na 1ª linha (e os de 'extra'
        numa linha própria); botão, tempo e barra de progresso na última. Retorna (quadro, botão,
        rótulo do tempo, barra).'''
        box = self._group(title)
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(6, 2, 6, 4)
        lay.setSpacing(3)
        for row_fields in (fields, extra) + tuple(more):
            if not row_fields:
                continue
            # Cada rótulo + campo é um grupo que não se divide; sem espaço na largura, a linha quebra (antes os
            # campos se sobrepunham aos rótulos quando a janela era mais estreita que a linha)
            row1 = soi_layout.FlowBar(hspace=6, vspace=3, last_right=False)
            for label, w in row_fields:
                g = row1.group()
                if isinstance(label, QtWidgets.QWidget):
                    g.addWidget(label)
                elif label:
                    g.addWidget(QtWidgets.QLabel(label))
                g.addWidget(w)
            lay.addLayout(row1)
        # 2.5.0: botão e warm-up numa linha que quebra (painel lateral estreito); tempo e barra na linha de baixo
        row2 = soi_layout.FlowBar(hspace=6, vspace=3, last_right=False)
        row3 = QtWidgets.QHBoxLayout()
        btn = QtWidgets.QPushButton('▶ Varredura')
        btn.setStyleSheet('background:#cfe2ff;')
        btn.setMinimumWidth(110)
        btn.clicked.connect(lambda _=False, b=btn, f=on_click: self._warm_click(b, f))
        row2.addWidget(btn)
        g_w = row2.group()
        eta = QtWidgets.QLabel('Tempo estimado: --:--')
        # O tempo fica no fim da linha (depois do warm-up): quando o texto muda, nada mais se move; com pouco
        # espaço ele quebra a linha em vez de alargar a janela. O botão tem largura para "⏹ Warm-up 0:00:00".
        eta.setWordWrap(True)
        eta.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        eta.setMinimumWidth(70)                # quebra a linha; não alarga a janela com o warm-up ligado
        btn.setMinimumWidth(max(110, btn.fontMetrics().horizontalAdvance('⏹ Warm-up 0:00:00') + 24))
        # Aguardar warm-up: laser ligado (no PWM da medida) por N s antes do 1º ponto (aquecimento da amostra/célula)
        chk_w = QtWidgets.QCheckBox('Aguardar warm-up')
        chk_w.setToolTip('Antes do 1º ponto, liga o laser (no PWM da medida) e espera o tempo indicado: depois que o laser\n'
                         'liga, o sinal fotoacústico cai alguns % até a amostra e a célula aquecerem (campanha de 16-17/11:\n'
                         '−14 % com constante de ~4,4 min a 10 Hz). Clicar no botão durante a espera cancela.')
        sp_w = self._dspin(10.0, 7200.0, WARMUP_DEF_S, 0, 30.0, None, 85, ' s')
        sp_w.setVisible(False)
        chk_w.toggled.connect(sp_w.setVisible)
        chk_w.toggled.connect(lambda _=False, e=eta: self._eta_render(e))
        sp_w.valueChanged.connect(lambda _=0.0, e=eta: self._eta_render(e))
        g_w.addWidget(chk_w)
        g_w.addWidget(sp_w)
        row3.addWidget(eta, 4)
        if not hasattr(self, 'warm_w'):
            self.warm_w = {}
        self.warm_w[btn] = (chk_w, sp_w, warm_pwm, eta)
        bar = QtWidgets.QProgressBar()
        bar.setRange(0, 1000)
        bar.setTextVisible(False)
        bar.setFixedHeight(12)
        bar.setVisible(False)
        row3.addWidget(bar, 3)
        lay.addLayout(row2)
        lay.addLayout(row3)
        return box, btn, eta, bar

    def flash(self, text, seconds=3.0):
        self.flash_text = text
        self.flash_until = time.perf_counter() + seconds
        # Também na barra de status da janela, para aparecer em qualquer aba
        self.statusBar().showMessage(text, int(seconds * 1000))

    def update_window_status(self):
        '''Barra de status da janela: conexão (à direita) e varredura em andamento em qualquer aba.'''
        if self.link.connected:
            conn = f"<span style='color:#1a7f1a;'>●</span> STM32 conectado ({self.link.port})"
            tip = ''
        elif self.simulating:
            conn = "<span style='color:#d07000;font-weight:bold;'>● SIMULAÇÃO (sem STM32)</span>"
            tip = ''
        else:
            conn = "<span style='color:#d07000;'>●</span> STM32 desconectado, procurando..."
            tip = self.link.last_error or 'Nenhuma porta do STM32 (USB VID 0x0483) encontrada.'
        task = ''
        if self.sweep_active:
            alvo = 'OPT101' if self.sweep_target == 'OPT' else 'INMP441'
            tipo = 'frequência' if self.sweep_kind == 'F' else 'PWM'
            task = (f'Varredura {alvo} em {tipo}: ponto {self.sweep_idx + 1}/{len(self.sweep_freqs)}, '
                    f'restante {self._fmt_time(self._sweep_remaining(time.perf_counter()))}')
        elif self.dual_active and self.dual_src == 'X':
            task = f'Modo Duplo, varredura manual: {len(self.dual_results)} pontos'
        elif self.dual_active:
            tipo = 'PWM' if self.dual_kind == 'P' else 'frequência'
            task = (f'Modo Duplo em {tipo}: ponto {self.dual_idx + 1}/{len(self.dual_values)}, '
                    f'restante {self._fmt_time(getattr(self, "dual_rest", 0.0))}')
        state = (conn, tip, task)
        if state != self.last_sb_state:
            self.last_sb_state = state
            self.lbl_sb_conn.setText(conn)
            self.lbl_sb_conn.setToolTip(tip)
            self.lbl_sb_task.setText(task)

    # ----------------------------------------------------------- Controles
    def default_pretrigger(self, freq=None):
        '''25% do tempo em que o laser fica ligado (meio período).'''
        return 0.25 * 0.5 / max(freq or self.ref_freq, 0.1)

    def update_avg_ref_line(self):
        pre = self.average_pretrigger_sec
        half = 0.5 / max(self.ref_freq, 0.1)
        end = max(1.0 / max(self.ref_freq, 0.1), half)
        self.line_ref_avg.setData([-pre, 0, 0, half, half, end], [0, 0, 1, 1, 0, 0])

    def set_pretrigger(self, sec):
        self.average_pretrigger_sec = float(sec)
        self.avg.pre = int(round(sec * RATE.FS))
        self.lbl_pre.setText(f'Pré: -{sec:.4f} s')

    def apply_frequency(self, val, command=True):
        '''Nova frequência de modulação: cortes automáticos dos dois lock-ins e, com command, envia F ao STM32
        (command=False: modulação óptica, a frequência é a detectada no OPT101).'''
        self.ref_freq = val
        tau = auto_tau(val)
        self.cutoff_hp = get_effective_cutoffs(val)[1]
        self.cutoff_lp = tau_cutoff(tau, RATE.FS)
        if command:
            self.link.write(f"F{val}\n")
        self.update_raw_window()
        with self.dsp_lock:
            self.dsp.update_params(val, self.cutoff_lp, self.cutoff_hp)
        # O lock-in do INMP441 segue a frequência de excitação comum
        with self.audio_lock:
            self.audio_freq = val
            self.audio_cutoff_lp, self.audio_cutoff_hp = tau_cutoff(tau, AUDIO_FS_REAL), self.cutoff_hp
            self.audio_li.update_params(val, self.audio_cutoff_lp, self.audio_cutoff_hp)
        self._set_spin(self.sp_audio_tau, tau)
        self._set_spin(self.sp_audio_hp, self.audio_cutoff_hp)
        self._set_spin(self.sp_tau, tau)
        self._set_spin(self.sp_hp, self.cutoff_hp)
        self._sync_sweep_tau(tau)        # o τ das varreduras em frequência segue o τ do INMP441
        self.update_tau_labels()
        self.update_audio_fft_range()
        self.update_opt_fft_range()
        if self.average_mode:
            self.set_pretrigger(self.default_pretrigger(val))
            self.reset_average()
            self.update_avg_ref_line()
            self.plot1.getPlotItem().setXRange(-self.average_pretrigger_sec, 1.0 / val, padding=0)

    def on_freq(self, val):
        if self.ext_mode:
            # Modulação óptica: na simulação o campo é o botão do chopper simulado; com o STM32 fica travado
            if self.chopper_sim is not None:
                self.chopper_sim.set_freq(val, time.perf_counter() - self.sim_epoch)
            return
        if not self.sweep_active:
            self.apply_frequency(val)

    def on_power(self, val):
        self.laser_power = val
        if not self.ext_mode:
            self.link.write(f"P{val}\n")

    def _beam_off_after_sweep(self):
        """Fim de qualquer varredura (concluída, parada ou interrompida): PWM 0, feixe desligado (Marcos, 26/11).
        Dentro de Medidas em Série não desliga: a série decide no fim (fim = laser_parado ou manter)."""
        if getattr(self, 'series_active', False) or self.ext_mode:
            return
        rp = getattr(self, 'dual_rep', None)
        if rp and rp['k'] < rp['n']:          # entre repetições da mesma varredura: o feixe continua ligado
            return
        if self.sp_power.value() > 0 or self.laser_power > 0:
            self.pwm_before_off = float(self.sp_power.value() or self.laser_power)
            self.sp_power.setValue(0.0)
            self.on_power(0.0)
            self.flash('Fim da varredura: PWM 0, feixe desligado.', 5.0)

    def _beam_on_for_sweep(self):
        """Início de varredura em frequência com o feixe desligado (PWM 0 deixado pela varredura anterior): volta ao
        PWM de antes do desligamento, para não medir no escuro."""
        pwm = getattr(self, 'pwm_before_off', None)
        if self.ext_mode or self.sp_power.value() > 0 or not pwm:
            return
        self.sp_power.setValue(pwm)
        self.on_power(self.sp_power.value())
        self.flash(f'PWM {pwm:g} % religado para a varredura.', 5.0)

    def _link_params(self):
        '''(F, P) enviados ao STM32 na conexão: no modo óptico, o farol (1 Hz, PWM 0).'''
        return (EXT_BEACON_HZ, 0.0) if self.ext_mode else (self.ref_freq, self.laser_power)

    # ------------------------------------------------------------ Configurações
    show_nb = False           # Configurações: mostrar "Descartar trechos com som da sala"

    def set_show_nb(self, on):
        self.show_nb = bool(on)
        self.chk_dual_nb.setVisible(self.show_nb)
        if not self.show_nb:
            self.chk_dual_nb.setChecked(False)

    def open_settings(self):
        '''Janela Configurações: trigger dos lock-ins, alimentação do OPT101 e Finalizar experimento.'''
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle('Configurações')
        dlg.setMinimumWidth(620)
        lay = QtWidgets.QVBoxLayout(dlg)

        def info(text):
            lbl = QtWidgets.QLabel(text)
            lbl.setWordWrap(True)
            lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
            lbl.setStyleSheet('color:#404040;margin-left:22px;margin-bottom:4px;')
            return lbl

        busy = self.sweep_active or self.dual_active
        box = self._group('Trigger (referência dos lock-ins)')
        bl = QtWidgets.QVBoxLayout(box)
        r_el = QtWidgets.QRadioButton('Eletrônico (STM32)')
        r_op = QtWidgets.QRadioButton('Óptico (OPT101, chopper)')
        (r_op if self.ext_mode else r_el).setChecked(True)
        bl.addWidget(r_el)
        bl.addWidget(info('O STM32 modula o laser pelo PWM em PA8 na frequência do campo <b>Freq</b>, e o instante de '
                          'cada borda vai junto com as amostras. É o modo normal, com o laser ligado ao driver do SOI.'))
        bl.addWidget(r_op)
        bl.addWidget(info('A luz é modulada fora do SOI (chopper, ventilador) e a fonte tem alimentação própria. O SOI '
                          'acha a frequência no sinal do OPT101, que precisa ver a luz <b>já modulada</b>, e usa a fase '
                          'dele como referência do OPT101 e do microfone. O STM32 fica com PWM 0 e só gera um "farol" de '
                          '1 Hz no bit de referência, que alinha o microfone ao OPT101: <b>não ligue nada em PA8</b>. '
                          'A faixa de busca da frequência fica na aba OPT101; no Modo Duplo a varredura em frequência '
                          'vira manual (você muda o chopper).'))
        if busy:
            for r in (r_el, r_op):
                r.setEnabled(False)
            bl.addWidget(info('<i>Termine ou cancele a varredura em andamento para trocar o trigger.</i>'))
        lay.addWidget(box)

        box = self._group('Alimentação do OPT101')
        bl = QtWidgets.QVBoxLayout(box)
        r33 = QtWidgets.QRadioButton('3,3 V (padrão)')
        r50 = QtWidgets.QRadioButton('5 V')
        (r50 if self.opt_supply > 4 else r33).setChecked(True)
        bl.addWidget(r33)
        bl.addWidget(info('A saída do OPT101 vai de ~7,5 mV até V<sub>s</sub> − 1,3 V ≈ <b>2,0 V</b>: nunca passa do limite '
                          'do ADC do STM32 (3,3 V), então não precisa de proteção. Usa ~60 % da faixa do ADC. '
                          'Linha "Max OPT101 output" em 2,0 V.'))
        bl.addWidget(r50)
        bl.addWidget(info('A saída chega a ≈ <b>3,7 V</b>, acima do limite do ADC. Ajuste o ganho (resistor de '
                          'realimentação) ou a luz para o pico ficar abaixo de ~2,9 V (vermelho a partir de 90 % = 3,0 V): usa quase toda '
                          'a faixa do ADC. Linha "Max OPT101 output" em 3,3 V (limite do ADC, antes do OPT101 saturar).'))
        warn = QtWidgets.QLabel('⚠ Com 5 V o PA0 <b>precisa de proteção</b>: resistor de 1 kΩ em série entre a saída do '
                                'OPT101 e o PA0 e diodo Schottky BAT54 do PA0 para os 3,3 V. Sem isso o STM32 pode queimar.')
        warn.setWordWrap(True)
        warn.setTextFormat(QtCore.Qt.TextFormat.RichText)
        warn.setStyleSheet('color:#b00000;background:#fdecea;border:1px solid #e0a0a0;border-radius:4px;padding:4px;')
        bl.addWidget(warn)
        warn.setVisible(self.opt_supply > 4)
        lay.addWidget(box)                          # 2.5.0: a escala fixa do osciloscópio foi para a seção da aba OPT101

        box = self._group('Varreduras')
        bl = QtWidgets.QVBoxLayout(box)
        chk_nb = QtWidgets.QCheckBox('Mostrar "Descartar trechos com som da sala" na varredura em frequência')
        chk_nb.setChecked(self.show_nb)
        bl.addWidget(chk_nb)
        bl.addWidget(info('A cada 1 s o SOI compara o sinal do microfone nas frequências vizinhas (f ± 7 %) com o sinal '
                          'em f; o segundo em que um som da sala sobe as vizinhas sai da média, e o ponto é refeito se '
                          'mais de 30 % for descartado. Com τ = 1 s não trouxe ganho (testes de 18–19/11); pode valer '
                          'com τ maior. Desligada, a caixa some da interface e o descarte fica desligado.'))
        chk_nb.toggled.connect(self.set_show_nb)
        lay.addWidget(box)

        box = self._group('Desempenho')
        bl = QtWidgets.QVBoxLayout(box)
        chk_light = QtWidgets.QCheckBox('Modo leve (para computadores lentos)')
        chk_light.setChecked(self.light_mode)
        bl.addWidget(chk_light)
        bl.addWidget(info('Desenha a tela 10 vezes por segundo (em vez de 25), com menos pontos no osciloscópio, e '
                          'não processa o INMP441 enquanto você não está na aba dele nem em medida ou Modo Duplo '
                          '(ao voltar, o lock-in dele recomeça e leva ~3τ para estabilizar). Os dados medidos e '
                          'salvos são os mesmos. Use se a interface engasgar ou houver perdas de USB.'))
        chk_light.toggled.connect(self.set_light_mode)
        lay.addWidget(box)

        # 2.5.0: "Finalizar experimento" fica à vista, na seção Experimento do painel lateral

        def on_trigger(checked):
            if not checked:
                return
            self.cmb_mod.setCurrentIndex(1 if r_op.isChecked() else 0)
            (r_op if self.ext_mode else r_el).setChecked(True)       # pode ter sido recusado (varredura)

        def on_supply(checked):
            if not checked:
                return
            v = 5.0 if r50.isChecked() else 3.3
            if v > 4 and self.opt_supply < 4:
                ans = QtWidgets.QMessageBox.warning(
                    dlg, 'Alimentação de 5 V',
                    'Com o OPT101 em 5 V a saída pode chegar a ~3,7 V, acima do limite do ADC do STM32 (3,3 V).\n\n'
                    'A proteção do PA0 está instalada? (1 kΩ em série + diodo Schottky BAT54 do PA0 para 3,3 V)',
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No)
                if ans != QtWidgets.QMessageBox.StandardButton.Yes:
                    r33.setChecked(True)
                    return
            self.set_opt_supply(v)
            warn.setVisible(v > 4)

        for r in (r_el, r_op):
            r.toggled.connect(on_trigger)
        for r in (r33, r50):
            r.toggled.connect(on_supply)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        soi_layout.scroll_dialog(dlg)                          # 2.5.0: rola em telas baixas (125 % em 1366×768)
        lay.addWidget(btns)
        for lbl in dlg.findChildren(QtWidgets.QLabel):        # rótulos com quebra de linha: altura certa
            if lbl.wordWrap():
                lbl.setMinimumHeight(lbl.heightForWidth(dlg.minimumWidth() - 60))
        dlg.fit_scroll()
        dlg.adjustSize()
        soi_layout.fit_to_screen(dlg)
        dlg.exec()

    def set_light_mode(self, on):
        '''Modo leve (Configurações): salvo na hora, vale já e na próxima abertura.'''
        self.light_mode = bool(on)
        self.timer.setInterval(LIGHT_GUI_INTERVAL_MS if self.light_mode else GUI_INTERVAL_MS)
        QtCore.QSettings('LCTM', 'SOI Controller').setValue('light_mode', self.light_mode)

    def set_opt_supply(self, v):
        self.opt_supply = 5.0 if v > 4 else 3.3
        self._apply_scope_scale()
        self.flash('OPT101 alimentado com 3,3 V: teto do sinal em 2,0 V (saturação do OPT101).' if self.opt_supply < 4 else
                   'OPT101 alimentado com 5 V: teto do sinal em 3,3 V (limite do ADC).', 4.0)

    def _sat_counts(self):
        '''Contagens (escala 0-16380) do teto do sinal com a alimentação escolhida.'''
        return OPT_SUPPLY[self.opt_supply] / ADC_VREF * ADC_FULL_SCALE

    def _apply_scope_scale(self):
        '''Linha do teto do OPT101 e escala do osciloscópio (fixa 0-3,3 V ou acompanhando o sinal).'''
        sat = self._sat_counts()
        self.line_opt_max.setPos(sat)
        # texto em cima da linha; no teto do ADC (5 V) não há espaço acima, então fica embaixo
        a = (0, 0) if sat >= ADC_FULL_SCALE - 1 else (0, 1)
        self.line_opt_max.label.anchors = [a, a]
        self.line_opt_max.label.setAnchor(a)
        if self.chk_scope_fixed.isChecked():
            self.plot_raw.getPlotItem().setYRange(0, ADC_FULL_SCALE * 1.003, padding=0)
        else:
            self._autoscale_raw()

    def _autoscale_raw(self):
        '''Eixo do osciloscópio pelo sinal (como antes); perto do teto (≥ 80 %) a linha entra na vista.'''
        m = float(self.raw.adc.max()) if len(self.raw.adc) else 0.0
        if m <= 0:
            return
        top = max(10.0, m * 1.10)
        sat = self._sat_counts()
        if m >= OPT_PCT_ORANGE / 100.0 * sat:
            top = max(top, min(sat * 1.10, ADC_FULL_SCALE * 1.003))
        self.plot_raw.getPlotItem().setYRange(0, top, padding=0)

    # ------------------------------------------------------------ Modulação óptica
    def on_mod_mode(self, idx):
        ext = idx == 1
        if ext == self.ext_mode:
            return
        if self.sweep_active or self.dual_active:
            self.cmb_mod.blockSignals(True)
            self.cmb_mod.setCurrentIndex(1 if self.ext_mode else 0)
            self.cmb_mod.blockSignals(False)
            self.flash('Termine ou cancele a varredura antes de trocar a modulação.')
            return
        if ext:
            self._int_freq = self.sp_freq.value()
        self.ext_mode = ext
        with self.dsp_lock:
            self.dsp.ext = self.ext_ref if ext else None
            self.dsp.ext_sync = self.ext_sync if ext else None
            self.dsp._unlock()
        if ext:
            self._ext_restart()
            self.flash('Modulação óptica: procurando a frequência no sinal do OPT101. O STM32 fica com PWM 0 '
                       '(farol de 1 Hz só no bit de referência).', 6.0)
        else:
            self.chopper_sim = None
            with self.audio_lock:
                self.audio_ext_pending.clear()
            if self.simulating and not self.link.connected:
                self.on_simulate(True)
            f = getattr(self, '_int_freq', self.sp_freq.value())
            self._set_spin(self.sp_freq, f)
            self.apply_frequency(f)
            self.link.write(f"P{self.laser_power}\n")
        self._apply_mod_ui()

    def _ext_restart(self):
        '''Recomeça a referência óptica (entrada no modo, reconexão, simulação ligada ou desligada).'''
        now = time.perf_counter()
        sim = self.simulating and not self.link.connected
        with self.dsp_lock:
            self.ext_ref.reset()
            self.ext_sync.reset()
            self._ext_tuned_f = None
            if sim:
                self.sim_epoch = now
                self.chopper_sim = ChopperSimulator(self.sp_freq.value())
                self.simulator.reset(now)
                self.rx_bytes.clear()
                self.rx_pos = 0
                self.ext_sync.set_marker(*self.chopper_sim.marker())
            else:
                self.chopper_sim = None
        with self.audio_lock:
            self.audio_ext_pending.clear()
            self.audio_ext_drops = 0
            if sim:
                self.audio_sim.reset(now)
            self.audio_last_sequence = None
            self.audio_gap_samples = 0
            self.audio_received_samples = 0
            self.audio_valid_samples = 0
            self.audio_write_index = 0
            self.audio_wait_started = now
            self._audio_reset_lockin()
        if not sim and self.link.connected:
            self._ext_resync_t = now
            self.link.write("P0\n")
            self.link.write(f"F{EXT_BEACON_HZ:g}\n")
        self._apply_mod_ui()

    def on_ext_range(self, *_, force=False):
        with self.dsp_lock:
            self.ext_ref.set_range(self.sp_ext_fmin.value(), self.sp_ext_fmax.value())
            if force:
                self.ext_ref.reset()

    def _apply_mod_ui(self):
        '''Habilita/esconde o que muda entre modulação eletrônica e óptica.'''
        ext = self.ext_mode
        sim = self.simulating and not self.link.connected
        busy = self.sweep_active or self.dual_active
        self.sp_power.setEnabled(not ext and not busy)
        self.sp_freq.setEnabled((ext and sim) or (not ext and not busy))
        self.sp_freq.setToolTip('Simulação do modo óptico: frequência nominal do chopper simulado (o "botão" do '
                                'ventilador).' if ext and sim else
                                'Modo óptico: frequência detectada no OPT101.' if ext else
                                'Frequência da modulação do laser (STM32).')
        self.lbl_ext.setVisible(ext)
        self.lbl_power.setVisible(not ext)
        self.sp_power.setVisible(not ext)
        self.ext_range_w.setVisible(ext)
        self.plot_raw.getPlotItem().setTitle(
            'Sinal bruto do ADC (PA0, <span style="color:#000;">preto</span>) e referência do PLL óptico '
            '(<span style="color:#009600;">verde tracejado</span>, cos θ ≥ 0)' if ext else
            'Sinal bruto do ADC (PA0, <span style="color:#000;">preto</span>) e referência do laser '
            '(<span style="color:#009600;">verde tracejado</span>, 0/1)')
        for b in list(self.btn_sweeps.values()) + list(getattr(self, 'btn_sweeps_aud', {}).values()):
            b.setEnabled(not ext and not busy)
            b.setToolTip('Use o Modo Duplo (varredura manual) na modulação óptica.' if ext else '')
        if hasattr(self, 'dual_manual_box'):
            self.dual_manual_box.setVisible(ext)
            self.dual_box_f.setVisible(not ext)
            for b, key in ((self.btn_dual_p_panel, 'dual_p'), (self.btn_dual_t_panel, 'dual_t')):   # só modulação eletrônica
                self.side_sections[key].setVisible(not ext)
                if ext:
                    b.setChecked(False)
        self._update_ext_label()

    def _update_ext_label(self):
        if not self.ext_mode:
            return
        r = self.ext_ref
        sim = self.simulating and not self.link.connected
        if not self.link.connected and not sim:
            self.lbl_ext.setText('<span style="color:#b05000;">Óptica: STM32 não conectado</span>')
            return
        if r.state == 'TRACK' and r.f_mean is not None:
            col = '#006400' if r.locked else '#b05000'
            txt = f'<span style="color:{col};"><b>{r.f_mean:.2f} Hz</b> {"●" if r.locked else "○"}</span>'
            info = (f'{r.f_mean:.3f} Hz, σ {r.f_std:.3f} Hz, fase ±{r.jitter_deg:.1f}° rms: '
                    + ('travado' if r.locked else r.msg))
        else:
            txt = '<span style="color:#b05000;">○ procurando</span>'
            info = r.msg
        if not self.ext_sync.ready():
            txt += ' <span style="color:#b05000;">⚠ mic</span>'
            info += '\nMicrofone: aguardando o farol do STM32 (alinhamento com o OPT101).'
        self.lbl_ext.setText(txt)
        self.lbl_ext.setToolTip(info + '\n\nFrequência detectada no OPT101 (média do último segundo), desvio padrão dela e\n'
                                'oscilação rms da fase da luz em relação ao PLL (● travado). O INMP441 usa a mesma referência\n'
                                'depois que o farol do STM32 alinha os dois fluxos (alguns segundos depois de conectar).')

    def _ext_follow(self, now):
        '''Modo óptico: a frequência de trabalho (FFT, janelas, cortes automáticos, ganho do OSR) segue a
        detectada no OPT101.'''
        self._update_ext_label()
        r = self.ext_ref
        if r.state != 'TRACK' or r.f_mean is None:
            return
        f = r.f_mean
        if abs(f - self.ref_freq) > 1e-3 * f:
            self.ref_freq = f
            with self.dsp_lock:
                self.dsp.ref_freq = f
            with self.audio_lock:
                self.audio_freq = f
                self.audio_li.ref_freq = f
            if self.chopper_sim is None:
                self._set_spin(self.sp_freq, f)
        # cortes automáticos (τ, passa-altas) só quando a frequência muda bastante e fora de varreduras
        if (r.locked and not self.dual_active and not self.sweep_active
                and (self._ext_tuned_f is None or abs(np.log(f / self._ext_tuned_f)) > np.log(1.15))):
            self._ext_tuned_f = f
            self.apply_frequency(f, command=False)

    def on_simulate(self, checked):
        self.simulating = checked
        if self.ext_mode:
            self._ext_restart()
            return
        self.simulator.reset()
        with self.dsp_lock:
            self.rx_bytes.clear()
        with self.audio_lock:
            self.audio_sim.reset()
            self.audio_last_sequence = None
            self.audio_gap_samples = 0
            self.audio_received_samples = 0
            self.audio_valid_samples = 0
            self.audio_write_index = 0
            self.audio_wait_started = time.perf_counter()
            self._audio_reset_lockin()
        self._clear_audio_wave()
        self.curve_audio_fft.setData([], [])

    def on_window(self, val):
        self.user_window = val
        self.update_raw_window()

    def update_raw_window(self):
        '''Janela do osciloscópio: a escolhida pelo usuário, limitada a MAX_SCOPE_CYCLES ciclos
        quando a modulação passa de REDUCED_VIEW_HZ.'''
        reduced = self.ref_freq > REDUCED_VIEW_HZ
        window = MAX_SCOPE_CYCLES / self.ref_freq if reduced else self.user_window
        self._set_spin(self.sp_window, window)
        self.lbl_reduced.setVisible(reduced)
        if reduced:
            self.lbl_reduced.setPos(window / 2.0, 0.6)
        if abs(window - self.raw.window) < 1e-9:
            return
        self.raw.resize(window)
        self.plot_raw.getPlotItem().setXRange(0, self.raw.window, padding=0)
        for c in (self.c_adc_a, self.c_adc_b, self.c_ref_a, self.c_ref_b):
            c.setData([], [])

    def on_mains(self, checked):
        with self.dsp_lock:
            self.dsp.set_mains_filter(checked)

