# Hosted grounding contract and diagnostics

The first successful Claude measurement accepted 3/5 normal documents. The other
two passed JSON/schema validation and failed grounding. The saved artifact does
not contain field-level grounding reasons, so their exact causes remain unknown.
The frozen dataset and historical measurements must remain unchanged.

The v2 request gave a schema and asked for labeled quotes. It did not
explain several rules enforced locally: Korean date-only publication values use
KST, list values retain their original language and order, qualified requirements
are omitted, and evidence quotes must be exact complete spans on the given page.
The v3 request now explains these rules. Validation criteria remain unchanged.
The code change alone was not evidence of improved accuracy; the subsequent
external measurement is described below.

New evaluations will record `grounding_issues`: deduplicated field/code pairs
produced by the validator. Fields are restricted to known business fields (or
null for document-level issues); codes identify missing evidence, a quote/page
mismatch, an unsupported value, contradictory claims, a qualified requirement,
or evidence for an absent/unknown field. No proposed values, quotes, checksums,
arbitrary field names, provider text or validation exception text belong in this
diagnostic. Existing schema/response/execution diagnostics remain separate.

The request identity must change with the actual system prompt, including its
JSON schema and grounding version, so cached/persisted v2 requests cannot be
reused for the clarified contract. The document remains untrusted user data.
Keep endpoint-specific JSON mode, strict parsing, token accounting and retry
bounds unchanged. No repair calls or new paid workflow triggers are added.

Verification requires privacy and grounding regressions, request identity tests,
the complete CI/release contract, and a separate review before merge. These passed.
The [subsequent v3 measurement](hosted-evaluation-success.md), run 36016974477,
accepted 5/5 normal cases (30/30 fields), versus 3/5 (18/30) in the preserved v2 run.
It retained usage for all rejected responses. Total tokens and hosted-all p95
increased. Each version has one run, so neither repeatability nor a causal
prompt effect has been established. Gated unstructured prose was still rejected
for evidence absent from the page and unsupported values.

The deterministic baseline already obtains 30/30 on this synthetic dataset.
Neither this change nor a higher hosted score would establish incremental LLM
utility on real procurement documents.
