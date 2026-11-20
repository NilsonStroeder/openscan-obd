import unittest
from ctypes import c_ulong

from openscan_obd.gateway.j2534 import PassThruMsg, ERR_BUFFER_EMPTY
from openscan_obd.gateway.sniff import CanSniffer, run_sniff, PROTOCOL_CAN, PASS_FILTER


def frame(can_id: int, data: bytes, ts_us: int = 0) -> PassThruMsg:
    m = PassThruMsg()
    m.ProtocolID = PROTOCOL_CAN
    m.Timestamp = ts_us
    m.Data[0:4] = can_id.to_bytes(4, "big")
    m.Data[4:4 + len(data)] = data
    m.DataSize = 4 + len(data)
    return m


def ticker():
    t = [0.0]
    def f():
        t[0] += 0.01
        return t[0]
    return f


class FakeLib:
    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = []

    def PassThruOpen(self, name, dev): self.calls.append("open"); dev._obj.value = 1; return 0
    def PassThruConnect(self, dev, proto, flags, baud, ch):
        self.calls.append(("connect", proto, baud)); ch._obj.value = 1; return 0
    def PassThruStartMsgFilter(self, ch, ftype, mask, pat, flow, fid):
        self.calls.append(("filter", ftype, bytes(mask._obj.Data[:4]), bytes(pat._obj.Data[:4]), flow is None)); return 0
    def PassThruReadMsgs(self, ch, msg, cnt, timeout):
        if not self.frames:
            return ERR_BUFFER_EMPTY
        src = self.frames.pop(0)
        from ctypes import byref, memmove, sizeof
        memmove(byref(msg._obj), byref(src), sizeof(src))
        return 0
    def PassThruDisconnect(self, ch): self.calls.append("disc"); return 0
    def PassThruClose(self, dev): self.calls.append("close"); return 0
    def PassThruWriteMsgs(self, *a): raise AssertionError("sniffer nunca escreve")
    def PassThruStopMsgFilter(self, *a): return 0


class SniffTests(unittest.TestCase):
    def make(self, frames):
        lib = FakeLib(frames)
        return CanSniffer("x.dll", loader=lambda p: lib), lib

    def test_opens_raw_can_with_pass_all_filter(self):
        s, lib = self.make([])
        s.open()
        self.assertIn(("connect", PROTOCOL_CAN, 500000), lib.calls)
        flt = [c for c in lib.calls if isinstance(c, tuple) and c[0] == "filter"][0]
        self.assertEqual(flt[1], PASS_FILTER)
        self.assertEqual(flt[2], b"\x00\x00\x00\x00")
        self.assertTrue(flt[4])                      # sem flow control

    def test_run_records_every_id_with_raw_bytes_and_summary(self):
        s, _ = self.make([frame(0x180, b"\x01\x02"), frame(0x180, b"\x01\x03"), frame(0x2A0, b"\xff")])
        s.open()
        out = []
        summary = run_sniff(s, 0.05, out.append, clock=ticker())
        recs = [r for r in out if "id" in r]
        self.assertEqual([(r["id"], r["data"]) for r in recs],
                         [("180", "0102"), ("180", "0103"), ("2A0", "ff")])
        self.assertEqual(summary["ids"]["180"]["count"], 2)
        self.assertEqual(summary["ids"]["180"]["distinct"], 2)
        self.assertEqual(out[0]["event"], "sniff_started")
        self.assertEqual(out[-1]["event"], "sniff_finished")

    def test_never_writes(self):
        s, lib = self.make([frame(0x1, b"\x00")])
        s.open()
        run_sniff(s, 0.01, lambda r: None, clock=ticker())
        s.close()
        self.assertIn("close", lib.calls)


if __name__ == "__main__":
    unittest.main()
