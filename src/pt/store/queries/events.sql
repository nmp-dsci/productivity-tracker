-- Raw events view over the JSONL store. Explicit column types keep DuckDB from
-- inferring a different struct for `meta` per source; meta is read as JSON
-- and picked apart with json_extract where a rollup needs it.
CREATE OR REPLACE VIEW events AS
SELECT
  event_id, source, kind,
  ts::TIMESTAMPTZ AS ts,
  timezone($tz, ts::TIMESTAMPTZ)::DATE AS day,
  project, repo, branch, session_id, model,
  coalesce(tokens.input, 0)       AS tok_in,
  coalesce(tokens.output, 0)      AS tok_out,
  coalesce(tokens.cache_read, 0)  AS tok_cr,
  coalesce(tokens.cache_write, 0) AS tok_cw,
  coalesce(tokens.thinking, 0)    AS tok_think,
  coalesce(cost_usd, 0)           AS cost_usd,
  tools, "class" AS cls, meta
FROM read_json($glob, format = 'newline_delimited', union_by_name = true,
  columns = {
    event_id: 'VARCHAR', "schema": 'INTEGER', source: 'VARCHAR', kind: 'VARCHAR',
    ts: 'VARCHAR', project: 'VARCHAR', repo: 'VARCHAR', branch: 'VARCHAR',
    session_id: 'VARCHAR', model: 'VARCHAR',
    tokens: 'STRUCT(input BIGINT, output BIGINT, cache_read BIGINT, cache_write BIGINT, thinking BIGINT)',
    cost_usd: 'DOUBLE', tools: 'VARCHAR[]', "class": 'VARCHAR', meta: 'JSON'
  });
