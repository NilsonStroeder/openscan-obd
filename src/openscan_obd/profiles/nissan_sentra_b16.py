from openscan_obd.dids import NISSAN_MODULES
from openscan_obd.profiles.base import VehicleProfile

NISSAN_SENTRA_B16_2010 = VehicleProfile(
    id="nissan-sentra-b16-2010",
    name="Nissan Sentra B16 2010 (2.0 flex, CVT JF011E)",
    make="Nissan",
    model="Sentra (B16)",
    years="2010",
    description=(
        "Perfil do carro de teste do projeto (Sentra B16 2010, câmbio CVT JF011E/RE0F10A, adaptador "
        "GODIAG GD101). Os endereços e o mapa de bytes do câmbio foram observados neste único carro; "
        "várias leituras são hipóteses. Não assuma que valem para outro Sentra."
    ),
    modules=NISSAN_MODULES,
    validation="single_vehicle",
    has_tcm_lid01=True,
    notes=(
        "Sessão KWP 10 C0 e leitura 21 01 no TCM (0x7E1/0x7E9).",
        "ABS, airbag e ar-condicionado não responderam à varredura de IDs (2026-11-16).",
    ),
)
