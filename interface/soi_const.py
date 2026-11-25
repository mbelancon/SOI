# -*- coding: utf-8 -*-
'''Constantes, parâmetros do protocolo e da aquisição e funções simples de τ e filtros.

Parte do SOI Controller (antes em soi_controller.py).'''

import binascii
import bisect
import os
import re
import sys
import threading
import time
import warnings
import zipfile
from collections import deque, namedtuple
from datetime import datetime

import numpy as np
from scipy.signal import iirnotch, lfilter, sosfilt, sosfilt_zi
import serial
from serial.tools import list_ports

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets


import soi_i18n  # idioma da interface (português ou inglês, conforme o Windows ou SOI_LANG)
import soi_serie  # Medidas em Série (fila de varreduras, Sinal x t, pausas e avisos)
import soi_ruido  # Detectar ruídos de fundo (espectro do INMP441, tons e séries harmônicas)
import soi_layout  # FlowBar: barras que quebram linha em telas estreitas ou com escala alta

soi_i18n.install(QtWidgets, QtGui, pg)

# Executáveis empacotados sem console (PyInstaller --windowed) não têm stdout/stderr.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')


BAUD_RATE = 500000        # Ignorado pelo USB CDC do STM32
ARDUINO_VIDS = {0x0483, 0x2341, 0x2A03, 0x1A86}  # 0x0483 = STM32 CDC.
RECONNECT_INTERVAL = 3.0

# Firmware 2.0.0 (STM32Cube): o STM32 envia TODAS as amostras do ADC (12 bits, 200 kS/s) com o rótulo
# do laser; a sobreamostragem (média de OSR amostras) é feita aqui. FS e DECIMATION mudam com o OSR
# escolhido na aba OPT101 (LockInWindow.set_osr); o padrão OSR 16 reproduz os 12,5 kS/s da 1.0.0.
RAW_FS = 200000.0         # Taxa do ADC no firmware (TIM3 TRGO)
OSR_CHOICES = (1, 2, 4, 8, 16, 32, 64)
OSR_DEFAULT = 16
LOCKIN_OUT_HZ = 50.0      # Taxa aproximada da saída do lock-in (pontos de R e fase por segundo)


class _Rate:
    '''Taxa do OPT101 depois da sobreamostragem: FS (Hz) e DECIMATION (decimação da saída do lock-in, 12500 -> 50 Hz).
    Mudam com o OSR (LockInWindow.set_osr). Ficam num objeto, e não em variáveis globais, para que todos os módulos
    vejam o valor atual (com "from soi_const import *" cada módulo teria a sua cópia).'''
    FS = RAW_FS / OSR_DEFAULT
    DECIMATION = int(round(FS / LOCKIN_OUT_HZ))


RATE = _Rate()

