"""Window size check (2.5.0): builds the interface without a screen and verifies that its minimum size fits a
1366×768 screen at 125 % Windows scaling (~1093×585 logical pixels of usable area), with the panels opened one by one.

Run from the repository root:
    QT_QPA_PLATFORM=offscreen python docs/tests/check_window_size.py        (Linux)
    set QT_QPA_PLATFORM=offscreen & python docs\\tests\\check_window_size.py  (Windows)
SOI_LANG=en checks the English interface. Exit code 1 if any state does not fit.
"""
import os
import sys
import time

LIMIT_W, LIMIT_H = 1093, 585


def main():
    os.environ.setdefault('SOI_NO_SERIAL', '1')
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'interface'))
    import soi_controller as sc
    app = sc.pg.mkQApp('size-check')
    win = sc.LockInWindow()
    win.show()

    def pump(s):
        t = time.time()
        while time.time() - t < s:
            app.processEvents()
            time.sleep(0.01)
    pump(1.0)
    worst = []

    def check(name):
        pump(0.2)
        m = win.minimumSizeHint()
        ok = m.width() <= LIMIT_W and m.height() <= LIMIT_H
        worst.append(ok)
        print(f'{"ok  " if ok else "FAIL"} {name:<32} minimum {m.width()}×{m.height()}', flush=True)

    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        check(f'tab {win.tabs.tabText(i)}')
    for key, sec in win.side_sections.items():
        sec.set_open(True)
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        check(f'tab {win.tabs.tabText(i)}, all sections open')
    win.tabs.setCurrentIndex(0)
    win.chk_opt_fft.setChecked(True)
    win.btn_mode_avg.click()
    check('OPT101 FFT + Average')
    win.tabs.setCurrentIndex(1)
    for c in (win.chk_audio_noise, win.chk_audio_fft):
        c.setChecked(True)
    check('INMP441 noise + FFT')
    win.tabs.setCurrentIndex(2)
    win.chk_dual_sensors.setChecked(True)
    check('Dual Mode with sensor plots')
    print('all states fit' if all(worst) else 'some states do not fit', flush=True)
    os._exit(0 if all(worst) else 1)


if __name__ == '__main__':
    main()
