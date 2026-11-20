"""
Varredura genérica de DIDs (ReadDataByIdentifier, serviço 0x22) contra
uma ECU já endereçada.

Módulo NOVO e isolado — não modifica capture.py, analyze.py,
transport.py nem dids.py. Só reutiliza `make_j2534_client` de
transport.py como está.

Escopo de segurança (deliberado, igual ao resto do projeto):
- Só envia 0x22 ReadDataByIdentifier. NUNCA envia 0x2E
  WriteDataByIdentifier nem qualquer rotina (0x31).
- NUNCA tenta 0x27 SecurityAccess. Pra DIDs protegidos, a ECU
  simplesmente nega o pedido (NegativeResponseException) — isso é só
  registrado como "negado", não é um bypass de nada, nem tenta
  calcular/adivinhar seed/key.
- Isso é reconhecimento passivo e legítimo: a mesma coisa que qualquer
  ferramenta de diagnóstico comercial faz pra descobrir o que uma ECU
  suporta (ver nota sobre jakka351/GenericDiagnosticTool em
  docs/protocol_notes.md).

Uso típico: depois de achar um endereço de ECU candidato (ver
experimental/examples_scan_addresses.py / STANDARD_ADDRESSES em dids.py), rodar esta
varredura contra ele pra ver quais DIDs (genéricos ou de uma faixa
qualquer) ele realmente suporta e retorna dado.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from pathlib import Path

import click


@dataclass
class DidResult:
    did: int
    status: str  # "ok", "negado", "sem_resposta", "erro"
    detail: str


def scan_dids(
    dll_path: str,
    rxid: int,
    txid: int,
    start: int,
    end: int,
    delay: float = 0.1,
    timeout: float = 1.0,
) -> list[DidResult]:
    """Varre start..end (inclusive) de DIDs via ReadDataByIdentifier.

    Só leitura. Nunca escreve, nunca tenta SecurityAccess.
    """
    from udsoncan.exceptions import ConfigError, NegativeResponseException, TimeoutException

    from openscan_obd.transport import make_j2534_client

    results: list[DidResult] = []

    with make_j2534_client(dll_path, rxid=rxid, txid=txid, timeout=timeout) as client:
        for did in range(start, end + 1):
            try:
                response = client.read_data_by_identifier_first(did)
                detail = response.hex() if isinstance(response, bytes) else repr(response)
                results.append(DidResult(did, "ok", detail))
                click.echo(f"  0x{did:04X}: OK -> {detail}")
            except NegativeResponseException as exc:
                nr = exc.response
                results.append(
                    DidResult(did, "negado", f"{nr.code_name} (0x{nr.code:02X})")
                )
            except TimeoutException:
                results.append(DidResult(did, "sem_resposta", ""))
            except ConfigError as exc:
                results.append(DidResult(did, "erro_config", str(exc)))
            except Exception as exc:  # noqa: BLE001 — queremos registrar e seguir pro próximo DID
                results.append(DidResult(did, "erro", repr(exc)))
            time.sleep(delay)

    return results


def run_and_report(
    dll_path: str,
    rxid: int,
    txid: int,
    start: int,
    end: int,
    delay: float,
    timeout: float,
    out_path: Path | None,
) -> None:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if out_path is None:
        out_path = Path("logs") / f"did_scan_{ts}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    click.echo(
        f"Varrendo DIDs 0x{start:04X}..0x{end:04X} em TXID=0x{txid:03X}/RXID=0x{rxid:03X} "
        f"(delay={delay}s entre requisições)...\n"
    )
    results = scan_dids(dll_path, rxid, txid, start, end, delay=delay, timeout=timeout)

    ok = [r for r in results if r.status == "ok"]
    negado = [r for r in results if r.status == "negado"]
    sem_resposta = [r for r in results if r.status == "sem_resposta"]
    erro = [r for r in results if r.status in ("erro", "erro_config")]

    lines = [
        f"Varredura de DIDs — {dt.datetime.now().isoformat()}",
        f"TXID=0x{txid:03X} RXID=0x{rxid:03X} faixa=0x{start:04X}-0x{end:04X}",
        "",
        f"Responderam com dado: {len(ok)}",
        f"Negados (provavelmente exigem SecurityAccess): {len(negado)}",
        f"Sem resposta: {len(sem_resposta)}",
        f"Erro: {len(erro)}",
        "",
        "=== DIDs com dado ===",
    ]
    for r in ok:
        lines.append(f"0x{r.did:04X} [{r.status}]: {r.detail}")
    lines.append("\n=== DIDs negados (candidatos a precisar de SecurityAccess) ===")
    for r in negado:
        lines.append(f"0x{r.did:04X}: {r.detail}")
    lines.append("\n=== Erros ===")
    for r in erro:
        lines.append(f"0x{r.did:04X} [{r.status}]: {r.detail}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    click.echo(f"\n{len(ok)} DID(s) com dado, {len(negado)} negado(s). Relatório completo: {out_path}")


@click.command()
@click.option("--dll", required=True, help="Caminho da DLL J2534")
@click.option("--txid", required=True, help="ID de requisição em hex, ex: 7E1")
@click.option("--rxid", required=True, help="ID de resposta em hex, ex: 7E9")
@click.option("--start", default="F180", show_default=True, help="Início da faixa de DIDs, em hex")
@click.option("--end", default="F1FF", show_default=True, help="Fim da faixa de DIDs, em hex")
@click.option("--delay", default=0.1, show_default=True, help="Segundos entre requisições")
@click.option("--timeout", default=1.0, show_default=True, help="Timeout por requisição (segundos)")
@click.option("--out", default=None, help="Arquivo de relatório (.txt). Default: logs/did_scan_<timestamp>.txt")
def main(dll: str, txid: str, rxid: str, start: str, end: str, delay: float, timeout: float, out: str | None) -> None:
    """Varre uma faixa de DIDs (ReadDataByIdentifier) contra uma ECU já endereçada."""
    run_and_report(
        dll_path=dll,
        rxid=int(rxid, 16),
        txid=int(txid, 16),
        start=int(start, 16),
        end=int(end, 16),
        delay=delay,
        timeout=timeout,
        out_path=Path(out) if out else None,
    )


if __name__ == "__main__":
    main()