ADC_OVS_FACTOR = 1.0
ADC_FULL_SCALE = 16380.0  # 4095 * 4: a média é exibida na escala de 14 bits da 1.0.0, qualquer que seja o OSR
ADC_LSB = ADC_FULL_SCALE / 4095.0          # 1 LSB do ADC de 12 bits na escala exibida (= 4)
ADC_VREF = 3.3
# Alimentação do OPT101 (Configurações): a saída vai de ~7,5 mV até Vs − 1,3 V. Com 3,3 V ela nunca passa de
# ~2,0 V; com 5 V chega a ~3,7 V, acima do ADC (3,3 V): o ganho deve deixar o pico em ~3,0 V e o PA0 precisa
# de proteção (1 kΩ em série + Schottky BAT54 para 3,3 V). Teto do sinal em V por alimentação (onde o sinal para
# de crescer: o OPT101 com 3,3 V; o ADC com 5 V): linha "Max OPT101 output" no osciloscópio e base do % do pico.
OPT_SUPPLY = {3.3: 2.0, 5.0: 3.3}
OPT_PCT_ORANGE = 80.0     # pico ≥ 80 % do teto: laranja (e o autoajuste do osciloscópio passa a mostrar a linha)
OPT_PCT_RED = 90.0        # pico ≥ 90 %: vermelho, aviso no status e "Limiar de Saturação" no gráfico
AUDIO_FS = 48000          # = AUDIO_FS_HZ do firmware (nominal)
# Taxa real do I2S: PLLI2S = 1 MHz * 384 / 5 = 76,8 MHz; quadro de 64 bits; I2SDIV = 12 com ODD = 1
# (divisor 25) -> 76,8e6 / 64 / 25 = 48000 Hz exatos. A referência numérica do lock-in de áudio usa a
# taxa real (na 1.0.0 eram 31994,05 Hz, -186 ppm, e a diferença fazia a fase girar).
I2S_CLK_HZ = 1e6 * 384 / 5
AUDIO_FS_REAL = I2S_CLK_HZ / 64.0 / round(I2S_CLK_HZ / 64.0 / AUDIO_FS)
MOD_TIMER_CLK_HZ = 84e6   # TIM4 (APB1 x2), mesmo cristal do I2S
# Atraso da referência do lock-in do OPT101 em relação à luz (cadeia digital): a fase do PLL vale 0 no
# centro do bloco em que o REF (maioria das OSR amostras) sobe, em média (OSR-1)/2 amostras do ADC
# (200 kHz) depois da borda do rótulo (7,5 com OSR 16); o rótulo segue a escrita do DMA, 12 ciclos do ADC
# (21 MHz) depois do instante amostrado, e o CCR1 do laser muda ~0,2 µs depois do rótulo. Soma
# +360°·f·opt_ref_delay() à fase do OPT101 (conferido com simulação do firmware: erro < 0,05° até 1,7 kHz).
def opt_fft_size():
    '''Pontos da FFT da faixa completa do OPT101: 4096 a 12,5 kS/s, proporcional à taxa (mesma resolução).'''
    return int(OPT_FFT_SIZE * max(1, round(RATE.FS / 12500.0))) if RATE.FS >= 12500.0 else OPT_FFT_SIZE


def opt_ref_delay(osr=None):
    osr = int(round(RAW_FS / RATE.FS)) if osr is None else int(osr)
    return 0.5 * (osr - 1) / RAW_FS - 12.0 / 21e6 - 0.2e-6


def boxcar_gain(f, osr, fs_raw=RAW_FS):
    '''Ganho (real) da média de osr amostras consecutivas em f: sin(pi f osr/fs)/(osr sin(pi f/fs)).'''
    x = np.pi * np.asarray(f, dtype=np.float64) / fs_raw
    if osr <= 1:
        return np.ones_like(x)
    with np.errstate(invalid='ignore', divide='ignore'):
        g = np.sin(osr * x) / (osr * np.sin(x))
    return np.where(np.abs(x) < 1e-12, 1.0, g)


