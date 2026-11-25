# -*- coding: utf-8 -*-
'''Processamento sem Qt: lock-ins (OPT101 com PLL, INMP441), referência externa, buffers, teste de resolução
e gravação opcional do áudio bruto.

Parte do SOI Controller (antes em soi_controller.py).'''

from soi_const import *  # noqa: F401,F403
from soi_analise import *  # noqa: F401,F403


# ============================================================================
# PURE-BEGIN  (classes sem Qt/serial: testáveis isoladamente)
# ============================================================================
# ----------------------------------------------------------------------------
# Lock-in (antigo lockin_py.py): OPT101 (com PLL) e INMP441 (referência numérica)
# ----------------------------------------------------------------------------
Result = namedtuple('Result', 'adc ref r phase dc consumed')

PLL_KP = 0.05
PLL_KI = PLL_KP * PLL_KP / 4.0
PLL_ERR_UNLOCK = 1.1
PLL_ERR_ALPHA = 0.15
PLL_FREQ_CLAMP = 0.05
TWO_PI = 2.0 * np.pi


def _wrap_pi(x):
    '''Leva o ângulo (rad) ao intervalo [-pi, pi).'''
    return (x + np.pi) % TWO_PI - np.pi


_E_U16 = np.empty(0, np.uint16)
_E_U8 = np.empty(0, np.uint8)
_E_F = np.empty(0, np.float64)
_E_F32 = np.empty(0, np.float32)


MAINS_HZ = 60.0
MAINS_MAX_HZ = 1500.0     # harmônicas rejeitadas até esta frequência
MAINS_BW_HZ = 2.0         # largura (-3 dB) de cada notch
MAINS_GUARD_HZ = 5.0      # notches a menos disso da modulação são omitidos (preservam o sinal)


