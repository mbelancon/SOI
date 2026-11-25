# -*- coding: utf-8 -*-
'''Modo Duplo: painéis, abrir varredura salva e ajuste de modelos.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class DualPanelsMixin:
    def set_display_mode(self, average):
        '''Botões Lock-In / Valor Médio da aba OPT101.'''
        if average != self.average_mode:
            self.toggle_display_mode()
        (self.btn_mode_avg if self.average_mode else self.btn_mode_li).setChecked(True)

    def on_audio_sweeps_panel(self, checked):
        self.audio_sweeps_panel.setVisible(checked)
        self.btn_audio_sweeps.setText('Varreduras ▾' if checked else 'Varreduras ▸')

    def on_dual_sweeps_panel(self, checked):
        '''Painel "Executar varreduras" do Modo Duplo (quadros das varreduras casada e em frequência).'''
        self.dual_cal_scroll.setVisible(checked)
        if checked:
            QtCore.QTimer.singleShot(0, self._fit_dual_cal_scroll)
        self.btn_dual_sweeps_panel.setText('Calibração ' + ('▾' if checked else '▸'))
        self.btn_dual_cal_panel.setChecked(checked)

    def _fit_dual_cal_scroll(self):
        '''Altura da área do painel Calibração = altura do conteúdo (+ barra horizontal, se aparecer).'''
        sc = self.dual_cal_scroll
        if not sc.isVisible():
            return
        panel = self.dual_sweeps_panel
        w = max(sc.viewport().width(), panel.minimumSizeHint().width())
        # Os textos com quebra de linha informam no sizeHint a altura para uma largura estreita, o que deixava um
        # espaço cinza grande sob os passos; a altura certa é a da largura real do painel
        h = panel.heightForWidth(w) if panel.hasHeightForWidth() else -1
        if h <= 0:
            h = panel.sizeHint().height()
        if panel.minimumSizeHint().width() > sc.viewport().width():
            h += sc.horizontalScrollBar().sizeHint().height()
        # Teto de ~40 % da altura da tela (com barra de rolagem vertical): numa janela estreita os textos quebram e o
        # painel crescia até a janela passar da tela (o Windows só acertava ao restaurar e maximizar de novo)
        scr = self.screen() or QtWidgets.QApplication.primaryScreen()
        if scr is not None:
            h = min(h, max(150, int(0.4 * scr.availableGeometry().height())))
        if sc.height() != h + 2:
            sc.setFixedHeight(h + 2)

    def on_dual_pwm_panel(self, checked):
        '''Painel "Varreduras" do Modo Duplo (medidas: em frequência e casada em PWM).'''
        self.dual_pwm_panel.setVisible(checked)
        self.btn_dual_pwm_panel.setText('Sinal x f (Hz) ' + ('▾' if checked else '▸'))

    def open_dual_sweep(self):
        '''Carrega um CSV do Modo Duplo salvo e o exibe como se a varredura tivesse acabado de rodar.'''
        if self.dual_active or self.sweep_active:
            self.flash('Termine ou cancele a varredura em andamento antes de abrir outra.')
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Abrir varredura do Modo Duplo', MEDIDAS_DIR,
            'Varreduras do Modo Duplo (*DUPLO*.csv);;Todos os CSV (*.csv)')
        if path:
            self.load_dual_sweep(path)

    def load_dual_sweep(self, path):
        try:
            kind, rows, params = load_dual_csv(path)
        except (OSError, ValueError, IndexError) as e:
            QtWidgets.QMessageBox.warning(self, 'Abrir varredura', f'Não foi possível abrir {os.path.basename(path)}:\n{e}')
            return
        self.dual_kind = self.dual_src = kind
        self.dual_results = rows
        self.dual_pinfo = params.pop('pinfo', [])
        self.dual_params = params
        self.dual_excluded = set()
        self.dual_ref_cfg = []          # cortes do OPT101 em cada ponto não ficam no CSV: sem diagnóstico do τ óptico
        self.dual_fit = None
        self.dual_last_csv = path
        self._setup_dual_plots(kind)
        self._show_dual_results()
        self.btn_dual_resave.setEnabled(True)
        what = 'em frequência' if kind == 'F' else 'casada em PWM'
        self.lbl_dual_status.setText(f'Varredura aberta ({what}, {len(rows)} pontos): {os.path.basename(path)}')

    def on_dual_model_panel(self, checked):
        '''Painel "Ajuste com modelos" do Modo Duplo; fechado, nenhum modelo é ajustado.'''
        self.dual_model_box.setVisible(checked)
        self.btn_dual_model_panel.setText('Ajuste ' + ('▾' if checked else '▸'))   # botão escondido (sempre ligado)
        self._show_dual_results()

    def _on_dual_model(self, _=None):
        model = self.cmb_dual_model.currentData()
        self.cmb_dual_model.setToolTip(FREQ_MODEL_TIPS.get(model, 'Escolha um modelo para ajustar à varredura em frequência.'))
        self.cmb_dual_model_target.setEnabled(model not in (None, 'pow', 'pow2', 'band'))   # leis de potência: só magnitude
        self.lbl_dual_model_n.setVisible(model == 'band')
        self.sp_dual_model_n.setVisible(model == 'band')
        self.btn_dual_peak.setEnabled(model == 'res')
        if model != 'res':
            self.btn_dual_peak.setChecked(False)
        self._show_dual_results()

    def _dual_diagnose(self, f, s, dphi):
        '''Botão Diagnóstico: ajusta diagnose_freq aos pontos do ajuste (os mesmos do modelo) e desenha as
        componentes. O resultado fica guardado enquanto os pontos não mudam (o ajuste leva alguns segundos).'''
        for c in self.c_dual_diag:
            c.setData([], [])
        for lg in self.dual_diag_leg:
            lg.clear()
            lg.setVisible(False)
        self.dual_diag_txt = None
        freq = f is not None
        self.btn_dual_diag.setEnabled(freq)
        on = freq and self.btn_dual_diag.isChecked() and not self.dual_active   # não refaz a cada ponto
        self.lbl_dual_diag.setVisible(on)
        if not on:
            return
        key = (np.asarray(f).tobytes(), np.asarray(s).tobytes(), np.asarray(dphi).tobytes())
        if self.dual_diag is None or self.dual_diag[0] != key:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            try:
                self.dual_diag = (key, diagnose_freq(f, s, dphi))
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
        d = self.dual_diag[1]
        if d is None:
            self.lbl_dual_diag.setText('<b>Diagnóstico:</b> são necessários pelo menos 12 pontos cobrindo uma década '
                                       'de frequência.')
            return
        ff = np.logspace(np.log10(d['fmin']), np.log10(d['fmax']), 400)
        tot, pa, bg = d['func'](ff)
        self.c_dual_diag[0].setData(ff, np.abs(tot))
        self.c_dual_diag[1].setData(ff, np.abs(pa))
        if d['bg']:
            self.c_dual_diag[2].setData(ff, np.abs(bg))
        # fase do modelo desenrolada e posta na mesma volta dos dados
        ph = np.degrees(np.unwrap(np.angle(tot)))
        fs_ = np.asarray(f, dtype=float)
        k = np.argsort(fs_)
        off = np.median(np.asarray(dphi, dtype=float)[k] - np.interp(fs_[k], ff, ph))
        self.c_dual_diag[3].setData(ff, ph + 360.0 * np.round(off / 360.0))
        la, lb = self.dual_diag_leg
        la.addItem(self.c_dual_diag[0], 'Modelo (soma)')
        la.addItem(self.c_dual_diag[1], f'Fotoacústico (∝ f⁻ⁿ, n = {d["n"]:.2f})')
        if d['bg']:
            la.addItem(self.c_dual_diag[2], 'Fundo plano (não fotoacústico)')
        lb.addItem(self.c_dual_diag[3], 'Modelo (soma)')
        for lg in self.dual_diag_leg:
            lg.setVisible(True)
        txt, tip = diagnose_text(d, calibrated=self.dual_cal is not None)
        if self.dual_cal is None:
            txt += ('<br><span style="color:#606060;">Sem calibração aplicada, a resposta da célula + microfone entra no '
                    'ajuste e parte do "fundo" pode ser dela. Para separar componentes da amostra, aplique a calibração.</span>')
        self.lbl_dual_diag.setText('<b>Diagnóstico</b> &nbsp; ' + txt)
        self.lbl_dual_diag.setToolTip(tip)
        self.dual_diag_txt = tip.replace('\n', ' ')

    def _on_dual_peak_mode(self, checked):
        '''Liga a captura de dois cliques no gráfico da esquerda (faixa do ajuste da ressonância).'''
        self.dual_peak_clicks = [] if checked else None
        if checked:
            self.flash('Marcar pico: clique no gráfico da esquerda um pouco abaixo e depois um pouco acima do pico.', 8.0)

    def _on_dual_plot_clicked(self, ev):
        if self.dual_peak_clicks is None or ev.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        vb = self.pw_dual_a.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        xv = vb.mapSceneToView(ev.scenePos()).x()
        f = 10.0 ** xv if self.pw_dual_a.getPlotItem().ctrl.logXCheck.isChecked() else xv
        self.dual_peak_clicks.append(float(f))
        if len(self.dual_peak_clicks) < 2:
            self.flash(f'Marcar pico: {f:.4g} Hz; agora clique do outro lado do pico.', 8.0)
            return
        lo, hi = sorted(self.dual_peak_clicks)
        for sp, v in ((self.sp_dual_model_f0, lo), (self.sp_dual_model_f1, hi)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        self.btn_dual_peak.setChecked(False)
        self.flash(f'Faixa da ressonância: {lo:.4g} a {hi:.4g} Hz.', 5.0)
        self._show_dual_results()

    def _fit_dual_model(self, f, s, s_rel, dphi, dphi_e):
        '''Ajusta o modelo escolhido no painel aos pontos da varredura em frequência (já calibrados, se "Usar")
        e desenha as curvas em verde. Recebe só os pontos que entram no ajuste.'''
        self.c_dual_a_model.setData([], [])
        self.c_dual_b_model.setData([], [])
        self.ln_dual_break.setVisible(False)
        for reg in getattr(self, 'reg_dual', ()):
            reg.setVisible(False)
        self.dual_model_txt = None
        model = self.cmb_dual_model.currentData()
        if not self.btn_dual_model_panel.isChecked() or model is None:
            self.lbl_dual_model.setText('')
            return
        target = 'mag' if model in ('pow', 'pow2') else self.cmb_dual_model_target.currentData()
        lo, hi = self.sp_dual_model_f0.value(), self.sp_dual_model_f1.value()     # 0 = sem limite
        if model == 'res':
            self._fit_dual_resonance(f, s, s_rel, dphi, dphi_e, target, lo, hi)
            return
        if model == 'band':
            self._fit_dual_band(f, s, dphi, lo, hi)
            return
        sel = (f >= lo) & ((f <= hi) if hi > 0 else True)
        f, s, s_rel, dphi, dphi_e = f[sel], s[sel], s_rel[sel], dphi[sel], dphi_e[sel]
        need = 5 if model == 'pow2' else 4
        if model == 'pow2':
            r = fit_broken_power(f, s, s_rel) if f.size >= need else None
        else:
            r = fit_freq_model(f, s, s_rel, dphi, dphi_e, model, target) if f.size >= need else None
        if r is None:
            self.lbl_dual_model.setText(f'Ajuste com modelo: são necessários pelo menos {need} pontos válidos.'
                                        if f.size < need else 'Ajuste com modelo: não convergiu.')
            return
        ff = np.geomspace(float(f.min()), float(f.max()), 300)
        z = r['func'](ff)
        if target in ('mag', 'both'):
            self.c_dual_a_model.setData(ff, np.abs(z))
        if target in ('phase', 'both'):
            pz = np.degrees(np.unwrap(np.angle(z)))
            # o modelo é definido a menos de 360°: alinha com a fase desenrolada dos dados
            pz += 360.0 * np.round(np.mean(dphi - np.interp(np.log(f), np.log(ff), pz)) / 360.0)
            self.c_dual_b_model.setData(ff, pz)
        what = {'phase': 'fase', 'mag': 'magnitude', 'both': 'fase e magnitude'}[target]
        parts = [f'<b>{FREQ_MODELS[model]}</b> (ajuste da {what}, {r["n"]} pontos, '
                 f'{f.min():g}–{f.max():g} Hz):']
        if model == 'pow':
            parts.append(f'n = {r["shape"]:.3f} ± {r["shape_err"]:.2g}')
        elif model == 'pow2':
            parts.append(f'n1 = {r["n1"]:.3f} ± {r["n1_err"]:.2g} (abaixo da quebra)')
            parts.append(f'n2 = {r["n2"]:.3f} ± {r["n2_err"]:.2g} (acima)')
            parts.append(f'<b>quebra fb = {r["fb"]:.3g} ± {r["fb_err"]:.2g} Hz</b>')
            self.ln_dual_break.setPos(np.log10(r['fb']))      # eixo X em escala log
            self.ln_dual_break.setVisible(True)
        elif model in FREQ_MODELS_FIXED:
            parts.append(f'expoente fixo n = {FREQ_MODELS_FIXED[model]:g} (sem parâmetro de forma)')
        else:
            f1, e1 = r['shape'], r['shape_err']
            parts.append(f'f1 = α/(πL²) = {f1:.3g} ± {e1:.2g} Hz')
            parts.append(f'L²/α = 1/(π·f1) = {1e3 / (np.pi * f1):.3g} ms')
            L = self.sp_dual_thick.value() * 1e-6
            if L > 0:
                a = np.pi * f1 * L * L
                parts.append(f'<b>α = {a:.3g} ± {a * e1 / f1:.2g} m²/s</b> (L = {L * 1e6:g} µm; '
                             'sem incluir o erro de L, que conta em dobro)')
            else:
                parts.append('informe L para obter α')
        if target in ('mag', 'both'):
            parts.append(f'resíduo rms da magnitude {100 * r["rms_mag"]:.0f} %')
        if target in ('phase', 'both'):
            parts.append(f'resíduo rms da fase {r["rms_phase"]:.1f}°')
        txt = ' &nbsp; '.join(parts)
        if self.dual_cal is None:
            why = ('"Usar" desmarcado' if self.chk_dual_norm.isChecked()
                   else 'sinal sem normalização pelo OPT101')
            txt += (f'<br><span style="color:#d00000;">⚠ Sem calibração aplicada ({why}): magnitude e fase '
                    'incluem a resposta do microfone/célula e o atraso do sistema.</span>')
        self.lbl_dual_model.setText(f'<span style="color:#2e7d32;">{txt}</span>')
        self.dual_model_txt = self._plain(txt.replace(' &nbsp; ', '; ').replace('<br>', ' '))

    def _fit_dual_band(self, f, s, dphi, lo, hi):
        '''Modelo "Faixa com S ∝ f⁻ⁿ": maior faixa em que a amostra segue o n esperado (find_ref_band).'''
        n_exp = self.sp_dual_model_n.value()
        sel = (f >= lo) & ((f <= hi) if hi > 0 else True)
        r = find_ref_band(f[sel], s[sel], dphi[sel], n_exp) if sel.sum() >= 5 else None
        self.dual_band = r if r is not None and r['ok'] else None
        if r is None:
            self.lbl_dual_model.setText('Faixa com S ∝ f⁻ⁿ: são necessários pelo menos 5 pontos válidos na faixa.')
            return
        ff = np.geomspace(r['f_lo'], r['f_hi'], 100)
        self.c_dual_a_model.setData(ff, np.exp(r['lnA']) * ff ** -n_exp)
        dec = np.log10(r['f_hi'] / r['f_lo'])
        nums = (f'n = {r["n"]:.2f} ± {r["n_err"]:.2f}, desvio de f<sup>−{n_exp:g}</sup> {r["rms_db"]:.1f} dB rms, '
                f'fase ± {r["rms_deg"]:.0f}° rms ({r["npts"]} pontos)')
        if r['ok']:
            for reg in self.reg_dual:
                reg.setRegion((np.log10(r['f_lo']), np.log10(r['f_hi'])))
                reg.setVisible(True)
            txt = (f'<b>S ∝ f<sup>−{n_exp:g}</sup> de {r["f_lo"]:.4g} a {r["f_hi"]:.4g} Hz</b> ({dec:.1f} década(s)): {nums}.')
        else:
            txt = (f'<span style="color:#b35c00;"><b>Nenhuma faixa segue f<sup>−{n_exp:g}</sup></b> (critério: n ± 0,15, '
                   f'≤ 1,5 dB rms, fase ± 10° rms). Mais próxima: {r["f_lo"]:.4g}–{r["f_hi"]:.4g} Hz, {nums}.</span>')
        if self.dual_cal is None:
            txt += ('<br><span style="color:#d00000;">⚠ Sem calibração aplicada: a forma inclui a resposta do '
                    'microfone/célula.</span>')
        self.lbl_dual_model.setText(f'<span style="color:#2e7d32;">{txt}</span>')
        self.dual_model_txt = self._plain(txt.replace('<br>', ' '))

    def _fit_dual_resonance(self, f, s, s_rel, dphi, dphi_e, target, lo, hi):
        '''Modelo "Ressonância": f0, Q, largura e ganho do pico (fit_resonance). Faixa vazia = pico automático.'''
        window = None if lo <= 0 and hi <= 0 else (lo if lo > 0 else float(f.min()), hi if hi > 0 else float(f.max()))
        r = fit_resonance(f, s, s_rel, dphi, dphi_e, target, window) if f.size >= 6 else None
        if r is None:
            self.lbl_dual_model.setText('Ressonância: nenhum pico claro encontrado (ou menos de 6 pontos na faixa). '
                                        'Use "Marcar pico" e clique dos dois lados dele.' if window is None else
                                        'Ressonância: o ajuste não convergiu (são necessários pelo menos 6 pontos na faixa).')
            return
        ff = np.linspace(*r['window'], 600)
        z = r['func'](ff)
        if target in ('mag', 'both'):
            self.c_dual_a_model.setData(ff, np.abs(z))
        if target in ('phase', 'both'):
            pz = np.degrees(np.unwrap(np.angle(z)))
            sel = (f >= r['window'][0]) & (f <= r['window'][1])
            pz += 360.0 * np.round(np.mean(dphi[sel] - np.interp(f[sel], ff, pz)) / 360.0)
            self.c_dual_b_model.setData(ff, pz)
        self.ln_dual_break.setPos(np.log10(r['f0']))
        self.ln_dual_break.setVisible(True)
        what = {'phase': 'fase', 'mag': 'magnitude', 'both': 'fase e magnitude'}[target]
        src = 'pico achado automaticamente' if window is None else 'faixa escolhida'
        parts = [f'<b>{FREQ_MODELS["res"]}</b> (ajuste da {what}, {r["n"]} pontos, '
                 f'{r["window"][0]:.4g}–{r["window"][1]:.4g} Hz, {src}):',
                 f'<b>f0 = {r["f0"]:.4g} ± {r["f0_err"]:.2g} Hz</b>',
                 f'<b>Q = {r["q"]:.3g} ± {r["q_err"]:.2g}</b>',
                 f'largura (f0/Q) = {r["fwhm"]:.3g} ± {r["fwhm_err"]:.2g} Hz',
                 f'ganho do pico sobre o fundo = {r["gain_db"]:.1f} dB (máximo em {r["f_peak"]:.4g} Hz)']
        if target in ('mag', 'both'):
            parts.append(f'resíduo rms da magnitude {100 * r["rms_mag"]:.0f} %')
        if target in ('phase', 'both'):
            parts.append(f'resíduo rms da fase {r["rms_phase"]:.1f}°; atraso τ = {r["tau"] * 1e6:.0f} µs')
        txt = ' &nbsp; '.join(parts)
        if r['n'] < 10:
            txt += ('<br><span style="color:#b35c00;">Poucos pontos no pico: para f0 e Q confiáveis, faça uma varredura '
                    'linear em volta dele (passo ≤ largura/5).</span>')
        if self.dual_cal is not None:
            txt += ('<br><span style="color:#d00000;">⚠ Com a calibração aplicada ("Usar"), a ressonância da célula é '
                    'removida dos dados: desmarque "Usar" para medir a ressonância da célula.</span>')
        self.lbl_dual_model.setText(f'<span style="color:#2e7d32;">{txt}</span>')
        self.dual_model_txt = self._plain(txt.replace(' &nbsp; ', '; ').replace('<br>', ' '))

    def on_dual_cal_panel(self, checked):
        '''Painel "Calibração do microfone" do Modo Duplo; fechado, o fit do padrão não é aplicado.'''
        self.btn_dual_cal_panel.setText('Calibração do microfone ' + ('▾' if checked else '▸'))
        self._show_dual_results()

    def _on_dual_fspace(self, idx, kind='F'):
        '''Logarítmico: número de pontos; Linear: passo em Hz.'''
        log = idx == 0
        spn, lbl = self.dual_fw[kind][3], self.dual_fw[kind][4]
        lbl.setText('N pontos:' if log else 'Passo:')
        spn.setSuffix('' if log else ' Hz')
        spn.setDecimals(0 if log else 2)
