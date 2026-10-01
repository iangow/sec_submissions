# Python API

::: sec_submissions.fetch_reference

::: sec_submissions.ReferenceBundle

::: sec_submissions.data_directory

::: sec_submissions.raw_data_directory

The command-line interface and Python functions share the same implementation.
Explicit paths override the documented directory defaults. Otherwise the
functions use `DATA_DIR` and `RAW_DATA_DIR`, including values in the local `.env`.

## Core functions

::: sec_submissions.download_submissions

::: sec_submissions.extract_submissions

::: sec_submissions.make_previous

::: sec_submissions.process

## Evidence and release

::: sec_submissions.collect_live_json

::: sec_submissions.collect_sgml

::: sec_submissions.audit

::: sec_submissions.publish

## SEC user agent

::: sec_submissions.resolve_user_agent

::: sec_submissions.set_user_agent
