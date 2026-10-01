"""Download a versioned reference and its evidence from public data releases."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request

from ._paths import DataPaths

DATA_REPOSITORY = "iangow/sec_submissions_data"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def validate_manifest(manifest):
    """Validate the version-1 data manifest before writing any local files."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported reference manifest schema")
    version = manifest.get("version")
    if not isinstance(version, str) or not _NAME.fullmatch(version) or version in {".", "..", "latest"}:
        raise ValueError("Invalid reference version")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Reference manifest has no files")
    seen = set()
    for asset in files:
        if not isinstance(asset, dict):
            raise ValueError("Invalid reference asset")
        name, size, checksum = asset.get("name"), asset.get("size_bytes"), asset.get("sha256")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in {".", "..", "manifest.json", "current.json"} or name in seen:
            raise ValueError("Unsafe or repeated reference filename")
        if type(size) is not int or size <= 0 or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Invalid reference size or checksum")
        if not isinstance(asset.get("role"), str) or type(asset.get("optional", False)) is not bool:
            raise ValueError("Invalid reference role or optional flag")
        seen.add(name)
    if sum(asset["role"] == "filings" for asset in files) != 1:
        raise ValueError("Reference must have exactly one corrected filings file")
    if any(asset.get("optional", False) for asset in files if asset["role"] == "filings"):
        raise ValueError("The corrected filings file cannot be optional")
    return manifest


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _download_asset(url, destination, size, checksum):
    if destination.exists():
        if destination.stat().st_size == size and _sha256(destination) == checksum:
            print(f"Cached: {destination.name}", flush=True)
            return
        raise ValueError(f"Cached file does not match its release: {destination}")
    partial = destination.with_name(destination.name + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > size:
            partial.unlink()
            offset = 0
        if offset == size:
            break
        headers = {"User-Agent": "sec-submissions reference downloader", "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                if status == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not match or int(match[1]) != offset or int(match[2]) != size - 1 or int(match[3]) != size:
                        raise ValueError("Download returned an inconsistent byte range")
                elif status == 200:
                    offset = 0
                else:
                    raise ValueError(f"Unexpected reference download status: {status}")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != size - offset:
                    raise ValueError("Download size does not match the manifest")
                last_report = time.monotonic()
                with partial.open("ab" if offset else "wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        if offset + len(chunk) > size:
                            raise ValueError("Download is larger than the manifest permits")
                        stream.write(chunk)
                        offset += len(chunk)
                        if time.monotonic() - last_report >= 2:
                            print(f"{destination.name}: {offset / 1024**2:,.0f}/{size / 1024**2:,.0f} MiB ({100*offset/size:.1f}%)", flush=True)
                            last_report = time.monotonic()
                    stream.flush()
                    os.fsync(stream.fileno())
            if offset != size:
                raise OSError(f"Incomplete reference download: {offset:,}/{size:,} bytes")
            break
        except (urllib.error.URLError, OSError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code not in {408, 429, 500, 502, 503, 504}:
                raise
            if attempt == 2:
                raise
            time.sleep(1)
    if _sha256(partial) != checksum:
        partial.unlink()
        raise ValueError(f"Reference checksum failed: {destination.name}")
    partial.replace(destination)
    print(f"Verified: {destination.name}", flush=True)


@dataclass(frozen=True)
class ReferenceBundle:
    """Local paths and metadata for one downloaded, pinned data release."""

    directory: Path
    manifest: dict

    @property
    def version(self):
        return self.manifest["version"]

    @property
    def filings(self):
        return next(self.directory / asset["name"] for asset in self.manifest["files"] if asset["role"] == "filings")

    def observations(self, kind):
        return tuple(self.directory / asset["name"] for asset in self.manifest["files"]
                     if asset["role"] == kind and (self.directory / asset["name"]).is_file())


def fetch_reference(output=None, version="latest", data_dir=None,
                    repository=DATA_REPOSITORY, companions=False):
    """Fetch a corrected reference, evidence, and audit artifacts with checksums.

    Files are stored under ``DATA_DIR/submissions/references/<version>``. The
    mutable latest manifest is resolved once; every asset URL then
    uses the concrete release tag. Interrupted transfers resume automatically.
    SEC identification and a GitHub login are not needed for public downloads.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository must be owner/name")
    if not isinstance(version, str) or not _NAME.fullmatch(version) or version in {".", ".."}:
        raise ValueError("Invalid requested reference version")
    suffix = "latest/download" if version == "latest" else f"download/{version}"
    request = urllib.request.Request(f"https://github.com/{repository}/releases/{suffix}/manifest.json",
                                     headers={"User-Agent": "sec-submissions reference downloader"})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("Reference manifest is unexpectedly large")
    manifest = validate_manifest(json.loads(content))
    if version != "latest" and manifest["version"] != version:
        raise ValueError("Requested and returned reference versions disagree")
    parent = Path(output).expanduser().resolve() if output is not None else DataPaths(data_dir).references
    directory = parent / manifest["version"]
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("This data release changed; use a fresh reference output directory")
    _write_json(manifest_path, manifest)
    selected = [asset for asset in manifest["files"] if companions or not asset.get("optional", False)]
    print(f"Reference {manifest['version']}: {sum(asset['size_bytes'] for asset in selected) / 1024**3:.2f} GiB; {directory}", flush=True)
    for asset in selected:
        url = f"https://github.com/{repository}/releases/download/{manifest['version']}/{asset['name']}"
        _download_asset(url, directory / asset["name"], asset["size_bytes"], asset["sha256"])
    _write_json(parent / "current.json", {"version": manifest["version"]})
    return ReferenceBundle(directory, manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Override the reference-cache parent directory")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--version", default="latest", help="Data release tag, or latest")
    parser.add_argument("--repository", default=DATA_REPOSITORY)
    parser.add_argument("--companions", action="store_true", help="Also download companies, addresses, tickers, former_names, and files")
    args = parser.parse_args()
    bundle = fetch_reference(args.output, args.version, args.data_dir, args.repository, args.companions)
    print(f"Previous filings: {bundle.filings}")
