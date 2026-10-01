"""Default locations for a user's downloaded data and update work."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from dotenv import load_dotenv


def _directory(name, value, leaf):
    load_dotenv(Path.cwd() / ".env", override=False)
    value = value or os.environ.get(name) or Path.home() / "sec-submissions-data" / leaf
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def data_directory(data_dir=None) -> Path:
    """Resolve the Parquet root from an argument, ``DATA_DIR``, or defaults.

    The working directory's ``.env`` is loaded without overriding existing
    environment variables. The fallback is ``~/sec-submissions-data/pq_data``.
    """
    return _directory("DATA_DIR", data_dir, "pq_data")


def raw_data_directory(raw_data_dir=None) -> Path:
    """Resolve the ZIP root from an argument, ``RAW_DATA_DIR``, or defaults."""
    return _directory("RAW_DATA_DIR", raw_data_dir, "raw_data")


class DataPaths:
    def __init__(self, data_dir=None, raw_data_dir=None):
        self.root = data_directory(data_dir)
        self.raw_root = raw_data_directory(raw_data_dir)
        self.submissions = self.root / "submissions"
        self.raw_submissions = self.raw_root / "submissions"
        self.references = self.submissions / "references"
        self.snapshots = self.submissions / "snapshots"
        self.current = self.submissions / "filings.parquet"

    def new_zip(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return self.raw_submissions / f"submissions-{stamp}.zip"

    def zip(self):
        choices = list(self.raw_submissions.glob("submissions*.zip"))
        if not choices:
            raise FileNotFoundError("No local SEC snapshot. Run 'sec-submissions download' first.")
        return max(choices, key=lambda path: (path.stat().st_mtime_ns, path.name))

    def extracted(self, zip_path):
        zip_path = Path(zip_path)
        name = zip_path.stem
        if name == "submissions":
            name += f"-{zip_path.stat().st_mtime_ns}"
        return self.snapshots / name / "filings_raw.parquet"

    def snapshot(self):
        choices = list(self.snapshots.glob("*/filings_raw.parquet"))
        if not choices:
            raise FileNotFoundError("No extracted snapshot. Run 'sec-submissions extract' first.")
        return max(choices, key=lambda path: (path.stat().st_mtime_ns, path.name)).parent

    def raw(self):
        raw = self.snapshot() / "filings_raw.parquet"
        if not raw.is_file():
            raise FileNotFoundError("The latest snapshot is not extracted. Run 'sec-submissions extract'.")
        return raw

    def candidate(self, directory=None):
        folder = Path(directory) if directory is not None else self.snapshot()
        choices = sorted(folder.glob("filings_candidate_*.parquet"))
        if not choices:
            raise FileNotFoundError("No local candidate. Run 'sec-submissions process' first.")
        return max(choices, key=lambda path: (path.stat().st_mtime_ns, path.name))

    def new_candidate(self, raw):
        folder = Path(raw).parent
        number = 1
        while True:
            candidate = folder / f"filings_candidate_{number:04d}.parquet"
            checks = candidate.with_name(candidate.stem + "_checks")
            if not candidate.exists() and not checks.exists():
                return candidate
            number += 1

    def reference(self):
        from .reference_data import ReferenceBundle, validate_manifest

        pointer = self.references / "current.json"
        if not pointer.is_file():
            raise FileNotFoundError("No downloaded reference. Run 'sec-submissions fetch-reference'.")
        version = json.loads(pointer.read_text())["version"]
        if not isinstance(version, str) or Path(version).name != version or "\\" in version or version in {".", ".."}:
            raise ValueError("Invalid local reference version")
        directory = self.references / version
        manifest = validate_manifest(json.loads((directory / "manifest.json").read_text()))
        if manifest["version"] != version:
            raise ValueError("Local reference pointer and manifest disagree")
        bundle = ReferenceBundle(directory, manifest)
        if any(not (directory / asset["name"]).is_file() for asset in manifest["files"]
               if not asset.get("optional", False)):
            raise FileNotFoundError("Reference download is incomplete. Run 'sec-submissions fetch-reference'.")
        return bundle

    def previous(self):
        return self.current if self.current.is_file() else self.reference().filings

    def observations(self, kind):
        name = "sgml_observations.parquet" if kind == "sgml" else "live_json_timestamp_observations.parquet"
        subdir = "sgml" if kind == "sgml" else "live-json"
        paths = list(self.snapshots.glob(f"*/evidence/{subdir}/{name}"))
        shared = self.submissions / "evidence" / subdir / name
        if shared.is_file():
            paths.append(shared)
        return tuple(sorted(paths))
