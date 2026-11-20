"""Perfis de veículo.

Tudo que é específico de um carro (endereços CAN dos módulos, protocolo de cada um, se existe um
decodificador de dados do câmbio) mora num perfil. O fluxo genérico (OBD-II padrão, adaptador,
guarda de somente leitura, dashboard) não deve conhecer marca nem modelo.

Para adicionar um carro, veja docs/adicionar-veiculo.md.
"""
from __future__ import annotations

from openscan_obd.profiles.base import UnknownProfile, VehicleProfile
from openscan_obd.profiles.generic_obd2 import GENERIC_OBD2
from openscan_obd.profiles.nissan_sentra_b16 import NISSAN_SENTRA_B16_2010

DEFAULT_PROFILE_ID = GENERIC_OBD2.id

PROFILES: dict[str, VehicleProfile] = {
    p.id: p for p in (GENERIC_OBD2, NISSAN_SENTRA_B16_2010)
}


def get_profile(profile_id: str) -> VehicleProfile:
    try:
        return PROFILES[profile_id]
    except KeyError:
        raise UnknownProfile(
            f"perfil {profile_id!r} não existe; disponíveis: {', '.join(sorted(PROFILES))}"
        ) from None


def list_profiles() -> list[VehicleProfile]:
    return sorted(PROFILES.values(), key=lambda p: p.id)


__all__ = ["DEFAULT_PROFILE_ID", "PROFILES", "UnknownProfile", "VehicleProfile",
           "get_profile", "list_profiles"]
