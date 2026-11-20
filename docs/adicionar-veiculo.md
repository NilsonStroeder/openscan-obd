# Como adicionar um veículo

Um **perfil** descreve o que a ferramenta sabe sobre um carro: quais módulos existem, em quais IDs
CAN e por qual protocolo, e quanto isso foi validado.

## 1. Comece pelo genérico

Rode o dashboard com o perfil padrão `generic-obd2`. Ele só usa padrões públicos (SAE J1979) e funciona
em qualquer carro que fale OBD-II no ECM (0x7E0/0x7E8). Se isso já resolve, não precisa de perfil.

## 2. Descubra os módulos (carro parado, ignição ligada, só leitura)

```
python -m openscan_obd.cli discover --dll <driver.dll>
python -m openscan_obd.cli scan-all --dll <driver.dll> --start 700 --end 7FF
```

Anote cada par TX/RX que respondeu e o protocolo (OBD-II, KWP `10 C0`/`21`, UDS `22`).
Evite varrer 0x600–0x6FF: pode travar alguns adaptadores.

## 3. Crie o arquivo do perfil

Copie `src/openscan_obd/profiles/nissan_sentra_b16.py` para `profiles/<marca>_<modelo>_<ano>.py`:

```python
from openscan_obd.profiles.base import VehicleProfile

MEU_CARRO = VehicleProfile(
    id="marca-modelo-ano",
    name="Marca Modelo Ano (motor, câmbio)",
    make="Marca", model="Modelo", years="2015",
    description="O que foi observado, em qual carro, com qual adaptador.",
    modules={
        "engine": {"tx": 0x7E0, "rx": 0x7E8, "protocol": "obd2", "note": ""},
    },
    validation="single_vehicle",   # ou "generic"
    has_tcm_lid01=False,           # True só se existir decodificador do câmbio para este carro
    notes=("evidência e limitações",),
)
```

Registre em `profiles/__init__.py` (dentro de `PROFILES`).

## 4. Níveis de evidência

| Selo | Significado |
|---|---|
| padrão | Definido por norma pública (ex.: PID 0C = RPM) |
| confirmado | Comparado com instrumento ou comportamento conhecido neste carro |
| estimado | Fórmula plausível, ainda não conferida |
| cru | Bytes sem interpretação |
| indisponível | Não respondeu; o motivo é mostrado |

Nunca promova um valor sem evidência registrada em `docs/`.

## 5. Testes e envio

Adicione um teste em `tests/test_profiles.py` (perfil registrado, módulos coerentes) e, se criar
decoder, testes com bytes reais **sanitizados** (sem VIN). Rode `python -m pytest tests --ignore=tests/browser`.
Veja `CONTRIBUTING.md`.
