from openscan_obd.profiles.base import VehicleProfile

GENERIC_OBD2 = VehicleProfile(
    id="generic-obd2",
    name="Genérico OBD-II",
    make="qualquer",
    model="qualquer",
    years="OBD-II / EOBD (CAN ISO 15765, 11 bits)",
    description=(
        "Só padrões públicos (SAE J1979): PIDs ao vivo, DTCs padrão e identificação do motor. "
        "Não fala com nenhum outro módulo e não lê dados do câmbio."
    ),
    modules={
        "engine": {"tx": 0x7E0, "rx": 0x7E8, "protocol": "obd2",
                   "note": "ECM padrão OBD-II (endereço definido pela norma)"},
    },
    validation="generic",
    has_tcm_lid01=False,
    notes=("Seguro como padrão: nada específico de fabricante é enviado.",),
)
