-- One row per agent session: the unit the Agents view draws as a Gantt bar and
-- the tier-2 tagger labels. Class is the token-weighted majority of messages.
WITH msgs AS (
  SELECT * FROM events
  WHERE source IN ('claude_code', 'codex') AND kind IN ('assistant_message', 'token_count', 'prompt', 'session_start')
), cls AS (
  SELECT session_id, cls, sum(tok_out) AS w
  FROM msgs WHERE cls <> 'unknown' GROUP BY 1, 2
), best AS (
  SELECT session_id, arg_max(cls, w) AS cls FROM cls GROUP BY 1
)
SELECT
  m.session_id, any_value(m.source) AS source,
  arg_max(m.project, m.ts) AS project,
  arg_max(m.branch, m.ts)  AS branch,
  min(m.ts) AS first_ts, max(m.ts) AS last_ts,
  timezone($tz, min(m.ts))::DATE AS day,
  date_diff('second', min(m.ts), max(m.ts)) AS seconds,
  sum(CASE WHEN m.kind IN ('assistant_message', 'token_count') THEN 1 ELSE 0 END) AS messages,
  sum(CASE WHEN m.kind = 'prompt' THEN 1 ELSE 0 END) AS prompts,
  sum(m.tok_in) AS tok_in, sum(m.tok_out) AS tok_out, sum(m.tok_cr) AS tok_cr,
  sum(m.tok_cw) AS tok_cw, sum(m.cost_usd) AS cost_usd,
  coalesce(any_value(b.cls), 'unknown') AS cls,
  list_distinct(list_filter(list(m.model), x -> x IS NOT NULL)) AS models,
  list_distinct(flatten(list(m.tools))) AS tools,
  sum(CASE WHEN json_extract_string(m.meta, '$.subagent') = 'true' THEN 1 ELSE 0 END) AS subagent_msgs
FROM msgs m LEFT JOIN best b USING (session_id)
WHERE m.session_id IS NOT NULL
GROUP BY m.session_id
ORDER BY first_ts;
