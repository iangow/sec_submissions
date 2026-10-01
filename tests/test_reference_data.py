import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sec_submissions import fetch_reference
from sec_submissions._paths import DataPaths
from sec_submissions.reference_data import _download_asset, validate_manifest


class Response(io.BytesIO):
    def __init__(self, payload, status=200, headers=None):
        super().__init__(payload)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(payload))}


def asset(name, content, role="filings", optional=False):
    return {"name": name, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "role": role, "optional": optional}


class ReferenceDataTests(unittest.TestCase):
    def test_env_file_separates_raw_and_parquet_roots_and_respects_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / ".env").write_text(f'RAW_DATA_DIR="{root}/raw with spaces"\nDATA_DIR="{root}/from-file"\n')
            with patch.dict(os.environ, {"DATA_DIR": str(root / "from-process")}, clear=True), patch("pathlib.Path.cwd", return_value=root):
                paths = DataPaths()
                self.assertEqual(paths.raw_root, root / "raw with spaces")
                self.assertEqual(paths.root, root / "from-process")
                self.assertEqual(paths.new_zip().parent, root / "raw with spaces" / "submissions")
                self.assertEqual(paths.current, root / "from-process" / "submissions" / "filings.parquet")
                self.assertEqual(DataPaths(root / "explicit").root, root / "explicit")

    def test_download_resumes_only_from_an_exact_range(self):
        payload = b"a reference file that was interrupted"
        checksum = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filings.parquet"
            path.with_name(path.name + ".part").write_bytes(payload[:9])
            response = Response(payload[9:], 206, {"Content-Length": str(len(payload)-9),
                                                 "Content-Range": f"bytes 9-{len(payload)-1}/{len(payload)}"})
            with patch("urllib.request.urlopen", return_value=response) as fetch:
                _download_asset("https://example.org/file", path, len(payload), checksum)
            self.assertEqual(fetch.call_args.args[0].get_header("Range"), "bytes=9-")
            self.assertEqual(path.read_bytes(), payload)

    def test_range_ignored_restarts_and_checksum_failures_are_not_installed(self):
        payload = b"a complete reference"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filings.parquet"
            path.with_name(path.name + ".part").write_bytes(b"a com")
            with patch("urllib.request.urlopen", return_value=Response(payload)):
                _download_asset("https://example.org/file", path, len(payload), hashlib.sha256(payload).hexdigest())
            self.assertEqual(path.read_bytes(), payload)
            rejected = path.with_name("rejected.parquet")
            with patch("urllib.request.urlopen", return_value=Response(payload)), self.assertRaisesRegex(ValueError, "checksum"):
                _download_asset("https://example.org/file", rejected, len(payload), "0" * 64)
            self.assertFalse(rejected.exists())
            self.assertFalse(rejected.with_name(rejected.name + ".part").exists())

    def test_latest_pins_assets_caches_downloads_and_skips_optional_companions(self):
        content = b"corrected reference"
        manifest = {"schema_version": 1, "version": "2026-09-30", "files": [
            asset("filings.parquet", content), asset("companies.parquet", b"companies", "companion", True)]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            requests = []

            def respond(request, **kwargs):
                requests.append(request.full_url)
                if request.full_url.endswith("manifest.json"):
                    return Response(json.dumps(manifest).encode())
                return Response(content)

            with patch("urllib.request.urlopen", side_effect=respond):
                bundle = fetch_reference(data_dir=root)
                again = fetch_reference(data_dir=root)
            self.assertEqual(bundle.version, "2026-09-30")
            self.assertEqual(bundle.filings, root / "submissions/references/2026-09-30/filings.parquet")
            self.assertEqual(again.filings, bundle.filings)
            self.assertFalse((bundle.directory / "companies.parquet").exists())
            self.assertEqual(sum(url.endswith("filings.parquet") for url in requests), 1)
            self.assertIn("/download/2026-09-30/filings.parquet", requests[1])
            self.assertEqual(DataPaths(root).reference().filings, bundle.filings)

    def test_unsafe_manifest_names_are_rejected(self):
        manifest = {"schema_version": 1, "version": "2026-09-30", "files": [asset("../filings.parquet", b"x")]}
        with self.assertRaisesRegex(ValueError, "filename"):
            validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
