"""
Camada de transporte — agora usando o suporte NATIVO a J2534 do udsoncan.

Achado importante (2026-10-22): udsoncan já embute
`udsoncan.connections.J2534Connection`, que fala com qualquer interface
J2534 através da DLL do fabricante. Isso elimina a necessidade de um
wrapper ctypes próprio, DESDE que o GD101 instale um driver J2534 padrão
no Windows (o que a maioria dos clones faz).

Passo prático pra descobrir o caminho da DLL:
1. Instalar o driver/software que veio com o GD101 no Windows.
2. Procurar em "C:\\Program Files (x86)\\" por uma pasta do fabricante
   (ex.: "Godiag", "OpenPort", etc.) contendo um arquivo .dll — geralmente
   chamado algo como "op20pt32.dll", "<marca>_J2534.dll", etc.
3. O Painel de Controle do Windows normalmente tem um atalho
   "<Nome do adaptador> J2534 Configuration" que mostra esse caminho.

Se o GD101 não expuser um driver J2534, o transporte serial ELM327 permanece
experimental e não foi validado como alternativa confiável neste projeto.
"""
from __future__ import annotations

import udsoncan
from udsoncan.client import Client
from udsoncan.connections import J2534Connection


class RawBytesDidCodec(udsoncan.DidCodec):
    """Preserva o payload inteiro de um DID sem presumir tamanho ou formato."""

    def __len__(self) -> int:
        raise self.ReadAllRemainingData()

    def decode(self, did_payload: bytes) -> bytes:
        return did_payload


def make_j2534_client(
    dll_path: str,
    rxid: int,
    txid: int,
    baudrate: int = 500_000,
    timeout: float = 2.0,
) -> Client:
    """Monta um cliente UDS pronto pra usar, sobre J2534.

    rxid/txid: IDs CAN de request/response da ECU que você quer falar.
    Confirme os IDs do módulo no veículo antes de enviar requests.
    """
    conn = J2534Connection(
        windll=dll_path,
        rxid=rxid,
        txid=txid,
        baudrate=baudrate,
    )
    config = dict(udsoncan.configs.default_client_config)
    config["request_timeout"] = timeout

    # O codec default preserva os bytes crus; DIDs de tamanho/formato
    # desconhecidos não devem ser truncados nem interpretados como inteiro.
    # À medida que formos confirmando DIDs do CVT (ver dids.py), adicionar
    # os codecs certos aqui também.
    config["data_identifiers"] = {
        "default": RawBytesDidCodec,
        0xF190: udsoncan.AsciiCodec(17),  # VIN: string ASCII de 17 bytes
    }

    return Client(conn, config=config)
