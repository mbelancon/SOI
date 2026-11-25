# -*- coding: utf-8 -*-
'''Aba INMP441: gráficos, FFT, lock-in, detecção de ruídos e descarte por vizinhas.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class AudioMixin:
    def _optical_step(self):
        '''Thread do OPT101: consome os bytes da serial, roda o lock-in e enfileira o lote.'''
        data, first = self.link.take_optical()
        markers = self.link.take_markers()
        with self.dsp_lock:
            if data:
                if self.rx_bytes and first != self.rx_pos + len(self.rx_bytes) // 2:
                    self.rx_bytes.clear()       # fluxo recomeçou (reconexão) ou bytes descartados na serial
                if not self.rx_bytes:
                    self.rx_pos = first
                self.rx_bytes.extend(data)
                if len(self.rx_bytes) > MAX_RX_BYTES:
                    self.rx_pos += (len(self.rx_bytes) - MAX_RX_BYTES) // 2
                    del self.rx_bytes[:-MAX_RX_BYTES]
            for k_m, pos_m in markers:
                self.ext_sync.set_marker(k_m, pos_m)
            if len(self.rx_bytes) < 2 * self.dsp.osr:
                return
            res = self.dsp.process(self.rx_bytes, RATE.DECIMATION, not self.average_mode, self.normalize_mode,
                                   stream_pos=self.rx_pos)
            cap = self.res_capture          # Teste de resolução: guarda as palavras cruas consumidas
            if cap is not None and len(cap) < self.res_capture_bytes:
                cap.extend(self.rx_bytes[:min(res.consumed, self.res_capture_bytes - len(cap))])
            if res.consumed > 0:
                del self.rx_bytes[:res.consumed]
                self.rx_pos += res.consumed // 2
        if len(res.adc) or len(res.r):
            self.opt_results.append(res)

    def _audio_step(self):
        '''Thread do INMP441: lock-in de áudio independente do OPT101.'''
        chunks, drops = self.link.take_audio()
        with self.audio_lock:
            if self.simulating and not self.link.connected:
                chop = self.chopper_sim if self.ext_mode else None
                chunks = chunks + self.audio_sim.generate(time.perf_counter(), self.ref_freq, self.laser_power, chop)
            if chunks or drops:
                self._process_audio(chunks, drops)

    def on_audio_views(self, _=None):
        '''Caixas Lock-In / Ruído-SNR / FFT. O lock-in roda se qualquer um dos dois primeiros estiver ligado.'''
        show_li = self.chk_audio_lockin.isChecked()
        show_noise = self.chk_audio_noise.isChecked()
        use_fft = self.chk_audio_fft.isChecked()
        use_lockin = show_li or show_noise
        with self.audio_lock:
            if use_lockin != self.audio_lockin_enabled:
                self.audio_lockin_enabled = use_lockin
                self._audio_reset_lockin()
            if use_fft != self.audio_fft_enabled:
                self.audio_fft_enabled = use_fft
                self.audio_valid_samples = 0
                self.audio_write_index = 0
            self.audio_dirty = True
        self.plot_audio_wave.setVisible(show_li)
        self.audio_noise_panel.setVisible(show_noise)
        self.audio_fft_panel.setVisible(use_fft)
        self.audio_li_group.setEnabled(use_lockin)
        self.audio_xy_group.setEnabled(show_li)
        self.lbl_audio_noise.setVisible(use_lockin)
        # Com o ruído embaixo, o eixo de tempo (rótulo) fica só no gráfico de baixo
        self.plot_audio_wave.getPlotItem().getAxis('bottom').setLabel('' if show_noise else 'Tempo relativo (s)')
        if not use_lockin:
            self._clear_audio_wave()
        if not use_fft:
            self.curve_audio_fft.setData([], [])

    def on_audio_fft_full(self, checked):
        self.audio_fft_full = checked
        self.last_fft_t = 0.0
        self.update_audio_fft_range()

    def on_audio_fft_fit(self, checked):
        if not checked:
            self.curve_audio_fft_fit.setData([], [])
            self.txt_audio_fft_fit.setVisible(False)
            self.lbl_audio_fft_missing.setVisible(False)
            self.audio_fft_fit_html = None
            self.audio_fft_missing = None
        self.last_fft_t = 0.0

    FFT_MOUSE_TIP = ('Clique: frequência e magnitude do ponto mais próximo (o marcador acompanha o espectro)\n'
                     'Roda do mouse: zoom (sobre um eixo: só naquele eixo) | Arrastar: mover\n'
                     'Duplo clique: volta à escala automática | Botão direito: apaga o marcador')

    def _make_fft_interactive(self, plot_widget, curve, reset_view):
        '''Zoom com a roda do mouse, arrastar para mover e clique para ler as coordenadas de um ponto.
        Depois de um zoom manual a escala automática pausa até um duplo clique (ou troca de frequência).'''
        item = plot_widget.getPlotItem()
        vb = item.vb
        item.setMouseEnabled(True, True)
        vb.setMouseMode(pg.ViewBox.PanMode)
        plot_widget.setToolTip(self.FFT_MOUSE_TIP)
        marker = pg.ScatterPlotItem(size=9, pen=pg.mkPen('#1f5fbf', width=2), brush=pg.mkBrush(255, 255, 255, 0))
        text = pg.TextItem(anchor=(0, 1), color='#000', fill=pg.mkBrush(255, 255, 255, 220),
                           border=pg.mkPen('#1f5fbf'))
        for it in (marker, text):
            it.setZValue(50)
            it.setVisible(False)
            item.addItem(it, ignoreBounds=True)
        cur = {'manual': False, 'freq': None, 'curve': curve, 'marker': marker, 'text': text}
        vb.sigRangeChangedManually.connect(lambda *_: cur.__setitem__('manual', True))

        def clicked(ev):
            pos = ev.scenePos()
            if not vb.sceneBoundingRect().contains(pos):
                return
            if ev.double():
                reset_view()
                ev.accept()
                return
            if ev.button() == QtCore.Qt.MouseButton.RightButton:
                cur['freq'] = None
                marker.setVisible(False)
                text.setVisible(False)
                ev.accept()
                return
            if ev.button() != QtCore.Qt.MouseButton.LeftButton:
                return
            x, y = curve.getData()
            if x is None or len(x) == 0:
                return
            p = vb.mapSceneToView(pos)
            # ponto mais próximo na tela (o eixo x e o y têm escalas muito diferentes)
            (x0, x1), (y0, y1) = vb.viewRange()
            sx, sy = max(x1 - x0, 1e-12), max(y1 - y0, 1e-12)
            i = int(np.argmin(((x - p.x()) / sx) ** 2 + ((y - p.y()) / sy) ** 2))
            cur['freq'] = float(x[i])
            self._fft_cursor_refresh(cur)
            ev.accept()
        plot_widget.scene().sigMouseClicked.connect(clicked)
        return cur

    def _install_double_click_reset(self):
        '''Duplo clique na área de dados de qualquer gráfico volta os eixos/zoom ao padrão. As FFTs já têm o seu
        (cursor de pico) e aceitam o evento antes; os demais usam _reset_plot_view.'''
        for pw in self.findChildren(pg.PlotWidget):
            pw.scene().sigMouseClicked.connect(lambda ev, pw=pw: self._on_plot_double_click(pw, ev))

    def _on_plot_double_click(self, pw, ev):
        if not ev.double() or ev.isAccepted() or ev.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        if not pw.getPlotItem().vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        self._reset_plot_view(pw)
        ev.accept()

    def _reset_plot_view(self, pw):
        pi = pw.getPlotItem()
        if pw is self.plot1:
            if self.average_mode:
                pi.setXRange(-self.average_pretrigger_sec, 1.0 / max(self.ref_freq, 0.1), padding=0)
            else:
                pi.setXRange(-self.lockin_span, 0, padding=0)
            pi.enableAutoRange(y=True)
        elif pw in (self.plot_audio_wave, self.plot_audio_noise):
            pi.setXRange(-self.audio_span, 0, padding=0)
            pi.enableAutoRange(y=True)
        elif pw in (self.pw_dual_a, self.pw_dual_b, self.pw_dual_c, self.pw_dual_d):
            # Modo Duplo: só os pontos medidos (curvas teóricas, ajustes, modelos e regiões não esticam os eixos);
            # os gráficos andam juntos (eixo x compartilhado no empilhado/sobreposto)
            self._dual_fit_view()
        else:
            pi.enableAutoRange()

    @staticmethod
    def _fft_cursor_refresh(cur):
        f = cur['freq']
        if f is None:
            return
        x, y = cur['curve'].getData()
        if x is None or len(x) == 0:
            return
        i = int(np.argmin(np.abs(x - f)))
        fx, fy = float(x[i]), float(y[i])
        df = float(x[1] - x[0]) if len(x) > 1 else 0.0
        cur['marker'].setData([fx], [fy])
        cur['text'].setText(f'{fx:.6g} Hz (±{df / 2:.2g})\n{fy:.1f} dBFS')
        cur['text'].setPos(fx, fy)
        cur['marker'].setVisible(True)
        cur['text'].setVisible(True)

    def update_audio_fft_range(self):
        '''Eixo X da FFT: faixa completa ou região em torno da frequência de referência.'''
        item = self.plot_audio_fft.getPlotItem()
        if hasattr(self, 'audio_fft_cursor'):
            self.audio_fft_cursor['manual'] = False
            item.setYRange(-120, 0, padding=0)
        f = self.audio_freq
        self.audio_fft_ref_line.setPos(f)
        self.audio_fft_ref_line.setVisible(f > 0)
        if self.audio_fft_full or f <= 0:
            item.setXRange(0, AUDIO_FS / 2, padding=0)
            item.setTitle('INMP441 - espectro (FFT)')
        else:
            w = max(0.5 * f, 20.0 / AUDIO_FFT_HISTORY_SEC)
            item.setXRange(max(0.0, f - w), min(AUDIO_FS / 2, f + w), padding=0)
            item.setTitle(f'INMP441 - espectro (FFT) em torno de {f:g} Hz')

    # ------------------------------------------------------------ FFT do ADC do OPT101

    def on_audio_xy(self, checked):
        '''Alterna o gráfico do lock-in entre R/Fase e X/Y; ao entrar em X/Y aplica a auto-fase.'''
        self.audio_xy = checked
        item = self.plot_audio_wave.getPlotItem()
        if checked:
            item.setTitle('INMP441 - Lock-In (X e Y)')
            item.setLabel('left', 'X, Y (escala completa 24 bits)', color='k')
            item.getAxis('left').setPen('k')
            item.getAxis('left').setTextPen('k')
            item.getAxis('right').setLabel('')
            item.getAxis('right').setStyle(showValues=False)
            item.getAxis('right').setPen(pg.mkPen(0, 0, 0, 0))
        else:
            item.setTitle('INMP441 - Lock-In (Magnitude e Fase)')
            item.setLabel('left', 'Magnitude (escala completa 24 bits)', color='b')
            item.getAxis('left').setPen('b')
            item.getAxis('left').setTextPen('b')
            item.getAxis('right').setLabel('Fase (Graus)', color='r')
            item.getAxis('right').setStyle(showValues=True)
            item.getAxis('right').setPen('r')
            item.getAxis('right').setTextPen('r')
        self.audio_phase_vb.setVisible(not checked)
        self.curve_audio_y.setVisible(checked)
        self.audio_zero_line.setVisible(checked)
        self.audio_wave_legend.setVisible(checked)
        if checked:
            self.audio_auto_phase()
        with self.audio_lock:
            self.audio_dirty = True

    def audio_auto_phase(self):
        '''Offset = fase média (ponderada pela amplitude) do último AUTO_PHASE_SPAN s: o sinal passa para X.'''
        n = max(1, int(round(AUTO_PHASE_SPAN / self.audio_block_sec)))
        with self.audio_lock:
            z = self.audio_z[-n:].copy()
            self.audio_dirty = True
        if z.size == 0 or not np.any(z):
            self.flash('Auto-fase: sem dados do lock-in ainda')
            return
        self.audio_phase_offset = float(np.degrees(np.angle(z.sum())))
        self._set_spin(self.sp_audio_phase_off, self.audio_phase_offset)

    def on_audio_phase_offset(self, val):
        self.audio_phase_offset = float(val)
        with self.audio_lock:
            self.audio_dirty = True

    def on_audio_span(self, val):
        self.audio_span = float(val)
        self.audio_max_points = int(round(self.audio_span / self.audio_block_sec)) + 1
        self.plot_audio_wave.getPlotItem().setXRange(-self.audio_span, 0, padding=0)
        self.plot_audio_noise.getPlotItem().setXRange(-self.audio_span, 0, padding=0)
        self.audio_noise_window = min(self.audio_span, AUDIO_NOISE_SPAN / 2)
        with self.audio_lock:
            self.audio_dirty = True

    def on_audio_snr_alert(self, val):
        self.audio_snr_alert = float(val)
        self.audio_snr_alert_line.setPos(self.audio_snr_alert)

    def _clear_audio_wave(self):
        self.curve_audio_wave.setData([], [])
        self.curve_audio_phase.setData([], [])
        self.curve_audio_y.setData([], [])
        self.curve_audio_snr.setData([], [])
        self.lbl_audio_noise.setText('Ruído/SNR: aguardando dados')
        self.audio_noise_text = None

    def on_audio_tau(self, tau):
        self.audio_cutoff_lp = tau_cutoff(tau, AUDIO_FS_REAL)
        with self.audio_lock:
            self.audio_li.update_params(self.audio_freq, self.audio_cutoff_lp, self.audio_cutoff_hp)
        self.update_tau_labels()

    def on_audio_hp(self, val):
        self.audio_cutoff_hp = val
        with self.audio_lock:
            self.audio_li.update_params(self.audio_freq, self.audio_cutoff_lp, self.audio_cutoff_hp)

    def on_audio_mains(self, checked):
        self.audio_mains = checked
        with self.audio_lock:
            self.audio_li.set_mains_filter(checked)

    def _store_audio_samples(self, samples):
        values = np.asarray(samples, dtype=np.int32)
        capacity = len(self.audio_history)
        if len(values) >= capacity:
            self.audio_history[:] = values[-capacity:]
            self.audio_write_index = 0
            self.audio_valid_samples = capacity
            return

        first = min(len(values), capacity - self.audio_write_index)
        self.audio_history[self.audio_write_index:self.audio_write_index + first] = values[:first]
        rest = len(values) - first
        if rest:
            self.audio_history[:rest] = values[first:]
        self.audio_write_index = (self.audio_write_index + len(values)) % capacity
        self.audio_valid_samples = min(capacity, self.audio_valid_samples + len(values))

    def _process_audio(self, chunks, queue_drops):
        if queue_drops:
            self.audio_queue_drops += queue_drops
        for sequence, samples in chunks:
            if samples is None:
                # Marcador: a onda quadrada do laser (re)começou na amostra 'sequence'
                self.audio_phase_origin = sequence
                self.audio_li.phase_origin = sequence
                continue
            if self.audio_last_sequence is not None:
                gap = (sequence - self.audio_last_sequence) & 0xFFFFFFFF
                if gap:
                    if gap < 0x80000000:
                        self.audio_gap_samples += gap
                    self.audio_valid_samples = 0
                    self.audio_write_index = 0
            self.audio_last_sequence = (sequence + len(samples)) & 0xFFFFFFFF
            if self.audio_rec is not None:
                self.audio_rec.push(sequence, samples)
            if self.noise_cap is not None:
                # média de 4 sem perder amostras: o resto do bloco passa para o seguinte (sem saltos de fase)
                xs = np.concatenate((self.noise_rem, np.asarray(samples, dtype=np.float64)))
                n4 = (len(xs) // 4) * 4
                self.noise_rem = xs[n4:]
                if n4:
                    self.noise_cap.append((xs[:n4].reshape(-1, 4).mean(axis=1) / 8388608.0).astype(np.float32))
            if self.audio_lockin_enabled and not self.ext_mode:
                self._nb_feed(samples)
            if self.audio_fft_enabled:
                self._store_audio_samples(samples)
            if self.audio_lockin_enabled:
                self._audio_lockin(sequence, samples)
            self.audio_received_samples += len(samples)

    audio_rec = None          # AudioRecorder (SOI_GRAVAR_AUDIO)
    noise_cap = None          # Detectar ruídos de fundo: blocos do INMP441 a 12 kS/s (média de 4) durante a gravação

    # ---- Detectar ruídos de fundo (janela em soi_ruido)
    def noise_fs(self):
        return AUDIO_FS_REAL / 4.0

    def noise_capture_begin(self):
        with self.audio_lock:
            self.noise_cap = []
            self.noise_rem = np.zeros(0)
        self.noise_cap_opt = []               # OPT101 junto (amostras sobreamostradas, RAW_FS/osr), para a rede
        self.noise_cap_opt_fs = RAW_FS / max(1, int(getattr(self, 'osr', OSR_DEFAULT)))

    def noise_capture_len(self):
        cap = self.noise_cap
        return sum(len(c) for c in list(cap)) if cap is not None else 0

    def noise_capture_end(self):
        with self.audio_lock:
            cap, self.noise_cap = self.noise_cap, None
        co, self.noise_cap_opt = getattr(self, 'noise_cap_opt', None), None
        self.noise_last_opt = ((np.concatenate(co), self.noise_cap_opt_fs) if co and not self.ext_mode else None)
        return np.concatenate(cap) if cap else np.zeros(0, dtype=np.float32)

    NOISE_WARM_MAX_S = 180.0      # warm-up: analisa só os últimos 3 min

    def noise_warm_begin(self):
        """Detectar ruídos no warm-up: começa a guardar o áudio (laser ligado, na frequência atual)."""
        self.noise_warm_on = False
        if not self.chk_dual_warm_noise.isChecked() or self.ext_mode or self.noise_cap is not None:
            return
        self.noise_warm_fref = float(self.ref_freq)
        self.noise_capture_begin()
        self.noise_warm_on = True

    def noise_warm_end(self):
        """Fim do warm-up: tons e séries do áudio (sem a frequência do laser e harmônicos, ±1 Hz) passam a ser
        evitados na varredura que vai começar."""
        if not getattr(self, 'noise_warm_on', False):
            return None
        self.noise_warm_on = False
        x = self.noise_capture_end()
        fs = self.noise_fs()
        x = x[-int(self.NOISE_WARM_MAX_S * fs):]
        if len(x) < soi_ruido.SEG_S * fs * 2:
            print('Detectar ruídos no warm-up: áudio curto demais, nada analisado.', flush=True)
            return None
        # Laser e harmônicos: frequência real do TIM4, exata no relógio do I2S -> tolerância estreita (±0,15 Hz).
        # ±1 Hz esconderia boa parte do espectro com o laser em frequência baixa (a 5 Hz, 40 %).
        fr = actual_mod_freq(self.noise_warm_fref) if self.noise_warm_fref > 0 else 0.0
        ex = ([(k * fr, NOISE_LASER_TOL_HZ) for k in range(1, int(soi_ruido.FMAX_HZ / fr) + 2)] if fr > 0 else [])
        res = soi_ruido.analyze(x, fs, exclude=ex)
        res['opt_mains'], res['opt_ok'] = [], False
        lo = getattr(self, 'noise_last_opt', None)
        if lo is not None and fr > 0:
            xo, fso = lo
            xo = xo[-int(self.NOISE_WARM_MAX_S * fso):]
            # múltiplos de 60 Hz que caem num harmônico do laser não podem ser vistos no OPT101 (laser ligado)
            hidden = [m for m in range(60, int(soi_ruido.FMAX_HZ) + 1, 60)
                      if abs(m / fr - round(m / fr)) * fr <= 2 * NOISE_LASER_TOL_HZ]
            res['opt_mains'] = soi_ruido.opt_mains(xo, fso, exclude=ex)
            res['opt_ok'] = len(xo) >= soi_ruido.SEG_S * fso and len(hidden) <= 2
        vals = soi_ruido.avoid_list_for(res, [r[0] for r in soi_ruido.rows(res)], True)
        self.dual_auto_avoid = {'vals': vals, 'summary': soi_ruido.summary(res), 'dur': len(x) / fs, 'fref': fr,
                                'mains_checked': bool(res['opt_ok'])}
        self.dual_auto_pending = True
        msg = (f"Ruídos detectados no warm-up: {self.dual_auto_avoid['summary']}"
               + (f" -> excluídos desta varredura: {', '.join(f'{v:g}' for v in vals)} Hz" if vals else ''))
        print(msg, flush=True)
        self.flash(msg, 8.0)
        return res

    def audio_available(self):
        return bool(self.link.connected or self.simulating)

    def set_pwm(self, pwm):
        self.sp_power.setValue(pwm)
        self.on_power(self.sp_power.value())

    def add_avoid(self, vals):
        """Acrescenta frequências ao campo Evitar (Hz) (sem repetir as que já estão, ±1 Hz). True se mudou."""
        cur = self._dual_avoid_extra(field_only=True)
        new = [v for v in vals if all(abs(v - c) > 1.0 for c in cur)]
        if not new:
            return False
        allv = sorted(cur + new)
        self.ed_dual_avoid.setText('; '.join(f'{v:g}'.replace('.', ',') for v in allv))
        self.ed_dual_avoid.editingFinished.emit()
        return True

    def set_noise_detection(self, res, dur):
        """Resultado da janela Detectar ruídos de fundo: passa a ser evitado nas varreduras seguintes (com
        "Evitar ruídos detectados" marcada) até a próxima detecção."""
        rws = [r[0] for r in soi_ruido.rows(res)]
        vals = soi_ruido.avoid_list_for(res, rws, True)
        self.noise_det_last = {'vals': vals, 'summary': soi_ruido.summary(res), 'dur': dur, 'fref': 0.0,
                               'src': 'janela', 'when': datetime.now().strftime('%H:%M'),
                               'mains_checked': bool(res.get('opt_ok'))}
        print(f"Detectar ruídos de fundo: {self.noise_det_last['summary']}"
              + (f" -> excluídos das próximas varreduras: {', '.join(f'{v:g}' for v in vals)} Hz" if vals else ''),
              flush=True)
        self._noise_det_ui()
        self.update_dual_eta()
        return vals

    def _noise_det_ui(self):
        """Texto e dica da caixa "Evitar ruídos detectados" com a última detecção da janela."""
        d = getattr(self, 'noise_det_last', None)
        txt = 'Excluir ruídos detectados'
        tip = self._warm_noise_tip
        if d and d['vals']:
            txt += f" ({len(d['vals'])} faixas, {d['when']})"
            tip += (f"\n\nÚltima detecção ({d['when']}): {d['summary']}\nExcluídas: "
                    + ', '.join(f'{v:g}' for v in d['vals']) + ' Hz')
        self.chk_dual_warm_noise.setText(txt)
        self.chk_dual_warm_noise.setToolTip(tip)

    def open_noise_dialog(self):
        if getattr(self, 'noise_dlg', None) is None:
            self.noise_dlg = soi_ruido.make_dialog(self)
        self.noise_dlg.show()
        self.noise_dlg.raise_()
    nb_buf = np.empty(0, dtype=np.float32)
    nb_cnt = 0
    nb_q = deque(maxlen=600)  # (time.time(), f, q) do monitor de ruído pelas vizinhas, 1 por segundo

    def _nb_feed(self, samples):
        """Thread de áudio: guarda 2 s do INMP441 (média de 4 amostras, 12 kS/s) e calcula q a cada 1 s."""
        n = (len(samples) // 4) * 4
        if n <= 0:
            return
        fs = AUDIO_FS_REAL / 4.0
        x = np.asarray(samples[:n], dtype=np.float64).reshape(-1, 4).mean(axis=1) / 8388608.0
        size = int(NB_WIN_S * fs)
        self.nb_buf = np.concatenate((self.nb_buf, x))[-size:]
        self.nb_cnt += len(x)
        if self.nb_cnt >= fs and len(self.nb_buf) >= size:
            self.nb_cnt = 0
            f = float(self.audio_freq)
            if f > 0:
                try:
                    self.nb_q.append((time.time(), f, nb_ratio(self.nb_buf, f, fs)))
                except Exception:
                    pass

    def _nb_active(self):
        return (self.dual_kind == 'F' and self.dual_src in ('F', 'M') and not self.ext_mode
                and self.chk_dual_nb.isChecked())

    def _nb_filter(self, v, now):
        """Fim da média de um ponto: tira os trechos com ruído do ambiente (q > 2 × mediana de q do ponto) e refaz a
        média se mais de 30 % foi descartado. False = ponto refeito (a média recomeça)."""
        fa = float(self.audio_freq)
        t0 = getattr(self, 'point_t0', 0.0)
        wall0 = time.time() - (now - t0)                  # point_t0 está em perf_counter; nb_q em time.time()
        qs = [(t, q) for t, f, q in list(self.nb_q)
              if abs(f - fa) <= 0.01 * max(fa, 1e-9) and t >= wall0 + NB_WIN_S and np.isfinite(q)]
        with self.audio_lock:
            aud = list(self.dual_aud)
        if len(qs) < 3 or not aud or len(aud[0]) < 3:
            self.nb_point = (float('nan'), float('nan'), getattr(self, 'nb_redo', 0))
            return True
        qv = np.array([q for _, q in qs])
        med = float(np.median(qv))
        bad_t = [t for t, q in qs if q > NB_K * med]
        tau = float(self.sp_audio_tau.value())
        # trecho do lock-in em tc (média ~τ para trás) x janela de q em tb (2 s para trás): sobrepõem se tb em (tc-τ-1, tc+1)
        good = [c for c in aud if not any(c[2] - tau - 1.0 < tb < c[2] + 1.0 for tb in bad_t)]
        frac = 1.0 - len(good) / len(aud)
        if frac > NB_REDO_FRAC and getattr(self, 'nb_redo', 0) < NB_MAX_REDO:
            self.nb_redo = getattr(self, 'nb_redo', 0) + 1
            print(f'  {v:g} Hz: {100 * frac:.0f} % da média com ruído do ambiente (vizinhas): refazendo a média '
                  f'({self.nb_redo}/{NB_MAX_REDO})', flush=True)
            self.dual_state = 'MEASURING'
            self.dual_timer = now
            self.dual_opt = []
            with self.audio_lock:
                self.dual_aud = []
            return False
        if good and len(good) < len(aud):
            with self.audio_lock:
                self.dual_aud = good
        q_kept = [q for t, q in qs if q <= NB_K * med]
        self.nb_point = (float(np.median(q_kept)) if q_kept else med, 100.0 * frac if good else 0.0,
                         getattr(self, 'nb_redo', 0))
        return True

    def _start_audio_rec(self):
        """SOI_GRAVAR_AUDIO=<pasta>: grava o áudio bruto do INMP441 (análise offline do ruído acústico)."""
        folder = os.environ.get('SOI_GRAVAR_AUDIO', '').strip()
        self._rec_sample = ''
        self.audio_rec = None
        if not folder:
            return
        self.ed_sample.textChanged.connect(lambda t: setattr(self, '_rec_sample', t))
        self._rec_sample = self.ed_sample.text()
        self.audio_rec = AudioRecorder(folder, lambda: self._rec_sample)
        print(f'SOI_GRAVAR_AUDIO: áudio bruto do INMP441 será gravado em {folder}', flush=True)

    def _audio_reset_lockin(self):
        '''Reinicia o lock-in do INMP441 e o histórico plotado (chamar com audio_lock).'''
        self.audio_li = AudioLockIn(AUDIO_FS_REAL, self.audio_freq, self.audio_cutoff_lp, self.audio_cutoff_hp)
        self.audio_li.set_mains_filter(self.audio_mains)
        self.audio_li.phase_origin = getattr(self, 'audio_phase_origin', 0)
        self.audio_z = np.empty(0, dtype=np.complex128)   # saída X + jY, últimos AUDIO_NOISE_SPAN s
        self.audio_snr_db = None
        self.audio_dirty = False

    def _audio_lockin(self, sequence, samples):
        '''Um ponto (R e fase) a cada AUDIO_LOCKIN_BLOCK amostras, com a mesma cadeia do OPT101.
        Na modulação óptica a referência é a fase do OPT101 levada à grade do I2S: o trecho espera
        (audio_ext_pending) até o OPT101 ter sido processado naquele instante.'''
        if self.ext_mode:
            self.audio_ext_pending.append((sequence, samples))
            while self.audio_ext_pending:
                seq, smp = self.audio_ext_pending[0]
                s_raw = self.ext_sync.audio_to_raw(seq, len(smp))
                theta, st = (None, 'nosync') if s_raw is None else self.ext_ref.theta_at(s_raw)
                if st == 'wait':
                    break
                self.audio_ext_pending.popleft()
                if theta is not None:
                    self._audio_lockin_theta(seq, smp, theta + 0.5 * np.pi)   # mesma convenção do OPT101
                else:
                    self.audio_ext_drops += len(smp)
            # sem alinhamento ainda, ou o OPT101 parado: não acumula mais que EXT_AUDIO_PENDING_SEC
            limit = int(EXT_AUDIO_PENDING_SEC * AUDIO_FS / max(1, len(samples)))
            while len(self.audio_ext_pending) > limit:
                _, smp = self.audio_ext_pending.popleft()
                self.audio_ext_drops += len(smp)
            return
        self._audio_lockin_theta(sequence, samples, None)

    def _audio_lockin_theta(self, sequence, samples, theta):
        r, ph = self.audio_li.process(sequence, samples, AUDIO_LOCKIN_BLOCK, theta)
        if r.size:
            z = r * np.exp(1j * np.radians(ph))
            self.audio_z = np.append(self.audio_z, z)[-AUDIO_NOISE_POINTS:]
            self.audio_dirty = True
            
            if getattr(self, 'sweep_active', False) and getattr(self, 'sweep_target', 'OPT') == 'AUDIO' and getattr(self, 'sweep_state', 'IDLE') == 'MEASURING':
                self.audio_sweep_r.append(r)
                self.audio_sweep_p.append(ph)
                self.audio_sweep_count += r.size
            if getattr(self, 'dual_state', 'IDLE') == 'MEASURING':
                self.dual_aud.append((r, ph, time.time()))

    def _update_audio_plots(self, now):
        wave_visible = self.plot_audio_wave.isVisible()
        noise_visible = self.audio_noise_panel.isVisible()
        fft_visible = self.plot_audio_fft.isVisible()
        if not (wave_visible or noise_visible or fft_visible):
            return
        z_all = None
        with self.audio_lock:
            if (wave_visible or noise_visible) and self.audio_dirty:
                self.audio_dirty = False
                z_all = self.audio_z.copy()
            do_fft = (fft_visible and self.audio_fft_enabled and self.audio_valid_samples >= AUDIO_FFT_SIZE
                      and now - self.last_fft_t >= AUDIO_FFT_INTERVAL)
            if do_fft:
                self.last_fft_t = now
                # Com zoom usa todo o histórico disponível (resolução fina perto da referência)
                fft_n = AUDIO_FFT_SIZE if self.audio_fft_full else self.audio_valid_samples
                indices = (self.audio_write_index - fft_n +
                           np.arange(fft_n)) % len(self.audio_history)
                pcm = self.audio_history[indices].astype(np.float64) / 8388608.0
        if z_all is not None and wave_visible:
            z = z_all[-self.audio_max_points:] * np.exp(-1j * np.radians(self.audio_phase_offset))
            n = len(z)
            if n:
                x = (np.arange(n) - (n - 1)) * self.audio_block_sec
                item = self.plot_audio_wave.getPlotItem()
                if self.audio_xy:
                    self.curve_audio_wave.setData(x, z.real)
                    self.curve_audio_y.setData(x, z.imag)
                    lim = max(1e-6, float(np.abs(z).max()) * 1.10)
                    item.setYRange(-lim, lim, padding=0)
                else:
                    r = np.abs(z)
                    self.curve_audio_wave.setData(x, r)
                    self.curve_audio_phase.setData(x, np.degrees(np.angle(z)))
                    item.setYRange(0, max(1e-6, float(r.max()) * 1.10), padding=0)
        if z_all is not None:
            # Estatística calculada sempre que o lock-in roda: alimenta o alerta de sinal baixo
            self._update_audio_noise(z_all, noise_visible)

        if do_fft:
            window = np.hanning(fft_n)
            spectrum = np.abs(np.fft.rfft(pcm * window)) / window.sum()
            spectrum[1:-1] *= 2.0
            magnitude_dbfs = 20.0 * np.log10(np.maximum(spectrum, 1e-6))
            frequency = np.fft.rfftfreq(fft_n, 1.0 / AUDIO_FS_REAL)
            self.curve_audio_fft.setData(frequency, magnitude_dbfs)
            self._fft_cursor_refresh(self.audio_fft_cursor)
            if self.chk_audio_fft_fit.isChecked():
                self._fit_audio_fft(frequency, spectrum)

    def _fit_audio_fft(self, frequency, spectrum):
        '''Fit em f0 fixo (excitação); o texto acompanha a barra de status (2 s).'''
        self.audio_fft_fit_html, self.audio_fft_missing = self._fit_fft_at(
            frequency, spectrum, self.audio_freq, AUDIO_FFT_HISTORY_SEC, self.curve_audio_fft_fit)

    def _update_audio_noise(self, z, plot=True):
        '''SNR móvel e números de ruído da janela mais recente.'''
        w = max(2, int(round(self.audio_noise_window / self.audio_block_sec)))
        sig, sigma = rolling_noise(z, w)
        if sig.size == 0:
            self.audio_snr_db = None
            self.curve_audio_snr.setData([], [])
            self.audio_noise_text = (f'Ruído/SNR: acumulando {self.audio_noise_window:g} s de dados '
                                         f'({len(z) * self.audio_block_sec:.1f} s)')
            return
        snr_db = 20.0 * np.log10(np.maximum(sig, 1e-30) / np.maximum(sigma, 1e-30))
        self.audio_snr_db = float(snr_db[-1])
        if plot:
            t = (np.arange(sig.size) - (sig.size - 1)) * self.audio_block_sec
            self.curve_audio_snr.setData(t, snr_db)
        tau = lp_tau(self.audio_cutoff_lp, AUDIO_FS_REAL)
        enbw = 1.0 / (8.0 * tau)                      # banda equivalente de ruído, 2 polos em cascata
        density = sigma[-1] / np.sqrt(2.0 * enbw)     # ruído de entrada (rms) por raiz de Hz
        warn = (' <span style="color:#b36b00;">(janela &lt; 10τ: estimativa imprecisa)</span>'
                if self.audio_noise_window < 10.0 * tau else '')
        # O texto só vai para a tela junto com a barra de status (a cada 2 s), para dar tempo de ler
        self.audio_noise_text = (
            f'<b>Sinal</b> |⟨Z⟩| = {sig[-1]:.3e} FS &nbsp; <b>Ruído</b> σ(X,Y) = {sigma[-1]:.3e} FS &nbsp; '
            f'<b>SNR</b> = {snr_db[-1]:.1f} dB &nbsp; <b>Densidade</b> ≈ {density:.2e} FS/√Hz '
            f'(ENBW = {enbw:.3g} Hz){warn}')

    def _update_audio_status(self, now):
        received = self.audio_received_samples
        diff = received - getattr(self, 'last_audio_received_samples_stat', 0)
        self.last_audio_received_samples_stat = received
        dt = now - getattr(self, 'last_audio_status_now', now - 1.0)
        self.last_audio_status_now = now
        rate = diff / dt if dt > 0 else 0

        color = OK_COLOR
        # NOVO: Exibe o status da varredura do INMP441, se ativa
        if getattr(self, 'sweep_active', False) and getattr(self, 'sweep_target', 'OPT') == 'AUDIO':
            text = self.sweep_status_text
            color = OK_COLOR
        elif self.simulating and not self.link.connected:
            text = f"Status INMP441 (Simulado) | Taxa: {rate:.0f} amostras/s | 24 bits"
        elif not self.link.connected:
            text = f"Status INMP441: Aguardando conexão com o STM32 (I2S2, {AUDIO_FS // 1000} kHz, PCM 24 bits)"
            color = WARN_COLOR
        elif received == 0 and now - self.audio_wait_started > 2.0:
            text = "Status INMP441: Nenhum pacote recebido; verifique a inicialização I2S e fios PB13/PB12/PB15"
            color = WARN_COLOR
        elif received == 0:
            text = "Status INMP441: Aguardando pacotes I2S..."
            color = WARN_COLOR
        else:
            text = f"Status INMP441: Conectado | Taxa de dados: {rate:.0f} amostras/s | 24 bits"
        if (color == OK_COLOR and received and self.audio_lockin_enabled and self.audio_snr_db is not None
                and self.audio_snr_db < self.audio_snr_alert):
            text += f" | ⚠ SINAL BAIXO: SNR = {self.audio_snr_db:.1f} dB (limiar {self.audio_snr_alert:g} dB)"
            color = ALERT_COLOR

        if getattr(self, 'last_audio_status_text', None) != text:
            self.last_audio_status_text = text
            self.audio_status.setText(text)
        if getattr(self, 'last_audio_status_color', None) != color:
            self.last_audio_status_color = color
            self.audio_status.setStyleSheet(
                f'background:{color}; border:1px solid gray; border-radius:6px; padding:4px;')

    def _check_modulation_sync(self, now, connected):
        '''O PLL do OPT101 trava nas bordas reais do laser (bit REF). Se ele passa vários períodos sem
        travar, o STM32 está modulando em outra frequência (F perdido na conexão, placa reiniciada no
        padrão de 5 Hz...). O lock-in do INMP441 não tem PLL e daria resultado errado sem aviso:
        reenvia F, o que reinicia a onda quadrada e manda um novo marcador de fase.'''
        if self.ext_mode:
            # Modulação óptica: o PLL do bit 15 não é usado. Sem o alinhamento com o I2S (marcador perdido,
            # placa reiniciada), reenvia o farol.
            self._pll_bad_since = None
            if connected and not self.ext_sync.ready() and now - self._ext_resync_t >= 4.0:
                self._ext_resync_t = now
                self.link.write(f"P0\n")
                self.link.write(f"F{EXT_BEACON_HZ:g}\n")
            return
        f = self.ref_freq
        if not connected or f <= 0 or self.average_mode or self.dsp.pll_locked:
            self._pll_bad_since = None
            return
        if self._pll_bad_since is None:
            self._pll_bad_since = now
            return
        if now - self._pll_bad_since >= max(5.0, 5.0 / f):
            self._pll_bad_since = now
            self.link.write(f"F{f}\n")
            self.flash(f'PLL do OPT101 sem travar: frequência {f:g} Hz reenviada ao STM32.', 5.0)
            print(f'PLL sem travar: F{f} reenviado')
