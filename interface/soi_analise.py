# -*- coding: utf-8 -*-
'''Análise sem Qt: calibração do microfone, ajustes (modelos, ressonância), diagnóstico e leitura dos CSV.

Parte do SOI Controller (antes em soi_controller.py).'''

from soi_const import *  # noqa: F401,F403


# Pico da FFT considerado ausente abaixo desta razão pico/piso (mesmo limiar do alerta de sinal baixo)
FFT_FIT_MIN_SNR_DB = LOW_SIGNAL_SNR_DB


def fit_hann_at(freq, spec, f0, half_window_bins=20):
    '''Ajusta só a amplitude A de A*|W((f - f0)/df)| com f0 fixo (frequência da excitação), por mínimos
    quadrados nos 5 bins em torno de f0; não pula para picos vizinhos. spec em amplitude linear.
    Piso de ruído = mediana do espectro em ±half_window_bins de f0, sem ±4 bins de f0 e sem o lóbulo do DC.
    Devolve (estado, A, piso): estado 'ok', 'baixo' (A/piso abaixo de FFT_FIT_MIN_SNR_DB),
    'fora' (f0 fora da faixa da FFT) ou 'dc' (f0 dentro do lóbulo do DC nesta resolução).'''
    df = freq[1] - freq[0]
    c = f0 / df
    k = int(round(c))
    if f0 <= 0 or k + 2 > len(spec) - 1:
        return 'fora', None, None
    if k < 4:
        return 'dc', None, None
    idx = np.arange(k - 2, k + 3)
    h = hann_kernel(idx - c)
    amp = float(np.dot(spec[idx], h) / np.dot(h, h))
    i = np.arange(max(3, k - half_window_bins), min(len(spec), k + half_window_bins + 1))
    i = i[np.abs(i - k) > 4]
    floor = float(np.median(spec[i])) if i.size else float('nan')
    if not (np.isfinite(amp) and np.isfinite(floor)) or floor <= 0 or amp < floor * 10.0 ** (FFT_FIT_MIN_SNR_DB / 20.0):
        return 'baixo', amp, floor
    return 'ok', amp, floor


def find_flat_band(f, sens, good, tol_db=1.0):
    '''Faixa de resposta plana: o maior trecho contíguo (em log f) de pontos válidos cuja sensibilidade
    fica dentro de ±tol_db em torno da média do trecho (max/min ≤ 2·tol_db). f deve estar em ordem crescente.
    Devolve (i0, i1, ref) com os índices inclusivos e a média geométrica do trecho, ou None.'''
    ldb = 20.0 * np.log10(np.maximum(sens, 1e-30))
    best = None
    for i in range(f.size):
        if not good[i]:
            continue
        lo = hi = ldb[i]
        for j in range(i + 1, f.size):
            if not good[j]:
                break
            lo, hi = min(lo, ldb[j]), max(hi, ldb[j])
            if hi - lo > 2.0 * tol_db:
                break
            span = np.log(f[j] / f[i])
            if best is None or span > best[0]:
                best = (span, i, j)
    if best is None:
        return None
    _, i0, i1 = best
    return i0, i1, float(10.0 ** (np.mean(ldb[i0:i1 + 1]) / 20.0))


def load_mic_calibration(path):
    '''Lê uma calibração CAL_[amostra_]microfone_*.csv. Devolve dict com 'path', 'f', 'ref' (referência),
    'cell' ('OPC' ou 'Camara'), 'verified' (True/False; None nas calibrações antigas), 'verify_txt',
    'sens' (sensibilidade relativa), 'phase' (graus), 'opt_tau' (τ do sensor OPT101 descontado, em s; 0 se
    não houve correção) e 'legacy' (True sem a chave OPT101_tau_sensor_s: calibração feita com o firmware
    anterior ao marcador de modulação corrigido, ou com a correção pelo τ efetivo; a fase não é comparável),
    ou None se o arquivo for inválido.'''
    if not path:
        return None
    opt_tau = None
    meta = {}
    try:
        with open(path, encoding='utf-8') as fh:
            raw = [ln.strip() for ln in fh if ln.strip()]
        for ln in raw:
            m = re.match(r'#\s*OPT101_tau_sensor_s\s*=\s*(\S+)', ln)
            if m:
                opt_tau = float(m.group(1))
            m = re.match(r'#\s*(Referencia|Referencia_ID|Celula|Verificada|Ressonancia_f0_Hz|Metodo)\s*=\s*(.+)$', ln)
            if m:
                meta[m.group(1)] = m.group(2).strip()
            m = re.match(r'#\s*Verificacao:\s*(.+)$', ln)
            if m:
                meta['Verificacao'] = m.group(1).strip()
            m = re.match(r'#\s*Verificacao_2a_referencia:\s*(.+)$', ln)
            if m:
                meta['Verificacao2'] = m.group(1).strip()
        lines = [ln for ln in raw if not ln.startswith('#')]
        head = lines[0].split(',')
        data = np.array([[float(v) for v in ln.split(',')] for ln in lines[1:]])
        f = data[:, head.index('Frequencia_Hz')]
        sens = data[:, head.index('Sensibilidade_Rel')]
        ph = data[:, head.index('Fase_Sistema_Graus')]
        # incerteza da calibração (DP da sensibilidade, absoluto, e da fase do sistema); sem as colunas: None
        sens_e = data[:, head.index('Sensibilidade_Rel_DP')] if 'Sensibilidade_Rel_DP' in head else None
        ph_e = data[:, head.index('Fase_DP')] if 'Fase_DP' in head else None
        ok = (data[:, head.index('Valido')] > 0) & (sens > 0)
        # Calibração por duas amostras: Concorda = 1 onde a razão A/B foi constante (sem a coluna: tudo concorda)
        agree = data[:, head.index('Concorda')] > 0 if 'Concorda' in head else None
    except (OSError, ValueError, IndexError):
        return None
    if ok.sum() < 2:
        return None
    k = np.argsort(f[ok])
    # Sem as chaves (calibrações até a 2.0.0): folha de Al em OPC, sem verificação registrada
    ver = meta.get('Verificada')
    return {'path': path, 'f': f[ok][k], 'sens': sens[ok][k], 'phase': ph[ok][k],
            'opt_tau': opt_tau or 0.0, 'legacy': opt_tau is None,
            'ref': meta.get('Referencia', CAL_REFS['al_opc']['name']), 'cell': meta.get('Celula', 'OPC'),
            'ref_id': meta.get('Referencia_ID', 'al_opc'), 'verify2': meta.get('Verificacao2', ''),
            'f0': float(meta['Ressonancia_f0_Hz']) if meta.get('Ressonancia_f0_Hz', '').replace('.', '', 1).isdigit() else None,
            'agree': None if agree is None else agree[ok][k],
            'sens_rel_e': None if sens_e is None else np.abs(sens_e[ok][k]) / sens[ok][k],
            'phase_e': None if ph_e is None else np.abs(ph_e[ok][k]),
            'method': meta.get('Metodo', ''),
            'verified': None if ver is None else ver.lower().startswith('s'),
            'verify_txt': meta.get('Verificacao', '').split(' - problemas: ')[-1] if ver and not ver.lower().startswith('s') else ''}


CAL_VER_DB = 1.5        # desvio rms máximo (dB) da 2ª referência corrigida em relação a f^-n
CAL_VER_DEG = 10.0      # desvio rms máximo (graus) da fase corrigida em relação a uma constante


def verify_with_second_ref(f, s, dphi, n_exp):
    '''Verificação da calibração por uma segunda referência: com a calibração aplicada, a varredura de outra
    referência deve dar S ∝ f^-n_exp com fase constante. Devolve dict ('ok', 'n', 'n_err', 'rms_db',
    'rms_deg', 'npts', 'fmin', 'fmax', 'text') ou None (menos de 5 pontos).'''
    f, s, dphi = (np.asarray(v, dtype=np.float64) for v in (f, s, dphi))
    ok = (f > 0) & (s > 0) & np.isfinite(s) & np.isfinite(dphi)
    f, s, dphi = f[ok], s[ok], dphi[ok]
    if f.size < 5:
        return None
    lf, ls = np.log10(f), np.log10(s)
    c, cov = np.polyfit(lf, ls, 1, cov=True)
    n, n_err = float(-c[0]), float(np.sqrt(cov[0, 0]))
    r = ls + n_exp * lf
    rms_db = float(20.0 * np.std(r - np.median(r)))
    ph = np.degrees(np.angle(np.exp(1j * np.radians(dphi - np.degrees(np.angle(np.mean(np.exp(1j * np.radians(dphi)))))))))
    rms_deg = float(np.sqrt(np.mean(ph ** 2)))
    good = abs(n - n_exp) <= CAL_N_TOL and rms_db <= CAL_VER_DB and rms_deg <= CAL_VER_DEG
    text = (f'n = {n:.2f} ± {n_err:.2f} (esperado {n_exp:g}), desvio de f<sup>−{n_exp:g}</sup> = {rms_db:.1f} dB rms, '
            f'fase constante ± {rms_deg:.0f}° rms ({f.size} pontos, {fmt_freq(f.min())}–{fmt_freq(f.max())})')
    return {'ok': bool(good), 'n': n, 'n_err': n_err, 'rms_db': rms_db, 'rms_deg': rms_deg, 'npts': int(f.size),
            'fmin': float(f.min()), 'fmax': float(f.max()), 'text': text}


# ------------------------------------------------------------ Calibração por duas amostras
# A calibração usa duas amostras de materiais diferentes, medidas na mesma montagem. As duas seguem
# S = K·H(f)·f^-n (K da amostra, H do sistema), então a razão S_A/S_B = K_A/K_B é uma constante complexa
# onde as duas estão no regime previsto. Essa razão plana é a verificação; a calibração é
# M(f) = √(S_A·S_B)·f^n. Câmara: metais opacos e termicamente grossos (n = 1, não depende de α nem de L).
# OPC: folhas termicamente finas (n = 1,5). α em m²/s; L = espessura típica em m.
CAL_MATERIALS = {
    'al': {'name': 'Alumínio', 'cell': 'Camara', 'alpha': 9.7e-5, 'L': 5e-3, 'sim_k': 0.6,
           'tips': 'Bloco ou placa de alumínio de vários mm, com a face do laser lixada fosca (#400) e limpa. '
                   'Reflete muito: sinal menor que o do inox.'},
    'inox': {'name': 'Inox (304/316)', 'cell': 'Camara', 'alpha': 4.0e-6, 'L': 2e-3, 'sim_k': 1.0,
             'tips': 'Placa de inox austenítico (304, 316, 316L: a liga não importa) de 1 mm ou mais, face lixada '
                     'fosca. Bom sinal, estável e fácil de achar.'},
    'ti': {'name': 'Titânio', 'cell': 'Camara', 'alpha': 9.3e-6, 'L': 3e-3, 'sim_k': 1.1,
           'tips': 'Placa de titânio de 1,5 mm ou mais, face lixada fosca. Sinal alto e óxido estável. '
                   'α parecido com o do inox: faça o par com Al ou Ni.'},
    'ni': {'name': 'Níquel', 'cell': 'Camara', 'alpha': 2.3e-5, 'L': 3e-3, 'sim_k': 0.5,
           'tips': 'Placa de níquel de 2,5 mm ou mais, face lixada fosca. α intermediário (entre Al e inox).'},
    'latao': {'name': 'Latão', 'cell': 'Camara', 'alpha': 3.4e-5, 'L': 5e-3, 'sim_k': 0.5,
              'tips': 'Bloco de latão de 3 mm ou mais, face lixada fosca. Barato e fácil de achar.'},
    'grafite': {'name': 'Grafite', 'cell': 'Camara', 'alpha': 1.0e-4, 'L': 5e-3, 'sim_k': 2.5,
                'tips': 'Placa ou eletrodo de grafite de 5 mm ou mais. Absorve muito: bastante sinal.'},
    'al12': {'name': 'Folha de Al 12 µm', 'cell': 'OPC', 'alpha': 9.7e-5, 'L': 12e-6, 'sim_k': 1.0,
             'tips': 'Papel alumínio comum, bem esticado e vedado nas bordas da abertura (graxa ou fita). '
                     'O laser incide na face de fora.'},
    'al25': {'name': 'Folha de Al 25 µm', 'cell': 'OPC', 'alpha': 9.7e-5, 'L': 25e-6, 'sim_k': 0.5,
             'tips': 'Papel alumínio reforçado ("heavy duty"), esticado e vedado como a folha comum.'},
    'cu35': {'name': 'Folha de Cu 35 µm', 'cell': 'OPC', 'alpha': 1.1e-4, 'L': 35e-6, 'sim_k': 0.4,
             'tips': 'Fita ou folha de cobre, sem adesivo na área iluminada, esticada e vedada nas bordas.'},
}
CAL_CELL_N = {'Camara': 1.0, 'OPC': 1.5}     # expoente esperado de cada célula
CAL_PAIR_MIN_RATIO = 3.0                     # as duas amostras devem diferir pelo menos isso (α ou f_c)
CAL_F0_TOL = 0.03                            # ressonâncias de A e B devem coincidir em ±3 %
RES_SHIFT_TOL = 0.05     # f0 da medida x f0 da calibração: acima de 5 % (ou 1,5 passo da varredura), "ressonância deslocada"
RES_SHIFT_MSG = 'Ressonância deslocada: cheque a montagem da célula'


