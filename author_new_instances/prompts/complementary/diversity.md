You are auditing the DIVERSITY of a set of finished **complementary** dataset
instances. Read `./instances.jsonl` (one JSON object per line, each with:
`instance_id`, `repo`, `subsystem`, `mutex_type`, `diversity_mechanism`,
`shared_artifact`, `agentA_problem_statement`, `agentB_problem_statement`).

Your job is to judge whether the set is well spread or over-concentrated, and to
say what to avoid next. Write your findings to `./DIVERSITY_report.json` only.

For each instance, assign:
- `capability_type` — the kind of shared interface A and B must agree on, one of:
  encoding | serialization_decode | parsing | config | caching | transport_queue |
  data_retrieval | ui_merge | api_design | other
- `code_layer` — coarse layer, one of: util_helper | db_adapter | api_handler |
  ui_component | cli | config | network_http | serialization | data_model |
  auth_permission | other

Then compute distributions and flag concentration:
- counts by `repo`, by `(repo, subsystem)`, by `capability_type`, by `code_layer`.
- **flag** any `(repo, subsystem)` pair that repeats, any repo that exceeds ~1/4 of
  the set, any single `capability_type` that exceeds ~1/3 of the set (encoding and
  config tend to dominate — watch them), and any `code_layer` that dominates.
- `avoid_next`: concrete buckets (repos, subsystems, capability types, layers) the
  next batch should steer AWAY from to rebalance.

## Output — write EXACTLY `./DIVERSITY_report.json`
```json
{
  "n": 0,
  "labels": [{"instance_id": "...", "repo": "...", "subsystem": "...",
              "capability_type": "...", "code_layer": "..."}],
  "distribution": {"by_repo": {}, "by_repo_subsystem": {}, "by_capability_type": {}, "by_code_layer": {}},
  "concentration_flags": ["short bullet per problem, or empty"],
  "avoid_next": {"repos": [], "subsystems": [], "capability_types": [], "code_layers": []},
  "summary": "2-3 sentences: is the set diverse, and the main thing to fix next"
}
```
Do not modify any other file. Base every judgement on the instances given.
