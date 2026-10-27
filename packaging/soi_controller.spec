# -*- mode: python ; coding: utf-8 -*-
# Spec do PyInstaller para gerar o executável do SOI Controller.
#
# Uso (a partir da raiz do repositório, num venv só com requirements-build.txt):
#   pyinstaller packaging/soi_controller.spec              -> dist/SOI_Controller.exe (arquivo único)
#   pyinstaller packaging/soi_controller.spec -- --onedir  -> dist/SOI_Controller/ (pasta)
#   pyinstaller packaging/soi_controller.spec -- --upx     -> comprime com UPX (não recomendado:
#     o Controle Inteligente de Aplicativos do Windows 11 bloqueia as DLLs comprimidas)
import argparse
import os
import re

parser = argparse.ArgumentParser()
parser.add_argument('--onedir', action='store_true')
parser.add_argument('--upx', action='store_true')
opts = parser.parse_args()

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
NAME = 'SOI_Controller'

# Módulos que a interface não usa (nem o pyqtgraph com PySide6).
EXCLUDES = [
    'tkinter', '_tkinter', 'matplotlib', 'IPython', 'jupyter', 'notebook',
    'PyQt5', 'PyQt6', 'PySide2', 'pandas', 'PIL', 'cupy', 'numba', 'h5py',
    'pyqtgraph.opengl', 'pyqtgraph.examples', 'pyqtgraph.jupyter',
    'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSql', 'PySide6.QtXml',
    'PySide6.QtMultimedia', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtUiTools', 'PySide6.QtConcurrent',
    'PySide6.QtDBus', 'PySide6.QtPrintSupport',
]

# Arquivos do Qt que não fazem falta: o renderizador OpenGL por software
# (opengl32sw.dll, ~20 MB), traduções, e bibliotecas/plugins de módulos não usados.
# (QtOpenGL e QtOpenGLWidgets ficam: o PlotCurveItem do pyqtgraph os importa.)
DROP = re.compile(
    r'(opengl32sw|d3dcompiler_\d+|Qt6(Network|Qml|Quick|Pdf|Sql|Xml|Multimedia|WebEngine|'
    r'Designer|Help|UiTools|VirtualKeyboard|Positioning|Charts)|'
    r'[\\/]translations[\\/]|'
    r'[\\/]plugins[\\/](imageformats[\\/]q(?!svg|ico)|tls|networkinformation|'
    r'generic|platforminputcontexts|qmltooling|sqldrivers|multimedia|virtualkeyboard|'
    r'position|printsupport))',
    re.IGNORECASE)


def keep(entry):
    return not (DROP.search(entry[0]) or DROP.search(entry[1]))


a = Analysis(
    [os.path.join(ROOT, 'interface', 'stm32_opt_inmmp_novo.py')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)
a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]

pyz = PYZ(a.pure)

common = dict(
    name=NAME,
    debug=False,
    strip=False,
    upx=opts.upx,
    console=False,
)

if opts.onedir:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=opts.upx,
                   upx_exclude=[], name=NAME)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              upx_exclude=[], runtime_tmpdir=None, **common)
