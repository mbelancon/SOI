# -*- coding: utf-8 -*-
'''Comunicação com o STM32: detecção da porta, processo leitor da serial e SerialLink.

Parte do SOI Controller (antes em soi_controller.py).'''

from soi_const import *  # noqa: F401,F403
from soi_analise import *  # noqa: F401,F403
from soi_dsp import *  # noqa: F401,F403


# ============================================================================
# PURE-END
# ============================================================================


# ----------------------------------------------------------------------------
# Serial em thread
# ----------------------------------------------------------------------------
def keep_system_awake(on):
    """Windows: com on=True impede a suspensão (e a hibernação) por inatividade até ser chamada com False.
    Mantém também a tela ligada: nos PCs com Modern Standby (como o sbook2) o Windows entra em espera quando a tela
    apaga, mesmo com ES_SYSTEM_REQUIRED (visto em 19/11: Kernel-Power 506/507 no meio de varreduras).
    Não impede fechar a tampa nem suspender pelo menu ou pelo botão.
    Vale para a thread que chama (chame sempre da thread da GUI). Devolve True se o Windows aceitou."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        es_continuous, es_system_required, es_display_required = 0x80000000, 0x00000001, 0x00000002
        flags = es_continuous | ((es_system_required | es_display_required) if on else 0)
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
    except Exception:
        return False


def find_arduino_port():
    if os.environ.get('SOI_NO_SERIAL'):           # modo sem janela com --simulado: não abre a placa
        return None, []
    configured_port = os.environ.get('TL_ARDUINO_PORT')
    ports = list(list_ports.comports())
    if configured_port and (any(p.device.upper() == configured_port.upper() for p in ports)
                            or (configured_port.startswith('/dev/') and os.path.exists(configured_port))):
        return configured_port, ports
    # STM32 (VID 0x0483) primeiro, depois as outras placas conhecidas; só portas USB.
    # Nomes genéricos ("serial", "usb serial") não bastam: pegavam Bluetooth e adaptadores USB-serial.
    usb = [p for p in ports if p.vid is not None]
    for vids in ({0x0483}, ARDUINO_VIDS):
        for port in usb:
            if port.vid in vids:
                return port.device, ports
    for port in usb:
        ident = ' '.join(filter(None, [port.description, port.manufacturer])).lower()
        if any(k in ident for k in ('arduino', 'stm32', 'stmicro')):
            return port.device, ports
    if len(usb) == 1:
        return usb[0].device, ports
    return None, ports


def _serial_reader_process(out_q, cmd_q, stop_evt, params):
    '''Processo leitor da porta serial (firmware 2.0.0: ~550 kB/s). Roda fora do processo da interface
    para não depender do GIL: o STM32 guarda só ~41 ms de amostras, e um desenho ou uma conta longa na
    tela bastava para perder dados. Conecta, reconecta, envia F/P e repassa os bytes crus.
    Mensagens para a interface: ('status', conectado, porta, erro) e ('data', bytes).
    Comandos recebidos: ('write', texto) e ('stop',).'''
    import queue as _queue
    f, p = params
    ser = None
    last_try = 0.0

    def send_status(connected, port, error):
        out_q.put(('status', connected, port, error))

    def close():
        nonlocal ser
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        ser = None

    while not stop_evt.is_set():
        # comandos (não bloqueia)
        while True:
            try:
                cmd = cmd_q.get_nowait()
            except _queue.Empty:
                break
            if cmd[0] == 'stop':
                close()
                return
            if cmd[0] == 'write':
                text = cmd[1]
                if text.startswith('F'):
                    f = text[1:].strip()
                elif text.startswith('P'):
                    p = text[1:].strip()
                if ser is not None:
                    try:
                        ser.write(text.encode())
                    except Exception as e:
                        print(f"Conexão com o STM32 perdida ao escrever: {e}")
                        close()
                        send_status(False, None, None)
        if ser is None:
            now = time.monotonic()
            if now - last_try < RECONNECT_INTERVAL:
                stop_evt.wait(0.05)
                continue
            last_try = now
            port, _ = find_arduino_port()
            if port is None:
                continue
            try:
                print(f"Conectando à porta {port}...")
                ser = serial.Serial(port, BAUD_RATE, timeout=0.02)
                try:
                    ser.set_buffer_size(rx_size=1 << 20, tx_size=1 << 14)
                except Exception:
                    pass
                if stop_evt.wait(0.3):
                    close()
                    return
                ser.reset_input_buffer()
                ser.write(f"F{f}\n".encode())
                time.sleep(0.05)
                ser.write(f"P{p}\n".encode())
                print(f"Conectado! Parâmetros enviados: F={f} Hz, PWM={p}%")
                send_status(True, port, None)
            except Exception as e:
                print(f"Erro ao abrir porta serial ({port}): {e}")
                close()
                send_status(False, None, f"{port}: {e}")
            continue
        try:
            data = ser.read(max(1, ser.in_waiting))
        except Exception as e:
            print(f"Conexão com o STM32 perdida ao ler: {e}")
            close()
            send_status(False, None, None)
            continue
        if data:
            out_q.put(('data', data))
    close()


class SerialLink(threading.Thread):
    '''Lê a porta serial continuamente e reconecta sozinha se necessário.
    A GUI só chama take() para pegar os bytes acumulados.'''

    def __init__(self, get_params):
        super().__init__(daemon=True)
        self.get_params = get_params          # () -> (freq_hz, power_pct)
        self.ser = None
        self.connected = False
        self.port = None                      # porta em uso (exibida na barra de status)
        self.last_error = None
        self._parse_buf = bytearray()
        self._opt_buf = bytearray()
        self._audio_chunks = deque()
        self._audio_queued_samples = 0
        self._audio_queue_drops = 0
        self.audio_crc_errors = 0
        self._opt_reset_counters()
        self._lock = threading.Lock()         # protege as filas de saída
        self._wlock = threading.Lock()        # protege escrita/fechamento
        self._stop_evt = threading.Event()
        # Leitura num processo separado (padrão); SOI_SERIAL_THREAD=1 volta à thread da 1.0.0
        self.use_process = os.environ.get('SOI_SERIAL_THREAD', '0') != '1'
        self._proc = None

    def _opt_reset_counters(self):
        self._opt_next_seq = None
        # Logo depois de abrir a porta chega um resto do fluxo antigo (anterior ao reset do buffer):
        # o salto de SEQ desse início não é perda e não é contado.
        self._opt_settle_until = time.monotonic() + 0.5
        self._opt_last_word = b'\x00\x00'
        self.opt_lost_samples = 0
        self.opt_gap_events = 0
        self.opt_crc_errors = 0
        self.opt_received_samples = 0
        # Índice das palavras do fluxo óptico (amostras cruas desde a conexão, perdas preenchidas): o primeiro
        # byte de _opt_buf é a palavra _opt_buf_first; _opt_out_words conta tudo o que já entrou no fluxo.
        self._opt_out_words = 0
        self._opt_buf_first = 0
        # Marcadores de modulação com a posição do fluxo óptico em que chegaram: (amostra I2S, índice óptico)
        self.mod_markers = deque(maxlen=16)

    # -- API para a GUI --
    def take_optical(self):
        '''(bytes crus, índice no fluxo da primeira palavra).'''
        with self._lock:
            optical = bytes(self._opt_buf)
            first = self._opt_buf_first
            self._opt_buf_first += len(optical) // 2
            self._opt_buf.clear()
        return optical, first

    def take_markers(self):
        with self._lock:
            out = list(self.mod_markers)
            self.mod_markers.clear()
        return out

    def take_audio(self):
        with self._lock:
            audio = list(self._audio_chunks)
            self._audio_chunks.clear()
            self._audio_queued_samples = 0
            dropped = self._audio_queue_drops
            self._audio_queue_drops = 0
        return audio, dropped

    @staticmethod
    def _crc16_ccitt(data):
        # CRC-16/CCITT-FALSE em C (o laço em Python saturava a CPU e a thread serial)
        return binascii.crc_hqx(bytes(data), 0xFFFF)

    def _opt_append(self, out, sequence, payload):
        '''Acrescenta as palavras cruas de um pacote óptico. Um salto de SEQ (amostras perdidas na USB ou
        no firmware) é preenchido repetindo a última amostra, para o tempo e o PLL seguirem certos.'''
        n = len(payload) // 2
        end_seq = (sequence + n) & 0xFFFFFFFF
        expected = self._opt_next_seq
        if expected is not None:
            gap = (sequence - expected) & 0xFFFFFFFF
            if gap >= 0x80000000:            # pacote repetido/atrasado: ignora o que já veio
                skip = min(n, (expected - sequence) & 0xFFFFFFFF)
                payload = payload[skip * 2:]
                n -= skip
                if n <= 0:
                    return
            elif gap and time.monotonic() < self._opt_settle_until:
                pass                         # início da conexão: recomeça do pacote atual
            elif gap:
                self.opt_lost_samples += gap
                self.opt_gap_events += 1
                print(f"[{time.strftime('%H:%M:%S')}] Perda USB no OPT101: {gap} amostras "
                      f"({gap / RAW_FS * 1000:.1f} ms); total {self.opt_lost_samples} em {self.opt_gap_events} vezes")
                if gap <= OPT_GAP_FILL_MAX:
                    out.extend(self._opt_last_word * gap)
        out.extend(payload)
        self._opt_last_word = bytes(payload[-2:])
        self._opt_next_seq = end_seq

    def _parse_received(self, data):
        buf = self._parse_buf
        buf.extend(data)
        optical = bytearray()
        audio = []
        markers = []
        pos = 0
        size = len(buf)

        while pos < size:
            if buf[pos] != 0xA5:
                nxt = buf.find(b'\xA5', pos + 1)
                if nxt < 0:
                    pos = size
                    break
                pos = nxt
                continue
            remaining = size - pos
            if remaining < 4:
                tail = bytes(buf[pos:])
                if any(m.startswith(tail) for m in (OPT_PACKET_MAGIC, AUDIO_PACKET_MAGIC, MOD_MARKER_MAGIC)):
                    break
                pos += 1
                continue
            magic = bytes(buf[pos:pos + 4])
            if magic == OPT_PACKET_MAGIC:
                if remaining < OPT_PACKET_HEADER_SIZE:
                    break
                count = int.from_bytes(buf[pos + 8:pos + 10], 'little')
                if not 1 <= count <= OPT_PACKET_MAX_SAMPLES:
                    pos += 1
                    continue
                packet_end = pos + OPT_PACKET_HEADER_SIZE + count * 2 + 2
                if size < packet_end:
                    break
                crc = int.from_bytes(buf[packet_end - 2:packet_end], 'little')
                if self._crc16_ccitt(buf[pos + 4:packet_end - 2]) != crc:
                    self.opt_crc_errors += 1
                    pos += 1
                    continue
                sequence = int.from_bytes(buf[pos + 4:pos + 8], 'little')
                self._opt_append(optical, sequence, buf[pos + OPT_PACKET_HEADER_SIZE:packet_end - 2])
                self.opt_received_samples += count
                pos = packet_end
                continue
            if magic == MOD_MARKER_MAGIC:
                if remaining < MOD_MARKER_SIZE:
                    break
                crc = int.from_bytes(buf[pos + 8:pos + 10], 'little')
                if self._crc16_ccitt(buf[pos + 4:pos + 8]) == crc:
                    k_m = int.from_bytes(buf[pos + 4:pos + 8], 'little')
                    audio.append((k_m, None))
                    # o firmware manda o óptico antes do marcador: a posição atual do fluxo é a do farol (±50 ms)
                    markers.append((k_m, self._opt_out_words + len(optical) // 2))
                    pos += MOD_MARKER_SIZE
                    continue
                pos += 1
                continue
            if magic == AUDIO_PACKET_MAGIC:
                if remaining < AUDIO_PACKET_HEADER_SIZE:
                    break
                sequence = int.from_bytes(buf[pos + 4:pos + 8], 'little')
                count = int.from_bytes(buf[pos + 8:pos + 10], 'little')
                if not 1 <= count <= AUDIO_PACKET_MAX_SAMPLES:
                    pos += 1
                    continue
                payload_start = pos + AUDIO_PACKET_HEADER_SIZE
                packet_end = payload_start + count * 3 + 2
                if size < packet_end:
                    break
                packet_crc = int.from_bytes(buf[packet_end - 2:packet_end], 'little')
                if self._crc16_ccitt(buf[pos + 4:packet_end - 2]) != packet_crc:
                    self.audio_crc_errors += 1
                    pos += 1
                    continue
                packed = np.frombuffer(
                    buf, dtype=np.uint8, count=count * 3, offset=payload_start
                ).reshape(count, 3).astype(np.int32)
                samples = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
                samples = (samples ^ 0x800000) - 0x800000
                audio.append((sequence, samples))
                pos = packet_end
                continue
            pos += 1

        if pos:
            del buf[:pos]
        if len(buf) > 1 << 16:        # lixo sem cabeçalho válido: não deixa crescer
            del buf[:-8]

        if optical or audio:
            with self._lock:
                self._opt_buf.extend(optical)
                self._opt_out_words += len(optical) // 2
                self.mod_markers.extend(markers)
                if len(self._opt_buf) > MAX_RX_BYTES:
                    self._opt_buf_first += (len(self._opt_buf) - MAX_RX_BYTES) // 2
                    del self._opt_buf[:-MAX_RX_BYTES]
                for sequence, samples in audio:      # samples None = marcador de modulação
                    self._audio_chunks.append((sequence, samples))
                    self._audio_queued_samples += 0 if samples is None else len(samples)
                    while self._audio_queued_samples > AUDIO_QUEUE_MAX_SAMPLES:
                        _, discarded = self._audio_chunks.popleft()
                        self._audio_queued_samples -= 0 if discarded is None else len(discarded)
                        self._audio_queue_drops += len(discarded)

    def write(self, text):
        if self._proc is not None:
            self._cmd_q.put(('write', text))
            return
        with self._wlock:
            ser = self.ser
            if ser is None:
                return
            try:
                ser.write(text.encode())
            except Exception as e:
                print(f"Conexão com o Arduino perdida ao escrever: {e}")
                self._close_locked()

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=2.0)
        if self._proc is not None:
            try:
                self._cmd_q.put(('stop',))
                self._mp_stop.set()
                self._proc.join(timeout=2.0)
                if self._proc.is_alive():
                    self._proc.terminate()
            except Exception:
                pass
        with self._wlock:
            self._close_locked()

    def _start_process(self):
        import multiprocessing as mp
        ctx = mp.get_context('spawn')
        self._out_q = ctx.Queue()
        self._cmd_q = ctx.Queue()
        self._mp_stop = ctx.Event()
        self._proc = ctx.Process(target=_serial_reader_process, name='SOI-serial',
                                 args=(self._out_q, self._cmd_q, self._mp_stop, self.get_params()),
                                 daemon=True)
        self._proc.start()

    def _run_process(self):
        import queue as _queue
        while not self._stop_evt.is_set():
            try:
                msg = self._out_q.get(timeout=0.1)
            except _queue.Empty:
                if not self._proc.is_alive():
                    print('Processo de leitura da serial terminou; voltando à leitura em thread.')
                    self._proc = None
                    self.connected = False
                    return False
                continue
            if msg[0] == 'data':
                self._parse_received(msg[1])
            elif msg[0] == 'status':
                _, connected, port, error = msg
                if connected:
                    self._parse_buf.clear()
                    with self._lock:
                        self._opt_buf.clear()
                        self._audio_chunks.clear()
                        self._audio_queued_samples = 0
                        self.audio_crc_errors = 0
                        self._opt_reset_counters()
                    self.port = port
                    self.last_error = None
                    self.connected = True
                    # Uma troca feita na GUI durante a conexão: reenviar o estado atual não faz mal
                    f2, p2 = self.get_params()
                    self.write(f"F{f2}\n")
                    self.write(f"P{p2}\n")
                else:
                    self.connected = False
                    if error:
                        self.last_error = error
        return True

    # -- internos --
    def _close_locked(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connected = False

    def _try_connect(self):
        port, _ = find_arduino_port()
        if port is None:
            return
        new = None
        try:
            print(f"Conectando à porta {port}...")
            new = serial.Serial(port, BAUD_RATE, timeout=0.05)
            try:
                new.set_buffer_size(rx_size=1 << 20, tx_size=1 << 14)
            except Exception:
                pass
            # STM32 USB CDC não reinicia com DTR; espera curta só para estabilizar.
            if self._stop_evt.wait(0.3):
                new.close()
                return
            new.reset_input_buffer()
            f, p = self.get_params()
            new.write(f"F{f}\n".encode())
            time.sleep(0.05)
            new.write(f"P{p}\n".encode())
            self._parse_buf.clear()
            with self._lock:
                self._opt_buf.clear()
                self._audio_chunks.clear()
                self._audio_queued_samples = 0
                self.audio_crc_errors = 0
                self._opt_reset_counters()
            with self._wlock:
                self.ser = new
                self.port = port
                self.connected = True
                self.last_error = None
            print(f"Conectado! Parâmetros enviados: F={f} Hz, PWM={p}%")
            # Uma troca feita na GUI durante a conexão foi descartada por write() (ser ainda era None)
            f2, p2 = self.get_params()
            if f2 != f:
                self.write(f"F{f2}\n")
            if p2 != p:
                self.write(f"P{p2}\n")
        except Exception as e:
            self.last_error = f"{port}: {e}"
            print(f"Erro ao abrir porta serial ({port}): {e}")
            if new is not None:
                try:
                    new.close()
                except Exception:
                    pass

    def run(self):
        if self.use_process:
            try:
                self._start_process()
            except Exception as e:
                print(f'Leitura da serial em processo separado indisponível ({e}); usando thread.')
                self._proc = None
            if self._proc is not None and self._run_process():
                return
        last_try = 0.0
        while not self._stop_evt.is_set():
            ser = self.ser
            if ser is None:
                now = time.monotonic()
                if now - last_try >= RECONNECT_INTERVAL:
                    last_try = now
                    self._try_connect()
                else:
                    self._stop_evt.wait(0.1)
                continue
            try:
                # Bloqueia até chegar ao menos 1 byte (ou 50 ms de timeout).
                data = ser.read(max(1, ser.in_waiting))
            except Exception as e:
                print(f"Conexão com o Arduino perdida ao ler: {e}")
                with self._wlock:
                    self._close_locked()
                continue
            if data:
                self._parse_received(data)


# Exporta tudo (inclusive nomes com _) para os módulos que fazem import *
__all__ = [_n for _n in dir() if not _n.startswith('__')]
