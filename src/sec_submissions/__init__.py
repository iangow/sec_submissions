"""Evidence-based processing of SEC EDGAR submissions timestamps."""

from .download import download_submissions
from .extract_filings import extract as extract_submissions
from .http import resolve_user_agent, set_user_agent
from .publish_filings import publish
from .reference import make_previous
from .workflow import audit, collect_live_json, collect_sgml, process
from ._paths import data_directory, raw_data_directory
from .reference_data import fetch_reference, ReferenceBundle

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "audit",
    "collect_live_json",
    "collect_sgml",
    "download_submissions",
    "data_directory",
    "raw_data_directory",
    "fetch_reference",
    "ReferenceBundle",
    "extract_submissions",
    "make_previous",
    "process",
    "publish",
    "resolve_user_agent",
    "set_user_agent",
]
