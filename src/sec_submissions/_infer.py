"""Infer timezone interpretations from consistent, accession-level anchors."""


def infer(con, sgml_file_anchors=False, versioned=False):
    version_column = "retrieved_at observation_version," if versioned else ""
    version_group = ",retrieved_at" if versioned else ""
    version_join = "AND l.retrieved_at IS NOT DISTINCT FROM r.observation_version" if versioned else ""
    sgml_version_join = "AND l.retrieved_at IS NOT DISTINCT FROM s.retrieved_at" if versioned else ""
    extra_evidence = f"""
        UNION ALL
        SELECT l.source_url,l.accession_number,l.retrieved_at,
               CASE WHEN (try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'UTC')=s.instant THEN 'utc'
                    WHEN (try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'America/New_York')=s.instant THEN 'eastern'
                    ELSE 'contradiction' END
        FROM live l JOIN sgml_file_anchors s
          ON l.source_url=s.source_url AND l.accession_number=s.accession_number
          {sgml_version_join}
    """ if sgml_file_anchors else ""
    con.execute(f"""
        CREATE TABLE anchors AS
        SELECT accession, min(instant) instant FROM anchor_inputs
        GROUP BY accession HAVING count(DISTINCT instant)=1;
        CREATE TABLE file_evidence AS
        SELECT l.source_url,l.accession_number,l.retrieved_at,
               CASE WHEN (try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'UTC')=a.instant THEN 'utc'
                    WHEN (try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'America/New_York')=a.instant THEN 'eastern'
                    ELSE 'contradiction' END interpretation
        FROM live l JOIN anchors a ON a.accession=l.accession_number
        {extra_evidence};
        CREATE TABLE file_rules AS
        SELECT source_url,{version_column}min(interpretation) interpretation,
               count(DISTINCT accession_number) evidence_count,
               min(retrieved_at) first_observed,max(retrieved_at) last_observed
        FROM file_evidence GROUP BY source_url{version_group}
        HAVING count(DISTINCT interpretation)=1 AND min(interpretation)<>'contradiction';
        CREATE TABLE file_candidates AS
        SELECT l.source_url,l.accession_number,
               CASE WHEN r.interpretation='utc'
                 THEN try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'UTC'
                 ELSE try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'America/New_York'
               END instant
        FROM live l JOIN file_rules r ON l.source_url=r.source_url {version_join};
        CREATE TABLE rejected_accessions AS
        SELECT accession_number FROM file_candidates GROUP BY 1
        HAVING count(DISTINCT instant)<>1 OR count(*) FILTER(WHERE instant IS NULL)>0
        UNION
        SELECT c.accession_number FROM file_candidates c JOIN validation v
          ON v.accession=c.accession_number WHERE c.instant IS DISTINCT FROM v.instant;
        CREATE TABLE inferred_overrides AS
        SELECT accession_number,min(instant) instant,min(source_url) source_url
        FROM file_candidates WHERE accession_number NOT IN (SELECT accession_number FROM rejected_accessions)
        GROUP BY accession_number;
    """)
