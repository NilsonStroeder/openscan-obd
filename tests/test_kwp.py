"""Testa a lógica KWP2000 (kwp.py) com respostas sintéticas — sem carro."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd import kwp  # noqa: E402


class TestParse(unittest.TestCase):
    def test_positive(self) -> None:
        # 0x21 -> resposta positiva 0x61 <dados>
        r = kwp.parse_response(bytes([0x61, 0x01, 0x12, 0x34]))
        self.assertEqual(r.kind, "positive")
        self.assertEqual(r.data, bytes([0x01, 0x12, 0x34]))

    def test_negative_service_not_supported(self) -> None:
        # 7F 21 11 -> serviceNotSupported (o que o TCM deu pro 0x22)
        r = kwp.parse_response(bytes([0x7F, 0x21, 0x11]))
        self.assertEqual(r.kind, "negative")
        self.assertEqual(r.nrc, 0x11)
        self.assertIn("serviceNotSupported", r.nrc_name)

    def test_negative_request_out_of_range(self) -> None:
        r = kwp.parse_response(bytes([0x7F, 0x21, 0x31]))
        self.assertEqual(r.nrc, 0x31)

    def test_negative_response_for_unexpected_service_raises(self) -> None:
        with self.assertRaises(ValueError):
            kwp.parse_response(bytes([0x7F, 0x10, 0x11]), kwp.SERVICE_READ_LOCAL_ID)

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            kwp.parse_response(b"")

    def test_unrecognized_raises(self) -> None:
        with self.assertRaises(ValueError):
            kwp.parse_response(bytes([0x99, 0x00]))


class TestServiceSupported(unittest.TestCase):
    def test_positive_is_supported(self) -> None:
        r = kwp.parse_response(bytes([0x61, 0x01]))
        self.assertTrue(kwp.service_is_supported(r))

    def test_service_not_supported_is_false(self) -> None:
        # Só o NRC 0x11 derruba o serviço inteiro.
        r = kwp.parse_response(bytes([0x7F, 0x21, 0x11]))
        self.assertFalse(kwp.service_is_supported(r))

    def test_other_service_response_is_not_treated_as_supported(self) -> None:
        r = kwp.KwpResult(kind="negative", service=kwp.SERVICE_START_SESSION, nrc=0x31)
        self.assertFalse(kwp.service_is_supported(r))

    def test_out_of_range_still_supported(self) -> None:
        # requestOutOfRange: o módulo ENTENDE 0x21, só não tem aquele LID.
        r = kwp.parse_response(bytes([0x7F, 0x21, 0x31]))
        self.assertTrue(kwp.service_is_supported(r))

    def test_subfunction_still_supported(self) -> None:
        r = kwp.parse_response(bytes([0x7F, 0x21, 0x12]))
        self.assertTrue(kwp.service_is_supported(r))


class TestBuild(unittest.TestCase):
    def test_build_read_local_id(self) -> None:
        self.assertEqual(kwp.build_read_local_id(0x01), b"\x21\x01")


class TestRunner(unittest.TestCase):
    class FakeConn:
        def __init__(self, responses: dict[int, bytes]) -> None:
            self.responses = responses  # lid -> resposta crua
            self.sent: list[bytes] = []

        def send(self, data: bytes) -> None:
            self.sent.append(data)
            self._last_lid = data[1]

        def wait_frame(self, timeout: float = 2.0) -> bytes:
            return self.responses[self._last_lid]

    def test_read_local_id(self) -> None:
        fake = self.FakeConn({0x01: bytes([0x61, 0x01, 0xAB, 0xCD])})
        r = kwp.read_local_id(fake, 0x01)
        self.assertEqual(r.kind, "positive")
        self.assertEqual(r.data, bytes([0x01, 0xAB, 0xCD]))
        self.assertEqual(fake.sent, [b"\x21\x01"])

    def test_read_local_id_warns_on_unexpected_echo(self) -> None:
        # Módulo não ecoa o LID pedido — deve retornar o dado com warning,
        # não levantar exceção (evita falso negativo no sweep de outros módulos).
        import warnings
        fake = self.FakeConn({0x01: bytes([0x61, 0x02, 0xAB, 0xCD])})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = kwp.read_local_id(fake, 0x01)
        self.assertEqual(r.kind, "positive")
        self.assertTrue(any("ecoado" in str(x.message).lower() for x in w))

    def test_sweep_detects_support_via_negative(self) -> None:
        # Módulo responde serviceNotSupported pra tudo MENOS 0x05, onde dá
        # requestOutOfRange -> suportado=True, nenhum dado positivo.
        responses = {lid: bytes([0x7F, 0x21, 0x11]) for lid in range(0x00, 0x11)}
        responses[0x05] = bytes([0x7F, 0x21, 0x31])  # out of range
        fake = self.FakeConn(responses)
        suportado, achados, _ = kwp.sweep_local_ids(fake, 0x00, 0x10, timeout=0.1)
        self.assertTrue(suportado)
        self.assertEqual(achados, [])

    def test_sweep_collects_positive_data(self) -> None:
        responses = {lid: bytes([0x7F, 0x21, 0x11]) for lid in range(0x00, 0x11)}
        responses[0x02] = bytes([0x61, 0x02, 0x00, 0x5A])  # dado real
        fake = self.FakeConn(responses)
        suportado, achados, _ = kwp.sweep_local_ids(fake, 0x00, 0x10, timeout=0.1)
        self.assertTrue(suportado)
        self.assertEqual(achados, [(0x02, "02005a")])


if __name__ == "__main__":
    unittest.main()


class TestSession(unittest.TestCase):
    def test_build_start_session(self) -> None:
        self.assertEqual(kwp.build_start_session(0x85), b"\x10\x85")

    class FakeConn:
        def __init__(self, responses: dict[int, bytes]) -> None:
            self.responses = responses  # session_type -> resposta crua
            self.sent: list[bytes] = []

        def send(self, data: bytes) -> None:
            self.sent.append(data)
            self._last = data[1]

        def wait_frame(self, timeout: float = 1.0) -> bytes:
            return self.responses[self._last]

    def test_discover_session_finds_accepted_subtype(self) -> None:
        # Todos recusam (7F 10 12) menos 0x85 que aceita (0x50 ...).
        responses = {st: bytes([0x7F, 0x10, 0x12]) for st in kwp.SESSION_TYPES_TO_TRY}
        responses[0x85] = bytes([0x50, 0x85, 0x00, 0x32])  # positivo
        fake = self.FakeConn(responses)
        sess, tentativas = kwp.discover_session(fake, timeout=0.1)
        self.assertEqual(sess, 0x85)
        self.assertEqual(tentativas[0x85], "ACEITO")

    def test_discover_session_none_when_all_refuse(self) -> None:
        responses = {st: bytes([0x7F, 0x10, 0x12]) for st in kwp.SESSION_TYPES_TO_TRY}
        fake = self.FakeConn(responses)
        sess, tentativas = kwp.discover_session(fake, timeout=0.1)
        self.assertIsNone(sess)
        self.assertTrue(all(v != "ACEITO" for v in tentativas.values()))


class TestDataSession(unittest.TestCase):
    def test_build_tester_present(self) -> None:
        self.assertEqual(kwp.build_tester_present(), b"\x3e\x00")

    class FakeConn:
        """Simula: sessao 0xC0 libera 0x21 (retorna dado); as outras abrem
        mas o 0x21 continua dando 0x80; 0x81 so abre sessao."""
        def __init__(self):
            self.sent = []
            self.cur_session = None

        def send(self, data):
            self.sent.append(data)
            self._last = data

        def wait_frame(self, timeout=1.0):
            svc = self._last[0]
            if svc == 0x10:  # start session
                self.cur_session = self._last[1]
                return bytes([0x50, self._last[1]])
            if svc == 0x21:  # read local id
                lid = self._last[1]
                if self.cur_session == 0xC0:
                    return bytes([0x61, lid, 0xAB])  # liberado
                return bytes([0x7F, 0x21, 0x80])     # ainda negado
            if svc == 0x3E:
                return bytes([0x7E, 0x00])
            return bytes([0x7F, svc, 0x11])

    def test_finds_session_that_unlocks_reads(self) -> None:
        fake = self.FakeConn()
        sess, tentativas = kwp.find_data_session(fake, test_lids=(0x80,), timeout=0.1)
        self.assertEqual(sess, 0xC0)
        self.assertEqual(tentativas[0xC0], "ABRIU + 0x21 LIBERADO")
        # 0xC0 e a primeira da lista de prioridade, entao acha de cara

    def test_returns_none_when_no_session_unlocks(self) -> None:
        fake = self.FakeConn()
        # remove a sessao magica: nenhuma libera
        fake.wait_frame_orig = fake.wait_frame
        def only_80(timeout=1.0):
            svc = fake._last[0]
            if svc == 0x10:
                return bytes([0x50, fake._last[1]])
            if svc == 0x21:
                return bytes([0x7F, 0x21, 0x80])
            return bytes([0x7F, svc, 0x11])
        fake.wait_frame = only_80
        sess, tentativas = kwp.find_data_session(fake, test_lids=(0x80, 0x00), timeout=0.1)
        self.assertIsNone(sess)

    def test_sweep_keepalive_sends_tester_present(self) -> None:
        # Conta quantos TesterPresent (0x3E) foram enviados numa varredura.
        class CountConn:
            def __init__(self):
                self.tp = 0
            def send(self, data):
                self._last = data
                if data[0] == 0x3E:
                    self.tp += 1
            def wait_frame(self, timeout=1.0):
                if self._last[0] == 0x3E:
                    return bytes([0x7E, 0x00])
                return bytes([0x7F, 0x21, 0x80])
        c = CountConn()
        kwp.sweep_local_ids(c, 0x00, 0x20, timeout=0.01, keepalive_every=8)
        self.assertGreaterEqual(c.tp, 3)  # ~0x20/8 keepalives