def cal_materials(cell):
    '''Chaves dos materiais de calibração da célula, na ordem da tabela.'''
    return [k for k, m in CAL_MATERIALS.items() if m['cell'] == cell]


def cal_pair_check(a, b):
    '''O par (a, b) serve para a calibração? Na câmara compara α (o regime de amostra grossa depende de α);
    no OPC compara f_c = α/(πL²) das folhas típicas (o regime de folha fina depende de L²/α).
    Devolve (ok, motivo).'''
    if a == b:
        return False, 'mesmo material da amostra A: a razão não testa nada'
    ma, mb = CAL_MATERIALS[a], CAL_MATERIALS[b]
    if ma['cell'] != mb['cell']:
        return False, 'material de outra célula'
    if ma['cell'] == 'OPC':
        qa, qb, what = ma['alpha'] / ma['L'] ** 2, mb['alpha'] / mb['L'] ** 2, 'f_c = α/(πL²)'
    else:
        qa, qb, what = ma['alpha'], mb['alpha'], 'α'
    r = max(qa, qb) / min(qa, qb)
    if r < CAL_PAIR_MIN_RATIO:
        return False, f'{what} parecido com o de {ma["name"]} (só {r:.1f}×; mínimo {CAL_PAIR_MIN_RATIO:g}×)'
    return True, f'{what} {r:.0f}× diferente do de {ma["name"]}'


def cal_thickness_check(key, L, fmin, fmax):
    '''Confere a espessura L (m) da amostra na faixa da varredura. Câmara: L ≥ 2μ na frequência mínima,
    μ = √(α/πf). OPC: f_c = α/(πL²) ≥ 10× a frequência máxima. Devolve '' (ok) ou o aviso.'''
    m = CAL_MATERIALS[key]
    if L <= 0:
        return ''
    if m['cell'] == 'OPC':
        fc = m['alpha'] / (np.pi * L * L)
        if fc < 10.0 * fmax:
            return (f'{m["name"]}: f_c = {fmt_freq(fc)} < 10× {fmt_freq(fmax)}; a folha deixa de ser termicamente '
                    'fina no alto da faixa')
        return ''
    f_ok = 4.0 * m['alpha'] / (np.pi * L * L)          # L = 2μ(f)
    if fmin < f_ok:
        return (f'{m["name"]} com {L * 1e3:g} mm é termicamente grossa só acima de {fmt_freq(f_ok)} '
                f'(L ≥ 2μ); a varredura começa em {fmt_freq(fmin)}')
    return ''


def cal_sweep_arrays(rows, tau_sensor=0.0, excluded=(), snr_min_db=LOW_SIGNAL_SNR_DB):
    '''Varredura em frequência do Modo Duplo (linhas de dual_results ou de load_dual_csv) pronta para a
    calibração, como em _show_dual_results: S = R_INMP441/R_OPT101 e Δφ = φ_INMP441 − φ_OPT101 desenrolada,
    em ordem de frequência, com o OPT101 corrigido pelo τ do sensor (s). 'valid' = SNR suficiente e não
    excluído com clique.'''
    res = np.array(rows, dtype=float).reshape(-1, 9)
    keep = np.ones(len(res), dtype=bool)
    keep[[i for i in excluded if i < len(res)]] = False
    k = np.argsort(res[:, 0])
    res, keep = res[k], keep[k]
    x, ro, ro_e, ra, ra_e, pa, pa_e, po, po_e = res.T
    if tau_sensor > 0:
        xs = 2.0 * np.pi * np.array([actual_mod_freq(v) for v in x]) * tau_sensor
        po = po + np.degrees(np.arctan(xs))
        ro, ro_e = ro * np.sqrt(1.0 + xs * xs), ro_e * np.sqrt(1.0 + xs * xs)
    ok = (ro > 0) & (ra > 0)
    s = np.where(ok, ra / np.where(ok, ro, 1.0), np.nan)
    s_rel = np.sqrt((ra_e / np.maximum(ra, 1e-30)) ** 2 + (ro_e / np.maximum(ro, 1e-30)) ** 2)
    dphi = np.degrees(np.unwrap(np.radians(wrap_deg(pa - po))))
    snr = ra / np.maximum(ra_e, 1e-30)
    valid = ok & keep & (snr >= 10.0 ** (snr_min_db / 20.0))
    return {'f': x, 's': s, 's_rel': s_rel, 'dphi': dphi, 'dphi_e': np.hypot(pa_e, po_e), 'valid': valid}


def make_two_sample_cal(A, B, n, flat_tol=1.0):
    '''Calibração a partir de duas varreduras (dicts de cal_sweep_arrays) de amostras diferentes na mesma
    montagem. Procura a maior faixa em que a razão complexa R = S_A/S_B é constante (find_ref_band com
    n = 0: inclinação, desvio em dB e fase), e calcula M = √(S_A·S_B)·fⁿ normalizada pela faixa plana
    (±flat_tol dB) e a fase do sistema = média das duas Δφ − φ0. Devolve dict ou None (menos de 5 pontos
    válidos em comum).'''
    f = A['f']
    sA, dA, eA, rA, vA = A['s'], A['dphi'], A['dphi_e'], A['s_rel'], A['valid']
    if B['f'].size == f.size and np.allclose(B['f'], f, rtol=1e-4):
        sB, dB, eB, rB, vB = B['s'], B['dphi'], B['dphi_e'], B['s_rel'], B['valid']
    else:                                          # grades diferentes: B interpolada em log f na grade de A
        bv = B['valid'] & np.isfinite(B['s'])
        if bv.sum() < 2:
            return None
        lf, lfb = np.log(f), np.log(B['f'][bv])
        sB = np.exp(np.interp(lf, lfb, np.log(B['s'][bv])))
        dB = np.interp(lf, lfb, B['dphi'][bv])
        eB = np.interp(lf, lfb, B['dphi_e'][bv])
        rB = np.interp(lf, lfb, B['s_rel'][bv])
        vB = (f >= B['f'][bv].min() * 0.999) & (f <= B['f'][bv].max() * 1.001)
    v = vA & vB & np.isfinite(sA) & np.isfinite(sB)
    if v.sum() < 5:
        return None
    lr = np.log(sA) - np.log(sB)
    dd = dA - dB
    dd -= 360.0 * np.round(np.median(dd[v]) / 360.0)
    band = find_ref_band(f[v], np.exp(lr[v]), dd[v], 0.0)
    if band is None:
        return None
    dec = float(np.log10(band['f_hi'] / band['f_lo']))
    ok = bool(band['ok'] and dec >= CAL_MIN_DECADES)
    agree = v & (f >= band['f_lo'] * 0.999) & (f <= band['f_hi'] * 1.001)
    # Desvio de cada ponto em relação à razão constante: metade vai para cada amostra (incerteza da média)
    res_l = lr - band['lnA']
    res_p = wrap_deg(dd - band['phi0'])
    m = np.sqrt(sA * sB) * f ** n
    m_ref = float(np.median(m[v]))
    flat = find_flat_band(f, m / m_ref, v, flat_tol)
    if flat is not None and flat[1] > flat[0]:
        m_ref *= flat[2]
        f_lo, f_hi = float(f[flat[0]]), float(f[flat[1]])
        in_flat = (f >= f_lo) & (f <= f_hi)
        flat_txt = f'Faixa plana (±{flat_tol:g} dB): {f_lo:g} a {f_hi:g} Hz'
    else:
        in_flat = np.zeros(f.size, dtype=bool)
        flat_txt = f'Faixa plana (±{flat_tol:g} dB): não encontrada (normalizada pela mediana)'
    sens = m / m_ref
    sens_e = sens * np.sqrt((0.5 * np.hypot(rA, rB)) ** 2 + (0.5 * res_l) ** 2)
    ph = 0.5 * (dA + dB)
    ref_ph = in_flat & v if (in_flat & v).any() else v
    phi0 = float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(ph[ref_ph]))))))
    ph = ph - phi0
    ph -= 360.0 * np.round(np.median(ph[ref_ph]) / 360.0)
    ph_e = np.sqrt((0.5 * np.hypot(eA, eB)) ** 2 + (0.5 * res_p) ** 2)
    f0a, f0b = cell_resonance_f0(f[vA], sA[vA]), cell_resonance_f0(f[vB], sB[vB])
    probs = []
    if not band['ok']:
        probs.append('a razão A/B não fica constante em nenhuma faixa larga')
    elif dec < CAL_MIN_DECADES:
        probs.append(f'a razão A/B só é constante em {dec:.1f} década(s) (mínimo {CAL_MIN_DECADES:g})')
    f0_txt = ''
    if f0a and f0b:
        df0 = abs(f0a / f0b - 1.0)
        f0_txt = f'ressonância A {fmt_freq(f0a)}, B {fmt_freq(f0b)}'
        if df0 > CAL_F0_TOL:
            f0_txt += f' (diferem {df0 * 100:.0f} %: as amostras têm alturas diferentes?)'
    text = (f'razão A/B constante de {band["f_lo"]:.4g} a {band["f_hi"]:.4g} Hz ({dec:.1f} década(s); mínimo '
            f'{CAL_MIN_DECADES:g}): inclinação {-band["n"]:+.2f} ± {band["n_err"]:.2f}, {band["rms_db"]:.1f} dB rms, '
            f'fase ± {band["rms_deg"]:.0f}° rms; |A/B| = {np.exp(band["lnA"]):.3g}, Δφ = {band["phi0"]:+.1f}°')
    return {'ok': ok, 'f': f, 'sens': sens, 'sens_e': sens_e, 'phase': ph, 'phase_e': ph_e, 'valid': v,
            'in_flat': in_flat, 'agree': agree, 'flat_txt': flat_txt, 'band': band, 'decades': dec,
            'ratio': float(np.exp(band['lnA'])), 'ratio_deg': float(band['phi0']), 'ratio_s': np.exp(lr),
            'ratio_p': dd, 'f0a': f0a, 'f0b': f0b, 'f0_txt': f0_txt, 'problems': probs, 'text': text, 'n': n}


