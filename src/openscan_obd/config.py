"""Configurações de conexão com a interface de diagnóstico (GD101)."""
from dataclasses import dataclass


@dataclass
class ConnectionConfig:
    # Porta serial do GD101 quando em modo ELM327-compatível.
    # O adaptador usado neste projeto foi identificado como COM9.
    serial_port: str = "COM9"
    baudrate: int = 115200

    # Velocidade do barramento CAN do veículo (Nissan tipicamente 500 kbps
    # no CAN de alta velocidade onde fica a TCU/CVT).
    can_bitrate: int = 500_000

    # Timeout padrão (segundos) para respostas UDS.
    uds_timeout: float = 2.0
