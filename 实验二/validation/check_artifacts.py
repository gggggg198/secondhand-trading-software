"""Verify standalone PlantUML source/PNG identity and documentation links.

Usage: python check_artifacts.py <path to plantuml-1.2025.4.jar>
Requires Pillow for reading embedded source and PNG dimensions.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
jar = Path(sys.argv[1]).resolve()
sources = sorted((ROOT / 'UML').glob('*.puml'))
pngs = sorted((ROOT / 'UML').glob('*.png'))
assert len(sources) == len(pngs) == 8
assert len(list((ROOT / 'UML').glob('*时序图*.puml'))) == 3
result = subprocess.run(['java', '-Dfile.encoding=UTF-8', '-jar', str(jar),
    '-charset', 'UTF-8', '-checkonly', *map(str, sources)],
    capture_output=True, encoding='utf-8', errors='replace')
assert result.returncode == 0, result.stdout + result.stderr

def normalized_uml(text):
    text = text.replace('\r\n', '\n')
    return text[text.index('@startuml'):text.index('@enduml') + len('@enduml')].strip()

entries = []
for source in sources:
    png = source.with_suffix('.png')
    text = source.read_text(encoding='utf-8')
    assert not re.search(r'Id\b', text), source.name
    assert '!include' not in text, 'Each source must render independently'
    with Image.open(png) as im:
        im.load()
        assert normalized_uml(im.info['plantuml']) == normalized_uml(text), source.name
        width, height = im.size
    entries.append(dict(source=source.name, png=png.name, width=width, height=height,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        png_sha256=hashlib.sha256(png.read_bytes()).hexdigest(),
        embedded_source_matches=True))

report = ROOT / 'UML图解析.md'
for target in re.findall(r'\]\(([^)]+)\)', report.read_text(encoding='utf-8')):
    if not target.startswith(('https:', 'http:')):
        assert (report.parent / target).is_file(), target
data = dict(plantuml_version='1.2025.4', standalone_diagrams=8,
    sequence_diagrams=3, syntax_check='passed', embedded_source_check='passed',
    documentation_links='passed', identifier_check='passed', artifacts=entries)
(ROOT / 'validation/artifact-checks.json').write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('PASS: 8 standalone sources; 8 PNGs; 3 sequence diagrams; embedded sources, ID spelling and links match.')
for entry in entries:
    print(f"{entry['source']}: {entry['width']}x{entry['height']}")
