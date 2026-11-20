"""Ponto de entrada de linha de comando do scanner.

Comandos atuais:
  scan        Tier A: enumera modulos + DTCs/VIN/dados ao vivo do motor (OBD-II padrao)
  probe-kwp   Tier B: sonda KWP 0x21 nos modulos Nissan (sessao + varredura de LIDs)
  snapshot    Caminho B: foto dos LIDs de um modulo num estado do carro
  compare     Caminho B: compara duas fotos e mostra os LIDs que mudaram
  scan-dids   Varre uma faixa de DIDs (0x22 ReadDataByIdentifier) num endereco
  field-test  Captura LID 0x01 do TCM CVT e analisa na hora (testes de campo)
  j2534-check Abre e fecha o adaptador J2534 sem enviar mensagens (sem carro)

A abordagem de sniffing passivo (ELM327 ATMA) foi movida pra experimental/
por nao funcionar neste GD101 (ver docs/protocol_notes.md).
"""
import json
import time
from pathlib import Path
from typing import Any

import click


class HexIntegerType(click.ParamType):
    name = "HEX"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> int:
        try:
            return int(value, 16)
        except (TypeError, ValueError):
            self.fail(f"{value!r} deve ser hexadecimal", param, ctx)


HEX = HexIntegerType()


class DtcGroupType(click.ParamType):
    """Exatamente 4 dígitos hex (ex.: FF00), para não ser ambíguo como 'FF'."""

    name = "HEX4"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> int:
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if len(text) != 4:
            self.fail(f"{value!r} deve ter exatamente 4 dígitos hex (ex.: FF00)", param, ctx)
        try:
            return int(text, 16)
        except ValueError:
            self.fail(f"{value!r} deve ser hexadecimal", param, ctx)


DTC_GROUP = DtcGroupType()


@click.group()
def main() -> None:
    """Scanner automotivo geral para diagnóstico OBD-II, UDS, KWP e CAN."""


@main.command("scan")
@click.option("--dll", default=None, help="Caminho da DLL J2534 (default: GODIAG padrao)")
def scan(dll: str | None) -> None:
    """Tier A: enumera modulos e le DTCs/VIN/dados ao vivo do motor."""
    from openscan_obd.scanner import DEFAULT_DLL, full_scan
    full_scan(dll or DEFAULT_DLL)


@main.command("probe-kwp")
@click.option("--dll", default=None, help="Caminho da DLL J2534 (default: GODIAG padrao)")
@click.option("--only", default=None, help="Sondar so um modulo (ex: tcm_cvt, abs_vdc)")
@click.option("--start", default="00", show_default=True, help="LID inicial (hex)")
@click.option("--end", default="ff", show_default=True, help="LID final (hex)")
def probe_kwp(dll: str | None, only: str | None, start: str, end: str) -> None:
    """Tier B: sonda KWP 0x21 nos modulos Nissan (sessao + varredura de LIDs)."""
    from openscan_obd.scanner import DEFAULT_DLL, kwp_probe
    kwp_probe(dll or DEFAULT_DLL, only=only, lid_start=int(start, 16), lid_end=int(end, 16))


@main.command("snapshot")
@click.option("--dll", default=None, help="Caminho da DLL J2534 (default: GODIAG padrao)")
@click.option("--only", "module", required=True, help="Modulo (ex: tcm_cvt)")
@click.option("--label", required=True, help="Rotulo do estado (ex: 'frio_parado')")
@click.option("--start", default="00", show_default=True, help="LID inicial (hex)")
@click.option("--end", default="ff", show_default=True, help="LID final (hex)")
def snapshot(dll, module, label, start, end):
    """Caminho B: tira uma foto dos LIDs do modulo num estado do carro."""
    from openscan_obd.scanner import DEFAULT_DLL, snapshot_lids
    snapshot_lids(dll or DEFAULT_DLL, module, label,
                  lid_start=int(start, 16), lid_end=int(end, 16))


@main.command("compare")
@click.argument("snapshot_a")
@click.argument("snapshot_b")
def compare(snapshot_a, snapshot_b):
    """Caminho B: compara duas fotos e mostra os LIDs que mudaram."""
    from pathlib import Path
    from openscan_obd.scanner import compare_snapshots
    compare_snapshots(Path(snapshot_a), Path(snapshot_b))


@main.command("analyze-capture")
@click.argument(
    "capture_file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
)
@click.option("--json", "as_json", is_flag=True, help="Imprime o resumo estruturado em JSON.")
def analyze_capture(capture_file: Path, as_json: bool) -> None:
    """Resume uma captura JSONL sem interpretar os bytes dos payloads."""
    import json

    from openscan_obd.gateway.capture_analysis import (
        format_capture_summary,
        summarize_capture,
    )

    try:
        summary = summarize_capture(capture_file)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        click.echo(format_capture_summary(summary))


