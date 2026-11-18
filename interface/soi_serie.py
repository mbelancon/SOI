#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Medidas em Série do SOI Controller: uma fila de etapas (varredura em frequência do Modo Duplo, Sinal x t,
pausa com o laser parado, aviso ao operador) montada na aba "Medidas em Série" ou num arquivo de texto
(*.serie.txt), rodada pela interface ou sem janela (soi_controller.py --serie arquivo.serie.txt).

Arquivo (UTF-8), uma etapa por linha, com as mesmas opções da linha de comando do modo sem janela:

    # SOI - medidas em série (versão 1)
    nome_base = Al_tampa
    inicio = 22:00            (opcional: começa no próximo 22:00; ou 2026-11-18 22:00)
    repetir = 1               (repete a série inteira N vezes)
    fim = laser_parado        (ou manter)
    sinal-t   --nome 1_warmup_f17 --f 17 --pwm 100 --tau 1 --dt 1 --duracao 30
    sinal-t   --nome 2_f{f} --f 37;113;487 --duracao 20
    varredura --nome 4d_adapt2 --fmin 20 --fmax 2440 --n 25 --tau 4 --precisao 2 --repetir 3 --desligar
    aviso "Troque a tampa e clique Continuar"
    pausa --duracao 10
    #! pausa --duracao 5      (#! = etapa desmarcada: fica no arquivo, não roda)

