"""Public Python API for processing and collecting SEC submissions data."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ._process import process as _process
from .audit import audit as _audit
from .live_json import collect_live_json as _collect_live_json
from .sgml import collect_sgml as _collect_sgml


def process(raw, previous, output, cache_dir=None, memory_limit="8GB",
            sgml_observations=(), live_observations=()):
    """Create a corrected candidate Parquet and a separate diagnostics archive.

    Existing outputs are never overwritten. The diagnostic directory is named
    from the candidate stem, for example ``filings_checks``.
    """
    paths = [Path(value).expanduser().resolve() for value in (raw, previous, output)]
    cache = None if cache_dir is None else Path(cache_dir).expanduser().resolve()
    return _process(*paths, cache, memory_limit,
                    tuple(Path(p).expanduser().resolve() for p in sgml_observations),
                    tuple(Path(p).expanduser().resolve() for p in live_observations))


def collect_live_json(filings, raw, output, since_date=date(2024, 1, 1),
                      sample_blocks=None, seed=20261001, workers=8, rate=5,
                      user_agent=None, resume=False):
    """Collect live JSON for unresolved blocks, freezing the selected block set."""
    return _collect_live_json(filings, raw, output, since_date, sample_blocks,
                              seed, workers, rate, user_agent, resume)


def collect_sgml(queue, output, workers=8, rate=5, max_attempts=2,
                 user_agent=None, resume=False):
    """Collect SGML headers for a supplied accession queue into Parquet."""
    return _collect_sgml(queue, output, workers, rate, max_attempts,
                         user_agent, resume)


def audit(filings, output, sample_size=10_000, seed=20261001, cache=None,
          workers=8, rate=5, user_agent=None, resume=False):
    """Freeze and audit a random filing-row sample without changing predictions."""
    return _audit(filings, output, sample_size, seed, cache, workers,
                  rate, user_agent, resume)
