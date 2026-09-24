# Public Korean document OCR diagnostic

This is a measured diagnostic on **two real public procurement PDFs**, not a
natural-scan benchmark or a claim of production readiness. Both downloaded PDFs
have native text. Their first pages were visually checked before OCR, then
rendered into six images: 300 dpi, 300 dpi with Gaussian blur radius 1.2, and
150 dpi for each source. Full-page layout is retained; no labels are rewritten.

The frozen [manifest](../data/eval/public_ocr_manifest.json) records official
download URLs, source SHA-256, page numbers, manually checked factual anchors,
and expected title/buyer fields. The two issuing institutions are 광주광역시 and
한국인터넷진흥원. This is a convenience sample, **not** a held-out or representative
corpus. Three variants of a page are correlated; they are not three independent
documents. Source PDFs and full extracted text are not committed or published.

## What is measured

1. **Native-text control:** PyMuPDF text extraction from the same first page.
2. **Recognition anchors:** presence of four specified factual strings per page,
   after NFC normalization and whitespace removal. Punctuation is preserved;
   numeric anchors cannot match inside longer numbers. This is diagnostic span
   recall, **not** character accuracy or structured field accuracy. Text ordering
   can make an anchor fail even when individual words are present.
3. **Proposal fields:** exact title/buyer fields from the unchanged deterministic
   extractor, before validation.
4. **Trusted fields:** only fields from an output accepted by the unchanged
   production schema and evidence validator. A correct partial proposal in a
   rejected output earns zero trusted fields. Every expected field remains in
   the denominator. Failed/unrun cases make the aggregate score `null`.

Tesseract uses `kor+eng`, automatic page segmentation (`--psm 3`), and a 45-second
recognition timeout per image. The existing synthetic regression retains its
single-block mode (`--psm 6`). Process cancellation and timeout both kill and reap
the child, including version/language probes. No hosted model is called.

## Reference measurement

The reference [JSON](../artifacts/evaluation/public-ocr.json) is a local diagnostic,
separate from the synthetic CI/reference artifacts. It records source and model
hashes, Tesseract/PyMuPDF/Pillow versions, image hashes, environment, source-code
hash, per-case status and timings. Timings cover Tesseract recognition only,
excluding PDF rendering and downstream extraction; they are not cloud latency.
The [repeat run](../artifacts/evaluation/public-ocr-repeat.json) has identical
source-code, dataset, image and OCR-text hashes and the same scores; timings are
recorded separately. The measurement was made on a dirty working tree based on
the recorded Git commit, so the source-code hash identifies the measured code.

| Input | Matched anchors | Trusted title/buyer fields |
| --- | --- | --- |
| Native text control, 2 pages | 7/8 | 0/4 |
| 300 dpi, 2 images | 4/8 | 0/4 |
| 300 dpi blurred, 2 images | 5/8 | 0/4 |
| 150 dpi, 2 images | 2/8 | 0/4 |
| All 6 OCR images | **11/24** | **0/12** |

The failure matters: the synthetic Korean **18/18** result does not establish
real-document extraction quality. Even the native-text control produces no
trusted fields, so OCR quality alone cannot explain the extraction failure.
The conservative extractor requires explicit supported labels; these notices
use numbered labels, headings and tables. Their output is rejected instead of
being admitted as trusted facts. The native PDF also exposes reading-order
problems (for example, a currency unit can precede its amount in extracted text).

No extraction rules or ground truth were tuned to improve this score. The next
quality step is layout-aware grounding and independently annotated documents,
with held-out evaluation, plus the pending real hosted-provider comparison.
Changing only to a hosted model does not automatically bypass the current
label-based evidence validator. Natural scanned Korean PDFs remain unverified. A subsequent
[configured Tesseract runtime](runtime-ocr.md) adds real worker recognition; these
historical CLI measurements do not evaluate that runtime. The local default
`FakeFixtureOcrAdapter` remains a fixture-only routing boundary.

## Reproduction

Install the API development dependencies and Tesseract with `kor` and `eng`
language data. Download the two files from their exact manifest URLs to a local
directory using the manifest filenames. The script performs **no network I/O**;
it verifies all PDF checksums before recognizing any page. A changed/unavailable
upstream file must not be silently relabeled as the frozen source.

```bash
RUN_ENVIRONMENT=local-public-document-evaluation \
python scripts/run_public_ocr_eval.py \
  --source-dir /path/to/downloaded-public-pdfs \
  --tessdata-dir /path/to/tessdata \
  --output /tmp/public-ocr-rerun.json
```

The reference used Tesseract 5.3.4, `tessdata_fast` 4.1.0 Korean language data and
the local installation's English language data. Exact model SHA-256 values are
in the JSON. Different engines, language data or renderers can produce different
results. Keep reruns separate instead of overwriting historical measurements.

CI runs the DB-free provenance, metric, tamper, and process-cleanup contracts
alongside the existing English/Korean synthetic and full release gates. CI does
not redownload public documents or claim that this local public-document
measurement was performed in its containers.
