# -*- coding: utf-8 -*-
'''Calibração do microfone por duas amostras e lista de calibrações.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class CalMixin:
    def _cal_freq_range(self):
        '''Faixa da varredura em frequência atual (ou da planejada, se não houver resultados).'''
        if self.dual_kind == 'F' and getattr(self, 'dual_results', None):
            x = np.array([r[0] for r in self.dual_results], dtype=float)
            return float(x.min()), float(x.max())
        return self.sp_dual_f0.value(), self.sp_dual_f1.value()

    def _cal_ref(self):
        '''Referência implícita da célula (para a exibição da varredura com o painel de calibração aberto):
        (chave, dict, n esperado, texto, ok, célula). Câmara: metal opaco, n = 1; OPC: folha fina, n = 1,5.'''
        cell = self.cmb_cell.currentData() or 'Camara'
        key = 'al_opc' if cell == 'OPC' else 'al_cam'
        return key, CAL_REFS[key], CAL_CELL_N.get(cell, 1.0), '', True, cell

    # ---- Calibração por duas amostras
    CAL_SHORT = {'al': 'Al', 'inox': 'Inox', 'ti': 'Ti', 'ni': 'Ni', 'latao': 'Latao', 'grafite': 'Grafite',
                 'al12': 'Al12um', 'al25': 'Al25um', 'cu35': 'Cu35um'}

    def _cal_L(self, slot):
        '''Espessura da amostra do slot, em metros (mm na câmara, µm no OPC).'''
        cell = self.cmb_cell.currentData() or 'Camara'
        return self.sp_cal_s_L[slot].value() * (1e-6 if cell == 'OPC' else 1e-3)

    def _on_cal_cell(self):
        '''Troca de célula: lista os materiais dela em A (e B), muda a unidade da espessura e descarta as
        varreduras guardadas de outra célula.'''
        if not hasattr(self, 'cmb_cal_a'):
            return
        cell = self.cmb_cell.currentData() or 'Camara'
        keys = cal_materials(cell)
        cmb = self.cmb_cal_a
        cur = cmb.currentData()
        cmb.blockSignals(True)
        cmb.clear()
        for k in keys:
            cmb.addItem(CAL_MATERIALS[k]['name'], k)
            cmb.setItemData(cmb.count() - 1, CAL_MATERIALS[k]['tips'], QtCore.Qt.ItemDataRole.ToolTipRole)
        cmb.setCurrentIndex(keys.index(cur) if cur in keys else 0)
        cmb.blockSignals(False)
        for slot in ('A', 'B'):
            sp = self.sp_cal_s_L[slot]
            sp.blockSignals(True)
            sp.setSuffix(' µm' if cell == 'OPC' else ' mm')
            sp.blockSignals(False)
            d = self.cal_slots.get(slot)
            if d is not None and d['cell'] != cell:
                self.cal_slots[slot] = None
        self.cal_last_key = {}
        self._on_cal_samples(fill_b=True)

    def _on_cal_samples(self, fill=True, fill_b=False):
        '''Atualiza a lista colorida da amostra B (verde = par indicado com A, vermelho = não), as espessuras
        típicas, o esquema, as dicas e os avisos; habilita "Gerar calibração".'''
        if not hasattr(self, 'cmb_cal_b') or not hasattr(self, 'cal_schematic'):
            return
        cell = self.cmb_cell.currentData() or 'Camara'
        a = self.cmb_cal_a.currentData()
        if a is None:
            return
        if fill_b:
            cmb = self.cmb_cal_b
            cur = cmb.currentData()
            keys = cal_materials(cell)
            cmb.blockSignals(True)
            cmb.clear()
            first_ok = None
            for k in keys:
                ok, why = cal_pair_check(a, k)
                cmb.addItem(('✓ ' if ok else '✗ ') + CAL_MATERIALS[k]['name'], k)
                i = cmb.count() - 1
                cmb.setItemData(i, QtGui.QBrush(QtGui.QColor('#2e7d32' if ok else '#c62828')),
                                QtCore.Qt.ItemDataRole.ForegroundRole)
                cmb.setItemData(i, f'{"Indicado" if ok else "Não indicado"}: {why}.\n{CAL_MATERIALS[k]["tips"]}',
                                QtCore.Qt.ItemDataRole.ToolTipRole)
                if ok and first_ok is None:
                    first_ok = i
            if cur in keys and cur != a:
                cmb.setCurrentIndex(keys.index(cur))
            else:
                cmb.setCurrentIndex(first_ok if first_ok is not None else 0)
            cmb.blockSignals(False)
        b = self.cmb_cal_b.currentData()
        last = getattr(self, 'cal_last_key', {})
        for slot, k in (('A', a), ('B', b)):        # material novo: espessura típica dele
            if k is not None and last.get(slot) != k:
                sp = self.sp_cal_s_L[slot]
                sp.blockSignals(True)
                sp.setValue(CAL_MATERIALS[k]['L'] * (1e6 if cell == 'OPC' else 1e3))
                sp.blockSignals(False)
        self.cal_last_key = {'A': a, 'B': b}
        ok, why = cal_pair_check(a, b) if b is not None else (False, 'escolha a amostra B')
        self.cmb_cal_b.setStyleSheet(f'QComboBox {{ color: {"#2e7d32" if ok else "#c62828"}; }}')
        self.cal_schematic.set_setup(cell, 'al')
        tips = [f'<b>{CAL_MATERIALS[k]["name"]}:</b> {CAL_MATERIALS[k]["tips"]}' for k in (a, b) if k is not None]
        self.lbl_cal_tips.setText('<br>'.join(tips))
        n = CAL_CELL_N.get(cell, 1.0)
        fmin, fmax = self._cal_freq_range()
        warns = [w for w in (cal_thickness_check(k, self._cal_L(s), fmin, fmax)
                             for s, k in (('A', a), ('B', b)) if k is not None) if w]
        pair = (f'<span style="color:#2e7d32;">✓ par indicado: {why}</span>' if ok else
                f'<span style="color:#c62828;">✗ par não indicado: {why}</span>')
        info = pair                                   # 2.5.0: sem "Célula" e "Curva esperada" (Marcos, 25/11)
        if warns:
            info += '<br><span style="color:#b35c00;">⚠ ' + '<br>⚠ '.join(warns) + '</span>'
        self.lbl_cal_ref_info.setText(info)
        for slot in ('A', 'B'):
            self.lbl_cal_s_state[slot].setText(self._cal_slot_text(slot))
        busy = self.dual_active or getattr(self, 'sweep_active', False)
        self.btn_cal_make.setEnabled(not busy and all(self.cal_slots.get(s) is not None for s in ('A', 'B')))
        QtCore.QTimer.singleShot(0, self._fit_dual_cal_scroll)     # os textos mudam a altura do quadro

    def _cal_slot_text(self, slot):
        d = self.cal_slots.get(slot)
        if d is None:
            return '—' if self.cal_pending != slot else 'medindo…'
        name = os.path.basename(d['path']) if d['path'] else 'varredura sem arquivo'
        return f'✓ {int(d["arr"]["valid"].sum())} pontos ({name})'

    def _cal_store(self, slot, rows, path, excluded=()):
        '''Guarda uma varredura em frequência como amostra do slot.'''
        tau = self._tau_sensor()
        arr = cal_sweep_arrays(rows, tau, excluded, self.audio_snr_alert)
        if arr['valid'].sum() < 5:
            self.flash(f'Amostra {slot}: menos de 5 pontos com SNR suficiente; a varredura não foi guardada.', 6.0)
            return False
        self.cal_slots[slot] = {'arr': arr, 'path': path or '', 'cell': self.cmb_cell.currentData() or 'Camara',
                                'tau': tau}
        self.lbl_cal_verify.setText('')
        self._on_cal_samples(fill=False)
        return True

    def _cal_take(self, slot):
        '''Guarda como amostra do slot a varredura em frequência que está na tela.'''
        if self.dual_active:
            self.flash('Espere a varredura terminar.')
            return
        if self.dual_kind != 'F' or not getattr(self, 'dual_results', None):
            self.flash(f'Amostra {slot}: não há varredura em frequência na tela (meça com "Medir {slot}" ou use "Abrir…").', 6.0)
            return
        if self._cal_store(slot, self.dual_results, getattr(self, 'dual_last_csv', None), self.dual_excluded):
            self.flash(f'Varredura guardada como amostra {slot} ({self.cmb_cal_s[slot].currentText().lstrip("✓✗ ")}).', 4.0)

    def _cal_open(self, slot):
        '''Usa como amostra do slot uma varredura em frequência salva (mesma célula).'''
        if self.dual_active:
            self.flash('Espere a varredura terminar.')
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f'Varredura da amostra {slot}', MEDIDAS_DIR,
            'Modo Duplo em frequência (*DUPLO_freq_*.csv);;Todos os CSV (*.csv)')
        if not path:
            return
        try:
            kind, rows, _ = load_dual_csv(path)
            with open(path, encoding='utf-8') as fh:
                head = fh.read(4000)
        except (OSError, ValueError, IndexError) as e:
            QtWidgets.QMessageBox.warning(self, 'Abrir varredura', f'Não foi possível abrir {os.path.basename(path)}:\n{e}')
            return
        if kind != 'F':
            QtWidgets.QMessageBox.warning(self, 'Abrir varredura', 'A calibração precisa de uma varredura em frequência.')
            return
        m = re.search(r'#\s*Celula\s*=\s*(\w+)', head)
        cell = self.cmb_cell.currentData() or 'Camara'
        if m and m.group(1) != cell:
            QtWidgets.QMessageBox.warning(
                self, 'Abrir varredura', f'Esta varredura foi feita na célula {CELLS.get(m.group(1), m.group(1))}, e a '
                f'escolhida é {CELLS.get(cell, cell)}. A calibração vale para uma célula só: troque a célula no topo ou '
                'escolha outra varredura.')
            return
        self._cal_store(slot, rows, path)

    def _cal_measure(self, slot):
        '''Roda a varredura em frequência com os parâmetros da calibração e a guarda como amostra do slot. Na
        simulação, o sinal simulado segue o material escolhido (K diferente, mesma resposta do sistema).'''
        if self.dual_active or getattr(self, 'sweep_active', False):
            self.flash('Termine ou cancele a varredura em andamento antes de medir.')
            return
        key = self.cmb_cal_s[slot].currentData()
        if key is None:
            return
        cell = self.cmb_cell.currentData() or 'Camara'
        self.apply_cal_preset()
        self.ed_sample.setText(self.CAL_SHORT.get(key, key))         # nome dos arquivos da varredura
        if self.simulating and not self.link.connected:
            m = CAL_MATERIALS[key]
            self.audio_sim.sample = (m['sim_k'], CAL_CELL_N.get(cell, 1.0), 10.0 * (len(key) % 5) - 20.0)
        self.cal_pending = slot
        self.lbl_cal_s_state[slot].setText('medindo…')
        if not self.btn_dual_pwm_panel.isChecked():
            self.btn_dual_pwm_panel.setChecked(True)     # quadro Varredura: progresso, flutuação e esquema
        if self.ext_mode:
            # Modulação óptica: varredura manual; "Concluir" guarda a varredura como amostra do slot
            self.cal_pending = None
            if not self.btn_dual_pwm_panel.isChecked():
                self.btn_dual_pwm_panel.setChecked(True)
            self.toggle_manual_sweep(slot)
            if self.dual_active:
                self.btn_cal_make.setEnabled(False)
                self.flash(f'Varra o chopper pela faixa da calibração e clique em Concluir (amostra {slot}).', 6.0)
            else:
                self.audio_sim.sample = None
                self.lbl_cal_s_state[slot].setText(self._cal_slot_text(slot))
            return
        self.toggle_dual_sweep('F')
        if not self.dual_active:                    # não começou (aviso cancelado, OPT101 em Valor Médio…)
            self.cal_pending = None
            self.audio_sim.sample = None
            self.lbl_cal_s_state[slot].setText(self._cal_slot_text(slot))
        else:
            self.btn_cal_make.setEnabled(False)

    def _make_two_sample_calibration(self):
        '''Gera a calibração a partir das amostras A e B (make_two_sample_cal), grava CSV + PNG e a seleciona.'''
        A, B = self.cal_slots.get('A'), self.cal_slots.get('B')
        if A is None or B is None:
            return
        cell = self.cmb_cell.currentData() or 'Camara'
        a, b = self.cmb_cal_a.currentData(), self.cmb_cal_b.currentData()
        n = CAL_CELL_N.get(cell, 1.0)
        cal = make_two_sample_cal(A['arr'], B['arr'], n, self.sp_dual_flat_tol.value())
        if cal is None:
            self.lbl_cal_verify.setText('<span style="color:#d00000;">Menos de 5 pontos válidos em comum entre A e B: '
                                        'as duas varreduras cobrem a mesma faixa de frequências?</span>')
            return
        notes = []
        pair_ok, why = cal_pair_check(a, b)
        if not pair_ok:
            notes.append(f'Aviso: par não indicado ({why})')
        f = cal['f']
        for s, k in (('A', a), ('B', b)):
            w = cal_thickness_check(k, self._cal_L(s), float(f.min()), float(f.max()))
            notes.append(f'Espessura {s} = {self._cal_L(s) * (1e6 if cell == "OPC" else 1e3):g} '
                         f'{"µm" if cell == "OPC" else "mm"}' + (f' - aviso: {w}' if w else ''))
        if abs(A['tau'] - B['tau']) > 1e-9:
            notes.append('Aviso: A e B foram processadas com τ do sensor diferentes')
        q = self.dual_params if getattr(self, 'dual_params', None) else {}
        now_dt = datetime.now()
        stem = (f'CAL_{self.CAL_SHORT.get(a, a)}-{self.CAL_SHORT.get(b, b)}_microfone_{cell}_'
                f'{f.min():g}_{f.max():g}Hz_{now_dt.strftime("%Y%m%d_%H%M%S")}')
        os.makedirs(MEDIDAS_DIR, exist_ok=True)
        csv_path = os.path.join(MEDIDAS_DIR, stem + '.csv')
        sweep_txt = f'Varreduras {f.min():g} a {f.max():g} Hz ({f.size} pontos)' + (
            f', PWM {q["pwm"]:g} %; {q.get("mode", "")}' if q.get('pwm') is not None else '')
        try:
            verdict = write_two_sample_cal(csv_path, cal, a, b, cell, A['path'], B['path'], A['tau'], sweep_txt, notes)
        except OSError as e:
            self.lbl_cal_verify.setText(f'Não foi possível gravar a calibração: {e}')
            return
        win = self._two_sample_cal_window(cal, a, b, cell)
        png = os.path.join(MEDIDAS_DIR, stem + '.png')
        try:
            win.grab().save(png)
            self._session_add(csv_path, png)
        except Exception as e:
            print(f'Erro ao salvar o gráfico da calibração: {e}')
            self._session_add(csv_path)
        win.setWindowTitle('Calibração do microfone (duas amostras)')
        win.show()
        self._cal_win = win
        self.refresh_mic_cal(select_latest=True)
        na, nb = CAL_MATERIALS[a]['name'], CAL_MATERIALS[b]['name']
        extra = ''.join(f'<br>{t}' for t in notes if t.startswith('Aviso') or ' - aviso' in t)
        if cal['f0_txt']:
            extra += f'<br>{cal["f0_txt"]}'
        if cal['ok']:
            self.lbl_cal_verify.setText(f'<span style="color:#2e7d32;"><b>✓ Calibração verificada</b> ({na} × {nb}): '
                                        f'{cal["text"]}.</span><span style="color:#b35c00;">{extra}</span>'
                                        f'<br>Salva em {os.path.basename(csv_path)} e selecionada no topo.')
        else:
            self.lbl_cal_verify.setText(f'<span style="color:#d00000;"><b>⚠ Não verificada</b> ({na} × {nb}): '
                                        f'{"; ".join(cal["problems"])}. {cal["text"]}.</span>'
                                        f'<span style="color:#b35c00;">{extra}</span><br>Salva como não verificada em '
                                        f'{os.path.basename(csv_path)}. Causas comuns: {CAL_PROBLEM_CAUSES}.')
        self.flash(f'Calibração salva: {csv_path} ({"verificada" if cal["ok"] else "NÃO verificada"}).', 8.0)
        QtCore.QTimer.singleShot(0, self._fit_dual_cal_scroll)

    def _two_sample_cal_window(self, cal, a, b, cell):
        '''Janela com M(f), a razão A/B (amplitude e fase) e a faixa de concordância.'''
        f, v, ag = cal['f'], cal['valid'], cal['agree']
        band = cal['band']
        na, nb = CAL_MATERIALS[a]['name'], CAL_MATERIALS[b]['name']
        ok_html = ('<span style="color:#2e7d32;">verificada</span>' if cal['ok'] else
                   '<span style="color:#d00000;">não verificada</span>')
        win = pg.GraphicsLayoutWidget()
        win.setBackground('w')
        win.resize(900, 820)
        pa_ = win.addPlot(row=0, col=0, title=f'Sensibilidade relativa M = √(S<sub>A</sub>·S<sub>B</sub>)·f<sup>{cal["n"]:g}</sup>'
                                              f' — {na} × {nb}, célula {CELLS.get(cell, cell)} &nbsp; {ok_html}<br>'
                                              f'<span style="color:#2e7d32;">{cal["flat_txt"]}</span>')
        pa_.setLogMode(x=True, y=True)
        pa_.showGrid(x=True, y=True, alpha=0.3)
        pa_.setLabel('left', 'M(f) relativa')
        pa_.plot(f[v], cal['sens'][v], pen=pg.mkPen('#1f4e9c', width=1.5), symbol='o', symbolSize=6,
                 symbolBrush='#1f4e9c', symbolPen='#1f4e9c')
        pb_ = win.addPlot(row=1, col=0, title=f'Razão |S<sub>A</sub>/S<sub>B</sub>| (deve ser constante): '
                                              f'{band["f_lo"]:.4g}–{band["f_hi"]:.4g} Hz')
        pb_.setLogMode(x=True, y=True)
        pb_.showGrid(x=True, y=True, alpha=0.3)
        pb_.setLabel('left', '|A/B|')
        pb_.plot(f[v], cal['ratio_s'][v], pen=pg.mkPen('#b35c00', width=1.5), symbol='o', symbolSize=6,
                 symbolBrush='#b35c00', symbolPen='#b35c00')
        pb_.addLine(y=np.log10(cal['ratio']), pen=pg.mkPen('k', width=1, style=QtCore.Qt.PenStyle.DashLine))
        lr = np.log10(cal['ratio_s'][v])                # pelo menos ±3 dB em torno da razão: escala legível
        span = max(0.15, float(np.max(np.abs(lr - np.log10(cal['ratio'])))) * 1.1)
        pb_.setYRange(np.log10(cal['ratio']) - span, np.log10(cal['ratio']) + span, padding=0)
        pc_ = win.addPlot(row=2, col=0, title='Fase da razão A/B e fase do sistema (Δφ − φ0)')
        pc_.setLogMode(x=True, y=False)
        pc_.showGrid(x=True, y=True, alpha=0.3)
        pc_.setLabel('left', 'graus')
        pc_.setLabel('bottom', 'Frequência (Hz)')
        pc_.plot(f[v], wrap_deg(cal['ratio_p'][v] - band['phi0']), pen=pg.mkPen('#b35c00', width=1.5),
                 symbol='o', symbolSize=6, symbolBrush='#b35c00', symbolPen='#b35c00', name='A/B − constante')
        pc_.plot(f[v], cal['phase'][v], pen=pg.mkPen('firebrick', width=1.5), symbol='s', symbolSize=5,
                 symbolBrush='firebrick', symbolPen='firebrick', name='sistema')
        for plt in (pb_, pc_):
            plt.setXLink(pa_)
        if ag.any():
            for plt in (pa_, pb_, pc_):
                reg = pg.LinearRegionItem((np.log10(band['f_lo']), np.log10(band['f_hi'])), movable=False,
                                          brush=pg.mkBrush(46, 125, 50, 35), pen=pg.mkPen(46, 125, 50, 120))
                reg.setZValue(-10)
                plt.addItem(reg)
        return win

    def apply_cal_preset(self):
        '''Carrega na varredura em frequência do Modo Duplo os parâmetros recomendados para a calibração.'''
        if self.dual_active or self.sweep_active:
            self.flash('Termine ou cancele a varredura em andamento antes de carregar os parâmetros.')
            return
        self.cmb_dual_fspace.setCurrentIndex(0)          # logarítmico (antes do N: muda o sentido do campo)
        self.sp_dual_f0.setValue(CAL_SWEEP_F0)
        self.sp_dual_f1.setValue(CAL_SWEEP_F1)
        self.sp_dual_fn.setValue(CAL_SWEEP_N)
        self.cmb_dual_mode_f.setCurrentIndex(1)          # integração longa (antes do τ: libera o campo)
        self.sp_dual_tau_f.setValue(ADAPT_TAU0_DEF if self.chk_dual_adapt.isChecked() else CAL_SWEEP_TAU)
        # Notch ligado em só um dos lock-ins deslocaria a fase de um deles e contaminaria Δφ
        self.chk_mains.setChecked(False)
        self.chk_audio_mains.setChecked(False)
        self.chk_mic_cal.setChecked(False)               # a calibração é gerada com os dados brutos
        self.sp_power.setValue(CAL_SWEEP_PWM)
        self.btn_dual_sweeps_panel.setChecked(True)      # mostra os campos preenchidos
        self.flash(f'Parâmetros de calibração carregados (PWM {CAL_SWEEP_PWM:g} %): '
                   f'confira o pico do OPT101 (% da saturação) antes de rodar a varredura.', 6.0)

    def refresh_mic_cal(self, *_, select_latest=False):
        '''Lista as calibrações da pasta Medidas no seletor da linha superior (mais recente primeiro).
        Mantém a escolha do usuário enquanto o arquivo existir; senão (ou com select_latest), a mais recente.'''
        cmb = self.cmb_mic_cal
        current = cmb.currentData()
        paths = list_mic_calibrations()
        cmb.blockSignals(True)
        cmb.clear()
        for p in paths:
            # Sem as partes comuns a todas (CAL_, microfone_, .csv): cabe na linha superior
            c = load_mic_calibration(p)
            name = os.path.basename(p)[4:-4].replace('microfone_', '')
            name = re.sub(r'(^|_)(OPC|Camara)_', r'\1', name, count=1)    # a célula já vai na etiqueta
            cmb.addItem(f"[{CELLS.get(c['cell'], c['cell'])}] {'⚠ ' if c['verified'] is False else ''}{name}", p)
            cmb.setItemData(cmb.count() - 1, f"{p}\nReferência: {c['ref']}; célula: {CELLS.get(c['cell'], c['cell'])}"
                            + ('; NÃO verificada' if c['verified'] is False else ''), QtCore.Qt.ItemDataRole.ToolTipRole)
        if not paths:
            cmb.addItem('(nenhuma calibração na pasta Medidas)', None)
        cmb.setCurrentIndex(paths.index(current) if current in paths and not select_latest else 0)
        cmb.blockSignals(False)
        cmb.setEnabled(bool(paths))
        self.chk_mic_cal.setEnabled(bool(paths))
        if not paths:
            self.chk_mic_cal.setChecked(False)
            cmb.setToolTip('Nenhuma calibração encontrada (CAL_*microfone_*.csv na pasta Medidas).\n'
                           'Gere uma na aba Modo Duplo, painel Calibração: meça duas amostras (A e B) e '
                           'clique em Gerar calibração.')
        else:
            cmb.setToolTip(f'{cmb.currentData()}\nA lista é relida da pasta Medidas ao abrir.')
        if cmb.currentData() != current:
            self._show_dual_results()

    def _calibration_files(self, path):
        '''CSV da calibração e o PNG de mesmo nome (se existir).'''
        png = path[:-4] + '.png'
        return (path, png) if os.path.isfile(png) else (path,)

    def _make_dual_calibration(self):
        '''Curva de sensibilidade relativa do microfone + célula a partir da varredura da referência escolhida:
        em teoria S ∝ f^-n (folha fina em OPC: n = 1,5; opaca na câmara: n = 1), então M(f) = S(f)·f^n é a
        resposta do sistema. Entram todos os pontos com SNR suficiente (inclusive a ressonância da célula);
        o ajuste e a verificação usam só a "Faixa" (de … até).'''
        d = self.dual_std
        if d is None:
            return
        f, n = d['f'], d['n_exp']
        k = np.argsort(f)
        f, valid = f[k], d['cal_valid'][k]
        # A verificação vem da segunda referência: toda calibração nova nasce "não verificada".
        verified = False
        m = d['s'][k] * f ** n                         # M(f) = S(f)·fⁿ: a resposta do sistema (sem ajuste de modelo)
        res_f0 = cell_resonance_f0(f, d['s'][k])
        m_ref = float(np.median(m[valid])) if valid.any() else float(np.median(m))
        tol = self.sp_dual_flat_tol.value()
        flat = find_flat_band(f, m / m_ref, valid, tol)
        if flat is not None and flat[1] > flat[0]:
            m_ref *= flat[2]                           # com faixa plana: média da faixa plana = 1
            f_lo, f_hi = float(f[flat[0]]), float(f[flat[1]])
            in_flat = (f >= f_lo) & (f <= f_hi)
            flat_txt = f'Faixa plana (±{tol:g} dB): {f_lo:g} a {f_hi:g} Hz'
        else:
            flat = None
            in_flat = np.zeros(f.size, dtype=bool)
            flat_txt = f'Faixa plana (±{tol:g} dB): não encontrada (normalizada pela mediana)'
        sens, sens_e = m / m_ref, m / m_ref * d['s_rel'][k]
        ph = d['dphi'][k]
        ref_ph = in_flat & valid if (in_flat & valid).any() else valid
        phi0 = float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(ph[ref_ph])))))) if ref_ph.any() else 0.0
        ph = ph - phi0
        ph -= 360.0 * np.round(np.median(ph[ref_ph] if ref_ph.any() else ph) / 360.0)
        ph_e = d['dphi_e'][k]

        q = self.dual_params
        now_dt = datetime.now()
        # Calibração: CAL vem antes do nome da amostra (CAL_<amostra>_microfone_...)
        stem = 'CAL_' + self._stem(f"microfone_{d['cell']}_{f.min():g}_{f.max():g}Hz_{now_dt.strftime('%Y%m%d_%H%M%S')}")
        n_txt = f'{n:g}'.replace('.', ',')
        os.makedirs(MEDIDAS_DIR, exist_ok=True)
        csv_path = os.path.join(MEDIDAS_DIR, stem + '.csv')

        win = pg.GraphicsLayoutWidget()
        win.setBackground('w')
        win.resize(900, 650)
        ver_html = '<span style="color:#b35c00;">não verificada</span>'
        pa_ = win.addPlot(row=0, col=0, title=f'Sensibilidade relativa do microfone + célula (M = S·f<sup>{n_txt}</sup>)'
                                              f' — {d["ref"]["name"]}, célula {CELLS.get(d["cell"], d["cell"])}<br>'
                                              f'<span style="color:#2e7d32;">{flat_txt}</span> &nbsp; {ver_html}')
        pa_.setLogMode(x=True, y=True)
        pa_.showGrid(x=True, y=True, alpha=0.3)
        pa_.setLabel('left', 'M(f) relativa')
        pa_.setLabel('bottom', 'Frequência (Hz)')
        pa_.plot(f[valid], sens[valid], pen=pg.mkPen('#1f4e9c', width=1.5), symbol='o', symbolSize=6,
                 symbolBrush='#1f4e9c', symbolPen='#1f4e9c')
        if (~valid).any():
            pa_.plot(f[~valid], sens[~valid], pen=None, symbol='x', symbolSize=9,
                     symbolBrush='#d00000', symbolPen=pg.mkPen('#d00000', width=2))
        pb_ = win.addPlot(row=1, col=0, title='Fase do sistema (Δφ − φ0)')
        pb_.setLogMode(x=True, y=False)
        pb_.showGrid(x=True, y=True, alpha=0.3)
        pb_.setLabel('left', 'graus')
        pb_.setLabel('bottom', 'Frequência (Hz)')
        pb_.plot(f, ph, pen=pg.mkPen('firebrick', width=1.5), symbol='s', symbolSize=6,
                 symbolBrush='firebrick', symbolPen='firebrick')
        pb_.setXLink(pa_)
        if flat is not None:
            for plt in (pa_, pb_):
                reg = pg.LinearRegionItem((np.log10(f_lo), np.log10(f_hi)), movable=False,
                                          brush=pg.mkBrush(46, 125, 50, 40), pen=pg.mkPen(46, 125, 50, 120))
                reg.setZValue(-10)
                plt.addItem(reg)
            for y in (10 ** (-tol / 20.0), 10 ** (tol / 20.0)):
                pa_.addLine(y=np.log10(y), pen=pg.mkPen((46, 125, 50), width=1, style=QtCore.Qt.PenStyle.DotLine))
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
                fh.write(f"# Calibração relativa do microfone + célula - {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                         f"# Padrão: {d['ref']['name']}, S teórico ∝ f^-{n:g}; M(f) = S(f)*f^{n:g}, normalizada pela média da faixa plana (ou pela mediana, se não houver)\n"
                         f"# Referencia = {d['ref']['name']}\n# Referencia_ID = {d['key']}\n# Celula = {d['cell']}\n"
                         f"# Expoente_teorico = {n:g}\n"
                         + (f"# L_um = {d['L_um']:g}\n# alpha_cm2_s = {d['alpha']:g}\n" if 'L' in CAL_REFS.get(d['key'], {}).get('params', ()) else '')
                         + (f"# Ressonancia_f0_Hz = {res_f0:.1f}\n" if res_f0 is not None else '')
                         + f"# Verificada = {'sim' if verified else 'nao'}\n"
                         + f"# Varredura {f.min():g} a {f.max():g} Hz ({f.size} pontos), PWM {q['pwm']:g} %; {q['mode']}\n"
                         f"# Fase_Sistema = Δφ(INMP441 - OPT101) - φ0 (φ0 = fase média na faixa plana); Valido = 0 para SNR baixo ou ponto excluído com clique; Sensibilidade_Fit = Sensibilidade_Rel e No_Ajuste = Faixa_Plana (colunas mantidas pelo formato)\n"
                         f"# {flat_txt}\n")
                if self.dual_excluded:
                    fh.write('# Pontos excluídos do ajuste com clique (Valido = 0): '
                             + ', '.join(f'{self.dual_results[i][0]:g}' for i in sorted(self.dual_excluded)) + ' Hz\n')
                for txt in (self.dual_opt_tau['text'] if self.dual_opt_tau else None,
                            getattr(self, 'dual_sensor_fit_txt', None)):
                    if txt:
                        fh.write(f"# {self._plain(txt)}\n")
                # Lido por load_mic_calibration: τ do sensor descontado do OPT101 (0 = sem correção). A chave
                # também marca a calibração como feita com o marcador de modulação corrigido no firmware.
                fh.write(f"# OPT101_tau_sensor_s = {self.dual_tau_sensor:.6g}\n")
                if self.dual_fit:
                    fh.write(f'# {self.dual_fit}\n')
                fh.write('Frequencia_Hz,Sensibilidade_Rel,Sensibilidade_Rel_DP,Sensibilidade_Fit,Fase_Sistema_Graus,'
                         'Fase_DP,Valido,Faixa_Plana,No_Ajuste\n')
                for i in range(f.size):
                    fh.write(f'{f[i]:.3f},{sens[i]:.6g},{sens_e[i]:.4g},{sens[i]:.6g},{ph[i]:.3f},{ph_e[i]:.3f},'
                             f'{int(valid[i])},{int(in_flat[i])},{int(in_flat[i])}\n')
            win.grab().save(os.path.join(MEDIDAS_DIR, stem + '.png'))
            self._session_add(csv_path, os.path.join(MEDIDAS_DIR, stem + '.png'))
            self.flash(f'Calibração do microfone salva: {csv_path}. Confira com uma segunda referência ("Verificar com esta medida").', 8.0)
            self.refresh_mic_cal(select_latest=True)        # a nova passa a ser a selecionada
            self.lbl_dual_status.setText(f'Calibração salva: {csv_path} — {flat_txt}')
        except Exception as e:
            print(f'Erro ao salvar a calibração: {e}')
            return
        win.setWindowTitle('Calibração do microfone')
        win.show()
        self._cal_win = win                                  # mantém a janela viva

    def _verify_calibration(self):
        '''Passo 5: confere a calibração aplicada com a varredura atual de uma segunda referência e grava o
        resultado no arquivo da calibração.'''
        c, d = self.dual_cal, self.dual_corr
        if c is None or d is None:
            return
        key, ref, n_exp, _, _, _ = self._cal_ref()
        f, s, dphi = d
        # Com a calibração aplicada, a segunda referência deve seguir f⁻ⁿ numa faixa larga (≥ 1 década)
        b = find_ref_band(f, s, dphi, n_exp, tol_n=CAL_N_TOL, max_db=CAL_VER_DB, max_deg=CAL_VER_DEG)
        if b is None:
            self.lbl_cal_verify.setText('São necessários pelo menos 5 pontos válidos.')
            return
        dec = float(np.log10(b['f_hi'] / b['f_lo']))
        ok = bool(b['ok'] and dec >= 1.0)
        r = {'ok': ok, 'rms_db': b['rms_db'], 'rms_deg': b['rms_deg'],
             'text': (f'{"segue" if b["ok"] else "não segue"} f−{n_exp:g} de {b["f_lo"]:.4g} a {b["f_hi"]:.4g} Hz '
                      f'({dec:.1f} década(s); mínimo 1): n = {b["n"]:.2f} ± {b["n_err"]:.2f}, '
                      f'{b["rms_db"]:.1f} dB rms, fase ± {b["rms_deg"]:.0f}° rms')}
        same = key == c.get('ref_id')
        name = os.path.basename(getattr(self, 'dual_last_csv', None) or '') or 'varredura atual'
        if same:
            # mesma referência: só testa a repetibilidade da montagem, não separa sistema de amostra
            self.lbl_cal_verify.setText(
                f'<span style="color:#b35c00;">Mesma referência da calibração ({ref["name"]}): isso mede só a '
                f'repetibilidade ({r["rms_db"]:.1f} dB, {r["rms_deg"]:.0f}° rms). Para verificar, use outra '
                'referência.</span>')
            return
        txt = f'{ref["name"]} ({name}): {self._plain(r["text"])}'
        try:
            mark_calibration_verified(c['path'], r['ok'], ('aprovada - ' if r['ok'] else 'reprovada - ') + txt)
        except OSError as e:
            self.lbl_cal_verify.setText(f'Não foi possível gravar o resultado na calibração: {e}')
            return
        if r['ok']:
            self.lbl_cal_verify.setText(f'<span style="color:#2e7d32;"><b>✓ Calibração verificada</b> com '
                                        f'{ref["name"]}: {r["text"]}.</span>')
        else:
            self.lbl_cal_verify.setText(f'<span style="color:#d00000;"><b>⚠ Não passou</b> com {ref["name"]}: '
                                        f'{r["text"]}. As duas referências discordam: uma delas não é ideal '
                                        'nesta faixa ou a montagem mudou (altura, vedação, posição do feixe). Refaça '
                                        'a medida ou use uma terceira referência para decidir qual vale.</span>')
        path = c['path']
        self.refresh_mic_cal()
        i = self.cmb_mic_cal.findData(path)
        if i >= 0:
            self.cmb_mic_cal.setCurrentIndex(i)
        self._show_dual_results()