def write_two_sample_cal(path, cal, a, b, cell, file_a='', file_b='', tau_sensor=0.0, sweep_txt='', notes=()):
    '''Grava a calibração de duas amostras no formato CAL_ (lido por load_mic_calibration), com as chaves do
    método e a coluna Concorda (1 dentro da faixa em que a razão A/B é constante).'''
    na, nb = CAL_MATERIALS[a]['name'], CAL_MATERIALS[b]['name']
    n = cal['n']
    band = cal['band']
    verdict = ('aprovada - ' if cal['ok'] else 'reprovada - ') + f'{na} × {nb}: {cal["text"]}'
    if cal['problems']:
        verdict += ' - problemas: ' + '; '.join(cal['problems'])
    f = cal['f']
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        fh.write(f"# Calibração relativa do microfone + célula - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"# Método: duas amostras ({na} e {nb}), S teórico ∝ f^-{n:g} nas duas; M(f) = √(S_A·S_B)*f^{n:g}, "
                 "normalizada pela média da faixa plana (ou pela mediana, se não houver)\n"
                 f"# Metodo = duas_amostras\n"
                 f"# Referencia = {na} × {nb}\n# Referencia_ID = par_{a}_{b}\n# Celula = {cell}\n"
                 f"# Expoente_teorico = {n:g}\n"
                 f"# Amostra_A = {a} ({os.path.basename(file_a) or 'varredura sem arquivo'})\n"
                 f"# Amostra_B = {b} ({os.path.basename(file_b) or 'varredura sem arquivo'})\n"
                 f"# Razao_AB = {cal['ratio']:.4g}, {cal['ratio_deg']:.2f}\n"
                 f"# Faixa_concordancia_Hz = {band['f_lo']:g} a {band['f_hi']:g}\n"
                 + (f"# Ressonancia_f0_Hz = {cal['f0a']:.1f}\n" if cal['f0a'] else '')
                 + f"# Verificada = {'sim' if cal['ok'] else 'nao'}\n"
                 f"# Verificacao_2a_referencia: {verdict}\n"
                 + (f"# Ressonancias: {cal['f0_txt']}\n" if cal['f0_txt'] else '')
                 + (f"# {sweep_txt}\n" if sweep_txt else '')
                 + ''.join(f'# {t}\n' for t in notes)
                 + "# Fase_Sistema = média de Δφ(INMP441 - OPT101) das duas amostras - φ0 (φ0 = fase média na faixa plana); "
                 "Valido = 0 para SNR baixo ou ponto excluído; Concorda = 1 dentro da faixa em que a razão A/B é constante\n"
                 f"# {cal['flat_txt']}\n"
                 f"# OPT101_tau_sensor_s = {tau_sensor:.6g}\n")
        fh.write('Frequencia_Hz,Sensibilidade_Rel,Sensibilidade_Rel_DP,Sensibilidade_Fit,Fase_Sistema_Graus,'
                 'Fase_DP,Valido,Faixa_Plana,No_Ajuste,Concorda\n')
        for i in range(f.size):
            s = cal['sens'][i] if np.isfinite(cal['sens'][i]) else 0.0
            fh.write(f"{f[i]:.3f},{s:.6g},{cal['sens_e'][i]:.4g},{s:.6g},{cal['phase'][i]:.3f},"
                     f"{cal['phase_e'][i]:.3f},{int(cal['valid'][i])},{int(cal['in_flat'][i])},"
                     f"{int(cal['in_flat'][i])},{int(cal['agree'][i])}\n")
    return verdict


def mark_calibration_verified(path, ok, text):
    '''Regrava o cabeçalho da calibração com o resultado da verificação pela segunda referência.'''
    with open(path, encoding='utf-8') as fh:
        lines = fh.read().splitlines()
    out, done = [], False
    for ln in lines:
        if re.match(r'#\s*Verificada\s*=', ln):
            ln = f"# Verificada = {'sim' if ok else 'nao'}"
            done = True
        elif re.match(r'#\s*Verificacao_2a_referencia:', ln):
            continue
        out.append(ln)
        if re.match(r'#\s*Verificada\s*=', ln):
            out.append(f'# Verificacao_2a_referencia: {text}')
    if not done:
        out.insert(1, f"# Verificada = {'sim' if ok else 'nao'}")
        out.insert(2, f'# Verificacao_2a_referencia: {text}')
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write('\n'.join(out) + '\n')


DUAL_COLUMNS = ('OPT101_R', 'OPT101_R_DP', 'INMP441_R', 'INMP441_R_DP', 'INMP441_Fase_Graus',
                'INMP441_Fase_DP', 'OPT101_Fase_Graus', 'OPT101_Fase_DP')


# colunas por ponto do Modo Duplo (2.3.0): τ do lock-in, tempo gasto no ponto (espera + média, com os refazimentos),
# vezes que o ponto foi refeito pelo τ adaptativo e flutuação de S e de Δφ durante a média
DUAL_POINT_COLUMNS = ('Tau_s', 'Tempo_ponto_s', 'Refeito', 'Flutuacao_S_Pct', 'Flutuacao_Fase_Graus')
# deriva na última média do ponto (2ª metade - 1ª): S e Δφ, e R do OPT101 e do microfone em separado (opcionais ao ler)
DUAL_DRIFT_COLUMNS = ('Deriva_S_Pct', 'Deriva_Fase_Graus', 'Deriva_OPT101_Pct', 'Deriva_INMP441_Pct')


def load_dual_csv(path):
    '''Lê um CSV do Modo Duplo (varredura em frequência ou casada em PWM, inclusive os formatos antigos).
    Devolve (tipo 'F' ou 'P', linhas (valor, 8 colunas de DUAL_COLUMNS), parâmetros da varredura).
    Levanta ValueError se o arquivo não for do Modo Duplo.'''
    with open(path, encoding='utf-8') as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    i_head = next((i for i, ln in enumerate(lines) if not ln.startswith('#')), None)
    if i_head is None:
        raise ValueError('arquivo sem dados')
    cols = lines[i_head].split(',')
    kind = {'Frequencia_Hz': 'F', 'PWM_Pct': 'P', 'Tempo_s': 'T'}.get(cols[0])
    if kind is None or not all(c in cols for c in DUAL_COLUMNS):
        raise ValueError('não é uma varredura do Modo Duplo (colunas de OPT101 e INMP441 não encontradas)')
    idx = [0] + [cols.index(c) for c in DUAL_COLUMNS]
    rows = []
    for ln in lines[i_head + 1:]:
        v = ln.split(',')
        rows.append(tuple(float(v[i]) for i in idx))
    if not rows:
        raise ValueError('arquivo sem pontos')
    header = '\n'.join(lines[:i_head])
    name = os.path.basename(path)

    def num(pattern, *texts):
        for t in texts:
            m = re.search(pattern, t)
            if m:
                return float(m.group(1))
        return None
    mode = re.search(r'# Medida:\s*([^;\n]+)', header)
    params = {'kind': kind, 'values': [r[0] for r in rows],
              # nome do arquivo primeiro (mesmo formato desde o início), cabeçalho como alternativa
              'pwm': num(r'_pwm([\d.]+)_', name) if kind in ('F', 'T') else None,
              'freq': num(r'_f([\d.]+)Hz_', name) if kind in ('P', 'T') else None,
              'mode': mode.group(1).strip() if mode else 'não registrada',
              'tau': num(r'tau = ([\d.eE+-]+) s \(integração longa\)', header)}
    if re.search(r'# Modulacao = (optica|externa)', header):
        params['mod'] = 'optica'
    pcols = [c for c in DUAL_POINT_COLUMNS if c in cols]
    if len(pcols) == len(DUAL_POINT_COLUMNS):     # τ, tempo e flutuação por ponto (2.3.0)
        pidx = [cols.index(c) for c in DUAL_POINT_COLUMNS] + [cols.index(c) if c in cols else -1 for c in DUAL_DRIFT_COLUMNS]
        params['pinfo'] = [tuple(float(v) if v not in ('', 'nan') else float('nan')
                                 for v in ((ln.split(',')[i] if i >= 0 else 'nan') for i in pidx))
                           for ln in lines[i_head + 1:]]
    for key, lab in (('t_start', 'Inicio'), ('t_end', 'Fim')):
        mt = re.search(rf'{lab} = (\d{{4}}-\d\d-\d\d \d\d:\d\d:\d\d)', header)
        if mt:
            params[key] = datetime.strptime(mt.group(1), '%Y-%m-%d %H:%M:%S')
    m = re.search(r'tau adaptativo \(precisão ([\d.]+) %, tau (?:inicial|max) ([\d.]+) s', header)
    if m:
        params['adapt'] = (float(m.group(1)), float(m.group(2)))
    refine = re.findall(r'# (Refino da ressonância:[^\n]+)', header)
    if refine:
        params['refine'] = refine[-1]
    if kind == 'F' and params['pwm'] is None:
        params['pwm'] = num(r'PWM\s*([\d.]+)\s*%', header) or 0.0
    if kind == 'P' and params['freq'] is None:
        params['freq'] = num(r'modulação\s*([\d.]+)\s*Hz', header) or 0.0
    return kind, rows, params


def list_mic_calibrations(folder=None):
    '''Calibrações válidas da pasta Medidas, da mais recente para a mais antiga. A data vem do nome
    (_AAAAMMDD_HHMMSS.csv), que sobrevive a cópias e sincronização; sem ela, a data de modificação.'''
    folder = folder or MEDIDAS_DIR
    try:
        files = [os.path.join(folder, n) for n in os.listdir(folder)
                 if n.startswith('CAL_') and '_microfone_' in n and n.endswith('.csv')]
    except OSError:
        return []

    def stamp(path):
        m = re.search(r'_(\d{8}_\d{6})\.csv$', path)
        return m.group(1) if m else datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y%m%d_%H%M%S')
    return [p for p in sorted(files, key=stamp, reverse=True) if load_mic_calibration(p) is not None]


def poly_fit_text(x, y, deg):
    '''Ajuste polinomial y = c0 + c1·x + … de grau deg (1 a 3). Devolve (coeficientes no formato de np.polyval,
    texto com os coeficientes ± erro, R² e o desvio relativo máximo da reta em relação aos pontos) ou None.'''
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < deg + 2:
        return None
    try:
        coef, cov = np.polyfit(x, y, deg, cov=True)
    except (ValueError, np.linalg.LinAlgError):
        try:
            coef, cov = np.polyfit(x, y, deg), None
        except (ValueError, np.linalg.LinAlgError):
            return None
    yf = np.polyval(coef, x)
    ss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum((y - yf) ** 2)) / ss if ss > 0 else float('nan')
    err = np.sqrt(np.abs(np.diag(cov))) if cov is not None and np.all(np.isfinite(cov)) else np.full(deg + 1, np.nan)
    terms = []
    for i, (c, e) in enumerate(zip(coef[::-1], err[::-1])):
        terms.append(f'c{i} = {c:.4g}' + (f' ± {e:.2g}' if np.isfinite(e) else ''))
    rng = float(np.max(np.abs(y))) or 1.0
    dev = 100.0 * float(np.max(np.abs(y - yf))) / rng
    return coef, ('y = ' + ' + '.join(['c0'] + [f'c{i}·x' + (f'<sup>{i}</sup>' if i > 1 else '') for i in range(1, deg + 1)])
                  + ': ' + ', '.join(terms) + f'; R² = {r2:.5f}; desvio máximo {dev:.2g} % do maior valor')


def circ_stats_deg(p):
    '''Média e desvio-padrão circulares de fases em graus (a média aritmética falha perto de ±180°).'''
    u = np.exp(1j * np.radians(np.asarray(p, dtype=np.float64)))
    m = u.mean()
    rbar = min(max(abs(m), 1e-12), 1.0)
    return float(np.degrees(np.angle(m))), float(np.degrees(np.sqrt(-2.0 * np.log(rbar))))


