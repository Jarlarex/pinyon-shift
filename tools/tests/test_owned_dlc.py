"""Installing every owned DLC package from one folder, with synthetic packages only."""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("dlc", ROOT / "tools/manage-fh1-dlc.py")
dlc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dlc)


def package_bytes(content_id: str, content_type: str = "00000002", fill: int = 0) -> bytes:
    data = bytearray([fill]) * 0xA000
    data[:4] = b"LIVE"
    data[0x32C:0x340] = bytes.fromhex(content_id)
    data[0x344:0x348] = bytes.fromhex(content_type)
    data[0x360:0x364] = bytes.fromhex("4D5309C9")
    return bytes(data)


class OwnedDlcFolderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pinyon-owned-dlc-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        payload = self.root / "payload"
        payload.mkdir()
        (payload / "offer.puboffer").write_bytes(b"owned")
        _, digest = dlc.payload_catalog(payload)
        self.good = package_bytes("11" * 20)
        rejected = package_bytes("22" * 20, fill=1)
        self.package = dict(package_id="A" * 42, content_id="11" * 20, display_name="Owned Car Pack",
                            payload_sha256=digest, file_count=1, rejected=[], accepted=[dict(
                                sha256=hashlib.sha256(self.good).hexdigest().upper(), size=len(self.good),
                                license_mask="00000001")])
        damaged = dict(package_id="B" * 42, content_id="22" * 20, display_name="Damaged Pack",
                       payload_sha256=digest, file_count=1, accepted=[], rejected=[dict(
                           sha256=hashlib.sha256(rejected).hexdigest().upper(), size=len(rejected),
                           reason="Corrupt terrain archive")])
        self.manifest = dict(title_id="4D5309C9", content_type="00000002", packages=[self.package, damaged])
        self.source = self.root / "gamefiles"
        (self.source / "tu").mkdir(parents=True)
        (self.source / "owned.pkg").write_bytes(self.good)
        with zipfile.ZipFile(self.source / "owned again (ZIP).zip", "w") as archive:
            archive.writestr("4D5309C9/00000002/" + "A" * 42, self.good)
        (self.source / "damaged.pkg").write_bytes(rejected)
        (self.source / "unknown.pkg").write_bytes(package_bytes("33" * 20))
        (self.source / "tu" / "tu0000000c_00000000").write_bytes(package_bytes("44" * 20, "000B0000"))
        (self.source / "notes.txt").write_text("not a package")
        self.before = {path: path.read_bytes() for path in self.source.rglob("*") if path.is_file()}
        self.state = self.root / "state"

    def extract(self, args, **kwargs):
        destination, package_id = Path(args[3]), args[4]
        folder = destination / dlc.CONTENT / "00000002" / package_id
        folder.mkdir(parents=True)
        (folder / "offer.puboffer").write_bytes(b"owned")
        header = destination / dlc.CONTENT / "Headers" / "00000002" / (package_id + ".header")
        header.parent.mkdir(parents=True)
        header.write_bytes(bytes(328) + b"\1\0\0\0")
        return subprocess.CompletedProcess(args, 0, "", "")

    def install(self):
        with patch.object(dlc, "catalog", return_value=self.manifest), \
                patch.object(dlc.subprocess, "check_output", return_value=b""), \
                patch.object(dlc.subprocess, "run", side_effect=self.extract):
            return dlc.install_folder(self.source, self.state, self.root / "extractor")

    def test_every_owned_package_is_installed_and_enabled_and_the_rest_reported(self):
        report = {Path(row["file"]).name: row for row in self.install()["files"]}
        # The same package raw and in a ZIP: whichever comes first is imported.
        self.assertEqual(sorted(report[name]["status"] for name in ("owned.pkg", "owned again (ZIP).zip")),
                         ["already installed", "imported"])
        self.assertEqual(report["damaged.pkg"]["status"], "skipped")
        self.assertIn("Corrupt terrain archive", report["damaged.pkg"]["reason"])
        self.assertIn("not in the verified catalog", report["unknown.pkg"]["reason"])
        self.assertIn("title update", report["tu0000000c_00000000"]["reason"])
        self.assertEqual(report["notes.txt"]["reason"], "not a DLC package")
        packages = {row["package_id"]: row for row in dlc.list_content(self.state)}
        self.assertTrue(packages["A" * 42]["enabled"])
        for path, data in self.before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_a_running_game_stops_the_whole_folder_at_once(self):
        with patch.object(dlc, "catalog", return_value=self.manifest), \
                patch.object(dlc.subprocess, "check_output", return_value=b'"pinyon_shift.exe","1"'), \
                patch.object(dlc.subprocess, "run", side_effect=self.extract):
            with self.assertRaisesRegex(ValueError, "close the game"):
                dlc.install_folder(self.source, self.state, self.root / "extractor")
        self.assertFalse(list(self.state.glob("user/**/00000002/*")))

    def test_a_licence_only_copy_sorted_first_still_joins_its_verified_copy(self):
        broken = package_bytes("11" * 20, fill=2)
        self.package["rejected"].append(dict(sha256=hashlib.sha256(broken).hexdigest().upper(), size=len(broken),
                                             license_mask="00000004", reason="Corrupt terrain archive",
                                             license_only=True))
        self.source = self.root / "licence-first"
        self.source.mkdir()
        (self.source / "a corrupt copy.pkg").write_bytes(broken)
        (self.source / "b verified copy.pkg").write_bytes(self.good)
        report = {Path(row["file"]).name: row["status"] for row in self.install()["files"]}
        self.assertEqual(report, {"a corrupt copy.pkg": "imported", "b verified copy.pkg": "imported"})
        package = {row["package_id"]: row for row in dlc.list_content(self.state)}["A" * 42]
        self.assertEqual(package["license_mask"], "00000005")
        self.assertTrue(package["enabled"])

    def test_installing_again_changes_nothing(self):
        self.install()
        report = {Path(row["file"]).name: row["status"] for row in self.install()["files"]}
        self.assertEqual(report["owned.pkg"], "already installed")
        self.assertTrue({row["package_id"]: row for row in dlc.list_content(self.state)}["A" * 42]["enabled"])


