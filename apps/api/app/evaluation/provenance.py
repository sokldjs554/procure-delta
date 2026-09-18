from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_dataset(directory: Path) -> tuple[dict[str, Any], str]:
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError('dataset manifest escapes its directory')
        if sha256(path.read_bytes()) != expected:
            raise ValueError(f'frozen dataset checksum mismatch: {name}')
    raw = (directory / 'benchmark.json').read_bytes()
    return json.loads(raw), sha256(raw)


def source_hash(root: Path) -> str:
    digest = hashlib.sha256()
    files = [*root.glob('apps/api/app/**/*.py'), *root.glob('scripts/*.py')]
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()


def environment() -> dict[str, Any]:
    return {'python': platform.python_version(), 'os': platform.platform(),
            'cpu_logical_count': os.cpu_count(), 'machine': platform.machine(),
            'cpu_model': platform.processor() or 'not exposed',
            'environment_label': os.getenv('RUN_ENVIRONMENT', 'unspecified'),
            'cpu_quota': Path('/sys/fs/cgroup/cpu.max').read_text().strip()
            if Path('/sys/fs/cgroup/cpu.max').exists() else None}


def provenance(root: Path, dataset_hash: str, config: dict[str, Any]) -> dict[str, Any]:
    try:
        commit = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(root), 'status', '--porcelain'],
                                   capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {'dataset_sha256': dataset_hash, 'source_sha256': source_hash(root),
            'git_commit': commit, 'git_dirty': dirty, 'configuration': config,
            'environment': environment(), 'synthetic': True}


def write_artifact(path: Path, payload: dict[str, Any], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False,
                               default=str) + '\n', encoding='utf-8')
    path.with_suffix('.md').write_text(
        f'# {title}\n\n기계 판독용 원본: `{path.name}`.\n\n'
        '합성 회귀 실험이며 운영 성능/실제 조달 적합도 평가가 아니다. '
        '미실행 지표는 null 또는 not_run이다.\n\n```json\n'
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n```\n',
        encoding='utf-8',
    )