def fit_sweep(x, y, model):
    '''Ajuste da varredura. model: 'pow' -> y = A*x^n (mínimos quadrados em log-log, só pontos > 0);
    'lin' -> y = a + b*x. Devolve (função, texto) ou None.'''
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if model == 'pow':
        ok = (x > 0) & (y > 0)
        if ok.sum() < 2:
            return None
        lx, ly = np.log10(x[ok]), np.log10(y[ok])
        (n, la), cov = np.polyfit(lx, ly, 1, cov=True) if ok.sum() > 3 else (np.polyfit(lx, ly, 1), None)
        r2 = 1.0 - np.sum((ly - (la + n * lx)) ** 2) / max(np.sum((ly - ly.mean()) ** 2), 1e-300)
        a = 10.0 ** la
        sn = f' ± {np.sqrt(cov[0, 0]):.3f}' if cov is not None else ''
        return (lambda xx: a * np.power(xx, n)), f'y = A·x<sup>n</sup><br>n = {n:.3f}{sn}<br>A = {a:.4g}<br>R² (log) = {r2:.4f}'
    if x.size < 2:
        return None
    (b, a), cov = np.polyfit(x, y, 1, cov=True) if x.size > 3 else (np.polyfit(x, y, 1), None)
    r2 = 1.0 - np.sum((y - (a + b * x)) ** 2) / max(np.sum((y - y.mean()) ** 2), 1e-300)
    sb = f' ± {np.sqrt(cov[0, 0]):.3g}' if cov is not None else ''
    return (lambda xx: a + b * xx), f'y = a + b·x<br>b = {b:.4g}{sb}<br>a = {a:.4g}<br>R² = {r2:.4f}'