# Pacote óptico do firmware 2.0.0: A5 5A 4F 50 | SEQ (uint32, índice absoluto da 1ª amostra) | N (uint16)
# | N x uint16 (bits 0-11 = ADC, bit 15 = laser) | CRC16 (CCITT-FALSE dos bytes entre o magic e o CRC).
OPT_PACKET_MAGIC = b'\xA5\x5A\x4F\x50'
OPT_PACKET_HEADER_SIZE = 10
OPT_PACKET_MAX_SAMPLES = 512
OPT_GAP_FILL_MAX = int(RAW_FS)   # perdas até 1 s são preenchidas (repete a última amostra) para manter o tempo
AUDIO_PACKET_MAGIC = b'\xA5\x5A\x49\x32'
# Marcador A5 5A 4D 4B + SEQ (uint32) + CRC16: amostra I2S em que a onda quadrada do laser começou
# (borda de subida). Dá ao lock-in do INMP441 a mesma origem de fase do OPT101 (PLL na borda).
MOD_MARKER_MAGIC = b'\xA5\x5A\x4D\x4B'
MOD_MARKER_SIZE = 10
AUDIO_PACKET_HEADER_SIZE = 10
AUDIO_PACKET_MAX_SAMPLES = 256
AUDIO_QUEUE_MAX_SAMPLES = AUDIO_FS * 2
AUDIO_DISPLAY_SAMPLES = AUDIO_FS // 10
AUDIO_FFT_SIZE = 4096        # FFT da faixa completa (resolução ~7,8 Hz)
AUDIO_FFT_HISTORY_SEC = 4.0  # histórico de áudio; a FFT com zoom usa todo ele (resolução ~0,25 Hz)
AUDIO_LOCKIN_BLOCK = 2400     # amostras por ponto do lock-in de áudio (0,05 s a 48 kHz -> 20 Hz)
AUDIO_LOCKIN_SPAN = 10.0    # s exibidos no gráfico do lock-in de áudio (padrão; ajustável na aba)
LOW_SIGNAL_SNR_DB = 10.0    # alerta de sinal baixo abaixo deste SNR (~3 sigma)
ALERT_COLOR = '#ffd6d6'
AUDIO_MAX_POINTS = int(round(AUDIO_LOCKIN_SPAN * AUDIO_FS / AUDIO_LOCKIN_BLOCK)) + 1
AUDIO_NOISE_SPAN = 60.0     # s de histórico do lock-in de áudio usados no gráfico de ruído/SNR
AUDIO_NOISE_POINTS = int(round(AUDIO_NOISE_SPAN * AUDIO_FS / AUDIO_LOCKIN_BLOCK))
AUTO_PHASE_SPAN = 1.0       # s de média usados pela auto-fase
AUDIO_FFT_INTERVAL = 0.25     # s entre FFTs (só roda com a opção ligada)
OPT_FFT_SIZE = 4096          # FFT da faixa completa do ADC do OPT101 com OSR 16 (resolução ~3,1 Hz);
                             # cresce com a taxa (opt_fft_size()) para manter a resolução
OPT_FFT_ZOOM_MAX = 1 << 19   # limite da FFT com zoom (a 200 kS/s: 2,6 s, resolução ~0,4 Hz)
OPT_FFT_HISTORY_SEC = 4.0    # histórico do ADC; a FFT com zoom usa todo ele (resolução ~0,25 Hz)
# Varredura recomendada para a calibração do microfone (padrão de alumínio), aba Modo Duplo.
# 5 Hz fica bem abaixo do corte do microfone/célula (~40 Hz); 35 pontos log até 2440 Hz ficam a >= 4 Hz
# de todo múltiplo de 60 Hz e longe das frequências em que o período cai num número inteiro de amostras
# do OPT101 (ex.: 2500 Hz = 5 amostras), onde a grade de 80 us deixa erro residual no R.
# PWM 100 %: o laser fica contínuo no meio período ligado (sem a portadora de 5 kHz).
CAL_SWEEP_F0 = 5.0
CAL_SWEEP_F1 = 2440.0
CAL_SWEEP_N = 35
CAL_SWEEP_TAU = 2.0
# τ adaptativo das varreduras em frequência do Modo Duplo (2.3.0). A varredura começa com o τ do quadro
# (τ inicial, alto: o ruído acústico em baixa frequência é lento) e, a cada ponto, mede a flutuação da saída
# dos lock-ins (desvio-padrão de S e de Δφ durante a medida, e a diferença entre a 1ª e a 2ª metade). Se a
# flutuação está bem abaixo da Precisão, o τ do ponto seguinte diminui (a flutuação cai com 1/√τ); se passa
# muito da Precisão, o ponto é refeito com τ maior. Cada ponto: espera 7τ + 0,3 s e média por max(1 s, 3τ).
ADAPT_TOL_DEF = 2.0       # precisão alvo da flutuação de S (%); a de Δφ é a mesma em radianos (2 % -> 1,15°)
ADAPT_TAU0_DEF = 4.0      # τ inicial padrão (s) com o τ adaptativo
ADAPT_TAU_CAP = 4.0       # τ max padrão (s) do modo adaptativo; o campo "τ max" do quadro define o teto (Marcos, 17/11)
ADAPT_Q_TARGET = 0.7      # o τ seguinte é escolhido para a flutuação ficar em 70 % da Precisão
ADAPT_Q_REDO = 2.0        # flutuação acima de 2× a Precisão: refaz o ponto com τ maior
ADAPT_MAX_REDO = 2
ADAPT_BLOCKS_DEF = 3       # "Permitir médias": até N medidas seguidas com o mesmo τ (≤ ADAPT_TAU_CAP) por ponto
ADAPT_MAX_DRIFT_WAIT = 0  # médias extras (mesmo τ) enquanto S ou Δφ derivam; 0 = só registra a deriva (4 travava
                          # o ponto por minutos em 6 Hz); a regra nova sai da campanha de Sinal x t


