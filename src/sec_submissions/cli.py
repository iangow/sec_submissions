"""Command-line entry point for the ``sec-submissions`` package."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from . import _process
from .audit import main as audit_main
from .download import main as download_main
from .extract_filings import main as extract_main
from .http import resolve_user_agent, set_user_agent
from .live_json import main as live_json_main
from .publish_filings import main as publish_main
from .reference import make_previous
from .sgml import main as sgml_main


def main():
    parser = argparse.ArgumentParser(prog="sec-submissions", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    handlers = {
        "download": download_main,
        "extract": extract_main,
        "collect-live-json": live_json_main,
        "collect-sgml": sgml_main,
        "process": _process.main,
        "audit": audit_main,
        "publish": publish_main,
    }
    for command, help_text in (
        ("download", "Download a dated submissions.zip snapshot"),
        ("extract", "Extract a submissions ZIP to raw Parquet tables"),
        ("collect-live-json", "Collect live JSON observations for unresolved blocks"),
        ("collect-sgml", "Collect SGML observations for an explicit accession queue"),
        ("process", "Create a corrected candidate and diagnostics"),
        ("audit", "Audit a frozen random sample against SGML"),
        ("publish", "Validate and replace an existing local release in place"),
        ("reference", "Create the one-time 2024 bootstrap Parquet"),
        ("configure-user-agent", "Set or resolve SEC request identification"),
    ):
        subcommands.add_parser(command, help=help_text, add_help=False)
    args, remainder = parser.parse_known_args()
    if args.command == "reference":
        reference_parser = argparse.ArgumentParser(prog="sec-submissions reference")
        reference_parser.add_argument("--raw", required=True)
        reference_parser.add_argument("--output", required=True)
        options = reference_parser.parse_args(remainder)
        print(make_previous(options.raw, options.output))
        return
    if args.command == "configure-user-agent":
        configure = argparse.ArgumentParser(prog="sec-submissions configure-user-agent")
        configure.add_argument("--user-agent")
        configure.add_argument("--scope", choices=("session", "project", "user"), default="user")
        options = configure.parse_args(remainder)
        if options.user_agent:
            print(set_user_agent(options.user_agent, options.scope))
        else:
            print(resolve_user_agent(prompt=True))
        return
    sys.argv = [sys.argv[0], *remainder]
    handlers[args.command]()
