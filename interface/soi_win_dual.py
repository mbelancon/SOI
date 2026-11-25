# -*- coding: utf-8 -*-
'''Modo Duplo: gráficos, planejamento (τ, tempos, frequências a evitar), varredura manual e Sinal x t.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class DualMixin:
    def _sync_sweep_tau(self, v):
        '''τ do INMP441 mudou: as varreduras em frequência passam a usar o mesmo τ (fora de uma varredura:
        durante ela os cortes são trocados pela própria varredura).'''
        if getattr(self, "dual_active", False) or not hasattr(self, "dual_tau_w"):
            return
        for k in ('F', 'M'):
            self._set_spin(self.dual_tau_w[k], v)
            self.dual_user_tau[k] = float(v)
        self.update_dual_eta()

    def _on_sweep_tau_edit(self, kind, v):
        if self.dual_active:
            return
        if abs(self.sp_audio_tau.value() - v) > 1e-9:
            self.sp_audio_tau.setValue(v)       # aplica no INMP441 e, por _sync_sweep_tau, na outra varredura
        else:
            self._sync_sweep_tau(v)

    def _on_dual_tau(self, kind, val):
        if self.dual_mode_w[kind].currentIndex() == 1:
            self.dual_user_tau[kind] = float(val)

    def _on_dual_mode(self, kind, idx):
        '''Integração longa: campo editável com o τ escolhido. Média no tempo: mostra o τ atual (mais lento
        dos dois lock-ins), só para leitura.'''
        self.dual_tau_w[kind].setEnabled(idx == 1 and not self.dual_active)
        if idx == 1:
            self._set_spin(self.dual_tau_w[kind], self.dual_user_tau[kind])
        self.update_dual_eta()

    def _setup_dual_plots(self, kind):
        a, b = self.pw_dual_a, self.pw_dual_b
        if kind == 'P':
            a.setTitle('Fotoacústico × intensidade óptica')
            a.setLabel('left', 'INMP441 R (escala completa 24 bits)')
            a.setLabel('bottom', 'OPT101 R (u.a., ∝ intensidade)')
            b.setTitle('Calibração: intensidade óptica × PWM')
            b.setLabel('left', 'OPT101 R (u.a.)')
            b.setLabel('bottom', 'PWM do laser (%)')
            a.setLogMode(x=False, y=False)
            b.setLogMode(x=False, y=False)
            self._apply_dual_layout()
        elif kind == 'T':
            a.setTitle('Sinal fotoacústico normalizado × tempo (INMP441 R / OPT101 R)')
            a.setLabel('left', 'S = R_INMP441 / R_OPT101')
            a.setLabel('bottom', 'Tempo (s)')
            b.setTitle('Diferença de fase INMP441 − OPT101 × tempo')
            b.setLabel('left', 'Δφ (graus)')
            b.setLabel('bottom', 'Tempo (s)')
            a.setLogMode(x=False, y=False)
            b.setLogMode(x=False, y=False)
            self._apply_dual_layout()
        else:
            self._set_dual_f_titles()
            a.setLabel('bottom', 'Frequência (Hz)')
            b.setLabel('bottom', 'Frequência (Hz)')
            a.setLogMode(x=True, y=True)
            b.setLogMode(x=True, y=False)
        xl = {'P': 'PWM do laser (%)', 'T': 'Tempo (s)'}.get(kind, 'Frequência (Hz)')
        for pw in (self.pw_dual_c, self.pw_dual_d):
            pw.setLabel('bottom', xl)
        self.pw_dual_c.setLogMode(x=kind == 'F', y=kind == 'F')
        self.pw_dual_d.setLogMode(x=kind == 'F', y=False)
        for cc in self.c_dual_sens.values():
            for c in cc:
                c.setData([], [])
        self.chk_dual_norm.setEnabled(kind == 'F')
        # Barras de erro nos dois tipos (na frequência, em coordenadas log calculadas aqui: o pyqtgraph não
        # transforma o ErrorBarItem para a escala log)
        self.e_dual_a.setVisible(True)
        self.e_dual_b.setVisible(True)
        for e in (self.e_dual_a, self.e_dual_b, self.e_dual_a_cal, self.e_dual_b_cal):
            self._set_errbar(e, x=np.empty(0), y=np.empty(0))
        for c in (self.c_dual_a, self.c_dual_a_fit, self.c_dual_a_bad, self.c_dual_b, self.c_dual_b_fit,
                  self.c_dual_a_out, self.c_dual_b_out):
            c.setData([], [])
        self._dual_cal_regions(self._applied_cal() if kind == 'F' else None)
        for t in self.txt_dual_empty:
            t.setVisible(True)
        # Faixa neutra enquanto não há dados (em vez de -400 a 400 x 0,001)
        if kind == 'P':
            a.setRange(xRange=(0, 1), yRange=(0, 1), padding=0)
            b.setRange(xRange=(0, 100), yRange=(0, 1), padding=0)
        elif kind == 'T':
            a.setRange(xRange=(0, 60), yRange=(0, 1), padding=0)
            b.setRange(xRange=(0, 60), yRange=(-180, 180), padding=0)
        else:
            fw = self.dual_fw['M' if self.dual_src == 'M' else 'F']
            lf = np.log10(sorted((max(fw[0].value(), 0.1), max(fw[1].value(), 0.1))))
            a.setRange(xRange=tuple(lf), yRange=(-3, 0), padding=0)
            b.setRange(xRange=tuple(lf), yRange=(-180, 180), padding=0)
        self.chk_dual_std.setEnabled(kind == 'F')
        self.chk_dual_std_phase.setEnabled(kind == 'F')
        for w in (self.sp_dual_tau_sensor, self.btn_dual_tau_measure):
            w.setEnabled(kind == 'F')
        self.btn_dual_cal.setEnabled(False)
        self.dual_std = None
        self.dual_opt_tau = None
        self.dual_sensor_fit_txt = None
        self.lbl_dual_fit.setText('')
        self.lbl_dual_tau.setText('')

    def _place_dual_plots(self):
        '''Coloca os dois gráficos na grade conforme o arranjo (a varredura casada em PWM fica sempre lado a lado:
        os eixos x dos dois gráficos são diferentes).'''
        g, a, b = self.dual_plot_grid, self.pw_dual_a, self.pw_dual_b
        mode = self.dual_layout if self.dual_kind == 'F' else 'side'
        for pw in (a, b):
            g.removeWidget(pw)
        for i in range(3):
            g.setRowStretch(i, 0)
            g.setColumnStretch(i, 0)
        g.setVerticalSpacing(0 if mode == 'stacked' else -1)
        if mode == 'stacked':
            g.addWidget(a, 0, 0)
            g.addWidget(b, 1, 0)
            g.setRowStretch(0, 1)
            g.setRowStretch(1, 1)
            g.setColumnStretch(0, 1)
        elif mode == 'overlay':
            g.addWidget(a, 0, 0)
            g.addWidget(b, 0, 0)                    # mesma célula: b fica por cima, transparente
            g.setRowStretch(0, 1)
            g.setColumnStretch(0, 1)
        else:
            g.addWidget(a, 0, 0)
            g.addWidget(b, 0, 1)
            g.setRowStretch(0, 1)
            g.setColumnStretch(0, 1)
            g.setColumnStretch(1, 1)
        b.setXLink(a if mode in ('stacked', 'overlay') else None)
        if hasattr(self, 'dual_float'):
            self.dual_float.raise_()

    def set_dual_layout(self, key):
        '''Arranjo dos gráficos da varredura em frequência (menu do botão direito).'''
        self.dual_layout = key if key in ('side', 'stacked', 'overlay') else 'side'
        for k, acts in self.dual_layout_actions.items():
            for act in acts:
                act.setChecked(k == self.dual_layout)
        if self.dual_kind == 'F':
            self._set_dual_f_titles()
        else:
            self._apply_dual_layout()

    def _apply_dual_layout(self):
        '''Aplica o arranjo e, nos gráficos sobrepostos, deixa os dois com a mesma área de dados: o de fase fica
        transparente por cima (sem receber o mouse), com o eixo à direita; o de magnitude reserva o espaço.'''
        self._place_dual_plots()
        a, b = self.pw_dual_a, self.pw_dual_b
        pa, pb = a.getPlotItem(), b.getPlotItem()
        over = self.dual_kind == 'F' and self.dual_layout == 'overlay'
        stk = self.dual_kind == 'F' and self.dual_layout == 'stacked'
        clear = QtGui.QColor(0, 0, 0, 0)
        if over:
            b_title = pb.titleLabel.text
            b_left = pb.getAxis('left').labelText
            if b_left:
                self._dual_b_texts = (b_title, b_left)
            b_title, b_left = getattr(self, '_dual_b_texts', (b_title, b_left))
            a_title = pa.titleLabel.text.split('  +  ')[0]
            both = f'{a_title}  +  fase (eixo da direita)'
            a.setTitle(both)
            b.setTitle(both, color='#00000000')
            wl = max(pa.getAxis('left').width(), 60)
            hb = max(pa.getAxis('bottom').height(), 36)
            pa.showAxis('right')
            ar = pa.getAxis('right')
            ar.setStyle(showValues=False)
            ar.setLabel('')
            ar.setPen(pg.mkPen(None))
            for ax in (ar, pb.getAxis('right')):
                ax.setWidth(80)
            pb.showAxis('right')
            br = pb.getAxis('right')
            br.setStyle(showValues=True)
            br.setLabel(b_left)
            bl = pb.getAxis('left')
            bl.setStyle(showValues=False)
            bl.setLabel('')
            bl.setPen(pg.mkPen(None))
            for ax in (pa.getAxis('left'), bl):
                ax.setWidth(wl)
            bb = pb.getAxis('bottom')
            bb.setStyle(showValues=False)
            bb.setPen(pg.mkPen(None))
            bb.setTextPen(pg.mkPen(clear))
            bb.label.setVisible(False)
            for ax in (pa.getAxis('bottom'), bb):
                ax.setHeight(hb)
            b.showGrid(x=False, y=False)
            b.setBackground(None)
            b.setStyleSheet('background: transparent;')
            b.viewport().setAutoFillBackground(False)
            b.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        else:
            if getattr(self, '_dual_b_texts', None) and not pb.getAxis('left').labelText:
                b.setTitle(self._dual_b_texts[0])
                pb.getAxis('left').setLabel(self._dual_b_texts[1])
            fg = pg.getConfigOption('foreground')
            a.setTitle(pa.titleLabel.text.split('  +  ')[0], color=fg)
            b.setTitle(pb.titleLabel.text, color=fg)      # tira a cor transparente do modo sobreposto
            pa.showAxis('right', False)
            pb.showAxis('right', False)
            for pi in (pa, pb):
                for name in ('left', 'bottom', 'right'):
                    ax = pi.getAxis(name)
                    ax.setStyle(showValues=True)
                    ax.setPen()
                    ax.setTextPen()
                    ax.label.setVisible(True)
                    if name == 'bottom':
                        ax.setHeight(None)
                    else:
                        ax.setWidth(None)
            b.showGrid(x=True, y=True, alpha=0.3)
            b.setBackground(pg.getConfigOption('background'))
            b.setStyleSheet('')
            b.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            pa.showAxis('top', False)
            pa.showAxis('bottom', True)
            if stk:
                # Empilhado: escala de frequência em cima no gráfico de cima e embaixo no de baixo, sem repetir o
                # nome do eixo e sem o título do de baixo (o nome do eixo y já diz o que é), para colar os dois
                pa.showAxis('bottom', False)
                pa.showAxis('top', True)
                at = pa.getAxis('top')
                at.setStyle(showValues=True)
                at.setLabel('')
                at.setLogMode(pa.getAxis('bottom').logMode)
                b.setTitle(None)
                wl = max(pa.getAxis('left').width(), pb.getAxis('left').width(), 60)
                for pi in (pa, pb):
                    pi.getAxis('left').setWidth(wl)
        # Eixo de cada grandeza na cor da sua curva (S azul, fase vermelha) na varredura em frequência
        fg = pg.getConfigOption('foreground')
        col_a, col_b = ('royalblue', 'firebrick') if self.dual_kind == 'F' else (fg, fg)
        axes = ((pa.getAxis('left'), col_a), (pb.getAxis('right' if over else 'left'), col_b))
        for ax, col in axes:
            ax.setPen(pg.mkPen(col))
            ax.setTextPen(pg.mkPen(col))
            ax.setLabel(ax.labelText, color=pg.mkColor(col).name())

    def _set_dual_f_titles(self):
        '''Títulos da varredura em frequência conforme a normalização pelo OPT101.'''
        a, b = self.pw_dual_a, self.pw_dual_b
        if self.chk_dual_norm.isChecked():
            a.setTitle('Sinal fotoacústico normalizado (INMP441 R / OPT101 R)')
            a.setLabel('left', 'S = R_INMP441 / R_OPT101')
            b.setTitle('Diferença de fase INMP441 − OPT101')
            b.setLabel('left', 'Δφ (graus)')
        else:
            a.setTitle('Sinal fotoacústico sem normalização (INMP441 R)')
            a.setLabel('left', 'R_INMP441 (escala completa 24 bits)')
            b.setTitle('Fase do INMP441 (sem descontar o OPT101)')
            b.setLabel('left', 'φ_INMP441 (graus)')
        self._apply_dual_layout()

    def _on_dual_sensors(self, checked):
        self.dual_sensor_plots.setVisible(checked)
        self._show_dual_results()

    def _update_dual_sensor_plots(self, x, ro, ra, pa, po):
        '''Amplitude (÷ mediana) e fase desenrolada de cada sensor, com a mediana absoluta na legenda.'''
        if not self.chk_dual_sensors.isChecked():
            return
        order = np.argsort(x)
        xs = x[order]
        for name, r, ph in (('INMP441', ra, pa), ('OPT101', ro, po)):
            r, ph = r[order], ph[order]
            ok = r > 0
            med = float(np.median(r[ok])) if ok.any() else 1.0
            ca, cp = self.c_dual_sens[name]
            ca.setData(xs[ok], r[ok] / med)
            cp.setData(xs, np.degrees(np.unwrap(np.radians(ph))))
            leg = self.pw_dual_c.getPlotItem().legend
            for sample, label in leg.items:
                if label.text.startswith(name):
                    label.setText(f'{name} (mediana R = {med:.4g})')

    def _dual_planned(self, kind, raw=False):
        if kind == 'P':
            return self._planned_range(self.sp_dual_p0.value(), self.sp_dual_p1.value(), self.sp_dual_dp.value())
        sp0, sp1, space, spn, _ = self.dual_fw[kind]
        f0, f1 = sorted((sp0.value(), sp1.value()))
        if space.currentIndex() == 0:
            n = max(2, int(round(spn.value())))
            vals = [round(float(v), 3) for v in np.geomspace(f0, f1, n)]
        else:
            vals = self._planned_range(f0, f1, spn.value())
        if raw:
            return vals
        if self._mains_fixed():
            vals = soi_serie.avoid_mains(vals)[0]
        return soi_serie.avoid_list(vals, self._dual_avoid_extra())[0]

    def _dual_avoid_extra(self, field_only=False):
        """Frequências do campo "Evitar (Hz)" (fontes de ruído conhecidas; texto inválido é ignorado) mais os ruídos
        detectados (janela Detectar ruídos de fundo e warm-up), se "Excluir ruídos detectados" estiver marcada."""
        out = []
        txt = self.ed_dual_avoid.text() if hasattr(self, 'ed_dual_avoid') else ''
        for p in re.split(r'[;\s]+', txt):
            try:
                v = float(p.strip(',').replace(',', '.'))
            except ValueError:
                continue
            if 0 < v <= 20000:
                out.append(v)
        if field_only:
            return out
        srcs = self._noise_sources()
        for auto in srcs:
            out += [v for v in auto['vals'] if all(abs(v - o) > 1.0 for o in out)]
        return out

    def _noise_sources(self):
        """Detecções de ruído que valem para a varredura (com "Excluir ruídos detectados" marcada): a última da
        janela Detectar ruídos de fundo e a do warm-up que acabou. Durante a varredura, a lista fixada no início."""
        if getattr(self, 'dual_noise_lock', False) or self.dual_busy():
            return getattr(self, 'dual_noise_used', None) or []
        if not (hasattr(self, 'chk_dual_warm_noise') and self.chk_dual_warm_noise.isChecked()):
            return []
        return [d for d in (getattr(self, 'noise_det_last', None),
                            getattr(self, 'dual_auto_avoid', None) if getattr(self, 'dual_auto_pending', False)
                            else None) if d]

    def _mains_fixed(self):
        """Excluir todos os múltiplos de 60 Hz (k·60 ± 3 Hz)? Só quando nenhuma detecção em uso analisou o OPT101
        (sem detecção, por segurança); com detecção, só a rede que ela achou é excluída. --sem-evitar-rede desliga."""
        return (self.chk_dual_avoid60.isChecked()
                and not any(d.get('mains_checked') for d in self._noise_sources()))

    def _dual_order_key(self):
        return self.cmb_dual_order.currentData() if hasattr(self, 'cmb_dual_order') else 'crescente'

    def _dual_adaptive(self, kind):
        return kind in ('F', 'M') and self.chk_dual_adapt.isChecked()

    def _lowf_fixed_tau(self, kind, f):
        """τ pré-definido do ponto (adaptativo só acima de LOWF_FMAX); None = o ponto usa o τ adaptativo."""
        if not (self._dual_adaptive(kind) and self.chk_dual_adapt40.isChecked()):
            return None
        return None if lowf_band_tau(f) is None else self._adapt_cap(kind)

    def _fixed_tau_at(self, kind, f):
        """τ do ponto f com o τ adaptativo desligado: o do campo em toda a faixa (desde 2.5.0 sem os 4 s abaixo de
        40 Hz; a célula nova mede bem em baixa frequência)."""
        return float(self.dual_tau_w[kind].value())

    def _adapt_cap(self, kind):
        """τ max do τ adaptativo: o valor do campo "τ max" do quadro."""
        return float(self.dual_tau_w['M' if kind == 'M' else 'F'].value())

    def _adapt_tau_at(self, kind, f):
        """τ do ponto f numa varredura com τ adaptativo em andamento."""
        fixed = self._lowf_fixed_tau(kind, f)
        if fixed is not None:
            return fixed
        return max(adapt_tau_min(f), self.adapt_tau_cur or self.dual_tau_w[kind].value())

    def _confirm_lowf(self, kind, values):
        """Antes avisava (janela) de varreduras abaixo de LOWF_FMAX. Desde 25/11 a célula nova mede bem em baixa
        frequência e a varredura padrão começa em 1 Hz: sem aviso (Marcos)."""
        return True

    def _update_lowf_warn(self, kind):
        self.lbl_dual_lowf[kind].setVisible(False)      # rótulo laranja "alto SNR em f < 40 Hz": sem aviso desde 25/11

    def _apply_adapt_ui(self):
        """τ adaptativo: o τ do quadro vira o τ inicial; a Precisão só vale com ele ligado."""
        on = self.chk_dual_adapt.isChecked()
        for k in ('F', 'M'):
            self.dual_tau_w[k].setEnabled(not self.dual_active)
        self.sp_dual_adapt_tol.setEnabled(on and not self.dual_active)
        self.chk_dual_adapt.setEnabled(not self.dual_active)
        self.chk_dual_adapt40.setEnabled(on and not self.dual_active)
        if hasattr(self, 'chk_dual_blocks'):
            self.chk_dual_blocks.setEnabled(on and not self.dual_active)
            self.sp_dual_blocks.setEnabled(on and not self.dual_active and self.chk_dual_blocks.isChecked())
        if hasattr(self, 'lbl_dual_taumax'):
            self.lbl_dual_taumax.setVisible(self.dual_tau_w['F'].value() > TAU_USEFUL_MAX + 1e-9)
        for k in ('F', 'M'):
            self.dual_tau_lbl[k].setText('τ max:' if on else 'τ:')
            self.dual_tau_w[k].setToolTip(
                'τ max da varredura (τ adaptativo ligado): a varredura começa nele e o τ muda conforme a flutuação,\n'
                'sem passar desse valor.\n'
                'É o mesmo τ do INMP441: mudar aqui muda lá e vice-versa.' if on else
                'τ dos dois lock-ins durante a varredura (integração longa): espera 9τ e faz a média por 1τ em\n'
                'cada ponto. É o mesmo τ do INMP441: mudar aqui muda lá e vice-versa (e na outra varredura).')

    def _dual_times(self, kind, value, bound=None):
        """(espera, medida) do ponto. O LP de 2 polos chega a ~1e-3 do degrau em 9τ. τ adaptativo: com o τ
        atual da varredura ('est', durante ela), o τ inicial ('max') ou o mínimo da frequência ('min')."""
        if self._dual_adaptive(kind):
            fixed = self._lowf_fixed_tau(kind, value)
            if fixed is not None:
                settle, meas = adapt_times(fixed)
                return settle, meas * self._adapt_blocks_max()      # "Permitir médias": N medidas por ponto
            tau0 = self._adapt_cap(kind)
            tmin = adapt_tau_min(value)
            if bound == 'est' and getattr(self, 'adapt_tau_cur', None):
                tau = max(tmin, self.adapt_tau_cur)
            elif bound == 'min':
                tau = tmin
            else:
                tau = max(tmin, tau0)
            return adapt_times(tau)
        if self.dual_mode_w[kind].currentIndex() == 1:
            tau = self.dual_tau_w[kind].value()
            return 9.0 * tau + 0.3, max(0.5, tau)
        if kind in ('F', 'M'):
            # A troca de frequência aplica os cortes automáticos nos dois lock-ins (apply_frequency)
            lp = get_effective_cutoffs(value)[0]
            tau = max(lp_tau(lp, RATE.FS), lp_tau(lp, AUDIO_FS_REAL))
        else:
            tau = max(lp_tau(self.cutoff_lp, RATE.FS), lp_tau(self.audio_cutoff_lp, AUDIO_FS_REAL))
        return max(1.0, 9.0 * tau) + 0.3, max(1.0, 4.0 * tau)

    def update_dual_eta(self, *_):
        if self.dual_active:
            return
        tau_now = max(lp_tau(self.cutoff_lp, RATE.FS), lp_tau(self.audio_cutoff_lp, AUDIO_FS_REAL))
        for kind, cmb in self.dual_mode_w.items():
            if cmb.currentIndex() == 0 and abs(self.dual_tau_w[kind].value() - tau_now) > 0.005:
                self._set_spin(self.dual_tau_w[kind], tau_now)
        if hasattr(self, 'chk_dual_avoid60'):
            self._update_dual_mains()
        for kind, lbl in self.dual_etas.items():
            values = self._dual_planned(kind)
            reps = self.sp_dual_reps.value() if (kind in ('F', 'M') and hasattr(self, 'sp_dual_reps')) else 1
            total = reps * sum(sum(self._dual_times(kind, v)) for v in values)
            if self._dual_adaptive(kind):
                tmin = reps * sum(sum(self._dual_times(kind, v, 'min')) for v in values)
                self._eta_set(lbl, f'Tempo estimado: {self._fmt_time(tmin)}\u00a0a\u00a0{self._fmt_time(total)}')
                lbl.setToolTip(f'{len(values)} pontos. τ adaptativo: do τ mínimo em todos os pontos ao τ max em todos.')
            else:
                self._eta_set(lbl, f'Tempo estimado: {self._fmt_time(total)}')
                lbl.setToolTip(f'{len(values)} pontos' + (f' × {reps} repetições' if reps > 1 else ''))

    def _update_dual_mains(self):
        """Caixa "Evitar múltiplos de 60 Hz": a dica lista os pontos deslocados; desligada, aviso laranja."""
        _vals, moved = soi_serie.avoid_mains(self._dual_planned('F', raw=True))
        on = self._mains_fixed()
        lst = ', '.join(f'{a:g} → {b:g} Hz' for a, b in moved)
        self.chk_dual_avoid60.setToolTip(
            f'Pontos a até {soi_serie.MAINS_NEAR_HZ:g} Hz de um múltiplo de 60 Hz pegam o fundo da rede (o OPT101 mostra\n'
            f'fundo em 300 Hz; em 18/11 o ponto de 121,2 Hz batia com 120 Hz). Ligada (padrão): esses pontos vão para\n'
            f'k·60 ± {soi_serie.MAINS_SWEEP_SHIFT_HZ:g} Hz, do lado em que estavam, e ficam listados no cabeçalho do CSV.'
            + (f'\nNesta varredura: {lst}' if moved else '\nNesta varredura nenhum ponto cai perto da rede.'))
        self.lbl_dual_mains.setText(f'⚠ perto de múltiplos de 60 Hz: {len(moved)} ponto(s)' if moved else '')
        self.lbl_dual_mains.setToolTip(lst)
        self.lbl_dual_mains.setVisible(False)          # sem a caixa da rede, não há o caso "desligada"
        self.lbl_dual_mains.setText(f'(+ múltiplos de 60 Hz: {len(moved)} ponto(s))' if on and moved else '')
        self.lbl_dual_mains.setToolTip('Nenhuma detecção de ruído em uso: os pontos perto de múltiplos de 60 Hz são\n'
                                       'deslocados por segurança: ' + lst if on and moved else '')
        self.lbl_dual_mains.setStyleSheet('color:gray;')
        self.lbl_dual_mains.setVisible(bool(on and moved))
        base = _vals if on else self._dual_planned('F', raw=True)
        _v2, moved2 = soi_serie.avoid_list(base, self._dual_avoid_extra())
        self.ed_dual_avoid.setStyleSheet('font-weight:bold;' if moved2 else '')
        self.ed_dual_avoid.setToolTip(self._avoid_tip + ('\nNesta varredura: ' + ', '.join(f'{a:g} → {b:g} Hz' for a, b in moved2)
                                             if moved2 else ''))

    def _mains_warn(self, spin):
        """Aviso laranja ao lado de um campo de frequência fixa perto de um múltiplo de 60 Hz, com "Deslocar"."""
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lbl = QtWidgets.QLabel('')
        lbl.setStyleSheet(f'color:{LOWF_WARN_COLOR};font-weight:bold;')
        btn = QtWidgets.QPushButton('Deslocar')
        btn.setToolTip(f'Troca pela frequência sugerida (k·60 ± {soi_serie.MAINS_FIX_SHIFT_HZ:g} Hz).')
        btn.setStyleSheet('padding:0px 6px;')
        lay.addWidget(lbl)
        lay.addWidget(btn)

        def upd(*_):
            msg = soi_serie.mains_msg(spin.value())
            lbl.setText(msg)
            w.setVisible(bool(msg) and not self.ext_mode if hasattr(self, 'ext_mode') else bool(msg))
        btn.clicked.connect(lambda: spin.setValue(soi_serie.mains_suggest(spin.value())))
        spin.valueChanged.connect(upd)
        QtCore.QTimer.singleShot(0, upd)
        return w

    def _dual_set_long_tau(self, kind=None):
        kind = kind or self.dual_src
        if self._dual_adaptive(kind) and self.dual_active and getattr(self, 'adapt_tau_cur', None):
            tau = self._adapt_tau_at(kind, self.ref_freq)                    # τ do ponto atual
        elif self.dual_active:
            tau = self._fixed_tau_at(kind, self.ref_freq)
        else:           # antes do 1º ponto (o τ do INMP441 está ligado ao campo: não o trocar por 4 s aqui)
            tau = self.dual_tau_w[kind].value()
        self.sp_tau.setValue(tau)
        self.sp_audio_tau.setValue(tau)

    def _check_cal_conditions(self):
        '''Antes da varredura da calibração: avisa se o PWM não está em 100 %, se algum filtro de 60 Hz está ligado
        ou se "Usar" (calibração aplicada) está marcado. Devolve False se o usuário cancelar.'''
        issues = []
        if self.sp_power.value() < CAL_SWEEP_PWM - 1e-6:
            issues.append(f'PWM do laser em {self.sp_power.value():g} % (recomendado {CAL_SWEEP_PWM:g} %, mais sinal).')
        on = [n for n, c in (('OPT101', self.chk_mains), ('INMP441', self.chk_audio_mains)) if c.isChecked()]
        if on:
            issues.append('Filtro de 60 Hz ligado (' + ' e '.join(on) + '): desloca a fase'
                          + (' de um lock-in e contamina Δφ.' if len(on) == 1 else ' e a amplitude perto de 60 Hz.'))
        if self.chk_mic_cal.isChecked():
            issues.append('"Usar" da calibração marcado: a calibração nova precisa dos dados brutos.')
        if not issues:
            return True
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle('Varredura da calibração')
        box.setText('Antes de calibrar, confira:')
        box.setInformativeText('\n'.join('• ' + t for t in issues))
        fix = box.addButton('Corrigir e rodar', QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton('Rodar assim', QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('Cancelar', QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(fix)
        box.exec()
        if box.clickedButton() is fix:
            if self.sp_power.value() < CAL_SWEEP_PWM - 1e-6:
                self.sp_power.setValue(CAL_SWEEP_PWM)
            self.chk_mains.setChecked(False)
            self.chk_audio_mains.setChecked(False)
            self.chk_mic_cal.setChecked(False)
            self.flash(f'PWM {CAL_SWEEP_PWM:g} %, filtros de 60 Hz desligados e calibração desmarcada: confira o pico do OPT101 (% da saturação).', 6.0)
            return True
        return box.clickedButton() is keep

    # ------------------------------------------------------------ Varredura manual (modulação óptica)
    def _build_manual_sweep_box(self):
        '''Quadro da varredura em frequência com modulação óptica: você muda a frequência do chopper e a
        interface grava um ponto quando ela fica estável (ou quando você manda).'''
        box = self._group('Varredura em frequência manual (modulação óptica)')
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(6, 2, 6, 4)
        lay.setSpacing(3)
        row = QtWidgets.QHBoxLayout()
        self.chk_man_auto = QtWidgets.QCheckBox('Gravar sozinho quando a frequência estabilizar')
        self.chk_man_auto.setChecked(True)
        self.chk_man_auto.setToolTip('Grava um ponto quando o PLL está travado, a frequência fica estável (desvio no\n'
                                     'último segundo ≤ "estável") e ela está longe o bastante do último ponto ("passo mínimo").\n'
                                     'Desmarcado: só grava com "Gravar ponto".')
        row.addWidget(self.chk_man_auto)
        row.addStretch(1)
        lay.addLayout(row)
        row = soi_layout.FlowBar(hspace=6, vspace=3, last_right=False)     # 2.5.0: quebra no painel lateral
        g = row.group()
        g.addWidget(QtWidgets.QLabel('Passo mínimo:'))
        self.sp_man_step = self._dspin(0.1, 100.0, 5.0, 1, 1.0, None, 80, ' %')
        self.sp_man_step.setToolTip('Distância mínima (em %) entre a frequência de um ponto novo e a do último gravado.')
        g.addWidget(self.sp_man_step)
        g = row.group()
        g.addWidget(QtWidgets.QLabel('estável:'))
        self.sp_man_tol = self._dspin(0.01, 10.0, 0.5, 2, 0.1, None, 80, ' %')
        self.sp_man_tol.setToolTip('Desvio padrão máximo da frequência (último segundo, em % dela) para considerá-la estável.\n'
                                   'Durante a espera e a medida do ponto, ela pode mudar no máximo 2× isso (mínimo 1 %).')
        g.addWidget(self.sp_man_tol)
        g = row.group()
        g.addWidget(QtWidgets.QLabel('τ:'))
        self.sp_man_tau = TauSpinBox(CAL_SWEEP_TAU, None, width=80)
        self.sp_man_tau.setToolTip('τ dos dois lock-ins durante a varredura manual (restaurado no fim). Cada ponto espera\n'
                                   '9τ depois que a frequência estabiliza e faz a média por 1τ.')
        g.addWidget(self.sp_man_tau)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.btn_man_start = QtWidgets.QPushButton('▶ Iniciar')
        self.btn_man_start.setStyleSheet('background:#cfe2ff;')
        self.btn_man_start.setMinimumWidth(110)
        self.btn_man_start.setToolTip('Começa uma varredura manual. Mude a frequência do chopper aos poucos; cada ponto\n'
                                      'espera 9τ e mede por 1τ. "Concluir" salva o CSV (DUPLO_freq_…_optica_…).')
        self.btn_man_start.clicked.connect(lambda: self.toggle_manual_sweep())
        row.addWidget(self.btn_man_start)
        self.btn_man_point = QtWidgets.QPushButton('Gravar ponto')
        self.btn_man_point.setToolTip('Mede um ponto na frequência atual agora, mesmo perto do último.')
        self.btn_man_point.clicked.connect(self.manual_record_now)
        self.btn_man_point.setEnabled(False)
        row.addWidget(self.btn_man_point)
        self.lbl_man = QtWidgets.QLabel('')
        self.lbl_man.setStyleSheet('font-family:Consolas,monospace;')
        self.lbl_man.setWordWrap(True)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.lbl_man)
        return box

    def toggle_manual_sweep(self, slot=None):
        if self.dual_active:
            if self.dual_src == 'X':
                self._finish_manual_sweep()
            return
        if self.average_mode:
            self.flash('As varreduras do Modo Duplo precisam do OPT101 no Modo Lock-In.')
            return
        if self.sweep_active:
            self.flash('Já existe uma varredura em andamento.')
            return
        if not self.chk_audio_lockin.isChecked() and not self.chk_audio_noise.isChecked():
            self.chk_audio_lockin.setChecked(True)
        tau = self.sp_man_tau.value()
        self.dual_saved_cutoffs = (self.sp_tau.value(), self.sp_audio_tau.value())
        self.sp_tau.setValue(tau)
        self.sp_audio_tau.setValue(tau)
        self.dual_src = 'X'
        self.dual_kind = 'F'
        self.dual_values = []
        self.dual_refine = False
        self.dual_view_manual = False
        self.dual_results = []
        self.dual_fstd = []
        self.dual_pinfo = []
        self.dual_excluded = set()
        self.dual_ref_cfg = []
        self.dual_fit = None
        self.dual_params = {'kind': 'F', 'values': [], 'freq': None, 'pwm': 0.0, 'mod': 'optica',
                            'mode': DUAL_MODE_NAMES[1], 'tau': tau}
        self.dual_restore = None
        self.cal_pending = slot
        self.dual_active = True
        self.man_force = False
        self.man_last_f = None
        self.dual_settle, self.dual_measure = 9.0 * tau + 0.3, max(0.5, tau)
        self.dual_state = 'WAIT'
        self.dual_timer = time.perf_counter()
        self.btn_man_start.setText('⏹ Concluir')
        self.btn_man_start.setStyleSheet('background:#f8d7da;')
        self.btn_man_point.setEnabled(True)
        for w in (self.sp_tau, self.sp_audio_tau, self.cmb_mod, self.sp_man_tau):
            w.setEnabled(False)
        self._setup_dual_plots('F')
        self._apply_mod_ui()
        self.lbl_dual_status.setText('Varredura manual: ajuste o chopper; o ponto é gravado quando a frequência estabilizar.')

    def manual_record_now(self):
        if self.dual_active and self.dual_src == 'X':
            self.man_force = True
            if self.dual_state != 'WAIT':
                self.flash('Já há um ponto sendo medido.')

    def _finish_manual_sweep(self):
        slot = self.cal_pending
        if self.dual_state in ('SETTLING', 'MEASURING'):
            self.flash('Ponto em andamento descartado.')
        self._end_dual_sweep()
        self.btn_man_start.setText('▶ Iniciar')
        self.btn_man_start.setStyleSheet('background:#cfe2ff;')
        self.btn_man_point.setEnabled(False)
        self.cmb_mod.setEnabled(True)
        self.sp_man_tau.setEnabled(True)
        self.lbl_man.setText('')
        if self.dual_results:
            self.dual_params['values'] = [r[0] for r in self.dual_results]
            self._export_dual()
            if slot:
                self._cal_take(slot)
        else:
            self.lbl_dual_status.setText('Varredura manual concluída sem pontos.')
            if slot:
                self.lbl_cal_s_state[slot].setText(self._cal_slot_text(slot))

    # ------------------------------------------------------------ Sinal x t (deriva)
    def _build_time_box(self):
        """Quadro "Sinal x t (s)": frequência e PWM fixos; a cada 'Ponto a cada' segundos grava a média de S, Δφ,
        R do OPT101 e R do microfone (com o desvio-padrão), por 'Duração' minutos (0 = até parar)."""
        self.sp_dt_f = self._dspin(0.5, 5000.0, 10.0, 2, 1.0, None, 100, ' Hz')
        self.sp_dt_pwm = self._dspin(0.0, 100.0, 100.0, 1, 5.0, None, 90, ' %')
        self.sp_dt_tau = self._dspin(0.05, 30.0, 1.0, 2, 0.5, None, 80, ' s')
        self.sp_dt_dt = self._dspin(0.5, 600.0, 5.0, 1, 1.0, None, 80, ' s')
        self.sp_dt_dur = self._dspin(0.0, 1440.0, 10.0, 1, 1.0, None, 90, ' min')
        self.sp_dt_tau.setToolTip('τ dos dois lock-ins durante a medida (restaurado no fim). Use τ menor que o intervalo\n'
                                  'entre pontos para os pontos serem independentes.')
        self.sp_dt_dt.setToolTip('Cada ponto é a média (e o desvio-padrão, nas barras de erro) dos lock-ins neste intervalo.')
        self.sp_dt_dur.setToolTip('Duração da medida; 0 = até clicar em Parar. O CSV e o PNG são gravados no fim.')
        box, btn, eta, bar = self._make_sweep_box(
            'Sinal x t (s)', (('Frequência:', self.sp_dt_f), ('', self._mains_warn(self.sp_dt_f)), ('PWM:', self.sp_dt_pwm)),
            lambda _=False: self.toggle_dual_time(),
            extra=(('τ:', self.sp_dt_tau), ('Ponto a cada:', self.sp_dt_dt), ('Duração:', self.sp_dt_dur)),
            warm_pwm=lambda: self.sp_dt_pwm.value())
        btn.setText('▶ Iniciar')
        self._eta_set(eta, '')
        self.btn_dt_start, self.lbl_dt_eta, self.bar_dt = btn, eta, bar
        box.setToolTip('O laser começa a modular na frequência e no PWM escolhidos ao clicar em Iniciar. Os primeiros 7τ\n'
                       '(assentamento dos lock-ins) são descartados; o tempo é contado desde o início (o aquecimento aparece).')
        return box

    def toggle_dual_time(self):
        if self.dual_active:
            if self.dual_src == 'T':
                self._finish_dual_time()
            else:
                self.flash('Termine ou cancele a medida em andamento antes.')
            return
        if self.ext_mode:
            self.flash('Sinal x t usa a modulação eletrônica (o STM32 fixa a frequência).')
            return
        if self.average_mode:
            self.flash('O Modo Duplo precisa do OPT101 no Modo Lock-In.')
            return
        if self.sweep_active:
            self.flash('Já existe uma varredura em andamento.')
            return
        if not self.chk_audio_lockin.isChecked() and not self.chk_audio_noise.isChecked():
            self.chk_audio_lockin.setChecked(True)
        f, pwm, tau = self.sp_dt_f.value(), self.sp_dt_pwm.value(), self.sp_dt_tau.value()
        self.dual_saved_cutoffs = (self.sp_tau.value(), self.sp_audio_tau.value())
        self.sp_tau.setValue(tau)
        self.sp_audio_tau.setValue(tau)
        self._set_spin(self.sp_freq, f)
        self.apply_frequency(f)
        self.sp_power.setValue(pwm)
        self.on_power(self.sp_power.value())
        self.dual_src = self.dual_kind = 'T'
        self.dual_values = []
        self.dual_refine = False
        self.dual_view_manual = False
        self.dual_results = []
        self.dual_pinfo = []
        self.dual_excluded = set()
        self.dual_ref_cfg = []
        self.dual_fit = None
        self.dual_restore = None
        self.cal_pending = None
        self.dual_params = {'kind': 'T', 'values': [], 'freq': f, 'pwm': pwm, 'mode': DUAL_MODE_NAMES[1],
                            'tau': tau, 'dt': self.sp_dt_dt.value(), 't_start': datetime.now()}
        self.dual_active = True
        now = time.perf_counter()
        self.dt_t0 = self.dual_timer = self.point_t0 = now
        self.dual_state = 'MEASURING'
        self.dual_opt = []
        with self.audio_lock:
            self.dual_aud = []
        self.btn_dt_start.setText('⏹ Parar')
        self.btn_dt_start.setStyleSheet('background:#f8d7da;')
        dur = self.sp_dt_dur.value() * 60.0
        self.bar_dt.setValue(0)
        self.bar_dt.setVisible(dur > 0)
        for w in (self.sp_freq, self.sp_power, self.sp_tau, self.sp_audio_tau, self.cmb_mod, self.sp_dt_f,
                  self.sp_dt_pwm, self.sp_dt_tau, self.sp_dt_dt, self.sp_dt_dur):
            w.setEnabled(False)
        for b in list(self.dual_btns.values()) + list(self.btn_sweeps.values()) + list(self.btn_sweeps_aud.values()):
            b.setEnabled(False)
        self._setup_dual_plots('T')
        print(f'Sinal x t: {f:g} Hz, PWM {pwm:g} %, τ = {tau:g} s, ponto a cada {self.sp_dt_dt.value():g} s, '
              + (f'{dur / 60:g} min' if dur else 'até parar'))

    def _time_step(self, now):
        t = now - self.dt_t0
        dt = self.dual_params.get('dt', 5.0)
        dur = self.sp_dt_dur.value() * 60.0
        n = len(self.dual_results)
        last = ''
        if n:
            r = self.dual_results[-1]
            last = f' | último: S = {r[3] / max(r[1], 1e-30):.4g}, Δφ = {wrap_deg(r[5] - r[7]):.2f}°'
        self._dual_bar(f'Sinal x t: {self._fmt_time(t)}' + (f' de {self._fmt_time(dur)}' if dur else '')
                       + f' | {self.dual_params["freq"]:g} Hz, PWM {self.dual_params["pwm"]:g} % | {n} ponto(s){last}')
        if dur:
            self.bar_dt.setValue(int(1000 * min(1.0, t / dur)))
            self.lbl_dt_eta.setText(f'Restante: {self._fmt_time(dur - t)}')
        else:
            self.lbl_dt_eta.setText(f'Decorrido: {self._fmt_time(t)}')
        settle = 7.0 * self.dual_params['tau']          # lock-ins assentando: descarta, mas o tempo conta desde o início
        if t < settle:
            self.dual_opt = []
            with self.audio_lock:
                self.dual_aud = []
            self.dual_timer = now
            self._dual_bar(f'Sinal x t: {self._fmt_time(t)} | lock-ins assentando ({t:.0f}/{settle:.0f} s), '
                           f'{self.dual_params["freq"]:g} Hz, PWM {self.dual_params["pwm"]:g} %')
            return
        if now - self.dual_timer >= dt:
            with self.audio_lock:
                aud = self.dual_aud
                self.dual_aud = []
            opt = self.dual_opt
            self.dual_opt = []
            if opt and aud:
                r_o = np.concatenate([c[0] for c in opt])
                p_o = np.concatenate([c[1] for c in opt])
                r_a = np.concatenate([c[0] for c in aud])
                p_a = np.concatenate([c[1] for c in aud])
                _, fl_s, fl_p = self._adapt_fluct(r_o, p_o, r_a, p_a)
                fp = self.fluct_parts
                if self.normalize_mode:
                    r_o = r_o * np.maximum(np.concatenate([c[2] for c in opt]), 1.0) / 100.0
                tm = 0.5 * (self.dual_timer + now) - self.dt_t0
                self.dual_results.append((tm, float(r_o.mean()), float(r_o.std()), float(r_a.mean()), float(r_a.std()),
                                          *circ_stats_deg(p_a), *circ_stats_deg(p_o)))
                self.dual_pinfo.append((self.dual_params['tau'], now - self.dual_timer, 0, fl_s, fl_p,
                                        fp['drift_s'], fp['drift_p'], fp['drift_opt'], fp['drift_mic']))
                self.dual_params['values'] = [r[0] for r in self.dual_results]
                self._show_dual_results()
            self.dual_timer = now
        if dur and t >= dur:
            self._finish_dual_time()

    def _finish_dual_time(self):
        self._end_dual_sweep()
        self.btn_dt_start.setText('▶ Iniciar')
        self.btn_dt_start.setStyleSheet('background:#cfe2ff;')
        self.bar_dt.setVisible(False)
        for w in (self.cmb_mod, self.sp_dt_f, self.sp_dt_pwm, self.sp_dt_tau, self.sp_dt_dt, self.sp_dt_dur):
            w.setEnabled(True)
        if self.dual_results:
            self.dual_params['values'] = [r[0] for r in self.dual_results]
            self._show_dual_results()
            self._export_dual()
        else:
            self.lbl_dual_status.setText('Sinal x t concluído sem pontos.')

    def _show_time_results(self, x, ro, ro_e, ra, ra_e, pa, pa_e, po, po_e, keep):
        """Sinal x t: S e Δφ no tempo com barras de erro (±1 DP de cada intervalo) e, no quadro Resultados, a variação
        total, a deriva no último terço e, com pontos suficientes, a constante de tempo de S(t) = A + B·e^(−t/T)."""
        for name in ('lbl_dual_tau', 'lbl_dual_cal'):
            getattr(self, name).setText('')
        ok = (ro > 0) & (ra > 0)
        s = np.where(ok, ra / np.maximum(ro, 1e-30), np.nan)
        s_rel = np.sqrt((ra_e / np.maximum(ra, 1e-30)) ** 2 + (ro_e / np.maximum(ro, 1e-30)) ** 2)
        dphi = np.degrees(np.unwrap(np.radians(wrap_deg(pa - po))))
        dphi_e = np.sqrt(pa_e ** 2 + po_e ** 2)
        self._set_dual_points(x[ok], s[ok], np.flatnonzero(ok), keep[ok])
        self._set_errbar(self.e_dual_a, x=x[ok], y=s[ok], height=2 * (s * s_rel)[ok], beam=0)
        self.c_dual_b.setData(x, dphi)
        self._set_errbar(self.e_dual_b, x=x, y=dphi, height=2 * dphi_e, beam=0)
        for e in (self.e_dual_a_cal, self.e_dual_b_cal):
            self._set_errbar(e, x=np.empty(0), y=np.empty(0))
        for c in (self.c_dual_a_fit, self.c_dual_b_fit, self.c_dual_a_bad):
            c.setData([], [])
        m = ok & keep
        txt = ''
        if m.sum() >= 3:
            xs, ss = x[m], s[m]
            k = max(1, m.sum() // 5)
            s0, s1 = float(np.mean(ss[:k])), float(np.mean(ss[-k:]))
            p0, p1 = float(np.mean(dphi[m][:k])), float(np.mean(dphi[m][-k:]))
            txt = (f'<b>Sinal x t:</b> S variou {100 * (s1 / s0 - 1):+.2f} % e Δφ {p1 - p0:+.2f}° entre o início e o fim '
                   f'({xs[-1] - xs[0]:.0f} s); OPT101 {100 * (np.mean(ro[m][-k:]) / np.mean(ro[m][:k]) - 1):+.2f} %, '
                   f'microfone {100 * (np.mean(ra[m][-k:]) / np.mean(ra[m][:k]) - 1):+.2f} %.')
            third = xs >= xs[0] + 2.0 * (xs[-1] - xs[0]) / 3.0
            if third.sum() >= 3:
                c = np.polyfit(xs[third] / 60.0, ss[third], 1)
                txt += f' Deriva de S no último terço: {100 * c[0] / max(abs(float(np.mean(ss[third]))), 1e-30):+.2f} %/min.'
            if m.sum() >= 8:
                try:
                    from scipy.optimize import curve_fit
                    f_exp = lambda t, A, B, T: A + B * np.exp(-(t - xs[0]) / T)
                    span = max(float(xs[-1] - xs[0]), 1.0)
                    popt, pcov = curve_fit(f_exp, xs, ss, p0=(s1, s0 - s1, span / 3.0), maxfev=4000)
                    T = float(popt[2])
                    if 2.0 * self.dual_params.get('dt', 0.0) < T < 20.0 * span and np.all(np.isfinite(pcov)):
                        tt = np.linspace(float(xs[0]), float(xs[-1]), 200)
                        self.c_dual_a_fit.setData(tt, f_exp(tt, *popt))
                        txt += (f' Ajuste S(t) = A + B·e<sup>−t/T</sup>: T = {T:.0f} ± {np.sqrt(pcov[2, 2]):.0f} s, '
                                f'S final estimado {popt[0]:.4g} ({100 * popt[1] / popt[0]:+.1f} % no início).')
                        self.dual_fit = self._plain(txt.split('Ajuste ', 1)[1])
                except Exception:
                    pass
        self.lbl_dual_fit.setText(txt + self._dual_excluded_text())

    def _manual_step(self, now):
        r = self.ext_ref
        f = r.f_mean if (r.state == 'TRACK' and r.f_mean is not None) else None
        tol = self.sp_man_tol.value() / 100.0
        elapsed = now - self.dual_timer
        npts = len(self.dual_results)
        last = f' | último: {self.man_last_f:.2f} Hz' if self.man_last_f else ''
        if self.dual_state == 'WAIT':
            if f is None or not r.locked:
                self.lbl_man.setText(f'{npts} pontos | esperando o PLL travar')
                return
            stable = r.f_std is not None and r.f_std <= tol * f
            far = self.man_last_f is None or abs(f / self.man_last_f - 1.0) >= self.sp_man_step.value() / 100.0
            self.lbl_man.setText(f'{npts} pontos | f = {f:.2f} Hz ' + ('estável' if stable else 'variando') + last)
            if self.man_force or (self.chk_man_auto.isChecked() and stable and far):
                self.man_force = False
                self.man_f0 = f
                self.man_fs = []
                self.dual_state = 'SETTLING'
                self.dual_timer = now
            return
        # Durante a espera e a medida a frequência não pode fugir do ponto
        drift = max(2.0 * tol, 0.01)
        if f is None or not r.locked or abs(f / self.man_f0 - 1.0) > drift:
            self.flash('A frequência mudou (ou o PLL destravou) durante o ponto: descartado; esperando estabilizar.')
            self.dual_state = 'WAIT'
            self.dual_timer = now
            return
        if self.dual_state == 'SETTLING':
            self.lbl_man.setText(f'{npts} pontos | {self.man_f0:.2f} Hz: estabilizando '
                                 f'({elapsed:.1f}/{self.dual_settle:.1f} s){last}')
            if elapsed >= self.dual_settle:
                self.dual_state = 'MEASURING'
                self.dual_timer = now
                self.dual_opt = []
                with self.audio_lock:
                    self.dual_aud = []
            return
        self.man_fs.append(f)
        self.lbl_man.setText(f'{npts} pontos | {self.man_f0:.2f} Hz: medindo ({elapsed:.1f}/{self.dual_measure:.1f} s){last}')
        if elapsed < self.dual_measure:
            return
        with self.audio_lock:
            aud = self.dual_aud
            self.dual_aud = []
        self.dual_state = 'WAIT'
        self.dual_timer = now
        if not (self.dual_opt and aud):
            self.flash('Varredura manual: sem dados do OPT101 ou do INMP441 (o microfone já está alinhado?).')
            return
        r_o = np.concatenate([c[0] for c in self.dual_opt])
        p_o = np.concatenate([c[1] for c in self.dual_opt])
        if self.normalize_mode:
            r_o = r_o * np.maximum(np.concatenate([c[2] for c in self.dual_opt]), 1.0) / 100.0
        r_a = np.concatenate([c[0] for c in aud])
        p_a = np.concatenate([c[1] for c in aud])
        fv = float(np.mean(self.man_fs)) if self.man_fs else self.man_f0
        row = (fv, float(r_o.mean()), float(r_o.std()), float(r_a.mean()), float(r_a.std()),
               *circ_stats_deg(p_a), *circ_stats_deg(p_o))
        self.dual_results.append(row)
        self.dual_fstd.append(float(np.std(self.man_fs)) if len(self.man_fs) > 1 else 0.0)
        self.dual_ref_cfg.append((self.cutoff_hp, self.chk_mains.isChecked()))
        self.dual_params['values'] = [x[0] for x in self.dual_results]
        self.man_last_f = fv
        self._show_dual_results()
        self.flash(f'Ponto gravado: {fv:.2f} Hz ({len(self.dual_results)} pontos).', 3.0)