# Baixa frequência (campanha de deriva 16-17/11): abaixo de ~40 Hz domina o ruído acústico do ambiente, lento e
# aditivo; a flutuação medida na janela subestima o erro e o τ adaptativo não converge. Opção (padrão): τ adaptativo
# só acima de LOWF_FMAX, τ fixo por faixa abaixo (f < limite -> τ); acima, o adaptativo recomeça de LOWF_TAU_ABOVE
NOISE_LASER_TOL_HZ = 0.15  # Detectar ruídos no warm-up: tons a ±0,15 Hz de k·f do laser são do laser
WARMUP_DEF_S = 600.0      # "Aguardar warm-up" das varreduras (s); 300 -> 600 s na campanha de ruído de 18/11
LOWF_FMAX = 40.0
LOWF_TAU_BANDS = ((LOWF_FMAX, ADAPT_TAU_CAP),)   # antes 8 s < 15 Hz e 4 s < 40 Hz; desde 17/11 usa o τ max do quadro
LOWF_TAU_ABOVE = 1.0
LOWF_WARN_COLOR = '#d97000'
# Padrão das varreduras em frequência do Modo Duplo (campanha de ruído de 18/11, aprovado por Marcos): τ fixo de 1 s
# (4 s abaixo de LOWF_FMAX, espera 7τ + média 3τ), 3 repetições combinadas pela mediana ponto a ponto, warm-up 600 s,
# início em 1 Hz desde 25/11 (célula nova resolveu a flutuação em baixa frequência; antes 40 Hz). Entre 40 e 200 Hz os erros são pontos isolados (sons do ambiente de alguns segundos) que um τ maior
# não remove; a mediana de varreduras separadas no tempo os descarta. Acima de τ = 4 s o S para de melhorar (Allan).
SWEEP_F0_DEF = 1.0
SWEEP_TAU_DEF = 1.0
LOWF_TAU_FIXED = 4.0       # τ fixo abaixo de LOWF_FMAX com o τ adaptativo desligado
TAU_USEFUL_MAX = 4.0       # acima disso: aviso "τ > 4 s não melhora: use repetições" (não bloqueia)
SWEEP_REPS_DEF = 3
DUAL_NODATA_RETRIES = 2     # ponto sem dados de um sensor: mede de novo até 2 vezes antes de pular
MEDIAN_EFF = 1.25          # incerteza da mediana = 1,25·DP/√N (eficiência da mediana)
# Monitor de ruído pelas vizinhas (aprovado por Marcos em 18/11; limites da campanha de aquecimento de 18/11): a cada
# 1 s, janela Hann de 2 s no INMP441 bruto, q = rms(R em f·0,93, R em f·1,07) / R em f (vizinhas afastadas de múltiplos
# de 60 Hz). Um som do ambiente aparece nas vizinhas e no sinal ao mesmo tempo: o trecho com q > 2 × mediana de q
# do próprio ponto é descartado (37 Hz: rms do desvio 27 -> 15 %; 113 Hz: 14 -> 7 %, descartando 7-15 %; >= 487 Hz
# quase nada). Com mais de 30 % descartado, o ponto é refeito. |desvio| mediano ~ 0,3·q (q estima o erro do ponto).
NB_REL = 0.07
NB_K = 2.0
NB_REDO_FRAC = 0.30
NB_MAX_REDO = 2
NB_WIN_S = 2.0


