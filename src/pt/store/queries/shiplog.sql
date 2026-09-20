-- Things that left the laptop (or count as delivered): merged PRs, deploys,
-- CI runs, review pages, eval runs, gate runs. Commits are deliberately not
-- here — they are effort, not delivery.
SELECT
  ts, day, source, kind, project, repo, branch,
  coalesce(
    json_extract_string(meta, '$.title'),
    json_extract_string(meta, '$.run_id'),
    json_extract_string(meta, '$.service'),
    json_extract_string(meta, '$.name')
  ) AS title,
  coalesce(json_extract_string(meta, '$.status'), json_extract_string(meta, '$.conclusion')) AS status,
  json_extract_string(meta, '$.url') AS url,
  json_extract(meta, '$.number')::INTEGER AS number
FROM events
WHERE (source = 'github' AND kind IN ('pr_merged', 'pr_opened', 'workflow_run', 'deployment_status', 'release'))
   OR (source = 'aws' AND kind IN ('apprunner_deploy', 'ecr_push'))
   OR (source = 'lavish' AND kind = 'page_created')
   OR (source = 'evals' AND kind = 'run')
   OR (source = 'nomistakes' AND kind = 'gate_run')
ORDER BY ts DESC;
