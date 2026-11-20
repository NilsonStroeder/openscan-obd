"""
Varredura dos endereços padrão SAE J2012 / ISO 15031-5 (0x7E0-0x7E7 nas
requisições, 0x7E8-0x7EF nas respostas) procurando por ECUs ativas no
barramento — em especial o TCU/CVT em 0x7E1/0x7E9.

Isso NÃO é engenharia reversa de nada proprietário: é só tentar, em cada
par de endereço do esquema padrão de 8 ECUs que qualquer veículo
OBD-II/UDS compatível pode usar, uma leitura UDS genérica e segura
(DID 0xF190 = VIN, que é igual pra qualquer módulo do mesmo carro — não
revela nada novo, só confirma se o módulo respondeu).

Resultado esperado: pelo menos 0x7E0/0x7E8 (motor, já confirmado antes)
deve responder. Se 0x7E1/0x7E9 também responder, é um forte candidato a
ser o TCU da transmissão/CVT — próximo passo aí seria tentar DIDs
genéricos adicionais (dids.py) e, mais importante, deixar uma sessão de
captura (capture.py) rodando enquanto esse endereço é usado, pra depois
cruzar os DIDs reais do CVT.

Ajuste DLL_PATH se necessário. Grava um relatório completo em
logs/scan_addresses_<timestamp>.txt.
"""
import datetime as dt
import traceback
from pathlib import Path

from openscan_obd.dids import STANDARD_ADDRESSES
from openscan_obd.transport import make_j2534_client

DLL_PATH = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"

# Timeout curto pra varredura não demorar muito em endereços sem resposta
# (ECU que não existe ali simplesmente não responde dentro do timeout).
SCAN_TIMEOUT = 1.0


def try_address(rxid: int, txid: int, label: str, lines: list[str]) -> str:
    """Retorna "ok" (leu VIN), "presente" (ECU recusou, mas existe — ver
    NegativeResponseException) ou "ausente" (timeout/sem ECU ali).

    Descoberto em 23/10/2026: a versão original só contava como
    "respondeu" o caso de sucesso total, então um módulo que EXISTE mas
    recusa o pedido (ex.: ServiceNotSupported) caía junto com "não
    existe" — foi assim que quase perdemos o achado do 0x7E1/0x7E9.
    """
    from udsoncan.exceptions import NegativeResponseException

    lines.append(f"\n--- TXID={hex(txid)} / RXID={hex(rxid)} ({label}) ---")
    try:
        with make_j2534_client(DLL_PATH, rxid=rxid, txid=txid, timeout=SCAN_TIMEOUT) as client:
            response = client.read_data_by_identifier_first(0xF190)
            lines.append(f"RESPONDEU COM DADO. VIN lido: {response}")
            return "ok"
    except NegativeResponseException as exc:
        lines.append(f"EXISTE, mas recusou o pedido: {exc.response.code_name} (0x{exc.response.code:02X})")
        return "presente"
    except Exception as exc:  # noqa: BLE001 — timeout ou outro erro de conexao: tratamos como "nao existe"
        lines.append(f"Sem resposta / erro: {exc!r}")
        return "ausente"


def main() -> None:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"scan_addresses_{ts}.txt"

    lines = [f"Varredura de endereços padrão — {dt.datetime.now().isoformat()}", f"DLL: {DLL_PATH}"]
    com_dado: list[tuple[int, int, str]] = []
    presentes: list[tuple[int, int, str]] = []

    for txid, (rxid, label) in STANDARD_ADDRESSES.items():
        status = try_address(rxid, txid, label, lines)
        if status == "ok":
            com_dado.append((txid, rxid, label))
        elif status == "presente":
            presentes.append((txid, rxid, label))

    lines.append("\n=== RESUMO ===")
    if com_dado:
        for txid, rxid, label in com_dado:
            msg = f"RESPONDEU COM DADO: TXID={hex(txid)} / RXID={hex(rxid)} ({label})"
            print(msg)
            lines.append(msg)
    if presentes:
        for txid, rxid, label in presentes:
            msg = f"EXISTE MAS RECUSOU: TXID={hex(txid)} / RXID={hex(rxid)} ({label})"
            print(msg)
            lines.append(msg)
    if not com_dado and not presentes:
        msg = "Nenhum endereço respondeu (nem com dado, nem recusando). Pode ser timeout curto demais."
        print(msg)
        lines.append(msg)

    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nLog completo salvo em: {log_path.resolve()}")


if __name__ == "__main__":
    main()
