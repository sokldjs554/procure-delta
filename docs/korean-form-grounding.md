# Korean form grounding diagnostic

The v2 extractor handles explicit Korean form typography that v1 missed: spaced
labels, one bullet/enumeration prefix, full-width colons, and a colon-only label
followed by one adjacent value line. Whole notice headings can ground category.
Evidence must still match the source attachment, page and exact span. Required
title/buyer/category fields and whole-result rejection have not been relaxed.
Unlabeled table cells, inferred buyers and longer wrapped values remain unsupported.

## Measured scope

The [additional manifest](../data/eval/public_ocr_forms_manifest.json) pins two
official G2B PDFs and their first pages. Search snippets informed the design, so
these are **development diagnostics, not a held-out generalization test**. Both
pages were visually checked and annotations frozen before OCR; OCR failures were
not removed or used to tune recognition settings. One document has explicit form
labels; the other is an unsupported cover/table. Neither is a natural scan.

| Same new documents | v1 trusted fields | v2 trusted fields |
| --- | ---: | ---: |
| Native text, 2 pages | 0/6 | **3/6** |
| Raster OCR, 6 images | 0/18 | **0/18** |

Only the Yeoju notice's native text passes all three fields (3/3). The other
native page abstains (0/3), and every OCR variant fails whole-result validation.
OCR anchor recognition is 3/12 for both versions; this is selected-string recall,
not full-page character accuracy. The original two-document suite still yields
0/12 trusted OCR fields and 0/4 native fields. Synthetic Korean 18/18 is a separate
regression metric. **This change improves native form parsing, not OCR quality.**

Evidence:

- [v1 baseline](../artifacts/evaluation/public-ocr-forms-v1-baseline.json): original
  `b5fc4a3` code, only the input manifest replaced in an isolated checkout;
  `git_dirty=true` records that substitution. No baseline code changed.
- [v2 additional documents](../artifacts/evaluation/public-ocr-forms-v2.json).
- [v2 original documents](../artifacts/evaluation/public-ocr-v2-original-cases.json).

Artifacts retain source/dataset/model/image/text hashes, versions, per-field
denominators, rejection status and local environment. Raw PDFs and full OCR/native
text are not published. Runs are local functional diagnostics; timings are not
a controlled performance comparison. Source and dataset hashes distinguish the
actual measured implementation and inputs even when the checkout is dirty.

## Reproduce

Acquire the official PDFs listed in the manifests and the same kor/eng model
files explicitly. The runner checks hashes and does not download inputs:

```sh
RUN_ENVIRONMENT=local-public-document-evaluation \
python scripts/run_public_ocr_eval.py \
  --source-dir /path/to/pdfs --tessdata-dir /path/to/tessdata \
  --manifest data/eval/public_ocr_forms_manifest.json \
  --output /tmp/forms-current.json
```

For the baseline, use an isolated checkout of `b5fc4a3`, replace only
`data/eval/public_ocr_manifest.json` with the additional manifest above, and run
the original command without `--manifest`. Keep the original two-document
manifest and historical artifacts unchanged in the main checkout.

The next quality gate needs independent documents and a separately evaluated
recognition/layout approach. Current evidence does not support a production OCR
accuracy claim, table understanding, or natural-scan generalization.
