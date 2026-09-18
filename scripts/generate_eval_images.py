"""Generate synthetic image fixtures; re-freezing requires intentional manifest review.

This is NOT OCR and never derives labels from recognition outputs. Pillow is only
needed to regenerate fixtures, not to run evaluation on the committed PNGs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main() -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    root = Path(__file__).resolve().parents[1] / 'data/eval'
    target = root / 'ocr'
    target.mkdir(exist_ok=True)
    text = (
        'Title: Synthetic cloud project\nBuyer: Example Agency\nCategory: services\n'
        'Budget: KRW 125000000\nRegion: Seoul'
    )
    font = ImageFont.load_default(size=32)
    image = Image.new('L', (1150, 360), 255)
    ImageDraw.Draw(image).multiline_text((35, 35), text, font=font, fill=0, spacing=15)
    variants = {
        'clean': image,
        'blurred': image.filter(ImageFilter.GaussianBlur(1.7)),
        'low_resolution': image.resize((345, 108)).resize(image.size),
    }
    expected = {'title': 'Synthetic cloud project', 'buyer_name': 'Example Agency',
                'procurement_type': 'services', 'estimated_amount': '125000000',
                'currency': 'KRW', 'regions': ['Seoul']}
    cases = []
    for name, variant in variants.items():
        path = target / f'{name}.png'
        variant.save(path)
        cases.append({'id': name, 'path': f'ocr/{name}.png', 'expected_fields': expected,
                      'language': 'eng', 'synthetic': True})
    (root / 'ocr_manifest.json').write_text(json.dumps({'cases': cases, 'source_text': text},
                                                     indent=2) + '\n')
    manifest = json.loads((root / 'manifest.json').read_text())
    for path in [root / 'ocr_manifest.json', *target.glob('*.png')]:
        manifest['files'][path.relative_to(root).as_posix()] = (
            hashlib.sha256(path.read_bytes()).hexdigest()
        )
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
