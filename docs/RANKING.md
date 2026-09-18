# Eligibility contract

Hard eligibility runs before relevance scoring. `evaluate_eligibility` returns known hard failures separately from review warnings. `allows_recommendation` is true only when no hard failure and no unresolved warning exists, so relevance scoring cannot promote an ineligible or uncertain opportunity with a score.

Regions, certifications, amount/currency, and company excluded keywords are deterministic. Amount bounds use the profile's nullable ISO-3 `contract_currency`; missing or different currencies create a review warning and no numeric comparison or FX conversion. Excluded keywords are an explicit company preference and are matched only against trusted upstream or validated extraction title, description, body, and participation-constraint claims. Arbitrary participation prose is not interpreted as a legal exclusion.

`materialize_eligibility(session, company_profile_id, opportunity_version_id)` persists an immutable result revision identified by the ruleset, a profile-input fingerprint, and a trusted opportunity-input fingerprint. The authoritative extraction is the validated row whose key exactly equals `extraction_identity` for the current document bundle and configured extractor; UUID order is never treated as chronology. Replaying identical inputs returns the existing row. Profile edits, normalized-version changes, or a newly configured and validated extraction identity create another revision while older rows remain historical.

Money is atomic: amount and currency must both come from the normalized opportunity snapshot or both come from that one trusted extraction. A partial source is not completed from another source. Normalized-derived fields carry normalized-version provenance; a raw JSON pointer is recorded only when that raw field actually backs the usable normalized value.

`reconcile_eligibility_results` is registered with the ARQ worker and scheduler. It ensures the clearly labeled `ProcureDelta Synthetic Demo Company` profile exists, then materializes all current opportunity versions for all profiles. The synthetic profile uses KRW amount bounds.

Company profile CRUD is available at `GET`, `POST`, and `PATCH /api/v1/company-profile`. Ownership comes from the replaceable `get_current_owner_id` dependency. The product API uses the demo session boundary; request bodies cannot select another owner.

## Deterministic ranking baseline

The `deterministic-baseline-v1` policy scores lexical relevance (25%), capability overlap
(25%), category match (20%), comparable-currency amount fit (15%), and recency/deadline
utility (15%). Its initial recommendation threshold is 0.60. These are documented heuristic
weights, not measured accuracy claims; frozen ranking fixtures are used only as regression evidence.

Hard failures, critical eligibility warnings, and expired deadlines block recommendation
regardless of feature or optional semantic score. Unknown or cross-currency amounts score zero
and remain visible in the explanation. Currency conversion is never inferred.

Pure ranking requires an explicit timezone-aware `as_of`. Historical callers use an exact
epoch. Scheduled materialization scores at the actual decision time and reuses an unchanged
input during one UTC day. The epoch changes immediately when inputs change or a deadline
expires. Smooth recency utility therefore refreshes daily, while deadline closure and new input
revisions invalidate reuse immediately. A reused row retains its original decision timestamp.

The optional semantic interface is disabled by default, permits at most 20 candidates, and
contributes at most 20% when explicitly enabled. It requires neither a paid provider nor a
vector database and cannot override eligibility.
