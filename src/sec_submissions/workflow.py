"""Public Python API for processing and collecting SEC submissions data."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ._process import process as _process
from .audit import audit as _audit
from .live_json import collect_live_json as _collect_live_json
from .sgml import collect_sgml as _collect_sgml
from ._paths import DataPaths


def process(raw=None, previous=None, output=None, cache_dir=None, memory_limit="8GB",
            sgml_observations=(), live_observations=(), data_dir=None):
    """Create a corrected candidate Parquet and a separate diagnostics archive.

    Existing outputs are never overwritten. The diagnostic directory is named
    from the candidate stem, for example ``filings_checks``.
    """
    workspace = DataPaths(data_dir)
    use_defaults = previous is None
    raw = Path(raw).expanduser().resolve() if raw is not None else workspace.raw()
    previous = workspace.previous() if previous is None else previous
    output = workspace.new_candidate(raw) if output is None else output
    if use_defaults:
        if cache_dir is None:
            try:
                bundle = workspace.reference()
                sgml_observations = (*sgml_observations, *bundle.observations("sgml"))
                live_observations = (*live_observations, *bundle.observations("live"))
            except FileNotFoundError:
                pass
        sgml_observations = (*sgml_observations, *workspace.observations("sgml"))
        live_observations = (*live_observations, *workspace.observations("live"))
    paths = [Path(value).expanduser().resolve() for value in (raw, previous, output)]
    cache = None if cache_dir is None else Path(cache_dir).expanduser().resolve()
    return _process(*paths, cache, memory_limit,
                    tuple(Path(p).expanduser().resolve() for p in sgml_observations),
                    tuple(Path(p).expanduser().resolve() for p in live_observations))


def collect_live_json(filings=None, raw=None, output=None, since_date=date(2024, 1, 1),
                      sample_blocks=None, seed=20261001, workers=8, rate=5,
                      user_agent=None, resume=False, data_dir=None):
    """Collect live JSON for unresolved blocks, freezing the selected block set."""
    workspace = DataPaths(data_dir)
    raw = Path(raw).expanduser().resolve() if raw is not None else workspace.raw()
    filings = workspace.candidate(raw.parent) if filings is None else filings
    output = raw.parent / "evidence" / "live-json" if output is None else output
    return _collect_live_json(filings, raw, output, since_date, sample_blocks,
                              seed, workers, rate, user_agent, resume)


def collect_sgml(queue, output=None, workers=8, rate=5, max_attempts=2,
                 user_agent=None, resume=False, data_dir=None):
    """Collect SGML headers for a supplied accession queue into Parquet."""
    if output is None:
        output = DataPaths(data_dir).submissions / "evidence" / "sgml"
    return _collect_sgml(queue, output, workers, rate, max_attempts,
                         user_agent, resume)


def audit(filings=None, output=None, sample_size=10_000, seed=20261001, cache=None,
          workers=8, rate=5, user_agent=None, resume=False, data_dir=None):
    """Freeze and audit a random filing-row sample without changing predictions."""
    filings = DataPaths(data_dir).candidate() if filings is None else Path(filings).expanduser().resolve()
    output = filings.parent / "audits" / filings.stem if output is None else output
    return _audit(filings, output, sample_size, seed, cache, workers,
                  rate, user_agent, resume)
