# -*- coding: utf-8 -*-
'''Abas OPT101 e INMP441: varreduras no padrão do Modo Duplo (Sinal x f, Sinal x PWM e Sinal x t), cada uma só com o
seu sensor (target 'OPT' ou 'AUDIO'; os campos de cada aba ficam em self.sw_w[target]).

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto. O laço de pontos continua
em soi_win_opt.py (toggle_sweep / sweep_step); aqui ficam a lista de pontos, os tempos, o τ adaptativo, as
repetições com mediana, o Sinal x t e a gravação dos CSV. Nas Medidas em Série (series_active) as varreduras do
OPT101 seguem o comportamento antigo (passo linear, τ automático da frequência): sweep_legacy.'''
import types

from soi_comum import *  # noqa: F401,F403


class OptSweepMixin:
    # ------------------------------------------------------------ Campos
    def _w(self, target=None):
        '''Campos das varreduras de uma aba: self.sw_w['OPT'] (OPT101) ou self.sw_w['AUDIO'] (INMP441).'''
        return self.sw_w[target or getattr(self, 'sweep_target', 'OPT')]

    def _build_sw_boxes(self, target, panel_layout):
        '''Quadros Sinal x f (Hz), Sinal x PWM (%) e Sinal x t (s) da aba OPT101 ('OPT') ou INMP441 ('AUDIO').'''
        aud = target == 'AUDIO'
        who = 'INMP441' if aud else 'OPT101'
        p = 'aud' if aud else 'opt'
        btns = self.btn_sweeps_aud if aud else self.btn_sweeps
        etas = self.eta_labels_aud if aud else self.eta_labels
        spins = self.sweep_spins_aud if aud else self.sweep_spins
        W = types.SimpleNamespace(target=target)
        if not hasattr(self, 'sw_w'):
            self.sw_w = {}
        self.sw_w[target] = W

        def build_box(kind, title, fields, **kw):
            box, btn, lbl, bar = self._make_sweep_box(
                title, fields,
                (lambda _=False, t=target: self.toggle_opt_time(t)) if kind == 'T' else
                (lambda _=False, k=kind, t=target: self.toggle_sweep(k, t)),
                warm_default=OPT_WARMUP_DEF_S, **kw)
            if not aud:
                btn.setToolTip('Requer o Modo Lock-In.')
            for _, sb in tuple(fields) + tuple(kw.get('extra', ())):
                if isinstance(sb, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
                    sb.valueChanged.connect(self.update_eta_idle)
            btns[kind], etas[kind] = btn, lbl
            self.sweep_bars[(target, kind)] = bar
            spins[kind] = [sb for _, sb in fields]
            panel_layout.addWidget(box)

        W.f0 = self._dspin(0.1, 5000.0, SWEEP_F0_DEF, 2, 1.0, None, 110, ' Hz')
        W.f1 = self._dspin(0.1, 5000.0, CAL_SWEEP_F1, 2, 10.0, None, 110, ' Hz')
        W.fspace = QtWidgets.QComboBox()
        W.fspace.addItems(['Logarítmico', 'Linear'])
        W.lbl_fn = QtWidgets.QLabel('N pontos:')
        W.fn = self._dspin(2.0, 5000.0, CAL_SWEEP_N, 0, 1.0, None, 90)     # N pontos (log) ou passo em Hz (linear)
        W.fn_last = {0: float(CAL_SWEEP_N), 1: 10.0}
        W.fspace_idx = 0
        W.order = QtWidgets.QComboBox()
        for txt, key in (('Crescente', 'crescente'), ('Decrescente', 'decrescente'), ('Embaralhada', 'embaralhada')):
            W.order.addItem(txt, key)
        W.order.setToolTip(
            'Ordem em que as frequências são medidas. Crescente (padrão). Com deriva lenta (aquecimento), crescente ou\n'
            'decrescente a transformam numa inclinação falsa na curva; embaralhada usa uma nova ordem aleatória a cada\n'
            'repetição, e a deriva vira ruído que a mediana das repetições reduz. A semente fica no cabeçalho do CSV.')
        W.adapt = QtWidgets.QCheckBox('τ adaptativo')
        W.adapt.setChecked(True)
        W.adapt.setToolTip(
            'Ligado (padrão): o campo vira "τ max" (padrão 1 s): a varredura começa nele e o τ muda ao longo dela sem\n'
            'passar desse valor, exceto em baixa frequência: o τ nunca fica abaixo de ~3 períodos (3 s em 1 Hz).\n'
            f'Em cada ponto o SOI mede a flutuação de R do {who} (desvio-padrão e diferença entre a 1ª e a 2ª metade da\n'
            'média). Bem abaixo da Precisão, o τ do ponto seguinte diminui (a flutuação cai com 1/√τ), até ~3 períodos\n'
            '(mínimo 100 ms); acima de 2× a Precisão, o ponto é refeito com τ maior (até o τ max). Cada ponto espera 7τ e\n'
            'faz a média por max(1 s, 3τ).\n'
            'Desligado: o campo volta a ser "τ", fixo na varredura toda; espera 9τ e média por 1τ.')
        W.lbl_tau = QtWidgets.QLabel('τ max:')
        W.tau = TauSpinBox(ADAPT_TAU_CAP, None, width=80)
        W.tol = self._dspin(0.1, 20.0, ADAPT_TOL_DEF, 1, 0.5, None, 80, ' %')
        W.tol.setToolTip(f'Flutuação aceitável de R do {who} em cada ponto (padrão 2 %). Menor = τ maior e\n'
                         'varredura mais lenta.')
        W.reps = QtWidgets.QSpinBox()
        W.reps.setRange(1, 20)
        W.reps.setValue(SWEEP_REPS_DEF)
        W.reps.setSuffix(' ×')
        W.reps.setFixedWidth(60)
        W.reps.setToolTip(
            'Repetições: a varredura é feita N vezes seguidas (laser ligado entre elas; warm-up só antes da 1ª).\n'
            'Cada repetição grava o CSV normal (_rep1, _rep2...) e no fim um CSV _mediana com a mediana ponto a ponto\n'
            'e a incerteza u = 1,25·DP/√N. 1 = uma varredura só.')
        W.avoid = QtWidgets.QLineEdit('')
        W.avoid.setPlaceholderText('ex.: 170,7')
        W.avoid.setFixedWidth(90)
        W.avoid.setToolTip(
            'Frequências de fontes de ruído conhecidas (ex.: ventoinha do laser em ~170 Hz), separadas por ";", que\n'
            'ficam sempre excluídas. Em volta de cada uma, ±2 % da frequência (mínimo ±3 Hz), nenhum ponto é medido: um\n'
            'ponto que cairia nessa faixa vai para 1 Hz além da borda, e fica listado no cabeçalho do CSV. Os múltiplos\n'
            'de 60 Hz também são deslocados (k·60 ± 3 Hz). Vazio = só a rede.')
        build_box('F', 'Sinal x f (Hz)',
                  (('Início:', W.f0), ('Fim:', W.f1), ('Espaçamento:', W.fspace), (W.lbl_fn, W.fn), ('Ordem:', W.order)),
                  extra=(('Faixas excluídas (Hz):', W.avoid),),
                  more=(((W.lbl_tau, W.tau), ('', W.adapt), ('Precisão:', W.tol), ('Repetições:', W.reps)),))
        W.p0 = self._dspin(0.0, 100.0, PWM_SWEEP_START_DEF, 1, 1.0, None, 110, ' %')
        W.p0.setToolTip('Início da varredura em PWM: qualquer valor de 0 a 100 % (padrão 40 %; o laser só emite acima de ~18 %).')
        W.p1 = self._dspin(0.0, 100.0, 100.0, 1, 1.0, None, 110, ' %')
        W.dp = self._dspin(0.1, 100.0, 10.0, 1, 1.0, None, 110, ' %')
        build_box('P', 'Sinal x PWM (%)',
                  (('Início:', W.p0), ('Fim:', W.p1), ('Passo:', W.dp)),
                  warm_pwm=lambda: max(W.p0.value(), W.p1.value()))
        W.t_f = self._dspin(0.5, 5000.0, 10.0, 2, 1.0, None, 100, ' Hz')
        W.t_pwm = self._dspin(0.0, 100.0, 100.0, 1, 5.0, None, 90, ' %')
        W.t_tau = TauSpinBox(1.0, None, width=80)
        W.t_dt = self._dspin(0.5, 600.0, 5.0, 1, 1.0, None, 80, ' s')
        W.t_dur = self._dspin(0.0, 1440.0, 10.0, 1, 1.0, None, 90, ' min')
        W.t_tau.setToolTip(f'τ do lock-in do {who} durante a medida (restaurado no fim). Use τ menor que o intervalo\n'
                           'entre pontos para os pontos serem independentes.')
        W.t_dt.setToolTip('Cada ponto é a média (e o desvio-padrão, nas barras de erro) do lock-in neste intervalo.')
        W.t_dur.setToolTip('Duração da medida; 0 = até clicar em Parar. O CSV e o PNG são gravados no fim.')
        build_box('T', 'Sinal x t (s)',
                  (('Frequência:', W.t_f), ('', self._mains_warn(W.t_f)), ('PWM:', W.t_pwm)),
                  extra=(('τ:', W.t_tau), ('Ponto a cada:', W.t_dt), ('Duração:', W.t_dur)),
                  warm_pwm=lambda: W.t_pwm.value())
        btns['T'].setText('▶ Iniciar')
        btns['T'].setToolTip('O laser começa a modular na frequência e no PWM escolhidos ao clicar em Iniciar. Os\n'
                             'primeiros 7τ (assentamento do lock-in) são descartados; o tempo é contado desde o\n'
                             'início (o aquecimento aparece).' + ('' if aud else ' Requer o Modo Lock-In.'))
        W.fspace.currentIndexChanged.connect(lambda i, t=target: self._on_sw_fspace(t, i))
        W.adapt.toggled.connect(lambda on, t=target: self._on_sw_adapt(t, on))
        for sig in (W.fspace.currentIndexChanged, W.adapt.toggled, W.reps.valueChanged, W.avoid.editingFinished):
            sig.connect(self.update_eta_idle)
        self._on_sw_adapt(target, True)
        return W

    def _on_sw_fspace(self, target, idx):
        '''Logarítmico: número de pontos; Linear: passo em Hz. Cada modo lembra o último valor.'''
        W = self.sw_w[target]
        sp = W.fn
        W.fn_last[W.fspace_idx] = float(sp.value())
        W.fspace_idx = idx
        log = idx == 0
        sp.blockSignals(True)
        W.lbl_fn.setText('N pontos:' if log else 'Passo:')
        sp.setSuffix('' if log else ' Hz')
        sp.setDecimals(0 if log else 2)
        sp.setRange(2.0 if log else 0.01, 5000.0)
        sp.setSingleStep(1.0 if log else 0.5)
        sp.setValue(W.fn_last[idx])
        sp.blockSignals(False)

    def _on_sw_adapt(self, target, on):
        '''τ adaptativo: o campo vira "τ max"; a Precisão só vale com ele ligado.'''
        W = self.sw_w[target]
        who = 'INMP441' if target == 'AUDIO' else 'OPT101'
        W.lbl_tau.setText('τ max:' if on else 'τ:')
        W.tau.setToolTip(
            'τ max da varredura (τ adaptativo ligado): a varredura começa nele e o τ muda conforme a flutuação,\n'
            'sem passar desse valor.' if on else
            f'τ do lock-in do {who} durante a varredura: espera 9τ e faz a média por 1τ em cada ponto.')
        W.tol.setEnabled(bool(on) and not self.sweep_active)

    def _opt_legacy(self):
        '''Comportamento antigo (Medidas em Série): passo linear, τ automático da frequência, sem repetições.'''
        return bool(getattr(self, 'series_active', False))

    @staticmethod
    def _who(target):
        return 'INMP441' if target == 'AUDIO' else 'OPT101'

    def _lock_cut(self, target):
        '''(corte do passa-baixas, taxa) do lock-in do sensor.'''
        return (self.audio_cutoff_lp, AUDIO_FS_REAL) if target == 'AUDIO' else (self.cutoff_lp, RATE.FS)

    def _set_lockin_tau(self, target, tau):
        (self.sp_audio_tau if target == 'AUDIO' else self.sp_tau).setValue(tau)

    def _sweep_data(self, target):
        '''(R, fase, DC) acumulados no ponto em medida, ou None se não há dados.'''
        if target == 'OPT':
            if self.sweep_count <= 0 or not self.sweep_chunks_r:
                return None
            return (np.concatenate(self.sweep_chunks_r), np.concatenate(self.sweep_chunks_p),
                    np.concatenate(self.sweep_chunks_dc))
        with self.audio_lock:
            if self.audio_sweep_count <= 0 or not self.audio_sweep_r:
                return None
            r, p = np.concatenate(self.audio_sweep_r), np.concatenate(self.audio_sweep_p)
        return r, p, np.zeros_like(r)

    def _opt_avoid_extra(self, target=None):
        out = []
        for p in re.split(r'[;\s]+', self._w(target).avoid.text()):
            try:
                v = float(p.strip(',').replace(',', '.'))
            except ValueError:
                continue
            if 0 < v <= 20000:
                out.append(v)
        return out

    def _opt_planned(self, kind, target='OPT', raw=False):
        W = self._w(target)
        if kind == 'P':
            return self._planned_range(W.p0.value(), W.p1.value(), W.dp.value())
        f0, f1 = sorted((W.f0.value(), W.f1.value()))
        if W.fspace.currentIndex() == 0:
            n = max(2, int(round(W.fn.value())))
            vals = [round(float(v), 3) for v in np.geomspace(f0, f1, n)]
        else:
            vals = self._planned_range(f0, f1, W.fn.value())
        if raw:
            return vals
        vals = soi_serie.avoid_mains(vals)[0]
        return soi_serie.avoid_list(vals, self._opt_avoid_extra(target))[0]

    # ------------------------------------------------------------ Tempos e τ
    def _opt_times(self, kind, value, bound=None, target=None):
        '''(espera, medida) do ponto. τ adaptativo: com o τ atual da varredura ('est'), o τ max (padrão) ou o mínimo
        da frequência ('min'). Varredura em PWM: o τ do lock-in, 7τ de espera e média max(1 s, 3τ) (só a amplitude
        muda entre os pontos).'''
        target = target or self.sweep_target
        W = self._w(target)
        if kind == 'P':
            return adapt_times(lp_tau(*self._lock_cut(target)))
        if W.adapt.isChecked():
            tmin = adapt_tau_min(value)
            cur = getattr(self, 'opt_tau_cur', None)
            if bound == 'est' and cur:
                tau = max(tmin, cur)
            elif bound == 'min':
                tau = tmin
            else:
                tau = max(tmin, float(W.tau.value()))
            return adapt_times(tau)
        tau = float(W.tau.value())
        return 9.0 * tau + 0.3, max(0.5, tau)

    def _opt_point_tau(self, value):
        '''τ do ponto numa varredura em frequência em andamento.'''
        W = self._w()
        if W.adapt.isChecked():
            cur = getattr(self, 'opt_tau_cur', None) or float(W.tau.value())
            return max(adapt_tau_min(value), cur)
        return float(W.tau.value())

    def _opt_set_point_tau(self, value):
        '''Depois de apply_frequency (que volta ao τ automático), aplica o τ da varredura ao lock-in do sensor.'''
        self.sweep_tau_now = self._opt_point_tau(value)
        self.opt_redo = 0
        self._set_lockin_tau(self.sweep_target, self.sweep_tau_now)

    def _opt_adapt_point(self, v, now):
        '''Fim da medida de um ponto com τ adaptativo: mede a flutuação de R e da fase; se passa de 2× a
        Precisão, refaz o ponto com τ maior (devolve True). Senão escolhe o τ do ponto seguinte (False).'''
        data = self._sweep_data(self.sweep_target)
        if data is None or len(data[0]) < 4:
            return False
        r, p = data[0], data[1]
        W = self._w()
        tol = W.tol.value() / 100.0
        sm = max(abs(float(r.mean())), 1e-30)
        std_p = float(np.radians(circ_stats_deg(p)[1]))
        q = max(float(r.std()) / sm, std_p) / tol
        h = len(r) // 2
        q_drift = abs(float(r[:h].mean() - r[h:].mean())) / sm / tol
        tau = self.sweep_tau_now
        cap = float(W.tau.value())
        fl = f'flutuação R {100.0 * float(r.std()) / sm:.2g} %, fase {np.degrees(std_p):.2g}°'.replace('.', ',')
        if q > ADAPT_Q_REDO and tau < cap * 0.999 and self.opt_redo < ADAPT_MAX_REDO:
            self.opt_redo += 1
            self.opt_tau_cur = min(cap, tau * min(4.0, max(2.0, (q / ADAPT_Q_TARGET) ** 2)))
            self.sweep_tau_now = self.opt_tau_cur
            self._set_lockin_tau(self.sweep_target, self.sweep_tau_now)
            self.sweep_settle_time, self.sweep_measure_time = adapt_times(self.sweep_tau_now)
            self.sweep_state = 'SETTLING'
            self.sweep_timer = now
            self._clear_sweep_buffers()
            self.sweep_adapt_info = f' | {fl}: refazendo com τ maior'
            return True
        self.opt_q_hist.append((q, tau))
        q_eff = float(np.median([qi * np.sqrt(ti / tau) for qi, ti in self.opt_q_hist[-3:]]))
        k = min(2.0, max(1.0 / 3.0, (q_eff / ADAPT_Q_TARGET) ** 2)) if q_eff > 0 else 1.0 / 3.0
        self.opt_tau_cur = min(cap, tau * k)
        self.sweep_adapt_info = f' | último: τ = {self._fmt_tau(tau)}, {fl}' + (
            f', deriva {q_drift * tol * 100:.2g} %'.replace('.', ',') if q_drift > 1.0 else '')
        return False

    # ------------------------------------------------------------ Início/fim de uma varredura nova
    def _warm_seconds(self, kind, target):
        btn = (self.btn_sweeps_aud if target == 'AUDIO' else self.btn_sweeps)[kind]
        chk_w, sp_w, _p, _e = self.warm_w.get(btn, (None, None, None, None))
        return float(sp_w.value()) if (chk_w is not None and chk_w.isChecked()) else 0.0

    def _opt_begin_run(self, kind, values, _rep, target='OPT'):
        '''Estado de uma varredura nova (F/P, fora das Medidas em Série): ordem, repetições, τ adaptativo.'''
        W = self._w(target)
        order, seed = 'crescente', None
        if kind == 'F':
            order = W.order.currentData()
            n_rep = W.reps.value()
            if not _rep:
                self.opt_rep = ({'n': n_rep, 'k': 1, 'runs': [], 'csvs': [], 'seeds': [], 'order': order,
                                 't0': datetime.now()} if n_rep > 1 else None)
                self.opt_seed0 = int.from_bytes(os.urandom(3), 'big')
                self.opt_warm_s = self._warm_seconds(kind, target)
            rp = getattr(self, 'opt_rep', None)
            if order == 'embaralhada':
                seed = getattr(self, 'opt_seed0', 0) + ((rp['k'] - 1) if rp else 0)
                if rp:
                    rp['seeds'].append(seed)
            if order != 'crescente':
                values = sorted(values)
                values = [values[i] for i in soi_serie.measure_order(values, order, seed)]
        else:
            self.opt_rep = None
            self.opt_warm_s = 0.0
        self.sweep_order = (order, seed)
        self.sweep_ordpos = []
        self.opt_tau_cur = float(W.tau.value()) if kind == 'F' else None
        self.opt_q_hist = []
        self.opt_redo = 0
        self.sweep_adapt_info = ''
        return values

    def _opt_record_point(self, v_curr, r, p, dc):
        tau = (float(getattr(self, 'sweep_tau_now', float('nan'))) if self.sweep_kind == 'F'
               else float(lp_tau(*self._lock_cut(self.sweep_target))))
        row = (v_curr, float(r.mean()), float(r.std()), *circ_stats_deg(p), float(dc.mean()), tau, self.sweep_idx + 1)
        self.sweep_results.append(row)

    def _opt_header(self, kind, rep=None, median=False):
        '''Linhas de cabeçalho do CSV (além das de sempre): espaçamento, ordem, τ, warm-up, repetição, exclusões.'''
        t = self.sweep_target
        W = self._w(t)
        lines = []
        rp_seeds = (rep or {}).get('seeds') if median else None
        if kind == 'F':
            sp = 'Logaritmico' if W.fspace.currentIndex() == 0 else 'Linear'
            lines.append(f'# Espacamento = {sp}')
            order, seed = getattr(self, 'sweep_order', ('crescente', None))
            if rp_seeds:
                seed = ', '.join(str(x) for x in rp_seeds)
            lines.append(f'# Ordem = {order}' + (f' (semente {seed})' if seed is not None else ''))
            if W.adapt.isChecked():
                lines.append(f'# Tau = adaptativo, tau max {W.tau.value():g} s, Precisao {W.tol.value():g} %')
            else:
                lines.append(f'# Tau = {W.tau.value():g} s (fixo)')
            ex = self._opt_avoid_extra(t)
            if ex:
                lines.append('# Faixas excluidas = ' + '; '.join(f'{e:g}' for e in ex) + ' Hz')
            moved = soi_serie.avoid_mains(self._opt_planned('F', t, raw=True))[1]
            if moved:
                lines.append('# Pontos deslocados da rede = ' + '; '.join(f'{a:g}->{b:g}' for a, b in moved) + ' Hz')
        else:
            lines.append(f'# Tau = {1e3 * lp_tau(*self._lock_cut(t)):.4g} ms (lock-in do {self._who(t)})')
        lines.append(f'# Warm-up = {getattr(self, "opt_warm_s", 0.0):g} s')
        if rep:
            lines.append(f"# Repeticao = {rep['k']}/{rep['n']}" if not median else f"# Repeticoes = {rep['n']} (mediana)")
        return lines

    def _opt_finish_new(self):
        '''Fim de uma varredura nova (F/P): CSV, repetições com mediana e janela de resultados.'''
        kind, t = self.sweep_kind, self.sweep_target
        who, W = self._who(t), self._w(t)
        rows = sorted(self.sweep_results, key=lambda r: r[0])
        rp = getattr(self, 'opt_rep', None)
        now_dt = datetime.now()
        now_str = now_dt.strftime('%Y%m%d_%H%M%S')
        f0, f1, df = self.sweep_params['f_start'], self.sweep_params['f_stop'], self.sweep_params['f_step']
        sfx = f"_rep{rp['k']}" if rp else ''
        if kind == 'F':
            stem = self._stem(f'{who}_F_varredura_f{f0:g}_f{f1:g}_{now_str}{sfx}')
            title, col, fmt = f'Varredura em Frequencia - {who}', 'Frequencia_Hz', '{:.3f}'
            params = (f"F_Start={f0} Hz, F_Stop={f1} Hz, "
                      + (f'N={df:g} pontos' if W.fspace.currentIndex() == 0 else f'F_Step={df} Hz'))
        else:
            fm = self.sweep_params.get('freq', self.ref_freq)
            stem = self._stem(f'{who}_P_varredura_p{f0:g}_p{f1:g}_{df:g}_f{fm:g}Hz_{now_str}')
            title, col, fmt = f'Varredura em PWM - {who}', 'PWM_Pct', '{:.2f}'
            params = f'P_Start={f0} %, P_Stop={f1} %, P_Step={df} %, Freq={fm} Hz'
        mode_str = 'Normalizado (R/DC %)' if (self.sweep_params.get('normalize_mode') and t == 'OPT') else 'Bruto (u.a.)'
        os.makedirs(self._save_dir(), exist_ok=True)
        filename = os.path.join(self._save_dir(), stem + '.csv')
        png_filename = os.path.join(self._save_dir(), stem + '.png')
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# {title} - Lock-In TL-Arduino\n# Data/Hora: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"# Parametros: {params}\n# Modo: {mode_str}\n")
                for ln in self._opt_header(kind, rp):
                    f.write(ln + '\n')
                f.write(f'{col},Magnitude_Media,Magnitude_DesvioPadrao,Fase_Media_Graus,Fase_DesvioPadrao_Graus,'
                        'DC_Offset_Medio,Tau_s,Ordem_medida\n')
                for r in rows:
                    f.write(f'{fmt.format(r[0])},{r[1]:.6g},{r[2]:.6g},{r[3]:.3f},{r[4]:.3f},{r[5]:.2f},'
                            f'{r[6]:.4g},{int(r[7])}\n')
            self._session_add(filename)
            self.sweep_last_csv = filename
            print(f'Varredura concluída! Dados em: {filename}')
        except Exception as e:
            print(f'Erro ao salvar arquivo CSV: {e}')
        if rp:
            rp['runs'].append(rows)
            rp['csvs'].append(filename)
            if rp['k'] < rp['n']:
                rp['k'] += 1
                print(f"Repetição {rp['k']} de {rp['n']} da varredura...", flush=True)
                QtCore.QTimer.singleShot(0, lambda: self.toggle_sweep('F', t, _rep=True))
                return
            self.opt_rep = None
            self._opt_finish_median(rp, f0, f1, df, mode_str)
            return
        self.sweep_results = rows
        self.show_sweep_results(kind, f0, f1, df, mode_str, filename, png_filename, who)
        self.flash(f'Varredura concluída: {filename}', 6.0)

    def _opt_finish_median(self, rp, f0, f1, df, mode_str):
        '''Fim das repetições: mediana ponto a ponto (casada pela frequência), incerteza u = 1,25·DP/√N, CSV _mediana.'''
        who = self._who(self.sweep_target)
        by = {}
        for run in rp['runs']:
            for r in run:
                by.setdefault(round(r[0], 6), []).append(r)
        med = []
        for fq in sorted(by):
            g = np.array([x[:6] for x in by[fq]], dtype=float)
            n = len(g)
            ph = np.radians(g[:, 3])
            c = float(np.angle(np.exp(1j * ph).mean()))
            dph = np.degrees((ph - c + np.pi) % (2 * np.pi) - np.pi)
            ph_med = float(np.degrees(c) + np.median(dph))
            r_med = float(np.median(g[:, 1]))
            u_r = 100.0 * 1.25 * float(g[:, 1].std(ddof=1)) / np.sqrt(n) / max(abs(r_med), 1e-30) if n > 1 else float('nan')
            u_p = 1.25 * float(dph.std(ddof=1)) / np.sqrt(n) if n > 1 else float('nan')
            med.append((fq, r_med, float(np.median(g[:, 2])), ((ph_med + 180.0) % 360.0) - 180.0,
                        float(np.median(g[:, 4])), float(np.median(g[:, 5])), u_r, u_p, n))
        now_dt = datetime.now()
        stem = self._stem(f"{who}_F_varredura_f{f0:g}_f{f1:g}_{now_dt.strftime('%Y%m%d_%H%M%S')}_mediana")
        filename = os.path.join(self._save_dir(), stem + '.csv')
        png_filename = os.path.join(self._save_dir(), stem + '.png')
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# Varredura em Frequencia - {who} (mediana de {rp['n']} repeticoes) - Lock-In TL-Arduino\n"
                        f"# Data/Hora: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n# Modo: {mode_str}\n")
                for ln in self._opt_header('F', rp, median=True):
                    f.write(ln + '\n')
                f.write('# Arquivos = ' + '; '.join(os.path.basename(c) for c in rp['csvs'] if c) + '\n')
                f.write('Frequencia_Hz,Magnitude_Media,Magnitude_DesvioPadrao,Fase_Media_Graus,Fase_DesvioPadrao_Graus,'
                        'DC_Offset_Medio,Incerteza_R_Pct,Incerteza_Fase_Graus,N_Repeticoes\n')
                for r in med:
                    f.write(f'{r[0]:.3f},{r[1]:.6g},{r[2]:.6g},{r[3]:.3f},{r[4]:.3f},{r[5]:.2f},{r[6]:.3g},{r[7]:.3g},{r[8]}\n')
            self._session_add(filename)
            self.sweep_last_csv = filename
            print(f'Mediana das repetições gravada em: {filename}')
        except Exception as e:
            print(f'Erro ao salvar arquivo CSV: {e}')
        self.sweep_results = [r[:6] for r in med]
        self.show_sweep_results('F', f0, f1, df, mode_str, filename, png_filename, who)
        self.flash(f'Varredura concluída (mediana de {rp["n"]}): {filename}', 6.0)

    # ------------------------------------------------------------ Sinal x t
    def toggle_opt_time(self, target='OPT'):
        '''Sinal x t: frequência e PWM fixos; cada ponto é a média do lock-in no intervalo escolhido.'''
        W = self._w(target)
        who = self._who(target)
        btns = self.btn_sweeps_aud if target == 'AUDIO' else self.btn_sweeps
        if getattr(self, 'sweep_active', False):
            if self.sweep_kind == 'T' and self.sweep_target == target:
                self._finish_opt_time()
            else:
                self.flash('Termine ou cancele a varredura em andamento antes.')
            return
        if self.average_mode:
            self.flash('O Sinal x t precisa do OPT101 no Modo Lock-In.')
            return
        if self.ext_mode:
            self.flash('Sinal x t usa a modulação eletrônica (o STM32 fixa a frequência).')
            return
        if getattr(self, 'dual_active', False):
            self.flash('A varredura do Modo Duplo está em andamento.')
            return
        if target == 'AUDIO' and not self.chk_audio_lockin.isChecked() and not self.chk_audio_noise.isChecked():
            self.chk_audio_lockin.setChecked(True)      # o lock-in do INMP441 precisa estar rodando
        f, pwm, tau = W.t_f.value(), W.t_pwm.value(), W.t_tau.value()
        self.sweep_restore = self._excitation_snapshot()
        self.sweep_kind, self.sweep_target = 'T', target
        self.sweep_legacy = False
        self.sweep_freqs, self.sweep_idx, self.sweep_results = [0.0], 0, []
        self.sweep_params = {'kind': 'T', 'freq': f, 'pwm': pwm, 'tau': tau, 'dt': W.t_dt.value(),
                             'normalize_mode': self.normalize_mode, 'f_start': 0.0, 'f_stop': 0.0,
                             'f_step': W.t_dt.value(), 'target': target}
        self.opt_warm_s = self._warm_seconds('T', target)
        self._set_spin(self.sp_freq, f)
        self.apply_frequency(f)
        self._set_lockin_tau(target, tau)
        self.sp_power.setValue(pwm)
        self.on_power(self.sp_power.value())
        self.sweep_active = True
        self.sweep_state = 'MEASURING'
        self._clear_sweep_buffers()
        now = time.perf_counter()
        self.ot_t0 = self.ot_timer = now
        self.sweep_settle_time = 7.0 * tau
        for b in list(self.btn_sweeps.values()) + list(self.btn_sweeps_aud.values()):
            b.setEnabled(False)
        btn = btns['T']
        btn.setEnabled(True)
        btn.setText('⏹ Parar')
        btn.setStyleSheet('background:#f8d7da;')
        for w in (self.sp_freq, self.sp_power, self.sp_tau, self.sp_audio_tau, W.t_f, W.t_pwm, W.t_tau, W.t_dt, W.t_dur):
            w.setEnabled(False)
        bar = self.sweep_bars[(target, 'T')]
        bar.setValue(0)
        bar.setVisible(W.t_dur.value() > 0)
        self._set_eta_style(True)
        print(f'Sinal x t ({who}): {f:g} Hz, PWM {pwm:g} %, τ = {tau:g} s, ponto a cada {W.t_dt.value():g} s, '
              + (f'{W.t_dur.value():g} min' if W.t_dur.value() else 'até parar'))

    def _opt_time_step(self, now):
        t = now - self.ot_t0
        tg = self.sweep_target
        W = self._w(tg)
        who = self._who(tg)
        dt = self.sweep_params['dt']
        dur = W.t_dur.value() * 60.0
        n = len(self.sweep_results)
        lbl = (self.eta_labels_aud if tg == 'AUDIO' else self.eta_labels)['T']
        if dur:
            self.sweep_bars[(tg, 'T')].setValue(int(1000 * min(1.0, t / dur)))
            lbl.setText(f'Restante: {self._fmt_time(dur - t)}')
        else:
            lbl.setText(f'Decorrido: {self._fmt_time(t)}')
        fp = f"{self.sweep_params['freq']:g} Hz, PWM {self.sweep_params['pwm']:g} %"
        settle = self.sweep_settle_time
        if t < settle:
            self._clear_sweep_buffers()
            self.ot_timer = now
            self.sweep_status_text = f'Sinal x t {who}: {self._fmt_time(t)} | lock-in assentando ({t:.0f}/{settle:.0f} s), {fp}'
            return
        self.sweep_status_text = (f'Sinal x t {who}: {self._fmt_time(t)}' + (f' de {self._fmt_time(dur)}' if dur else '')
                                  + f' | {fp} | {n} ponto(s)')
        if now - self.ot_timer >= dt:
            data = self._sweep_data(tg)
            if data is not None:
                r, p, dc = data
                tm = 0.5 * (self.ot_timer + now) - self.ot_t0
                self.sweep_results.append((tm, float(r.mean()), float(r.std()), *circ_stats_deg(p), float(dc.mean())))
            self._clear_sweep_buffers()
            self.ot_timer = now
        if dur and t >= dur:
            self._finish_opt_time()

    def _finish_opt_time(self):
        self.finish_and_export_sweep()

    def _opt_export_time(self):
        rows = list(self.sweep_results)
        pr = self.sweep_params
        who = self._who(self.sweep_target)
        now_dt = datetime.now()
        stem = self._stem(f"{who}_T_sinal_t_f{pr['freq']:g}Hz_pwm{pr['pwm']:g}_{now_dt.strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(self._save_dir(), exist_ok=True)
        filename = os.path.join(self._save_dir(), stem + '.csv')
        png_filename = os.path.join(self._save_dir(), stem + '.png')
        mode_str = 'Normalizado (R/DC %)' if (pr.get('normalize_mode') and self.sweep_target == 'OPT') else 'Bruto (u.a.)'
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# Sinal x t - {who} - Lock-In TL-Arduino\n# Data/Hora: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"# Parametros: Freq={pr['freq']} Hz, PWM={pr['pwm']} %, Tau={pr['tau']} s, "
                        f"Ponto_a_cada={pr['dt']} s\n# Modo: {mode_str}\n# Warm-up = {getattr(self, 'opt_warm_s', 0.0):g} s\n")
                f.write('Tempo_s,Magnitude_Media,Magnitude_DesvioPadrao,Fase_Media_Graus,Fase_DesvioPadrao_Graus,DC_Offset_Medio\n')
                for r in rows:
                    f.write(f'{r[0]:.2f},{r[1]:.6g},{r[2]:.6g},{r[3]:.3f},{r[4]:.3f},{r[5]:.2f}\n')
            self._session_add(filename)
            self.sweep_last_csv = filename
            print(f'Sinal x t concluído! Dados em: {filename}')
        except Exception as e:
            print(f'Erro ao salvar arquivo CSV: {e}')
        self.show_sweep_results('T', 0.0, rows[-1][0] if rows else 0.0, pr['dt'], mode_str, filename, png_filename, who)
        self.flash(f'Sinal x t concluído: {filename}', 6.0)
