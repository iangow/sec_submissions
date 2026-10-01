#!/usr/bin/env python3
"""Roll filings releases forward while retaining the current file's identity."""

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

import duckdb

from ._paths import DataPaths


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').digest()


def validate(candidate, current):
    with duckdb.connect() as con:
        schemas = [con.execute('DESCRIBE SELECT * FROM read_parquet(?)', [str(p)]).fetchall()
                   for p in (candidate, current) if p is not None]
        candidate_schema = {r[0]: r[1] for r in schemas[0]}
        if len(schemas) > 1 and any(candidate_schema.get(r[0]) != r[1] for r in schemas[1]):
            raise ValueError('Candidate drops or changes current columns')
        if dict((r[0],r[1]) for r in schemas[0]).get('acceptanceDateTime') != 'TIMESTAMP WITH TIME ZONE':
            raise ValueError('Candidate acceptanceDateTime must be timezone-aware')
        rows = con.execute('SELECT count(*) FROM read_parquet(?)', [str(candidate)]).fetchone()[0]
        if rows == 0:
            raise ValueError('Candidate is empty')
        return rows


def publish(candidate: Path | None = None, current: Path | None = None,
            previous: Path | None = None, archive: Path | None = None, data_dir=None):
    workspace = DataPaths(data_dir)
    candidate = workspace.candidate() if candidate is None else Path(candidate).expanduser().absolute()
    current = workspace.current if current is None else Path(current).expanduser().absolute()
    previous = current.with_name('filings_previous.parquet') if previous is None else Path(previous).expanduser().absolute()
    archive = current.parent/'archive' if archive is None else Path(archive).expanduser().absolute()
    if not candidate.is_file() or (current.exists() and not current.is_file()):
        raise ValueError('Candidate must exist and current must be a file path')
    paths = (candidate.resolve(),current.resolve(),previous.resolve())
    if len(set(paths)) != 3:
        raise ValueError('Candidate, current, and previous paths must differ')
    if (current.exists() and candidate.samefile(current)) or (previous.exists() and
        ((current.exists() and previous.samefile(current)) or previous.samefile(candidate))):
        raise ValueError('Release paths must not be links to the same file')
    if current.is_symlink() or previous.is_symlink():
        raise ValueError('Current and previous paths must not be symbolic links')
    rows = validate(candidate,current if current.exists() else None)
    candidate_digest = digest(candidate)
    if not current.exists():
        current.parent.mkdir(parents=True,exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=current.name+'.',suffix='.tmp',dir=current.parent)
        os.close(handle)
        temporary = Path(temporary)
        try:
            shutil.copyfile(candidate,temporary)
            if digest(temporary) != candidate_digest:
                raise OSError('Published bytes do not match the validated candidate')
            with temporary.open('rb') as installed:
                os.fsync(installed.fileno())
            # Linking the prepared file fails rather than overwriting a concurrently
            # installed first release. Subsequent updates retain the existing inode.
            os.link(temporary,current)
        finally:
            temporary.unlink(missing_ok=True)
        return rows, None
    previous.parent.mkdir(parents=True,exist_ok=True)
    archive.mkdir(parents=True,exist_ok=True)
    # Finish the backup before rotating releases or touching the current file.
    handle, temporary = tempfile.mkstemp(prefix=previous.name+'.',suffix='.tmp',dir=previous.parent)
    os.close(handle)
    temporary = Path(temporary)
    archived = None
    try:
        shutil.copyfile(current,temporary)
        with temporary.open('rb') as backup:
            os.fsync(backup.fileno())
        if previous.exists():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            archived = archive/f'{previous.stem}-{stamp}{previous.suffix}'
            if archived.exists():
                raise FileExistsError(archived)
            previous.rename(archived)
        temporary.replace(previous)
        inode = current.stat().st_ino
        try:
            with candidate.open('rb') as source, current.open('r+b') as destination:
                shutil.copyfileobj(source,destination)
                destination.truncate()
                destination.flush()
                os.fsync(destination.fileno())
            if digest(current) != candidate_digest:
                raise OSError('Published bytes do not match the validated candidate')
        except BaseException:
            # Restore interrupted writes without unlinking the shared file.
            with previous.open('rb') as source, current.open('r+b') as destination:
                shutil.copyfileobj(source,destination)
                destination.truncate()
                destination.flush()
                os.fsync(destination.fileno())
            raise
        if current.stat().st_ino != inode:
            raise RuntimeError('Current file identity changed during publication')
    finally:
        temporary.unlink(missing_ok=True)
    return rows, archived


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,help='Default: latest local candidate')
    parser.add_argument('--current',type=Path,help='Default: DATA_DIR/submissions/filings.parquet')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--archive-dir',type=Path)
    return parser


def main():
    args = build_parser().parse_args()
    workspace = DataPaths(args.data_dir)
    current = workspace.current if args.current is None else args.current.expanduser().absolute()
    previous = args.previous or current.with_name('filings_previous.parquet')
    archive = args.archive_dir or current.parent/'archive'
    updating = current.exists()
    rows, archived = publish(args.candidate,current,
                             previous.expanduser().absolute(),archive.expanduser().absolute(),
                             data_dir=args.data_dir)
    print(f'Published {rows:,} rows to {current}')
    if updating:
        print(f'Previous release: {previous}')
    if archived:
        print(f'Archived older previous release: {archived}')
    print('Verified candidate SHA-256; existing current-file identity is retained on updates.')


if __name__ == '__main__':
    main()
