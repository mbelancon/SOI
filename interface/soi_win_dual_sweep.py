# -*- coding: utf-8 -*-
'''Modo Duplo: varreduras automáticas, τ adaptativo, resultados e exportação.

Métodos da janela principal (LockInWindow em soi_controller.py), separados por assunto.'''
from soi_comum import *  # noqa: F401,F403


class DualSweepMixin:
    def dual_busy(self):
        """Varredura do Modo Duplo em andamento, incluindo o intervalo entre duas repetições."""
        return bool(self.dual_active or getattr(self, 'dual_rep', None))

    def toggle_dual_sweep(self, kind, refine=None, _rep=False):
        if _rep and getattr(self, 'dual_rep', None) is None:
            return                  # repetições canceladas entre uma varredura e a seguinte
        if self.dual_active:
            if kind == self.dual_src:
                self.dual_rep = None
                self._end_dual_sweep()
                self.flash('Varredura do Modo Duplo cancelada pelo usuário.')
            return
        if self.ext_mode:
            self.flash('Modulação óptica: use a varredura manual (o STM32 não muda a frequência do chopper).')
            return
        if self.average_mode:
            self.flash('As varreduras do Modo Duplo precisam do OPT101 no Modo Lock-In.')
            return
        if self.sweep_active:
            self.flash('Já existe uma varredura em andamento.')
            return
        if not refine and not _rep:
            if getattr(self, 'dual_auto_pending', False):
                self.dual_auto_pending = False          # ruídos do warm-up que acabou: valem nesta varredura
            else:
                self.dual_auto_avoid = None
            # ruídos usados nesta varredura (e repetições): última detecção da janela + a do warm-up
            self.dual_noise_used = ([d for d in (getattr(self, 'noise_det_last', None), self.dual_auto_avoid) if d]
                                    if self.chk_dual_warm_noise.isChecked() else [])
            self.dual_noise_lock = True
        values = list(refine[0]) if refine else self._dual_planned(kind)
        if not values:
            return
        prechecked = getattr(self, 'dual_prechecked', None) == kind      # já confirmado antes do warm-up
        self.dual_prechecked = None
        if (kind == 'F' and not _rep and not prechecked and self.btn_dual_sweeps_panel.isChecked()
                and not getattr(self, 'series_active', False) and not self._check_cal_conditions()):
            return
        if not refine and not _rep and not prechecked and not self._confirm_lowf(kind, values):
            return
        if not refine and not _rep:
            n_rep = self.sp_dual_reps.value() if (kind in ('F', 'M') and not self.cal_pending) else 1
            self.dual_rep = ({'n': n_rep, 'k': 1, 'runs': [], 'csvs': [], 'orders': [], 'seeds': [], 'kind': kind,
                              't0': datetime.now()} if n_rep > 1 else None)
            seed0 = getattr(self, 'dual_seed_fixed', None)
            self.dual_seed0 = int(seed0) if seed0 is not None else int.from_bytes(os.urandom(3), 'big')
            self.dual_median = None
            self._dual_draw_reps()
        if not self.chk_audio_lockin.isChecked() and not self.chk_audio_noise.isChecked():
            self.chk_audio_lockin.setChecked(True)     # o lock-in do INMP441 precisa estar rodando
        if kind in ('F', 'M') and not _rep:
            self._beam_on_for_sweep()
        self.dual_restore = self._excitation_snapshot() if kind != 'P' else None
        long_tau = self.dual_mode_w[kind].currentIndex() == 1
        if long_tau:
            self.dual_saved_cutoffs = (self.sp_tau.value(), self.sp_audio_tau.value())   # τ (s)
            self._dual_set_long_tau(kind)
        self.dual_src = kind
        self.dual_kind = 'F' if kind == 'M' else kind     # 'M' é uma varredura em frequência como a 'F'
        order, seed = 'crescente', None
        if kind in ('F', 'M') and not refine and not self.cal_pending:
            order = self._dual_order_key()
            if order == 'embaralhada':
                rp0 = getattr(self, 'dual_rep', None)
                seed = getattr(self, 'dual_seed0', 0) + ((rp0['k'] - 1) if rp0 else 0)
                if rp0:
                    rp0['seeds'].append(seed)
            if order != 'crescente':
                values = sorted(values)
                values = [values[i] for i in soi_serie.measure_order(values, order, seed)]
        self.dual_sorted_insert = order != 'crescente'
        self.dual_values = values
        self.dual_idx = 0
        self.dual_nodata_try = 0
        self.dual_refine = bool(refine)
        self.dual_view_manual = False        # medida nova: volta o ajuste automático dos eixos
        if refine:          # pontos novos entram na varredura atual, que é mantida (com as exclusões)
            q = dict(self.dual_params)
            q['values'] = sorted(set(q.get('values', [r[0] for r in self.dual_results])) | set(values))
            q['refine'] = ((q['refine'] + ' | ') if q.get('refine') else '') + refine[1]
            self.dual_params = q
        else:
            self.dual_results = []
            self.dual_excluded = set()
            self.dual_ref_cfg = []
            self.dual_fit = None
            self.dual_params = {'kind': self.dual_kind, 'values': sorted(values) if self.dual_sorted_insert else values,
                                'freq': self.ref_freq, 'pwm': self.laser_power, 'order': (order, seed),
                                'mode': DUAL_MODE_NAMES[self.dual_mode_w[kind].currentIndex()],
                                'tau': self.dual_tau_w[kind].value() if long_tau else None}
            if kind in ('F', 'M'):
                self.dual_params['mains_fixed'] = self._mains_fixed()
            if kind in ('F', 'M') and self._mains_fixed():
                self.dual_params['mains_moved'] = soi_serie.avoid_mains(self._dual_planned(kind, raw=True))[1]
            if kind in ('F', 'M') and getattr(self, 'dual_noise_used', None):
                self.dual_params['auto_noise'] = [dict(d) for d in self.dual_noise_used]
            if kind in ('F', 'M') and self._dual_avoid_extra():
                raw = self._dual_planned(kind, raw=True)
                if self._mains_fixed():
                    raw = soi_serie.avoid_mains(raw)[0]
                self.dual_params['extra_avoid'] = (self._dual_avoid_extra(),
                                                   soi_serie.avoid_list(raw, self._dual_avoid_extra())[1])
        self.adapt_tau_cur = None
        self.adapt_taus = []                # τ usado em cada ponto gravado
        self.adapt_q_hist = []              # (q, τ) dos pontos gravados: o τ seguinte usa a mediana dos últimos 3
        self.dual_nb = []                   # (q mediano, % descartado, refeitas) do monitor das vizinhas
        if not refine:
            self.dual_pinfo = []            # τ, tempo, refazimentos e flutuação de cada ponto (colunas do CSV)
            self.dual_ordpos = []           # posição em que cada ponto foi medido (coluna Ordem_medida)
            self.dual_ptime = []            # hora do fim de cada ponto (coluna Hora_ponto)
            self.dual_params['t_start'] = datetime.now()
        else:
            self.dual_ordpos, self.dual_ptime = [], []
            if len(getattr(self, 'dual_pinfo', [])) != len(self.dual_results):
                self.dual_pinfo = []
        self.fluct_last = ''
        self.fluct_now = ''
        self.fluct_q = 0.0
        self.lbl_dual_fl.setText('')
        self.lbl_dual_now.setText('')
        self.fluct_next = 0.0
        if self._dual_adaptive(kind):
            # começa no τ max (como antes, com o padrão de 4 s) e nunca passa dele
            self.adapt_tau_max = self.adapt_tau_cur = self._adapt_cap(kind)
            if not refine:
                self.dual_params['adapt'] = (self.sp_dual_adapt_tol.value(), self.adapt_tau_cur)
                self.dual_params['adapt40'] = self.chk_dual_adapt40.isChecked()
                self.dual_params['blocks'] = self._adapt_blocks_max()
        elif not refine:
            self.dual_params.pop('adapt', None)
        self.dual_active = True
        btn = self.dual_btns[kind]
        btn.setText('⏹ Cancelar')
        btn.setStyleSheet('background:#f8d7da;')
        for k, b in self.dual_btns.items():
            if k != kind:
                b.setEnabled(False)
        for w in ((self.sp_freq, self.sp_power, self.sp_tau, self.sp_audio_tau)
                  + tuple(self.dual_mode_w.values()) + tuple(self.dual_tau_w.values())):
            w.setEnabled(False)
        for b in list(self.btn_sweeps.values()) + list(self.btn_sweeps_aud.values()):
            b.setEnabled(False)
        self._apply_adapt_ui()
        self.dual_etas[kind].setStyleSheet('font-weight:bold;font-family:Consolas,monospace;color:#d00000;')
        if not refine:
            self._setup_dual_plots(self.dual_kind)
        self.dual_remaining = sum(sum(self._dual_times(kind, v)) for v in values)
        self.dual_bars[kind].setValue(0)
        self.dual_bars[kind].setVisible(True)
        self._dual_go(values[0], time.perf_counter())

    def _dual_go(self, value, now):
        if self.dual_kind == 'P':
            self._set_spin(self.sp_power, value)
            self.laser_power = value
            self.link.write(f"P{value}\n")
        else:
            self._set_spin(self.sp_freq, value)
            self.apply_frequency(value)        # reinicia a modulação (novo marcador de fase)
            if self.dual_saved_cutoffs is not None:
                self._dual_set_long_tau()      # apply_frequency volta aos cortes automáticos
        self.dual_settle, self.dual_measure = self._dual_times(self.dual_src, value, 'est')
        self.dual_state = 'SETTLING'
        self.dual_timer = now
        self.adapt_info = ''
        self.adapt_redo = 0
        self.adapt_drift_wait = 0
        self.adapt_blocks, self.adapt_block_len = 1, None
        self.nb_redo = 0
        self.point_t0 = now
        self.dual_opt = []
        with self.audio_lock:
            self.dual_aud = []

    def _end_dual_sweep(self):
        self.dual_active = False
        self.dual_noise_lock = False
        self.cal_pending = None
        self.audio_sim.sample = None                # simulação volta ao sinal sem amostra
        self.dual_state = 'IDLE'
        self.btn_dual_resave.setEnabled(bool(self.dual_results))
        if self.dual_saved_cutoffs is not None:
            self.sp_tau.setValue(self.dual_saved_cutoffs[0])
            self.sp_audio_tau.setValue(self.dual_saved_cutoffs[1])
            self.dual_saved_cutoffs = None
        if getattr(self, 'dual_restore', None) is not None:     # varredura em frequência: volta ao início
            self._restore_excitation(self.dual_restore)
            self.dual_restore = None
        for btn in self.dual_btns.values():
            btn.setText('▶ Varredura')
            btn.setStyleSheet('background:#cfe2ff;')
            btn.setEnabled(True)
        for w in (self.sp_freq, self.sp_power, self.sp_tau, self.sp_audio_tau) + tuple(self.dual_mode_w.values()):
            w.setEnabled(True)
        for kind, sp in self.dual_tau_w.items():
            sp.setEnabled(self.dual_mode_w[kind].currentIndex() == 1)
        self._apply_adapt_ui()
        for b in list(self.btn_sweeps.values()) + list(self.btn_sweeps_aud.values()):
            b.setEnabled(True)
        for lbl in self.dual_etas.values():
            lbl.setStyleSheet('font-family:Consolas,monospace;')
        for bar in self.dual_bars.values():
            bar.setVisible(False)
        self.update_dual_eta()
        self.btn_dual_cal.setEnabled(self.dual_std is not None and self.dual_cal is None)
        self._on_cal_samples(fill=False)
        self._apply_mod_ui()
        self._beam_off_after_sweep()

    def dual_step(self, now):
        if self.dual_src == 'X':
            self._manual_step(now)
            return
        if self.dual_src == 'T':
            self._time_step(now)
            return
        elapsed = now - self.dual_timer
        n = len(self.dual_values)
        v = self.dual_values[self.dual_idx]
        rest = sum(sum(self._dual_times(self.dual_src, x, 'est')) for x in self.dual_values[self.dual_idx:]) - elapsed
        self.dual_rest = rest
        self.dual_bars[self.dual_src].setValue(
            int(1000 * min(1.0, max(0.0, 1.0 - rest / max(self.dual_remaining, 1e-6)))))
        self.dual_etas[self.dual_src].setText(f'Restante: {self._fmt_time(rest)}')
        head = f'[{self.dual_idx + 1}/{n}] ' + (f'PWM {v:.1f} %' if self.dual_kind == 'P' else f'{v:g} Hz')
        rp = getattr(self, 'dual_rep', None)
        if rp:
            head = f"Repetição {rp['k']}/{rp['n']} · " + head
        if self.dual_state == 'SETTLING':
            tau_txt = (f' | τ = {self._fmt_tau(self._adapt_tau_at(self.dual_src, v))}'
                       if self._dual_adaptive(self.dual_src) and self.adapt_tau_cur else '')
            self._dual_bar(f'{head}{tau_txt} | estabilizando os lock-ins ({elapsed:.1f}/{self.dual_settle:.1f} s)')
            if elapsed >= self.dual_settle:
                self.dual_state = 'MEASURING'
                self.dual_timer = now
                self.dual_opt = []
                with self.audio_lock:
                    self.dual_aud = []
            return
        adaptive = self._dual_adaptive(self.dual_src)
        tau_txt = (f' | τ = {self._fmt_tau(self._adapt_tau_at(self.dual_src, v))}' if adaptive and
                   self.adapt_tau_cur else '')
        self._dual_bar(f'{head}{tau_txt} | medindo ({elapsed:.1f}/{self.dual_measure:.1f} s)')
        if now >= getattr(self, 'fluct_next', 0.0):
            self.fluct_next = now + 1.0
            self._show_live_fluct(v, head, elapsed)
        if elapsed < self.dual_measure:
            return
        if adaptive and self._adapt_point(v, now):
            return                      # ponto refeito com τ maior
        nb = self._nb_active()
        if nb and not self._nb_filter(v, now):
            return                      # média refeita: muito ruído do ambiente (vizinhas)
        self._show_live_fluct(v, head, elapsed, final=True)
        with self.audio_lock:
            aud = self.dual_aud
            self.dual_aud = []
        if self.dual_opt and aud:
            r_o = np.concatenate([c[0] for c in self.dual_opt])
            p_o = np.concatenate([c[1] for c in self.dual_opt])
            if self.normalize_mode:   # usa o R bruto: a referência é a intensidade, não R/DC
                r_o = r_o * np.maximum(np.concatenate([c[2] for c in self.dual_opt]), 1.0) / 100.0
            r_a = np.concatenate([c[0] for c in aud])
            p_a = np.concatenate([c[1] for c in aud])
            _, fl_s, fl_p = self._adapt_fluct(r_o, p_o, r_a, p_a)
            p_tau = (self.adapt_taus[-1] if adaptive and self.adapt_taus else
                     (self._fixed_tau_at(self.dual_src, v) if self.dual_params.get('tau') else float('nan')))
            fp = self.fluct_parts
            pinfo = (p_tau, now - getattr(self, 'point_t0', now),
                     (self.adapt_redo + getattr(self, 'adapt_drift_wait', 0) + getattr(self, 'adapt_blocks', 1) - 1)
                     if adaptive else 0, fl_s, fl_p,
                     fp['drift_s'], fp['drift_p'], fp['drift_opt'], fp['drift_mic'])
            row = (v, float(r_o.mean()), float(r_o.std()), float(r_a.mean()), float(r_a.std()),
                   *circ_stats_deg(p_a), *circ_stats_deg(p_o))
            cfg = (self.cutoff_hp, self.chk_mains.isChecked())
            if getattr(self, 'dual_refine', False):
                # refino: insere em ordem de frequência e desloca os índices dos pontos excluídos
                xs = [r[0] for r in self.dual_results]
                j = bisect.bisect(xs, v)
                self.dual_results = list(self.dual_results)
                self.dual_results.insert(j, row)
                if len(getattr(self, 'dual_pinfo', [])) == len(xs):
                    self.dual_pinfo.insert(j, pinfo)
                else:
                    self.dual_pinfo = []
                if len(self.dual_ref_cfg) == len(xs):
                    self.dual_ref_cfg.insert(j, cfg)
                else:
                    self.dual_ref_cfg = []
                self.dual_excluded = {i + 1 if i >= j else i for i in self.dual_excluded}
                self.dual_last_i = j
            else:
                # ordem decrescente ou embaralhada: o ponto entra na posição dele em frequência (gráfico e CSV ordenados)
                n0 = len(self.dual_results)
                j = (bisect.bisect([r[0] for r in self.dual_results], v)
                     if getattr(self, 'dual_sorted_insert', False) else n0)
                self.dual_results = list(self.dual_results)
                self.dual_results.insert(j, row)
                if len(self.dual_ref_cfg) == n0:
                    self.dual_ref_cfg.insert(j, cfg)
                if len(getattr(self, 'dual_pinfo', [])) == n0:
                    self.dual_pinfo.insert(j, pinfo)
                if nb and len(getattr(self, 'dual_nb', [])) == n0:
                    self.dual_nb.insert(j, getattr(self, 'nb_point', (float('nan'), float('nan'), 0)))
                if len(getattr(self, 'dual_ordpos', [])) == n0:
                    self.dual_ordpos.insert(j, self.dual_idx + 1)
                    self.dual_ptime.insert(j, datetime.now().strftime('%H:%M:%S'))
                self.dual_excluded = {i + 1 if i >= j else i for i in self.dual_excluded}
                self.dual_last_i = j
            if not getattr(self, 'headless', False):       # sem janela, o run_headless já imprime cada ponto
                s_pt = row[3] / row[1] if row[1] > 0 else float('nan')
                print(f'{head}: S = {s_pt:.4g}, Δφ = {wrap_deg(row[5] - row[7]):.2f}°, '
                      f'τ = {pinfo[0]:g} s, {pinfo[1]:.0f} s, flutuação S {pinfo[3]:.2g} %, Δφ {pinfo[4]:.2g}°',
                      flush=True)
            self._show_dual_results()
        else:
            n_o = sum(len(c[0]) for c in self.dual_opt)
            n_a = sum(len(c[0]) for c in aud)
            tries = getattr(self, 'dual_nodata_try', 0)
            if tries < DUAL_NODATA_RETRIES:
                # sem dados de um dos sensores (USB/serial parada um instante?): mede o ponto de novo
                self.dual_nodata_try = tries + 1
                print(f'Modo Duplo: sem dados em {head} (blocos OPT101 {n_o}, INMP441 {n_a}); '
                      f'medindo de novo ({tries + 1}/{DUAL_NODATA_RETRIES}).', flush=True)
                self.flash(f'Modo Duplo: sem dados em {head}; medindo o ponto de novo.')
                self._dual_go(v, now)
                return
            print(f'Modo Duplo: sem dados em {head} (blocos OPT101 {n_o}, INMP441 {n_a}) depois de '
                  f'{DUAL_NODATA_RETRIES} tentativas; ponto pulado.', flush=True)
            self.flash(f'Modo Duplo: sem dados em {head} (OPT101 e INMP441 conectados?); ponto pulado.')
            self.dual_params.setdefault('skipped', []).append(float(v))
        self.dual_nodata_try = 0
        self.dual_idx += 1
        if self.dual_idx < n:
            self._dual_go(self.dual_values[self.dual_idx], now)
        else:
            slot = self.cal_pending                 # "Medir A/B" da calibração: guarda a varredura no slot
            self._end_dual_sweep()
            self._export_dual()
            if slot:
                self._cal_take(slot)
            rp = getattr(self, 'dual_rep', None)
            if rp and not slot:
                rp['runs'].append(list(self.dual_results))
                rp['csvs'].append(getattr(self, 'dual_last_csv', None))
                rp.setdefault('orders', []).append(list(getattr(self, 'dual_ordpos', [])))
                rp.setdefault('cfgs', []).append(list(self.dual_ref_cfg))
                if rp['k'] < rp['n']:
                    rp['k'] += 1
                    print(f"Repetição {rp['k']} de {rp['n']} da varredura...", flush=True)
                    QtCore.QTimer.singleShot(0, lambda k=rp['kind']: self.toggle_dual_sweep(k, _rep=True))
                else:
                    self.dual_rep = None
                    self._dual_finish_median(rp)

    def _dual_finish_median(self, rp):
        """Fim das repetições: mediana ponto a ponto, incerteza u = 1,25·DP/√N, gráfico e CSV _mediana.
        As repetições são casadas pela frequência (não pela posição na tabela): uma repetição com pontos a menos
        só deixa de contar nesses pontos, que ficam com N menor."""
        keep = [i for i, r in enumerate(rp['runs']) if r]
        runs = [rp['runs'][i] for i in keep]
        if len(runs) < 2:
            return
        key = lambda f: round(float(f), 2)
        x = np.array(sorted({key(row[0]) for r in runs for row in r}))
        col = {f: i for i, f in enumerate(x)}
        m = x.size
        arr = np.full((len(runs), m, 9), np.nan)                                     # (N, pontos, 9)
        for k, r in enumerate(runs):
            for row in r:
                arr[k, col[key(row[0])]] = np.asarray(row[:9], dtype=float)
        arr[:, :, 0] = x
        nrep = arr.shape[0]
        n_pt = np.sum(np.isfinite(arr[:, :, 1]) & np.isfinite(arr[:, :, 3]), axis=0)  # repetições em cada ponto
        ro, ra, pa, po = arr[:, :, 1], arr[:, :, 3], arr[:, :, 5], arr[:, :, 7]
        with np.errstate(divide='ignore', invalid='ignore'):
            S = np.where(ro > 0, ra / np.where(ro > 0, ro, 1.0), np.nan)
        missing = [(rp['runs'].index(r) + 1, m - len({key(row[0]) for row in r})) for r in runs
                   if len({key(row[0]) for row in r}) < m]
        if missing:
            print('Mediana: repetição(ões) incompleta(s) ' + ', '.join(f'{k} (faltam {q})' for k, q in missing)
                  + '; esses pontos usam só as repetições que existem (coluna N_repeticoes).', flush=True)

        def circ_med(a):
            ref = np.degrees(np.angle(np.nanmean(np.exp(1j * np.radians(a)), axis=0)))
            d = wrap_deg(a - ref)
            return wrap_deg(ref + np.nanmedian(d, axis=0)), np.nanstd(d, axis=0, ddof=1)
        with warnings.catch_warnings(), np.errstate(divide='ignore', invalid='ignore'):
            warnings.simplefilter('ignore', RuntimeWarning)        # ponto com 1 repetição: DP = nan
            dphi = wrap_deg(pa - po)
            dphi_med, dphi_sd = circ_med(dphi)
            po_med, po_sd = circ_med(po)
            pa_med = wrap_deg(po_med + dphi_med)
            _, pa_sd = circ_med(pa)
            s_med = np.nanmedian(S, axis=0)
            sq = np.sqrt(np.maximum(n_pt, 1))
            u_s = 100.0 * MEDIAN_EFF * np.nanstd(S, axis=0, ddof=1) / sq / np.where(s_med > 0, s_med, np.nan)
            u_p = MEDIAN_EFF * dphi_sd / sq
            ro_med, ra_med = np.nanmedian(ro, axis=0), np.nanmedian(ra, axis=0)
            ro_sd, ra_sd = np.nanstd(ro, axis=0, ddof=1), np.nanstd(ra, axis=0, ddof=1)
        csv_rows = [(x[i], ro_med[i], ro_sd[i], ra_med[i], ra_sd[i],
                     pa_med[i], pa_sd[i], po_med[i], po_sd[i], s_med[i], int(n_pt[i]), u_s[i], u_p[i])
                    for i in range(m)]
        # No gráfico: S = mediana(S) e barras de erro = u (o R do INMP441 entra como mediana(S)·mediana(R_OPT101))
        self.dual_results = [(x[i], ro_med[i], 0.0, s_med[i] * ro_med[i],
                              s_med[i] * ro_med[i] * np.nan_to_num(u_s[i]) / 100.0,
                              pa_med[i], np.nan_to_num(u_p[i]), po_med[i], 0.0) for i in range(m)]
        # Sem normalização o gráfico usa o R do INMP441 e a incerteza dele (DP entre repetições), não a de S:
        # se o R do OPT101 varia entre repetições (laser instável), u de S fica enorme sem o INMP441 ter variado
        self.dual_raw_u = (self.dual_results, ra_med.copy(), MEDIAN_EFF * ra_sd / sq)
        self.dual_pinfo = []
        self.dual_nb = []
        self.dual_excluded = set()
        cfg = {}
        for r, c in zip(rp['runs'], rp.get('cfgs', [])):
            if r and len(c) == len(r):
                cfg.update({key(row[0]): ci for row, ci in zip(r, c)})
        self.dual_ref_cfg = [cfg[f] for f in x] if all(f in cfg for f in x) else []
        self.dual_params['values'] = [float(v) for v in x]
        self.dual_params['t_start'] = rp.get('t0', self.dual_params.get('t_start'))
        self.dual_params.pop('t_end', None)
        ords = [{key(row[0]): o_i for row, o_i in zip(r, o)}
                for o, r in zip(rp.get('orders', []), rp['runs']) if r and len(o) == len(r)]
        self.dual_median = {'rows': csv_rows, 'n': nrep, 'S': S, 'ra': ra,
                            'csvs': [os.path.basename(c) for c in rp['csvs'] if c],
                            'orders': ([';'.join(str(o.get(f, '-')) for o in ords) for f in x]
                                       if len(ords) == nrep else None),
                            'seeds': [sd for i, sd in enumerate(rp.get('seeds', [])) if i in keep],
                            'missing': missing}
        self._show_dual_results()
        self._export_dual()
        ok = np.isfinite(u_s)
        print(f'Mediana de {nrep} varreduras: u(S) mediana {np.median(u_s[ok]) if ok.any() else float("nan"):.2g} %, '
              f'máx {np.max(u_s[ok]) if ok.any() else float("nan"):.2g} % -> {getattr(self, "dual_last_csv", "")}',
              flush=True)

    def _dual_draw_reps(self, x=None, s=None, ok=None):
        """Repetições esmaecidas, cada uma numa cor da paleta do Marcos, atrás da mediana destacada (gráfico
        principal da varredura em frequência)."""
        if not hasattr(self, 'pw_dual_a'):
            return
        items = getattr(self, 'c_dual_reps', None) or []
        med = getattr(self, 'dual_median', None)
        if med is None or x is None or self.dual_kind != 'F' or med['S'].shape[1] != len(x):
            for it in items:
                it.setData([], [])
            return
        src = med['S'] if self.chk_dual_norm.isChecked() else med['ra']
        with np.errstate(divide='ignore', invalid='ignore'):
            rel = src / np.nanmedian(src, axis=0)          # cada repetição relativa à mediana, na escala do gráfico
            ys = rel * s[None, :]
        n = ys.shape[0]
        while len(items) < n:
            r, g, b = REP_COLORS[len(items) % len(REP_COLORS)]
            it = self.pw_dual_a.plot([], [], pen=pg.mkPen(r, g, b, 70, width=1), symbol='o', symbolSize=5,
                                     symbolBrush=pg.mkBrush(r, g, b, 120), symbolPen=None)
            it.setZValue(-5)
            items.append(it)
        self.c_dual_reps = items
        xa = np.asarray(x, float)
        for i, it in enumerate(items):
            if i >= n:
                it.setData([], [])
                continue
            mk = np.asarray(ok, bool) & np.isfinite(ys[i]) & (ys[i] > 0)
            it.setData(xa[mk], ys[i][mk])

    @staticmethod
    def _fmt_tau(t):
        return (f'{t * 1e3:.0f} ms' if t < 1.0 else f'{t:.2g} s').replace('.', ',')

    def _dual_bar_color(self, color):
        if getattr(self, '_dual_bar_c', None) != color:
            self._dual_bar_c = color
            self.dual_bar.setStyleSheet(
                f'#dualBar {{ background:{color}; border:1px solid gray; border-radius:6px; }}')

    def _dual_bar(self, text):
        '''Barra de status do Modo Duplo durante a varredura: andamento na 1ª linha; flutuação do ponto em medida
        e do último ponto na 2ª; cor pela flutuação (verde dentro da Precisão, amarelo até 2×, vermelho acima).'''
        info = getattr(self, 'adapt_info', '') if 'refazendo' in getattr(self, 'adapt_info', '') else ''
        self.lbl_dual_status.setText(text + info)
        self.lbl_dual_status.setToolTip('')
        tol = self.sp_dual_adapt_tol.value()
        now = getattr(self, 'fluct_now', '')
        self.lbl_dual_now.setText(now + (f' &nbsp;(alvo {tol:g} % / {np.degrees(tol / 100.0):.2g}°)'.replace('.', ',')
                                         if now else ''))
        self.lbl_dual_fl.setText(getattr(self, 'fluct_last', ''))
        q = getattr(self, 'fluct_q', 0.0)
        self._dual_bar_color(OK_COLOR if q <= 1.0 else (WARN_COLOR if q <= ADAPT_Q_REDO else ALERT_COLOR))

    def _show_live_fluct(self, f, head, elapsed, final=False):
        '''Flutuação de S e Δφ do ponto em medida (atualizada a cada 1 s) no quadro Varredura; no fim do ponto
        ela passa para a linha do último ponto.'''
        with self.audio_lock:
            aud = list(self.dual_aud)
        if not (self.dual_opt and aud) or (not final and (elapsed < 1.5 or sum(len(c[0]) for c in aud) < 8)):
            return
        q, s_s, s_p = self._adapt_fluct(np.concatenate([c[0] for c in self.dual_opt]),
                                        np.concatenate([c[1] for c in self.dual_opt]),
                                        np.concatenate([c[0] for c in aud]), np.concatenate([c[1] for c in aud]))
        tol = self.sp_dual_adapt_tol.value()
        color = '#006400' if q <= 1.0 else ('#b05000' if q <= ADAPT_Q_REDO else '#d00000')
        if self._dual_adaptive(self.dual_src) and self.adapt_tau_cur:
            tau = (self.adapt_taus[-1] if final and self.adapt_taus else self._adapt_tau_at(self.dual_src, f))
        else:
            tau = self.sp_audio_tau.value()
        # espaços não separáveis: se faltar largura, quebra só entre S e Δφ, nunca no meio de "Δφ ±1,5°"
        txt = (f"<span style='color:{color};'>S&nbsp;±{s_s:.2g}&nbsp;%,</span> "
               f"<span style='color:{color};white-space:nowrap;'>Δφ&nbsp;±{s_p:.2g}°</span>").replace('.', ',')
        if final:
            fv = head.split('] ')[-1]
            head_nb = f'Último ({fv}, τ = {self._fmt_tau(tau)}):'.replace(' Hz,', '&nbsp;Hz, ').replace(' ', '&nbsp;')
            self.fluct_last = (head_nb.replace('Hz,&nbsp;', 'Hz, ') + '<br>' + txt).replace('.', ',')
            self.fluct_now = ''
        else:
            self.fluct_now = f'Agora ({elapsed:.0f} s): {txt}'
        self.fluct_q = q

    def _adapt_fluct(self, r_o, p_o, r_a, p_a):
        """Flutuação de S = R_INMP441/R_OPT101 e de Δφ durante a medida, em unidades da Precisão:
        q = max(σ_S/tol, σ_Δφ/tol), com σ = desvio-padrão (ou, se maior, a diferença entre as médias da 1ª e da
        2ª metade: deriva). O OPT101 é interpolado nos instantes do INMP441 (as taxas são diferentes), e o que é
        comum aos dois canais (potência do laser) se cancela, como em S e Δφ."""
        tol = self.sp_dual_adapt_tol.value() / 100.0
        r_o, p_o = np.asarray(r_o, float), np.asarray(p_o, float)
        r_a, p_a = np.asarray(r_a, float), np.asarray(p_a, float)
        if len(r_o) < 2 or len(r_a) < 4:
            self.fluct_parts = {'q_rand': 0.0, 'q_drift': 0.0, 'drift_s': float('nan'), 'drift_p': float('nan'),
                                'drift_opt': float('nan'), 'drift_mic': float('nan')}
            return 0.0, 0.0, 0.0
        t_o, t_a = np.linspace(0.0, 1.0, len(r_o)), np.linspace(0.0, 1.0, len(r_a))
        ro_i = np.interp(t_a, t_o, r_o)
        po_u = np.degrees(np.unwrap(np.radians(p_o)))
        dphi = np.radians((p_a - np.interp(t_a, t_o, po_u) + 180.0) % 360.0 - 180.0)
        sr = r_a / np.maximum(np.abs(ro_i), 1e-30)
        c = np.angle(np.exp(1j * dphi).mean())
        dphi = (dphi - c + np.pi) % (2.0 * np.pi) - np.pi
        h = len(sr) // 2
        ho = len(r_o) // 2

        def drift(x):
            return abs(float(x[:h].mean() - x[h:].mean()))

        def fl(x, norm):
            return max(float(x.std()), drift(x)) / norm

        sm = max(abs(float(sr.mean())), 1e-30)
        s_s = fl(sr, sm)
        s_p = fl(dphi, 1.0)
        # partes separadas: aleatória (DP, cai com τ maior) e deriva (2ª metade - 1ª; τ maior não resolve, só esperar).
        # A deriva também em R do OPT101 e do microfone, com sinal: diz se vem da luz ou da amostra/célula
        rel = lambda x, n: 100.0 * float(x[n:].mean() - x[:n].mean()) / max(abs(float(x.mean())), 1e-30)
        self.fluct_parts = {
            'q_rand': max(float(sr.std()) / sm, float(dphi.std())) / tol,
            'q_drift': max(drift(sr) / sm, drift(dphi)) / tol,
            'drift_s': rel(sr, h), 'drift_p': float(np.degrees(dphi[h:].mean() - dphi[:h].mean())),
            'drift_opt': rel(r_o, ho) if ho else 0.0, 'drift_mic': rel(r_a, h)}
        return max(s_s, s_p) / tol, 100.0 * s_s, float(np.degrees(s_p))

    def _adapt_point(self, f, now):
        """Fim da medida de um ponto com τ adaptativo: mede a flutuação; se passa de 2× a Precisão, refaz o ponto
        com τ maior (devolve True). Senão escolhe o τ do ponto seguinte e devolve False (o ponto é gravado)."""
        with self.audio_lock:
            aud = list(self.dual_aud)
        if not (self.dual_opt and aud):
            return False
        r_o = np.concatenate([c[0] for c in self.dual_opt])
        p_o = np.concatenate([c[1] for c in self.dual_opt])
        r_a = np.concatenate([c[0] for c in aud])
        p_a = np.concatenate([c[1] for c in aud])
        q, s_s, s_p = self._adapt_fluct(r_o, p_o, r_a, p_a)
        parts = self.fluct_parts
        fixed = self._lowf_fixed_tau(self.dual_src, f)
        nmax = self._adapt_blocks_max()
        if fixed is not None and getattr(self, 'adapt_blocks', 1) < nmax:
            return self._adapt_more(f, now, f'τ = {self._fmt_tau(fixed)} (faixa < {LOWF_FMAX:g} Hz)')
        if fixed is not None:
            # τ pré-definido da faixa: sem refazer nem adaptar; acima de LOWF_FMAX o adaptativo recomeça de
            # LOWF_TAU_ABOVE, sem o histórico da baixa frequência
            self.adapt_taus.append(fixed)
            self.adapt_q_hist = []
            self.adapt_tau_cur = min(self.adapt_tau_max, LOWF_TAU_ABOVE)
            fl = f'flutuação S {s_s:.2g} %, Δφ {s_p:.2g}°'.replace('.', ',')
            self.adapt_info = (f' | último ponto: τ = {self._fmt_tau(fixed)} (faixa < {LOWF_FMAX:g} Hz)'
                               + self._blocks_txt() + f', {fl}')
            return False
        tau = max(adapt_tau_min(f), self.adapt_tau_cur)
        fl = f'flutuação S {s_s:.2g} %, Δφ {s_p:.2g}°'.replace('.', ',')
        # Deriva lenta (S ou Δφ mudando entre as metades da média mais que a Precisão e mais que o ruído): os
        # lock-ins já assentaram, quem muda é a amostra/célula (aquecimento, pressão). τ maior não ajuda: mede de
        # novo com o mesmo τ, sem nova espera, até a deriva cair (no máximo ADAPT_MAX_DRIFT_WAIT vezes)
        if (parts['q_drift'] > 1.0 and parts['q_drift'] > parts['q_rand']
                and getattr(self, 'adapt_drift_wait', 0) < ADAPT_MAX_DRIFT_WAIT):
            self.adapt_drift_wait = getattr(self, 'adapt_drift_wait', 0) + 1
            self.dual_state = 'MEASURING'
            self.dual_timer = now
            self._blocks_reset()
            self.dual_opt = []
            with self.audio_lock:
                self.dual_aud = []
            dtxt = (f"deriva S {parts['drift_s']:+.2g} % (OPT101 {parts['drift_opt']:+.2g} %, microfone "
                    f"{parts['drift_mic']:+.2g} %), Δφ {parts['drift_p']:+.2g}°").replace('.', ',')
            self.adapt_info = (f' | <span style="color:#b05000;">{dtxt}: refazendo a média com o mesmo τ, esperando '
                               f'estabilizar ({self.adapt_drift_wait}/{ADAPT_MAX_DRIFT_WAIT})</span>')
            print(f'Modo Duplo {f:g} Hz: {dtxt}; média refeita ({self.adapt_drift_wait}/{ADAPT_MAX_DRIFT_WAIT})')
            return True
        q = parts['q_rand']             # o τ segue só a parte aleatória (a deriva não cai com τ)
        nb = getattr(self, 'adapt_blocks', 1)
        if nb > 1:
            q = q / np.sqrt(nb)         # média de nb medidas com o mesmo τ
        # τ já no máximo e flutuação acima da Precisão: com "Permitir médias", mais uma medida com o mesmo τ
        if nb < nmax and q > 1.0 and tau >= self.adapt_tau_max * 0.999:
            return self._adapt_more(f, now, f'τ = {self._fmt_tau(tau)}')
        if nb == 1 and q > ADAPT_Q_REDO and tau < self.adapt_tau_max * 0.999 and self.adapt_redo < ADAPT_MAX_REDO:
            self.adapt_redo += 1
            self.adapt_tau_cur = min(self.adapt_tau_max, tau * min(4.0, max(2.0, (q / ADAPT_Q_TARGET) ** 2)))
            self._dual_set_long_tau()
            self.dual_settle, self.dual_measure = adapt_times(self.adapt_tau_cur)
            self.dual_state = 'SETTLING'
            self.dual_timer = now
            self.dual_opt = []
            with self.audio_lock:
                self.dual_aud = []
            self.adapt_info = (f' | <span style="color:#b05000;">{fl}: refazendo com τ maior</span>')
            return True
        self.adapt_taus.append(tau)
        if nb > 1:
            q = parts['q_rand']         # histórico do τ: flutuação de uma medida, como nos outros pontos
        # próximo ponto: flutuação ∝ 1/√τ -> τ para ficar em 70 % da Precisão. Usa a mediana dos 3 últimos pontos
        # (levados ao τ atual), para um ponto isolado ruim não triplicar o τ dos seguintes; sobe no máximo 2× e
        # desce no máximo 3× por ponto (o ruído cai com a frequência; um ponto muito ruim já é refeito)
        hist = getattr(self, 'adapt_q_hist', [])
        hist.append((q, tau))
        self.adapt_q_hist = hist
        q_eff = float(np.median([qi * np.sqrt(ti / tau) for qi, ti in hist[-3:]]))
        k = min(2.0, max(1.0 / 3.0, (q_eff / ADAPT_Q_TARGET) ** 2)) if q_eff > 0 else 1.0 / 3.0
        self.adapt_tau_cur = min(self.adapt_tau_max, tau * k)
        self.adapt_info = f' | último ponto: τ = {self._fmt_tau(tau)}' + self._blocks_txt() + f', {fl}'
        return False

    def _adapt_blocks_max(self):
        """Número máximo de medidas por ponto. Desde a 2.5.0 sempre 1: "Permitir médias" saiu (Marcos, 25/11); quando
        for preciso, repetem-se varreduras separadas (Repetições)."""
        return 1

    def _blocks_reset(self):
        self.adapt_blocks, self.adapt_block_len = 1, None

    def _blocks_txt(self):
        nb = getattr(self, 'adapt_blocks', 1)
        return f' × {nb} médias' if nb > 1 else ''

    def _adapt_more(self, f, now, tau_txt):
        """"Permitir médias": estende a medida do ponto por mais um bloco com o mesmo τ, sem nova espera e sem
        descartar o que já foi medido (o ponto gravado é a média de todos os blocos)."""
        if self.adapt_block_len is None:
            self.adapt_block_len = self.dual_measure
        self.adapt_blocks += 1
        self.dual_measure += self.adapt_block_len
        self.dual_state = 'MEASURING'
        self.adapt_info = (f' | <span style="color:#1f6fd1;">{tau_txt}: média {self.adapt_blocks}/'
                           f'{self._adapt_blocks_max()}</span>')
        print(f'Modo Duplo {f:g} Hz: média {self.adapt_blocks}/{self._adapt_blocks_max()} com {tau_txt}')
        return True

    def _dual_warn_texts(self, texts):
        """Avisos que ficavam no quadro "Resultados": indicador "⚠ N aviso(s)" na linha de opções do Modo Duplo,
        com o texto completo no tooltip (só as linhas com ⚠; as informativas não aparecem)."""
        lines, info = [], []
        for tx in texts:
            for part in re.split(r'<br\s*/?>', tx or ''):
                t = self._plain(part).strip()
                if '⚠' in part:
                    lines.append(t)
                elif t:
                    info.append(t)
        li = getattr(self, 'lbl_dual_info', None)
        if li is not None:
            li.setVisible(bool(info))
            li.setText('ℹ Resultados (passe o mouse)' if info else '')
            li.setToolTip('\n\n'.join(info))
        lbl = self.lbl_dual_warn
        lbl.setVisible(bool(lines))
        lbl.setText(f'⚠ {len(lines)} aviso(s) da medida (passe o mouse)' if lines else '')
        lbl.setToolTip('\n\n'.join(lines))

    def _set_res_shift(self, why):
        """Mostra/esconde o aviso "Ressonância deslocada" (why = motivo, ou None)."""
        lbl = getattr(self, 'lbl_dual_res_shift', None)
        if lbl is None:
            return
        was = lbl.isVisible()
        lbl.setVisible(why is not None)
        lbl.setText(f'⚠ {RES_SHIFT_MSG}' if why else '')
        lbl.setToolTip(why or '')
        if why and not was:
            self.flash(f'⚠ {RES_SHIFT_MSG}', 6.0)

    def _update_model_nocal(self):
        """Aviso laranja no quadro Ajuste enquanto a calibração não está aplicada."""
        lbl = getattr(self, 'lbl_dual_model_nocal', None)
        if lbl is None:
            return
        off = not self.chk_mic_cal.isChecked()
        lbl.setText(('⚠ Calibração não aplicada ("Usar" desmarcado na linha de cima)' if off else
                     '⚠ Calibração não aplicada (sinal sem normalizar pelo OPT101)')
                    + ': os modelos só fazem sentido com o sinal calibrado. O ajuste é feito assim mesmo, sobre o sinal bruto.')
        lbl.setVisible(off or not self.chk_dual_norm.isChecked())

    def _applied_cal(self):
        """Calibração que a varredura em frequência vai aplicar (Usar marcado e sinal normalizado), ou None."""
        if not (self.chk_mic_cal.isChecked() and self.chk_dual_norm.isChecked()):
            return None
        return load_mic_calibration(self.cmb_mic_cal.currentData())

    def _dual_cal_regions(self, cal):
        """Fundo avermelhado nos gráficos de S e Δφ fora da faixa da calibração aplicada (eixo x em log10)."""
        if not (getattr(self, 'chk_dual_out_red', None) is not None and self.chk_dual_out_red.isChecked()):
            cal = None
        for k, (pw, rg) in enumerate(self.rg_dual_out):
            if cal is None:
                rg.setVisible(False)
                continue
            lo, hi = np.log10(cal['f'][0]), np.log10(cal['f'][-1])
            rg.setRegion((-3.0, lo) if k % 2 == 0 else (hi, 7.0))
            rg.setToolTip(f'Fora da faixa calibrada ({cal["f"][0]:g}–{cal["f"][-1]:g} Hz): a correção usa o valor '
                          'da borda e não foi medida aqui.')
            rg.setVisible(True)

    def _dual_set_xrange(self, x):
        """Eixo x dos gráficos do Modo Duplo na faixa da varredura (planejada + medida), não a partir de 0/1 Hz:
        o ajuste automático fica só no eixo y."""
        kind = self.dual_kind
        vals = [float(v) for v in list(self.dual_params.get('values') or []) + list(x) if np.isfinite(v)]
        if kind == 'F':
            plots = (self.pw_dual_a, self.pw_dual_b, self.pw_dual_c, self.pw_dual_d)
            vals = [v for v in vals if v > 0]
            if not vals:
                return
            lo, hi = np.log10(min(vals)), np.log10(max(vals))
            m = 0.04 * (hi - lo) if hi > lo else 0.05
        elif kind == 'T':
            plots = (self.pw_dual_a, self.pw_dual_b, self.pw_dual_c, self.pw_dual_d)
            dur = self.sp_dt_dur.value() * 60.0 if self.dual_active else 0.0
            lo, hi = 0.0, max(max(vals, default=0.0), dur)
            if hi <= 0:
                return
            m = 0.02 * hi
        else:                                   # PWM: só o gráfico de calibração tem o PWM no eixo x
            plots = (self.pw_dual_b,)
            if not vals:
                return
            lo, hi = min(vals), max(vals)
            m = 0.04 * (hi - lo) if hi > lo else 1.0
        for pw in plots:
            pw.setXRange(lo - m, hi + m, padding=0)
            self._dual_fit_y(pw)

    def _dual_data_items(self, pw):
        """Itens com os pontos medidos de um gráfico do Modo Duplo (base do ajuste dos eixos)."""
        if pw is self.pw_dual_a:
            items = [self.c_dual_a, self.c_dual_a_out, self.c_dual_a_bad]
        elif pw is self.pw_dual_b:
            items = [self.c_dual_b, self.c_dual_b_out]
        else:
            items = list(pw.getPlotItem().listDataItems())
        out = []
        for it in items:
            x, _ = it.getData()
            if it.isVisible() and x is not None and len(x):
                out.append(it)
        return out

    def _dual_fit_y(self, pw, pad=0.06):
        """Eixo y ajustado aos pontos medidos visíveis (curvas teóricas, ajustes e regiões não contam)."""
        items = self._dual_data_items(pw)
        if not items:
            pw.getPlotItem().enableAutoRange(axis='y')
            return
        vb = pw.getPlotItem().vb
        yb = vb.childrenBounds(items=items)[1]
        if yb is None or not np.isfinite(yb).all():
            return
        y0, y1 = yb
        m = pad * (y1 - y0) if y1 > y0 else max(abs(y0) * 0.05, 0.05)
        vb.setYRange(y0 - m, y1 + m, padding=0)

    def _dual_fit_view(self):
        """Duplo clique num gráfico do Modo Duplo: x na faixa da varredura e y nos pontos medidos."""
        self.dual_view_manual = False
        if not getattr(self, 'dual_results', None):
            for pw in (self.pw_dual_a, self.pw_dual_b):
                pw.getPlotItem().enableAutoRange()
            return
        self._dual_set_xrange(self._dual_arrays()[0])
        for pw in (self.pw_dual_a, self.pw_dual_b, self.pw_dual_c, self.pw_dual_d):
            self._dual_fit_y(pw)
        if self.dual_kind == 'P':           # x do gráfico de S × intensidade: R do OPT101 (não o PWM)
            vb = self.pw_dual_a.getPlotItem().vb
            items = self._dual_data_items(self.pw_dual_a)
            xb = vb.childrenBounds(items=items)[0] if items else None
            if xb is not None and np.isfinite(xb).all():
                m = 0.05 * (xb[1] - xb[0]) if xb[1] > xb[0] else 1.0
                vb.setXRange(xb[0] - m, xb[1] + m, padding=0)

    def _dual_refit_after_update(self):
        if getattr(self, 'dual_results', None) and not getattr(self, 'dual_view_manual', False):
            self._dual_set_xrange(self._dual_arrays()[0])

    def _dual_arrays(self):
        res = np.array(self.dual_results, dtype=float).reshape(-1, 9)
        return res.T

    def _show_dual_results(self):
        if not getattr(self, 'dual_results', None):     # o seletor de calibração existe antes da aba
            self._set_res_shift(None)
            if hasattr(self, 'rg_dual_out'):
                self._dual_cal_regions(self._applied_cal() if getattr(self, 'dual_kind', 'F') == 'F' else None)
            return
        if self.txt_dual_empty[0].isVisible():
            for t in self.txt_dual_empty:
                t.setVisible(False)
            self.pw_dual_a.enableAutoRange()      # a faixa neutra desligou o ajuste automático
            self.pw_dual_b.enableAutoRange()
        x, ro, ro_e, ra, ra_e, pa, pa_e, po, po_e = self._dual_arrays()
        if not getattr(self, 'dual_view_manual', False):
            self._dual_set_xrange(x)
            # O y se ajusta aos pontos já desenhados: aqui as curvas ainda têm os dados anteriores (o ponto novo
            # ficava fora da escala, ex.: o de 5 Hz numa varredura que desce abaixo de 40 Hz). Refaz depois que o
            # resto desta função atualizou as curvas.
            QtCore.QTimer.singleShot(0, self._dual_refit_after_update)
        self._update_dual_sensor_plots(x, ro, ra, pa, po)
        self.dual_fit = None
        self.dual_std = None
        self.dual_cal = None        # só a varredura em frequência aplica a calibração (o CSV registra isso)
        self.dual_cal_err = None
        self.btn_dual_cal.setEnabled(False)
        self.dual_corr = None
        self.btn_cal_verify.setEnabled(False)
        keep = np.ones(x.size, dtype=bool)                # pontos não excluídos com clique
        keep[[i for i in self.dual_excluded if i < x.size]] = False
        self.btn_dual_incl.setEnabled(bool(self.dual_excluded))
        self.btn_dual_resave.setEnabled(not self.dual_active)
        excl_txt = self._dual_excluded_text()
        if self.dual_kind == 'T':
            self._show_time_results(x, ro, ro_e, ra, ra_e, pa, pa_e, po, po_e, keep)
            return
        if self.dual_kind == 'P':
            self._fit_dual_model(np.empty(0), np.empty(0), np.empty(0), np.empty(0), np.empty(0))
            if self.btn_dual_model_panel.isChecked() and self.cmb_dual_model.currentData() is not None:
                self.lbl_dual_model.setText('O ajuste com modelos vale só para a varredura em frequência.')
            self._set_dual_points(ro, ra, np.arange(x.size), keep)
            self._set_errbar(self.e_dual_a, x=ro, y=ra, height=2 * ra_e, width=2 * ro_e, beam=0)
            self.c_dual_b.setData(x, ro)
            self._set_errbar(self.e_dual_b, x=x, y=ro, height=2 * ro_e, beam=0)
            for e in (self.e_dual_a_cal, self.e_dual_b_cal):
                self._set_errbar(e, x=np.empty(0), y=np.empty(0))
            self.c_dual_a_fit.setData([], [])
            self.c_dual_b_fit.setData([], [])
            deg = self.cmb_dual_p_deg.currentData() or 0
            tgt = self.cmb_dual_p_target.currentData()
            parts, plain = [], []
            for key, xs_, ys_, curve, name in (('a', ro, ra, self.c_dual_a_fit, 'INMP441 × OPT101'),
                                               ('b', x, ro, self.c_dual_b_fit, 'OPT101 × PWM')):
                if not deg or key not in tgt:
                    continue
                res = poly_fit_text(xs_[keep], ys_[keep], deg)
                if res is None:
                    parts.append(f'<b>{name}:</b> pontos insuficientes para grau {deg}.')
                    continue
                coef, text = res
                xx = np.linspace(0.0, float(np.max(xs_)) * 1.05, 200)
                curve.setData(xx, np.polyval(coef, xx))
                parts.append(f'<span style="color:#b35c00;"><b>{name}:</b> {text}</span>')
                plain.append(f'Fit {name.replace("×", "x")}: {self._plain(text)}')
            self.dual_fit = '; '.join(plain) or None
            self.lbl_dual_p_fit.setText('<br>'.join(parts))
            self.lbl_dual_fit.setText(excl_txt)
            return

        # frequência real: na modulação óptica é a medida no OPT101; na eletrônica, a gerada pelo TIM4
        fa = (np.asarray(x, dtype=float) if getattr(self, 'dual_params', {}).get('mod') == 'optica'
              else np.array([actual_mod_freq(v) for v in x]))
        # Diagnóstico: τ efetivo do canal óptico pela fase do OPT101, descontada a cadeia digital de cada ponto
        self.dual_opt_tau = None
        lines = []
        ext_sweep = getattr(self, 'dual_params', {}).get('mod') == 'optica'
        if ext_sweep:
            # a fase do OPT101 é a própria referência: não diz nada sobre o τ do canal óptico
            lines.append('<span style="color:#606060;">Modulação óptica: a referência é o próprio OPT101 '
                         '(a fase dele fica perto de −90° por construção; S e Δφ valem como na eletrônica).</span>')
        elif len(self.dual_ref_cfg) == x.size and x.size >= 4:
            hp, mains = (np.array(c) for c in zip(*self.dual_ref_cfg))
            self.dual_opt_tau = fit_opt_tau(fa, po, po_e, opt_digital_phase(fa, hp, mains), ro)
        summ, details = opt_channel_summary(fa, ro, self.dual_opt_tau)
        if summ:
            lines.append(summ)
        # Correção pelo polo do sensor (OPT101), na fase e na amplitude da referência óptica
        self.dual_tau_sensor = self._tau_sensor()
        if self.dual_tau_sensor > 0:
            xs = 2.0 * np.pi * fa * self.dual_tau_sensor
            po = po + np.degrees(np.arctan(xs))
            ro, ro_e = ro * np.sqrt(1.0 + xs * xs), ro_e * np.sqrt(1.0 + xs * xs)
            lines.append(f'<span style="color:#606060;">OPT101 corrigido pelo τ do sensor = '
                         f'{self.dual_tau_sensor * 1e6:.3g} µs (Calibração do microfone → Avançado).</span>')
        if getattr(self, 'dual_sensor_fit_txt', None):
            lines.append(self.dual_sensor_fit_txt)
        self.lbl_dual_tau.setText('<br>'.join(lines))
        self.lbl_dual_tau.setToolTip(details)
        ok = (ro > 0) & (ra > 0)
        s = np.where(ok, ra / np.where(ok, ro, 1.0), np.nan)
        s_rel = np.sqrt((ra_e / np.maximum(ra, 1e-30)) ** 2 + (ro_e / np.maximum(ro, 1e-30)) ** 2)
        # Δφ desenrolada ao longo da frequência (sem os saltos falsos de ±360°)
        order = np.argsort(x)
        dphi = np.empty_like(x)
        dphi[order] = np.degrees(np.unwrap(np.radians(wrap_deg(pa - po)[order])))
        dphi_e = np.hypot(pa_e, po_e)
        norm = self.chk_dual_norm.isChecked()
        self._set_dual_f_titles()
        if not norm:
            # Só o INMP441: R e fase brutos (a luz não é descontada); sem calibração nem fit do padrão
            raw = getattr(self, 'dual_raw_u', None)
            if raw is not None and raw[0] is self.dual_results and raw[1].size == ra.size:
                ra = raw[1]                          # mediana das repetições: R do INMP441 e u = 1,25·DP/√N dele
                ra_e = np.nan_to_num(raw[2])
            ok = ra > 0
            s = np.where(ok, ra, np.nan)
            s_rel = ra_e / np.maximum(ra, 1e-30)
            dphi[order] = np.degrees(np.unwrap(np.radians(wrap_deg(pa)[order])))
            dphi_e = np.asarray(pa_e, dtype=float)
        cal_txt = ''
        res_shift = None
        cal_rel = cal_ph_e = None        # incerteza da calibração em cada ponto (relativa em S; graus em Δφ)
        out_cal = np.zeros(x.size, dtype=bool)
        if self.chk_mic_cal.isChecked() and not norm:
            cal_txt = ('<span style="color:#606060;">Calibração não aplicada: ela vale para o sinal normalizado '
                       '(marque "Normalizar pelo OPT101").</span>')
        elif self.chk_mic_cal.isChecked():
            self.dual_cal = load_mic_calibration(self.cmb_mic_cal.currentData())
            if self.dual_cal is None:
                cal_txt = '<b>Calibração INMP441:</b> nenhuma calibração válida selecionada na linha superior.'
            else:
                c = self.dual_cal
                lf, lc = np.log(np.maximum(x, 1e-9)), np.log(c['f'])
                inside = (x >= c['f'][0] * 0.999) & (x <= c['f'][-1] * 1.001)
                s_raw = s.copy()
                s = s / np.exp(np.interp(lf, lc, np.log(c['sens'])))
                dphi = dphi - np.interp(lf, lc, c['phase'])
                if c.get('sens_rel_e') is not None:
                    cal_rel = np.where(inside, np.interp(lf, lc, c['sens_rel_e']), np.nan)
                if c.get('phase_e') is not None:
                    cal_ph_e = np.where(inside, np.interp(lf, lc, c['phase_e']), np.nan)
                out_cal = ok & ~inside
                ok &= inside
                cal_txt = (f'<b>Calibração INMP441:</b> {os.path.basename(c["path"])}'
                           + (f' <span style="color:{DUAL_OUT_CAL_COLOR};">({int(out_cal.sum())} ponto(s) fora da '
                              f'faixa calibrada {c["f"][0]:g}–{c["f"][-1]:g} Hz: '
                              + ('fundo avermelhado, ' if self.chk_dual_out_red.isChecked() else '')
                              + 'pontos vazados, corrigidos pelo valor da borda e fora dos ajustes)</span>'
                              if out_cal.any() else ''))
                if c.get('agree') is not None and c['agree'].any():
                    fa_lo, fa_hi = float(c['f'][c['agree']].min()), float(c['f'][c['agree']].max())
                    out = ok & ((x < fa_lo * 0.999) | (x > fa_hi * 1.001))
                    if out.any():
                        cal_txt += (f'<br><span style="color:#b35c00;">⚠ {int(out.sum())} ponto(s) fora da faixa em que as '
                                    f'duas amostras da calibração concordaram ({fa_lo:.4g}–{fa_hi:.4g} Hz): ali a '
                                    'correção não foi verificada.</span>')
                if c['legacy']:
                    cal_txt += ('<br><span style="color:#d00000;">⚠ Calibração antiga: feita antes do firmware com o '
                                'marcador de modulação corrigido (23/10/2026 14:43) ou com a correção pelo τ efetivo. '
                                'A fase do sistema não é comparável (td ~100 µs maior); gere uma calibração nova.</span>')
                elif (c['opt_tau'] > 0) != (self.dual_tau_sensor > 0):
                    cal_txt += ('<br><span style="color:#d00000;">⚠ A calibração foi gerada '
                                + ('com' if c['opt_tau'] > 0 else 'sem')
                                + ' a correção pelo τ do sensor, e esta varredura está '
                                + ('com' if self.dual_tau_sensor > 0 else 'sem')
                                + ' ela: S e a fase do sistema ficam inconsistentes.</span>')
                # 2.5.0: sem aviso de célula diferente da calibração (só existe a Câmara desde a remoção do modo OPC)
                # Ressonância da célula: muda com o volume livre (altura da amostra). Longe da f0 da calibração,
                # a correção perto do pico não vale
                sh = resonance_shift(x[ok & inside & keep], s_raw[ok & inside & keep], c)
                if sh is not None:
                    res_shift = (f'{sh[0]}. Perto da ressonância a correção não vale. A montagem mudou (amostra de '
                                 'outra altura, célula mal fechada ou vazando)? Refaça a montagem ou gere uma '
                                 'calibração nesta montagem; também dá para ignorar a região da ressonância.')
                    cal_txt += (f'<br><span style="color:#d00000;">⚠ {RES_SHIFT_MSG}: {res_shift}</span>')
                if c['verified'] is False:
                    cal_txt += ('<br><span style="color:#d00000;">⚠ Calibração ainda não verificada experimentalmente: '
                                'confira com uma segunda referência ("Verificar com esta medida", no painel Calibração).</span>')
        self.lbl_dual_cal.setText(cal_txt)
        self._set_res_shift(res_shift)
        self._dual_cal_regions(self.dual_cal)
        red = self.chk_dual_out_red.isChecked()
        self.c_dual_a_out.setSymbolPen(pg.mkPen(DUAL_OUT_CAL_COLOR if red else 'royalblue', width=1.5))
        self.c_dual_b_out.setSymbolPen(pg.mkPen(DUAL_OUT_CAL_COLOR if red else 'firebrick', width=1.5))
        self.c_dual_a_out.setData(x[out_cal], s[out_cal])
        self.c_dual_b_out.setData(x[out_cal], dphi[out_cal])
        snr_ok = ra / np.maximum(ra_e, 1e-30) >= 10.0 ** (self.audio_snr_alert / 20.0)
        vm = ok & keep & snr_ok
        self.dual_corr = (x[vm], s[vm], dphi[vm]) if self.dual_cal is not None else None
        self.btn_cal_verify.setEnabled(self.dual_corr is not None and not self.dual_active)
        self._set_dual_points(x[ok], s[ok], np.flatnonzero(ok), keep[ok])
        self._dual_draw_reps(x, s, ok)
        self.c_dual_b.setData(x[ok] if self.dual_cal else x, dphi[ok] if self.dual_cal else dphi)
        show_ce = self.chk_dual_cal_err.isChecked()
        self._set_dual_f_errors(x, s, s_rel, dphi, dphi_e, ok, cal_rel if show_ce else None,
                                cal_ph_e if show_ce else None)
        self.dual_cal_err = (cal_rel, cal_ph_e) if self.dual_cal is not None else None
        if self.dual_cal is not None and show_ce and (cal_rel is not None or cal_ph_e is not None):
            cal_txt += ('<br><span style="color:#606060;">Barras de erro (±1 DP): <span style="color:#2ca02c;">'
                        '<b>verde</b></span> = calibração, <b>cinza</b> = esta medida.</span>')
            self.lbl_dual_cal.setText(cal_txt)
        self.c_dual_a_fit.setData([], [])
        self.c_dual_b_fit.setData([], [])
        self.c_dual_a_bad.setData([], [])
        self.c_dual_a_theory.setData([], [])
        m = ok & keep                                     # pontos que entram no ajuste
        self._fit_dual_model(x[m], s[m], s_rel[m], dphi[m], dphi_e[m])
        # Calibração (painel aberto): M(f) = S(f)·fⁿ da referência, sem ajuste de modelo; a faixa plana de M é onde
        # o sistema não distorce (lá S segue f⁻ⁿ). Pronta para "Gerar curva de calibração".
        cal_on = self.btn_dual_cal_panel.isChecked()
        if not cal_on:
            self.lbl_dual_fit.setText(excl_txt)
            return
        if not norm:
            self.lbl_dual_fit.setText('Calibração: marque "Normalizar pelo OPT101" (a referência é comparada com o '
                                      'sinal normalizado).' + excl_txt)
            return
        key, ref, n_exp, _, ref_ok, cell = self._cal_ref()
        snr = ra / np.maximum(ra_e, 1e-30)
        snr_min = 10.0 ** (self.audio_snr_alert / 20.0)
        cal_valid = (snr >= snr_min)[ok] & keep[ok]
        if cal_valid.sum() < 4:
            self.lbl_dual_fit.setText('Calibração: são necessários pelo menos 4 pontos com SNR suficiente.' + excl_txt)
            return
        fv, sv = x[ok], s[ok]
        mv = sv * fv ** n_exp
        m_ref = float(np.median(mv[cal_valid]))
        tol = self.sp_dual_flat_tol.value()
        order = np.argsort(fv)
        flat = find_flat_band(fv[order], mv[order] / m_ref, cal_valid[order], tol)
        if flat is not None and flat[1] > flat[0]:
            f_lo, f_hi = float(fv[order][flat[0]]), float(fv[order][flat[1]])
            band = (fv >= f_lo) & (fv <= f_hi)
            amp = float(np.mean(mv[band & cal_valid])) if (band & cal_valid).any() else m_ref
            flat_txt = f'sistema plano (±{tol:g} dB) de {f_lo:.4g} a {f_hi:.4g} Hz'
            ff = np.geomspace(f_lo, f_hi, 100)
            self.c_dual_a_fit.setData(ff, amp * ff ** -n_exp) if self.dual_cal is None else self.c_dual_a_fit.setData([], [])
        else:
            amp = m_ref
            flat_txt = f'nenhuma faixa com o sistema plano (±{tol:g} dB)'
            self.c_dual_a_fit.setData([], [])
        self.c_dual_a_bad.setData(fv[~cal_valid], sv[~cal_valid])
        self.dual_std = {'f': fv, 's': sv, 's_rel': s_rel[ok], 'dphi': dphi[ok], 'dphi_e': dphi_e[ok],
                         'cal_valid': cal_valid, 'key': key, 'ref': ref, 'n_exp': n_exp, 'cell': cell,
                         'L_um': self.sp_cal_L.value(), 'alpha': self.sp_cal_alpha.value()}
        self.btn_dual_cal.setEnabled(not self.dual_active and self.dual_cal is None)
        if self.dual_cal is not None:
            txt = (f'<b>Calibração em uso</b> ({os.path.basename(self.dual_cal.get("path", ""))}): os dados já estão '
                   'corrigidos. Para guardar uma calibração nova, desmarque "Usar".')
        else:
            txt = (f'<b>Amostra de calibração</b> (célula {CELLS.get(cell, cell)}: S ∝ f<sup>−{n_exp:g}</sup>): M = S·f<sup>{n_exp:g}</sup> '
                   f'({int(cal_valid.sum())} pontos com SNR suficiente), {flat_txt} (linha laranja, f<sup>−{n_exp:g}</sup>). '
                   'Guarde esta varredura como amostra A ou B no painel Calibração.')
        self.dual_fit = self._plain(txt)
        self.lbl_dual_fit.setText(f'<span style="color:#1f4e9c;">{txt}</span>' + excl_txt)
        self.lbl_dual_fit.setToolTip('')

    def _set_dual_f_errors(self, x, s, s_rel, dphi, dphi_e, ok, cal_rel=None, cal_ph_e=None):
        '''Barras de erro da varredura em frequência (±1 DP: S com o DP relativo dos dois R combinados, Δφ com
        os DP das duas fases), em coordenadas log10 (eixo x log; S também em log). Com calibração aplicada,
        a incerteza dela vai em outras barras (verdes, atrás), separada da incerteza da medida.'''
        m = ok & np.isfinite(s) & (s > 0) & (x > 0)
        for e in (self.e_dual_a_cal, self.e_dual_b_cal):
            self._set_errbar(e, x=np.empty(0), y=np.empty(0))
        if not m.any():
            return
        if cal_rel is not None:
            rc = np.clip(np.nan_to_num(cal_rel[m]), 0.0, 0.999)
            self._set_errbar(self.e_dual_a_cal, x=np.log10(x[m]), y=np.log10(s[m]), top=np.log10(1.0 + rc),
                             bottom=-np.log10(1.0 - rc), beam=0.02)
        if cal_ph_e is not None:
            self._set_errbar(self.e_dual_b_cal, x=np.log10(x[m]), y=dphi[m], height=2.0 * np.nan_to_num(cal_ph_e[m]),
                             beam=0.02)
        lx = np.log10(x[m])
        ls = np.log10(s[m])
        r = np.clip(np.nan_to_num(s_rel[m]), 0.0, 0.999)
        self._set_errbar(self.e_dual_a, x=lx, y=ls, top=np.log10(1.0 + r), bottom=-np.log10(1.0 - r), beam=0.012)
        self._set_errbar(self.e_dual_b, x=lx, y=dphi[m], height=2.0 * np.nan_to_num(dphi_e[m]), beam=0.012)

    def _set_dual_points(self, x, y, idx, keep):
        '''Pontos do gráfico principal do Modo Duplo: incluídos cheios, excluídos do ajuste vazados.
        'idx' (índice em dual_results) vai como dado de cada ponto, para o clique saber qual é.'''
        self.c_dual_a.setData(x, y, data=list(idx),
                              symbolBrush=[pg.mkBrush('royalblue') if k else pg.mkBrush(255, 255, 255, 0) for k in keep],
                              symbolPen=[pg.mkPen('royalblue') if k else pg.mkPen('#909090', width=1.5) for k in keep])

    def _on_dual_point_clicked(self, _item, points, ev=None, *_):
        '''Clique num ponto do gráfico principal: tira do ajuste ou devolve a ele. Com pontos sobrepostos
        (ex.: PWM abaixo do limiar do laser, todos perto da origem), vale o mais próximo do cursor.'''
        if not len(points):
            return
        pt = points[0]
        if ev is not None and len(points) > 1:
            sx, sy = self.pw_dual_a.getPlotItem().vb.viewPixelSize()
            c = ev.pos()
            pt = min(points, key=lambda q: ((q.pos().x() - c.x()) / sx) ** 2 + ((q.pos().y() - c.y()) / sy) ** 2)
        if self.dual_peak_clicks is not None:      # marcando o pico: o clique vale para a faixa, não exclui
            return
        i = int(pt.data())
        self.dual_excluded ^= {i}
        self._show_dual_results()

    def _dual_include_all(self):
        self.dual_excluded.clear()
        self._show_dual_results()

    def _dual_excluded_text(self):
        '''Aviso com os pontos excluídos do ajuste ('' se nenhum).'''
        if not self.dual_excluded:
            return ''
        unit = '%' if self.dual_kind == 'P' else 'Hz'
        vals = ', '.join(f'{self.dual_results[i][0]:g}' for i in sorted(self.dual_excluded) if i < len(self.dual_results))
        return (f'<br><span style="color:#606060;">{len(self.dual_excluded)} ponto(s) excluído(s) do ajuste '
                f'com clique: {vals} {unit}</span>')

    def _on_dual_adv(self, checked):
        self.btn_dual_adv.setText('Avançado ▾' if checked else 'Avançado ▸')
        self.dual_adv_row.setVisible(checked)

    def _tau_sensor(self):
        '''τ do sensor (s) descontado do OPT101 na varredura em frequência; 0 = sem correção.'''
        return self.sp_dual_tau_sensor.value() * 1e-6

    def measure_sensor_tau(self):
        '''Preenche o τ do sensor comparando a varredura em frequência atual com outra já salva, feita com a
        mesma luz e outro resistor de realimentação (fit_sensor_tau).'''
        if self.dual_active or self.dual_kind != 'F' or not self.dual_results:
            self.flash('Medir τ do sensor: rode antes uma varredura em frequência do Modo Duplo com o resistor atual.', 6.0)
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Varredura de referência (mesma luz, outro resistor)', MEDIDAS_DIR, 'Modo Duplo em frequência (*DUPLO_freq_*.csv)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as fh:
                rows = [ln.strip().split(',') for ln in fh if ln.strip() and not ln.startswith('#')]
            head, data = rows[0], np.array([[float(v) for v in r] for r in rows[1:]])
            col = {name: data[:, head.index(name)] for name in
                   ('Frequencia_Hz', 'OPT101_R', 'OPT101_Fase_Graus', 'OPT101_Fase_DP')}
        except (OSError, ValueError, IndexError):
            self.flash(f'Medir τ do sensor: arquivo inválido ({os.path.basename(path)}).', 6.0)
            return
        x, ro, _, _, _, _, _, po, po_e = self._dual_arrays()
        res = fit_sensor_tau(x, po, po_e, ro, col['Frequencia_Hz'], col['OPT101_Fase_Graus'],
                             col['OPT101_Fase_DP'], col['OPT101_R'])
        if res is None:
            self.flash('Medir τ do sensor: menos de 4 frequências em comum, ou o ajuste não convergiu.', 6.0)
            return
        self.dual_sensor_fit_txt = f'{res["text"]} — referência: {os.path.basename(path)}'
        if res['tau'] is not None:
            self.btn_dual_adv.setChecked(True)
            self._set_spin(self.sp_dual_tau_sensor, res['tau'] * 1e6)
        self._show_dual_results()

    def _export_dual(self, resave=False):
        '''Grava CSV + PNG da varredura do Modo Duplo. resave=True ("Salvar de novo"): arquivos novos com
        sufixo _editado, com o ajuste, as exclusões e a calibração atuais; o original nunca é sobrescrito.'''
        if not self.dual_results:
            return
        q = self.dual_params
        now_dt = datetime.now()
        v = q['values']
        if q['kind'] == 'P':
            stem = self._stem(f"DUPLO_casada_pwm{v[0]:g}_{v[-1]:g}_f{q['freq']:g}Hz_{now_dt.strftime('%Y%m%d_%H%M%S')}")
            what = f"Varredura casada em PWM {v[0]:g} a {v[-1]:g} % ({len(v)} pontos), modulação {q['freq']:g} Hz"
            col = 'PWM_Pct'
        elif q['kind'] == 'T':
            stem = self._stem(f"DUPLO_tempo_f{q['freq']:g}Hz_pwm{q['pwm']:g}_{now_dt.strftime('%Y%m%d_%H%M%S')}")
            what = (f"Sinal x tempo: {len(v)} pontos de {q.get('dt', 0):g} s em {v[-1]:.0f} s, modulação {q['freq']:g} Hz, "
                    f"PWM {q['pwm']:g} %")
            col = 'Tempo_s'
        elif q.get('mod') == 'optica':
            lo, hi = min(v), max(v)
            stem = self._stem(f"DUPLO_freq_{lo:.4g}_{hi:.4g}Hz_optica_{now_dt.strftime('%Y%m%d_%H%M%S')}")
            what = f"Varredura em frequência manual {lo:.4g} a {hi:.4g} Hz ({len(v)} pontos), modulação óptica"
            col = 'Frequencia_Hz'
        else:
            stem = self._stem(f"DUPLO_freq_{v[0]:g}_{v[-1]:g}Hz_pwm{q['pwm']:g}_{now_dt.strftime('%Y%m%d_%H%M%S')}")
            what = f"Varredura em frequência {v[0]:g} a {v[-1]:g} Hz ({len(v)} pontos), PWM {q['pwm']:g} %"
            col = 'Frequencia_Hz'
        med = getattr(self, 'dual_median', None)
        if med is not None and len(med['rows']) != len(self.dual_results):
            med = None
        rp = getattr(self, 'dual_rep', None)
        if not resave and med is not None:
            stem += '_mediana'
        elif not resave and rp and q['kind'] == 'F':
            stem += f"_rep{rp['k']}"
        if resave:
            orig = getattr(self, 'dual_last_csv', None)
            if orig:
                # herda o nome do original (amostra incluída), sem acumular sufixos em edições sucessivas
                base = re.sub(r'_editado(_\d{6})?$', '', os.path.splitext(os.path.basename(orig))[0])
                stem = f"{base}_editado_{now_dt.strftime('%H%M%S')}"
            else:
                stem += '_editado'
        os.makedirs(self._save_dir(), exist_ok=True)
        csv_path = os.path.join(self._save_dir(), stem + '.csv')
        tau = f"tau = {q['tau']:g} s (integração longa)" if q['tau'] else 'tau dos filtros dos lock-ins'
        if q.get('adapt'):
            taus = getattr(self, 'adapt_taus', [])
            rng = (f"; tau usado de {min(taus):.3g} a {max(taus):.3g} s" if taus else '')
            low = (f"; abaixo de {LOWF_FMAX:g} Hz tau fixo = tau max" if q.get('adapt40') else '')
            blk = (f", permitir médias: até {q['blocks']} medidas com o mesmo tau" if q.get('blocks', 1) > 1 else '')
            tau = (f"tau adaptativo (precisão {q['adapt'][0]:g} %, tau max {q['adapt'][1]:g} s{rng}; "
                   f"espera 7tau, média por max(1 s, 3tau){low}{blk})")
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                f.write(f"# Modo Duplo - {now_dt.strftime('%Y-%m-%d %H:%M:%S')}\n# {what}\n"
                        f"# Medida: {q['mode']}; {tau}\n# Celula = {self.cmb_cell.currentData() or 'Camara'}\n")
                ext_cols = q.get('mod') == 'optica' and len(getattr(self, 'dual_fstd', [])) == len(self.dual_results)
                if not resave and q.get('t_start') and not q.get('t_end'):
                    q['t_end'] = now_dt
                if q.get('t_start') and q.get('t_end'):
                    dur = (q['t_end'] - q['t_start']).total_seconds()
                    f.write(f"# Inicio = {q['t_start'].strftime('%Y-%m-%d %H:%M:%S')}; "
                            f"Fim = {q['t_end'].strftime('%Y-%m-%d %H:%M:%S')}; Duracao = {dur:.0f} s ({self._fmt_time(dur)})\n")
                pcol = len(getattr(self, 'dual_pinfo', [])) == len(self.dual_results)
                ce = getattr(self, 'dual_cal_err', None) if self.dual_cal is not None else None
                n_res = len(self.dual_results)
                c_rel = ce[0] if ce and ce[0] is not None and len(ce[0]) == n_res else np.full(n_res, np.nan)
                c_ph = ce[1] if ce and ce[1] is not None and len(ce[1]) == n_res else np.full(n_res, np.nan)
                ccol = bool(ce) and (np.isfinite(c_rel).any() or np.isfinite(c_ph).any())
                if ccol:
                    f.write('# Cal_S_DP_Pct e Cal_Fase_DP_Graus = incerteza (1 DP) da calibração interpolada em cada '
                            'frequência (nan fora da faixa dela); os _DP das colunas anteriores são desta medida\n')
                if pcol:
                    f.write('# Por ponto: Tau_s = tau do lock-in; Tempo_ponto_s = espera + média (inclui refazimentos); '
                            'Refeito = vezes que o tau adaptativo refez o ponto (tau maior ou, com deriva, nova média); '
                            'Flutuacao_S_Pct e Flutuacao_Fase_Graus = flutuação de S = R_INMP441/R_OPT101 e de Δφ durante a '
                            'média; Deriva_* = 2ª metade - 1ª da última média (S, Δφ, R do OPT101, R do INMP441)\n')
                if q.get('mod') == 'optica':
                    f.write('# Modulacao = optica (chopper; frequência e fase de referência detectadas no OPT101)\n')
                nbcol = med is None and len(getattr(self, 'dual_nb', [])) == len(self.dual_results) > 0
                if nbcol:
                    f.write(f'# Ruido das vizinhas: Ruido_vizinhas_q = mediana de q = rms(R em f*(1±{NB_REL:g})) / R em f '
                            f'(janela Hann de {NB_WIN_S:g} s, 1 por segundo; |erro| tipico ~0,3*q); Descartado_Pct = '
                            f'parte da média descartada (q > {NB_K:g} x mediana de q do ponto); Refeito_ruido = médias '
                            f'refeitas (mais de {100 * NB_REDO_FRAC:.0f} % descartado)\n')
                if q.get('mains_moved'):
                    f.write('# Pontos deslocados da rede (múltiplos de 60 Hz excluídos, sem detecção de ruído): '
                            + ', '.join(f'{a:g} -> {b:g} Hz' for a, b in q['mains_moved']) + '\n')
                order, seed = q.get('order', ('crescente', None))
                if med is not None and order == 'embaralhada' and med.get('seeds'):
                    f.write(f"# Ordem = embaralhada; sementes = {', '.join(str(x) for x in med['seeds'])} "
                            f"(random.Random(semente).shuffle dos índices em ordem crescente, uma por repetição)\n")
                elif order == 'embaralhada':
                    f.write(f'# Ordem = embaralhada; semente = {seed} '
                            '(random.Random(semente).shuffle dos índices em ordem crescente)\n')
                elif order != 'crescente':
                    f.write(f'# Ordem = {order}\n')
                if q.get('mains_fixed') is False:
                    f.write('# Rede = só os múltiplos de 60 Hz achados pela detecção de ruído (INMP441/OPT101) foram '
                            'excluídos\n')
                elif q.get('mains_fixed') and q['kind'] == 'F' and not q.get('mains_moved'):
                    f.write('# Rede = múltiplos de 60 Hz excluídos (±3 Hz; sem detecção de ruído do OPT101); nenhum '
                            'ponto perto\n')
                ans = q.get('auto_noise') or []
                for an in ([ans] if isinstance(ans, dict) else ans):
                    src = (f"janela Detectar ruídos de fundo, {an.get('when', '')}, {an['dur']:.0f} s, laser em PWM 0"
                           if an.get('src') == 'janela' else
                           f"áudio de {an['dur']:.0f} s do warm-up, laser em {an['fref']:.4g} Hz e harmônicos ignorados")
                    f.write(f"# Ruidos detectados = {an['summary']} ({src}); excluídos: "
                            + (', '.join(f'{v:g}' for v in an['vals']) or 'nenhum') + ' Hz\n')
                if q.get('skipped') and med is None:
                    f.write('# Pontos pulados (sem dados de um sensor, mesmo medindo de novo): '
                            + ', '.join(f'{v:g}' for v in q['skipped']) + ' Hz\n')
                if med is not None and med.get('missing'):
                    f.write('# Repetições incompletas: ' + '; '.join(f'{k} (faltam {n})' for k, n in med['missing'])
                            + '; nesses pontos a mediana usa só as repetições existentes (N_repeticoes)\n')
                if q.get('extra_avoid'):
                    ex, mv = q['extra_avoid']
                    f.write(f"# Faixas excluidas (fontes de ruído, ±2 %, mín. ±3 Hz): {', '.join(f'{x:g}' for x in ex)} Hz"
                            + ('; pontos deslocados: ' + ', '.join(f'{a:g} -> {b:g} Hz' for a, b in mv) if mv else '')
                            + '\n')
                ocol = (med is None and not resave and q['kind'] == 'F'
                        and len(getattr(self, 'dual_ordpos', [])) == len(self.dual_results) > 0)
                omed = med is not None and bool(med.get('orders'))
                if ocol or omed:
                    f.write('# Ordem_medida = posição em que o ponto foi medido (1 = primeiro'
                            + ('; uma por repetição, separadas por ";"' if omed else '')
                            + ')' + ('; Hora_ponto = hora do fim do ponto' if ocol else '') + '\n')
                if rp and q['kind'] == 'F' and med is None and not resave:
                    f.write(f"# Repeticao = {rp['k']} de {rp['n']} (no fim: CSV _mediana)\n")
                if med is not None:
                    pcol = ccol = ext_cols = False
                    f.write(f"# Mediana ponto a ponto de {med['n']} varreduras: {', '.join(med['csvs'])}\n"
                            '# Colunas: R e fases = mediana das repetições; _DP = desvio-padrão entre elas; S = '
                            'mediana de R_INMP441/R_OPT101; Incerteza_S_Pct = 100*1,25*DP(S)/sqrt(N)/mediana(S); '
                            'Incerteza_Fase_Graus = 1,25*DP(Δφ)/sqrt(N) (1,25 = eficiência da mediana)\n')
                if q.get('refine'):
                    f.write(f"# {q['refine']}\n")
                if resave and getattr(self, 'dual_last_csv', None):
                    f.write(f'# Versão editada ("Salvar de novo") de: {os.path.basename(self.dual_last_csv)}\n')
                if q['kind'] == 'F':
                    if self.dual_opt_tau is not None:
                        f.write(f"# {self._plain(self.dual_opt_tau['text'])}\n")
                    f.write(f"# OPT101: tau do sensor descontado em S e no gráfico = {self.dual_tau_sensor * 1e6:.3g} us "
                            f"(os dados abaixo são brutos)\n")
                    f.write(f"# Normalizacao pelo OPT101 no gráfico/ajuste = {'sim' if self.chk_dual_norm.isChecked() else 'nao'}\n")
                if self.dual_fit:
                    f.write(f'# {self.dual_fit}\n')
                if q['kind'] == 'F' and self.dual_model_txt:
                    f.write(f'# Ajuste com modelo: {self.dual_model_txt}\n')
                if self.dual_excluded:
                    f.write(f'# Pontos excluídos do ajuste com clique ({col}): '
                            + ', '.join(f'{self.dual_results[i][0]:g}' for i in sorted(self.dual_excluded))
                            + ' (continuam nos dados abaixo)\n')
                if self.dual_cal is not None:
                    f.write(f"# Arquivo de calibração do microfone: {os.path.basename(self.dual_cal['path'])} "
                            f"(aplicada no gráfico/fit; os dados abaixo são brutos)\n")
                elif q['kind'] == 'F':
                    # Sem esta linha ficava a dúvida se a calibração foi usada (ex.: "Usar" desmarcado no meio da medida)
                    why = ('"Usar" desmarcado' if not self.chk_mic_cal.isChecked() else
                           'sem normalização pelo OPT101' if not self.chk_dual_norm.isChecked() else
                           'nenhuma calibração válida selecionada')
                    f.write(f"# Calibração do microfone no gráfico/ajuste = não aplicada ({why}; os dados abaixo são "
                            f"brutos, como sempre)\n")
                f.write(f'{col},OPT101_R,OPT101_R_DP,INMP441_R,INMP441_R_DP,INMP441_Fase_Graus,'
                        'INMP441_Fase_DP,OPT101_Fase_Graus,OPT101_Fase_DP' + (',Frequencia_DP_Hz' if ext_cols else '')
                        + (',' + ','.join(DUAL_POINT_COLUMNS + DUAL_DRIFT_COLUMNS) if pcol else '')
                        + (',Cal_S_DP_Pct,Cal_Fase_DP_Graus' if ccol else '')
                        + (',S,N_repeticoes,Incerteza_S_Pct,Incerteza_Fase_Graus' if med is not None else '')
                        + (',Ruido_vizinhas_q,Descartado_Pct,Refeito_ruido' if nbcol else '')
                        + (',Ordem_medida,Hora_ponto' if ocol else '') + (',Ordem_medida' if omed else '') + '\n')
                for i, row in enumerate(med['rows'] if med is not None else ()):
                    f.write(f'{row[0]:.3f},{row[1]:.6g},{row[2]:.4g},{row[3]:.6g},{row[4]:.4g},'
                            f'{row[5]:.3f},{row[6]:.3f},{row[7]:.3f},{row[8]:.3f},{row[9]:.6g},{row[10]:d},'
                            f'{row[11]:.3g},{row[12]:.3g}'
                            + (f",{med['orders'][i]}" if omed else '') + '\n')
                for i, row in enumerate(self.dual_results if med is None else ()):
                    f.write(f'{row[0]:.3f},{row[1]:.6g},{row[2]:.4g},{row[3]:.6g},{row[4]:.4g},'
                            f'{row[5]:.3f},{row[6]:.3f},{row[7]:.3f},{row[8]:.3f}'
                            + (f',{self.dual_fstd[i]:.4g}' if ext_cols else '')
                            + (',{:.4g},{:.1f},{:.0f},{:.3g},{:.3g},{:.3g},{:.3g},{:.3g},{:.3g}'.format(
                                *(tuple(self.dual_pinfo[i]) + (float('nan'),) * 9)[:9]) if pcol else '')
                            + (f',{100 * c_rel[i]:.3g},{c_ph[i]:.3g}' if ccol else '')
                            + (',{:.3g},{:.3g},{:d}'.format(float(self.dual_nb[i][0]), float(self.dual_nb[i][1]),
                                                              int(self.dual_nb[i][2])) if nbcol else '')
                            + (f',{self.dual_ordpos[i]:d},{self.dual_ptime[i]}' if ocol else '') + '\n')
            self._grab_dual_plots().save(os.path.join(self._save_dir(), stem + '.png'))
            self._session_add(csv_path, os.path.join(self._save_dir(), stem + '.png'))
            if self.dual_cal is not None:
                self._session_add(*self._calibration_files(self.dual_cal['path']))
            if resave:
                self.flash(f'Varredura do Modo Duplo salva de novo: {csv_path}', 6.0)
                self.lbl_dual_status.setText(f'Salva de novo: {os.path.basename(csv_path)}')
                self.lbl_dual_status.setToolTip(csv_path)
            else:
                self.dual_last_csv = csv_path
                self.flash(f'Varredura do Modo Duplo concluída: {csv_path}', 6.0)
                self.lbl_dual_status.setText(f'Concluída: {os.path.basename(csv_path)}')
                self.lbl_dual_status.setToolTip(csv_path)       # caminho completo só no balão (cabia cortado)
        except Exception as e:
            print(f'Erro ao salvar a varredura do Modo Duplo: {e}')

    @staticmethod
    def _set_errbar(e, **kw):
        '''ErrorBarItem.setData acumula as opções: zera as que não vêm, para não sobrar top/height de outro gráfico.'''
        for k in ('height', 'width', 'top', 'bottom', 'left', 'right'):
            kw.setdefault(k, None)
        e.setData(**kw)

    @staticmethod
    def _plain(html):
        '''Texto de um rótulo rich text em uma linha (cabeçalho de CSV).'''
        return re.sub(r'<[^>]+>', '', html.replace('<br>', '; ')).replace('&nbsp;', ' ')

    @staticmethod
    def _group(title):
        box = QtWidgets.QGroupBox(title)
        box.setStyleSheet('QGroupBox{font-weight:bold;border:1px solid #999;border-radius:4px;'
                          'margin-top:8px;padding-top:6px;}'
                          'QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}')
        return box
