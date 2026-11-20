"""
Captura passiva de tráfego CAN, pra rodar em paralelo enquanto o
Consult-III Plus genuíno está conectado ao carro.

A ideia:
1. Você liga o GD101 em modo "monitor" (sniffing passivo, não envia nada
   no barramento) e deixa esse script gravando.
2. Ao mesmo tempo, você usa o Consult-III normalmente no notebook/tablet
   (pode ser outra porta, outro cabo, ou até o mesmo adaptador se ele
   permitir sniff + uso simultâneo — a confirmar na prática).
3. Enquanto navega nas telas do Consult (ex.: entra na tela do CVT, lê
   temperatura, lê DTCs), você aperta ENTER aqui pra marcar um evento
   com timestamp ("abri tela X às 14:32:10.123").
4. Depois, no log, você cruza os IDs CAN que aparecem/mudam perto de cada
   marcação — isso indica quais IDs/DIDs correspondem a quais dados.

Isso não interage com o binário do Consult-III em nenhum momento — só
observa o que passa no fio compartilhado.

Dois modos de transporte suportados aqui:
  - "socketcan" (Linux, se você tiver interface CAN nativa/MCP2515 etc.)
  - "serial-elm" (ELM327/STN-like via serial, usando modo monitor ATMA)

No Windows com o GD101: se o probe (elm_probe.py) confirmar que ele fala
AT commands, use --mode serial-elm --port COM3. Se não, este módulo vai
precisar de uma variante J2534 futuramente (não implementada ainda).
"""
from __future__ import annotations

import csv
import datetime as dt
import threading
import time
from pathlib import Path

import click
import serial


def _timestamp() -> str:
    return dt.datetime.now().isoformat(timespec="microseconds")


class SerialElmSniffer:
    """Sniff passivo via adaptador ELM327/STN-like em modo monitor (ATMA).

    ATMA ("Monitor All") faz o adaptador ficar escutando tudo que passa no
    barramento CAN e devolvendo via serial, sem transmitir nada — ou seja,
    não interfere na sessão real do Consult-III.
    """

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        self.port = port
        self.baudrate = baudrate
        self._ser: serial.Serial | None = None

    def connect(self) -> None:
        self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
        # ATZ reseta o adaptador e demora mais que os outros comandos pra
        # responder — dá um tempo maior só pra ele, senão a resposta dele
        # pode vazar pra dentro do buffer dos comandos seguintes.
        preamble = [
            ("ATZ", 1.5),
            ("ATE0", 0.3),
            ("ATL0", 0.3),
            ("ATS1", 0.3),  # espaços ON — o parser do analyze.py espera ID e bytes separados por espaço
            # Garante que o ID do frame apareça na saída (sem isso o
            # ATMA pode até funcionar, mas a linha vem sem o ID e o
            # regex do analyze.py nunca vai casar).
            ("ATH1", 0.3),
            # ATD1: inclui o byte de DLC (tamanho) na linha de monitor.
            # Fonte: driver can327 do kernel Linux (docs.kernel.org) — sem
            # isso, algumas versões de firmware não deixam claro onde os
            # dados terminam numa linha truncada/BUFFER FULL. Firmwares
            # antigos (<1.3) podem nao suportar.
            ("ATD1", 0.3, False),  # opcional — alguns firmwares nao suportam
            # IMPORTANTE: não usar ATSP0 (protocolo automático) aqui.
            # Auto-detecção de protocolo depende de uma troca real de
            # requisição/resposta OBD pra descobrir baud/formato do ID,
            # o que não existe em modo de monitor passivo (ATMA). Sem
            # protocolo fixado, o adaptador não sabe como decodificar o
            # barramento e o ATMA cai pedindo "?" em vez de entrar no
            # modo de streaming.
            # ATSP6 = ISO 15765-4 CAN (11 bit ID, 500 kbps) — confirmado
            # como o protocolo real do carro pelo teste com o J1979
            # Diagnostic Tool (ECU#1 ID 07E8).
            ("ATSP6", 0.3),
        ]
        for entry in preamble:
            cmd, wait, required = entry if len(entry) == 3 else (*entry, True)
            self._ser.write((cmd + "\r").encode())
            time.sleep(wait)
            reply = self._ser.read(256).decode(errors="replace").strip()
            # DEBUG temporário (2026-10-23): imprime cada comando e a
            # resposta crua recebida, pra diagnosticar por que o ATMA nao
            # esta produzindo nenhuma linha mesmo com o motor ligado.
            print(f"[debug] enviado={cmd!r} recebido={reply!r}")
            if "?" in reply or "ERROR" in reply.upper():
                if required:
                    raise RuntimeError(
                        f"Adaptador respondeu com erro ao comando {cmd!r}: {reply!r}"
                    )
                else:
                    print(
                        f"[aviso] comando opcional {cmd!r} nao suportado "
                        f"por este firmware ({reply!r}) — seguindo sem ele"
                    )
        # Entra em modo monitor (fica streamando frames; só sai com outro
        # comando ou reset do adaptador).
        self._ser.write(b"ATMA\r")
        time.sleep(0.3)
        # DEBUG temporário: mostra o que (se algo) veio logo depois do
        # ATMA, antes de qualquer frame real comecar a aparecer.
        imediato = self._ser.read(256).decode(errors="replace").strip()
        print(f"[debug] logo apos ATMA, leu: {imediato!r}")

    def read_lines(self):
        assert self._ser is not None
        buf = b""
        while True:
            chunk = self._ser.read(256)
            if not chunk:
                continue
            buf += chunk
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                text = line.decode(errors="replace").strip()
                if text:
                    yield text

    def close(self) -> None:
        if self._ser:
            self._ser.write(b"ATPC\r")  # fecha protocolo
            self._ser.close()


