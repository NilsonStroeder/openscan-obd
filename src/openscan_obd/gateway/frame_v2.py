"""Frame v2 do dashboard e agendador de PIDs OBD. Lógica pura, sem I/O.

Cada valor leva a fonte (`obd:0C`, `tcm:21 01[54]`), o selo de confiança (tier),
a idade da leitura e o hex cru. As chaves planas antigas (rpm, vsp, ect, tps...)
continuam no frame para não quebrar a API e a tela atuais (decisão 2026-11-15),
mas só são preenchidas com leitura recente.
"""
from __future__ import annotations

SCHEMA_VERSION = 2

TIER_STANDARD = "padrao"          # SAE J1979, confirmado por padrão
TIER_CONFIRMED = "confirmado"     # ✅ no tracker (2+ contrastes independentes)
TIER_ESTIMATED = "estimado"       # tabela/estimativa sem referência independente
TIER_RAW = "cru"                  # byte sem interpretação
TIER_UNAVAILABLE = "indisponivel"

STALE_AFTER_S = 2.0               # além disso o valor deixa de alimentar as chaves planas
SLOW_STALE_AFTER_S = 15.0         # PID lento só é relido a cada N ciclos; não pode piscar entre visitas
MAX_CONSECUTIVE_ERRORS = 3

# chave do valor OBD -> chave plana legada lida pela tela atual
LEGACY_FLAT = {
    "rpm": "rpm", "vsp": "vsp", "ect": "ect", "tps": "tps", "iat": "iat",
    "stft": "stft", "ltft": "ltft", "o2_b1s1": "o2s1", "timing": "ign_adv",
}


class ObdSchedule:
    """PIDs rápidos a cada ciclo; um PID lento por ciclo, em rodízio.

    PID recusado pelo ECM (NRC) sai da fila de vez; erro de leitura só tira o PID
    depois de 3 seguidos (falha transitória não pode esconder um PID válido).
    """

    def __init__(self, fast: dict[int, str], slow: dict[int, str]) -> None:
        self.fast = dict(fast)
        self.slow = dict(slow)
        self.unsupported: set[int] = set()
        self._errors: dict[int, int] = {}
        self._slow_order = list(slow)
        self._cursor = 0

    def next_batch(self) -> dict[int, str]:
        batch = {p: k for p, k in self.fast.items() if p not in self.unsupported}
        for _ in range(len(self._slow_order)):
            pid = self._slow_order[self._cursor % len(self._slow_order)]
            self._cursor += 1
            if pid not in self.unsupported:
                batch[pid] = self.slow[pid]
                break
        return batch

    def record(self, pid: int, result: dict) -> None:
        if "value" in result:
            self._errors.pop(pid, None)
        elif "nrc" in result:
            self.unsupported.add(pid)
        else:
            self._errors[pid] = self._errors.get(pid, 0) + 1
            if self._errors[pid] >= MAX_CONSECUTIVE_ERRORS:
                self.unsupported.add(pid)


def update_obd_cache(cache: dict, result: dict, pids: dict[int, str], t: float,
                     slow_pids: set[int] | None = None) -> None:
    """Atualiza `cache[chave]` com o resultado de read_obd_live.

    `slow_pids`: PIDs lidos em rodízio; ganham uma validade maior (`SLOW_STALE_AFTER_S`).
    """
    slow_pids = slow_pids or set()
    for pid, key in pids.items():
        r = result.get("pids", {}).get(key)
        if r is None:
            continue
        pid_hex = f"{pid:02X}"
        ttl = SLOW_STALE_AFTER_S if pid in slow_pids else STALE_AFTER_S
        if "value" in r:
            cache[key] = {"value": r["value"], "unit": r["unit"], "source": f"obd:{pid_hex}",
                          "tier": TIER_STANDARD, "raw": result.get("raw", {}).get(pid_hex, ""),
                          "t": t, "ttl": ttl}
        else:
            reason = (f"ECM recusou o PID (NRC 0x{r['nrc']})" if "nrc" in r
                      else r.get("error", "sem leitura"))
            cache[key] = {"value": None, "unit": "", "source": f"obd:{pid_hex}",
                          "tier": TIER_UNAVAILABLE, "reason": reason,
                          "raw": result.get("raw", {}).get(pid_hex, ""), "t": t, "ttl": ttl}


def update_tcm_cache(cache: dict, d: dict, t: float) -> None:
    """Atualiza `cache` com o dict de `decode_tcm_lid01` (LID 0x01 do TCM).

    Gear [54], REV [40], RPM [6,7] e VSP [3] são ✅; o ATF [30] é só estimado
    (decisão 2026-11-15); [38] fica cru. O byte [54] desconhecido não é inventado.
    """
    def put(key, value, unit, source, tier, raw):
        cache[key] = {"value": value, "unit": unit, "source": source, "tier": tier,
                      "raw": raw, "t": t}

    gear = d.get("gear")
    put("gear", gear, "", "tcm:21 01[54]>>4", TIER_CONFIRMED if gear else TIER_RAW,
        d["gear_raw"])
    put("reverse", d["REV_b40"] == "REVERSE", "", "tcm:21 01[40]==5A", TIER_CONFIRMED,
        f"{d['raw_hex'][80:82]}")
    put("rpm_tcm", d["ENG_SPEED_rpm"], "rpm", "tcm:21 01[6,7]/8", TIER_CONFIRMED,
        d["raw_hex"][12:16])
    put("vsp_tcm", d["VSP_b3"], "km/h", "tcm:21 01[3]", TIER_CONFIRMED,
        f"{d['VSP_b3']:02x}{d['VSP_b4']:02x}")
    put("atf", d["atf_temp_c_estimated"], "C", "tcm:21 01[30] (tabela ESM)", TIER_ESTIMATED,
        f"{d['b30']:02x}")
    put("lockup_b38", d["b38_lockup_raw"], "", "tcm:21 01[38]", TIER_RAW, d["b38_lockup_raw"])


def render_values(cache: dict, now: float) -> dict:
    """Cópia do cache com `age_ms` no lugar do carimbo interno `t`."""
    out = {}
    for key, e in cache.items():
        row = {k: v for k, v in e.items() if k not in ("t", "ttl")}
        row["age_ms"] = round((now - e["t"]) * 1000)
        row["stale_ms"] = round(e.get("ttl", STALE_AFTER_S) * 1000)
        out[key] = row
    return out


def module_state(last_ok: float | None, now: float, error: str | None = None) -> dict:
    if last_ok is None:
        state = {"status": "unavailable"}
    else:
        age = now - last_ok
        state = {"status": "ok" if age <= STALE_AFTER_S else "stale", "age_ms": round(age * 1000)}
    if error:
        state["error"] = error
    return state


def build_frame(*, ts: float, conn: bool, data_source: str, values: dict, cvt: dict,
                modules: dict, now: float) -> dict:
    rendered = render_values(values, now)
    frame: dict = {
        "schema": SCHEMA_VERSION, "ts": ts, "conn": conn, "data_source": data_source,
        "modules": modules, "values": rendered, "cvt": render_values(cvt, now),
    }
    fresh = False
    for key, flat in LEGACY_FLAT.items():
        e = rendered.get(key)
        if conn and e and e["value"] is not None and e["age_ms"] <= e["stale_ms"]:
            frame[flat] = e["value"]
            fresh = True
    frame["data_available"] = fresh     # `lid_available` segue sendo só o LID do ECM
    if fresh:
        frame["verified"] = True        # leituras OBD padrão, não o perfil B17 não verificado
    return frame
