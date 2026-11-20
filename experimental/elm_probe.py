"""
Primeiro teste prático: descobrir se o GODIAG GD101 responde como um
adaptador ELM327/STN via serial.

Uso:
    python -m openscan_obd.elm_probe --port COM3

Isso NÃO depende do app Consult-III Plus nem de nenhum software de
terceiros — é apenas uma sondagem da interface serial do próprio hardware.
"""
import time

import click
import serial


AT_COMMANDS = [
    "ATZ",   # reset
    "ATI",   # identifica o adaptador (deve responder algo como "ELM327 v1.5" ou o firmware do GD101)
    "ATE0",  # desliga eco
    "ATL0",  # desliga linefeeds extras
    "ATSP0",  # protocolo automático
]


def probe(port: str, baudrate: int = 115200, timeout: float = 2.0) -> None:
    click.echo(f"Abrindo {port} @ {baudrate} baud...")
    with serial.Serial(port, baudrate, timeout=timeout) as ser:
        for cmd in AT_COMMANDS:
            ser.write((cmd + "\r").encode())
            time.sleep(0.3)
            resp = ser.read(256).decode(errors="replace").strip()
            click.echo(f"  > {cmd}")
            click.echo(f"  < {resp!r}")

    click.echo(
        "\nSe alguma resposta acima contiver algo como 'ELM327', 'STN', "
        "ou um identificador do GD101, o adaptador fala o dialeto AT e dá "
        "para seguir com transporte serial ELM327-like.\n"
        "Se não respondeu nada reconhecível, o GD101 provavelmente só "
        "expõe a API J2534 nativa (via DLL no Windows) e o próximo passo "
        "é testar um wrapper J2534 em Python."
    )


@click.command()
@click.option("--port", required=True, help="Porta serial do GD101, ex: COM3")
@click.option("--baudrate", default=115200, show_default=True)
def main(port: str, baudrate: int) -> None:
    probe(port, baudrate)


if __name__ == "__main__":
    main()
