-- One row per day × project × source × kind × class × model. Every view in the
-- app is a slice of this table; the demo image bakes it as parquet.
WITH session_cls AS (
  -- token-weighted majority class per session, used for messages that carry
  -- no path/command signal of their own
  SELECT session_id, arg_max(cls, w) AS cls FROM (
    SELECT session_id, cls, sum(tok_out) + count(*) AS w FROM events
    WHERE session_id IS NOT NULL AND cls <> 'unknown' GROUP BY 1, 2
  ) GROUP BY 1
), ev AS (
  SELECT e.* REPLACE (coalesce(nullif(e.cls, 'unknown'), s.cls, 'unknown') AS cls)
  FROM events e LEFT JOIN session_cls s USING (session_id)
)
SELECT
  day, project, source, kind, cls,
  CASE WHEN source IN ('claude_code', 'codex') THEN model END AS model,
  count(*)                          AS n,
  count(DISTINCT session_id)        AS sessions,
  sum(tok_in)                       AS tok_in,
  sum(tok_out)                      AS tok_out,
  sum(tok_cr)                       AS tok_cr,
  sum(tok_cw)                       AS tok_cw,
  sum(tok_think)                    AS tok_think,
  sum(cost_usd)                     AS cost_usd,
  sum(coalesce(json_extract(meta, '$.insertions')::BIGINT, 0)) AS insertions,
  sum(coalesce(json_extract(meta, '$.deletions')::BIGINT, 0))  AS deletions,
  sum(CASE WHEN json_extract_string(meta, '$.subagent') = 'true' THEN 1 ELSE 0 END) AS subagent_msgs
FROM ev
GROUP BY ALL
ORDER BY day, project, source, kind;