def nb_ratio(x, f, fs):
    """q = rms(R nas vizinhas f·(1 ± 7 %)) / R em f, numa janela Hann (DFT de um bin)."""
    n = len(x)
    t = np.arange(n) / fs
    xw = (x - x.mean()) * np.hanning(n)

    def amp(ff):
        return abs(np.dot(xw, np.exp(-2j * np.pi * ff * t)))
    lo = soi_serie.mains_suggest(f * (1.0 - NB_REL), soi_serie.MAINS_SWEEP_SHIFT_HZ)
    hi = soi_serie.mains_suggest(f * (1.0 + NB_REL), soi_serie.MAINS_SWEEP_SHIFT_HZ)
    return float(np.sqrt(0.5 * (amp(lo) ** 2 + amp(hi) ** 2)) / max(amp(f), 1e-30))


# Perto da rede (|f - k·60| <= 3 Hz): funções em soi_serie (mains_near, mains_suggest, mains_msg, avoid_mains)


def lowf_band_tau(f):
    """τ pré-definido da faixa de baixa frequência (None acima de LOWF_FMAX)."""
    for fmax, tau in LOWF_TAU_BANDS:
        if f < fmax:
            return tau
    return None


def adapt_tau_min(f):
    """Menor τ permitido: ~3 períodos (rejeita o resíduo em 2f), pelo menos 100 ms."""
    return float(max(0.1, 3.0 / max(f, 1e-3)))


def adapt_times(tau):
    """(espera, medida) de um ponto com o τ adaptativo."""
    return 7.0 * tau + 0.3, max(1.0, 3.0 * tau)


CAL_SWEEP_PWM = 100.0
DUAL_CAL_ERR_COLOR = (44, 160, 44, 150)   # barras de erro da calibração (verde translúcido)
DUAL_OUT_CAL_COLOR = '#c0392b'    # pontos fora da faixa da calibração aplicada (fundo avermelhado no gráfico)
SNR_TOP_WINDOW_S = 4.0      # janela mínima do SNR da barra superior (s); usa 10τ se maior, até SNR_TOP_MAX_S
SNR_TOP_MAX_S = 30.0
SNR_TOP_GOOD_DB = 25.0      # verde: erro do ponto ≲ 10 %, perto do piso (análise das medidas de 17/11; antes 30)
SNR_TOP_OK_DB = 15.0        # amarelo: ~10 a 25 %; abaixo, vermelho (≳ 40 %) (antes 20)
PWM_PRESETS = (0.0, 10.0, 100.0)  # botões de um clique ao lado do campo do PWM (o campo fica antes do último)
MEDIDAS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False)
    else os.path.dirname(os.path.abspath(__file__)), 'Medidas')
SERIES_DIR = os.path.join(os.path.dirname(MEDIDAS_DIR), 'Series')   # arquivos *.serie.txt (Medidas em Série)
MAX_POINTS = 200          # Pontos exibidos de R e Fase
MAX_RX_BYTES = 4_000_000  # Proteção contra acúmulo de bytes se a GUI travar (10 s a 200 kS/s; múltiplo de 2)
MAX_SCOPE_POINTS = 120_000  # pontos guardados no osciloscópio; acima disso a janela é reduzida por média
GUI_INTERVAL_MS = 40      # 25 FPS (indistinguível de 30 para este sinal)
STATUS_INTERVAL = 0.15    # s entre atualizações do texto de status
RANGE_INTERVAL = 0.5      # s entre reajustes automáticos de escala Y
REDUCED_VIEW_HZ = 50.0    # acima desta frequência o osciloscópio mostra só MAX_SCOPE_CYCLES ciclos
MAX_SCOPE_CYCLES = 50

OK_COLOR = '#e6ffe6'
WARN_COLOR = '#fff3cd'


# Valores de τ do passa-baixas do lock-in (sequência 1–3–10, como nos lock-ins comerciais).
# As setas do campo τ andam por esta lista; um valor digitado fora dela também é aceito.
TAU_STEPS = (0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0)
TAU_MIN, TAU_MAX = TAU_STEPS[0], TAU_STEPS[-1]