def fit_pa_standard(f, s, s_rel, dphi, dphi_e, snr, snr_min, use_phase=True, n_exp=None, ref_name=None):
    '''Fit do padrão de calibração (referência escolhida; n livre) na varredura em frequência normalizada.
    Com n_exp, o texto compara o n ajustado com o esperado da referência ref_name.
    Amplitude S(f) = A·f^-n·H(f), H = passa-altas de 1ª ordem de corte fc (microfone/célula);
    fase Δφ(f) = φ0 + atan(fc/f) - 360°·f·td (td = atraso de propagação acústica).
    Pontos com SNR < snr_min ou resíduo > 3σ ficam fora do ajuste e da faixa confiável.
    Devolve dict com 'amp', 'phase' (funções), 'good' (máscara) e 'text', ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    ls = np.log(np.asarray(s, dtype=np.float64))
    sig_l = np.maximum(np.asarray(s_rel, dtype=np.float64), 0.01)
    dphi = np.asarray(dphi, dtype=np.float64)
    sig_p = np.maximum(np.asarray(dphi_e, dtype=np.float64), 1.0)
    lo, hi = np.log(f.min() / 100.0), np.log(f.max())

    def amp_l(p, ff):
        x = ff / np.exp(p[2])
        return p[0] - p[1] * np.log(ff) + np.log(x) - 0.5 * np.log1p(x * x)

    def phase(p, ff):
        return p[4] + np.degrees(np.arctan(np.exp(p[2]) / ff)) - 360.0 * ff * p[3]

    def resid(p, m):
        r = (amp_l(p, f[m]) - ls[m]) / sig_l[m]
        if use_phase:
            r = np.concatenate((r, wrap_deg(phase(p, f[m]) - dphi[m]) / sig_p[m]))
        return r

    good = np.asarray(snr) >= snr_min
    if good.sum() < 4:
        good = np.ones(f.size, dtype=bool)
    k = np.argsort(f)
    n0 = -np.polyfit(np.log(f[k][-max(2, f.size // 2):]), ls[k][-max(2, f.size // 2):], 1)[0]
    p0 = np.array([ls.max() + np.log(f.max()) * n0, float(np.clip(n0, 0.0, 3.0)), np.log(f.min() / 3.0), 0.0, 0.0])
    p0[2] = np.clip(p0[2], lo, hi)
    if use_phase:
        # Ponto de partida da fase: Δφ desenrolada ≈ a + b·log10 f + c·f -> td = -c/360; evita mínimos
        # locais criados pela volta de ±180°
        un = np.degrees(np.unwrap(np.radians(dphi[k])))
        c = np.linalg.lstsq(np.c_[np.ones(f.size), np.log10(f[k]), f[k]], un, rcond=None)[0]
        p0[3] = float(np.clip(-c[2] / 360.0, -0.0099, 0.0099))
        p0[4] = circ_stats_deg(dphi - np.degrees(np.arctan(np.exp(p0[2]) / f)) + 360.0 * f * p0[3])[0]
    bounds = ([-np.inf, 0.0, lo, -0.01, -720.0], [np.inf, 3.0, hi, 0.01, 720.0])
    sol = None
    for _ in range(2):                 # 2ª passada sem os pontos com resíduo > 3σ
        if good.sum() < 4:
            return None
        sol = least_squares(resid, p0, bounds=bounds, args=(good,))
        p0 = sol.x
        r_all = np.abs((amp_l(sol.x, f) - ls) / sig_l)
        if use_phase:
            r_all = np.maximum(r_all, np.abs(wrap_deg(phase(sol.x, f) - dphi)) / sig_p)
        # Outlier: resíduo > 3x a dispersão típica (MAD), não só 3σ estatístico, que ignora erros sistemáticos
        thr = 3.0 * max(1.0, 1.4826 * float(np.median(r_all[good])))
        new_good = good & (r_all <= thr)
        if new_good.sum() == good.sum() or new_good.sum() < 4:
            break
        good = new_good
    if sol is None or not sol.success:
        return None
    p = sol.x
    dof = max(1, sol.fun.size - (5 if use_phase else 3))
    chi2 = float(np.sum(sol.fun ** 2) / dof)
    J = sol.jac if use_phase else sol.jac[:, :3]
    try:
        cov = np.linalg.pinv(J.T @ J) * max(chi2, 1.0)
        err = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    except np.linalg.LinAlgError:
        err = np.full(J.shape[1], np.nan)
    fc, fc_err = np.exp(p[2]), np.exp(p[2]) * err[2]
    fc_txt = (f'Corte PAS = {fc:.3g} ± {fc_err:.2g} Hz' if p[2] > lo + 0.05
              else f'Corte PAS < {f.min():.3g} Hz')
    # Classificação pelo expoente: ≈1 amostra sobre suporte espesso, ≈1,5 folha fina livre (capacidade térmica)
    if n_exp is not None:
        ok_n = abs(p[1] - n_exp) <= CAL_N_TOL
        amostra = (f'{ref_name or "Referência"}: n esperado {n_exp:g} '
                   + ('✓' if ok_n else '<span style="color:#d00000;">⚠</span>'))
    elif 0.75 <= p[1] < 1.25:
        amostra = 'Amostra fina sobre suporte espesso'
    elif 1.25 <= p[1] < 1.75:
        amostra = 'Amostra fina livre'
    else:
        amostra = 'Fora dos regimes padrão (n ≈ 1 ou 1,5)'
    text = (f'<b>Fit padrão:</b> <b>{amostra}</b> &nbsp; n = {p[1]:.2f} ± {err[1]:.2f} &nbsp; {fc_txt}')
    if use_phase:
        text += (f' &nbsp; Atraso do sistema (td) = {p[3] * 1e6:.0f} ± {err[3] * 1e6:.0f} µs')
    text += (f'<br>Faixa confiável: {f[good].min():.4g} a {f[good].max():.4g} Hz '
             f'({int(good.sum())} de {f.size} pontos); x vermelho = ponto excluído')
    return {'amp': lambda ff: np.exp(amp_l(p, np.asarray(ff, dtype=np.float64))),
            'phase': (lambda ff: phase(p, np.asarray(ff, dtype=np.float64))) if use_phase else None,
            'good': good, 'text': text, 'params': p, 'errors': err, 'chi2': chi2}


# Referências de calibração do microfone (aba Modo Duplo, painel "Calibração do microfone").
# Todas têm fase teórica constante na faixa de uso; muda o expoente n de S ∝ f^-n e a célula em que valem.
# Rosencwaig–Gersho (célula fechada, amostra dentro): amostra opaca dá S ∝ f^-1 seja termicamente fina ou
# grossa. OPC (amostra fecha a célula, detecção traseira): folha termicamente fina dá S ∝ f^-1,5, enquanto
# f << f1 = α/(πL²).
CELLS = {'Camara': 'Câmara'}      # 2.5.0: só a Câmara (modo OPC removido, Marcos 25/11)
CELL_TIPS = {'OPC': 'OPC: a amostra fecha a abertura da célula; a luz chega pelo lado de fora e o microfone fica do outro lado.',
             'Camara': 'Câmara: a amostra fica dentro da célula, iluminada através de uma janela de vidro.'}
CAL_REFS = {
    'al_opc': {'name': 'Folha de Al fina (modo OPC)', 'cell': 'OPC', 'n': 1.5, 'L_um': 12.0, 'alpha': 0.97,
               'params': ('L', 'alpha'), 'sample': 'al', 'thin': True,
               'tips': 'Folha de alumínio fina (papel alumínio, ~12 µm) tampando a abertura, bem esticada e vedada '
                       'nas bordas (graxa ou fita). O laser incide na face de fora; o microfone fica do lado de dentro.'},
    'al_cam': {'name': 'Al espesso dentro da câmara', 'cell': 'Camara', 'n': 1.0, 'L_um': 2000.0, 'alpha': 0.97,
               'params': ('L', 'alpha'), 'sample': 'al',
               'tips': 'Placa de alumínio (1 mm ou mais) no fundo da câmara, com a face lixada (fosca) para o laser. '
                       'Feche com a janela de vidro e deixe 2–3 mm de ar ou mais sobre a amostra. '
                       'Sinal fraco: o alumínio reflete ~90 % da luz.'},
    'al_fina_cam': {'name': 'Folha de Al fina dentro da câmara', 'cell': 'Camara', 'n': 1.0, 'L_um': 12.0,
                    'alpha': 0.97, 'params': ('L', 'alpha'), 'sample': 'foil',
                    'tips': 'Folha de alumínio (papel alumínio) com o lado fosco para o laser, lisa e colada sobre um '
                            'apoio isolante (papel, plástico ou fita dupla face) no fundo da câmara, sob a janela de '
                            'vidro, com 2–3 mm de ar ou mais por cima. Sem rugas nem bolhas: o sinal depende do '
                            'contato com o apoio. Sinal fraco (reflete ~90 %); o Al pintado de preto dá mais sinal.'},
    'al_preto': {'name': 'Al pintado de preto fosco (câmara)', 'cell': 'Camara', 'n': 1.0, 'L_um': 2000.0,
                 'alpha': 0.97, 'params': ('L', 'alpha'), 'sample': 'black_plate',
                 'tips': 'Placa de alumínio com a face voltada para o laser pintada de preto fosco (spray), no fundo da '
                         'câmara, sob a janela de vidro, com 2–3 mm de ar ou mais por cima. A tinta é uma camada isolante '
                         'sobre o Al: abaixo de ~10–100 Hz (depende da espessura da tinta) parte do calor vai para o Al e o '
                         'sinal cai; acima disso segue f⁻¹ como a fita preta.'},
    'negro_fumo': {'name': 'Negro de fumo (câmara)', 'cell': 'Camara', 'n': 1.0, 'L_um': 0.0,
                   'alpha': 0.0, 'params': (), 'sample': 'black',
                   'tips': 'Fuligem de vela sobre um pedaço de lâmina de vidro (apoio isolante, não metal), em camada '
                           'grossa (~0,1 mm, preto fosco e opaco contra a luz), na mesma altura das amostras, no fundo '
                           'da câmara, com 2–3 mm de ar ou mais por cima. É o padrão clássico da fotoacústica: o mais '
                           'próximo de f⁻¹ ideal. Frágil: não toque nem sopre.'},
    'preto': {'name': 'Fita preta fosca (câmara)', 'cell': 'Camara', 'n': 1.0, 'L_um': 0.0,
              'alpha': 0.0, 'params': (), 'sample': 'black',
              'tips': 'Fita isolante preta (lado fosco) colada numa placa rígida, no fundo da câmara, sob a janela, '
                      'com 2–3 mm de ar ou mais por cima. Rápida de montar e com sinal alto; boa para gerar a '
                      'calibração ou para conferir a do negro de fumo. Limite a "Faixa" a ~1 kHz.'},
    'custom': {'name': 'Personalizada (lei de potência)', 'cell': None, 'n': 1.0, 'L_um': 0.0, 'alpha': 0.0,
               'params': ('n',), 'sample': 'generic',
               'tips': 'Use um padrão cujo expoente n você conheça (S ∝ f⁻ⁿ, fase constante). '
                       'A célula é a escolhida em "Célula" na linha superior.'},
}
CAL_N_TOL = 0.15          # |n ajustado − n esperado| acima disso: aviso
CAL_PHASE_TOL = 15.0      # graus: variação da fase (descontados fc e td) acima disso: aviso
CAL_MIN_DECADES = 1.0     # faixa confiável mais curta que isso: aviso


def fmt_freq(f):
    '''Frequência legível: 7,7 Hz; 214 kHz.'''
    return f'{f / 1e3:.3g} kHz' if f >= 1e3 else f'{f:.3g} Hz'


def cal_ref_info(key, L_um, alpha, n_custom, fmin=None, fmax=None):
    '''Curva esperada da referência key. alpha em cm²/s, L em µm. Devolve (n esperado, texto HTML,
    ok), com ok = False quando os parâmetros saem da validade do modelo (ex.: folha grossa demais).'''
    ref = CAL_REFS[key]
    n = float(n_custom) if key == 'custom' else ref['n']
    nt = f'{n:g}'.replace('.', ',')
    parts = [f'<b>Curva esperada:</b> S ∝ f<sup>−{nt}</sup>, fase constante']
    ok = True
    a = alpha * 1e-4                              # m²/s
    L = L_um * 1e-6
    if key == 'al_opc' and a > 0 and L > 0:
        f1 = a / (np.pi * L * L)
        parts.append(f'f₁ = α/(πL²) = {fmt_freq(f1)}')
        if fmax is not None and fmax > f1 / 10.0:
            ok = False
            parts.append(f'<span style="color:#d00000;">⚠ acima de f₁/10 ({fmt_freq(f1 / 10)}) a folha deixa de ser '
                         f'termicamente fina e f<sup>−1,5</sup> não vale: use folha mais fina ou limite a faixa</span>')
        else:
            parts.append('folha termicamente fina na faixa ✓')
    elif key == 'al_preto':
        parts.append('tinta isolante sobre Al: f<sup>−1</sup> acima de ~100 Hz (abaixo, o calor chega ao Al e o sinal cai)')
    elif key == 'al_cam' and a > 0:
        if fmin and fmax:
            mu0, mu1 = (np.sqrt(a / (np.pi * f)) * 1e3 for f in (fmin, fmax))
            parts.append(f'μ = √(α/πf) = {mu0:.2g} mm ({fmin:g} Hz) a {mu1:.2g} mm ({fmax:g} Hz)')
        if L > 0:
            parts.append(f'termicamente grossa acima de f₁ = α/(πL²) = {fmt_freq(a / (np.pi * L * L))}')
        parts.append('opaca: f<sup>−1</sup> nos dois regimes, não depende de L nem de α')
    elif key == 'al_fina_cam' and a > 0 and L > 0:
        parts.append(f'termicamente fina até f₁ = α/(πL²) = {fmt_freq(a / (np.pi * L * L))}: o sinal vem da folha e do '
                     'apoio, e continua f<sup>−1</sup> com o apoio termicamente grosso (papel ou plástico de ~0,1 mm ou mais)')
    elif key in ('preto', 'negro_fumo'):
        parts.append('opaca (Rosencwaig–Gersho): não depende da espessura nem da difusividade')
    return n, ' &nbsp; '.join(parts), ok


def verify_cal_fit(f, dphi, res, n_exp):
    '''Confere se o ajuste do padrão segue a referência: expoente, fase constante (descontados o passa-altas
    fc e o atraso td) e largura da faixa confiável. f e dphi são os pontos usados no ajuste. Devolve a lista
    de problemas (vazia = verificada) e um texto curto com os números.'''
    good = res['good']
    p, err = res['params'], res['errors']
    probs = []
    dn = p[1] - n_exp
    if abs(dn) > CAL_N_TOL:
        probs.append(f'expoente n = {p[1]:.2f} ± {err[1]:.2f}, esperado {n_exp:g} (diferença {dn:+.2f})')
    ph_txt = ''
    if res['phase'] is not None and good.sum() >= 4:
        r = wrap_deg(dphi[good] - res['phase'](f[good]))
        dev = float(np.percentile(np.abs(r - circ_stats_deg(r)[0]), 90))
        ph_txt = f'; fase: ±{dev:.0f}° em torno do modelo'
        if dev > CAL_PHASE_TOL:
            probs.append(f'a fase varia ±{dev:.0f}° (descontados fc e td), esperado constante (±{CAL_PHASE_TOL:g}°)')
    dec = float(np.log10(f[good].max() / f[good].min())) if good.sum() >= 2 else 0.0
    if dec < CAL_MIN_DECADES:
        probs.append(f'faixa confiável de só {dec:.2f} década(s), mínimo {CAL_MIN_DECADES:g}')
    txt = f'n = {p[1]:.2f} ± {err[1]:.2f} (esperado {n_exp:g}){ph_txt}; faixa confiável {dec:.1f} década(s)'
    return probs, txt


CAL_PROBLEM_CAUSES = ('vazamento na célula, amostra solta ou mal vedada, folga de ar pequena sobre a amostra, '
                      'sinal fraco (SNR baixo), absorção da janela de vidro, ou uma ressonância dentro da faixa '
                      'do ajuste (limite com a "Faixa")')


def find_resonance(f, s):
    '''Pico de ressonância em S(f): o maior excesso sobre uma reta em log-log (fundo) ajustada aos pontos
    fora do pico. Devolve (i do pico, f0 estimada, largura estimada, janela (f_lo, f_hi)) ou None.'''
    f, s = np.asarray(f, dtype=np.float64), np.asarray(s, dtype=np.float64)
    ok = (f > 0) & (s > 0) & np.isfinite(s)
    if ok.sum() < 6:
        return None
    k = np.flatnonzero(ok)[np.argsort(f[ok])]
    f, ls = f[k], np.log(s[k])
    lf = np.log(f)
    use = np.ones(f.size, dtype=bool)
    for _ in range(3):                              # fundo robusto: tira os pontos muito acima da reta
        c = np.polyfit(lf[use], ls[use], 1)
        ex = ls - np.polyval(c, lf)
        thr = 2.0 * max(1.4826 * np.median(np.abs(ex[use] - np.median(ex[use]))), 0.05)
        new = ex < thr
        if new.sum() < 4 or np.array_equal(new, use):
            break
        use = new
    i = int(np.argmax(ex))
    if ex[i] < np.log(1.5):                        # menos de 3,5 dB acima do fundo: sem pico claro
        return None
    half = 0.5 * (np.exp(ex[i]) + 1.0)              # meia altura do excesso, em amplitude
    lo = i
    while lo > 0 and np.exp(ex[lo]) > half:
        lo -= 1
    hi = i
    while hi < f.size - 1 and np.exp(ex[hi]) > half:
        hi += 1
    width = max(f[hi] - f[lo], 2.0 * (f[min(i + 1, f.size - 1)] - f[max(i - 1, 0)]) / 2.0, 1e-3 * f[i])
    # ±3 larguras (fundo dos dois lados), sem passar de f0/1,8 a 1,8·f0 (com poucos pontos a largura sai superestimada)
    f_lo = max(f[0], f[i] - 3.0 * width, f[i] / 1.8)
    f_hi = min(f[-1], f[i] + 3.0 * width, f[i] * 1.8)
    return int(k[i]), float(f[i]), float(width), (float(f_lo), float(f_hi))


def find_ref_band(f, s, dphi, n_exp, valid=None, tol_n=CAL_N_TOL, max_db=CAL_VER_DB, max_deg=CAL_VER_DEG, min_pts=5, min_dec=0.4):
    '''Procura a maior faixa contínua de frequências em que S segue f^-n_exp: ajuste livre de log S × log f com
    |n − n_exp| ≤ tol_n, desvio da reta com n = n_exp ≤ max_db (rms) e fase constante dentro de ±max_deg (rms).
    É o "Ajuste da referência": no resto da varredura a forma vem do sistema (vazamento, ressonância).
    Devolve dict com 'ok', 'i0', 'i1' (índices em f ordenado), 'f_lo', 'f_hi', 'n', 'n_err', 'rms_db', 'rms_deg',
    'lnA' (S = e^lnA·f^-n_exp), 'phi0' (graus), 'order' (ordenação usada) ou None. Sem faixa que passe, devolve a
    de menor desvio (ok = False), para mostrar o mais próximo.'''
    f, s, dphi = (np.asarray(v, dtype=np.float64) for v in (f, s, dphi))
    use = (f > 0) & (s > 0) & np.isfinite(s) & np.isfinite(dphi)
    if valid is not None:
        use &= np.asarray(valid, dtype=bool)
    idx = np.flatnonzero(use)
    if idx.size < min_pts:
        return None
    k = idx[np.argsort(f[idx])]
    lf, ls = np.log(f[k]), np.log(s[k])
    ph = np.unwrap(np.radians(dphi[k]))
    npt = k.size
    best_ok, best_any = None, None
    for i in range(npt):
        for j in range(i + min_pts - 1, npt):
            if lf[j] - lf[i] < min_dec * np.log(10.0):
                continue
            x, y = lf[i:j + 1], ls[i:j + 1]
            c, cov = np.polyfit(x, y, 1, cov=True) if j - i >= 3 else (np.polyfit(x, y, 1), np.zeros((2, 2)))
            n = -c[0]
            n_err = float(np.sqrt(max(cov[0, 0], 0.0)))
            lnA = float(np.mean(y + n_exp * x))
            rms_db = float(np.sqrt(np.mean((y + n_exp * x - lnA) ** 2)) * 20.0 / np.log(10.0))
            p = ph[i:j + 1]
            phi0 = float(np.angle(np.mean(np.exp(1j * p))))
            rms_deg = float(np.degrees(np.sqrt(np.mean(np.angle(np.exp(1j * (p - phi0))) ** 2))))
            good = abs(n - n_exp) <= tol_n and rms_db <= max_db and rms_deg <= max_deg
            r = {'i0': i, 'i1': j, 'f_lo': float(np.exp(lf[i])), 'f_hi': float(np.exp(lf[j])), 'n': float(n),
                 'n_err': n_err, 'rms_db': rms_db, 'rms_deg': rms_deg, 'lnA': lnA, 'phi0': float(np.degrees(phi0)),
                 'order': k, 'npts': j - i + 1}
            score = abs(n - n_exp) / tol_n + rms_db / max_db + rms_deg / max_deg
            if good and (best_ok is None or (lf[j] - lf[i], -score) > (np.log(best_ok['f_hi'] / best_ok['f_lo']),
                                                                       -best_ok['score'])):
                best_ok = dict(r, score=score)
            if best_any is None or score < best_any['score']:
                best_any = dict(r, score=score)
    if best_ok is not None:
        return dict(best_ok, ok=True)
    return dict(best_any, ok=False) if best_any is not None else None


def cell_resonance_f0(f, s, f_min=250.0):
    '''f0 da ressonância da célula (Helmholtz, ~1–2 kHz): procura o pico só acima de f_min, para não confundir
    com ruído ou interferência em baixa frequência. Devolve f0 ou None.'''
    f, s = np.asarray(f, dtype=np.float64), np.asarray(s, dtype=np.float64)
    m = f >= f_min
    fr = find_resonance(f[m], s[m]) if m.sum() >= 6 else None
    return None if fr is None else fr[1]


def resonance_shift(x, s_raw, cal):
    """Compara a ressonância da célula na medida (x, S sem a correção) com a da calibração cal. A f0 da
    calibração vem do arquivo ou, se faltar, do pico na própria curva de sensibilidade. Devolve None (ok ou
    sem como comparar) ou (texto do motivo, f0 da medida ou None, f0 da calibração ou None)."""
    x, s_raw = np.asarray(x, dtype=np.float64), np.asarray(s_raw, dtype=np.float64)
    v = np.isfinite(s_raw) & (s_raw > 0) & (x >= 250.0)
    if v.sum() < 6:
        return None
    cf = cal.get('f0')
    cal_has = cal['f'][-1] > 250.0 and (cal['f'] >= 250.0).sum() >= 6
    if cf is None and cal_has:
        cf = cell_resonance_f0(cal['f'], cal['sens'])
    xs = np.sort(x[v])
    lo, hi = max(xs[0], cal['f'][0]), min(xs[-1], cal['f'][-1])
    if hi <= lo * 1.2:
        return None
    fr = cell_resonance_f0(x[v], s_raw[v])
    if fr is not None and cf is not None:
        i = int(np.clip(np.searchsorted(xs, fr), 1, xs.size - 1))
        step = xs[i] / xs[i - 1] - 1.0
        tol = max(RES_SHIFT_TOL, 1.5 * step)
        if abs(fr / cf - 1.0) > tol:
            return (f'a ressonância desta medida ({fmt_freq(fr)}) difere {abs(fr / cf - 1.0) * 100:.0f} % da '
                    f'calibração ({fmt_freq(cf)})', fr, cf)
        return None
    if fr is not None and cal_has and lo * 1.1 < fr < hi / 1.1:
        return (f'há ressonância nesta medida ({fmt_freq(fr)}) e não na calibração', fr, None)
    if cf is not None and lo * 1.1 < cf < hi / 1.1:
        return (f'a ressonância da calibração ({fmt_freq(cf)}) não aparece nesta medida', None, cf)
    return None


def resonance_complex(p, f):
    '''Oscilador amortecido + fundo complexo, com atraso: p = (ln A, φ0, τ, ln f0, ln Q, b, β).
    z(f) = A·e^{i(φ0 − 2πfτ)}·[f0²/(f0² − f² + i·f·f0/Q) + b·e^{iβ}].'''
    la, phi0, tau, lf0, lq, b, beta = p
    f0, q = np.exp(lf0), np.exp(lq)
    r = f0 * f0 / (f0 * f0 - f * f + 1j * f * f0 / q)
    return np.exp(la + 1j * (phi0 - 2.0 * np.pi * f * tau)) * (r + b * np.exp(1j * beta))


def fit_resonance(f, s, s_rel, dphi, dphi_e, target='both', window=None):
    '''Ajusta a ressonância (resonance_complex) aos pontos dentro de window (f_lo, f_hi); sem window, acha o
    pico sozinho (find_resonance). target: 'mag', 'phase' ou 'both'. Devolve dict com 'func', 'f0', 'f0_err',
    'q', 'q_err', 'fwhm', 'fwhm_err', 'gain_db', 'window', 'n', 'rms_mag', 'rms_phase', ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    s = np.asarray(s, dtype=np.float64)
    dphi = np.asarray(dphi, dtype=np.float64)
    s_rel = np.maximum(np.asarray(s_rel, dtype=np.float64), 0.01)
    sig_p = np.radians(np.maximum(np.asarray(dphi_e, dtype=np.float64), 1.0))
    guess = None
    if window is None:
        found = find_resonance(f, s)
        if found is None:
            return None
        window, guess = found[3], (found[1], found[2])
    sel = (f >= window[0]) & (f <= window[1]) & (s > 0) & np.isfinite(s)
    if sel.sum() < 6:
        return None
    f, s, s_rel, ph, sig_p = f[sel], s[sel], s_rel[sel], np.radians(dphi[sel]), sig_p[sel]
    k = np.argsort(f)
    f, s, s_rel, ph, sig_p = f[k], s[k], s_rel[k], ph[k], sig_p[k]
    ph = np.unwrap(ph)
    ls = np.log(s)
    if guess is None:                               # janela dada pelo usuário: chute pelo maior ponto
        i = int(np.argmax(s))
        above = s > 0.5 * (s[i] + np.median(s))
        guess = (f[i], max(float(np.ptp(f[above])) if above.sum() > 1 else 0.0, 2.0 * float(np.median(np.diff(f)))))
    f0g, wg = guess
    use_mag, use_ph = target in ('mag', 'both'), target in ('phase', 'both')
    fixed_ph = not use_ph

    def resid(p):
        if fixed_ph:
            p = np.r_[p[0], 0.0, 0.0, p[1:]]
        z = resonance_complex(p, f)
        r = []
        if use_mag:
            r.append((np.log(np.abs(z)) - ls) / s_rel)
        if use_ph:
            r.append(np.angle(np.exp(1j * (np.angle(z) - ph))) / sig_p)
        return np.concatenate(r)

    # Atraso inicial pela inclinação da fase fora do pico; fase e amplitude pela borda de baixa frequência
    tau0 = float(np.clip(-np.polyfit(f, ph, 1)[0] / (2.0 * np.pi), -0.01, 0.01)) if use_ph else 0.0
    q0 = float(np.clip(f0g / max(wg, 1e-6), 0.5, 500.0))
    best = None
    for b0 in (0.05, 0.3, 1.0):
        for beta0 in (0.0, np.pi / 2, np.pi, -np.pi / 2):
            for qm in (0.5, 1.0, 2.0):
                p0 = np.array([0.0, 0.0, tau0, np.log(f0g), np.log(q0 * qm), b0, beta0])
                z0 = resonance_complex(p0, f)
                p0[0] = float(np.median(ls - np.log(np.abs(z0))))
                if use_ph:
                    p0[1] = float(np.angle(np.mean(np.exp(1j * (ph - np.angle(z0))))))
                lb = [-np.inf, -np.inf, -0.02, np.log(f.min()), np.log(0.3), 0.0, -np.inf]
                ub = [np.inf, np.inf, 0.02, np.log(f.max()), np.log(5000.0), 50.0, np.inf]
                if fixed_ph:
                    p0 = np.r_[p0[0], p0[3:]]
                    lb = [lb[0]] + lb[3:]
                    ub = [ub[0]] + ub[3:]
                try:
                    sol = least_squares(resid, p0, bounds=(lb, ub))
                except ValueError:
                    continue
                if best is None or sol.cost < best.cost:
                    best = sol
    if best is None:
        return None
    p = best.x
    npar = p.size
    dof = max(1, best.fun.size - npar)
    try:
        cov = np.linalg.pinv(best.jac.T @ best.jac) * max(2.0 * best.cost / dof, 1.0)
        err = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    except np.linalg.LinAlgError:
        err = np.full(npar, np.nan)
    if fixed_ph:
        p = np.r_[p[0], 0.0, 0.0, p[1:]]
        err = np.r_[err[0], np.nan, np.nan, err[1:]]
    f0, q = float(np.exp(p[3])), float(np.exp(p[4]))
    f0_err, q_err = f0 * float(err[3]), q * float(err[4])
    ff = np.linspace(f.min(), f.max(), 2000)
    zz = np.abs(resonance_complex(p, ff))
    z_bg = np.exp(p[0]) * abs(1.0 + p[5] * np.exp(1j * p[6]))   # fundo do lado de baixa frequência (r → 1)
    z = resonance_complex(p, f)
    rms_mag = float(np.sqrt(np.mean((np.log(np.abs(z)) - ls) ** 2)))
    rms_ph = float(np.degrees(np.sqrt(np.mean(np.angle(np.exp(1j * (np.angle(z) - ph))) ** 2))))

    def func(x):
        return resonance_complex(p, np.asarray(x, dtype=np.float64))
    return {'func': func, 'f0': f0, 'f0_err': f0_err, 'q': q, 'q_err': q_err, 'fwhm': f0 / q,
            'fwhm_err': f0 / q * np.hypot(f0_err / f0, q_err / q), 'tau': float(p[2]),
            'gain_db': float(20.0 * np.log10(zz.max() / max(z_bg, 1e-30))), 'f_peak': float(ff[np.argmax(zz)]),
            'window': (float(f.min()), float(f.max())), 'n': int(f.size), 'rms_mag': rms_mag, 'rms_phase': rms_ph}


