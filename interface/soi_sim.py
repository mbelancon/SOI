# -*- coding: utf-8 -*-
'''Modo simulado: chopper, OPT101 e INMP441 simulados (sem a placa).

Parte do SOI Controller (antes em soi_controller.py).'''

from soi_const import *  # noqa: F401,F403
from soi_analise import *  # noqa: F401,F403
from soi_dsp import *  # noqa: F401,F403
from soi_serial import *  # noqa: F401,F403


class ChopperSimulator:
    '''Simulação da modulação óptica: um ventilador/chopper com frequência nominal ajustável (o campo
    Freq faz de botão do chopper) que deriva devagar, pás um pouco desiguais e luz trapezoidal. A fase da
    luz é uma função determinística do tempo, então o OPT101 e o INMP441 simulados (gerados em threads
    diferentes) veem a mesma luz. Também simula o farol do STM32 (bit 15 a 1 Hz e marcador do I2S).
    Tempo t = 0 no início da simulação; amostra óptica n em t = n/RAW_FS; amostra I2S k em
    t = (k − K0)/AUDIO_FS_REAL.'''
    K0 = 123456                   # número da primeira amostra I2S (o firmware conta desde a partida)
    LAUNCH_S = 0.2                # instante em que o farol parte (s)
    WANDER = ((2.5, 0.05, 0.3), (0.4, 0.4, 1.1), (0.05, 3.0, 2.0))   # (rad, Hz, fase): deriva da rotação
    BLADES = 7
    BLADE_PM = 0.04               # rad: pás desiguais (modulação de fase na frequência de rotação)

    def __init__(self, f_set):
        self.lock = threading.Lock()
        self.segs = [(0.0, float(f_set), 0.0)]     # (t_início, f nominal, fase da rotação nominal)
        self.k_launch = self.K0 + int(round(self.LAUNCH_S * AUDIO_FS_REAL))
        self.t_launch = (self.k_launch - self.K0) / AUDIO_FS_REAL
        self.half = 0.5 / actual_mod_freq(EXT_BEACON_HZ)
        self.marker_sent = False

    def set_freq(self, f, t):
        with self.lock:
            t0, f0, p0 = self.segs[-1]
            t = max(t, t0)
            self.segs.append((t, float(max(f, 0.1)), p0 + TWO_PI * f0 * (t - t0)))

    def marker(self):
        '''(k do marcador, posição óptica aproximada), como o SerialLink registraria.'''
        return self.k_launch, self.t_launch * RAW_FS + 300.0

    def phase(self, t):
        with self.lock:
            segs = list(self.segs)
        ts = np.array([g[0] for g in segs])
        k = np.searchsorted(ts, t, side='right') - 1
        fs_ = np.array([g[1] for g in segs])[k]
        p = np.array([g[2] for g in segs])[k] + TWO_PI * fs_ * (t - ts[k])
        for a, nu, ph in self.WANDER:
            p = p + a * np.sin(TWO_PI * nu * t + ph)
        return p + self.BLADE_PM * np.sin(p / self.BLADES), fs_

    @staticmethod
    def light(p):
        return np.clip(0.5 + 0.9 * np.cos(p), 0.0, 1.0)     # feixe maior que a fenda: trapézio

    def beacon_label(self, n):
        '''Bit 15 nas amostras ópticas n: 1 desde o comando, onda quadrada a partir do farol. O rótulo segue
        a convenção de ExtTimeSync (troca da luz 0,154 amostra depois do instante amostrado).'''
        t = (n + EXT_EDGE_CORR + 0.5) / RAW_FS
        m = np.floor((t - self.t_launch) / self.half)
        return np.where(t < self.t_launch, 1, (m.astype(np.int64) % 2 == 0)).astype(np.uint16)