def capture(mode: str, port: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()

    def marker_listener() -> None:
        counter = 0
        while not stop_event.is_set():
            try:
                label = input()
            except EOFError:
                break
            counter += 1
            with out_path.open("a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([_timestamp(), "MARKER", counter, label or f"evento_{counter}"])
            click.echo(f"  [marcado evento #{counter}]")

    click.echo(
        "Capturando... aperte ENTER a qualquer momento pra marcar um evento "
        "(ex.: 'abri tela CVT no Consult'). Ctrl+C pra parar.\n"
    )

    with out_path.open("w", newline="") as f:
        csv.writer(f).writerow(["timestamp", "type", "can_id_or_seq", "data_or_label"])

    listener_thread = threading.Thread(target=marker_listener, daemon=True)
    listener_thread.start()

    if mode == "serial-elm":
        sniffer = SerialElmSniffer(port)
        sniffer.connect()
        try:
            with out_path.open("a", newline="") as f:
                writer = csv.writer(f)
                for line in sniffer.read_lines():
                    writer.writerow([_timestamp(), "CAN_RAW", "", line])
                    f.flush()
        except KeyboardInterrupt:
            pass
        finally:
            sniffer.close()
            stop_event.set()

    elif mode == "socketcan":
        import can  # import local: só exige python-can se usar este modo

        bus = can.interface.Bus(channel=port, interface="socketcan")
        try:
            with out_path.open("a", newline="") as f:
                writer = csv.writer(f)
                while True:
                    msg = bus.recv(timeout=1.0)
                    if msg is None:
                        continue
                    writer.writerow(
                        [_timestamp(), "CAN_FRAME", hex(msg.arbitration_id), msg.data.hex()]
                    )
                    f.flush()
        except KeyboardInterrupt:
            pass
        finally:
            bus.shutdown()
            stop_event.set()

    else:
        raise click.ClickException(f"Modo desconhecido: {mode}")

    click.echo(f"\nLog salvo em: {out_path}")


@click.command()
@click.option(
    "--mode",
    type=click.Choice(["serial-elm", "socketcan"]),
    required=True,
    help="serial-elm: GD101 via ELM327/STN (Windows, COM). socketcan: interface CAN nativa (Linux).",
)
@click.option("--port", required=True, help="Ex: COM3 (serial-elm) ou can0 (socketcan)")
@click.option(
    "--out",
    default=None,
    help="Arquivo de saída (.csv). Default: logs/capture_<timestamp>.csv",
)
def main(mode: str, port: str, out: str | None) -> None:
    """Grava tráfego CAN passivamente enquanto o Consult-III roda em paralelo."""
    if out is None:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path("logs") / f"capture_{ts}.csv"
    else:
        out_path = Path(out)
    capture(mode, port, out_path)


if __name__ == "__main__":
    main()
