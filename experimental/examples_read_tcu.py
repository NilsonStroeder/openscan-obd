"""
Teste pontual: abrir sessão de diagnóstico ESTENDIDA no candidato a
TCU/CVT (0x7E1 request / 0x7E9 response — achado via
experimental/examples_scan_addresses.py) e, só então, tentar ReadDataByIdentifier.

Motivo: a varredura de DIDs (scan-dids) mostrou que TODO DID testado
nesse endereço voltou com o mesmo erro "ServiceNotSupported", sem
variar — isso é característico de um módulo que só libera 0x22 depois
de uma sessão != default, não de DID individual sem suporte.

Script separado de examples_read_vin.py (que é sobre o motor, 0x7E0)
de propósito — não sobrescreve nada que já funciona.

Grava resultado em logs/read_tcu_<timestamp>.txt.
"""
import datetime as dt
import traceback
from pathlib import Path

import udsoncan

from openscan_obd.transport import make_j2534_client

DLL_PATH = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"
RXID = 0x7E9  # candidato a TCU/CVT (achado via scan de enderecos padrao)
TXID = 0x7E1


def main() -> None:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"read_tcu_{ts}.txt"

    lines = [f"Teste de sessão no candidato a TCU — {dt.datetime.now().isoformat()}",
             f"DLL: {DLL_PATH}", f"RXID: {hex(RXID)} TXID: {hex(TXID)}", ""]

    try:
        with make_j2534_client(DLL_PATH, rxid=RXID, txid=TXID) as client:
            try:
                client.change_session(udsoncan.services.DiagnosticSessionControl.Session.extendedDiagnosticSession)
                msg = "Sessão estendida aberta com SUCESSO."
                print(msg)
                lines.append(msg)
            except Exception as session_exc:
                msg = f"Sessão estendida FALHOU: {session_exc!r}"
                print(msg)
                lines.append(msg)

            # Tenta alguns DIDs genéricos (não é específico de VIN —
            # TCU pode não ter VIN, mas deve ter pelo menos serial/versão
            # de software se for um módulo UDS completo).
            for did, nome in [(0xF190, "VIN"), (0xF18C, "ECU Serial"), (0xF1A2, "Software Version")]:
                try:
                    response = client.read_data_by_identifier_first(did)
                    msg = f"0x{did:04X} ({nome}): SUCESSO -> {response!r}"
                except Exception as exc:
                    msg = f"0x{did:04X} ({nome}): falhou -> {exc!r}"
                print(msg)
                lines.append(msg)

    except Exception as exc:
        msg = f"ERRO DE CONEXAO: {exc!r}"
        print(msg)
        lines.append(msg)
        lines.append("")
        lines.append(traceback.format_exc())
    finally:
        log_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nLog salvo em: {log_path.resolve()}")


if __name__ == "__main__":
    main()