class SignalSimulator:
    '''Gera as palavras cruas do firmware 2.0.0 (uint16 LE a 200 kS/s: ADC de 12 bits + bit 15 do laser),
    sem STM32; a interface faz a sobreamostragem como faria com o STM32.
    Referência quadrada; com laser ligado o sinal sobe exponencialmente até uma saturação
    proporcional à potência (100 % -> SIM_FULL_POWER_FRAC do fundo de escala).'''
    SIM_FULL_POWER_FRAC = 0.70
    TAU = 0.05            # s, constante de tempo do crescimento
    BASELINE = 0.02       # fração do fundo de escala (escuro)
    NOISE = 0.004         # desvio padrão (fração do fundo de escala)

    def __init__(self, fs=RAW_FS):
        from scipy.signal import lfilter
        self._lfilter = lfilter
        self.fs = RAW_FS
        self.rng = np.random.default_rng()
        self.a = float(np.exp(-1.0 / (fs * self.TAU)))
        self.reset()

    def reset(self, epoch=None):
        self.t_last = epoch
        self.n = 0
        self.y = 0.0

    def generate(self, now, freq, power_pct, chopper=None):
        if self.t_last is None:
            self.t_last = now
            return b''
        m = int((now - self.t_last) * self.fs)
        if m <= 0:
            return b''
        m = min(m, int(self.fs // 4))
        self.t_last += m / self.fs
        if now - self.t_last > 1.0 and chopper is None:   # GUI parada: não tenta recuperar o atraso
            self.t_last = now
        idx = self.n + np.arange(m)
        self.n += m
        if chopper is not None:
            # Luz modulada por fora (LED contínuo + chopper): o bit 15 é só o farol do STM32 (PWM 0)
            t = idx / self.fs
            p, _ = chopper.phase(t)
            sig = (self.BASELINE + 0.45 * chopper.light(p) + 0.003 * np.sin(2 * np.pi * 60.0 * t)
                   + self.NOISE * self.rng.standard_normal(m))
            adc = np.clip(np.rint(sig * 4095.0), 0, 4095).astype('<u2')
            return (adc | (chopper.beacon_label(idx) << 15)).tobytes()
        if freq > 0:
            ref = ((idx * actual_mod_freq(freq) / self.fs) % 1.0 < 0.5).astype(np.uint8)
        else:
            ref = np.ones(m, dtype=np.uint8)
        top = self.SIM_FULL_POWER_FRAC * max(0.0, min(power_pct, 100.0)) / 100.0
        target = ref * top
        a = self.a
        y, zf = self._lfilter([1.0 - a], [1.0, -a], target, zi=[a * self.y])
        self.y = float(y[-1])
        t = idx / self.fs
        sig = (self.BASELINE + y + 0.003 * np.sin(2 * np.pi * 60.0 * t) + 0.001 * np.sin(2 * np.pi * 300.0 * t)
               + self.NOISE * self.rng.standard_normal(m))
        adc = np.clip(np.rint(sig * 4095.0), 0, 4095).astype('<u2')
        return (adc | (ref.astype('<u2') << 15)).tobytes()


class AudioSimulator:
    '''Gera áudio PCM de 24 bits a AUDIO_FS, como os pacotes I2S do INMP441 enviados pelo STM32.
    Sinal típico de microfone em silêncio (pequeno DC + ruído branco + ruído 1/f + resquício de 60 Hz)
    somado a um tom na frequência de excitação, com amplitude proporcional à potência do laser e
    dependente da frequência (resposta passa-baixas).'''
    NOISE_RMS = 3e-5          # ruído branco, fração do fundo de escala (~ -90 dBFS)
    PINK_CORNER_HZ = 300.0    # acima disto o ruído é branco; abaixo, sobe a 10 dB/década (1/f em potência)
    PINK_FMIN_HZ = 0.01       # o 1/f se estende até esta frequência
    DC = 0.004                # offset DC típico do INMP441
    HUM = 2e-5                # resquício de rede (60 Hz)
    TONE_FULL_POWER = 2e-3    # amplitude do tom com laser a 100 % (~ -54 dBFS)
    TONE_TAU = 2e-4           # s, resposta passa-baixas de 1ª ordem do tom (corte ~800 Hz): amplitude e fase variam com a frequência
    CHUNK = AUDIO_PACKET_MAX_SAMPLES
    try:
        FAN_HZ = float(os.environ.get('SOI_SIM_RUIDO', '') or 0.0)
    except ValueError:
        FAN_HZ = 0.0
    FAN_AMPS = (6e-5, 2e-5, 4e-5, 3e-5, 1.5e-5)

    def __init__(self):
        self.rng = np.random.default_rng()
        # Amostra simulada (calibração por duas amostras): (K, n, fase em graus) -> tom × K·(f/100 Hz)^-n.
        # None = tom sem dependência da amostra.
        self.sample = None
        self.reset()

    def reset(self, epoch=None):
        self.t_last = epoch
        self.n = 0
        self.phase = 0.0
        self.marker_done = False
        self.freq = None          # última frequência: a troca reinicia a onda do laser (como o firmware)
        self.n0 = 0
        self._init_pink()

    def _init_pink(self):
        '''Ruído 1/f = soma de processos AR(1) (Lorentzianas) com polos espaçados de uma oitava e
        variâncias iguais. A escala faz a DEP 1/f igualar a DEP do ruído branco em PINK_CORNER_HZ.'''
        n_poles = int(np.ceil(np.log2(0.3 * AUDIO_FS / self.PINK_FMIN_HZ)))
        fk = self.PINK_FMIN_HZ * 2.0 ** np.arange(n_poles)
        self._pink_p = np.exp(-2.0 * np.pi * fk / AUDIO_FS)
        s_white = self.NOISE_RMS ** 2 / (AUDIO_FS / 2.0)                  # DEP unilateral (1/Hz)
        shape = np.sum(2.0 / (np.pi * fk) / (1.0 + (self.PINK_CORNER_HZ / fk) ** 2))
        self._pink_sigma = float(np.sqrt(s_white / shape))
        # Estado inicial já estacionário (sem transitório de partida)
        self._pink_y = self.rng.normal(0.0, self._pink_sigma, n_poles)

    def _pink(self, m):
        out = np.zeros(m)
        for k, p in enumerate(self._pink_p):
            w = self.rng.standard_normal(m) * (self._pink_sigma * np.sqrt(1.0 - p * p))
            y, _ = lfilter([1.0], [1.0, -p], w, zi=[p * self._pink_y[k]])
            self._pink_y[k] = y[-1]
            out += y
        return out

    def generate(self, now, freq, power_pct, chopper=None):
        '''Retorna lista de (sequência, amostras int32 de 24 bits com sinal).'''
        if self.t_last is None:
            self.t_last = now
            return []
        m = int((now - self.t_last) * AUDIO_FS)
        if m <= 0:
            return []
        m = min(m, AUDIO_FS)
        self.t_last += m / AUDIO_FS
        if chopper is not None:
            return self._generate_ext(m, chopper)
        markers = []
        if freq != self.freq:
            # O firmware reinicia o TIM4 num instante arbitrário e informa a amostra I2S da borda
            self.freq = freq
            self.n0 = self.n + int(self.rng.integers(0, 256))
            markers.append((self.n0 & 0xFFFFFFFF, None))
        idx = self.n + np.arange(m)
        # Fase travada na referência (número da amostra). A resposta do sistema (passa-baixas de 1ª
        # ordem, como a do sinal do OPT101) reduz a amplitude e atrasa a fase conforme a frequência sobe.
        w = 2.0 * np.pi * freq * self.TONE_TAU
        gain = 1.0 / np.sqrt(1.0 + w * w)
        # Como no hardware: taxa I2S real, frequência quantizada pelo TIM4 e onda quadrada que começa
        # (borda de subida) em n0. A fundamental da onda quadrada é sen(wt) = cos(wt - 90°).
        ph = (2.0 * np.pi * np.mod(actual_mod_freq(freq) * (idx - self.n0) / AUDIO_FS_REAL, 1.0)
              - np.pi / 2.0 - np.arctan(w))
        amp = gain * self.TONE_FULL_POWER * max(0.0, min(power_pct, 100.0)) / 100.0
        if self.sample is not None and freq > 0:
            k, n_s, ph_s = self.sample
            amp *= k * (freq / 100.0) ** (-n_s)
            ph = ph + np.radians(ph_s - 45.0 * n_s)      # fase do pistão térmico: −45°·n, mais a da amostra
        x = (self.DC + amp * np.cos(ph)
             + self.HUM * np.sin(2.0 * np.pi * 60.0 * idx / AUDIO_FS)
             + self.NOISE_RMS * self.rng.standard_normal(m)
             + self._pink(m))
        if self.FAN_HZ:          # SOI_SIM_RUIDO=<f0>: ventoinha simulada (série harmônica em f0)
            for k, a in enumerate(self.FAN_AMPS, 1):
                x = x + a * np.sin(2.0 * np.pi * k * self.FAN_HZ * idx / AUDIO_FS + k)
        pcm = np.clip(np.rint(x * 8388607.0), -8388608, 8388607).astype(np.int32)
        chunks = markers + [((self.n + k) & 0xFFFFFFFF, pcm[k:k + self.CHUNK]) for k in range(0, m, self.CHUNK)]
        self.n += m
        return chunks

    def _generate_ext(self, m, chopper):
        '''Modulação óptica: o tom segue a fase da luz do chopper simulado (mesma luz do OPT101).'''
        idx = self.n + np.arange(m)
        t = idx / AUDIO_FS_REAL
        p, f = chopper.phase(t)
        w = 2.0 * np.pi * f * self.TONE_TAU
        amp = self.TONE_FULL_POWER * 0.6 / np.sqrt(1.0 + w * w)
        ph = p - np.arctan(w)
        if self.sample is not None:
            k, n_s, ph_s = self.sample
            amp = amp * k * (f / 100.0) ** (-n_s)
            ph = ph + np.radians(ph_s - 45.0 * n_s)
        x = (self.DC + amp * np.cos(ph)
             + self.HUM * np.sin(2.0 * np.pi * 60.0 * idx / AUDIO_FS)
             + self.NOISE_RMS * self.rng.standard_normal(m)
             + self._pink(m))
        pcm = np.clip(np.rint(x * 8388607.0), -8388608, 8388607).astype(np.int32)
        k0 = chopper.K0 + self.n
        chunks = []
        if not self.marker_done:
            self.marker_done = True
            chunks.append((chopper.k_launch & 0xFFFFFFFF, None))
        chunks += [((k0 + k) & 0xFFFFFFFF, pcm[k:k + self.CHUNK]) for k in range(0, m, self.CHUNK)]
        self.n += m
        return chunks


# Exporta tudo (inclusive nomes com _) para os módulos que fazem import *
__all__ = [_n for _n in dir() if not _n.startswith('__')]
