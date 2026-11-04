"""Build a searchable PDF reading copy directly from the Markdown plan."""
import html
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.project_tools'))
import pymupdf


def inline(text):
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', text)


def main():
    source = ROOT / 'docs' / 'PROJECT_UNDERSTANDING_AND_REBUILD_PLAN.md'
    lines = source.read_text(encoding='utf-8').splitlines()
    sections = [(int(m.group(1)), line[3:]) for line in lines
                if (m := re.match(r'^## (\d+)\.', line))]
    parts = [
        '<div class="cover"><p class="eyebrow">PROJECT UNDERSTANDING &amp; IMPLEMENTATION ROADMAP</p>',
        '<h1 class="title">Surface Subsidence<br/>and Strain Prediction</h1>',
        '<p class="subtitle">Rebuilding the inclined-seam influence-function project with modest, measurable improvements.</p>',
        '<p>Prepared from MTP 1.pdf and subsidence pdf .pdf<br/>3 November 2026</p>',
        '<p>This document explains the reported model and software, records the Adriyala evidence and reproduction gaps, and defines a phased rebuild with acceptance criteria.</p>',
        '<p class="notice"><b>Status:</b> Source analysis and planning completed. The prediction application has not yet been rebuilt in this workspace.</p>',
        '<p>Primary improvements: repeatable parameter fitting, clearer validation, and saved/exportable runs.</p></div>',
        '<div class="newpage"><h1>Contents</h1>',
    ]
    parts += [f'<p><a href="#section{n}">{inline(label)}</a></p>' for n, label in sections]
    parts.append('</div><div class="newpage">')
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line or line.startswith('# ') or line.startswith('## Understanding the existing'):
            i += 1; continue
        if line.startswith('```'):
            block = []; i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                block.append(lines[i]); i += 1
            parts.append('<pre>'+html.escape('\n'.join(block))+'</pre>')
            i += 1; continue
        if line.startswith('|'):
            rows=[]
            while i < len(lines) and lines[i].startswith('|'):
                row = [x.strip() for x in lines[i].strip('|').split('|')]
                if not all(re.fullmatch(r':?-{3,}:?', c) for c in row):
                    rows.append(row)
                i += 1
            parts.append('<table>')
            for index,row in enumerate(rows):
                tag='th' if index==0 else 'td'
                parts.append('<tr>'+''.join(f'<{tag}>{inline(c)}</{tag}>' for c in row)+'</tr>')
            parts.append('</table>')
            continue
        if line.startswith('## '):
            m = re.match(r'^## (\d+)\.', line)
            ident = f' id="section{m.group(1)}"' if m else ''
            parts.append(f'<h1{ident}>{inline(line[3:])}</h1>')
        elif line.startswith('### '):
            parts.append('<h2>'+inline(line[4:])+'</h2>')
        else:
            parts.append('<p>'+inline(line)+'</p>')
        i += 1
    parts.append('</div>')
    css = '''
    body {font-family:sans-serif; font-size:10.5pt; line-height:1.2; color:#202d35;}
    h1 {font-size:18pt; color:#164b63; margin-top:18pt; margin-bottom:8pt; page-break-after:avoid;}
    h2 {font-size:13pt; color:#164b63; margin-top:13pt; margin-bottom:6pt; page-break-after:avoid;}
    p {margin-top:0; margin-bottom:8pt;}
    .title {font-size:32pt; margin-top:55pt; margin-bottom:24pt;}
    .eyebrow {font-size:9pt; color:#164b63;}
    .subtitle {font-size:16pt; color:#446879; margin-bottom:28pt;}
    .notice {padding:12pt; margin-top:20pt;}
    .newpage {page-break-before:always;}
    table {border-collapse:collapse; width:100%; margin-top:8pt; margin-bottom:12pt; font-size:9pt;}
    th,td {border:0.5pt solid #b6c7cf; padding:5pt; vertical-align:top;}
    th {color:#164b63; text-align:left;}
    tr {page-break-inside:avoid;}
    pre {font-family:monospace; font-size:8.7pt; line-height:1.15; padding:8pt; margin-bottom:10pt;}
    code {font-family:monospace; font-size:9pt;}
    a {color:#176b92;}
    '''
    positions={}
    def positionfn(position):
        if position.id and position.open_close & 1:
            positions[position.id]=position.page_num
    a4=pymupdf.paper_rect('a4')
    def rectfn(number, filled):
        if number > 100:
            raise RuntimeError('Unexpected pagination size')
        return a4,pymupdf.Rect(48,50,a4.width-48,a4.height-45),None
    story=pymupdf.Story('<html><body>'+''.join(parts)+'</body></html>',user_css=css)
    doc=story.write_with_links(rectfn,positionfn=positionfn)
    for i,page in enumerate(doc):
        page.insert_text((48,27),'SUBSIDENCE PREDICTION | PROJECT STUDY & REBUILD PLAN',fontsize=7.5,color=(.086,.294,.388))
        page.insert_text((48,a4.height-22),'3 November 2026',fontsize=7.5,color=(.3,.3,.3))
        page.insert_text((a4.width-90,a4.height-22),f'Page {i+1}',fontsize=7.5,color=(.3,.3,.3))
    doc.set_toc([[1,label,positions[f'section{n}']] for n,label in sections])
    doc.set_metadata({'title':'Surface Subsidence and Strain Prediction: Understanding and Rebuild Plan',
                      'author':'Project workspace','subject':'Source-based analysis and phase-by-phase rebuild plan'})
    target=ROOT/'docs'/'Subsidence_Project_Understanding_and_Rebuild_Plan.pdf'
    doc.save(target,garbage=4,deflate=True)
    print(f'Wrote {target}: {len(doc)} searchable pages')
    previews=ROOT/'docs'/'review'; previews.mkdir(exist_ok=True)
    for index in [0,2,positions['section7']-1,len(doc)-1]:
        doc[index].get_pixmap(matrix=pymupdf.Matrix(1.3,1.3)).save(str(previews/f'plan_page_{index+1:02d}.png'))
    print('Section pages:',positions)


if __name__=='__main__':
    main()