def opt_digital_phase(f, hp_cutoff, mains=False, fs=None):
    '''Fase (graus) que a cadeia digital soma à fundamental do OPT101 em f (frequência real): atraso da
    referência (opt_ref_delay(), depende do OSR), passa-altas de remoção do DC e, onde ligados, os notches de rede.
    hp_cutoff e mains podem ser escalares ou um valor por frequência.'''
    from soi_dsp import mains_notch_sos           # soi_dsp importa este módulo: import aqui evita o ciclo
    fs = RATE.FS if fs is None else fs
    f = np.atleast_1d(np.asarray(f, dtype=np.float64))
    hp = np.broadcast_to(np.asarray(hp_cutoff, dtype=np.float64), f.shape)
    mains = np.broadcast_to(np.asarray(mains, dtype=bool), f.shape)
    zinv = np.exp(-2j * np.pi * f / fs)
    a = 2.0 * np.pi * hp / fs
    h = 1.0 - a / (1.0 - (1.0 - a) * zinv)          # x - LP(x), y[k] = a*x[k] + (1-a)*y[k-1]
    for i in np.flatnonzero(mains):
        z = zinv[i]
        for b0, b1, b2, _, a1, a2 in mains_notch_sos(fs, f[i]).values():
            h[i] *= (b0 + b1 * z + b2 * z * z) / (1.0 + a1 * z + a2 * z * z)
    return 360.0 * f * opt_ref_delay(int(round(RAW_FS / fs))) + np.degrees(np.angle(h))


