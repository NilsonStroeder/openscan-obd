"""
Tenta ler DTCs (ReadDTCInformation, 0x19) do candidato a TCU/CVT
(0x7E1/0x7E9). Esse serviço não depende de sessão estendida — pode
funcionar mesmo com DiagnosticSessionControl e ReadDataByIdentifier
recusados (como já vimos nesse endereço).

Script novo e isolado, nao sobrescreve nada existente.

Grava em logs/read_dtc_tcu_<timestamp>.txt.
"""
import datetime as dt
import traceback
from pathlib import Path

from openscan_obd.transport import make_j2534_client

DLL_PATH = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"
RXID = 0x7E9
TXID = 0x7E1


def main() -> None:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"read_dtc_tcu_{ts}.txt"

    lines = [f"Leitura de DTCs do candidato a TCU — {dt.datetime.now().isoformat()}",
             f"RXID: {hex(RXID)} TXID: {hex(TXID)}", ""]

    try:
        with make_j2534_client(DLL_PATH, rxid=RXID, txid=TXID) as client:
            response = client.get_dtc_by_status_mask(0xFF)
            msg = f"SUCESSO. Resposta crua: {response!r}"
            print(msg)
            lines.append(msg)
            try:
                dtcs = response.service_data.dtcs
                msg2 = f"DTCs encontrados: {len(dtcs)}"
                print(msg2)
                lines.append(msg2)
                for d in dtcs:
                    lines.append(f"  {d}")
            except Exception as parse_exc:
                lines.append(f"(nao consegui listar os DTCs individualmente: {parse_exc!r} — resposta crua acima)")
    except Exception as exc:
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
