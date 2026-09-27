"""Private, offline, single-page PP-OCRv5 candidate child; not a worker backend."""
from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import socket
from contextlib import contextmanager
from pathlib import Path

MODEL_SHA256 = {
    "ch_PP-OCRv5_det_mobile.onnx":
        "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae",
    "korean_PP-OCRv5_rec_mobile.onnx":
        "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx":
        "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
}
PACKAGES = {"rapidocr": "3.9.2", "onnxruntime": "1.23.2", "pymupdf": "1.28.2"}
MEMORY_BYTES = 1024 * 1024 * 1024


class CandidateFailure(Exception):
    def __init__(self, stage, code):
        super().__init__("candidate failed")
        self.stage = stage
        self.code = code


def failure_code(error, default):
    if isinstance(error, MemoryError) or (
        isinstance(error, OSError) and error.errno == errno.ENOMEM
    ):
        return "memory_allocation"
    # RapidOCR wraps ONNX allocation failures in its own exception. Match only
    # known allocator markers on that pinned wrapper; never return its message.
    if type(error).__name__ == "ONNXRuntimeError" and any(
        marker in str(error).lower()
        for marker in ("std::bad_alloc", "failed to allocate memory", "out of memory")
    ):
        return "memory_allocation"
    if isinstance(error, (ImportError, importlib.metadata.PackageNotFoundError)):
        return "dependency_unavailable"
    return default


@contextmanager
def candidate_stage(stage, default="runtime_error"):
    try:
        yield
    except CandidateFailure:
        raise
    except Exception as error:  # noqa: BLE001 - publish only the allowlisted diagnosis
        raise CandidateFailure(stage, failure_code(error, default)) from None


def diagnosed_call(call, stage):
    def invoke(*args, **kwargs):
        with candidate_stage(stage):
            return call(*args, **kwargs)
    return invoke


def model_paths(directory):
    paths = {}
    for name, expected in MODEL_SHA256.items():
        path = directory / name
        if not path.is_file() or not 0 < path.stat().st_size <= 20 * 1024 * 1024:
            raise ValueError("unverified model")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected:
            raise ValueError("unverified model")
        paths[name] = str(path)
    return paths


def metadata():
    versions = {name: importlib.metadata.version(name) for name in PACKAGES}
    if versions != PACKAGES:
        raise ValueError("unverified package version")
    for name in ("numpy", "opencv-python", "Pillow", "omegaconf", "PyYAML", "shapely"):
        versions[name] = importlib.metadata.version(name)
    return {"packages": versions, "python": platform.python_version(),
            "model_sha256": MODEL_SHA256, "address_space_limit_bytes": MEMORY_BYTES,
            "dpi": 300, "page_scope": "annotated_page_only", "threads": 1,
            "angle_classification": False, "max_side_len": 2000,
            "det_limit_side_len": 736, "det_limit_type": "min", "text_score": 0.5,
            "candidate_version": "ppocr-v5-offline-v1",
            "diagnostic_contract_version": "allowlisted-stage-v1"}


def deny_network(*args, **kwargs):
    raise OSError("offline candidate forbids network access")


def recognize(args):
    with candidate_stage("models", "invalid_input"):
        paths = model_paths(args.models)
    with candidate_stage("source", "invalid_input"):
        with args.pdf.open("rb") as stream:
            raw = stream.read(10 * 1024 * 1024 + 1)
        if (not 0 < len(raw) <= 10 * 1024 * 1024
                or hashlib.sha256(raw).hexdigest() != args.source_sha256):
            raise ValueError("unverified source")

    with candidate_stage("render", "invalid_input"):
        import pymupdf

        with pymupdf.open(stream=raw, filetype="pdf") as pdf:
            if pdf.needs_pass or not 1 <= args.page <= pdf.page_count <= 50:
                raise ValueError("invalid page")
            page = pdf[args.page - 1]
            pixels = math.ceil(page.rect.width * 300 / 72) * math.ceil(page.rect.height * 300 / 72)
            if not 0 < pixels <= 12_000_000:
                raise ValueError("pixel limit")
            image = page.get_pixmap(dpi=300, colorspace=pymupdf.csRGB, alpha=False).tobytes("png")
        del raw
        pymupdf.TOOLS.store_shrink(100)

    with candidate_stage("initialization"):
        import cv2
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        cv2.setNumThreads(1)
        engine = RapidOCR(params={
            "Global.log_level": "critical", "Global.use_cls": False,
            "EngineConfig.onnxruntime.intra_op_num_threads": 1,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Det.model_path": paths["ch_PP-OCRv5_det_mobile.onnx"],
            "Det.model_type": ModelType.MOBILE, "Det.ocr_version": OCRVersion.PPOCRV5,
            "Cls.model_path": paths["ch_ppocr_mobile_v2.0_cls_mobile.onnx"],
            "Rec.model_path": paths["korean_PP-OCRv5_rec_mobile.onnx"],
            "Rec.lang_type": LangRec.KOREAN, "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        })
        # Pinned RapidOCR hooks keep the same inputs, outputs and empty-result
        # behavior. Only exceptions that already escape these model calls change.
        engine.text_det = diagnosed_call(engine.text_det, "detection")
        engine.text_rec = diagnosed_call(engine.text_rec, "recognition")
    with candidate_stage("inference"):
        result = engine(image)
    with candidate_stage("output"):
        text = "\n".join(result.txts or ())
        if len(text) > 250_000:
            raise ValueError("text limit")
        return {"page_number": args.page, "text": text,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--models", type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--page", type=int)
    parser.add_argument("--source-sha256")
    args = parser.parse_args()
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (42, 42))
    # Local model paths should avoid all downloads. Enforce that if upstream
    # unexpectedly tries to retrieve a dictionary, font, telemetry or a model.
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    try:
        with candidate_stage("environment", "dependency_unavailable"):
            details = metadata()
        result = details if args.describe else recognize(args)
    except CandidateFailure as error:
        result = {"error": "candidate_failed", "stage": error.stage, "code": error.code}
    except Exception:  # noqa: BLE001 - private process boundary must not expose document errors
        result = {"error": "candidate_failed", "stage": "unknown", "code": "runtime_error"}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
