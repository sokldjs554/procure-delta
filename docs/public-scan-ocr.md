# Original Korean public-scan diagnostic

On 2026-09-24, two original image-only procurement PDFs from the official
농림수산업자신용보증기금 site were evaluated with the configured **worker OCR adapter**.
The original files were neither cropped nor rewritten. Each PDF has four pages;
all eight pages were recognized, and only the two first pages had frozen
annotations and were scored. This is a local diagnostic, not a full worker/DB
run, a representative corpus, or a production-quality claim.

The first two runs exposed a memory failure. After a runtime resource-lifetime
fix, two repeats completed both PDFs. Recognition anchors were **4/8** and
validated structured fields were **0/6** in each completed run. Completion of
recognition does not mean extraction quality passed.

## Sources and frozen annotations

The [manifest](../data/eval/public_scan_manifest.json) records the original URLs,
SHA-256 values, annotation page, exact expected values, selection limits and
acquisition failures. The first pages were visually inspected and annotated
before recognition; a subsequent independent code/source review checked those
annotations. This is not a separately authored annotation corpus or a holdout.

| Original official attachment | PDF size | Pages | Annotated fields |
| --- | ---: | ---: | --- |
| [2020년 농신보 부실채권 매각자문사 선정](https://nongshinbo.nonghyup.com/user/boardList.do?boardId=4482573&boardSeq=5075697&command=view&id=&page=1) | 89,166 bytes | 4 | title, buyer_name, procurement_type |
| [디지털 농신보 마스터플랜 연구용역](https://nongshinbo.nonghyup.com/user/boardList.do?boardId=4482573&boardSeq=5071891&categoryDepth=&categoryId=&column=&command=view&id=&page=1&parent=&search=&siteId=nongshinbo) | 5,306,594 bytes | 4 | title, buyer_name, procurement_type |

Both attachments are named `입찰공고(스캔).pdf` by the issuer. Every page has zero
native text characters, a full-page raster, visible contrast and no vector or
annotation overlays. Creator/producer metadata is `DocuCentre-V C2265`. These
signals and the visible scanner defects support scan origin; physical scanning
history is not independently attested. Both are 2020 notices from the same
issuer and similar template, so they do not demonstrate layout diversity.

Titles exclude their enclosing quotation marks. The buyer is the explicitly
named managing/contracting institution 농협중앙회. `services` is a semantic category
annotation supported by advisory/research scope, not a literal English label.
Four recognition anchors per page cover title, buyer, budget text and notice ID.
Personal names and contact details are not annotated or published. The two G2B
candidates excluded during acquisition remain in the manifest: one exceeded the
existing 10 MiB budget and the other never downloaded completely. Neither was
silently removed after an OCR score; neither received an OCR measurement. This
experiment is not evidence of a completed G2B attachment run.

## Path and metric boundaries

`run_scan_ocr_eval.py` checks all source hashes and preflight conditions before
starting the real adapter. It passes unchanged whole-PDF bytes, with no fixture
key, through native parsing, `needs_ocr` routing and `TesseractOcrAdapter`.
A small 36 dpi inspection render only checks visible raster content; it is not
the image used for recognition. The worker's own full-page OCR uses `kor+eng`,
300 dpi, at most 10 pages, 12 million rendered pixels/page, a 40-second child
deadline, and 512 MiB address space. Models, DPI, extraction rules and acceptance
thresholds were not tuned on this sample.

Only the pre-annotated first-page text is passed to the existing deterministic
extractor and evidence validator. Consequently, `downstream_valid` here is
**page-scoped validation**, not acceptance of the entire PDF by a worker job.
No hosted model is called and no results are persisted to PostgreSQL.

Anchor recall uses the existing NFC/whitespace normalization and numeric
boundaries while retaining punctuation. It is specified-string recall, not
character accuracy, word accuracy or field accuracy. Trusted fields require an
accepted complete output; a rejected output earns no trusted fields. Native
control text is empty and scores 0/8 anchors and 0/6 trusted fields. If any PDF
fails, the aggregate is `incomplete`, accuracy is `null`, all six expected fields
and eight anchors stay in the denominator, and the script exits nonzero.

## Failure and resource-lifetime fix

The preserved [v1 first run](../artifacts/evaluation/public-scan-v1-failed.json)
and [v1 repeat](../artifacts/evaluation/public-scan-v1-failed-repeat.json) each
recognized the small PDF but failed the digital notice with `RuntimeError`.
Their aggregate accuracy remains `null`; no partial-success score is published.
Their original stock limitation sentence, "All pages recognized", describes the
intended scope and is not a success assertion: per-case statuses are authoritative.
The generator now says pages are requested for recognition; historical artifacts
and their provenance remain unchanged.

A bounded local diagnostic reproduced memory allocation failure on the second
page of the high-resolution original. Its embedded scans are 4,964 × 7,020 RGB
pixels, despite the smaller 300 dpi recognition output. MuPDF retained decoded
images between pages. The original also completed after clearing that cache.
A generated regression with three distinct dense 600 dpi RGB pages exposed the
additional lifetime of the preceding native TextPage while allocating the next.
Clearing the cache alone did not pass that regression.

The final fix clears MuPDF's cache before each page and releases each TextPage
after copying its text. No input, output, time, memory or resolution limit was
increased. The [cache API](https://pymupdf.readthedocs.io/en/latest/tools.html#Tools.store_shrink)
operates inside the existing isolated child. Both runtime identity and provider
version advance to `pymupdf-ocr-v2`, so prior durable OCR results cannot masquerade
as the new runtime. This is a development fix informed by the diagnostic, not a
held-out robustness result, and it does not guarantee every in-budget PDF fits
within the process limit.

The dense regression failed before the fix with a memory-related invalid reply,
not a timeout. The complete local runtime test file then passed **13 tests in
23.52 seconds**; the dense case took 13.19 seconds including PDF generation,
startup probe and recognition. Its measured address-space peak was close to the
limit, so CI on its own runtime remains a required gate. These generated pages
are regression inputs, separate from the two real public sources.

## Completed measurements

[First v2 run](../artifacts/evaluation/public-scan.json) and
[repeat v2 run](../artifacts/evaluation/public-scan-repeat.json) retain the same
source, dataset, model, runtime identity and OCR-text hashes. Timings are separate
observations; they cover whole-PDF recognition including child setup, excluding
the earlier startup probe, preflight and downstream scoring. Two observations
are not a latency distribution or cloud throughput benchmark.

| Input | v2 run 1 | v2 run 2 | First-page anchors | Trusted fields |
| --- | ---: | ---: | ---: | ---: |
| NPL advisory notice, 4 pages | 22.54s | 18.59s | 2/4 | 0/3 |
| Digital research notice, 4 pages | 23.60s | 19.58s | 2/4 | 0/3 |
| Both original PDFs | 8 pages processed | 8 pages processed | **4/8** | **0/6** |

In both pages, the title and budget anchors match; buyer and notice-number
anchors do not. The deterministic extractor proposes none of the three expected
fields, and the validator accepts neither page. Runtime completion improved,
but the current extraction path still fails this real scan sample. The 18/18
Korean synthetic result remains a separate historical regression and is not
replaced or generalized by this result.

The completed runs used clean source commit
`f8f958247fb43f5998c11d1d7c4b896b589ffd6e`, PyMuPDF/MuPDF 1.28.2 and Python 3.12.14.
Dataset SHA-256 is
`251804ff21e4cf8347873d147b5f77e2f9006c7c36c8bdf2d10d45006f073700`;
source-code SHA-256 is
`063be20ec10d4809e71124f3fdbd038478d9ffad54e2e15843fd5ad9a0d5dab7`.
The v1 artifacts retain their original local commit `8b0ef04...`; published
baseline commit `4765bc2fbe04862e421aabbfcb6cddf3ac6d6f82` has the identical full
tree (`04110b4d2ed5ef8a0237b8dcfd04fb2d461eee85`). Old provenance was not rewritten.
Model content hashes and environment details are in every artifact.

## Why completed recognition still earns zero trusted fields

A [diagnostic rerun](../artifacts/evaluation/public-scan-diagnostics.json) on clean
commit `6fda858d632b654ae471691ae84a3c9755cb25e8` adds the rejection stage without
changing the runtime, extractor, validator, annotations or scoring. Both PDFs
completed again (22.23s and 21.54s). Dataset/model/runtime identity and all
recognized-text hashes match the earlier completed runs; anchors remain **4/8**
and trusted fields **0/6**.

Both first pages have `rejection_stage: schema` and `schema_error_fields` of
`buyer_name`, `procurement_type`, and `title`. The deterministic proposal is
missing those required fields. `grounding_issues` is empty because evidence
validation is reached only after a valid schema; it does **not** mean these
documents passed grounding. Native empty-text controls fail at the same stage.

Private inspection of the recognized first-page text and original images
separates the likely contributors:

- The title's label, colon and value are split across OCR lines, with checkbox
  bullets misrecognized. The current explicit-label extractor does not accept
  that arrangement. An anchor can match after whitespace removal while no
  structured title is proposed.
- The small header names the buyer in the image, but the expected buyer anchor
  does not match the OCR text. Even perfect recognition would still need an
  explicitly supported interpretation of the managing-institution header.
- The expected `services` category is a semantic annotation from the scope of
  work. It is not an explicit supported category label on these pages.

These are development diagnoses, not evidence that the original documents lack
the fields, nor proof that one parser change would fix them. Recognition and
layout, label coverage, and semantic extraction require separate evaluation.
No missing buyer is guessed, no OCR characters are manually corrected, and no
validation requirement is relaxed to obtain a passing score.

New OCR scores expose only the rejection stage, known schema field names (or
`unknown` for root/unknown locations), and existing typed grounding field/code
pairs. They omit validation messages, rejected values and evidence quotes.
A valid but annotation-inaccurate output has no rejection stage; accuracy is
still reported separately. Recognition/probe failures remain separate case
statuses and do not receive invented downstream diagnostics. Historical
artifacts are unchanged; this additive diagnostic appears in new evaluations.

## Reproduction and remaining limits

Download complete source files to the manifest filenames and install the API
with development dependencies and the recorded Korean/English language data.
The evaluator performs no network I/O and refuses changed checksums. Use a new
output path rather than overwriting a historical result:

```sh
RUN_ENVIRONMENT=local-public-original-scan-evaluation PYTHONPATH=apps/api \
python scripts/run_scan_ocr_eval.py \
  --source-dir /path/to/original-pdfs \
  --tessdata-dir /path/to/tessdata \
  --output /tmp/public-scan-rerun.json
```

CI checks generated OCR regressions, provenance/classification/failure contracts,
and the existing backend/frontend/release gates. It does not redownload these
public PDFs or relabel this local evidence as a container/cloud measurement.
Raw source files and full recognized text are not committed. Full-page CER,
independent layout coverage, full-PDF extraction acceptance, worker persistence,
real G2B acquisition and cloud OCR capacity remain unverified. The next quality
experiment needs separately annotated documents and held-out layouts; changing
rules on these two known pages would be development work, not generalization.
