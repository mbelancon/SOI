# -*- coding: utf-8 -*-
'''Tudo o que os módulos da janela usam: constantes, análise, DSP, serial, simulação e widgets.'''
from soi_const import *  # noqa: F401,F403
from soi_analise import *  # noqa: F401,F403
from soi_dsp import *  # noqa: F401,F403
from soi_serial import *  # noqa: F401,F403
from soi_sim import *  # noqa: F401,F403
from soi_widgets import *  # noqa: F401,F403


# Exporta tudo (inclusive nomes com _) para os módulos que fazem import *
__all__ = [_n for _n in dir() if not _n.startswith('__')]
