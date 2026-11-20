"""Comando j2534-check com DLL falsa — sem hardware e sem enviar mensagens."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from click.testing import CliRunner  # noqa: E402

from openscan_obd.cli import main  # noqa: E402
from openscan_obd.gateway import j2534  # noqa: E402
from openscan_obd.gateway.j2534 import ERR_FAILED, STATUS_NOERROR  # noqa: E402
from test_j2534_wrapper import FakeLib, _loader_from  # noqa: E402


class VersionLib(FakeLib):
    def PassThruReadVersion(self, _device, firmware, dll, api):
        for buf, text in ((firmware, b"FW1.0"), (dll, b"DLL2.0"), (api, b"04.04")):
            buf[:len(text)] = text
        return STATUS_NOERROR


class TestJ2534Check(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dll = Path(self._tmp.name) / "fake_PT32.dll"
        self.dll.write_bytes(b"")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, lib):
        real = j2534.J2534Device

        def factory(path, *args, **kwargs):
            return real(path, *args, loader=_loader_from(lib), **kwargs)

        with patch.object(j2534, "J2534Device", factory):
            return CliRunner().invoke(main, ["j2534-check", "--dll", str(self.dll)])

    def test_success_opens_and_closes_without_sending(self) -> None:
        lib = VersionLib()
        result = self._run(lib)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK: adaptador abriu e fechou", result.output)
        self.assertIn("firmware=FW1.0 dll=DLL2.0 api=04.04", result.output)
        self.assertIn("bits", result.output)
        self.assertEqual(lib.written, [])
        self.assertFalse(lib.opened)
        self.assertFalse(lib.connected)

    def test_success_without_read_version_export(self) -> None:
        lib = FakeLib()
        result = self._run(lib)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("não oferece PassThruReadVersion", result.output)
        self.assertEqual(lib.written, [])

    def test_missing_dll_fails(self) -> None:
        missing = Path(self._tmp.name) / "nao_existe.dll"
        result = CliRunner().invoke(main, ["j2534-check", "--dll", str(missing)])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("FALHA: DLL não encontrada", result.output)

    def test_passthru_open_failure_reports_error(self) -> None:
        class Boom(FakeLib):
            def PassThruOpen(self, _name, _p_device):
                return ERR_FAILED

            def PassThruGetLastError(self, buf):
                text = b"device not found"
                buf[:len(text)] = text
                return STATUS_NOERROR

        result = self._run(Boom())

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("FALHA: PassThruOpen: ERR_FAILED: device not found", result.output)
        self.assertNotIn("OK:", result.output)

    def test_32bit_dll_warning_on_64bit_python(self) -> None:
        with patch("struct.calcsize", return_value=8):
            result = self._run(FakeLib())
        self.assertIn("AVISO", result.output)
        self.assertIn("64 bits", result.output)


if __name__ == "__main__":
    unittest.main()