def auto_tau(f):
    '''τ automático ao mudar a frequência: ~3,2 períodos da modulação (equivale ao antigo corte de 5 % de f),
    limitado a 0,32–2 s e arredondado para o valor mais próximo de TAU_STEPS (escala log): 0,3 s acima de
    ~5,8 Hz, 1 s de ~1,8 a 5,8 Hz e 3 s abaixo disso.'''
    tau = float(np.clip(1.0 / (2.0 * np.pi * 0.05 * max(f, 1e-6)), 1.0 / (2.0 * np.pi * 0.5),
                        1.0 / (2.0 * np.pi * 0.08)))
    return min(TAU_STEPS, key=lambda v: abs(np.log(v / tau)))


def get_effective_cutoffs(f):
    '''Cortes adaptativos de filtro conforme a frequência de modulação: o passa-baixas vem do τ
    automático (auto_tau) e o passa-altas fica em 2 % de f, entre 0,01 e 0,05 Hz.'''
    lp = 1.0 / (2.0 * np.pi * auto_tau(f))
    hp = float(np.clip(f * 0.02, 0.01, 0.05))
    return lp, hp


def lp_tau(cutoff, fs):
    '''Constante de tempo (s) de cada polo do passa-baixas do lock-in, y[k] = a*x[k] + (1-a)*y[k-1]
    com a = 2*pi*fc/fs: tau = -1/(fs*ln(1-a)), que tende a 1/(2*pi*fc) quando fc << fs.'''
    a = 2.0 * np.pi * cutoff / fs
    return float('inf') if a >= 1.0 else -1.0 / (fs * np.log1p(-a))


def tau_cutoff(tau, fs):
    '''Inverso de lp_tau: corte (Hz) que dá exatamente a constante de tempo tau (s) por polo na taxa fs.'''
    return fs * -np.expm1(-1.0 / (fs * tau)) / (2.0 * np.pi)


def lp_info(tau):
    '''Corte de -3 dB, banda equivalente de ruído (ENBW) e espera recomendada do passa-baixas do lock-in
    (2 polos iguais em cascata, 12 dB/oitava) para um τ por polo.'''
    f3 = np.sqrt(np.sqrt(2.0) - 1.0) / (2.0 * np.pi * tau)     # -3 dB de dois polos: 0,644/(2πτ)
    enbw = 1.0 / (8.0 * tau)
    return f3, enbw, 9.0 * tau


def actual_mod_freq(f):
    '''Frequência real da onda quadrada gerada pelo TIM4 no firmware (startModulation), com os
    mesmos arredondamentos inteiros. O lock-in do INMP441 não tem PLL: precisa da frequência exata.'''
    if f <= 0:
        return f
    if f >= 100.0:
        tick = MOD_TIMER_CLK_HZ / 8                   # prescaler 8 -> 10,5 MHz
        half = int(tick / (2.0 * f) + 0.5)
        return tick / (2.0 * half)
    half_us = int(500000.0 / f + 0.5)                 # setOverflow(.., MICROSEC_FORMAT) do STM32duino
    cycles = half_us * int(MOD_TIMER_CLK_HZ // 1e6)
    psc = cycles // 0x10000 + 1
    return MOD_TIMER_CLK_HZ / (2.0 * psc * (cycles // psc))


def hann_kernel(d):
    '''|Espectro| da janela Hann normalizado (1 em d = 0), com d em bins:
    sinc(d) + (sinc(d - 1) + sinc(d + 1)) / 2  (= sinc(d) / (1 - d^2), sem singularidade em d = ±1).'''
    d = np.asarray(d, dtype=np.float64)
    return np.abs(np.sinc(d) + 0.5 * (np.sinc(d - 1.0) + np.sinc(d + 1.0)))


# Exporta tudo (inclusive nomes com _) para os módulos que fazem import *
__all__ = [_n for _n in dir() if not _n.startswith('__')]