As chaves e os nomes ficam em português em qualquer idioma da interface (como os arquivos de Medidas).
"""

import csv
import os
import numpy as np
import shlex
import time
from datetime import datetime, timedelta

SERIE_EXT = '.serie.txt'
SERIE_HEADER = '# SOI - medidas em série (versão 1)'
TIPOS = ('varredura', 'sinal-t', 'pausa', 'aviso', 'transiente')
TIPO_NOME = {'varredura': 'Varredura f', 'sinal-t': 'Sinal x t', 'pausa': 'Pausa', 'aviso': 'Aviso',
             'transiente': 'Transiente'}
LISTAS = ('sinal-t', 'transiente')     # tipos em que --f e --pwm aceitam lista (uma medida por combinação)

DEFAULTS = {
    'varredura': {'nome': 'varredura', 'fmin': 20.0, 'fmax': 2440.0, 'n': 25, 'tau': 4.0, 'tau_fixo': False,
                  'precisao': 2.0, 'medias': 1, 'adapt_tudo': False, 'pwm': 100.0, 'aquecer': 0.0,
                  'desligar': False, 'repetir': 1},
    'sinal-t': {'nome': 'f{f}', 'f': [17.0], 'pwm': [100.0], 'tau': 1.0, 'dt': 5.0, 'duracao': 10.0,
                'aquecer': 0.0, 'desligar': False, 'repetir': 1},
    'transiente': {'nome': 'transiente_f{f}_pwm{pwm}', 'f': [17.0], 'pwm': [100.0], 'pulsos': 64, 'intervalo': 60.0,
                   'duracao': 10.0, 'individuais': False, 'ajuste': 0, 'aquecer': 0.0, 'desligar': False,
                   'repetir': 1},
    'pausa': {'nome': 'pausa', 'duracao': 10.0, 'repetir': 1},
    'aviso': {'nome': '', 'texto': 'Clique em Continuar para seguir.'},
}
# opção da linha -> (chave, tipo); tipo None = flag sem valor
OPCOES = {
    '--nome': ('nome', str), '--fmin': ('fmin', float), '--fmax': ('fmax', float), '--n': ('n', int),
    '--tau': ('tau', float), '--tau-fixo': ('tau_fixo', None), '--precisao': ('precisao', float),
    '--medias': ('medias', int), '--adapt-tudo': ('adapt_tudo', None), '--pwm': ('pwm', float),
    '--aquecer': ('aquecer', float), '--desligar': ('desligar', None), '--repetir': ('repetir', int),
    '--f': ('f', 'flist'), '--dt': ('dt', float), '--duracao': ('duracao', float), '--texto': ('texto', str),
    '--pulsos': ('pulsos', int), '--intervalo': ('intervalo', float), '--individuais': ('individuais', None),
    '--ajuste': ('ajuste', int),
}
ORDEM = {   # ordem das opções ao salvar
    'varredura': ('nome', 'fmin', 'fmax', 'n', 'tau', 'tau_fixo', 'precisao', 'medias', 'adapt_tudo', 'pwm',
                  'aquecer', 'repetir', 'desligar'),
    'sinal-t': ('nome', 'f', 'pwm', 'tau', 'dt', 'duracao', 'aquecer', 'repetir', 'desligar'),
    'pausa': ('nome', 'duracao', 'repetir'),
    'transiente': ('nome', 'f', 'pwm', 'pulsos', 'intervalo', 'duracao', 'individuais', 'ajuste', 'aquecer', 'repetir',
                   'desligar'),
}
FIM_OPCOES = ('laser_parado', 'manter')


def new_step(tipo, **kw):
    s = {'tipo': tipo, 'ativa': True}
    s.update({k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS[tipo].items()})
    s.update(kw)
    return s


def new_serie():
    return {'nome_base': '', 'inicio': '', 'repetir': 1, 'fim': 'laser_parado', 'etapas': []}


def parse_flist(text, lo=0.1, hi=20000.0, what='frequência'):
    vals = []
    for p in str(text).replace(',', ';').split(';'):
        p = p.strip()
        if p:
            v = float(p)
            if not lo <= v <= hi:
                raise ValueError(f'{what} fora da faixa: {p}')
            vals.append(v)
    if not vals:
        raise ValueError(f'lista de {what} vazia')
    return vals


def parse_pwmlist(text):
    return parse_flist(text, 0.0, 100.0, 'PWM')


def fmt_flist(vals):
    return ';'.join(f'{v:g}' for v in vals)


def parse_inicio(text, now=None):
    """'22:00' (próxima vez que o relógio marcar 22:00) ou '2026-11-18 22:00' -> datetime; '' -> None."""
    text = (text or '').strip()
    if not text:
        return None
    now = now or datetime.now()
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            t = datetime.strptime(text, fmt).time()
        except ValueError:
            continue
        d = datetime.combine(now.date(), t)
        return d if d > now else d + timedelta(days=1)
    raise ValueError(f'horário de início inválido: "{text}" (use 22:00 ou 2026-11-18 22:00)')


def _parse_step(line):
    toks = shlex.split(line, posix=True)
    tipo = toks[0].lower()
    if tipo not in TIPOS:
        raise ValueError(f'tipo de etapa desconhecido: "{toks[0]}" (use {", ".join(TIPOS)})')
    st = new_step(tipo)
    rest = toks[1:]
    if tipo == 'aviso' and rest and not rest[0].startswith('--'):
        st['texto'] = ' '.join(rest)
        return st
    i = 0
    while i < len(rest):
        opt = rest[i]
        if opt not in OPCOES:
            raise ValueError(f'opção desconhecida: {opt}')
        key, kind = OPCOES[opt]
        if key not in DEFAULTS[tipo]:
            raise ValueError(f'{opt} não vale para {tipo}')
        if kind is None:
            st[key] = True
            i += 1
            continue
        if i + 1 >= len(rest):
            raise ValueError(f'falta o valor de {opt}')
        val = rest[i + 1]
        if key == 'pwm' and tipo in LISTAS:
            st[key] = parse_pwmlist(val)
        else:
            st[key] = parse_flist(val) if kind == 'flist' else kind(val)
        i += 2
    if st.get('repetir', 1) < 1:
        raise ValueError('--repetir precisa ser 1 ou mais')
    if tipo == 'transiente':
        if st['pulsos'] < 1:
            raise ValueError('--pulsos precisa ser 1 ou mais')
        if st['ajuste'] not in (0, 1, 2):
            raise ValueError('--ajuste: 0 (sem), 1 ou 2 exponenciais')
    return st


def parse(text):
    """Texto do arquivo -> série. ValueError com o número da linha em caso de erro."""
    serie = new_serie()
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        ativa = True
        if line.startswith('#!'):
            line, ativa = line[2:].strip(), False
            if not line:
                continue
        elif line.startswith('#'):
            continue
        try:
            first = line.split(None, 1)[0].lower()
            if ativa and '=' in line and first not in TIPOS:
                k, v = (x.strip() for x in line.split('=', 1))
                k = k.lower()
                if k == 'nome_base':
                    serie['nome_base'] = v
                elif k == 'inicio':
                    parse_inicio(v)
                    serie['inicio'] = v
                elif k == 'repetir':
                    serie['repetir'] = max(1, int(v))
                elif k == 'fim':
                    if v not in FIM_OPCOES:
                        raise ValueError(f'fim = {v}: use {" ou ".join(FIM_OPCOES)}')
                    serie['fim'] = v
                else:
                    raise ValueError(f'chave desconhecida: {k}')
                continue
            st = _parse_step(line)
            st['ativa'] = ativa
            serie['etapas'].append(st)
        except ValueError as e:
            raise ValueError(f'linha {no}: {e}') from None
    return serie


def _q(s):
    return shlex.quote(str(s)) if s != '' else "''"


def step_line(st):
    t = st['tipo']
    if t == 'aviso':
        line = f'aviso {_q(st.get("texto", ""))}'
    else:
        parts = [t]
        for k in ORDEM[t]:
            v = st.get(k, DEFAULTS[t].get(k))
            opt = next(o for o, (kk, _) in OPCOES.items() if kk == k)
            if isinstance(v, bool):
                if v:
                    parts.append(opt)
            elif k == 'repetir' and int(v) == 1:
                continue
            elif k in ('medias',) and int(v) <= 1:
                continue
            elif k == 'aquecer' and not v:
                continue
            elif k in ('f', 'pwm') and isinstance(v, list):
                parts += [opt, fmt_flist(v)]
            elif k == 'ajuste' and not v:
                continue
            elif k == 'nome':
                parts += [opt, _q(v)]
            else:
                parts += [opt, f'{v:g}' if isinstance(v, float) else str(v)]
        line = ' '.join(parts)
    return line if st.get('ativa', True) else '#! ' + line


def dumps(serie, extra_comment=None):
    out = [SERIE_HEADER]
    if extra_comment:
        out += [f'# {c}' for c in extra_comment.splitlines()]
    out.append(f"nome_base = {serie.get('nome_base', '')}")
    if serie.get('inicio'):
        out.append(f"inicio = {serie['inicio']}")
    out.append(f"repetir = {int(serie.get('repetir', 1))}")
    out.append(f"fim = {serie.get('fim', 'laser_parado')}")
    out += [step_line(st) for st in serie['etapas']]
    return '\n'.join(out) + '\n'


def load(path):
    with open(path, encoding='utf-8-sig') as fh:
        return parse(fh.read())


def save(path, serie, extra_comment=None):
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(dumps(serie, extra_comment))


def safe_name(name):
    return ''.join('_' if c in '\\/:*?"<>|' or ord(c) < 32 else c for c in str(name)).strip(' .')


def expand(serie):
    """Série -> lista de trabalhos na ordem de execução. Cada um: dict com 'etapa' (índice), 'ciclo', 'rep',
    'tipo', 'nome' (nome da etapa já com {f}, _rep e _ciclo), 'p' (parâmetros, f escalar na Sinal x t)."""
    jobs = []
    cycles = max(1, int(serie.get('repetir', 1)))
    for c in range(1, cycles + 1):
        for i, st in enumerate(serie['etapas']):
            if not st.get('ativa', True):
                continue
            reps = max(1, int(st.get('repetir', 1))) if st['tipo'] != 'aviso' else 1
            lst = st['tipo'] in LISTAS
            freqs = st['f'] if lst else [None]
            pwms = st['pwm'] if lst else [None]
            combos = [(f, q) for f in freqs for q in pwms]
            for r in range(1, reps + 1):
                for f, q in combos:
                    p = dict(st)
                    nome = str(st.get('nome', '') or '')
                    if f is not None:
                        p['f'], p['pwm'] = f, q
                        for key, val, n in (('f', f, len(freqs)), ('pwm', q, len(pwms))):
                            if '{' + key + '}' in nome:
                                nome = nome.replace('{' + key + '}', f'{val:g}')
                            elif n > 1:
                                nome = f'{nome}_{key}{val:g}' if nome else f'{key}{val:g}'
                    if reps > 1:
                        nome += f'_rep{r}'
                    if cycles > 1:
                        nome += f'_ciclo{c}'
                    jobs.append({'etapa': i, 'ciclo': c, 'rep': r, 'tipo': st['tipo'], 'nome': safe_name(nome),
                                 'p': p})
    return jobs


def fmt_dur(sec):
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h} h {m:02d} min'
    if m:
        return f'{m} min' if not s or m >= 10 else f'{m} min {s:02d} s'
    return f'{s} s'


# --------------------------------------------------------------------------- execução (Qt)
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets    # noqa: E402
import pyqtgraph as pg                               # noqa: E402


class SeriesRunner(QtCore.QObject):
    """Roda uma série na LockInWindow (a mesma usada pela interface e pelo modo sem janela), etapa a etapa,
    com as mesmas funções dos quadros do Modo Duplo. Dirigida por um QTimer: não bloqueia a interface."""
    changed = QtCore.Signal() if hasattr(QtCore, 'Signal') else QtCore.pyqtSignal()
    finished = QtCore.Signal(str) if hasattr(QtCore, 'Signal') else QtCore.pyqtSignal(str)

    SETTLE_S = 3.0     # lock-ins assentam com PWM e frequência novos antes de cada varredura (como no sem janela)

    def __init__(self, win, medidas_dir, log=print):
        super().__init__(win)
        self.win, self.medidas_dir, self.log = win, medidas_dir, log
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.active = False
        self.state = 'idle'
        self.jobs, self.idx = [], -1
        self.status = {}
        self.pause_after = False
        self.on_aviso = None          # sem janela: função chamada no aviso (espera Enter no terminal)
        self.folder = None

    # ---- tempo estimado
    def estimate(self, job):
        """(mínimo, máximo) em segundos; None para o aviso (espera o operador)."""
        p, w = job['p'], self.win
        t = job['tipo']
        if t == 'aviso':
            return None
        if t == 'pausa':
            d = 60.0 * p['duracao']
            return d, d
        if t in ('sinal-t', 'transiente'):
            d = 60.0 * p['duracao'] + p.get('aquecer', 0.0)
            return d, d
        return w._series_sweep_estimate(p)

    def total_estimate(self, jobs=None):
        lo = hi = 0.0
        avisos = 0
        for j in (self.jobs if jobs is None else jobs):
            e = self.estimate(j)
            if e is None:
                avisos += 1
            else:
                lo, hi = lo + e[0], hi + e[1]
        return lo, hi, avisos

    # ---- controle
    def start(self, serie, nome_arquivo=''):
        w = self.win
        if self.active:
            return False
        if w.dual_active or getattr(w, 'sweep_active', False):
            w.flash('Termine ou cancele a medida em andamento antes de iniciar a série.')
            return False
        if w.ext_mode:
            w.flash('Medidas em série usam a modulação eletrônica: mude o trigger em Configurações.')
            return False
        if getattr(w, 'average_mode', False):
            w.flash('Medidas em série precisam do OPT101 no Modo Lock-In.')
            return False
        jobs = expand(serie)
        if not jobs:
            w.flash('A série não tem etapas marcadas.')
            return False
        self.serie, self.jobs, self.idx = serie, jobs, -1
        self.status = {i: 'na fila' for i in range(len(jobs))}
        self.files = {}
        self.t_job = {}
        self.base = serie.get('nome_base', '').strip() or w.ed_sample.text().strip()
        now = datetime.now()
        self.t_start = now
        stem = safe_name(f"Serie_{self.base + '_' if self.base else ''}{now.strftime('%Y%m%d_%H%M%S')}")
        self.folder = os.path.join(self.medidas_dir, stem)
        try:
            os.makedirs(self.folder, exist_ok=True)
            fname = safe_name(os.path.basename(nome_arquivo)) if nome_arquivo else ''
            if not fname.endswith(SERIE_EXT):
                fname = stem + SERIE_EXT
            self.serie_copy = os.path.join(self.folder, fname)
            lo, hi, av = self.total_estimate()
            save(self.serie_copy, serie,
                 f'Rodada em {now.strftime("%Y-%m-%d %H:%M:%S")} pelo SOI Controller {getattr(w, "version", "")}'
                 f' ({len(jobs)} medidas, tempo estimado {fmt_dur(hi)}).\n'
                 'Para repetir: Medidas em Série > Abrir série... e escolha este arquivo.')
            self.resumo = os.path.join(self.folder, 'resumo.csv')
            with open(self.resumo, 'w', encoding='utf-8', newline='') as fh:
                csv.writer(fh).writerow(['Ciclo', 'Etapa', 'Repeticao', 'Tipo', 'Nome', 'Inicio', 'Fim', 'Estado',
                                         'Arquivo'])
        except OSError as e:
            w.flash(f'Não foi possível criar a pasta da série: {e}')
            return False
        self.snapshot = w._series_snapshot()
        w._series_lock(True)                 # antes da 1ª medida (ela mesma desabilita campos)
        w.save_dir_override = self.folder
        w.series_active = True
        self.sample0 = w.ed_sample.text()
        self.active = True
        self.pause_after = False
        self.skip = False
        self.log(f'Série: {len(jobs)} medidas, pasta {self.folder}')
        self.t0_series = time.time()
        when = parse_inicio(serie.get('inicio', ''))
        if when and when > datetime.now():
            self.wait_until = when
            self._laser_off()
            self.state = 'wait_start'
            self.log(f'Série: aguardando o início às {when.strftime("%d/%m %H:%M")} (laser parado).')
        else:
            self._next()
        self.timer.start(250)
        self.changed.emit()
        return True

    def stop(self):
        """Para a série: a medida em andamento é encerrada e salva com os pontos já medidos."""
        if not self.active:
            return
        if self.state == 'run':
            self._stop_measure()
            self._job_end('parada')
        elif 0 <= self.idx < len(self.jobs) and self.status.get(self.idx) not in ('concluída', 'falhou'):
            self._job_end('parada')
        self._finish('Série parada pelo usuário.')

    def skip_job(self):
        if not self.active:
            return
        if self.state == 'run':
            self._stop_measure()
            self._job_end('pulada')
        elif self.state in ('warm', 'settle', 'pause', 'aviso'):
            self._job_end('pulada')
        elif self.state == 'wait_start':
            self.wait_until = datetime.now()
            return
        self._after_job()

    def resume(self):
        """Botão Continuar: depois de um aviso ou de "Pausar após esta etapa"."""
        if self.state == 'aviso':
            self._job_end('concluída')
            self._after_job()
        elif self.state == 'paused':
            self._next()
        self.changed.emit()

    # ---- máquina de estados
    def _laser_off(self):
        w = self.win
        w.sp_power.setValue(0.0)
        w.on_power(0.0)

    def _laser(self, pwm, f=None):
        w = self.win
        if f is not None:
            w._set_spin(w.sp_freq, f)
            w.apply_frequency(f)
        w.sp_power.setValue(pwm)
        w.on_power(w.sp_power.value())

    def job(self):
        return self.jobs[self.idx] if 0 <= self.idx < len(self.jobs) else None

    def _next(self):
        self.idx += 1
        if self.idx >= len(self.jobs):
            self._finish('Série concluída.')
            return
        j = self.job()
        p, w = j['p'], self.win
        self.t_job[self.idx] = [datetime.now(), None]
        self.status[self.idx] = 'em andamento'
        self.log(f'Série [{self.idx + 1}/{len(self.jobs)}] {TIPO_NOME[j["tipo"]]} "{j["nome"]}"')
        if j['tipo'] == 'pausa':
            self._laser_off()
            self.until = time.time() + 60.0 * p['duracao']
            self.state = 'pause'
        elif j['tipo'] == 'aviso':
            self.state = 'aviso'
            w.flash(f'Medidas em série: {p.get("texto", "")}', 30.0)
            QtWidgets.QApplication.beep()
            if self.on_aviso:
                self.on_aviso(p.get('texto', ''))
                self.resume()
                return
        else:
            if j['tipo'] != 'transiente':
                w._series_apply(j['tipo'], p)
            self.warm_s = p.get('aquecer', 0.0) or 0.0
            if self.warm_s > 0:
                self._laser(p['pwm'], p['f'] if j['tipo'] in LISTAS else None)
                self.until = time.time() + self.warm_s
                self.state = 'warm'
                self.log(f'  warm-up: PWM {p["pwm"]:g} % por {self.warm_s:g} s')
            elif j['tipo'] == 'varredura':
                self._laser(p['pwm'])
                self.until = time.time() + self.SETTLE_S
                self.state = 'settle'
            else:
                self._begin_measure()
        self.changed.emit()

    def _begin_measure(self):
        j, w = self.job(), self.win
        w.ed_sample.setText(f'{self.base}_{j["nome"]}' if self.base and j['nome'] else (self.base or j['nome']))
        w.dual_last_csv = None
        if j['tipo'] == 'transiente':
            self.tjob = TransientJob(w, j['p'], self.folder, self.log)
            if not self.tjob.start():
                self._job_end('falhou')
                self._after_job()
                return
            self.state = 'run'
            self.t_meas = time.time()
            return
        if j['tipo'] == 'varredura':
            w.toggle_dual_sweep('F')
        else:
            w.toggle_dual_time()
        if not w.dual_active:
            self.log('  ERRO: a medida não começou (veja as mensagens acima).')
            self._job_end('falhou')
            self._after_job()
            return
        self.state = 'run'
        self.t_meas = time.time()

    def _stop_measure(self):
        w = self.win
        tj = getattr(self, 'tjob', None)
        if tj is not None and not tj.done:
            tj.finish()
            return
        if not w.dual_active:
            return
        if w.dual_src == 'T':
            w.toggle_dual_time()          # encerra e salva o que já foi medido
        else:
            w._series_stop_sweep()        # idem para a varredura (CSV com os pontos medidos)

    def _job_end(self, estado):
        j, w = self.job(), self.win
        if j is None:
            return
        if j['tipo'] == 'transiente':
            tj = getattr(self, 'tjob', None)
            csv_path = tj.csv if tj is not None else None
            self.tjob = None
        else:
            csv_path = getattr(w, 'dual_last_csv', None) if j['tipo'] in ('varredura', 'sinal-t') else None
        if j['tipo'] in ('varredura', 'sinal-t', 'transiente') and estado == 'concluída' and not csv_path:
            estado = 'falhou'
        self.status[self.idx] = estado
        self.files[self.idx] = csv_path or ''
        t = self.t_job.setdefault(self.idx, [datetime.now(), None])
        t[1] = datetime.now()
        w.dual_last_csv = None
        try:
            with open(self.resume_path(), 'a', encoding='utf-8', newline='') as fh:
                csv.writer(fh).writerow([j['ciclo'], j['etapa'] + 1, j['rep'], TIPO_NOME[j['tipo']], j['nome'],
                                         t[0].strftime('%Y-%m-%d %H:%M:%S'), t[1].strftime('%Y-%m-%d %H:%M:%S'),
                                         estado, os.path.basename(csv_path) if csv_path else ''])
        except OSError as e:
            self.log(f'  resumo.csv não gravado: {e}')
        if j['tipo'] in ('varredura', 'sinal-t', 'transiente') and j['p'].get('desligar'):
            self._laser_off()
        self.log(f'  {estado}' + (f': {csv_path}' if csv_path else ''))
        self.state = 'between'
        w._series_lock(True)                 # o fim da medida reabilita campos: bloqueia de novo

    def resume_path(self):
        return self.resumo

    def _after_job(self):
        if not self.active:
            return
        if self.pause_after and self.idx + 1 < len(self.jobs):
            self.pause_after = False
            self.state = 'paused'
            self.log('Série pausada após a etapa (Continuar segue).')
            self.changed.emit()
            return
        self._next()

    def _tick(self):
        if not self.active:
            return
        now, w = time.time(), self.win
        if self.state == 'wait_start':
            if datetime.now() >= self.wait_until:
                self.log('Série: horário de início, começando.')
                self._next()
        elif self.state in ('warm', 'pause', 'settle') and now >= self.until:
            if self.state == 'pause':
                self._job_end('concluída')
                self._after_job()
            elif self.state == 'warm':
                if self.job()['tipo'] == 'varredura':
                    self.until = now + self.SETTLE_S
                    self.state = 'settle'
                else:
                    self._begin_measure()
            else:
                self._begin_measure()
        elif self.state == 'run' and getattr(self, 'tjob', None) is not None:
            self.tjob.tick()
            if self.tjob.done:
                self._job_end('concluída')
                self._after_job()
        elif self.state == 'run' and not w.dual_active:
            self._job_end('concluída')
            self._after_job()
        self.changed.emit()

    def _finish(self, msg):
        w = self.win
        self.timer.stop()
        self.active = False
        self.state = 'idle'
        w.ed_sample.setText(self.sample0)
        w._series_restore(self.snapshot)
        if self.serie.get('fim', 'laser_parado') == 'laser_parado':
            self._laser_off()
        w.save_dir_override = None
        w.series_active = False
        w._series_lock(False)
        ok = sum(1 for s in self.status.values() if s == 'concluída')
        txt = f'{msg} {ok} de {len(self.jobs)} medidas concluídas em {fmt_dur(time.time() - self.t0_series)}. ' \
              f'Pasta: {self.folder}'
        self.log(txt)
        w.flash(txt, 10.0)
        self.changed.emit()
        self.finished.emit(txt)

    # ---- textos de estado
    def remaining(self):
        """(restante da etapa em s ou None, restante da série em s, hora prevista do fim ou None)."""
        if not self.active:
            return None, 0.0, None
        w, now = self.win, time.time()
        cur = None
        if self.state in ('warm', 'pause', 'settle'):
            cur = max(0.0, self.until - now)
            j = self.job()
            if self.state == 'warm':
                e = self.estimate(j)
                cur += (e[1] - self.warm_s) if j['tipo'] == 'varredura' else 60.0 * j['p']['duracao']
        elif self.state == 'run':
            j = self.job()
            if j['tipo'] in LISTAS:
                cur = max(0.0, 60.0 * j['p']['duracao'] - (now - self.t_meas))
            else:
                cur = max(0.0, getattr(w, 'dual_rest', 0.0) or 0.0)
        rest = sum((self.estimate(self.jobs[i]) or (0, 0))[1] for i in range(self.idx + 1, len(self.jobs)))
        if self.state == 'wait_start':
            rest += sum((self.estimate(j) or (0, 0))[1] for j in self.jobs[:1])
            cur = None
            pre = max(0.0, (self.wait_until - datetime.now()).total_seconds())
            return pre, rest + pre, datetime.now() + timedelta(seconds=rest + pre)
        total = rest + (cur or 0.0)
        return cur, total, (datetime.now() + timedelta(seconds=total)) if self.state != 'paused' else None


class TransientJob:
    """Etapa Transiente: OPT101 no modo Valor Médio, uma média de N pulsos a cada 'intervalo' segundos por
    'duracao' minutos (intervalo 0 = uma média atrás da outra). Grava, na pasta da série:
      <stem>.csv          Tempo_s + uma coluna por média (M001, M002...), cabeçalho com o horário de cada uma;
      <stem>_medias.csv   uma linha por média: horário, t, pulsos, mín, máx, amplitude e o ajuste (se pedido);
      <stem>.png          a última média (gráfico da aba OPT101);
      <stem>_individuais/M001.csv ...  (opcional) os N transientes de cada média, um por coluna."""

    def __init__(self, win, p, folder, log=print):
        self.w, self.p, self.folder, self.log = win, p, folder, log
        self.done = False
        self.csv = None
        self.avgs = []           # (datetime, t_s, values)
        self.tax = None
        self.rows = []

    def start(self):
        w, p = self.w, self.p
        if w.dual_active or getattr(w, 'sweep_active', False):
            self.log('  ERRO: há outra medida em andamento.')
            return False
        self.was_avg = w.average_mode
        w._set_spin(w.sp_freq, p['f'])
        w.apply_frequency(p['f'])
        w.sp_power.setValue(p['pwm'])
        w.on_power(w.sp_power.value())
        self.pulses0 = w.sp_pulses.value()
        w.sp_pulses.setValue(int(p['pulsos']))
        w.avg.pulses = int(p['pulsos'])
        if not w.average_mode:
            w.toggle_display_mode()             # Valor Médio (pré-trigger padrão para a frequência)
        else:
            w.set_pretrigger(w.default_pretrigger())
        if getattr(w, 'paused', False):
            w.sw_pause.setChecked(False)
        w.avg.keep = bool(p.get('individuais'))
        now = datetime.now()
        name = w._sample_name()
        self.stem = safe_name(f"{name + '_' if name else ''}Transientes_f{p['f']:g}Hz_pwm{p['pwm']:g}_"
                              f"{now.strftime('%Y%m%d_%H%M%S')}")
        self.t0 = time.time()
        self.t_end = self.t0 + 60.0 * float(p['duracao'])
        self.next_start = self.t0
        self.k = 0
        self.waiting = False      # True: média em andamento
        self.ind_dir = os.path.join(self.folder, self.stem + '_individuais') if p.get('individuais') else None
        if self.ind_dir:
            os.makedirs(self.ind_dir, exist_ok=True)
        n = self.count()
        self.log(f'  Transiente: {p["f"]:g} Hz, PWM {p["pwm"]:g} %, {p["pulsos"]} pulsos por média, '
                 f'{n} média(s) em {p["duracao"]:g} min' + (f' (a cada {p["intervalo"]:g} s)' if p['intervalo'] else ''))
        return True

    def count(self):
        iv = float(self.p['intervalo'])
        dur = 60.0 * float(self.p['duracao'])
        return int(np.ceil(dur / iv)) if iv > 0 else None

    def _begin_avg(self):
        w = self.w
        w.reset_average()
        w.avg.keep = bool(self.p.get('individuais'))
        self.ready0 = getattr(w, 'avg_ready_n', 0)
        self.t_avg = time.time()
        self.dt_avg = datetime.now()
        self.waiting = True

    def tick(self):
        if self.done:
            return
        w, now = self.w, time.time()
        if self.waiting:
            if getattr(w, 'avg_ready_n', 0) > self.ready0 and len(w.avg.values):
                self._capture()
                self.waiting = False
                iv = float(self.p['intervalo'])
                self.next_start = (self.t0 + self.k * iv) if iv > 0 else now
                if self.next_start < now:            # a média demorou mais que o intervalo: começa já
                    self.next_start = now
            elif now - self.t_avg > max(120.0, 3.0 * self.p['pulsos'] / max(self.p['f'], 0.1) + 30.0):
                self.log('  aviso: a média não fechou (sem pulsos do laser?); recomeçando.')
                self._begin_avg()
            return
        if now >= self.t_end:
            self.finish()
        elif now >= self.next_start:
            self._begin_avg()

    def _capture(self):
        w = self.w
        vals = np.array(w.avg.values, dtype=np.float64)
        tax = np.array(w.avg.time, dtype=np.float64)
        if self.tax is None or len(tax) < len(self.tax):
            self.tax = tax
        self.k += 1
        t_rel = self.t_avg - self.t0
        self.avgs.append((self.dt_avg, t_rel, vals))
        row = [self.k, self.dt_avg.strftime('%Y-%m-%d %H:%M:%S'), f'{t_rel:.1f}', self.p['pulsos'],
               f'{vals.min():.4f}', f'{vals.max():.4f}', f'{vals.max() - vals.min():.4f}']
        if self.p.get('ajuste'):
            row += self._fit(tax, vals)
        self.rows.append(row)
        if self.ind_dir and w.avg.last_cycles:
            cyc = w.avg.last_cycles
            n = min(len(c) for c in cyc)
            try:
                with open(os.path.join(self.ind_dir, f'M{self.k:03d}.csv'), 'w', encoding='utf-8', newline='') as fh:
                    fh.write(f'# Transientes individuais da media {self.k} - {self.dt_avg:%Y-%m-%d %H:%M:%S}, '
                             f'Freq={self.p["f"]:g} Hz, PWM={self.p["pwm"]:g} %\n')
                    fh.write('Tempo_s,' + ','.join(f'P{i + 1:03d}' for i in range(len(cyc))) + '\n')
                    for r in range(n):
                        fh.write(f'{tax[r]:.6f},' + ','.join(f'{c[r]:.2f}' for c in cyc) + '\n')
            except OSError as e:
                self.log(f'  transientes individuais não gravados: {e}')
        self._write()          # grava a cada média: nada se perde se a série parar
        self.log(f'  média {self.k}' + (f'/{self.count()}' if self.count() else '') +
                 f': amplitude {vals.max() - vals.min():.1f}' + (f', τ = {row[9]} s' if self.p.get('ajuste') else ''))

    def _fit(self, tax, vals):
        """Ajuste exponencial no laser ligado (t de 0 a meio período): y_inf + A1·e^(−t/τ1) [+ A2·e^(−t/τ2)]."""
        from scipy.optimize import curve_fit
        half = 0.5 / max(float(self.p['f']), 0.1)
        m = (tax >= 0) & (tax <= half)
        t, y = tax[m], vals[m]
        two = int(self.p.get('ajuste')) == 2
        try:
            if len(t) < 8:
                raise RuntimeError('poucos pontos')
            yi = float(np.mean(y[-max(2, len(y) // 10):]))
            a = float(y[0] - yi)
            thr = yi + a / np.e
            cross = np.flatnonzero((y - thr) * np.sign(a) <= 0)
            tau = float(t[cross[0]]) if cross.size and t[cross[0]] > 0 else half / 4
            if two:
                f = lambda tt, y0, a1, t1, a2, t2: y0 + a1 * np.exp(-tt / t1) + a2 * np.exp(-tt / t2)
                p0 = (yi, a / 2, tau / 3, a / 2, tau * 3)
                bounds = ((-np.inf, -np.inf, 1e-6, -np.inf, 1e-6), (np.inf, np.inf, 100.0, np.inf, 100.0))
            else:
                f = lambda tt, y0, a1, t1: y0 + a1 * np.exp(-tt / t1)
                p0 = (yi, a, tau)
                bounds = ((-np.inf, -np.inf, 1e-6), (np.inf, np.inf, 100.0))
            popt, _ = curve_fit(f, t, y, p0=p0, bounds=bounds, maxfev=20000)
            res = y - f(t, *popt)
            ss = float(np.sum((y - y.mean()) ** 2))
            r2 = 1.0 - float(np.sum(res ** 2)) / ss if ss > 0 else float('nan')
            out = [f'{popt[0]:.6g}', f'{popt[1]:.6g}', f'{popt[2]:.6g}']
            out += [f'{popt[3]:.6g}', f'{popt[4]:.6g}'] if two else ['', '']
            return out + [f'{r2:.5f}']
        except Exception as e:
            self.log(f'  ajuste não convergiu: {e}')
            return ['', '', '', '', '', '']

    def _write(self):
        if not self.avgs:
            return
        p = self.p
        n = min(len(self.tax), min(len(v) for _, _, v in self.avgs))
        self.csv = os.path.join(self.folder, self.stem + '.csv')
        hdr = (f'# Transientes do OPT101 (forma de onda media do ADC) - Medidas em Serie\n'
               f'# Freq={p["f"]:g} Hz, PWM={p["pwm"]:g} %, Pulsos={p["pulsos"]}, Intervalo={p["intervalo"]:g} s, '
               f'Duracao={p["duracao"]:g} min, Pre={self.w.average_pretrigger_sec:.5f} s\n'
               f'# Inicio das medias: ' + '; '.join(f'M{i + 1:03d}={d:%H:%M:%S} (t={t:.1f} s)'
                                                    for i, (d, t, _) in enumerate(self.avgs)) + '\n')
        try:
            with open(self.csv, 'w', encoding='utf-8', newline='') as fh:
                fh.write(hdr)
                fh.write('Tempo_s,' + ','.join(f'M{i + 1:03d}' for i in range(len(self.avgs))) + '\n')
                for r in range(n):
                    fh.write(f'{self.tax[r]:.6f},' + ','.join(f'{v[r]:.4f}' for _, _, v in self.avgs) + '\n')
            cols = ['Media', 'Inicio', 't_s', 'Pulsos', 'ADC_Min', 'ADC_Max', 'Amplitude']
            if p.get('ajuste'):
                cols += ['Fit_y_inf', 'Fit_A1', 'Fit_tau1_s', 'Fit_A2', 'Fit_tau2_s', 'Fit_R2']
            with open(os.path.join(self.folder, self.stem + '_medias.csv'), 'w', encoding='utf-8', newline='') as fh:
                wr = csv.writer(fh)
                wr.writerow(cols)
                wr.writerows(self.rows)
        except OSError as e:
            self.log(f'  ERRO ao gravar os transientes: {e}')

    def finish(self):
        """Encerra (fim da duração, Pular ou Parar): grava o que já foi medido e volta ao Modo Lock-In."""
        if self.done:
            return
        w = self.w
        self.done = True
        self._write()
        if self.avgs:
            try:
                w._grab_hidden(w.plot1).save(os.path.join(self.folder, self.stem + '.png'))
            except Exception as e:
                self.log(f'  PNG não gravado: {e}')
        w.avg.keep = False
        w.avg.kept = []
        w.avg.last_cycles = []
        if w.average_mode and not self.was_avg:
            w.toggle_display_mode()
        w.sp_pulses.setValue(self.pulses0)
        if self.csv:
            w._session_add(self.csv)
            w.flash(f'Transientes salvos: {self.csv} ({len(self.avgs)} médias)', 6.0)


# --------------------------------------------------------------------------- aba da interface
def _tr(s):
    try:
        import soi_i18n
        return soi_i18n.tr(s)
    except Exception:
        return s


COLS = ('', '#', 'Tipo', 'Nome da etapa', 'Frequência (Hz)', 'PWM %', 'τ / Precisão', 'Pontos / Δt',
        'Repetir', 'Duração', 'Estado')


class SeriesTab(QtWidgets.QWidget):
    """Aba "Medidas em Série": tabela de etapas, editor da etapa selecionada, execução e gráfico da medida atual."""

    def __init__(self, win, medidas_dir, series_dir):
        super().__init__()
        self.win, self.series_dir = win, series_dir
        self.runner = SeriesRunner(win, medidas_dir)
        self.runner.changed.connect(self._on_runner)
        self.runner.finished.connect(self._on_finished)
        self.serie = new_serie()
        self.path = ''
        self.dirty = False
        self._loading = False
        self._build()
        last = QtCore.QSettings('LCTM', 'SOI Controller').value('serie_arquivo', '', type=str)
        if last and os.path.exists(last):
            try:
                self._set_serie(load(last), last)
            except (OSError, ValueError) as e:
                print(f'Série {last} não carregada: {e}')
        if not self.serie['etapas']:
            self._set_serie(self._example(), '')
        self.plot_timer = QtCore.QTimer(self)
        self.plot_timer.timeout.connect(self._update_plot)
        self.plot_timer.start(1000)

    @staticmethod
    def _example():
        s = new_serie()
        s['etapas'] = [new_step('sinal-t', nome='warmup_f17', f=[17.0], dt=5.0, duracao=20.0),
                       new_step('varredura', nome='adapt2', fmin=20.0, fmax=2440.0, n=25, tau=4.0, precisao=2.0,
                                desligar=True)]
        return s

    # ---- construção
    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        self.lbl_status = QtWidgets.QLabel('Monte a série abaixo (ou abra um arquivo) e clique em Iniciar série.')
        self.lbl_status.setWordWrap(True)
        self._status_style('idle')
        root.addWidget(self.lbl_status)

        row = QtWidgets.QHBoxLayout()
        self.btn_open = QtWidgets.QPushButton('Abrir série...')
        self.btn_save = QtWidgets.QPushButton('Salvar')
        self.btn_saveas = QtWidgets.QPushButton('Salvar como...')
        self.btn_new = QtWidgets.QPushButton('Nova')
        self.btn_open.clicked.connect(self.open_file)
        self.btn_save.clicked.connect(lambda: self.save_file(False))
        self.btn_saveas.clicked.connect(lambda: self.save_file(True))
        self.btn_new.clicked.connect(self.new_file)
        self.btn_open.setToolTip('Abre um arquivo .serie.txt (também a cópia gravada na pasta de uma série já rodada,\n'
                                 'para repetir a mesma medida).')
        for b in (self.btn_open, self.btn_save, self.btn_saveas, self.btn_new):
            row.addWidget(b)
        self.lbl_file = QtWidgets.QLabel('')
        self.lbl_file.setStyleSheet('color:#555;')
        row.addWidget(self.lbl_file)
        row.addSpacing(20)
        lb = QtWidgets.QLabel('Nome base:')
        lb.setStyleSheet('font-weight:bold;')
        row.addWidget(lb)
        self.ed_base = QtWidgets.QLineEdit()
        self.ed_base.setFixedWidth(150)
        self.ed_base.setPlaceholderText('= Amostra')
        self.ed_base.setToolTip('Início do nome dos arquivos: Nome base + "_" + nome da etapa.\n'
                                'Vazio = o nome da Amostra da barra de cima.')
        self.ed_base.textEdited.connect(self._on_header)
        row.addWidget(self.ed_base)
        row.addSpacing(14)
        self.chk_start = QtWidgets.QCheckBox('Começar às')
        self.chk_start.setToolTip('A série espera (com o laser parado) até este horário.\n'
                                  'Se o horário já passou hoje, começa amanhã.')
        self.ed_start = QtWidgets.QTimeEdit()
        self.ed_start.setDisplayFormat('HH:mm')
        self.ed_start.setTime(QtCore.QTime(22, 0))
        self.lbl_start_day = QtWidgets.QLabel('')
        self.lbl_start_day.setStyleSheet('color:#555;')
        self.chk_start.toggled.connect(self._on_header)
        self.ed_start.timeChanged.connect(self._on_header)
        row.addWidget(self.chk_start)
        row.addWidget(self.ed_start)
        row.addWidget(self.lbl_start_day)
        row.addSpacing(14)
        row.addWidget(QtWidgets.QLabel('Repetir a série:'))
        self.sp_cycles = QtWidgets.QSpinBox()
        self.sp_cycles.setRange(1, 999)
        self.sp_cycles.setSuffix(' ×')
        self.sp_cycles.setToolTip('Roda a série inteira N vezes (arquivos com _ciclo1, _ciclo2, ...).')
        self.sp_cycles.valueChanged.connect(self._on_header)
        row.addWidget(self.sp_cycles)
        row.addSpacing(14)
        self.chk_end_off = QtWidgets.QCheckBox('Laser parado no fim')
        self.chk_end_off.setChecked(True)
        self.chk_end_off.setToolTip('No fim da série (ou ao parar), PWM 0.')
        self.chk_end_off.toggled.connect(self._on_header)
        row.addWidget(self.chk_end_off)
        row.addStretch(1)
        root.addLayout(row)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        root.addWidget(split, 1)
        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.tbl = QtWidgets.QTableWidget(0, len(COLS))
        self.tbl.setHorizontalHeaderLabels([_tr(c) for c in COLS])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setAlternatingRowColors(False)
        for i, wd in enumerate((24, 28, 80, 150, 105, 50, 130, 70, 55, 125)):
            self.tbl.setColumnWidth(i, wd)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.itemSelectionChanged.connect(self._on_select)
        self.tbl.itemChanged.connect(self._on_item_changed)
        lv.addWidget(self.tbl, 1)
        add = QtWidgets.QHBoxLayout()
        for txt, tipo in (('+ Varredura f', 'varredura'), ('+ Sinal x t', 'sinal-t'),
                          ('+ Transiente (OPT101)', 'transiente'), ('+ Pausa (laser parado)', 'pausa'),
                          ('+ Aviso (espera o operador)', 'aviso')):
            b = QtWidgets.QPushButton(txt)
            b.clicked.connect(lambda _=False, t=tipo: self.add_step(t))
            add.addWidget(b)
        add.addSpacing(10)
        self.btn_dup = QtWidgets.QPushButton('Duplicar')
        self.btn_up = QtWidgets.QPushButton('▲')
        self.btn_down = QtWidgets.QPushButton('▼')
        self.btn_del = QtWidgets.QPushButton('Remover')
        self.btn_up.setFixedWidth(32)
        self.btn_down.setFixedWidth(32)
        self.btn_dup.clicked.connect(self.dup_step)
        self.btn_up.clicked.connect(lambda: self.move_step(-1))
        self.btn_down.clicked.connect(lambda: self.move_step(1))
        self.btn_del.clicked.connect(self.del_step)
        for b in (self.btn_dup, self.btn_up, self.btn_down, self.btn_del):
            add.addWidget(b)
        add.addStretch(1)
        lv.addLayout(add)
        self.lbl_total = QtWidgets.QLabel('')
        self.lbl_total.setStyleSheet('color:#555;')
        lv.addWidget(self.lbl_total)
        self.edit_widgets = [self.btn_open, self.btn_new, self.ed_base, self.chk_start, self.ed_start,
                             self.sp_cycles, self.chk_end_off, self.btn_dup, self.btn_up, self.btn_down, self.btn_del]
        self.edit_widgets += [add.itemAt(i).widget() for i in range(5)]
        split.addWidget(left)

        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.box = QtWidgets.QGroupBox('Etapa')
        self.box.setStyleSheet('QGroupBox{font-weight:bold;}')
        bl = QtWidgets.QVBoxLayout(self.box)
        self.stack = QtWidgets.QStackedWidget()
        bl.addWidget(self.stack)
        self.forms = {}
        self._build_forms()
        rv.addWidget(self.box)
        self.plot = pg.PlotWidget()
        self.plot.setBackground('w')
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setTitle('Medida em andamento')
        self.curve = self.plot.plot([], [], pen=None, symbol='o', symbolSize=6, symbolBrush='royalblue',
                                    symbolPen=None)
        rv.addWidget(self.plot, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 62)
        split.setStretchFactor(1, 38)
        split.setSizes([900, 560])

        ctl = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton('▶ Iniciar série')
        self.btn_start.setStyleSheet('QPushButton{font-weight:bold;background:#cfe2ff;padding:3px 12px;}')
        self.btn_pause = QtWidgets.QPushButton('⏸ Pausar após esta etapa')
        self.btn_pause.setCheckable(True)
        self.btn_cont = QtWidgets.QPushButton('▶ Continuar')
        self.btn_cont.setStyleSheet('QPushButton{font-weight:bold;background:#ffe8b3;padding:3px 12px;}')
        self.btn_skip = QtWidgets.QPushButton('⏭ Pular etapa')
        self.btn_stop = QtWidgets.QPushButton('■ Parar (salva o já medido)')
        self.btn_stop.setStyleSheet('QPushButton{background:#f8d7da;padding:3px 10px;}')
        self.btn_start.clicked.connect(self.start)
        self.btn_pause.toggled.connect(self._on_pause_toggle)
        self.btn_cont.clicked.connect(self.runner.resume)
        self.btn_skip.clicked.connect(self.runner.skip_job)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_skip.setToolTip('Encerra a etapa atual (salva o que já foi medido) e segue para a próxima.')
        for b in (self.btn_start, self.btn_cont, self.btn_pause, self.btn_skip, self.btn_stop):
            ctl.addWidget(b)
        ctl.addSpacing(12)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedWidth(240)
        self.bar.setTextVisible(False)
        ctl.addWidget(self.bar)
        self.lbl_folder = QtWidgets.QLabel('')
        self.lbl_folder.setStyleSheet('color:#555;')
        ctl.addWidget(self.lbl_folder, 1)
        root.addLayout(ctl)
        self._apply_run_ui()

    def _dsp(self, lo, hi, val, dec, suffix, step=1.0, width=95):
        sp = QtWidgets.QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(dec)
        sp.setSingleStep(step)
        sp.setValue(val)
        sp.setSuffix(suffix)
        sp.setFixedWidth(width)
        sp.setKeyboardTracking(False)
        return sp

    def _build_forms(self):
        def grid():
            w = QtWidgets.QWidget()
            g = QtWidgets.QGridLayout(w)
            g.setContentsMargins(2, 2, 2, 2)
            return w, g

        def name_rep(g, f, row=0, rep=True):
            f['nome'] = QtWidgets.QLineEdit()
            f['nome'].setToolTip('Nome da etapa: entra no nome dos arquivos (Nome base + "_" + nome).')
            g.addWidget(QtWidgets.QLabel('Nome:'), row, 0)
            g.addWidget(f['nome'], row, 1, 1, 3)
            if rep:
                f['repetir'] = QtWidgets.QSpinBox()
                f['repetir'].setRange(1, 999)
                f['repetir'].setSuffix(' ×')
                f['repetir'].setToolTip('Repete esta etapa N vezes seguidas (arquivos com _rep1, _rep2, ...).')
                g.addWidget(QtWidgets.QLabel('Repetir:'), row, 4)
                g.addWidget(f['repetir'], row, 5)

        # varredura
        w, g = grid()
        f = {}
        name_rep(g, f)
        f['fmin'] = self._dsp(0.5, 5000.0, 20.0, 2, ' Hz')
        f['fmax'] = self._dsp(0.5, 5000.0, 2440.0, 2, ' Hz')
        f['n'] = QtWidgets.QSpinBox()
        f['n'].setRange(2, 500)
        g.addWidget(QtWidgets.QLabel('f inicial:'), 1, 0)
        g.addWidget(f['fmin'], 1, 1)
        g.addWidget(QtWidgets.QLabel('f final:'), 1, 2)
        g.addWidget(f['fmax'], 1, 3)
        g.addWidget(QtWidgets.QLabel('Pontos (log):'), 1, 4)
        g.addWidget(f['n'], 1, 5)
        f['tau'] = self._dsp(0.05, 30.0, 4.0, 2, ' s', 0.5)
        f['tau_fixo'] = QtWidgets.QCheckBox('τ fixo')
        f['tau_fixo'].setToolTip('Desliga o τ adaptativo: espera 9τ e faz a média por 1τ em cada ponto.\n'
                                 'Com o τ adaptativo, o τ do campo é o τ max.')
        f['precisao'] = self._dsp(0.1, 20.0, 2.0, 1, ' %', 0.5, 70)
        f['lbl_tau'] = QtWidgets.QLabel('τ max:')
        g.addWidget(f['lbl_tau'], 2, 0)
        g.addWidget(f['tau'], 2, 1)
        g.addWidget(f['tau_fixo'], 2, 2)
        g.addWidget(QtWidgets.QLabel('Precisão:'), 2, 3)
        g.addWidget(f['precisao'], 2, 4)
        f['pwm'] = self._dsp(0.0, 100.0, 100.0, 1, ' %', 5.0)
        f['aquecer'] = self._dsp(0.0, 7200.0, 0.0, 0, ' s', 60.0, 80)
        f['aquecer'].setToolTip('Antes da varredura, laser ligado (no PWM da etapa) por este tempo. 0 = sem warm-up.')
        g.addWidget(QtWidgets.QLabel('PWM:'), 3, 0)
        g.addWidget(f['pwm'], 3, 1)
        g.addWidget(QtWidgets.QLabel('Warm-up:'), 3, 2)
        g.addWidget(f['aquecer'], 3, 3)
        f['medias'] = QtWidgets.QSpinBox()
        f['medias'].setRange(1, 20)
        f['medias'].setToolTip('"Permitir médias" do τ adaptativo: até N medidas por ponto (1 = desligado).')
        g.addWidget(QtWidgets.QLabel('Médias:'), 3, 4)
        g.addWidget(f['medias'], 3, 5)
        f['adapt_tudo'] = QtWidgets.QCheckBox('τ adaptativo também abaixo de 40 Hz')
        f['desligar'] = QtWidgets.QCheckBox('Laser parado (PWM 0) ao terminar a etapa')
        g.addWidget(f['adapt_tudo'], 4, 0, 1, 3)
        g.addWidget(f['desligar'], 4, 3, 1, 3)
        f['tau_fixo'].toggled.connect(lambda on, ff=f: (ff['precisao'].setEnabled(not on),
                                                        ff['medias'].setEnabled(not on),
                                                        ff['adapt_tudo'].setEnabled(not on),
                                                        ff['lbl_tau'].setText('τ:' if on else 'τ max:')))
        g.setRowStretch(5, 1)
        self.forms['varredura'] = f
        self.stack.addWidget(w)

        # sinal x t
        w, g = grid()
        f = {}
        name_rep(g, f)
        f['f'] = QtWidgets.QLineEdit()
        f['f'].setToolTip('Uma frequência ou uma lista separada por ";" (ex.: 37; 113; 487): uma medida por\n'
                          'frequência. Use {f} no nome para a frequência entrar no nome do arquivo.')
        g.addWidget(QtWidgets.QLabel('Frequências:'), 1, 0)
        g.addWidget(f['f'], 1, 1, 1, 3)
        f['pwm'] = self._pwm_edit()
        g.addWidget(QtWidgets.QLabel('PWM (%):'), 1, 4)
        g.addWidget(f['pwm'], 1, 5)
        f['tau'] = self._dsp(0.05, 30.0, 1.0, 2, ' s', 0.5)
        f['dt'] = self._dsp(0.5, 600.0, 5.0, 1, ' s')
        f['duracao'] = self._dsp(0.1, 1440.0, 10.0, 1, ' min')
        g.addWidget(QtWidgets.QLabel('τ:'), 2, 0)
        g.addWidget(f['tau'], 2, 1)
        g.addWidget(QtWidgets.QLabel('Ponto a cada:'), 2, 2)
        g.addWidget(f['dt'], 2, 3)
        g.addWidget(QtWidgets.QLabel('Duração:'), 2, 4)
        g.addWidget(f['duracao'], 2, 5)
        f['aquecer'] = self._dsp(0.0, 7200.0, 0.0, 0, ' s', 60.0, 80)
        f['aquecer'].setToolTip('Antes da medida, laser ligado (na frequência e no PWM da etapa) por este tempo,\n'
                                'sem gravar. 0 = a medida começa já (o aquecimento aparece no Sinal x t).')
        g.addWidget(QtWidgets.QLabel('Warm-up:'), 3, 0)
        g.addWidget(f['aquecer'], 3, 1)
        f['desligar'] = QtWidgets.QCheckBox('Laser parado (PWM 0) ao terminar a etapa')
        g.addWidget(f['desligar'], 3, 2, 1, 4)
        g.setRowStretch(4, 1)
        self.forms['sinal-t'] = f
        self.stack.addWidget(w)

        # pausa
        w, g = grid()
        f = {}
        name_rep(g, f)
        f['duracao'] = self._dsp(0.1, 1440.0, 10.0, 1, ' min')
        g.addWidget(QtWidgets.QLabel('Duração:'), 1, 0)
        g.addWidget(f['duracao'], 1, 1)
        note = QtWidgets.QLabel('Laser parado (PWM 0), sem gravar: para a amostra esfriar. Para medir o fundo, use '
                                'Sinal x t com PWM 0.')
        note.setWordWrap(True)
        note.setStyleSheet('color:#666;font-weight:normal;')
        g.addWidget(note, 2, 0, 1, 6)
        g.setRowStretch(3, 1)
        self.forms['pausa'] = f
        self.stack.addWidget(w)

        # aviso
        w, g = grid()
        f = {}
        f['texto'] = QtWidgets.QLineEdit()
        g.addWidget(QtWidgets.QLabel('Texto:'), 0, 0)
        g.addWidget(f['texto'], 0, 1, 1, 5)
        note = QtWidgets.QLabel('A série para neste ponto, mostra o texto e espera o clique em Continuar '
                                '(ex.: trocar a amostra). O laser fica como estava.')
        note.setWordWrap(True)
        note.setStyleSheet('color:#666;font-weight:normal;')
        g.addWidget(note, 1, 0, 1, 6)
        g.setRowStretch(2, 1)
        self.forms['aviso'] = f
        self.stack.addWidget(w)

        # transiente (OPT101, Valor Médio)
        w, g = grid()
        f = {}
        name_rep(g, f)
        f['f'] = QtWidgets.QLineEdit()
        f['f'].setToolTip('Uma frequência ou uma lista separada por ";": uma medida por frequência ({f} no nome).')
        g.addWidget(QtWidgets.QLabel('Frequências:'), 1, 0)
        g.addWidget(f['f'], 1, 1, 1, 3)
        f['pwm'] = self._pwm_edit()
        g.addWidget(QtWidgets.QLabel('PWM (%):'), 1, 4)
        g.addWidget(f['pwm'], 1, 5)
        f['pulsos'] = QtWidgets.QSpinBox()
        f['pulsos'].setRange(1, 1000)
        f['pulsos'].setToolTip('Pulsos somados em cada média (como "Pulsos" no modo Valor Médio da aba OPT101).')
        f['intervalo'] = self._dsp(0.0, 86400.0, 60.0, 0, ' s', 10.0, 90)
        f['intervalo'].setToolTip('Uma média começa a cada intervalo (ex.: 64 pulsos a cada 60 s).\n'
                                  '0 = uma média atrás da outra. Se a média demorar mais que o intervalo, a próxima\n'
                                  'começa logo depois dela.')
        f['duracao'] = self._dsp(0.1, 1440.0, 10.0, 1, ' min')
        f['duracao'].setToolTip('Tempo total do acompanhamento.')
        g.addWidget(QtWidgets.QLabel('Pulsos (média):'), 2, 0)
        g.addWidget(f['pulsos'], 2, 1)
        g.addWidget(QtWidgets.QLabel('Uma média a cada:'), 2, 2)
        g.addWidget(f['intervalo'], 2, 3)
        g.addWidget(QtWidgets.QLabel('Duração:'), 2, 4)
        g.addWidget(f['duracao'], 2, 5)
        f['ajuste'] = QtWidgets.QComboBox()
        f['ajuste'].addItems(['sem ajuste', '1 exponencial', '2 exponenciais'])
        f['ajuste'].setToolTip('Ajuste exponencial de cada média no laser ligado (t de 0 a meio período);\n'
                               'τ, amplitude e R² vão para o arquivo _medias.csv.')
        f['individuais'] = QtWidgets.QCheckBox('Guardar os transientes individuais')
        f['individuais'].setToolTip('Grava também os N pulsos de cada média (pasta <arquivo>_individuais, um CSV por média).')
        g.addWidget(QtWidgets.QLabel('Ajuste:'), 3, 0)
        g.addWidget(f['ajuste'], 3, 1)
        g.addWidget(f['individuais'], 3, 2, 1, 4)
        f['aquecer'] = self._dsp(0.0, 7200.0, 0.0, 0, ' s', 60.0, 80)
        f['aquecer'].setToolTip('Antes do acompanhamento, laser ligado (na frequência e no PWM) por este tempo, sem gravar.')
        g.addWidget(QtWidgets.QLabel('Warm-up:'), 4, 0)
        g.addWidget(f['aquecer'], 4, 1)
        f['desligar'] = QtWidgets.QCheckBox('Laser parado (PWM 0) ao terminar a etapa')
        g.addWidget(f['desligar'], 4, 2, 1, 4)
        f['lbl_n'] = QtWidgets.QLabel('')
        f['lbl_n'].setStyleSheet('color:#666;font-weight:normal;')
        g.addWidget(f['lbl_n'], 5, 0, 1, 6)
        g.setRowStretch(6, 1)
        self.forms['transiente'] = f
        self.stack.addWidget(w)

        for tipo, f in self.forms.items():
            for key, wd in f.items():
                if key in ('lbl_tau', 'lbl_n'):
                    continue
                if isinstance(wd, QtWidgets.QLineEdit):
                    wd.editingFinished.connect(lambda t=tipo: self._form_to_step(t))
                elif isinstance(wd, QtWidgets.QCheckBox):
                    wd.toggled.connect(lambda _=False, t=tipo: self._form_to_step(t))
                elif isinstance(wd, QtWidgets.QComboBox):
                    wd.currentIndexChanged.connect(lambda _=0, t=tipo: self._form_to_step(t))
                else:
                    wd.valueChanged.connect(lambda _=0, t=tipo: self._form_to_step(t))

    def _pwm_edit(self):
        e = QtWidgets.QLineEdit()
        e.setFixedWidth(110)
        e.setToolTip('Um PWM ou uma lista separada por ";" (ex.: 25; 50; 100): uma medida por potência.\n'
                     'Use {pwm} no nome para o PWM entrar no nome do arquivo.')
        return e

    # ---- série <-> tela
    def _set_serie(self, serie, path):
        self.serie, self.path = serie, path
        self._loading = True
        self.ed_base.setText(serie.get('nome_base', ''))
        ini = serie.get('inicio', '')
        self.chk_start.setChecked(bool(ini))
        if ini:
            try:
                self.ed_start.setTime(QtCore.QTime(parse_inicio(ini).hour, parse_inicio(ini).minute))
            except ValueError:
                pass
        self.sp_cycles.setValue(int(serie.get('repetir', 1)))
        self.chk_end_off.setChecked(serie.get('fim', 'laser_parado') == 'laser_parado')
        self._loading = False
        self.dirty = False
        self._refresh_table()
        if serie['etapas']:
            self.tbl.selectRow(0)
        self._on_select()
        self._update_file_label()

    def _on_header(self, *_):
        if self._loading:
            return
        self.serie['nome_base'] = self.ed_base.text().strip()
        self.serie['inicio'] = self.ed_start.time().toString('HH:mm') if self.chk_start.isChecked() else ''
        self.serie['repetir'] = self.sp_cycles.value()
        self.serie['fim'] = 'laser_parado' if self.chk_end_off.isChecked() else 'manter'
        self._mark_dirty()
        self._refresh_table()

    def _mark_dirty(self):
        self.dirty = True
        self._update_file_label()

    def _update_file_label(self):
        name = os.path.basename(self.path) if self.path else _tr('(série nova, não salva)')
        self.lbl_file.setText(name + (' *' if self.dirty else ''))
        if self.chk_start.isChecked():
            try:
                d = parse_inicio(self.ed_start.time().toString('HH:mm'))
                self.lbl_start_day.setText(_tr('hoje') if d.date() == datetime.now().date() else _tr('amanhã'))
            except ValueError:
                self.lbl_start_day.setText('')
        else:
            self.lbl_start_day.setText('')

    def _row_texts(self, st):
        t = st['tipo']
        dur = ''
        reps = max(1, int(st.get('repetir', 1))) if t != 'aviso' else 1
        if t == 'varredura':
            freq = f"{st['fmin']:g} – {st['fmax']:g}"
            tau = f"τ fixo {st['tau']:g} s" if st['tau_fixo'] else f"τ max {st['tau']:g} s · {st['precisao']:g} %"
            pts = f"{st['n']} pts"
            lo, hi = self.win._series_sweep_estimate(st)
            one = fmt_dur(hi) if abs(hi - lo) < 30 else f'{fmt_dur(lo)}–{fmt_dur(hi)}'
            dur = (f'{reps} × ' if reps > 1 else '') + '~' + one
            pwm = f"{st['pwm']:g}"
        elif t == 'sinal-t':
            freq = '; '.join(f'{v:g}' for v in st['f'])
            tau = f"τ {st['tau']:g} s"
            pts = f"{st['dt']:g} s"
            n = len(st['f']) * reps
            one = fmt_dur(60 * st['duracao'] + st.get('aquecer', 0))
            dur = f'{n} × {one}' if n > 1 else one
            pwm = '; '.join(f'{v:g}' for v in st['pwm'])
        elif t == 'transiente':
            freq = '; '.join(f'{v:g}' for v in st['f'])
            pwm = '; '.join(f'{v:g}' for v in st['pwm'])
            iv = st['intervalo']
            tau = f"{st['pulsos']} pulsos" + (f" · fit {st['ajuste']} exp" if st.get('ajuste') else '')
            pts = (f'a cada {iv:g} s' if iv > 0 else _tr('contínuo')) + (' + ind.' if st.get('individuais') else '')
            n = len(st['f']) * len(st['pwm']) * reps
            one = fmt_dur(60 * st['duracao'] + st.get('aquecer', 0))
            dur = f'{n} × {one}' if n > 1 else one
        elif t == 'pausa':
            freq, tau, pts, pwm = '', '', '', '0'
            one = fmt_dur(60 * st['duracao'])
            dur = f'{reps} × {one}' if reps > 1 else one
        else:
            freq, tau, pts, pwm = '', '', '', ''
            dur = _tr('espera')
        name = st.get('texto', '') if t == 'aviso' else st.get('nome', '')
        rep = str(reps) if t != 'aviso' else ''
        return [_tr(TIPO_NOME[t]), name, freq, pwm, tau, pts, rep, dur]

    def _refresh_table(self):
        self._loading = True
        sel = self._sel()
        self.tbl.setRowCount(len(self.serie['etapas']))
        for i, st in enumerate(self.serie['etapas']):
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled
                         | QtCore.Qt.ItemFlag.ItemIsSelectable)
            chk.setCheckState(QtCore.Qt.CheckState.Checked if st.get('ativa', True) else QtCore.Qt.CheckState.Unchecked)
            chk.setToolTip(_tr('Desmarcada: a etapa fica na série, mas não roda.'))
            self.tbl.setItem(i, 0, chk)
            self.tbl.setItem(i, 1, QtWidgets.QTableWidgetItem(str(i + 1)))
            for j, txt in enumerate(self._row_texts(st)):
                it = QtWidgets.QTableWidgetItem(txt)
                if st['tipo'] in ('aviso', 'pausa') and j == 1:
                    fnt = it.font()
                    fnt.setItalic(True)
                    it.setFont(fnt)
                if not st.get('ativa', True):
                    it.setForeground(QtGui.QColor('#999'))
                self.tbl.setItem(i, j + 2, it)
            self.tbl.setItem(i, len(COLS) - 1, QtWidgets.QTableWidgetItem(''))
            if st['tipo'] == 'aviso':
                self.tbl.setSpan(i, 3, 1, 5)
            elif self.tbl.columnSpan(i, 3) > 1:
                self.tbl.setSpan(i, 3, 1, 1)
        self._loading = False
        if sel is not None and sel < self.tbl.rowCount():
            self.tbl.selectRow(sel)
        self._refresh_states()
        self._refresh_total()

    def _refresh_total(self):
        jobs = expand(self.serie)
        lo, hi, av = self.runner.total_estimate(jobs)
        txt = (f'{len(jobs)} medidas/etapas · tempo estimado: '
               + (fmt_dur(hi) if hi - lo < 60 else f'{fmt_dur(lo)} a {fmt_dur(hi)}'))
        if av:
            txt += f' (+ {av} aviso(s) que esperam o operador)'
        txt += ' · ☑ = etapa incluída'
        self.lbl_total.setText(txt)

    def _refresh_states(self):
        """Coluna Estado e cores das linhas (durante e depois de uma série)."""
        r = self.runner
        per_step = {}
        if r.jobs and r.serie is self.serie:
            for k, j in enumerate(r.jobs):
                per_step.setdefault(j['etapa'], []).append(r.status.get(k, 'na fila'))
        cur_step = r.job()['etapa'] if (r.active and r.job()) else None
        self._loading, was = True, self._loading
        try:
            self._paint_states(per_step, cur_step)
        finally:
            self._loading = was

    def _paint_states(self, per_step, cur_step):
        r = self.runner
        for i in range(self.tbl.rowCount()):
            sts = per_step.get(i)
            txt, color, bg = '', None, None
            if sts:
                n, done = len(sts), sum(1 for s in sts if s in ('concluída', 'pulada', 'parada', 'falhou'))
                if i == cur_step and r.active:
                    k = next((q for q, s in enumerate(sts) if s == 'em andamento'), done)
                    txt = '▶ ' + (_tr('em andamento') if n == 1 else f'{k + 1} de {n}')
                    if r.state == 'aviso':
                        txt = '▶ ' + _tr('esperando Continuar')
                    elif r.state == 'warm':
                        txt = '▶ warm-up'
                    color, bg = '#1565c0', '#eaf2fd'
                elif done == n:
                    bad = [s for s in sts if s != 'concluída']
                    txt = ('✓ ' + _tr('concluída')) if not bad else ('⚠ ' + _tr(bad[-1]))
                    color, bg = ('#2e7d32', '#f1f8f1') if not bad else ('#b26a00', '#fff6e5')
                elif done:
                    txt = f'{done} de {n}'
                else:
                    txt = _tr('na fila')
            it = self.tbl.item(i, len(COLS) - 1)
            if it is None:
                continue
            it.setText(txt)
            fnt = it.font()
            fnt.setBold(bool(color))
            it.setFont(fnt)
            it.setForeground(QtGui.QColor(color) if color else QtGui.QBrush())
            for j in range(len(COLS)):
                cell = self.tbl.item(i, j)
                if cell is not None:
                    cell.setBackground(QtGui.QColor(bg) if bg else QtGui.QBrush())

    def _sel(self):
        rows = self.tbl.selectionModel().selectedRows() if self.tbl.selectionModel() else []
        return rows[0].row() if rows else None

    def _on_select(self):
        if self._loading:
            return
        i = self._sel()
        if i is None or i >= len(self.serie['etapas']):
            self.box.setTitle(_tr('Etapa'))
            self.stack.setEnabled(False)
            return
        st = self.serie['etapas'][i]
        t = st['tipo']
        self.box.setTitle(f'{_tr("Etapa")} {i + 1}: {_tr(TIPO_NOME[t])}')
        self.stack.setCurrentIndex(TIPOS.index(t))
        self.stack.setEnabled(not self.runner.active)
        f = self.forms[t]
        self._loading = True
        for key, wd in f.items():
            if key in ('lbl_tau', 'lbl_n'):
                continue
            v = st.get(key, DEFAULTS[t].get(key))
            if isinstance(wd, QtWidgets.QLineEdit):
                wd.setText(fmt_flist(v).replace(';', '; ') if key in ('f', 'pwm') else str(v))
            elif isinstance(wd, QtWidgets.QComboBox):
                wd.setCurrentIndex(int(v))
            elif isinstance(wd, QtWidgets.QCheckBox):
                wd.setChecked(bool(v))
            else:
                wd.setValue(v)
        if t == 'transiente':
            self._upd_n(st)
        if t == 'varredura':
            on = st['tau_fixo']
            for k in ('precisao', 'medias', 'adapt_tudo'):
                f[k].setEnabled(not on)
            f['lbl_tau'].setText('τ:' if on else 'τ max:')
        self._loading = False

    def _form_to_step(self, tipo):
        if self._loading:
            return
        i = self._sel()
        if i is None:
            return
        st = self.serie['etapas'][i]
        if st['tipo'] != tipo:
            return
        for key, wd in self.forms[tipo].items():
            if key in ('lbl_tau', 'lbl_n'):
                continue
            if isinstance(wd, QtWidgets.QLineEdit):
                if key in ('f', 'pwm'):
                    try:
                        st[key] = parse_flist(wd.text()) if key == 'f' else parse_pwmlist(wd.text())
                        wd.setStyleSheet('')
                    except ValueError:
                        wd.setStyleSheet('background:#ffd6d6;')
                        self.win.flash('Frequências: números separados por ";" (ex.: 37; 113; 487).' if key == 'f'
                                       else 'PWM: números de 0 a 100 separados por ";" (ex.: 25; 50; 100).')
                else:
                    st[key] = wd.text().strip()
            elif isinstance(wd, QtWidgets.QComboBox):
                st[key] = wd.currentIndex()
            elif isinstance(wd, QtWidgets.QCheckBox):
                st[key] = wd.isChecked()
            else:
                st[key] = wd.value()
        if tipo == 'transiente':
            self._upd_n(st)
        self._mark_dirty()
        self._refresh_table()

    def _upd_n(self, st):
        iv, dur = st['intervalo'], 60.0 * st['duracao']
        per = st['pulsos'] / max(min(st['f']), 0.1)
        if iv > 0:
            txt = (f'{int(np.ceil(dur / iv))} médias de {st["pulsos"]} pulsos por medida '
                   f'(cada média leva ~{per:.3g} s no laser de {min(st["f"]):g} Hz)')
            if per > iv:
                txt += ' — a média é mais longa que o intervalo: as médias ficam seguidas'
        else:
            txt = f'Médias seguidas por {st["duracao"]:g} min (~{int(dur / max(per, 1e-3))} médias de ~{per:.3g} s)'
        self.forms['transiente']['lbl_n'].setText(txt)

    def _on_item_changed(self, it):
        if self._loading or it.column() != 0:
            return
        i = it.row()
        on = it.checkState() == QtCore.Qt.CheckState.Checked
        if i < len(self.serie['etapas']) and self.serie['etapas'][i].get('ativa', True) != on:
            self.serie['etapas'][i]['ativa'] = on
            self._mark_dirty()
            self._refresh_table()

    # ---- edição da lista
    def add_step(self, tipo):
        i = self._sel()
        pos = len(self.serie['etapas']) if i is None else i + 1
        st = new_step(tipo)
        if tipo == 'varredura':
            sp0, sp1, _sp, spn, _ = self.win.dual_fw['F']
            st.update(fmin=min(sp0.value(), sp1.value()), fmax=max(sp0.value(), sp1.value()), n=int(spn.value()))
        self.serie['etapas'].insert(pos, st)
        self._mark_dirty()
        self._refresh_table()
        self.tbl.selectRow(pos)

    def dup_step(self):
        i = self._sel()
        if i is None:
            return
        st = {k: (list(v) if isinstance(v, list) else v) for k, v in self.serie['etapas'][i].items()}
        self.serie['etapas'].insert(i + 1, st)
        self._mark_dirty()
        self._refresh_table()
        self.tbl.selectRow(i + 1)

    def move_step(self, d):
        i = self._sel()
        if i is None or not 0 <= i + d < len(self.serie['etapas']):
            return
        e = self.serie['etapas']
        e[i], e[i + d] = e[i + d], e[i]
        self._mark_dirty()
        self._refresh_table()
        self.tbl.selectRow(i + d)

    def del_step(self):
        i = self._sel()
        if i is None:
            return
        del self.serie['etapas'][i]
        self._mark_dirty()
        self._refresh_table()
        if self.serie['etapas']:
            self.tbl.selectRow(min(i, len(self.serie['etapas']) - 1))
        self._on_select()

    # ---- arquivos
    def _ask_discard(self):
        if not self.dirty:
            return True
        ans = QtWidgets.QMessageBox.question(
            self, 'Medidas em Série', 'A série atual tem mudanças não salvas. Descartar?',
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        return ans == QtWidgets.QMessageBox.StandardButton.Yes

    def open_file(self):
        if not self._ask_discard():
            return
        os.makedirs(self.series_dir, exist_ok=True)
        start = os.path.dirname(self.path) if self.path else self.series_dir
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Abrir série', start, 'Séries do SOI (*.serie.txt);;Texto (*.txt);;Todos (*)')
        if not path:
            return
        try:
            serie = load(path)
        except (OSError, ValueError) as e:
            QtWidgets.QMessageBox.warning(self, 'Abrir série', f'Não foi possível abrir {os.path.basename(path)}:\n{e}')
            return
        self._set_serie(serie, path)
        self._remember(path)

    def save_file(self, ask):
        path = self.path
        # a cópia gravada na pasta de uma série rodada fica como registro: "Salvar" vai para Salvar como
        if ask or not path or os.path.basename(os.path.dirname(path)).startswith('Serie_'):
            os.makedirs(self.series_dir, exist_ok=True)
            base = safe_name(self.serie.get('nome_base') or 'serie')
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, 'Salvar série', os.path.join(self.series_dir, base + SERIE_EXT), 'Séries do SOI (*.serie.txt)')
            if not path:
                return False
            if not path.endswith(SERIE_EXT):
                path = os.path.splitext(path)[0].removesuffix('.serie') + SERIE_EXT
        try:
            save(path, self.serie)
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, 'Salvar série', f'Erro ao salvar:\n{e}')
            return False
        self.path = path
        self.dirty = False
        self._update_file_label()
        self._remember(path)
        self.win.flash(f'Série salva: {path}')
        return True

    def new_file(self):
        if not self._ask_discard():
            return
        self._set_serie(new_serie(), '')

    @staticmethod
    def _remember(path):
        QtCore.QSettings('LCTM', 'SOI Controller').setValue('serie_arquivo', path)

    # ---- execução
    def start(self):
        if self.runner.active:
            return
        if not self.serie['etapas']:
            self.win.flash('Adicione etapas antes de iniciar.')
            return
        self._on_header()
        if self.runner.start(self.serie, self.path):
            self.btn_pause.setChecked(False)
            self.lbl_folder.setText(_tr('Pasta:') + ' ' + self.runner.folder)
            self.lbl_folder.setToolTip(self.runner.folder)
        self._apply_run_ui()

    def stop(self):
        self.runner.stop()

    def _on_pause_toggle(self, on):
        self.runner.pause_after = on

    def _apply_run_ui(self):
        on = self.runner.active
        for wd in self.edit_widgets:
            wd.setEnabled(not on)
        self.tbl.setEnabled(True)
        self.stack.setEnabled(not on and self._sel() is not None)
        self.btn_start.setEnabled(not on)
        for b in (self.btn_pause, self.btn_skip, self.btn_stop):
            b.setEnabled(on)
        self.btn_cont.setVisible(on and self.runner.state in ('aviso', 'paused'))
        self.btn_pause.setVisible(not self.btn_cont.isVisible())
        self.bar.setVisible(on)

    def _status_style(self, kind):
        css = {'idle': 'background:#f4f4f4;border:1px solid #ccc;',
               'run': 'background:#e7f5e9;border:1px solid #6fbf73;',
               'wait': 'background:#fff3cd;border:1px solid #e0a800;',
               'done': 'background:#e7f1ff;border:1px solid #6ea8fe;'}[kind]
        self.lbl_status.setStyleSheet(css + 'border-radius:4px;padding:4px;')

    def _on_runner(self):
        r = self.runner
        self._apply_run_ui()
        self._refresh_states()
        if not r.active:
            return
        cur, total, end = r.remaining()
        n = len(r.jobs)
        if r.state == 'wait_start':
            self._status_style('wait')
            self.lbl_status.setText(
                f'⏰ {_tr("Aguardando o início às")} {r.wait_until.strftime("%d/%m %H:%M")} '
                f'({_tr("faltam")} {fmt_dur(cur)}; {_tr("laser parado")}) · {n} {_tr("medidas")}, '
                f'{_tr("fim previsto às")} {end.strftime("%H:%M")}')
            self.bar.setValue(0)
            return
        j = r.job()
        if j is None:
            return
        p = j['p']
        if j['tipo'] == 'varredura':
            what = f"Varredura {p['fmin']:g}–{p['fmax']:g} Hz"
        elif j['tipo'] == 'sinal-t':
            what = f"Sinal x t {p['f']:g} Hz, PWM {p['pwm']:g} %"
        elif j['tipo'] == 'transiente':
            tj = getattr(r, 'tjob', None)
            nn = tj.count() if tj else None
            what = (f"Transiente {p['f']:g} Hz, PWM {p['pwm']:g} %, {p['pulsos']} pulsos"
                    + (f" · {_tr('média')} {tj.k + (1 if tj.waiting else 0)}" + (f'/{nn}' if nn else '') if tj else ''))
        elif j['tipo'] == 'pausa':
            what = f"Pausa (laser parado) {p['duracao']:g} min"
        else:
            what = 'Aviso'
        head = f'{_tr("Medida")} {r.idx + 1} {_tr("de")} {n} · {what}' + (f' · "{j["nome"]}"' if j['nome'] else '')
        if r.state == 'aviso':
            self._status_style('wait')
            self.lbl_status.setText(f'⚠ {p.get("texto", "")}  —  {_tr("clique em Continuar")} '
                                    f'({_tr("Medida")} {r.idx + 1} {_tr("de")} {n})')
        elif r.state == 'paused':
            self._status_style('wait')
            self.lbl_status.setText(f'⏸ {_tr("Série pausada")} ({_tr("próxima")}: {r.idx + 2} {_tr("de")} {n}). '
                                    f'{_tr("Clique em Continuar")}.')
        else:
            self._status_style('run')
            stage = {'warm': ' · warm-up', 'settle': ' · ' + _tr('assentando'), 'pause': ''}.get(r.state, '')
            self.lbl_status.setText(
                f'▶ {head}{stage}' + (f' · {_tr("restante")} {fmt_dur(cur)}' if cur is not None else '')
                + f'   |   {_tr("Série")}: {fmt_dur(time.time() - r.t0_series)} {_tr("decorridos")}, '
                + f'~{fmt_dur(total)} {_tr("restantes")}' + (f', {_tr("fim previsto às")} {end.strftime("%H:%M")}'
                                                            if end else ''))
        done = time.time() - r.t0_series
        self.bar.setValue(int(1000 * done / max(done + total, 1.0)))

    def _on_finished(self, txt):
        self._status_style('done')
        self.lbl_status.setText('✓ ' + txt)
        self._apply_run_ui()
        self._refresh_states()

    def _update_plot(self):
        r, w = self.runner, self.win
        tj = getattr(r, 'tjob', None)
        if r.active and r.state == 'run' and tj is not None:
            if tj.avgs and getattr(self, '_plot_k', None) != (id(tj), tj.k):
                self._plot_k = (id(tj), tj.k)
                v = tj.avgs[-1][2]
                n = min(len(v), len(tj.tax))
                self.plot.setLogMode(x=False, y=False)
                self.curve.setSymbol(None)
                self.curve.setPen(pg.mkPen('royalblue', width=2))
                self.curve.setData(tj.tax[:n] * 1000.0, v[:n])
                self.plot.setLabel('bottom', 'Tempo (ms)')
                self.plot.setLabel('left', 'ADC médio')
                self.plot.setTitle(f'{_tr("Medida em andamento")}: {r.job()["nome"]} · {_tr("média")} {tj.k}')
            return
        if not (r.active and r.state == 'run' and w.dual_active):
            return
        self.curve.setPen(None)
        self.curve.setSymbol('o')
        res = list(getattr(w, 'dual_results', []) or [])
        if not res:
            self.curve.setData([], [])
            return
        x = [q[0] for q in res]
        s = [q[3] / max(q[1], 1e-30) for q in res]
        sweep = w.dual_src != 'T'
        self.plot.setLogMode(x=sweep, y=sweep)
        self.plot.setLabel('bottom', 'Frequência (Hz)' if sweep else 'Tempo (s)')
        self.plot.setLabel('left', 'S = R_INMP441 / R_OPT101')
        self.plot.setTitle(f'{_tr("Medida em andamento")}: {r.job()["nome"]}')
        self.curve.setData(x, s)

    def on_close(self):
        """Fechando a interface com uma série rodando: para e salva o que já foi medido."""
        if self.runner.active:
            self.runner.stop()
