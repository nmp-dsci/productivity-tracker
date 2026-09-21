-- One row per day × project × source × kind × class × model. Every view in the
-- app is a slice of this table; the demo image bakes it as parquet.
WITH labels AS (
  -- tier-2 labels (pt tag) are events too; the latest one per session wins
  SELECT session_id, arg_max(cls, ts) AS cls FROM events WHERE kind = 'label' GROUP BY 1
), majority AS (
  -- token-weighted majority class per session, used for messages that carry
  -- no path/command signal of their own
  SELECT session_id, arg_max(cls, w) AS cls FROM (
    SELECT session_id, cls, sum(tok_out) + count(*) AS w FROM events
    WHERE session_id IS NOT NULL AND cls <> 'unknown' AND kind <> 'label' GROUP BY 1, 2
  ) GROUP BY 1
), ev AS (
  SELECT e.* REPLACE (coalesce(l.cls, nullif(e.cls, 'unknown'), m.cls, 'unknown') AS cls)
  FROM events e LEFT JOIN labels l USING (session_id) LEFT JOIN majority m USING (session_id)
  WHERE e.kind <> 'label'
)
SELECT
  day, project, source, kind, cls,
  CASE WHEN source IN ('claude_code', 'codex') THEN model END AS model,
  -- branch only matters for git activity; keeping it off agent rows caps cardinality
  CASE WHEN source IN ('git_local', 'github') THEN branch END AS branch,
  count(*)                          AS n,
  count(DISTINCT session_id)        AS sessions,
  sum(tok_in)                       AS tok_in,
  sum(tok_out)                      AS tok_out,
  sum(tok_cr)                       AS tok_cr,
  sum(tok_cw)                       AS tok_cw,
  sum(tok_think)                    AS tok_think,
  sum(cost_usd)                     AS cost_usd,
  sum(seconds)                      AS seconds,
  sum(coalesce(json_extract(meta, '$.insertions')::BIGINT, 0)) AS insertions,
  sum(coalesce(json_extract(meta, '$.deletions')::BIGINT, 0))  AS deletions,
  sum(CASE WHEN json_extract_string(meta, '$.subagent') = 'true' THEN 1 ELSE 0 END) AS subagent_msgs
FROM ev
GROUP BY ALL
ORDER BY day, project, source, kind;
