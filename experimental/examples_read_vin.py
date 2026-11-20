"""
Exemplo mínimo: ler o VIN (DID 0xF190, genérico ISO 14229) via J2534.

Ajuste DLL_PATH, RXID e TXID pro seu carro antes de rodar. RXID/TXID da
TCU do CVT ainda não são conhecidos (ver docs/protocol_notes.md) — este
exemplo serve pra validar a conexão J2534 em si, não pra ler dados do CVT
ainda.

Grava o resultado (sucesso OU erro) em logs/vin_test_<timestamp>.txt,
além de imprimir na tela — assim dá pra conferir depois sem precisar
copiar o terminal manualmente.
"""
import datetime as dt
import traceback
from pathlib import Path

from openscan_obd.transport import make_j2534_client

DLL_PATH = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"  # confirmado em 22/10/2026, via Explorador de Arquivos
RXID = 0x7E8  # ID de resposta típico de ECU de motor (exemplo, confirmar)
TXID = 0x7E0  # ID de request típico (exemplo, confirmar)


def main() -> None:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"vin_test_{ts}.txt"

    lines = [f"Teste de conexão J2534 — {dt.datetime.now().isoformat()}",
             f"DLL: {DLL_PATH}", f"RXID: {hex(RXID)} TXID: {hex(TXID)}", ""]

    try:
        with make_j2534_client(DLL_PATH, rxid=RXID, txid=TXID) as client:
            # Tenta abrir sessão de diagnóstico estendida antes do RDBI —
            # alguns módulos só liberam certos DIDs fora da sessão default.
            try:
                import udsoncan
                client.change_session(udsoncan.services.DiagnosticSessionControl.Session.extendedDiagnosticSession)
                lines.append("Sessão estendida aberta com sucesso.")
            except Exception as session_exc:
                lines.append(f"Aviso: não conseguiu abrir sessão estendida: {session_exc!r}")

            response = client.read_data_by_identifier_first(0xF190)
            msg = f"SUCESSO. VIN: {response}"
            print(msg)
            lines.append(msg)
    except Exception as exc:  # noqa: BLE001 — queremos capturar qualquer falha pra log
        msg = f"ERRO: {exc!r}"
        print(msg)
        lines.append(msg)
        lines.append("")
        lines.append(traceback.format_exc())
    finally:
        log_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nLog salvo em: {log_path.resolve()}")


if __name__ == "__main__":
    main()
