"""Extract the two scanned source PDFs locally; keep page references and OCR boxes."""
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.project_tools'))

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageOps
from rapidocr_onnxruntime import RapidOCR


def main():
    output = ROOT / 'docs' / 'source_extracts'
    images = output / 'images'
    images.mkdir(parents=True, exist_ok=True)
    engine = RapidOCR(intra_op_num_threads=4, inter_op_num_threads=2)
    sources = [('MTP 1.pdf', 'mtp1', 0), ('subsidence pdf .pdf', 'subsidence', 90)]
    for filename, prefix, rotation in sources:
        document = pymupdf.open(ROOT / filename)
        texts, records, thumbnails = [], [], []
        for index, page in enumerate(document):
            started = time.monotonic()
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.25, 2.25))
            picture = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
            if rotation:
                picture = picture.rotate(rotation, expand=True)
                # Textbook photos have large white margins around the photograph.
                a = np.asarray(picture)
                mask = a.min(axis=2) < 180
                ys, xs = np.where(mask)
                if len(xs):
                    picture = picture.crop((max(0, xs.min()-10), max(0, ys.min()-10),
                                            min(picture.width, xs.max()+11), min(picture.height, ys.max()+11)))
            picture.save(images / f'{prefix}_{index+1:02d}.png')
            result, elapsed = engine(np.array(picture))
            lines = result or []
            page_text = '\n'.join(item[1] for item in lines)
            texts.append(f'\n\n===== PDF PAGE {index+1} =====\n\n{page_text}')
            records.append({'pdf_page': index+1, 'lines': lines})
            (output / f'{prefix}.txt').write_text(''.join(texts), encoding='utf-8')
            (output / f'{prefix}_ocr.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            thumb = ImageOps.contain(picture, (260, 350))
            tile = Image.new('RGB', (280, 385), 'white')
            tile.paste(thumb, ((280-thumb.width)//2, 25))
            ImageDraw.Draw(tile).text((10, 5), f'{prefix} PDF p.{index+1}', fill='black')
            thumbnails.append(tile)
            print(f'{prefix} {index+1}/{len(document)}: {len(page_text)} characters in {time.monotonic()-started:.1f}s', flush=True)
        for start in range(0, len(thumbnails), 12):
            sheet = Image.new('RGB', (1120, 1155), '#dddddd')
            for n, tile in enumerate(thumbnails[start:start+12]):
                sheet.paste(tile, ((n%4)*280, (n//4)*385))
            sheet.save(output / f'{prefix}_contact_{start//12+1}.jpg')


if __name__ == '__main__':
    main()
