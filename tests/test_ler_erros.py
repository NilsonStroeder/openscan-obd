from openscan_obd.gateway.ler_erros import formatar, ler_erros


class FakeDev:
    """ECM sem códigos; TCM com os 3 códigos reais de 16/11; EPS recusa; demais sem resposta."""
    TCM = bytes.fromhex("57030725f1d000a71722f1")

    def __init__(self):
        self.ids = (0x7E0, 0x7E8)
        self.sent = []

    def set_ids(self, tx, rx):
        self.ids = (tx, rx)

    def send_recv(self, data, timeout_ms=200):
        self.sent.append((self.ids, bytes(data)))
        tx = self.ids[0]
        if data[0] == 0x10:
            return bytes([0x50, 0xC0])
        if tx == 0x7E0:
            if data[0] == 0x03:
                return bytes.fromhex("4300")
            if data[0] == 0x07:
                return bytes.fromhex("4700")
            raise TimeoutError
        if data[0] == 0x17 and tx == 0x7E1:
            return self.TCM
        if data[0] == 0x17 and tx == 0x742:
            return bytes([0x7F, 0x17, 0x12])
        raise TimeoutError


def test_le_tcm_e_nao_envia_apagar():
    dev = FakeDev()
    res = ler_erros(dev)
    tcm = next(m for m in res["modulos"] if "TCM" in m["modulo"])
    assert [c["code"] for c in tcm["decodificado"]["codes"]] == ["P0725", "U1000", "P1722"]
    assert all(req[0] not in (0x04, 0x14) for _, req in dev.sent)
    assert dev.ids == (0x7E0, 0x7E8)            # devolve os IDs ao motor


def test_texto_distingue_zero_recusa_e_sem_resposta():
    t = formatar(ler_erros(FakeDev()))
    assert "P1722  Sinal de velocidade do veículo" in t
    assert "armazenados: respondeu 0 códigos" in t
    assert "recusou este pedido (NRC 12)" in t
    assert "NÃO quer dizer sem falhas" in t