class ExtractorDiscoveryTests(unittest.TestCase):
    def test_extractor_is_found_in_any_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidates = [root / build / "pinyon_shift_fh1_archive_extract.exe" for build in dlc.EXTRACTOR_BUILDS]
            self.assertEqual(dlc.default_extractor(root), candidates[0])
            candidates[-1].parent.mkdir(parents=True)
            candidates[-1].write_bytes(b"exe")
            self.assertEqual(dlc.default_extractor(root), candidates[-1])
            candidates[1].parent.mkdir(parents=True)
            candidates[1].write_bytes(b"exe")
            self.assertEqual(dlc.default_extractor(root), candidates[1])


class CatalogTests(unittest.TestCase):
    def test_catalog_has_the_mustang_pizza_hut_pack_and_unique_ids(self):
        catalog = json.loads((ROOT / "config/supported-dlc.json").read_text(encoding="utf-8"))
        ids = [package["package_id"] for package in catalog["packages"]]
        self.assertEqual(len(ids), len(set(ids)))
        mustang = next(p for p in catalog["packages"] if p["package_id"] == "D4888FE9189BEF249567245E784F876794F0BDC04D")
        self.assertEqual(mustang["content_id"], "0390E8868FD0F18657144FA6F6B1329D980E8D02")
        self.assertEqual(mustang["accepted"][0]["sha256"],
                         "C19665C453830AD41D8D6A970C981856AF4BF3E994BFE31EDC554F885D62F811")
        # Its licence is empty; offer 2800 needs ContentOffers.LicenseMask 1.
        self.assertEqual(mustang["accepted"][0]["license_mask"], "00000000")
        self.assertEqual(mustang["license_grant"]["mask"], "00000001")

    def test_rally_corrupt_copy_supplies_only_its_licence(self):
        catalog = json.loads((ROOT / "config/supported-dlc.json").read_text(encoding="utf-8"))
        rally = next(p for p in catalog["packages"] if p["package_id"] == "6F6992766050D818245ADD408031E280FB5F4E634D")
        corrupt = next(v for v in rally["rejected"] if v["sha256"].startswith("AA7BD510"))
        # Its licence covers the season-pass Focus SVT (offer mask 00000004).
        self.assertTrue(corrupt["license_only"])
        self.assertEqual(int(corrupt["license_mask"], 16) & 4, 4)
        self.assertEqual([v["license_mask"] for v in rally["accepted"]], ["00000001"])

    def test_catalog_licence_grants_are_explicit(self):
        catalog = json.loads((ROOT / "config/supported-dlc.json").read_text(encoding="utf-8"))
        for package in catalog["packages"]:
            if "license_grant" in package:
                grant = package["license_grant"]
                self.assertRegex(grant["mask"], r"\A[0-9A-F]{8}\Z")
                self.assertNotEqual(grant["mask"], "00000000")
                self.assertTrue(grant["reason"].strip())


if __name__ == "__main__":
    unittest.main()
