#!/usr/bin/env python3
"""Clone a stock FH1 car into a new, separate car, from the player's own files.

The result is a staging tree in the layout a DLC package mounts (`media/...`):
the stock car's model files under a new media name, its audio tuning, and a
merge database with its rows copied to a new car ID. Every source is read
only; nothing in the disc, the title update or an installed package changes.
"""
import re
import sqlite3
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

TITLE_CONTENT = Path("user/0000000000000000/4D5309C9")
XMEM = 21  # FH1's LZX ("XMem") zip compression method


def _load_tool(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Sources:
    """Read-only view of the player's disc, installed title update and enabled packages."""

    def __init__(self, state_root: Path, game_root: Path, extractor: Path):
        self.state_root, self.game_root, self.extractor = Path(state_root), Path(game_root), Path(extractor)

    # -- archives ---------------------------------------------------------

    def member(self, archive: Path, info: zipfile.ZipInfo) -> bytes:
        """One archive member's bytes; XMem members go through the native extractor."""
        if info.compress_type != XMEM:
            with zipfile.ZipFile(archive) as zipped:
                return zipped.read(info)
        with open(archive, "rb") as stream:
            stream.seek(info.header_offset)
            header = stream.read(30)
        name_length, extra_length = struct.unpack_from("<HH", header, 26)
        offset = info.header_offset + 30 + name_length + extra_length
        with tempfile.TemporaryDirectory(prefix="pinyon-clone-") as directory:
            output = Path(directory) / "member"
            result = subprocess.run([str(self.extractor), str(archive), str(offset), str(info.compress_size),
                                     str(info.file_size), str(output)], capture_output=True)
            if result.returncode or not output.is_file():
                raise ValueError(f"the archive extractor could not read {info.filename} from {archive.name}")
            return output.read_bytes()

    def _members(self, archive: Path, prefix: str = "", file_name: str | None = None) -> dict[str, bytes]:
        """Members under `prefix` (optionally only those named `file_name`), keyed without the prefix."""
        with zipfile.ZipFile(archive) as zipped:
            infos = [info for info in zipped.infolist()
                     if not info.is_dir() and info.filename.lower().startswith(prefix.lower())
                     and (file_name is None or info.filename.replace("\\", "/").split("/")[-1].lower() == file_name)]
        return {info.filename[len(prefix):]: self.member(archive, info) for info in infos}

    def _package_archives(self) -> list[Path]:
        """Every DLCZips archive of the enabled packages (Disabled/ is skipped)."""
        return sorted((self.state_root / TITLE_CONTENT / "00000002").glob("*/Media/DLCZips/*.zip"))

    # -- database ---------------------------------------------------------

    def database(self) -> sqlite3.Connection:
        """The title update's game database with its merges and every enabled
        package's merge applied, merges in merge-number order, in memory."""
        update = self.state_root / "title-update-v4" / "media.zip"
        merges: list[tuple[int, bytes]] = []
        if update.is_file():
            with zipfile.ZipFile(update) as zipped:
                infos = {info.filename.lower(): info for info in zipped.infolist()}
            base = self.member(update, infos["db/gamedb.slt"])
            merges += [(self._merge_number(name), self.member(update, info)) for name, info in infos.items()
                       if name.startswith("db/patch/") and name.endswith("_merge.slt")]
        else:
            base = (self.game_root / "media/db/gamedb.slt").read_bytes()
        for archive in self._package_archives():
            with zipfile.ZipFile(archive) as zipped:
                infos = [info for info in zipped.infolist()
                         if info.filename.lower().startswith("media/db/patch/")
                         and info.filename.lower().endswith("_merge.slt")]
            merges += [(self._merge_number(info.filename), self.member(archive, info)) for info in infos]
        con = sqlite3.connect(":memory:")
        con.deserialize(base)
        for _, data in sorted(merges, key=lambda merge: merge[0]):
            self._apply_merge(con, data)
        return con

    @staticmethod
    def _merge_number(name: str) -> int:
        match = re.search(r"(\d+)_merge\.slt$", name, re.IGNORECASE)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _apply_merge(con: sqlite3.Connection, data: bytes) -> None:
        merge = sqlite3.connect(":memory:")
        merge.deserialize(data)
        for table, sql in merge.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                con.execute(sql)
            columns = [column[1] for column in merge.execute(f"PRAGMA table_info([{table}])")]
            names = ",".join(f"[{column}]" for column in columns)
            # A later merge replaces a row with the same key (the update re-ships CameraOverrides).
            con.executemany(f"INSERT OR REPLACE INTO [{table}] ({names}) VALUES ({','.join('?' * len(columns))})",
                            merge.execute(f"SELECT {names} FROM [{table}]"))
        merge.close()

    # -- strings ----------------------------------------------------------

    def data_car_keys(self) -> set[int]:
        """Every key used in any installed Data_Car string table, any language."""
        strings = _load_tool("fh1-strings")
        tables = []
        for archive in sorted((self.game_root / "media/StringTables").glob("*.zip")):
            tables += self._members(archive, file_name="data_car.str").values()
        for archive in self._package_archives():
            if archive.name.lower().startswith("stringtables_"):
                tables += self._members(archive, file_name="data_car.str").values()
        return {key for data in tables for key, _ in strings.parse(data)}

    # -- car files --------------------------------------------------------

    def car_files(self, media_name: str) -> dict[str, bytes]:
        """The stock car's model archive: the disc's media/cars/<name>.zip, or the
        media/cars/<name>/ folder of an enabled package."""
        disc = self.game_root / "media" / "cars" / f"{media_name}.zip"
        if disc.is_file():
            return self._members(disc)
        prefix = f"media/cars/{media_name}/"
        for archive in self._package_archives():
            with zipfile.ZipFile(archive) as zipped:
                if any(name.lower().startswith(prefix.lower()) for name in zipped.namelist()):
                    return self._members(archive, prefix)
        raise ValueError(f"car {media_name} is not on the disc or in an enabled package")

    def audio_files(self, media_name: str) -> dict[str, bytes]:
        """The car's CarModelTuning and EngineTuning XML, from the disc or a package."""
        wanted = {"CarModelTuning": (f"{media_name}_CMT.xml", "media/audio/cars/CarModelTuning.zip",
                                     "media/audio/cars/CarModelTuning/"),
                  "EngineTuning": (f"{media_name}_ET.xml", "media/audio/cars/Engines/EngineTuning.zip",
                                   "media/audio/cars/Engines/EngineTuning/")}
        found = {}
        for kind, (file_name, disc_archive, package_folder) in wanted.items():
            disc = self.game_root / disc_archive
            if disc.is_file():
                with zipfile.ZipFile(disc) as zipped:
                    info = next((i for i in zipped.infolist() if i.filename.lower() == file_name.lower()), None)
                if info:
                    found[kind] = self.member(disc, info)
                    continue
            for archive in self._package_archives():
                with zipfile.ZipFile(archive) as zipped:
                    info = next((i for i in zipped.infolist()
                                 if i.filename.lower() == (package_folder + file_name).lower()), None)
                if info:
                    found[kind] = self.member(archive, info)
                    break
            else:
                raise ValueError(f"no {kind} file for car {media_name}")
        return found
