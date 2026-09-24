# Real PDF OCR runtime

`OCR_BACKEND=tesseract` selects a real Korean/English OCR adapter for the document
worker and scheduler. The API Docker image includes Tesseract and `kor`/`eng`
language data. The Render reference Blueprint selects this backend; the local
synthetic demo keeps the explicit `fixture` default for reproducibility.

The adapter uses [PyMuPDF's integrated Tesseract OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html)
with full-page recognition in a separate Linux process. Worker startup runs an
actual recognition probe and fails if language data or the engine is unavailable.
It does not substitute packaged fixture answers after a configuration failure.

| Setting / bound | Default |
| --- | --- |
| `OCR_BACKEND` | `fixture`; set `tesseract` for real recognition |
| `OCR_TESSDATA_DIR` | `/usr/share/tesseract-ocr/5/tessdata` in the image |
| `OCR_LANGUAGE` | `kor+eng` (`kor` and `eng` also supported) |
| `OCR_DPI` | 300 |
| `OCR_MAX_PAGES` | 10; whole PDF rejected above this limit |
| `OCR_MAX_PIXELS_PER_PAGE` | 12,000,000; all pages checked before recognition |
| `OCR_TIMEOUT_SECONDS` | 40 per recognition child, maximum configurable 45 |
| Process address space | 512 MiB, Linux `RLIMIT_AS` |
| Input PDF | 10 MiB |
| Recognized document text | 250,000 characters; response pipe also bounded |
| Concurrent recognition children | 1 per configured adapter instance |

The current adapter supports Linux workers. Native parsing and attachment
downloads precede OCR and retain their existing boundaries; the child limits do
not sandbox the entire ingestion pipeline. ARQ's job timeout also bounds work
waiting for an OCR slot. One PDF may consume much of a job budget; no cloud
throughput/capacity claim follows from these defaults.

Recognition is all-or-nothing for the PDF. Page/pixel/input limits yield an
unavailable OCR row, preserving the native parse. Runtime errors and timeouts
raise bounded error messages into the existing retry/DLQ path. Timeout and caller
cancellation kill and reap the child; temporary files are removed afterwards.
Raw document text, paths and native-library diagnostics are not put in errors.

The durable OCR identity includes adapter version, PyMuPDF/MuPDF versions,
language-file SHA-256 values, language, resolution and limits. Results from a
changed runtime cannot silently reuse the prior identity. Native parse, attachment
checksum, page numbers and OCR text hash are retained. The source's fixture flag
is retained independently of whether recognition is real. Downstream text quality
and structured-field grounding remain mandatory; readable OCR text alone is not
a trusted procurement claim.

## Verification and quality boundary

Unit/integration tests exercise image-only English and Korean PDFs, configuration,
model identity, limits, bounded output, real child cancellation/reaping, native
parse preservation and idempotent PostgreSQL persistence. These PDFs are generated
synthetic fixtures. The Korean smoke checks recognition anchors, not full-field
accuracy: in a local run, the first word of a synthetic title (`합성`) was read as
`BS` while the Korean buyer anchor was recognized. This failure is not hidden by
the runtime checks. Evidence quoting OCR text cannot by itself detect a wrong
character in that text.

The release gate additionally probes the **application image**, so installing
models only in the verification image cannot make the gate pass. Its result is
explicitly `quality_evaluated=false`:

```sh
OCR_BACKEND=tesseract python -m app.ops.check_ocr
```

The historical Korean synthetic 18/18 and public-document diagnostics use a
separate CLI evaluation path and remain unchanged. They are not measurements of
this new integrated runtime. Natural-scan generalization, complex layouts,
handwriting, production throughput and full cloud operation remain unverified.
