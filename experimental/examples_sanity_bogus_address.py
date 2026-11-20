"""
Teste de sanidade: tenta ler VIN num par TXID/RXID que quase certamente
NAO existe nesse carro (0x7F7 / 0x7FF — fora da faixa OBD-II padrao de
8 ECUs). Se isso também "responder" com algum NegativeResponseException
em vez de dar timeout, é sinal de que o driver/GD101 não está filtrando
por ID corretamente — e as respostas que vimos em 0x7E1 podem na
verdade ser o motor (0x7E8) vazando pra qualquer endereço que a gente
tente.

Grava em logs/sanity_bogus_<timestamp>.txt.
"""
import datetime as dt
from pathlib import Path

from openscan_obd.transport import make_j2534_client

DLL_PATH = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"
RXID = 0x7FF
TXID = 0x7F7


def main() -> None:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"sanity_bogus_{ts}.txt"

    lines = [f"Teste de sanidade (endereco bogus) — {dt.datetime.now().isoformat()}",
             f"RXID: {hex(RXID)} TXID: {hex(TXID)}", ""]

    try:
        with make_j2534_client(DLL_PATH, rxid=RXID, txid=TXID, timeout=1.0) as client:
            response = client.read_data_by_identifier_first(0xF190)
            msg = f"RESPOSTA INESPERADA (deveria dar timeout!): {response!r}"
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc!r}"

    print(msg)
    lines.append(msg)
    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nLog salvo em: {log_path.resolve()}")


if __name__ == "__main__":
    main()
