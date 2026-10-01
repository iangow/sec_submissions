"""Small shared utilities kept private to the package."""

import hashlib
from pathlib import Path


def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()