def fit_opt_tau(f, phase, phase_e, digital, r=None):
    '''Constante de tempo efetiva do canal óptico (sensor + driver/laser) pela fase do lock-in do OPT101 numa
    varredura em frequência. Modelo de 1 polo: φ(f) = φ0 + digital(f) - atan(2π·f·τ), φ0 ≈ -90° (onda
    quadrada que liga no início do período). Diagnóstico: o atraso do driver/laser também entra aqui, mas
    é comum ao microfone e se cancela em Δφ; para corrigir o sensor use fit_sensor_tau.
    Com r (R do OPT101), ajusta também τ pela queda de amplitude 1/√(1 + (2π·f·τ)²), como verificação.
    Devolve dict ('tau', 'tau_err', 'phi0', 'rms', 'valid', 'tau_amp', 'tau_amp_err', 'text') ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    if f.size < 4:
        return None
    k = np.argsort(f)
    f = f[k]
    w = 2.0 * np.pi * f
    y = np.degrees(np.unwrap(np.radians(wrap_deg(np.asarray(phase, dtype=np.float64)[k] - np.asarray(digital)[k]))))
    sig = np.maximum(np.asarray(phase_e, dtype=np.float64)[k], 0.05)

    def model(p):
        return p[0] - np.degrees(np.arctan(w * p[1]))

    def errors(sol, npar, weighted=True):
        '''Desvios dos parâmetros. Resíduos sem peso: a escala vem toda da dispersão dos resíduos.'''
        chi2 = float(np.sum(sol.fun ** 2) / max(1, f.size - npar))
        try:
            scale = max(chi2, 1.0) if weighted else chi2
            return np.sqrt(np.clip(np.diag(np.linalg.pinv(sol.jac.T @ sol.jac) * scale), 0.0, None))
        except np.linalg.LinAlgError:
            return np.full(npar, np.nan)

    # Partida: inclinação da fase com a frequência (atan(x) ≈ x)
    tau0 = float(np.clip(-np.polyfit(w, y, 1)[0] * np.pi / 180.0, 1e-7, 1e-3))
    sol = least_squares(lambda p: (model(p) - y) / sig, [float(y[0]), tau0], bounds=([-720.0, 0.0], [720.0, 1e-3]))
    if not sol.success:
        return None
    phi0, tau = (float(v) for v in sol.x)
    err = errors(sol, 2)
    out = {'tau': tau, 'tau_err': float(err[1]), 'phi0': phi0,
           'rms': float(np.sqrt(np.mean((y - model(sol.x)) ** 2))),
           'valid': bool(np.isfinite(err[1]) and tau > 2.0 * err[1]),
           'tau_amp': None, 'tau_amp_err': None}
    fc = 1.0 / (2.0 * np.pi * tau) if tau > 0 else np.inf
    text = (f'<b>Canal óptico (sensor + driver/laser):</b> τ efetivo = {tau * 1e6:.3g} ± {err[1] * 1e6:.2g} µs '
            f'pela fase (1 polo) &nbsp; '
            f'banda (-3 dB) = {fc / 1e3:.3g} kHz &nbsp; subida 10–90 % = {tau * np.log(9.0) * 1e6:.3g} µs &nbsp; '
            f'φ0 = {phi0:.1f}° &nbsp; resíduo rms = {out["rms"]:.2f}°')
    if not out['valid']:
        text += (f'<br><span style="color:#d00000;">τ não determinado: a fase até {f.max():g} Hz não separa o polo '
                 f'do ruído (varra até frequências maiores).</span>')
    if r is not None and np.all(np.asarray(r) > 0):
        la = np.log(np.asarray(r, dtype=np.float64)[k])
        sol_a = least_squares(lambda p: p[0] - 0.5 * np.log1p((w * p[1]) ** 2) - la, [float(la.max()), tau],
                              bounds=([-np.inf, 0.0], [np.inf, 1e-3]))
        if sol_a.success:
            out['tau_amp'], out['tau_amp_err'] = float(sol_a.x[1]), float(errors(sol_a, 2, weighted=False)[1])
            text += f'<br>Verificação: τ pela queda de amplitude = {out["tau_amp"] * 1e6:.3g} ± {out["tau_amp_err"] * 1e6:.2g} µs'
            if abs(tau - out['tau_amp']) > 3.0 * np.hypot(err[1], out['tau_amp_err']):
                text += (' &nbsp; <span style="color:#d00000;">⚠ fase e amplitude incompatíveis com um polo único: '
                         'atraso puro (driver/laser) ou potência do laser variando com a frequência. '
                         'O τ da fase é efetivo e inclui esse atraso.</span>')
    out['text'] = text
    return out


def opt_channel_summary(f, r, opt_tau):
    '''Uma linha sobre a luz na varredura em frequência (o que importa para o usuário) e o texto completo do
    canal óptico para a dica. f: frequências reais; r: R do OPT101; opt_tau: dict de fit_opt_tau ou None.'''
    f, r = np.asarray(f, dtype=np.float64), np.asarray(r, dtype=np.float64)
    ok = (r > 0) & np.isfinite(r)
    if ok.sum() < 2:
        return '', ''
    k = np.argsort(f[ok])
    fs, rs = f[ok][k], r[ok][k]
    ref = float(np.median(rs[: max(1, rs.size // 5)]))          # nível de baixa frequência
    drop = 100.0 * (rs[-1] / ref - 1.0)
    spread = 100.0 * (rs.max() - rs.min()) / ref
    parts = [f'<b>Luz (OPT101):</b> R = {ref:.3g} em baixa frequência, {drop:+.0f} % em {fmt_freq(fs[-1])} '
             f'(variação total {spread:.0f} %)']
    if spread < 2.0:
        parts.append('estável')
    else:
        parts.append('a normalização desconta essa variação')
    details = ('Canal óptico = driver + laser + OPT101. Só o polo do OPT101 não é comum ao microfone; o atraso do\n'
               'driver/laser se cancela em Δφ, e a calibração do microfone absorve o polo do OPT101 enquanto o\n'
               'resistor de realimentação for o mesmo. Nada aqui precisa ser calibrado no uso normal.')
    warn = ''
    if opt_tau is not None and opt_tau.get('valid'):
        tau = opt_tau['tau_amp'] if opt_tau.get('tau_amp') else opt_tau['tau']
        fc = 1.0 / (2.0 * np.pi * tau) if tau > 0 else np.inf
        parts.append(f'banda do canal óptico ≈ {fmt_freq(fc)}')
        if fs[-1] > 0.5 * fc:
            warn = (f'<br><span style="color:#b35c00;">A varredura passa de metade da banda óptica: perto de '
                    f'{fmt_freq(fs[-1])} parte da queda da luz pode ser do sensor. Se trocar o resistor do OPT101, '
                    f'use Calibração do microfone → Avançado.</span>')
        details += '\n\n' + re.sub(r'<[^>]+>', '', opt_tau['text'].replace('<br>', '\n')).replace('&nbsp;', ' ')
    return '<span style="color:#404040;">' + '; '.join(parts) + '.</span>' + warn, details


def fit_sensor_tau(f, ph, ph_e, r, f_ref, ph_ref, ph_ref_e, r_ref):
    '''τ do sensor (polo do OPT101) pela diferença de fase entre duas varreduras em frequência com a mesma
    luz (mesmo PWM e alinhamento) e resistores de realimentação diferentes. A cadeia digital, o driver e o
    laser são comuns e se cancelam. O polo é ∝ R_eq, e a razão g = R_eq/R_eq,ref sai da razão dos R:
    Δφ(f) = c - atan(ω·τ) + atan(ω·τ/g), com τ o τ do sensor da varredura atual (f, ph, r).
    Só usa as frequências presentes nas duas. Devolve dict ('tau', 'tau_err', 'tau_ref', 'g', 'n', 'text') ou None.'''
    from scipy.optimize import least_squares
    a = {round(float(v), 2): i for i, v in enumerate(f_ref)}
    pairs = [(i, a[round(float(v), 2)]) for i, v in enumerate(f) if round(float(v), 2) in a]
    if len(pairs) < 4:
        return None
    i, j = (np.array(p) for p in zip(*pairs))
    ff = np.asarray(f, dtype=np.float64)[i]
    w = 2.0 * np.pi * ff
    g = float(np.median(np.asarray(r, dtype=np.float64)[i] / np.asarray(r_ref, dtype=np.float64)[j]))
    if not 0.0 < g or abs(np.log(g)) < np.log(1.3):
        return {'tau': None, 'g': g, 'n': ff.size,
                'text': f'τ do sensor: os ganhos das duas varreduras são próximos demais (razão {g:.2f}); '
                        f'use resistores que mudem o ganho pelo menos 1,3×.'}
    dp = wrap_deg(np.asarray(ph, dtype=np.float64)[i] - np.asarray(ph_ref, dtype=np.float64)[j])
    sig = np.hypot(np.maximum(np.asarray(ph_e, dtype=np.float64)[i], 0.05),
                   np.maximum(np.asarray(ph_ref_e, dtype=np.float64)[j], 0.05))

    def resid(p):
        return (p[0] - np.degrees(np.arctan(w * p[1])) + np.degrees(np.arctan(w * p[1] / g)) - dp) / sig
    sol = least_squares(resid, [0.0, 1e-5], bounds=([-30.0, 0.0], [30.0, 1e-3]))
    if not sol.success:
        return None
    chi2 = float(np.sum(sol.fun ** 2) / max(1, ff.size - 2))
    try:
        err = float(np.sqrt(np.linalg.pinv(sol.jac.T @ sol.jac)[1, 1] * max(chi2, 1.0)))
    except np.linalg.LinAlgError:
        err = float('nan')
    tau = float(sol.x[1])
    return {'tau': tau, 'tau_err': err, 'tau_ref': tau / g, 'g': g, 'n': ff.size,
            'text': f'τ do sensor = {tau * 1e6:.3g} ± {err * 1e6:.2g} µs nesta varredura '
                    f'({tau / g * 1e6:.3g} µs na de referência; razão de ganho {g:.3f}; {ff.size} frequências em comum)'}


# Modelos físicos da resposta da amostra na varredura em frequência (Modo Duplo, painel "Ajuste com modelos").
# Com a calibração aplicada, S e Δφ já são referidos à folha fina de alumínio (∝ f^-1,5), então cada modelo
# descreve a amostra a menos de uma constante complexa (amplitude e fase livres). x = √(f/f1), f1 = α/(πL²).
# Medida das varreduras do Modo Duplo (o nome em português vai para o cabeçalho do CSV)
DUAL_MODE_NAMES = ('Média no tempo (τ atual)', 'Integração longa (τ da varredura)')

FREQ_MODELS = {
    'band': 'Faixa com S ∝ f⁻ⁿ (n esperado da amostra)',
    'pow': 'Lei de potência  S ∝ f⁻ⁿ',
    'pow2': 'Duas leis de potência (com quebra)',
    'diff': 'Difusão térmica (placa, detecção traseira)',
    'te': 'Flexão termoelástica (Perondi–Miranda)',
    'cam_op': 'Câmara: amostra opaca (RG, S ∝ f⁻¹)',
    'cam_tr': 'Câmara: transparente e termicamente grossa (RG, S ∝ f⁻¹·⁵)',
    'res': 'Ressonância da célula (oscilador amortecido + fundo)',
}
FREQ_MODELS_FIXED = {'cam_op': 1.0, 'cam_tr': 1.5}     # modelos sem parâmetro de forma: só amplitude e fase
FREQ_MODEL_TIPS = {
    'band': ('Escolha o n esperado da amostra (1: opaca na câmara; 1,5: folha fina em OPC ou transparente). O ajuste\n'
             'procura a maior faixa contínua em que S segue f⁻ⁿ (n livre dentro de ±0,15 do esperado, desvio ≤ 1,5 dB rms\n'
             'e fase constante ± 10°) e a mostra sombreada. Fora dela, a forma vem do sistema (vazamento, ressonância)\n'
             'ou a amostra não é a esperada. Com a calibração aplicada ("Usar"), a faixa mostra onde a calibração vale.'),
    'pow': 'S ∝ f⁻ⁿ com fase constante. Ajusta só o expoente n (descritivo, sem modelo físico).',
    'pow2': ('Duas retas em log-log, contínuas na frequência de quebra fb: S ∝ f^-n1 abaixo de fb e f^-n2 acima.\n'
             'Ajusta n1, n2 e fb (só a magnitude). Útil para separar regimes: por exemplo, a flexão termoelástica\n'
             'de uma placa grossa (n ≈ 1) e uma contribuição de fundo que domina em frequência alta (n ≈ 0).\n'
             'Use a Faixa para analisar cada parte com mais cuidado.'),
    'diff': ('Difusão do calor através de uma placa iluminada numa face, com o gás do microfone na outra\n'
             '(célula aberta, OPC): S ∝ f^-0,5 / [σL·sinh(σL)], σL = (1+i)·√(f/f1).\n'
             'Baixa frequência (placa termicamente fina): S ∝ f^-1,5, como a folha de alumínio.\n'
             'Alta frequência: a amplitude cai como exp(−√(f/f1)) e a fase atrasa √(f/f1) radianos.'),
    'te': ('Flexão termoelástica de uma placa termicamente grossa em célula aberta (OPC):\n'
           'S ∝ f⁻¹·[(1 − 1/x) + i/x], x = √(f/f1). Costuma dominar em placas metálicas.\n'
           'A fase cai ~90° em torno de f1 e se estabiliza acima dela.\n'
           'Ref.: L. F. Perondi, L. C. M. Miranda, J. Appl. Phys. 62, 2955 (1987);\n'
           'G. Rousset, F. Lepoutre, L. Bertrand, J. Appl. Phys. 54, 2383 (1983).'),
    'cam_op': ('Célula fechada com a amostra dentro (Rosencwaig–Gersho). Amostra opaca: S ∝ f⁻¹ com fase constante,\n'
               'seja ela termicamente fina ou grossa. Sem parâmetro de forma: o ajuste mede só o quanto os dados\n'
               'se afastam do modelo (resíduos). Use com a calibração aplicada.\n'
               'Ref.: A. Rosencwaig, A. Gersho, J. Appl. Phys. 47, 64 (1976).'),
    'cam_tr': ('Célula fechada com a amostra dentro (Rosencwaig–Gersho). Amostra transparente (absorção fraca) e\n'
               'termicamente grossa: S ∝ f⁻¹·⁵, fase constante (−90° em relação à opaca). Se a amostra for\n'
               'semitransparente, o expoente fica entre 1 e 1,5. Sem parâmetro de forma: veja os resíduos.'),
    'res': ('Ressonância acústica da célula: z(f) = A·e^{i(φ0 − 2πfτ)}·[f0²/(f0² − f² + i·f·f0/Q) + b·e^{iβ}].\n'
            'Ajusta f0, Q, a largura (f0/Q) e o ganho do pico sobre o fundo. Sem "Faixa", o pico é achado sozinho;\n'
            'ou use "Marcar pico" e clique dos dois lados dele no gráfico da esquerda.\n'
            'Meça com "Usar" desmarcado: a calibração do microfone remove a ressonância da célula.'),
}


def _log_sinh(q):
    '''log(sinh(q)) complexo sem overflow para Re(q) grande.'''
    q = np.asarray(q, dtype=np.complex128)
    big = q.real > 20.0
    out = np.empty_like(q)
    out[big] = q[big] - np.log(2.0)
    out[~big] = np.log(np.sinh(q[~big]))
    return out


def freq_model_log(model, f, shape):
    '''log do modelo (complexo, sem a constante): Re = log da amplitude, Im = fase em rad.'''
    f = np.asarray(f, dtype=np.float64)
    if model == 'pow':
        return -shape * np.log(f) + 0j
    if model in FREQ_MODELS_FIXED:
        return -FREQ_MODELS_FIXED[model] * np.log(f) + 0j
    x = np.sqrt(f / shape)
    if model == 'diff':
        q = (1 + 1j) * x
        return -0.5 * np.log(f) - np.log(q) - _log_sinh(q)
    return -np.log(f) + np.log((1.0 - 1.0 / x) + 1j / x)          # 'te'


def fit_freq_model(f, s, s_rel, dphi, dphi_e, model, target):
    '''Ajusta um modelo de FREQ_MODELS à magnitude S, à fase Δφ (graus) ou às duas ('mag', 'phase', 'both').
    Parâmetros: log da amplitude, fase φ0 e o de forma (n ou log f1). Devolve dict com 'func' (modelo
    complexo nos f dados, com as constantes), 'shape', 'shape_err', 'rms_mag', 'rms_phase', ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    ls = np.log(np.asarray(s, dtype=np.float64))
    sig_l = np.maximum(np.asarray(s_rel, dtype=np.float64), 0.01)
    ph = np.radians(np.asarray(dphi, dtype=np.float64))
    sig_p = np.radians(np.maximum(np.asarray(dphi_e, dtype=np.float64), 1.0))
    use_mag, use_ph = target in ('mag', 'both'), target in ('phase', 'both')
    if f.size < 3 or not np.all(np.isfinite(ls)):
        return None
    if model in FREQ_MODELS_FIXED:
        # Sem parâmetro de forma: a melhor amplitude e fase constantes, e os resíduos
        g = freq_model_log(model, f, 0.0)
        c0 = float(np.sum((ls - g.real) / sig_l ** 2) / np.sum(1.0 / sig_l ** 2))
        p1 = float(np.angle(np.mean(np.exp(1j * (ph - g.imag)))))
        rms_mag = float(np.sqrt(np.mean((c0 + g.real - ls) ** 2)))
        rms_ph = float(np.degrees(np.sqrt(np.mean(np.angle(np.exp(1j * (p1 + g.imag - ph))) ** 2))))
        return {'func': lambda ff: np.exp(c0 + 1j * p1 + freq_model_log(model, ff, 0.0)), 'shape': None,
                'shape_err': None, 'rms_mag': rms_mag, 'rms_phase': rms_ph, 'n': f.size}

    def shape_of(p):
        return p[2] if model == 'pow' else float(np.exp(p[2]))

    def resid(p):
        g = freq_model_log(model, f, shape_of(p))
        r = []
        if use_mag:
            r.append((p[0] + g.real - ls) / sig_l)
        if use_ph:
            r.append(np.angle(np.exp(1j * (p[1] + g.imag - ph))) / sig_p)
        return np.concatenate(r)

    if model == 'pow':
        starts, lb, ub = [0.5, 1.0, 1.5], -5.0, 5.0
    else:
        starts = np.log(np.geomspace(f.min() / 30.0, f.max() * 3.0, 12))
        lb, ub = np.log(f.min() / 1000.0), np.log(f.max() * 100.0)
    best = None
    for s0 in starts:
        g0 = freq_model_log(model, f, s0 if model == 'pow' else float(np.exp(s0)))
        p0 = [float(np.median(ls - g0.real)), float(np.angle(np.mean(np.exp(1j * (ph - g0.imag))))), s0]
        try:
            sol = least_squares(resid, p0, bounds=([-np.inf, -np.inf, lb], [np.inf, np.inf, ub]))
        except ValueError:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        return None
    p = best.x
    dof = max(1, best.fun.size - 3)
    cov = np.linalg.pinv(best.jac.T @ best.jac) * 2.0 * best.cost / dof
    err = float(np.sqrt(max(cov[2, 2], 0.0)))
    shape = shape_of(p)
    g = freq_model_log(model, f, shape)
    rms_mag = float(np.sqrt(np.mean((p[0] + g.real - ls) ** 2)))
    rms_ph = float(np.degrees(np.sqrt(np.mean(np.angle(np.exp(1j * (p[1] + g.imag - ph))) ** 2))))

    def func(ff):
        return np.exp(p[0] + 1j * p[1] + freq_model_log(model, ff, shape))
    return {'func': func, 'shape': shape, 'shape_err': err if model == 'pow' else shape * err,
            'rms_mag': rms_mag, 'rms_phase': rms_ph, 'n': f.size}


