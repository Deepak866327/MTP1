"""Build an editable Word study/plan from its Markdown source."""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.project_tools'))

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from docx.opc.constants import RELATIONSHIP_TYPE as RT

SOURCE = ROOT / 'docs' / 'PROJECT_UNDERSTANDING_AND_REBUILD_PLAN.md'
TARGET = ROOT / 'docs' / 'Subsidence_Project_Understanding_and_Rebuild_Plan.docx'
ACCENT = '164B63'


def shade(element, fill):
    props = element.get_or_add_tcPr() if element.tag == qn('w:tc') else element.get_or_add_pPr()
    node = OxmlElement('w:shd')
    node.set(qn('w:fill'), fill)
    props.append(node)


def hyperlink(paragraph, label, target):
    relation = paragraph.part.relate_to(target, RT.HYPERLINK, is_external=True)
    link = OxmlElement('w:hyperlink')
    link.set(qn('r:id'), relation)
    run = OxmlElement('w:r')
    props = OxmlElement('w:rPr')
    color = OxmlElement('w:color'); color.set(qn('w:val'), '176B92')
    props.append(color)
    underline = OxmlElement('w:u'); underline.set(qn('w:val'), 'single')
    props.append(underline)
    run.append(props)
    text = OxmlElement('w:t'); text.text = label
    run.append(text)
    link.append(run)
    paragraph._p.append(link)


def inline(paragraph, text, bold=False, color=None):
    tokens = re.split(r'(\[[^\]]+\]\([^\)]+\)|\*\*[^*]+\*\*|`[^`]+`)', text)
    for token in tokens:
        if not token:
            continue
        match = re.fullmatch(r'\[([^\]]+)\]\(([^\)]+)\)', token)
        if match:
            hyperlink(paragraph, match.group(1), match.group(2))
            continue
        code = token.startswith('`') and token.endswith('`')
        strong = token.startswith('**') and token.endswith('**')
        content = token[1:-1] if code else token[2:-2] if strong else token
        run = paragraph.add_run(content)
        run.bold = bold or strong
        if code:
            run.font.name = 'Consolas'
            run.font.size = Pt(9)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)


def field(paragraph, instruction):
    run = paragraph.add_run()
    start = OxmlElement('w:fldChar'); start.set(qn('w:fldCharType'), 'begin')
    code = OxmlElement('w:instrText'); code.set(qn('xml:space'), 'preserve'); code.text = instruction
    separator = OxmlElement('w:fldChar'); separator.set(qn('w:fldCharType'), 'separate')
    value = OxmlElement('w:t'); value.text = '1'
    end = OxmlElement('w:fldChar'); end.set(qn('w:fldCharType'), 'end')
    for element in [start, code, separator, value, end]:
        run._r.append(element)


def table(document, lines):
    rows = [[c.strip() for c in line.strip().strip('|').split('|')] for line in lines]
    rows = [row for row in rows if not all(re.fullmatch(r':?-{3,}:?', c) for c in row)]
    tab = document.add_table(rows=1, cols=len(rows[0]))
    tab.alignment = WD_TABLE_ALIGNMENT.CENTER
    tab.style = 'Table Grid'
    for index, rowdata in enumerate(rows):
        cells = tab.rows[0].cells if index == 0 else tab.add_row().cells
        row = tab.rows[index]
        no_split = OxmlElement('w:cantSplit'); row._tr.get_or_add_trPr().append(no_split)
        if index == 0:
            header = OxmlElement('w:tblHeader'); row._tr.get_or_add_trPr().append(header)
        for cell, text in zip(cells, rowdata):
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(4)
            paragraph.paragraph_format.space_before = Pt(3)
            paragraph.paragraph_format.line_spacing = 1.05
            if index == 0:
                shade(cell._tc, ACCENT)
            elif index % 2 == 0:
                shade(cell._tc, 'F2F6F8')
            inline(paragraph, text, bold=index == 0, color='FFFFFF' if index == 0 else None)
            for run in paragraph.runs:
                run.font.size = Pt(9)
    document.add_paragraph().paragraph_format.space_after = Pt(1)


