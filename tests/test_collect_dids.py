import unittest

from openscan_obd.gateway.collect import parse_did_ranges, scan_dids, plan_from_discovery


class Dev:
    data_source = "fake"

    def __init__(self, supported=True):
        self.supported = supported
        self.sent = []

    def send_recv(self, data, timeout_ms=200):
        self.sent.append(bytes(data))
        if not self.supported:
            return bytes([0x7F, 0x22, 0x11])
        did = int.from_bytes(data[1:3], "big")
        if did == 0xF190:
            return bytes.fromhex("62f190aa")
        if did == 0xF100:
            return bytes.fromhex("62f10011223344")
        return bytes([0x7F, 0x22, 0x31])


class DidTests(unittest.TestCase):
    def test_parse_ranges(self):
        self.assertEqual(parse_did_ranges("F100-F101,1E00"), [(0xF100, 0xF101), (0x1E00, 0x1E00)])
        self.assertEqual(parse_did_ranges("todos"), [(0, 0xFFFF)])
        with self.assertRaises(ValueError):
            parse_did_ranges("F101-F100")

    def test_unsupported_service_is_one_request_only(self):
        d = Dev(supported=False)
        r = scan_dids(d, [(0xF100, 0xF1FF)], 20)
        self.assertEqual(r["status"], "nao_suportado")
        self.assertEqual(len(d.sent), 1)

    def test_supported_scans_range_and_keeps_data(self):
        d = Dev()
        r = scan_dids(d, [(0xF100, 0xF1FF)], 20)
        self.assertEqual(r["status"], "suportado")
        live = {}
        scan_dids(Dev(), [(0xF190, 0xF190)], 20, out=live)
        self.assertEqual(live["dids"], {"F190": "62f190aa"})
        self.assertEqual(sorted(r["dids"]), ["F100", "F190"])
        self.assertEqual(r["dids"]["F100"], "62f10011223344")

    def test_plan_includes_dids(self):
        disc = {"obd": {}, "kwp": {"eps": {"status": "respondeu", "tx": "0x742", "rx": "0x762",
                                           "lids": {"01": "6101aa"},
                                           "svc22": {"status": "suportado", "dids": {"F190": "62f190aa"}}}}}
        self.assertEqual(plan_from_discovery(disc)["kwp"]["eps"]["dids"], [0xF190])


if __name__ == "__main__":
    unittest.main()
