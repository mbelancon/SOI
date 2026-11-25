# -*- coding: utf-8 -*-
'''Modo sem janela (--varredura, --sinal-t, --serie, --detectar-ruido): a mesma janela, fora da tela.

Parte do SOI Controller (antes em soi_controller.py).'''

from soi_comum import *  # noqa: F401,F403


HEADLESS_HELP = """Modo sem janela (varredura em frequência do Modo Duplo pela linha de comando).

Exemplos:
  python soi_controller.py --varredura --amostra Al
  python soi_controller.py --varredura --amostra Al --fmin 5 --fmax 2440 --n 35 --tau 4 --precisao 1
  python soi_controller.py --varredura --simulado --fmin 100 --fmax 1000 --n 5

Usa o mesmo código da interface (τ adaptativo, colunas por ponto, calibração, nome padrão na pasta Medidas).
O PWM do laser é posto em 100 % (ou --pwm) e a modulação em Eletrônica. Feche a interface antes: a porta
serial só pode ser aberta por um programa. Ctrl+C cancela (o que já foi medido não é salvo).
"""


def _headless_args(argv):
    import argparse
    ap = argparse.ArgumentParser(prog='soi_controller.py --varredura', description=HEADLESS_HELP, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--varredura', action='store_true', help='roda a varredura sem janela')
    ap.add_argument('--amostra', default=None, help='nome da amostra (prefixo dos arquivos; padrão: o da interface)')
    ap.add_argument('--fmin', type=float, default=None, help='frequência inicial em Hz (padrão: a da interface)')
    ap.add_argument('--fmax', type=float, default=None, help='frequência final em Hz (padrão: a da interface)')
    ap.add_argument('--n', type=int, default=None, help='número de pontos, espaçamento log (padrão: o da interface)')
    ap.add_argument('--tau', type=float, default=None, help='τ max em s (τ adaptativo) ou τ fixo (padrão: o da interface)')
    ap.add_argument('--precisao', type=float, default=None, help='precisão do τ adaptativo em %% (padrão: a da interface)')
    ap.add_argument('--tau-fixo', action='store_true', help='τ fixo (padrão desde 18/11; espera 9τ, média 1τ; '
                    'em toda a faixa)')
    ap.add_argument('--descartar', action='store_true',
                    help='liga "Descartar trechos com som da sala" (monitor das vizinhas f ± 7 %%; desligado por padrão)')
    ap.add_argument('--sem-descarte', action='store_true', help='(padrão desde 19/11) não descarta trechos com som da sala')
    ap.add_argument('--sem-evitar-rede', action='store_true',
                    help='sem detecção de ruído, não exclui os múltiplos de 60 Hz (±3 Hz) da varredura')
    ap.add_argument('--ordem', choices=('crescente', 'decrescente', 'embaralhada'), default='embaralhada',
                    help='ordem de medida das frequências (padrão embaralhada = nova ordem aleatória a cada repetição, '
                         'semente no cabeçalho do CSV)')
    ap.add_argument('--semente', type=int, default=None,
                    help='semente da ordem embaralhada (repetição k usa semente + k - 1); padrão: aleatória')
    ap.add_argument('--excluir', '--evitar', dest='evitar', default=None, metavar='F1;F2',
                    help='faixas excluídas: frequências de fontes de ruído (ex.: "170.7" ou "170.7;341.4"); nenhum '
                         'ponto é medido a até ±2 %% delas (mínimo 3 Hz): o ponto vai para 1 Hz além da borda')
    ap.add_argument('--adaptativo', action='store_true', help='liga o τ adaptativo (antes o padrão; --precisao também liga)')
    ap.add_argument('--repeticoes', type=int, default=None, metavar='N',
                    help='repete a varredura N vezes e grava a mediana ponto a ponto (padrão: o da interface, 3)')
    ap.add_argument('--aquecer', type=float, default=0.0, metavar='S',
                    help='warm-up: espera S segundos com o laser ligado (no PWM escolhido) antes de começar')
    ap.add_argument('--medias', type=int, default=0, metavar='N',
                    help='(ignorado desde a 2.5.0: "Permitir médias" saiu; use --repeticoes)')
    ap.add_argument('--adapt-tudo', action='store_true',
                    help='(desde a 2.5.0 o τ adaptativo vale em toda a faixa; mantido por compatibilidade)')
    ap.add_argument('--pwm', type=float, default=100.0, help='PWM do laser em %% (padrão 100)')
    ap.add_argument('--celula', choices=('Camara',), default=None, help='montagem (desde a 2.5.0 só Camara; mantido por compatibilidade)')
    ap.add_argument('--cal', default=None, help='arquivo CAL_*.csv da pasta Medidas aplicado no gráfico, ou "nenhuma"')
    ap.add_argument('--porta', default=None, help='porta serial (ex.: COM5); padrão: detecção automática')
    ap.add_argument('--simulado', action='store_true', help='amostragem simulada, sem a placa')
    ap.add_argument('--sinal-t', action='store_true',
                    help='em vez da varredura, Sinal x t: --f, --pwm, --tau, --dt, --duracao fixos')
    ap.add_argument('--f', type=float, default=10.0, help='Sinal x t: frequência em Hz (padrão 10)')
    ap.add_argument('--dt', type=float, default=5.0, help='Sinal x t: um ponto a cada dt segundos (padrão 5)')
    ap.add_argument('--duracao', type=float, default=None,
                    help='Sinal x t: duração em minutos (padrão 10); --detectar-ruido: segundos por gravação (padrão 20)')
    ap.add_argument('--detectar-ruido', action='store_true',
                    help='Detectar ruídos de fundo: grava o INMP441 com o laser parado, lista os tons acima do fundo e '
                         'as séries harmônicas e salva Ruido_fundo_*.csv/.bin em Medidas')
    ap.add_argument('--sem-detectar-ruido', action='store_true',
                    help='não analisa o áudio do warm-up (--aquecer) para excluir os ruídos de fundo da varredura')
    ap.add_argument('--comparar', action='store_true',
                    help='--detectar-ruido comparativo: grava sem a fonte de ruído, espera Enter, grava com a fonte')
    ap.add_argument('--limiar', type=float, default=None, metavar='DB',
                    help=f'--detectar-ruido: tom = PSD acima do fundo por mais de DB (padrão {soi_ruido.TONE_DB:g} dB)')
    ap.add_argument('--desligar', action='store_true', help='no fim, PWM 0 (laser parado; para esfriar entre medidas)')
    ap.add_argument('--serie', default=None, metavar='ARQUIVO',
                    help='roda uma série (*.serie.txt, a mesma da aba Medidas em Série); --amostra troca o nome base')
    return ap.parse_args(argv)


def _headless_off(win, a, pump):
    if a.desligar:
        win.sp_power.setValue(0.0)
        win.on_power(0.0)
        pump(1.0)
        print('PWM 0 (laser parado).')


def _headless_time(win, a, pump):
    """Sinal x t sem janela (pedido por run_headless com --sinal-t)."""
    win.sp_dt_f.setValue(a.f)
    win.sp_dt_pwm.setValue(a.pwm)
    win.sp_dt_tau.setValue(a.tau if a.tau is not None else 1.0)
    win.sp_dt_dt.setValue(a.dt)
    win.sp_dt_dur.setValue(a.duracao if a.duracao is not None else 10.0)
    print(f'Sinal x t: {win.sp_dt_f.value():g} Hz, PWM {win.sp_dt_pwm.value():g} %, τ = {win.sp_dt_tau.value():g} s, '
          f'ponto a cada {win.sp_dt_dt.value():g} s, {win.sp_dt_dur.value():g} min; amostra "{win.ed_sample.text()}"'
          + ('; SIMULADO' if a.simulado else ''), flush=True)
    win.dual_last_csv = None
    win.toggle_dual_time()
    if not win.dual_active:
        print('ERRO: a medida não começou (veja as mensagens acima).')
        _headless_off(win, a, pump)
        win.close()
        return 6
    shown, t0 = 0, time.time()
    every = max(1, int(round(60.0 / max(a.dt, 0.5))))
    try:
        while win.dual_busy():
            pump(0.5)
            n = len(win.dual_results)
            if n != shown and n and (n % every == 0 or n == 1):
                r = win.dual_results[-1]
                print(f'  t = {r[0]:7.0f} s  S = {r[3] / max(r[1], 1e-30):.5g}  Δφ = {wrap_deg(r[5] - r[7]):7.2f}°  '
                      f'OPT101 R = {r[1]:.5g}  INMP441 R = {r[3]:.5g}', flush=True)
            shown = n
    except KeyboardInterrupt:
        print('Interrompido: salvando o que já foi medido.')
        win.toggle_dual_time()
    csv = getattr(win, 'dual_last_csv', None)
    print(f'Concluída em {win._fmt_time(time.time() - t0)}: {csv}' if csv else 'ERRO: o CSV não foi salvo.')
    _headless_off(win, a, pump)
    win.close()
    return 0 if csv else 7


def _headless_serie(win, a, serie, pump):
    """Medidas em série sem janela (--serie): o mesmo SeriesRunner da aba, dirigido pelo laço de eventos."""
    runner = win.series_tab.runner
    runner.log = lambda t: print(t, flush=True)

    def aviso(text):
        print(f'\n*** AVISO: {text}', flush=True)
        if sys.stdin is not None and sys.stdin.isatty():
            input('    Tecle Enter para continuar... ')
        else:
            print('    (sem terminal: seguindo sem esperar)', flush=True)
    runner.on_aviso = aviso
    jobs = soi_serie.expand(serie)
    lo, hi, av = runner.total_estimate(jobs)
    print(f'Série {a.serie}: {len(jobs)} medidas, tempo estimado {soi_serie.fmt_dur(hi)}'
          + (f' (+ {av} aviso(s))' if av else '') + ('; SIMULADO' if a.simulado else ''), flush=True)
    if not runner.start(serie, a.serie):
        print('ERRO: a série não começou (veja as mensagens acima).')
        win.close()
        return 6
    try:
        while runner.active:
            pump(0.5)
    except KeyboardInterrupt:
        print('Interrompido: parando a série (salva o que já foi medido).')
        runner.stop()
    st = list(runner.status.values())
    win.close()
    return 0 if st and all(x == 'concluída' for x in st) else 7


def _headless_noise(win, a, pump):
    """--detectar-ruido [--comparar] [--duracao S] [--limiar DB]: mesma análise da janela Detectar ruídos de fundo."""
    dur = a.duracao if a.duracao is not None else soi_ruido.DUR_DEF_S
    thr = a.limiar if a.limiar is not None else soi_ruido.TONE_DB
    win.set_pwm(0.0)
    pump(1.5)                                      # laser parado e áudio chegando
    fs = win.noise_fs()

    def record(what):
        print(f'Gravando {dur:g} s do INMP441 {what}(laser em PWM 0)...', flush=True)
        win.noise_capture_begin()
        t0 = time.time()
        while win.noise_capture_len() < dur * fs:
            pump(0.2)
            if time.time() - t0 > 2 * dur + 10:
                win.noise_capture_end()
                return None
        x = win.noise_capture_end()
        return x[:int(dur * fs)]
    x_off = None
    if a.comparar:
        x_off = record('SEM a fonte de ruído ')
        if x_off is None:
            print('ERRO: o áudio do INMP441 não chegou.')
            win.close()
            return 7
        try:
            input('Ligue a fonte de ruído e tecle Enter... ')
        except EOFError:
            pass
    x = record('COM a fonte de ruído ' if a.comparar else '')
    if x is None:
        print('ERRO: o áudio do INMP441 não chegou.')
        win.close()
        return 7
    res = (soi_ruido.analyze_compare(x_off, x, fs, thr=thr) if a.comparar else soi_ruido.analyze(x, fs, thr=thr))
    lo = getattr(win, 'noise_last_opt', None)
    res['opt_mains'] = soi_ruido.opt_mains(lo[0], lo[1], thr=thr) if lo is not None else []
    stem = soi_ruido.file_stem(win.ed_sample.text(), 'Ruido_fundo' + ('_comparativo' if a.comparar else ''))
    folder = win._save_dir()
    os.makedirs(folder, exist_ok=True)
    hdr = [f"Detectar ruidos de fundo (sem janela) - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
           f"Modo = {'comparativo (sem/com a fonte)' if a.comparar else 'rapido'}; laser em PWM 0; {dur:g} s por "
           f"gravacao; INMP441 a {fs:.0f} S/s (media de 4 amostras)" + ('; SIMULADO' if a.simulado else ''),
           f'Welch Hann {soi_ruido.SEG_S:g} s; fundo = mediana movel +-{soi_ruido.BG_HALF_HZ:g} Hz; limiar {thr:g} dB'
           + (f'; com a fonte >= {soi_ruido.CMP_DB:g} dB acima' if a.comparar else ''),
           f'Celula = {win.cmb_cell.currentData()}']
    path = os.path.join(folder, stem + '.csv')
    soi_ruido.save_csv(path, res, hdr)
    soi_ruido.save_bin(os.path.join(folder, stem + '.bin'), x)
    if x_off is not None:
        soi_ruido.save_bin(os.path.join(folder, stem + '_sem_fonte.bin'), x_off)
    for fx, db, f0, k, kind in soi_ruido.rows(res):
        print(f'  {fx:9.2f} Hz  +{db:5.1f} dB' + (f'  série f0 = {f0:.2f} Hz, k = {k}' if f0 else '')
              + ('  (rede)' if kind == 'rede' else '  (rede, OPT101)' if kind == 'rede OPT101' else ''), flush=True)
    sel = [r[0] for r in soi_ruido.rows(res)]
    av = soi_ruido.avoid_list_for(res, sel, True)
    print(f'Ruídos detectados: {soi_ruido.summary(res)}', flush=True)
    if av:
        print('Para excluir sempre nas varreduras: --excluir "' + ';'.join(f'{v:g}' for v in av) + '"', flush=True)
    print(f'Salvo: {path}', flush=True)
    win.close()
    return 0


def run_headless(argv, LockInWindow):
    """Varredura em frequência do Modo Duplo sem janela: a mesma LockInWindow, fora da tela (Qt offscreen),
    dirigida pelos argumentos. Devolve o código de saída (0 = CSV salvo)."""
    for stream in (sys.stdout, sys.stderr):         # console do Windows (cp1252/cp850): τ, Δφ, ±
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    a = _headless_args(argv)
    serie = None
    if a.serie:
        try:
            serie = soi_serie.load(a.serie)
        except (OSError, ValueError) as e:
            print(f'ERRO: série {a.serie}: {e}')
            return 8
        if a.amostra is not None:
            serie['nome_base'] = a.amostra
        a.pwm = 0.0                                # laser parado até a primeira etapa
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.*=false')
    if a.simulado:
        os.environ['SOI_NO_SERIAL'] = '1'
    else:
        if a.porta:
            os.environ['TL_ARDUINO_PORT'] = a.porta
        port, ports = find_arduino_port()
        if port is None:
            print('ERRO: placa não encontrada. Portas vistas: '
                  + (', '.join(f'{p.device} ({p.description})' for p in ports) or 'nenhuma')
                  + '. Use --porta COMx ou --simulado.')
            return 2
        try:
            serial.Serial(port, BAUD_RATE, timeout=0.05).close()
        except (serial.SerialException, OSError) as e:
            print(f'ERRO: a porta {port} está ocupada ou não abriu ({e}).\n'
                  'Provavelmente a interface do SOI (ou um monitor serial) está aberta: feche-a e rode de novo.')
            return 3
        print(f'Placa em {port}.')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(['soi_controller'])
    # nada de janelas modais (ninguém para clicar): as mensagens vão para o terminal
    def _msg(kind):
        def f(parent, title, text, *rest, **kw):
            print(f'[{kind}] {title}: {text}')
            return QtWidgets.QMessageBox.StandardButton.Ok
        return f
    for k in ('warning', 'information', 'critical'):
        setattr(QtWidgets.QMessageBox, k, staticmethod(_msg(k)))
    LockInWindow.save_settings = lambda self: None        # não mexe nas preferências da interface
    win = LockInWindow()
    win.headless = True
    win.show()

    def pump(sec):
        t = time.time()
        while time.time() - t < sec:
            app.processEvents()
            time.sleep(0.005)
    last_flash = ['']
    orig_flash = win.flash

    def flash(text, seconds=3.0):
        if text != last_flash[0]:
            print(f'  · {re.sub(r"<[^>]+>", "", text)}', flush=True)
            last_flash[0] = text
        orig_flash(text, seconds)
    win.flash = flash
    if a.simulado:
        win.chk_sim.setChecked(True)
    else:
        t0 = time.time()
        while not win.link.connected and time.time() - t0 < 20:
            pump(0.2)
        if not win.link.connected:
            print(f'ERRO: não conectou à placa ({win.link.last_error or "sem resposta"}).')
            win.close()
            return 4
    win.cmb_mod.setCurrentIndex(0)                 # modulação eletrônica (o STM32 varre a frequência)
    win.sp_power.setValue(a.pwm)                   # PWM 100 %: dispara on_power -> P100
    win.on_power(win.sp_power.value())
    if a.amostra is not None:
        win.ed_sample.setText(a.amostra)
        if win.audio_rec is not None:
            win.audio_rec.retitle()
    if a.celula:
        win.cmb_cell.setCurrentIndex(max(0, win.cmb_cell.findData(a.celula)))
    if a.cal:
        if a.cal.lower() in ('nenhuma', 'none', '0'):
            win.chk_mic_cal.setChecked(False)
        else:
            i = next((i for i in range(win.cmb_mic_cal.count())
                      if os.path.basename(str(win.cmb_mic_cal.itemData(i) or '')) == os.path.basename(a.cal)
                      or win.cmb_mic_cal.itemText(i).endswith(os.path.splitext(os.path.basename(a.cal))[0])), None)
            if i is None:
                print(f'ERRO: calibração {a.cal} não encontrada na pasta Medidas.')
                win.close()
                return 5
            win.cmb_mic_cal.setCurrentIndex(i)
    if a.detectar_ruido:
        return _headless_noise(win, a, pump)
    sp0, sp1, space, spn, _ = win.dual_fw['F']
    space.setCurrentIndex(0)                       # pontos em escala log
    if a.fmin is not None:
        sp0.setValue(a.fmin)
    if a.fmax is not None:
        sp1.setValue(a.fmax)
    if a.n is not None:
        spn.setValue(a.n)
    win.chk_dual_adapt.setChecked((a.adaptativo or a.precisao is not None) and not a.tau_fixo)
    if a.repeticoes is not None:
        win.sp_dual_reps.setValue(max(1, a.repeticoes))
    win.chk_dual_avoid60.setChecked(not a.sem_evitar_rede)
    win.chk_dual_nb.setChecked(a.descartar and not a.sem_descarte)
    win.cmb_dual_order.setCurrentIndex(win.cmb_dual_order.findData(a.ordem))
    win.dual_seed_fixed = a.semente if a.semente is not None else int.from_bytes(os.urandom(3), 'big')
    if a.evitar is not None:
        win.ed_dual_avoid.setText(a.evitar)
    if win._dual_avoid_extra():
        _base = win._dual_planned('F', raw=True)
        if win._mains_fixed():
            _base = soi_serie.avoid_mains(_base)[0]
        _m2 = soi_serie.avoid_list(_base, win._dual_avoid_extra())[1]
        print(f"Faixas excluídas: {', '.join(f'{x:g}' for x in win._dual_avoid_extra())} Hz"
              + ('; pontos deslocados: ' + ', '.join(f'{x:g} -> {y:g} Hz' for x, y in _m2) if _m2 else
                 ' (nenhum ponto perto)'), flush=True)
    _v, moved = soi_serie.avoid_mains(win._dual_planned('F', raw=True))
    if moved:
        print(('Aviso: pontos perto de múltiplos de 60 Hz: ' if a.sem_evitar_rede else
               'Pontos deslocados da rede: ') + ', '.join(f'{x:g} -> {y:g} Hz' for x, y in moved), flush=True)
    if a.sinal_t and soi_serie.mains_near(a.f) is not None:
        print('Aviso: ' + soi_serie.mains_msg(a.f), flush=True)
    win.chk_dual_adapt40.setChecked(False)          # 2.5.0: τ adaptativo em toda a faixa (--adapt-tudo é o padrão)
    win.chk_dual_blocks.setChecked(False)
    if a.medias > 1:
        print('Aviso: --medias é ignorado desde a 2.5.0 ("Permitir médias" saiu); use --repeticoes.', flush=True)
    win._apply_adapt_ui()
    if a.tau is not None:
        win.dual_tau_w['F'].setValue(a.tau)
    if a.precisao is not None:
        win.sp_dual_adapt_tol.setValue(a.precisao)
    if a.aquecer > 0:
        if a.sinal_t:                              # aquece no PWM e na frequência da medida
            win._set_spin(win.sp_freq, a.f)
            win.apply_frequency(a.f)
        print(f'Warm-up: laser em PWM {win.sp_power.value():g} % por {a.aquecer:g} s...', flush=True)
        noise_warm = not a.sinal_t and serie is None and not a.sem_detectar_ruido
        if noise_warm:
            win.chk_dual_warm_noise.setChecked(True)
            win.noise_warm_begin()
        pump(a.aquecer)
        if noise_warm:
            win.noise_warm_end()
        print('Warm-up concluído.', flush=True)
    if serie is not None:
        return _headless_serie(win, a, serie, pump)
    if a.sinal_t:
        return _headless_time(win, a, pump)
    win.btn_dual_sweeps_panel.setChecked(False)    # sem o aviso de calibração (janela modal)
    win.tabs.setCurrentIndex(win.tabs.indexOf(win.dual_tab) if hasattr(win, 'dual_tab') else 2)
    pump(3.0)                                      # lock-ins assentam com PWM e frequência novos
    vals = win._dual_planned('F')
    adapt = win.chk_dual_adapt.isChecked()
    cal = (win.cmb_mic_cal.currentText() if win.cmb_mic_cal.count() else '—')
    print(f'Varredura: {vals[0]:g} a {vals[-1]:g} Hz, {len(vals)} pontos; PWM {win.sp_power.value():g} %; '
          + (f'τ adaptativo (τ max {win.dual_tau_w["F"].value():g} s, precisão {win.sp_dual_adapt_tol.value():g} %'
             + (f'; τ fixo por faixa abaixo de {LOWF_FMAX:g} Hz' if win.chk_dual_adapt40.isChecked() else '')
             + (f'; até {win.sp_dual_blocks.value()} médias por ponto' if win.chk_dual_blocks.isChecked() else '') + ')'
             if adapt else f'τ fixo {win.dual_tau_w["F"].value():g} s')
          + (f'; {win.sp_dual_reps.value()} repetições + mediana' if win.sp_dual_reps.value() > 1 else '')
          + (f'; ordem {a.ordem}' + (f' (semente {win.dual_seed_fixed})' if a.ordem == 'embaralhada' else '')
             if a.ordem != 'crescente' else '')
          + f'; amostra "{win.ed_sample.text()}"; célula {win.cmb_cell.currentData()}; calibração: '
          + (cal if win.chk_mic_cal.isChecked() else f'{cal} (não aplicada)')
          + f'; filtro 60 Hz OPT101/INMP441: {"sim" if win.chk_mains.isChecked() else "não"}/'
          + f'{"sim" if win.chk_audio_mains.isChecked() else "não"}' + ('; SIMULADO' if a.simulado else ''), flush=True)
    win.dual_last_csv = None
    win.toggle_dual_sweep('F')
    if not win.dual_active:
        print('ERRO: a varredura não começou (veja as mensagens acima).')
        win.close()
        return 6
    t0 = time.time()
    shown = -1
    try:
        while win.dual_busy():
            pump(0.5)
            n = len(win.dual_results)
            if n != shown:
                shown = n
                if n and len(getattr(win, 'dual_pinfo', [])) == n:
                    li = min(getattr(win, 'dual_last_i', n - 1), n - 1)
                    r, pi = win.dual_results[li], win.dual_pinfo[li]
                    print(f'[{n}/{len(vals)}] {r[0]:g} Hz  S = {r[3] / max(r[1], 1e-30):.4g}  '
                          f'Δφ = {r[5] - r[7]:.2f}°  τ = {pi[0]:.3g} s  {pi[1]:.0f} s'
                          + (f'  (refeito {pi[2]:.0f}×)' if pi[2] else '')
                          + (f'  q {win.dual_nb[li][0]:.2g}, descartado {win.dual_nb[li][1]:.0f} %'
                             if len(getattr(win, 'dual_nb', [])) == n else '')
                          + f'  flutuação S {pi[3]:.2g} %, Δφ {pi[4]:.2g}°   [{win._fmt_time(time.time() - t0)}]', flush=True)
    except KeyboardInterrupt:
        print('Cancelado pelo usuário.')
        win.toggle_dual_sweep(win.dual_src)
        win.close()
        return 130
    csv = getattr(win, 'dual_last_csv', None)
    print(f'Concluída em {win._fmt_time(time.time() - t0)}: {csv}' if csv else 'ERRO: o CSV não foi salvo.')
    _headless_off(win, a, pump)
    win.close()
    return 0 if csv else 7


# Exporta tudo (inclusive nomes com _) para os módulos que fazem import *
__all__ = [_n for _n in dir() if not _n.startswith('__')]