@main.command("export-capture-csv")
@click.argument(
    "capture_file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--out",
    "output_path",
    required=True,
    type=click.Path(path_type=Path, dir_okay=False),
    help="Novo arquivo CSV para Excel/LibreOffice.",
)
def export_capture_csv_command(capture_file: Path, output_path: Path) -> None:
    """Exporta a série de frames para CSV sem sobrescrever arquivos."""
    from openscan_obd.gateway.capture_visualization import export_capture_csv

    try:
        count = export_capture_csv(capture_file, output_path)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"CSV criado: {output_path} ({count} frames).")


@main.command("plot-capture")
@click.argument(
    "capture_file",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--out",
    "output_path",
    required=True,
    type=click.Path(path_type=Path, dir_okay=False),
    help="Novo relatório HTML offline.",
)
def plot_capture_command(capture_file: Path, output_path: Path) -> None:
    """Gera gráficos 2D offline para os sinais disponíveis numa captura."""
    from openscan_obd.gateway.capture_visualization import generate_capture_report

    try:
        count = generate_capture_report(capture_file, output_path)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Relatório criado: {output_path} ({count} frames).")


@main.command("compare-captures")
@click.argument(
    "first_capture",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
)
@click.argument(
    "second_capture",
    type=click.Path(path_type=Path, exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--out",
    "output_path",
    required=True,
    type=click.Path(path_type=Path, dir_okay=False),
    help="Novo relatório HTML offline.",
)
def compare_captures_command(
    first_capture: Path,
    second_capture: Path,
    output_path: Path,
) -> None:
    """Compara duas capturas offline por tempo decorrido e sinais comuns."""
    from openscan_obd.gateway.capture_visualization import (
        generate_capture_comparison_report,
    )

    try:
        first_count, second_count = generate_capture_comparison_report(
            first_capture, second_capture, output_path,
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Comparação criada: {output_path} "
        f"({first_count} frames na primeira; {second_count} na segunda)."
    )


@main.command("probe-dtc")
@click.option("--dll", required=True, help="Caminho da DLL J2534.")
@click.option("--allow-a3", is_flag=True,
              help="Também testa o SID A3 (semântica desconhecida; só com carro parado em P).")
@click.option("--confirm-parked", is_flag=True,
              help="Confirma que o carro está parado em P com o freio de mão puxado.")
@click.option("--out-dir", default="logs", show_default=True, help="Pasta do resultado (JSON).")
def probe_dtc(dll: str, allow_a3: bool, confirm_parked: bool, out_dir: str) -> None:
    """Hipóteses H1-H3 (e H5 com --allow-a3) de leitura de DTC do TCM. Só leitura; resultado cru."""
    from openscan_obd.gateway.j2534 import J2534Device, J2534Error
    from openscan_obd.gateway.probe_dtc import run_probe
    from openscan_obd.gateway.readonly_guard import ReadOnlyDevice
    from openscan_obd.gateway.scan import save_scan

    if allow_a3 and not confirm_parked:
        confirm_parked = click.confirm(
            "O carro está parado em P com o freio de mão puxado?", default=False)
    device = ReadOnlyDevice(J2534Device(dll, txid=0x7E0, rxid=0x7E8),
                            extra_allowed={0xA3} if allow_a3 else None)
    try:
        device.open()
        result = run_probe(device, allow_a3=allow_a3, confirm_parked=confirm_parked,
                           progress=lambda step: click.echo(f"Testando {step}…"))
    except (J2534Error, TimeoutError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        device.close()
    path = save_scan(result, Path(out_dir), prefix="probe_dtc")
    click.echo(f"Resultado cru salvo em {path}")
    click.echo("Nada foi interpretado nem validado no veículo (hipóteses).")


@main.command("ler-erros")
@click.option("--dll", required=True, help="Caminho da DLL J2534.")
@click.option("--out-dir", default="logs", show_default=True, help="Pasta do resultado (JSON e TXT).")
@click.option("--label", default="", help="Rótulo no nome do arquivo (ex.: antes, depois).")
def ler_erros_cmd(dll: str, out_dir: str, label: str) -> None:
    """Lê os códigos de falha de motor, câmbio e demais módulos. Só leitura: não apaga nada."""
    import json
    import time

    from openscan_obd.gateway.j2534 import J2534Device, J2534Error
    from openscan_obd.gateway.ler_erros import formatar, ler_erros
    from openscan_obd.gateway.readonly_guard import ReadOnlyDevice

    device = ReadOnlyDevice(J2534Device(dll, txid=0x7E0, rxid=0x7E8))
    try:
        device.open()
        result = ler_erros(device, progress=lambda m: click.echo(f"Lendo {m}…"))
    except (J2534Error, TimeoutError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        device.close()
    texto = formatar(result)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if label:
        stamp = f"{label}_{stamp}"
    (out / f"erros_{stamp}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / f"erros_{stamp}.txt").write_text(texto, encoding="utf-8")
    click.echo("")
    click.echo(texto)
    click.echo(f"\nSalvo em {out / f'erros_{stamp}.txt'}")


@main.command("scan-all")
@click.option("--dll", required=True, help="Caminho da DLL J2534.")
@click.option("--start", default="700", show_default=True, metavar="HEX", help="Primeiro ID de requisição.")
@click.option("--end", default="7FF", show_default=True, metavar="HEX", help="Último ID de requisição.")
@click.option("--offsets", default="20", show_default=True,
              help="Deslocamentos do ID de resposta, em hex, separados por vírgula (ex.: 20,10,08). "
                   "Cada um é uma troca de filtro no adaptador; o GD101 não aguenta muitas.")
@click.option("--out-dir", default="logs", show_default=True, help="Pasta do resultado (JSON).")
def scan_all(dll: str, start: str, end: str, offsets: str, out_dir: str) -> None:
    """Varredura longa e só de leitura de todos os IDs CAN; guarda tudo cru. Ctrl+C salva o parcial."""
    from openscan_obd.gateway.j2534 import J2534Device, J2534Error
    from openscan_obd.gateway.readonly_guard import ReadOnlyDevice
    from openscan_obd.gateway.scan_all import run_scan_all

    first, last = int(start, 16), int(end, 16)
    try:
        rx_offsets = tuple(int(o, 16) for o in offsets.split(",") if o.strip())
    except ValueError as exc:
        raise click.ClickException(f"--offsets inválido: {offsets!r}") from exc
    if not rx_offsets:
        raise click.ClickException("--offsets precisa de pelo menos um valor")
    if not 0x000 <= first <= last <= 0x7FF:
        raise click.ClickException("faixa inválida: use IDs de 11 bits (000 a 7FF) com início <= fim")
    device = ReadOnlyDevice(J2534Device(dll, txid=0x7E0, rxid=0x7E8))
    done = {"n": 0}
    path = Path(out_dir) / f"scan_all_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    def progress(tx: int, total: int) -> None:
        done["n"] += 1
        if done["n"] % 8 == 1 or done["n"] == total:
            click.echo(f"Varrendo 0x{tx:03X} ({done['n']}/{total})…")

    def save_partial(partial: dict) -> None:
        # regrava a cada ID: se o adaptador travar e a janela for fechada, o que já foi achado fica no arquivo
        path.write_text(json.dumps(partial, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        device.open()
        result = run_scan_all(device, tx_range=(first, last), rx_offsets=rx_offsets,
                              progress=progress, on_update=save_partial)
    except (J2534Error, TimeoutError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        device.close()
    for f in result["found"]:
        click.echo(f"  RESPONDEU tx={f['tx']} rx={f['rx']} ({f['offset']})")
    click.echo(f"{result['summary']['found']} módulo(s). Resultado cru salvo em {path}")
    if result["summary"]["interrupted"]:
        click.echo("Interrompido: resultado parcial.")
    if result["summary"]["aborted"]:
        click.echo(f"Adaptador parou de responder ({result['summary']['abort_reason']}): resultado parcial.")


@main.command("read-kwp-dtcs")
@click.option("--dll", required=True, help="Caminho da DLL J2534.")
@click.option("--txid", required=True, metavar="HEX", type=HEX,
              help="ID CAN de transmissão, em hexadecimal.")
@click.option("--rxid", required=True, metavar="HEX", type=HEX,
              help="ID CAN de receção, em hexadecimal.")
@click.option("--session", "session_type", required=True, metavar="HEX", type=HEX,
              help="Subtipo de sessão KWP, em hexadecimal.")
@click.option("--status-mask", required=True, metavar="HEX", type=HEX,
              help="Status mask do serviço 0x18, em hexadecimal.")
@click.option("--group", default=None, metavar="HEX4", type=DTC_GROUP,
              help="groupOfDTC opcional (4 dígitos hex, ex.: FF00); envia "
                   "18 <status> <grupo>. Sem ele envia só 18 <status>. "
                   "Formato aceito pelo veículo: não validado.")
@click.option("--timeout-ms", default=1000, show_default=True,
              type=click.IntRange(min=1, max=60000), help="Timeout da requisição.")
@click.option("--json", "as_json", is_flag=True, help="Imprime o resultado em JSON.")
def read_kwp_dtcs(
    dll: str,
    txid: int,
    rxid: int,
    session_type: int,
    status_mask: int,
    group: int | None,
    timeout_ms: int,
    as_json: bool,
) -> None:
    """Lê DTCs KWP uma vez, em conexão separada do dashboard/poller."""
    import json

    from openscan_obd.gateway.j2534 import J2534Device, J2534Error
    from openscan_obd.gateway.kwp_dtc import build_read_dtcs_request, read_dtcs_raw
    from openscan_obd.gateway.kwp_session import KWPSession, KWPSessionError

    if txid > 0x7FF or rxid > 0x7FF:
        raise click.BadParameter("txid e rxid devem ser IDs CAN de 11 bits")
    if session_type > 0xFF or status_mask > 0xFF:
        raise click.BadParameter("session e status-mask devem caber em um byte")
    try:
        request = build_read_dtcs_request(status_mask, group)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc

    device = J2534Device(dll, txid=txid, rxid=rxid)
    session = KWPSession(device, session_type=session_type, timeout_ms=timeout_ms)
    try:
        device.open()
        session.start()
        result = read_dtcs_raw(session, status_mask, timeout_ms=timeout_ms, group=group)
    except (J2534Error, KWPSessionError, TimeoutError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        session.stop()
        device.close()

    report = {
        "operation": "read_kwp_dtcs",
        "read_only": True,
        "txid": f"0x{txid:03X}",
        "rxid": f"0x{rxid:03X}",
        "session": f"0x{session_type:02X}",
        "request": request.hex(" ").upper(),
        "request_format": "status_and_group" if group is not None else "status_only",
        "status_mask": f"0x{status_mask:02X}",
        "group": f"0x{group:04X}" if group is not None else None,
        "positive": result.positive,
        "nrc": f"0x{result.nrc:02X}" if result.nrc is not None else None,
        "raw_response": result.raw_response.hex(),
        "response_data_raw": result.response_data.hex(),
        "decoded_dtcs": None,
        "vehicle_validation": "not_validated",
    }
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Pedido KWP 0x18: {report['request']}")
        click.echo(f"Resposta KWP 0x18: {report['raw_response'] or '(vazia)'}")
        click.echo("DTCs não decodificados; payload preservado como bytes crus.")
        if result.nrc is not None:
            click.echo(f"NRC: 0x{result.nrc:02X}")
        click.echo("Validação no veículo: pendente.")


@main.command("j2534-check")
@click.option("--dll", default=None, help="Caminho da DLL J2534 (default: GODIAG padrao)")
def j2534_check(dll: str | None) -> None:
    """Testa o adaptador J2534 sem carro: abre e fecha, sem enviar mensagens.

    Faz PassThruOpen + PassThruConnect (ISO15765) + filtro e depois
    PassThruDisconnect + PassThruClose. Nenhuma mensagem vai para o barramento.
    """
    import platform
    import struct

    from openscan_obd.gateway.j2534 import J2534Device, J2534Error
    from openscan_obd.scanner import DEFAULT_DLL

    dll_path = dll or DEFAULT_DLL
    bits = struct.calcsize("P") * 8
    click.echo(f"Python {platform.python_version()} ({bits} bits)")
    click.echo(f"DLL: {dll_path}")
    click.echo("A DLL J2534 precisa ter a mesma arquitetura do Python (32 ou 64 bits).")
    if bits != 32 and "PT32" in dll_path.upper():
        click.echo(
            "AVISO: esta DLL parece ser de 32 bits (PT32), mas o Python é de "
            f"{bits} bits. Use o ambiente 32 bits: .\\.venv\\Scripts\\python.exe"
        )

    if not Path(dll_path).is_file():
        click.echo(f"FALHA: DLL não encontrada: {dll_path}")
        raise SystemExit(1)

    device = J2534Device(dll_path)
    try:
        device.open()
        click.echo("PassThruOpen + PassThruConnect (ISO15765) + filtro: ok")
        try:
            version = device.read_version()
        except J2534Error as exc:
            click.echo(f"Versão: não lida ({exc})")
        else:
            if version is None:
                click.echo("Versão: DLL não oferece PassThruReadVersion")
            else:
                click.echo(
                    f"Versão: firmware={version['firmware'] or '?'} "
                    f"dll={version['dll'] or '?'} api={version['api'] or '?'}"
                )
    except J2534Error as exc:
        click.echo(f"FALHA: {exc}")
        raise SystemExit(1)
    finally:
        device.close()
    click.echo("OK: adaptador abriu e fechou. Nenhuma mensagem foi enviada ao carro.")
    click.echo("Validação no veículo: não feita por este comando.")


@main.command("scan-dids")
@click.option("--dll", required=True, help="Caminho da DLL J2534")
@click.option("--txid", required=True, help="ID de requisicao em hex, ex: 7E1")
@click.option("--rxid", required=True, help="ID de resposta em hex, ex: 7E9")
@click.option("--start", default="F180", show_default=True, help="Inicio da faixa de DIDs, em hex")
@click.option("--end", default="F1FF", show_default=True, help="Fim da faixa de DIDs, em hex")
@click.option("--delay", default=0.1, show_default=True, help="Segundos entre requisicoes")
@click.option("--timeout", default=1.0, show_default=True, help="Timeout por requisicao (segundos)")
@click.option("--out", default=None, help="Arquivo de relatorio (.txt)")
def scan_dids(dll: str, txid: str, rxid: str, start: str, end: str, delay: float, timeout: float, out: str) -> None:
    """Varre uma faixa de DIDs (0x22 ReadDataByIdentifier) contra um endereco."""
    from pathlib import Path
    from openscan_obd.did_scan import run_and_report

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


@main.command("scan-22")
@click.option("--dll", required=True, help="Caminho da DLL J2534.")
@click.option("--txid", default="7E1", show_default=True, help="ID de requisição em hex (7E1 = TCM, 7E0 = ECM).")
@click.option("--rxid", default="7E9", show_default=True, help="ID de resposta em hex.")
@click.option("--start", default="1E00", show_default=True, metavar="HEX", help="Primeiro DID.")
@click.option("--end", default="1EFF", show_default=True, metavar="HEX", help="Último DID (FFFF = faixa toda).")
@click.option("--no-session", is_flag=True, help="Não abre a sessão 10 C0 antes.")
@click.option("--out-dir", default="logs", show_default=True, help="Pasta do resultado (JSON).")
def scan_22(dll: str, txid: str, rxid: str, start: str, end: str, no_session: bool, out_dir: str) -> None:
    """Varredura só de leitura do serviço 0x22 (DIDs de 2 bytes); guarda tudo cru."""
    from openscan_obd.gateway.j2534 import J2534Device, J2534Error
    from openscan_obd.gateway.readonly_guard import ReadOnlyDevice
    from openscan_obd.gateway.scan_22 import run_scan_22

    tx, rx, first, last = int(txid, 16), int(rxid, 16), int(start, 16), int(end, 16)
    if not 0 <= first <= last <= 0xFFFF:
        raise click.ClickException("faixa inválida: DIDs de 0000 a FFFF com início <= fim")
    device = ReadOnlyDevice(J2534Device(dll, txid=0x7E0, rxid=0x7E8), extra_allowed={0x22})
    path = Path(out_dir) / f"scan_22_{txid.upper()}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = {"n": 0}

    def progress(did: int, total: int) -> None:
        seen["n"] += 1
        if seen["n"] % 256 == 1:
            click.echo(f"DID 0x{did:04X} ({seen['n']}/{total})…")

    def save_partial(partial: dict) -> None:
        path.write_text(json.dumps(partial, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        device.open()
        result = run_scan_22(device, tx, rx, did_range=(first, last), use_session=not no_session,
                             progress=progress, on_update=save_partial)
    except (J2534Error, TimeoutError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        device.close()
    for f in result["found"]:
        click.echo(f"  DID {f['did']} = {f['data']}")
    for code, dids in result["nrc_dids"].items():
        click.echo(f"  NRC {code}: {len(dids)} DID(s) (ex.: {', '.join(dids[:5])})")
    click.echo(f"Veredito: {result['summary']['verdict']}. Resultado cru salvo em {path}")


def _profile_modules(profile: str | None) -> dict:
    from openscan_obd.profiles import DEFAULT_PROFILE_ID, UnknownProfile, get_profile
    try:
        return get_profile(profile or DEFAULT_PROFILE_ID).modules
    except UnknownProfile as exc:
        raise click.ClickException(str(exc)) from exc


def _guarded(dll: str):
    from openscan_obd.gateway.j2534 import J2534Device
    from openscan_obd.gateway.readonly_guard import ReadOnlyDevice
    return ReadOnlyDevice(J2534Device(dll, txid=0x7E0, rxid=0x7E8), extra_allowed={0x22})   # 22 = só leitura


@main.command("collect-discover")
@click.option("--dll", required=True, help="Caminho da DLL J2534.")
@click.option("--profile", default=None, metavar="ID", help="Perfil do veículo (padrão: generic-obd2).")
@click.option("--dids", default="todos", show_default=True,
              help='Faixas de DID do serviço 22 (hex, ex.: "F100-F1FF,1E00"); "todos" = 0000-FFFF '
                   "(~45 min por módulo que aceitar); \"nenhum\" pula.")
@click.option("--out-dir", default="logs", show_default=True, help="Pasta do resultado (JSON).")
def collect_discover(dll: str, profile: str | None, dids: str, out_dir: str) -> None:
    """Carro parado: descobre PIDs (declarados ou não), modos 06/09, DTCs e LIDs de cada módulo. Só leitura."""
    from openscan_obd.gateway.collect import parse_did_ranges, run_discovery
    from openscan_obd.gateway.j2534 import J2534Error

    modules = _profile_modules(profile)
    device = _guarded(dll)
    path = Path(out_dir) / f"coleta_descoberta_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    def save(partial: dict) -> None:
        path.write_text(json.dumps(partial, indent=2, ensure_ascii=False), encoding="utf-8")

    def progress(name: str, done: int, total: int) -> None:
        if done % 64 == 1:
            click.echo(f"{name}: LID {done - 1:02X}/{total - 1:02X}…")

    try:
        device.open()
        ranges = None if dids.strip().lower() in ("nenhum", "none") else parse_did_ranges(dids)
        result = run_discovery(device, modules, did_ranges=ranges, progress=progress, on_update=save)
    except (J2534Error, TimeoutError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        device.close()
    obd = result["obd"]
    click.echo(f"PIDs declarados: {len(obd.get('declared_pids', []))}; "
               f"não declarados que responderam: {sorted(obd.get('undeclared_responders', {}))}")
    for name, e in result["kwp"].items():
        click.echo(f"  {name}: {e['status']}, {len(e.get('lids', {}))} LID(s)")
    click.echo(f"Descoberta salva em {path}")


class _Guia:
    """Roda os estímulos numa thread e escreve as marcas no mesmo arquivo da gravação (com trava)."""

    def __init__(self, nome: str | None, write) -> None:
        import threading

        from openscan_obd.gateway import estimulos as est

        self.passos = {"parado": est.PARADO, "andando": est.ANDANDO, "puxada": est.PUXADA}[nome] if nome else None
        self.duracao_s = (est.duracao_total(self.passos) + 15) if self.passos else None
        self._lock = threading.Lock()
        self._write = write
        self._parar = threading.Event()
        self._th = (threading.Thread(target=est.run_estimulos, args=(self.passos, self.write),
                                     kwargs={"parar": self._parar}, daemon=True) if self.passos else None)

    def write(self, rec: dict) -> None:
        with self._lock:
            self._write(rec)

    def iniciar(self) -> None:
        if self._th:
            self._th.start()

    def encerrar(self) -> None:
        if self._th:
            self._parar.set()
            self._th.join(timeout=2)


@main.command("analisar-log")
@click.option("--arquivo", "-a", "arquivos", multiple=True, type=click.Path(exists=True, dir_okay=False),
              help="coleta_*.jsonl a analisar (repita para vários). Padrão: todos os coleta_2*.jsonl da pasta.")
@click.option("--erros", "erros", multiple=True, type=click.Path(exists=True, dir_okay=False),
              help="erros_*.json (do ler-erros) para resumir. Padrão: todos os erros_*.json da pasta.")
@click.option("--out-dir", default="logs", show_default=True, help="Pasta dos logs e da saída analise_*.md.")
def analisar_log(arquivos: tuple[str, ...], erros: tuple[str, ...], out_dir: str) -> None:
    """Relatório de calibração (combustível, avanço, MAF, malha, puxadas) a partir das coletas. Offline."""
    from openscan_obd import analise_tuning as at

    base = Path(out_dir)
    paths = [Path(a) for a in arquivos] or sorted(base.glob("coleta_2*.jsonl"))
    if not paths:
        raise click.ClickException(f"nenhum coleta_*.jsonl em {base} (rode o roteiro de coleta antes)")
    texto = at.relatorio_completo(paths, [Path(e) for e in erros] or sorted(base.glob("erros_*.json")))
    out = base / f"analise_{time.strftime('%Y%m%d_%H%M%S')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(texto, encoding="utf-8")
    click.echo(texto)
    click.echo(f"Salvo em {out}")


@main.command("collect")
@click.option("--dll", required=True, help="Caminho da DLL J2534.")
@click.option("--plan", "plan_path", default=None, help="JSON da descoberta (padrão: o mais recente em --out-dir).")
@click.option("--minutes", default=15.0, show_default=True, help="Duração da gravação.")
@click.option("--fuel", default=None, help="Combustível no tanque (ex.: etanol, gasolina, flex) para a análise.")
@click.option("--note", default=None, help="Observação livre guardada no cabeçalho (ex.: trajeto).")
@click.option("--estimulos", type=click.Choice(["parado", "andando", "puxada"]), default=None,
              help="Roteiro de estímulos com horário (parado, andando ou puxada); define a duração sozinho.")
@click.option("--so-obd", is_flag=True, help="Só OBD (sem LIDs/DIDs): ciclos bem mais curtos, para puxadas.")
@click.option("--pids", default=None, help="Só estes PIDs OBD, em hex separados por vírgula (ex.: 0C,0D,11,10).")
@click.option("--out-dir", default="logs", show_default=True, help="Pasta de saída.")
def collect(dll: str, plan_path: str | None, minutes: float, fuel: str | None, note: str | None,
            estimulos: str | None, so_obd: bool, pids: str | None, out_dir: str) -> None:
    """Dirigindo: grava em ciclos tudo o que a descoberta achou, em JSONL cru. Só leitura. Ctrl+C encerra."""
    from openscan_obd.gateway.collect import plan_from_discovery, plano_rapido, run_record
    from openscan_obd.gateway.j2534 import J2534Error

    base = Path(out_dir)
    if plan_path:
        src = Path(plan_path)
    else:
        found = sorted(base.glob("coleta_descoberta_*.json"))
        if not found:
            raise click.ClickException("sem descoberta: rode `collect-discover` antes (ou passe --plan)")
        src = found[-1]
    plan = plano_rapido(plan_from_discovery(json.loads(src.read_text(encoding="utf-8"))), pids=pids, so_obd=so_obd)
    device = _guarded(dll)
    out = base / f"coleta_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in {"fuel": fuel, "note": note, "plan_file": src.name}.items() if v}
    click.echo(f"Plano: {len(plan['obd_pids'])} PIDs, "
               f"{ {n: len(v['lids']) for n, v in plan['kwp'].items()} } LIDs. Gravando {minutes:g} min em {out}")
    last = {"t": 0.0}

    def tick(cycles: int, elapsed: float, records: int) -> None:
        if elapsed - last["t"] >= 30:
            last["t"] = elapsed
            click.echo(f"  {elapsed / 60:.1f} min, {cycles} ciclos, {records} leituras")

    try:
        device.open()
        with out.open("w", encoding="utf-8") as fh:
            def write(rec: dict) -> None:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
            guia = _Guia(estimulos, write)
            if guia.duracao_s:
                minutes = guia.duracao_s / 60
                meta["estimulos"] = estimulos
                click.echo(f"Roteiro de estímulos '{estimulos}': {minutes:.1f} min. Siga as instruções da tela.")
            guia.iniciar()
            try:
                from openscan_obd.gateway.estimulos import cadencia_total
                summary = run_record(device, plan, minutes * 60, guia.write, meta=meta, on_cycle=tick,
                                     every=cadencia_total(plan) if (guia.passos and not so_obd) else None)
            finally:
                guia.encerrar()
    except (J2534Error, TimeoutError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        device.close()
    click.echo(f"{summary['cycles']} ciclos, {summary['records']} leituras, {summary['timeouts']} timeouts. {out}")


@main.command("sniff")
@click.option("--dll", required=True, help="Caminho da DLL J2534.")
@click.option("--minutes", default=5.0, show_default=True, help="Duração da escuta.")
@click.option("--fuel", default=None, help="Combustível no tanque.")
@click.option("--note", default=None, help="Observação livre guardada no cabeçalho.")
@click.option("--estimulos", type=click.Choice(["parado", "andando", "puxada"]), default=None,
              help="Roteiro de estímulos com horário (parado ou andando); define a duração sozinho.")
@click.option("--out-dir", default="logs", show_default=True, help="Pasta de saída.")
def sniff(dll: str, minutes: float, fuel: str | None, note: str | None, estimulos: str | None,
          out_dir: str) -> None:
    """Escuta passiva do CAN: grava todo quadro que passa, sem enviar nada. Rode separado da coleta."""
    from openscan_obd.gateway.j2534 import J2534Error
    from openscan_obd.gateway.sniff import CanSniffer, run_sniff

    out = Path(out_dir) / f"sniff_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in {"fuel": fuel, "note": note}.items() if v}
    sniffer = CanSniffer(dll)
    click.echo(f"Escutando o CAN por {minutes:g} min (nada é enviado). Saída: {out}")
    try:
        sniffer.open()
        with out.open("w", encoding="utf-8") as fh:
            def write(rec: dict) -> None:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            guia = _Guia(estimulos, write)
            if guia.duracao_s:
                minutes = guia.duracao_s / 60
                meta["estimulos"] = estimulos
                click.echo(f"Roteiro de estímulos '{estimulos}': {minutes:.1f} min. Siga as instruções da tela.")
            guia.iniciar()
            try:
                summary = run_sniff(sniffer, minutes * 60, guia.write, meta=meta)
            finally:
                guia.encerrar()
    except (J2534Error, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        sniffer.close()
    click.echo(f"{summary['frames']} quadros, {len(summary['ids'])} IDs distintos. {out}")


@main.command("discover")
@click.option("--dll", default=None, help="Caminho da DLL J2534 (default: GODIAG padrao)")
@click.option("--start", default="700", show_default=True, help="ID de requisicao inicial (hex)")
@click.option("--end", default="7ff", show_default=True, help="ID de requisicao final (hex)")
def discover(dll, start, end):
    """Varre 0x700-0x7FF achando TODO modulo que responde (sem lista chutada)."""
    from openscan_obd.scanner import DEFAULT_DLL, discover_modules
    discover_modules(dll or DEFAULT_DLL, tx_start=int(start, 16), tx_end=int(end, 16))


@main.command("field-test")
@click.option("--dll", default=None, help="Caminho da DLL J2534 (default: GODIAG padrao)")
@click.option(
    "--scenario", required=True,
    type=click.Choice([
        "frio",
        "P", "N", "D", "R",
        "rpm1000", "rpm2000", "rpm3000",
        "accel25", "accel50", "accel75", "accel100",
        "cruising60", "cruising80", "cruising100",
        "arranque", "tcc",
    ], case_sensitive=True),
    help="Cenário de análise — define quais bytes interpretar e como",
)
@click.option("--label", default="", help="Rótulo livre para identificar a coleta (ex: 'estrada_sp150')")
@click.option(
    "--hex", "payload_hex", default=None,
    help="Payload LID 0x01 em hex (69 bytes separados por espaço). "
         "Se omitido, captura ao vivo via J2534.",
)
def field_test(dll, scenario, label, payload_hex):
    """Captura e analisa o LID 0x01 do TCM CVT em tempo real.

    \b
    Modo ao vivo (requer GD101 conectado):
        python -m openscan_obd field-test --scenario cruising80

    Modo offline (payload copiado do log):
        python -m openscan_obd field-test --scenario D \\
            --hex "01 00 00 01 00 01 16 3A ..."

    \b
    Cenários disponíveis:
        frio         Antes de ligar — ATF TEMP lookup table
        P/N/D/R      Posição do seletor — RANGE SW, GEAR RATIO
        rpm1000/2000/3000  RPM fixo em P — escala PRI SPEED
        accel25/50/75/100  Acelerador em % — ACC PEDAL POS
        cruising60/80/100  Velocidade constante em D — GEAR RATIO
        arranque     Arrancada suave — SLIP REV saindo de 0xFE
        tcc          Lock-up engajado — SLIP REV ≈ 0
    """
    from openscan_obd.field_tests import capture_and_analyze, run_analysis

    if payload_hex:
        # Modo offline: parse do hex fornecido
        payload = bytes(int(x, 16) for x in payload_hex.split())
        run_analysis(scenario, payload, label)
    else:
        # Modo ao vivo: captura real do carro
        from openscan_obd.scanner import DEFAULT_DLL
        capture_and_analyze(scenario, dll or DEFAULT_DLL, label)


@main.command("dashboard")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Endereço de escuta. Use 0.0.0.0 para acesso na rede local.")
@click.option("--port", default=8000, show_default=True, type=int, help="Porta HTTP.")
@click.option("--mock/--hardware", default=True, show_default=True,
              help="Usa fixture offline; hardware J2534 exige escolha explícita.")
@click.option("--dll", default=None, help="Caminho da DLL J2534 no modo --hardware.")
@click.option("--elm", "elm_port", default=None,
              help="Usa um ELM327 nesta porta (ex.: COM5 ou socket://192.168.0.10:35000) "
                   "em vez do J2534. Implica --hardware. Não validado em adaptador real.")
@click.option(
    "--capture",
    type=click.Path(path_type=Path, dir_okay=False, writable=True),
    default=None,
    help="Grava frames e erros crus em JSONL; o arquivo não pode existir.",
)
@click.option("--vehicle", default="not_recorded", show_default=True,
              help="Identificação do veículo incluída na captura.")
@click.option("--ecu", default="ECM configured; not discovered", show_default=True,
              help="Identificação da ECU incluída na captura.")
@click.option("--adapter", default="not_recorded", show_default=True,
              help="Identificação do adaptador/driver incluída na captura.")
@click.option("--profile", "profile", default=None, metavar="ID",
              help="Perfil de veículo (veja `profiles`). Padrão: generic-obd2, só padrões públicos.")
def dashboard(
    host: str,
    port: int,
    mock: bool,
    dll: str | None,
    capture: Path | None,
    vehicle: str,
    ecu: str,
    adapter: str,
    elm_port: str | None,
    profile: str | None,
) -> None:
    """Inicia a API e o dashboard; por padrão usa mock offline."""
    from openscan_obd.api.main import main as run_api
    from openscan_obd.profiles import UnknownProfile, get_profile

    if profile:
        try:
            get_profile(profile)
        except UnknownProfile as exc:
            raise click.ClickException(str(exc)) from exc

    run_api(
        host=host,
        port=port,
        mock=mock and not elm_port,
        dll_path=dll,
        capture_path=capture,
        capture_metadata={"vehicle": vehicle, "ecu": ecu, "adapter": adapter},
        elm_port=elm_port,
        profile=profile,
    )


@main.command("profiles")
def profiles_cmd() -> None:
    """Lista os perfis de veículo disponíveis e o quanto cada um foi validado."""
    from openscan_obd.profiles import DEFAULT_PROFILE_ID, list_profiles

    for p in list_profiles():
        padrao = " (padrão)" if p.id == DEFAULT_PROFILE_ID else ""
        click.echo(f"{p.id}{padrao}\n  {p.name}\n  validação: {p.validation}; módulos: "
                   f"{', '.join(p.modules)}; leitura de câmbio: {'sim' if p.has_tcm_lid01 else 'não'}\n"
                   f"  {p.description}\n")


@main.command("elm-check")
@click.option("--port", required=True,
              help="Porta do ELM327: COMx (USB/Bluetooth) ou socket://IP:PORTA (Wi-Fi).")
@click.option("--baudrate", default=38400, show_default=True, type=int,
              help="Só para ELM USB/serial; Bluetooth e Wi-Fi ignoram.")
@click.option("--txid", default="7E0", show_default=True, help="ID de requisição (hex).")
@click.option("--rxid", default="7E8", show_default=True, help="ID de resposta (hex).")
@click.option("--probe-ecm", is_flag=True,
              help="Depois da inicialização, envia só 01 00 (PIDs suportados) e mostra a resposta crua.")
def elm_check(port: str, baudrate: int, txid: str, rxid: str, probe_ecm: bool) -> None:
    """Confere se um ELM327 aceita os comandos AT que o transporte exige.

    Somente leitura: não abre sessão KWP e não envia nada ao veículo além de
    `01 00` com --probe-ecm.
    """
    from openscan_obd.gateway.elm327 import ELM327Device, ELM327Error, ELM327Unsupported

    dev = ELM327Device(port, txid=int(txid, 16), rxid=int(rxid, 16), baudrate=baudrate)
    try:
        try:
            dev.open()
        except ELM327Unsupported as exc:
            click.echo(f"RECUSADO: {exc}")
        except (ELM327Error, OSError) as exc:
            click.echo(f"FALHA ao abrir {port}: {type(exc).__name__}: {exc}")
        for cmd, reply in dev.at_log:
            mark = "??" if "?" in reply else "ok"
            click.echo(f"  [{mark}] {cmd:<14} -> {reply!r}")
        if dev.adapter_id is None:
            raise SystemExit(1)
        click.echo(f"Adaptador: {dev.adapter_id}")
        if probe_ecm:
            try:
                resp = dev.send_recv(bytes.fromhex("0100"), timeout_ms=1000)
                click.echo(f"01 00 -> {resp.hex()}")
            except (ELM327Error, TimeoutError) as exc:
                click.echo(f"01 00 -> falhou: {type(exc).__name__}: {exc}")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