def build():
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.7)
    section.left_margin = section.right_margin = Cm(1.9)
    section.header_distance = section.footer_distance = Cm(0.8)
    normal = document.styles['Normal']
    normal.font.name, normal.font.size = 'Calibri', Pt(10.5)
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.12
    for name, size in [('Title', 30), ('Heading 1', 18), ('Heading 2', 13), ('Heading 3', 11)]:
        style = document.styles[name]
        style.font.name = 'Calibri'
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(ACCENT)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(14)
        style.paragraph_format.space_after = Pt(6)
    for name in ['List Bullet', 'List Number']:
        document.styles[name].paragraph_format.space_after = Pt(5)
    header = section.header.paragraphs[0]
    header.add_run('SUBSIDENCE PREDICTION  |  PROJECT STUDY & REBUILD PLAN')
    header.runs[0].font.size = Pt(8)
    header.runs[0].font.color.rgb = RGBColor.from_string(ACCENT)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run('3 November 2026  |  Page ')
    field(footer, 'PAGE')
    for run in footer.runs:
        run.font.size = Pt(8)
    document.core_properties.title = 'Surface Subsidence and Strain Prediction: Understanding and Rebuild Plan'
    document.core_properties.subject = 'Source-based project analysis and phase-by-phase implementation plan'
    document.core_properties.author = 'Project workspace'
    document.core_properties.keywords = 'subsidence, mining, influence function, strain, Adriyala, rebuild'

    document.add_paragraph('PROJECT UNDERSTANDING & IMPLEMENTATION ROADMAP', 'Subtitle')
    document.add_paragraph('Surface Subsidence\nand Strain Prediction', 'Title')
    document.add_paragraph('Rebuilding the inclined-seam influence-function project with modest, measurable improvements.', 'Subtitle')
    document.add_paragraph('Prepared from MTP 1.pdf and subsidence pdf .pdf\n3 November 2026')
    document.add_paragraph('This document explains the reported model and software, records the Adriyala evidence and reproduction gaps, and defines a phased rebuild with acceptance criteria.')
    p = document.add_paragraph()
    shade(p._p, 'EEF4F7')
    inline(p, '**Status:** Source analysis and planning completed. The prediction application has not yet been rebuilt in this workspace.')
    document.add_paragraph('Primary improvements: repeatable parameter fitting, clearer validation, and saved/exportable runs.')
    document.add_page_break()
    document.add_paragraph('Contents', 'Title')
    for line in SOURCE.read_text(encoding='utf-8').splitlines():
        if re.match(r'^## \d+\.', line):
            document.add_paragraph(line[3:])
    document.add_page_break()

    lines = SOURCE.read_text(encoding='utf-8').splitlines()
    i = 0
    skipped_subtitle = False
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith('# '):
            i += 1
            continue
        if line.startswith('## Understanding the existing') and not skipped_subtitle:
            skipped_subtitle = True
            i += 1
            continue
        if line.startswith('```'):
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                block.append(lines[i]); i += 1
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(4)
            paragraph.paragraph_format.space_after = Pt(9)
            paragraph.paragraph_format.line_spacing = 1.0
            shade(paragraph._p, 'F1F4F6')
            run = paragraph.add_run('\n'.join(block))
            run.font.name, run.font.size = 'Consolas', Pt(9)
            i += 1
            continue
        if line.startswith('|'):
            block = []
            while i < len(lines) and lines[i].startswith('|'):
                block.append(lines[i]); i += 1
            table(document, block)
            continue
        if line.startswith('## '):
            document.add_heading(line[3:], level=1)
        elif line.startswith('### '):
            document.add_heading(line[4:], level=2)
        elif re.match(r'^\d+\. ', line):
            inline(document.add_paragraph(style='List Number'), re.sub(r'^\d+\. ', '', line))
        elif line.startswith('- '):
            inline(document.add_paragraph(style='List Bullet'), line[2:])
        else:
            inline(document.add_paragraph(), line)
        i += 1
    settings = document.settings.element
    update = OxmlElement('w:updateFields'); update.set(qn('w:val'), 'true'); settings.append(update)
    document.save(TARGET)
    print(f'Wrote {TARGET}')
    print(f'{len(document.paragraphs)} paragraphs, {len(document.tables)} tables')


if __name__ == '__main__':
    build()
