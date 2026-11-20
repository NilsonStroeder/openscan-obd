from __future__ import annotations

from dataclasses import dataclass, field


class UnknownProfile(KeyError):
    def __str__(self) -> str:      # KeyError coloca aspas na mensagem
        return str(self.args[0])


@dataclass(frozen=True)
class VehicleProfile:
    """Descrição de um veículo (ou de uma família) que a ferramenta sabe tratar.

    modules: nome -> {"tx", "rx", "protocol" ("obd2" | "kwp" | "uds"), "note"}; "engine" é obrigatório
        e é o único que o OBD-II padrão garante (0x7E0/0x7E8).
    has_tcm_lid01: existe decodificador do bloco 21 01 do câmbio (módulo "tcm_cvt").
    validation: "generic" (só padrões públicos) ou "single_vehicle" (confirmado em um carro; não
        significa que vale para outros do mesmo modelo).
    """
    id: str
    name: str
    make: str
    model: str
    years: str
    description: str
    modules: dict[str, dict]
    validation: str
    has_tcm_lid01: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)