def fit_broken_power(f, s, s_rel):
    '''Duas leis de potência contínuas em log-log: log S = c − n1·log f + (n1 − n2)·max(0, log f − log fb).
    Devolve dict com 'func', 'n1', 'n1_err', 'n2', 'n2_err', 'fb', 'fb_err', 'rms_mag', 'n', ou None.'''
    from scipy.optimize import least_squares
    f = np.asarray(f, dtype=np.float64)
    if f.size < 5:
        return None
    lf = np.log(f)
    ls = np.log(np.asarray(s, dtype=np.float64))
    sig = np.maximum(np.asarray(s_rel, dtype=np.float64), 0.01)
    if not np.all(np.isfinite(ls)):
        return None

    def model(p, x):
        return p[0] - p[1] * x + (p[1] - p[2]) * np.maximum(0.0, x - p[3])
    lo, hi = lf.min(), lf.max()
    best = None
    for lfb in np.linspace(lo, hi, 17)[1:-1]:          # quebra estritamente dentro da faixa
        try:
            sol = least_squares(lambda p: (model(p, lf) - ls) / sig, [ls[0] + lf[0], 1.0, 1.0, lfb],
                                bounds=([-np.inf, -5, -5, lo], [np.inf, 5, 5, hi]))
        except ValueError:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        return None
    p = best.x
    e = np.sqrt(np.maximum(np.diag(np.linalg.pinv(best.jac.T @ best.jac) * 2 * best.cost / max(1, f.size - 4)), 0))
    fb = float(np.exp(p[3]))
    return {'func': lambda ff: np.exp(model(p, np.log(ff))) + 0j,
            'n1': p[1], 'n1_err': e[1], 'n2': p[2], 'n2_err': e[2], 'fb': fb, 'fb_err': fb * e[3],
            'rms_mag': float(np.sqrt(np.mean((model(p, lf) - ls) ** 2))), 'n': f.size}


def wrap_deg(a):
    '''Ângulo(s) em graus no intervalo [-180, 180).'''
    return (np.asarray(a) + 180.0) % 360.0 - 180.0


def rolling_noise(z, w):
    '''Estatística móvel (janela de w pontos) da saída complexa Z = X + jY do lock-in.
    Devolve (|<Z>|, sigma por quadratura) para cada janela completa.'''
    z = np.asarray(z, dtype=np.complex128)
    if w < 2 or z.size < w:
        return np.empty(0), np.empty(0)
    c1 = np.concatenate(([0j], np.cumsum(z)))
    c2 = np.concatenate(([0.0], np.cumsum(np.abs(z) ** 2)))
    mean = (c1[w:] - c1[:-w]) / w
    p2 = (c2[w:] - c2[:-w]) / w
    var = np.maximum(p2 - np.abs(mean) ** 2, 0.0) * w / (w - 1)
    return np.abs(mean), np.sqrt(var / 2.0)


def fmt_tau(tau):
    if not np.isfinite(tau):
        return 'τ = —'
    return f'τ = {tau * 1e3:.3g} ms' if tau < 1.0 else f'τ = {tau:.3g} s'


def fmt_hz(f):
    return f'{f * 1e3:.3g} mHz' if f < 1.0 else f'{f:.3g} Hz'


def fmt_seconds(s):
    return f'{s * 1e3:.3g} ms' if s < 1.0 else f'{s:.3g} s'


def fmt_lp_info(tau):
    '''Texto curto mostrado ao lado do τ de cada lock-in.'''
    f3, enbw, wait = lp_info(tau)
    return f'−3 dB: {fmt_hz(f3)}   ENBW: {fmt_hz(enbw)}   espera: {fmt_seconds(wait)}'


TAU_TIP = ('Constante de tempo de cada polo do passa-baixas aplicado depois da demodulação (2 polos em cascata).\n'
           'τ maior = menos ruído e leitura mais estável, porém resposta mais lenta.\n'
           'As setas andam na sequência 1–3–10: 1 ms, 3 ms, 10 ms … 30 s, 100 s. Também aceita um valor digitado\n'
           '(ex.: 0,5 s ou 200 ms).\n'
           'Use τ de pelo menos ~3 períodos da modulação (τ ≥ 3/f) para rejeitar o resíduo em 2f.\n'
           'Ao mudar a frequência, volta ao automático: ~3 períodos, arredondado para 0,3 s, 1 s ou 3 s.')
HP_TIP = ('Passa-altas de 1 polo antes da demodulação: estima e remove o nível DC do sinal\n'
          '(luz ambiente, offset do sensor), deixando só a parte modulada.\n'
          'Precisa ficar bem abaixo da frequência de modulação: corte alto atenua e adianta a fase do sinal.\n'
          'No OPT101 o DC estimado também é o usado em R/DC e na coluna DC_Offset das varreduras.\n'
          'Ao mudar a frequência, volta ao automático: 2 % da frequência, entre 0,01 e 0,05 Hz.')
LP_INFO_TIP = ('Calculados a partir do τ (2 polos em cascata, 12 dB/oitava):\n'
               '−3 dB: frequência de corte do filtro, 0,644/(2πτ).\n'
               'ENBW: banda equivalente de ruído, 1/(8τ). O ruído na saída cresce com √ENBW.\n'
               'espera: 9τ, tempo para a saída chegar a ~0,1 % do valor final após um degrau\n'
               '(~95 % em 4,7τ e ~99 % em 6,6τ). É o que as varreduras esperam em cada ponto.')


# Exporta tudo (inclusive nomes com _) para os módulos que fazem import *
__all__ = [_n for _n in dir() if not _n.startswith('__')]