def mains_notch_sos(fs, ref_freq):
    '''Notches em 60 Hz e múltiplos até MAINS_MAX_HZ, sem os que caem a menos de MAINS_GUARD_HZ da
    modulação. Devolve {harmônica: linha sos (b0 b1 b2 a0 a1 a2)}.'''
    nyq = fs / 2.0
    out = {}
    for h in range(1, int(min(MAINS_MAX_HZ, 0.95 * nyq) // MAINS_HZ) + 1):
        f0 = h * MAINS_HZ
        if abs(f0 - ref_freq) > MAINS_GUARD_HZ:
            b, a = iirnotch(f0, f0 / MAINS_BW_HZ, fs)
            out[h] = np.concatenate((b, a))
    return out


class _MainsFilterMixin:
    '''Notches em 60 Hz e múltiplos (usa self.fs, self.ref_freq e self.mains_zi).'''

    supports_mains = True

    def set_mains_filter(self, enabled):
        self.mains_enabled = bool(enabled)
        self.mains_zi = {}

    mains_enabled = False

    def _mains_filter(self, x):
        '''Notches em 60 Hz e múltiplos, só no caminho do lock-in. Omite os que caem sobre a modulação.'''
        notches = mains_notch_sos(self.fs, self.ref_freq)
        hs = list(notches)
        self.mains_zi = {h: z for h, z in self.mains_zi.items() if h in hs}
        if not hs:
            return x
        secs, zis = [], []
        for h in hs:
            sos = notches[h][None, :]
            secs.append(sos)
            z = self.mains_zi.get(h)
            zis.append(sosfilt_zi(sos)[0] * x[0] if z is None else z)
        sos_all = np.concatenate(secs)
        y, zf = sosfilt(sos_all, x, zi=np.array(zis))
        self.mains_zi = {h: zf[i] for i, h in enumerate(hs)}
        return y


def decimate_raw(buf, osr):
    '''Média de osr palavras cruas do firmware 2.0.0 (uint16 LE: bits 0-11 = ADC, bit 15 = laser).
    Devolve (adc float32 = soma * 4 / osr, na escala 0-16380 da 1.0.0; ref uint8 = maioria das osr
    amostras, empate = 0; bytes consumidos, sempre blocos completos).'''
    osr = max(1, int(osr))
    m = (len(buf) // 2) // osr
    if m == 0:
        return _E_F32, _E_U8, 0
    w = np.frombuffer(buf, dtype='<u2', count=m * osr)
    if osr == 1:
        return (w & 0x0FFF).astype(np.float32) * np.float32(4.0), (w >> 15).astype(np.uint8), m * 2
    blk = w.reshape(m, osr)
    adc = (blk & 0x0FFF).sum(axis=1, dtype=np.uint32).astype(np.float32) * np.float32(4.0 / osr)
    ref = ((blk >> 15).sum(axis=1, dtype=np.uint32) * 2 > osr).astype(np.uint8)
    return adc, ref, m * osr * 2


class PyLockIn(_MainsFilterMixin):
    def __init__(self, fs, ref_freq, cutoff_lp, cutoff_hp):
        # Modulação óptica: ExternalReference (PLL no próprio sinal) e ExtTimeSync (farol do bit 15).
        # None = modulação eletrônica (PLL nas bordas do bit 15, o laser do STM32).
        self.ext = None
        self.ext_sync = None
        self.init(fs, ref_freq, cutoff_lp, cutoff_hp)

    # --------------------------------------------------------------- estado
    def init(self, fs, ref_freq, cutoff_lp, cutoff_hp):
        self.fs = float(fs)
        self.osr = max(1, int(round(RAW_FS / self.fs)))   # amostras cruas do ADC por amostra do lock-in
        self.ref_freq = ref_freq
        self.alpha_lp = TWO_PI * cutoff_lp / self.fs
        self.alpha_hp = TWO_PI * cutoff_hp / self.fs
        self.d_theta = TWO_PI * ref_freq / self.fs
        self.dc_offset = 512.0
        self.dc_init = False
        self.theta = 0.0
        self.last_ref = 0
        self.lp1 = 0j
        self.lp2 = 0j
        self.sample_count = 0
        self.edge_count = 0
        self.measured_freq = ref_freq
        self.pll_locked = False
        self.err_avg = 0.0
        self.mains_zi = {}

    def update_params(self, ref_freq, cutoff_lp, cutoff_hp):
        self.ref_freq = ref_freq
        self.alpha_lp = TWO_PI * cutoff_lp / self.fs
        self.alpha_hp = TWO_PI * cutoff_hp / self.fs
        self.edge_count = 0
        self._unlock()

    def _nominal_step(self):
        return TWO_PI * self.ref_freq / self.fs

    def _unlock(self):
        self.pll_locked = False
        self.err_avg = 0.0
        self.d_theta = self._nominal_step()
        self.measured_freq = self.ref_freq

    # --------------------------------------------------------------- amostras
    def _parse(self, buf):
        '''Sobreamostragem: média de OSR palavras cruas (uint16 LE: bits 0-11 = ADC, bit 15 = laser).
        Devolve (adc float32 na escala 0-16380, ref uint8 = maioria das OSR amostras, bytes consumidos).
        Só consome blocos completos; o resto fica no buffer para a próxima chamada.'''
        return decimate_raw(buf, self.osr)

    # ------------------------------------------------------------------- PLL
    def _phase(self, ref):
        '''Fase do demodulador em cada amostra. O estado do PLL avança a cada borda de subida.'''
        n = ref.size
        prev = np.empty(n, dtype=np.uint8)
        prev[0] = self.last_ref
        prev[1:] = ref[:-1]
        edges = np.flatnonzero((prev == 0) & (ref == 1)).tolist()
        self.last_ref = int(ref[-1])

        limit = int(self.fs * 10.0)
        nominal_n = self.fs / self.ref_freq if self.ref_freq > 0 else 0.0
        tol = 2.0 + 0.001 * nominal_n

        # Segmentos de fase linear: (início, theta no início, passo)
        starts, thetas, steps = [0], [self.theta], [self.d_theta]
        s, th, d = 0, self.theta, self.d_theta   # segmento corrente
        c, p = self.edge_count, 0                # contador de amostras desde a última borda, a partir de p

        for e in edges + [None]:
            end = e if e is not None else n
            # Perda de referência por mais de 10 s antes de 'end': volta à frequência nominal
            j = p + max(0, limit - c)
            while j < end:
                th += d * (j - s); s = j
                self.d_theta = d; self._unlock(); d = self.d_theta
                starts.append(s); thetas.append(th); steps.append(d)
                c, p = 0, j + 1
                j = p + max(0, limit - c)
            if e is None:
                break
            N = c + (e - p) + 1
            th += d * (e - s); s = e
            c, p = 0, e + 1
            if abs(N - nominal_n) > tol or nominal_n <= 0.0:
                self.d_theta = d; self._unlock(); d = self.d_theta
            elif not self.pll_locked:
                th, d = 0.0, self._nominal_step()
                self.pll_locked, self.err_avg = True, 0.0
            else:
                err = _wrap_pi(th)
                self.err_avg += PLL_ERR_ALPHA * (abs(err) - self.err_avg)
                if self.err_avg > PLL_ERR_UNLOCK:
                    self.d_theta = d; self._unlock(); d = self.d_theta
                else:
                    nom = self._nominal_step()
                    th -= PLL_KP * err
                    d -= PLL_KI * err / nominal_n
                    d = min(max(d, nom * (1.0 - PLL_FREQ_CLAMP)), nom * (1.0 + PLL_FREQ_CLAMP))
                    self.measured_freq = d * self.fs / TWO_PI
            starts.append(s); thetas.append(th); steps.append(d)

        th_end = (th + d * (n - s)) % TWO_PI
        self.theta, self.d_theta, self.edge_count = th_end, d, c + (n - p)

        if len(starts) == 1:
            return thetas[0] + steps[0] * np.arange(n)
        st = np.asarray(starts)
        lens = np.diff(np.append(st, n))
        return (np.repeat(thetas, lens) + np.repeat(steps, lens)
                * (np.arange(n) - np.repeat(st, lens)))

    # ------------------------------------------------------------------ DSP
    def process(self, buf, decimation, enable_lockin, normalize, stream_pos=None):
        '''stream_pos: índice (amostras cruas desde a conexão) da primeira palavra de buf; usado só na
        modulação óptica, em que a referência é a fase θ(s) do próprio OPT101.'''
        adc, ref, consumed = self._parse(buf)
        ext = self.ext
        theta = None
        if ext is not None and adc.size and stream_pos is not None:
            if self.ext_sync is not None:     # bordas do bit 15 (farol do alinhamento com o I2S)
                self.ext_sync.add_raw(np.frombuffer(buf, dtype='<u2', count=consumed // 2), stream_pos)
            c = stream_pos + np.arange(adc.size, dtype=np.float64) * self.osr + 0.5 * (self.osr - 1)
            theta = ext.process(adc.astype(np.float64), c)
            # O traço verde do osciloscópio (e o Modo Valor Médio) passa a ser a referência do PLL
            ref = (np.cos(theta) >= 0.0).astype(np.uint8)
        if adc.size == 0 or not enable_lockin:
            return Result(adc, ref, _E_F, _E_F, _E_F, consumed)
        n = adc.size
        x = adc.astype(np.float64)

        if theta is not None:
            # Mesma convenção de fase da modulação eletrônica (onda quadrada que liga em θ = 0, PLL no centro
            # do bloco do OSR): Δφ = φ_INMP441 − φ_OPT101 sai igual e as calibrações valem nos dois modos.
            theta = theta + 0.5 * np.pi + TWO_PI * self.ref_freq * opt_ref_delay(self.osr)
        else:
            theta = self._phase(ref)
        if self.mains_enabled:
            x = self._mains_filter(x)
            adc = x.astype(np.float32)
        # Remoção de DC: passa-baixas de 1 polo; y[k] = a*x[k] + (1-a)*y[k-1]
        if not self.dc_init:
            self.dc_offset, self.dc_init = float(x[0]), True
        a = self.alpha_hp
        dc = lfilter([a], [1.0, a - 1.0], x, zi=[(1.0 - a) * self.dc_offset])[0]
        self.dc_offset = float(dc[-1])

        # Demodulação em quadratura, em um único vetor complexo (x + jy)
        z = (2.0 * (x - dc)) * np.exp(-1j * theta)

        # Passa-baixas de 2 polos em cascata
        a = self.alpha_lp
        b_lp, a_lp = [a], [1.0, a - 1.0]
        z1 = lfilter(b_lp, a_lp, z, zi=[(1.0 - a) * self.lp1])[0]
        z2 = lfilter(b_lp, a_lp, z1, zi=[(1.0 - a) * self.lp2])[0]
        self.lp1, self.lp2 = complex(z1[-1]), complex(z2[-1])

        # Decimação: uma saída a cada 'decimation' amostras (contador persistente)
        first = decimation - self.sample_count - 1
        self.sample_count = (self.sample_count + n) % decimation
        idx = np.arange(first, n, decimation)
        zo = z2[idx]
        # Cada amostra é a média de OSR amostras do ADC (janela de OSR/200 kHz, 80 us com OSR 16): a
        # fundamental chega atenuada pelo ganho da média (-1 % em 1 kHz e -9 % em 3 kHz com OSR 16). Desfaz.
        r = np.abs(zo) / float(boxcar_gain(self.ref_freq, self.osr))
        phase = np.degrees(np.angle(zo))
        dco = dc[idx]
        if normalize:
            r = r / np.maximum(dco, 1.0) * 100.0
        return Result(adc, ref, r, phase, dco, consumed)


class AudioLockIn(_MainsFilterMixin):
    '''Lock-in do INMP441: mesma cadeia do PyLockIn (passa-altas de 1 polo para o DC, notches de
    rede opcionais, demodulação em quadratura e passa-baixas de 2 polos), mas com referência
    numérica: a fase vem do número de sequência da amostra I2S, sem PLL.'''

    def __init__(self, fs, ref_freq, cutoff_lp, cutoff_hp):
        self.init(fs, ref_freq, cutoff_lp, cutoff_hp)

    def init(self, fs, ref_freq, cutoff_lp, cutoff_hp):
        self.fs = float(fs)
        self.ref_freq = actual_mod_freq(ref_freq)
        self.alpha_lp = TWO_PI * cutoff_lp / self.fs
        self.alpha_hp = TWO_PI * cutoff_hp / self.fs
        self.dc_offset = 0.0
        self.dc_init = False
        self.lp1 = 0j
        self.lp2 = 0j
        self.sample_count = 0
        self.mains_zi = {}
        self.phase_origin = 0     # nº da amostra I2S da borda de subida do laser (marcador do firmware)

    def update_params(self, ref_freq, cutoff_lp, cutoff_hp):
        # Os estados dos filtros são mantidos: ao trocar a frequência a saída transita até estabilizar
        self.ref_freq = actual_mod_freq(ref_freq)
        self.alpha_lp = TWO_PI * cutoff_lp / self.fs
        self.alpha_hp = TWO_PI * cutoff_hp / self.fs

    def process(self, sequence, samples, decimation, theta=None):
        '''samples: int32 (PCM 24 bits). Devolve (r, fase em graus), uma saída a cada 'decimation'
        amostras (contador persistente), em fração da escala completa. theta: fase da referência em cada
        amostra (modulação óptica, vinda do OPT101); None = referência numérica a partir do marcador.'''
        x = np.asarray(samples, dtype=np.float64) / 8388608.0
        if theta is None:
            n = float((sequence - self.phase_origin) & 0xFFFFFFFF) + np.arange(x.size, dtype=np.float64)
            theta = TWO_PI * np.mod(self.ref_freq * n / self.fs, 1.0)
        if self.mains_enabled:
            x = self._mains_filter(x)
        if not self.dc_init:
            self.dc_offset, self.dc_init = float(x[0]), True
        a = self.alpha_hp
        dc = lfilter([a], [1.0, a - 1.0], x, zi=[(1.0 - a) * self.dc_offset])[0]
        self.dc_offset = float(dc[-1])

        z = (2.0 * (x - dc)) * np.exp(-1j * theta)

        a = self.alpha_lp
        b_lp, a_lp = [a], [1.0, a - 1.0]
        z1 = lfilter(b_lp, a_lp, z, zi=[(1.0 - a) * self.lp1])[0]
        z2 = lfilter(b_lp, a_lp, z1, zi=[(1.0 - a) * self.lp2])[0]
        self.lp1, self.lp2 = complex(z1[-1]), complex(z2[-1])

        first = decimation - self.sample_count - 1
        self.sample_count = (self.sample_count + x.size) % decimation
        zo = z2[np.arange(first, x.size, decimation)]
        return np.abs(zo), np.degrees(np.angle(zo))


# ----------------------------------------------------------------------------
# Modulação óptica (chopper): referência derivada do próprio OPT101
# ----------------------------------------------------------------------------
# Com a luz modulada fora do SOI (chopper, ventilador), o STM32 não gera a referência. A interface:
#  1. acha a frequência na FFT do OPT101 e a segue com um PLL sobre o próprio sinal (ExternalReference),
#     que dá a fase θ(s) da fundamental da luz em função do índice s das amostras cruas do fluxo óptico;
#  2. leva a mesma θ ao microfone: ADC (200 kS/s) e I2S (48 kHz) saem do mesmo cristal, a razão entre as
#     taxas é exata e o deslocamento entre os dois fluxos vem de um "farol" (ExtTimeSync): o STM32 modula a
#     1 Hz com PWM 0 (laser apagado); o bit 15 do OPT101 e o marcador do I2S marcam o mesmo instante.
# Os dois lock-ins usam a mesma θ: erros dela (atraso de filtro, jitter do chopper) se cancelam em
# S = R_INMP441/R_OPT101 e Δφ = φ_INMP441 − φ_OPT101.
EXT_BEACON_HZ = 1.0           # farol do alinhamento ADC↔I2S (F do STM32 no modo óptico; PWM 0)
EXT_FMIN_DEFAULT = 20.0       # faixa de busca padrão da frequência do chopper (Hz)
EXT_FMAX_DEFAULT = 5000.0
EXT_TIMELINE_SEC = 4.0        # quanto da fase θ(s) fica guardado para o lock-in do INMP441
EXT_AUDIO_PENDING_SEC = 1.5   # áudio à espera da θ do OPT101 (descartado se passar disso)
# Borda da luz em relação à primeira amostra com o rótulo novo (amostras cruas): a troca ocorre, em média,
# meia amostra antes; o rótulo segue a escrita do DMA (12 ciclos do ADC a 21 MHz depois do instante
# amostrado) e o laser muda ~0,2 µs depois do rótulo (mesma cadeia de opt_ref_delay).
EXT_EDGE_CORR = -0.5 + (12.0 / 21e6 + 0.2e-6) * RAW_FS
EXT_AUDIO_RATIO = RAW_FS / AUDIO_FS_REAL      # amostras cruas do ADC por amostra I2S (exato: mesmo cristal)


def _sdiff32(a, b):
    '''a − b para contadores de 32 bits, com sinal.'''
    return ((int(a) - int(b) + 0x80000000) & 0xFFFFFFFF) - 0x80000000


class ExtTimeSync:
    '''Relação entre o índice s do fluxo óptico (amostras cruas desde a conexão) e o número k da amostra
    I2S: s = L + (k − k_ref)·RAW_FS/AUDIO_FS_REAL. O marcador do I2S dá k_ref (amostra em que o TIM4 do
    farol partiu) e a posição aproximada do fluxo óptico nesse instante; as bordas do bit 15 (todas em
    L + m·meio período, m ≥ 1) dão L com precisão de fração de amostra (média de várias bordas).
    Usada pela thread do OPT101 (escreve) e pela do INMP441 (lê).'''
    MAX_EDGES = 64            # média móvel das últimas bordas

    def __init__(self, beacon_hz=EXT_BEACON_HZ):
        self.lock = threading.Lock()
        self.beacon_hz = beacon_hz
        self.reset()

    def reset(self):
        with self.lock:
            self.half = RAW_FS / (2.0 * actual_mod_freq(self.beacon_hz))   # meio período em amostras cruas
            self.pending = None          # (k_m, pos_m) do último marcador
            self.est = deque(maxlen=self.MAX_EDGES)
            self.map = None              # (k_ref, L) em uso
            self.outliers = 0
            self.last_bit = None
            self.marker_count = 0

    def set_marker(self, k_m, pos_m):
        with self.lock:
            self.pending = (int(k_m), float(pos_m))
            self.est.clear()
            self.outliers = 0
            self.marker_count += 1

    def add_raw(self, words, s0):
        '''words: palavras cruas (uint16) a partir do índice s0 do fluxo. Procura as bordas do bit 15.'''
        if words.size == 0:
            return
        bit = (words >> 15).astype(np.int8)
        prev = self.last_bit if self.last_bit is not None else int(bit[0])
        self.last_bit = int(bit[-1])
        d = np.diff(bit, prepend=np.int8(prev))
        edges = np.flatnonzero(d)
        if edges.size == 0:
            return
        with self.lock:
            if self.pending is None:
                return
            k_m, pos_m = self.pending
            for e in edges:
                x = s0 + float(e) + EXT_EDGE_CORR
                m = int(round((x - pos_m) / self.half))
                if m < 1 or abs(x - pos_m - m * self.half) > 0.25 * self.half:
                    continue             # borda anterior ao farol (ligou o laser no comando) ou fora do lugar
                L = x - m * self.half
                if self.est and abs(L - np.mean(self.est)) > 4.0:
                    self.outliers += 1
                    if self.outliers >= 3:      # o fluxo mudou (reconexão sem aviso): recomeça a média
                        self.est.clear()
                        self.outliers = 0
                    continue
                self.outliers = 0
                self.est.append(L)
            if self.est:
                self.map = (k_m, float(np.mean(self.est)))

    def ready(self):
        return self.map is not None

    def audio_to_raw(self, k, n):
        '''Índices s (float64) das amostras I2S k..k+n−1, ou None sem alinhamento.'''
        m = self.map
        if m is None:
            return None
        k_ref, L = m
        return L + (_sdiff32(k, k_ref) + np.arange(n, dtype=np.float64)) * EXT_AUDIO_RATIO


class ExternalReference:
    '''PLL sobre o próprio sinal do OPT101 (luz modulada por fora). A frequência inicial vem da FFT de
    uma janela do sinal (pico na faixa de busca, interpolado); depois um PLL de 2ª ordem, atualizado em
    blocos de um número inteiro de períodos, mantém θ(s) contínua e linear por trechos (um trecho por
    bloco). θ é a fase da fundamental do OPT101: x ≈ A·cos θ. Guarda os trechos dos últimos
    EXT_TIMELINE_SEC para o lock-in do INMP441 (theta_at, chamado da thread de áudio).'''

    def __init__(self, fmin=EXT_FMIN_DEFAULT, fmax=EXT_FMAX_DEFAULT):
        self.lock = threading.Lock()
        self.fmin, self.fmax = float(fmin), float(fmax)
        self.reset()

    def set_range(self, fmin, fmax):
        fmin, fmax = sorted((float(fmin), float(fmax)))
        if (fmin, fmax) != (self.fmin, self.fmax):
            self.fmin, self.fmax = fmin, fmax
            self.reset()

    def reset(self, f_guess=None):
        with self.lock:
            self.state = 'ACQ'           # 'ACQ' procurando a frequência; 'TRACK' seguindo
            self.locked = False
            self.f = float(f_guess) if f_guess else 0.0
            self.w = TWO_PI * max(self.f, self.fmin) / RAW_FS   # rad por amostra crua (trecho atual)
            self.w_base = self.w
            self.s0 = None               # início do trecho atual (s) e θ nesse ponto
            self.th0 = 0.0
            self.blk_end = None
            self.blk_len = 0.0
            self.acc = 0j
            self.acc_x = 0.0
            self.cnt = 0
            self.dc = None
            self.err_prev = 0.0
            self.err_ema = 0.0
            self.amp = 0.0
            self.nblocks = 0
            self.acq_x = []
            self.acq_c = []
            self.acq_n = 0
            self.segs = deque()          # (s_início, θ_início, w)
            self.stats = deque()         # (s, f instantânea, erro de fase) por bloco
            self.msg = 'procurando a frequência no sinal do OPT101'
            self.f_mean = self.f_std = self.jitter_deg = None
            self.reacq = 0
            self.spacing = 16.0
            self.last_c = -np.inf

    # ---------------------------------------------------------------- aquisição pela FFT
    def _acq_span(self):
        return float(np.clip(12.0 / self.fmin, 0.25, 3.0))   # s: ≥ 12 períodos da menor frequência

    def _acquire(self, x, c):
        self.acq_x.append(np.asarray(x, dtype=np.float64))
        self.acq_c.append(np.asarray(c, dtype=np.float64))
        self.acq_n += x.size
        if self.acq_n < 8:
            return
        c_first, c_last = self.acq_c[0][0], self.acq_c[-1][-1]
        if (c_last - c_first) / RAW_FS < self._acq_span():
            return
        xx = np.concatenate(self.acq_x)
        cc = np.concatenate(self.acq_c)
        # janela deslizante: guarda a metade mais nova para a próxima tentativa
        half = xx.size // 2
        self.acq_x, self.acq_c, self.acq_n = [xx[half:]], [cc[half:]], xx.size - half
        fs = RAW_FS / float(np.median(np.diff(cc[:64]))) if cc.size > 2 else RAW_FS
        y = (xx - xx.mean()) * np.hanning(xx.size)
        nfft = 1 << int(np.ceil(np.log2(xx.size * 4)))
        spec = np.abs(np.fft.rfft(y, nfft))
        freqs = np.fft.rfftfreq(nfft, 1.0 / fs)
        band = (freqs >= self.fmin) & (freqs <= min(self.fmax, 0.45 * fs))
        if band.sum() < 3:
            self.msg = 'faixa de busca fora da taxa de amostragem (reduza o OSR)'
            return
        idx = np.flatnonzero(band)
        k = idx[np.argmax(spec[idx])]
        floor = float(np.median(spec[idx])) + 1e-12
        if spec[k] < 8.0 * floor or k <= 0 or k >= spec.size - 1:
            self.msg = (f'sem pico claro na faixa {fmt_hz(self.fmin)}–{fmt_hz(self.fmax)} '
                        '(a luz está modulada? o OPT101 vê o feixe?)')
            return
        a, b, g = np.log(spec[k - 1] + 1e-30), np.log(spec[k] + 1e-30), np.log(spec[k + 1] + 1e-30)
        den = a - 2.0 * b + g
        delta = 0.5 * (a - g) / den if den < 0 else 0.0
        f0 = (k + float(np.clip(delta, -0.5, 0.5))) * fs / nfft
        # fase da fundamental no fim da janela (últimos ~10 períodos, sem janela para não deslocar a fase)
        n_tail = int(min(cc.size, max(8, round(10.0 * fs / f0))))
        ct, xt = cc[-n_tail:], xx[-n_tail:]
        z = np.sum((xt - xt.mean()) * np.exp(-1j * TWO_PI * f0 * (ct - ct[-1]) / RAW_FS))
        self.f = f0
        self.w = self.w_base = TWO_PI * f0 / RAW_FS
        self.s0 = float(ct[-1])
        self.th0 = float(np.angle(z))
        self.dc = float(xt.mean())
        self.state = 'TRACK'
        self.nblocks = 0
        self.err_ema = 0.0
        self.err_prev = 0.0
        self.stats.clear()               # estatística só do trecho travado nesta frequência
        self._new_block(self.s0)
        self.acq_x, self.acq_c, self.acq_n = [], [], 0
        self.msg = f'frequência encontrada: {fmt_hz(f0)}; travando'

    # ---------------------------------------------------------------- PLL
    def _gains(self):
        '''Ganhos por bloco do PLL de 2ª ordem (ζ = 0,707) com banda de ruído B_L = f/50 (0,5 a 10 Hz).'''
        bl = float(np.clip(self.f / 50.0, 0.5, 10.0))
        wn_t = 2.0 * bl / (0.707 + 1.0 / (4.0 * 0.707)) * self.blk_len / RAW_FS
        return 2.0 * 0.707 * wn_t, wn_t * wn_t

    def _new_block(self, start):
        f = max(self.f, 1e-3)
        per = RAW_FS / f
        n_per = max(1, int(round(0.005 * f)))          # ~5 ms, número inteiro de períodos
        self.blk_len = max(n_per * per, 8.0 * self.spacing)
        self.blk_end = start + self.blk_len
        self.acc, self.acc_x, self.cnt = 0j, 0.0, 0

    def _end_block(self):
        end = self.blk_end
        th_end = self.th0 + self.w * (end - self.s0)
        if self.cnt > 0:
            err = float(np.angle(self.acc)) if self.acc != 0 else 0.0
            self.amp = 2.0 * abs(self.acc) / self.cnt
            self.dc = self.acc_x / self.cnt
            kp, ki = self._gains()
            self.w_base += ki * err / self.blk_len
            self.w = self.w_base + kp * err / self.blk_len
            self.f = self.w_base * RAW_FS / TWO_PI
            self.err_ema += 0.1 * (abs(err) - self.err_ema)
            self.nblocks += 1
            self.stats.append((end, self.f, err))
            while self.stats and end - self.stats[0][0] > 2.0 * RAW_FS:
                self.stats.popleft()
            # travado: erro de fase médio pequeno depois de alguns blocos; perde a trava se o erro cresce,
            # se a frequência sai da faixa ou se a fundamental some
            if self.nblocks >= 10:
                self.locked = self.err_ema < 0.5
                lost = (self.err_ema > 1.2 or not (0.8 * self.fmin <= self.f <= 1.25 * self.fmax))
                if lost:
                    self.reacq += 1
                    f_old = self.f
                    self.state, self.locked = 'ACQ', False
                    self.w = self.w_base = TWO_PI * min(max(f_old, self.fmin), self.fmax) / RAW_FS
                    self.msg = 'referência perdida; procurando de novo'
                    self.acq_x, self.acq_c, self.acq_n = [], [], 0
        self.s0, self.th0 = end, th_end
        self.segs.append((end, th_end, self.w))
        while len(self.segs) > 2 and end - self.segs[1][0] > EXT_TIMELINE_SEC * RAW_FS:
            self.segs.popleft()
        self._new_block(end)

    def process(self, x, c):
        '''x: amostras do OPT101 (média de OSR); c: índice cru (float) do centro de cada uma, espaçamento OSR.
        Devolve θ (rad, desenrolada) em cada amostra.'''
        n = x.size
        if n == 0:
            return _E_F
        x = np.asarray(x, dtype=np.float64)
        c = np.asarray(c, dtype=np.float64)
        if n > 1:
            self.spacing = float(c[1] - c[0])
        with self.lock:
            if self.s0 is None:          # primeira chamada: θ corre livre na frequência inicial
                self.s0, self.th0 = float(c[0]), 0.0
                self._new_block(self.s0)
                self.segs.append((self.s0, self.th0, self.w))
            out = np.empty(n)
            i = 0
            while i < n:
                j = i + int(np.searchsorted(c[i:], self.blk_end))
                if j > i:
                    th = self.th0 + self.w * (c[i:j] - self.s0)
                    out[i:j] = th
                    if self.state == 'TRACK':
                        xs = x[i:j]
                        dc = self.dc if self.dc is not None else float(xs.mean())
                        self.acc += np.sum((xs - dc) * np.exp(-1j * th))
                        self.acc_x += float(xs.sum())
                        self.cnt += j - i
                if j >= n:
                    break
                self._end_block()
                i = j
            if self.state == 'ACQ':
                self._acquire(x, c)
                if self.state == 'TRACK':        # começou a seguir: novo trecho a partir do fim da janela
                    self.segs.append((self.s0, self.th0, self.w))
            self.last_c = float(c[-1])
            self._update_stats()
            return out

    def _update_stats(self):
        st = self.stats
        if self.state != 'TRACK' or len(st) < 3:
            self.f_mean = self.f_std = self.jitter_deg = None
            return
        s_last = st[-1][0]
        recent = [(f, e) for s, f, e in st if s_last - s <= RAW_FS]   # último segundo
        if len(recent) < 3:
            recent = list((f, e) for _, f, e in st)[-3:]
        fs_, es = np.array(recent).T
        self.f_mean = float(fs_.mean())
        self.f_std = float(fs_.std())
        self.jitter_deg = float(np.degrees(np.sqrt(np.mean(es * es))))
        if self.locked:
            self.msg = 'travado'
        elif self.nblocks < 10:
            self.msg = f'frequência encontrada: {fmt_hz(self.f)}; travando'
        else:
            self.msg = 'seguindo, mas a fase oscila muito (sinal fraco ou chopper instável)'

    def theta_at(self, s):
        '''θ nos índices crus s (float64, crescentes). Devolve (θ, situação): 'ok', 'wait' (o OPT101 ainda não
        chegou lá) ou 'old' (anterior ao que está guardado).'''
        with self.lock:
            if not self.segs or s[-1] > self.last_c:
                return None, 'wait'
            segs = self.segs
            starts = np.fromiter((g[0] for g in segs), dtype=np.float64, count=len(segs))
            if s[0] < starts[0]:
                return None, 'old'
            th0 = np.fromiter((g[1] for g in segs), dtype=np.float64, count=len(segs))
            w = np.fromiter((g[2] for g in segs), dtype=np.float64, count=len(segs))
            k = np.searchsorted(starts, s, side='right') - 1
            return th0[k] + w[k] * (s - starts[k]), 'ok'


class RawRing:
    '''Ring buffer do osciloscópio. Em vez de apagar um 'rastro' com NaN
    amostra por amostra, o desenho usa duas fatias que deixam um vão à frente
    do cursor; o custo por lote é constante, independente do tamanho do vão.
    Guarda no máximo MAX_SCOPE_POINTS pontos: se janela x taxa passar disso, cada ponto exibido é a média
    de 'step' amostras (o laser é o máximo do bloco), para o desenho não travar a 200 kS/s.'''

    def __init__(self, window_sec, fs, max_points=MAX_SCOPE_POINTS):
        self.fs = fs
        self.max_points = int(max_points)
        self.resize(window_sec)

    def set_fs(self, fs):
        self.fs = fs
        self.resize(self.window)

    def resize(self, window_sec):
        self.window = float(window_sec)
        total = max(2, int(self.window * self.fs))
        self.step = max(1, -(-total // self.max_points))
        self.n = max(2, total // self.step)
        self._pend_adc = np.empty(0, dtype=np.float32)
        self._pend_ref = np.empty(0, dtype=np.float32)
        self.gap = max(5, int(0.02 * self.n))
        self.adc = np.zeros(self.n, dtype=np.float32)
        self.ref = np.zeros(self.n, dtype=np.float32)
        self.t = np.linspace(0.0, self.window, self.n, dtype=np.float32)
        self.head = 0
        self.wrapped = False

    def push(self, adc, ref):
        '''Insere um lote. Retorna True se o cursor deu a volta na janela.'''
        k = self.step
        if k > 1:
            adc = np.concatenate((self._pend_adc, np.asarray(adc, dtype=np.float32)))
            ref = np.concatenate((self._pend_ref, np.asarray(ref, dtype=np.float32)))
            m = len(adc) // k
            self._pend_adc, self._pend_ref = adc[m * k:], ref[m * k:]
            if m == 0:
                return False
            adc = adc[:m * k].reshape(m, k).mean(axis=1)
            ref = ref[:m * k].reshape(m, k).max(axis=1)
        N = self.n
        n = len(adc)
        if n >= N:
            adc, ref, n = adc[-N:], ref[-N:], N
        h = self.head
        end = h + n
        if end <= N:
            self.adc[h:end] = adc
            self.ref[h:end] = ref
        else:
            k = N - h
            self.adc[h:] = adc[:k]
            self.adc[:end - N] = adc[k:]
            self.ref[h:] = ref[:k]
            self.ref[:end - N] = ref[k:]
        self.head = end % N
        wrapped_now = end >= N
        if wrapped_now:
            self.wrapped = True
        return wrapped_now

    def segments(self):
        '''(fatia_a, fatia_b) a desenhar; fatia_b pode ser None.'''
        N, h, g = self.n, self.head, self.gap
        a0 = max(0, h + g - N) if self.wrapped else 0
        a = slice(a0, h)
        b = slice(h + g, N) if (self.wrapped and h + g < N) else None
        return a, b

    def cursor_x(self):
        return self.head / self.n * self.window


class AverageAccumulator:
    '''Forma de onda média por pulso, vetorizada por lote.

    Um ciclo vai de (borda_k - pré) até a borda_{k+1} (exclusive), como no algoritmo original amostra
    a amostra. Guarda só a soma corrente dos ciclos e os pedaços do ciclo aberto (sem concatenar o
    ciclo inteiro a cada lote), para aguentar 200 kS/s com ciclos longos.
    '''
    MAX_CYCLE_SEC = 120.0     # ciclo aberto mais longo que isso (laser parado) é descartado

    def __init__(self, fs):
        self.fs = fs
        self.pulses = 8
        self.pre = 0
        self.keep = False         # guarda os ciclos individuais da média (Medidas em Série: transientes individuais)
        self.last_cycles = []
        self.reset()

    def reset(self):
        self.chunks = []          # ciclo aberto (com as 'pre' amostras antes da borda) ou o histórico pré
        self.chunks_len = 0
        self.is_open = False
        self.open_valid = False   # havia 'pre' amostras antes da borda que abriu o ciclo
        self.prev_ref = 0
        self.sum = None
        self.count = 0
        self.spc = 0
        self.values = np.empty(0)
        self.time = np.empty(0)
        self.kept = []

    @property
    def cycles(self):
        '''Compatibilidade: só o número de ciclos acumulados importa (len(avg.cycles)).'''
        return range(self.count)

    def current_len(self):
        return self.chunks_len if self.is_open else 0

    def _joined(self, extra):
        parts = self.chunks + [extra] if len(extra) else self.chunks
        if not parts:
            return np.empty(0, dtype=np.float32)
        return parts[0] if len(parts) == 1 else np.concatenate(parts)

    def _accumulate(self, cyc):
        if self.keep:
            self.kept.append(np.array(cyc, dtype=np.float32))
        if self.count == 0:
            self.sum = cyc.astype(np.float64)
            self.spc = len(cyc)
        else:
            self.spc = min(self.spc, len(cyc))
            self.sum = self.sum[:self.spc] + cyc[:self.spc]
        self.count += 1
        if self.count >= self.pulses:
            self.values = self.sum / self.count
            self.time = (np.arange(self.spc) - self.pre) / self.fs
            if self.keep:
                self.last_cycles = [c[:self.spc] for c in self.kept]
            self.kept = []
            self.sum, self.count, self.spc = None, 0, 0
            return True
        return False

    def push(self, adc, ref):
        '''Processa um lote. Retorna True quando uma nova média ficou pronta.'''
        a = np.asarray(adc, dtype=np.float32)
        r = np.asarray(ref, dtype=np.uint8)
        if a.size == 0:
            return False
        rp = np.empty(r.size, dtype=np.uint8)
        rp[0] = self.prev_ref
        rp[1:] = r[:-1]
        edges = np.flatnonzero((r == 1) & (rp == 0))
        self.prev_ref = int(r[-1])
        pre = self.pre
        ready = False
        pos = 0
        for e in edges.tolist():
            full = self._joined(a[pos:e])
            if self.is_open and self.open_valid and len(full) > pre:
                ready |= self._accumulate(full)
            self.is_open = True
            self.open_valid = len(full) >= pre
            head = full[len(full) - pre:] if pre > 0 else full[:0]
            self.chunks = [head.copy()] if len(head) else []
            self.chunks_len = len(head)
            pos = e
        rest = a[pos:]
        if len(rest):
            self.chunks.append(rest.copy())
            self.chunks_len += len(rest)
        if not self.is_open and self.chunks_len > pre:
            full = self._joined(_E_F32)
            keep = full[len(full) - pre:] if pre > 0 else full[:0]
            self.chunks = [keep.copy()] if len(keep) else []
            self.chunks_len = len(keep)
        elif self.is_open and self.chunks_len > self.MAX_CYCLE_SEC * self.fs:
            self.is_open = False
            self.chunks, self.chunks_len = [], 0
        return ready


class AudioRecorder:
    """Gravação opcional do áudio bruto do INMP441 (variável de ambiente SOI_GRAVAR_AUDIO=<pasta>), para análise
    offline do ruído acústico. Um arquivo por execução: <pasta>/audio_<amostra ou soi>_<AAAAMMDD_HHMMSS>.bin.
    Cada bloco: uint32 sequence (nº I2S da 1ª amostra), uint32 n_out, float64 t_pc (time.time() na chegada) e
    n_out float32 = média de cada 4 amostras / 8388608 (12 kS/s; o resto do bloco, se não for múltiplo de 4, vai
    para o bloco seguinte quando ele é contíguo). Little-endian. A thread de áudio só enfileira; uma thread própria grava (flush a cada ~1 s)."""
    HEADER = '<IId'

    def __init__(self, folder, name_fn):
        self.folder, self.name_fn = folder, name_fn
        self.q = deque()
        self.fh = None
        self.path = None
        self.stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.want_retitle = False
        self.bytes = 0
        self.stop_ev = threading.Event()
        self.th = threading.Thread(target=self._run, name='AudioRecorder', daemon=True)
        self.th.start()

    rem = np.zeros(0)
    rem_end = None

    def push(self, sequence, samples):
        # o resto (bloco não múltiplo de 4) passa para o bloco seguinte, se ele for contíguo: sem saltos de fase
        xs = np.asarray(samples, dtype=np.float64)
        seq0 = sequence
        if len(self.rem) and self.rem_end == (sequence & 0xFFFFFFFF):
            xs = np.concatenate((self.rem, xs))
            seq0 = sequence - len(self.rem)
        n = (len(xs) // 4) * 4
        self.rem = xs[n:]
        self.rem_end = (sequence + len(samples)) & 0xFFFFFFFF
        if n <= 0:
            return
        x = (xs[:n].reshape(-1, 4).mean(axis=1) / 8388608.0).astype('<f4')
        self.q.append((seq0 & 0xFFFFFFFF, time.time(), x))

    def _name(self):
        name = re.sub(r'[^\w.-]+', '_', (self.name_fn() or '').strip()) or 'soi'
        return os.path.join(self.folder, f'audio_{name}_{self.stamp}.bin')

    def retitle(self):
        """A amostra mudou (ex.: --amostra do modo sem janela, depois de o arquivo já ter sido aberto): renomeia."""
        self.want_retitle = True

    def _open(self):
        os.makedirs(self.folder, exist_ok=True)
        self.path = self._name()
        self.fh = open(self.path, 'ab')
        print(f'Gravando o áudio bruto do INMP441 (12 kS/s, float32): {self.path}', flush=True)

    def _do_retitle(self):
        self.want_retitle = False
        new = self._name()
        if self.fh is None or new == self.path:
            return
        self.fh.close()                         # no Windows um arquivo aberto não pode ser renomeado
        try:
            os.replace(self.path, new)
            print(f'Áudio bruto: arquivo renomeado para {new}', flush=True)
            self.path = new
        except OSError as e:
            print(f'Áudio bruto: não foi possível renomear ({e}); continua em {self.path}', flush=True)
        self.fh = open(self.path, 'ab')

    def _drain(self):
        import struct
        if self.want_retitle:
            self._do_retitle()
        if not self.q:
            return
        if self.fh is None:
            self._open()
        while self.q:
            seq, t, x = self.q.popleft()
            self.fh.write(struct.pack(self.HEADER, seq, len(x), t))
            self.fh.write(x.tobytes())
            self.bytes += 16 + 4 * len(x)
        self.fh.flush()

    def _run(self):
        while not self.stop_ev.wait(1.0):
            try:
                self._drain()
            except Exception as e:
                print(f'Gravação do áudio interrompida: {e}', flush=True)
                self.q.clear()
                return

    def close(self):
        if self.stop_ev.is_set():
            return
        self.stop_ev.set()
        self.th.join(timeout=3.0)
        try:
            self._drain()
        except Exception as e:
            print(f'Gravação do áudio: {e}', flush=True)
        if self.fh is not None:
            self.fh.close()
            print(f'Áudio bruto gravado: {self.path} ({self.bytes / 1e6:.1f} MB)', flush=True)


# Exporta tudo (inclusive nomes com _) para os módulos que fazem import *
__all__ = [_n for _n in dir() if not _n.startswith('__')]
