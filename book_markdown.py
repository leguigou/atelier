"""Shared Markdown rendering for portable publications; no raw HTML."""
import html, re
from markdown_it import MarkdownIt
from defusedxml import ElementTree as ET

parser = MarkdownIt('commonmark', {'html': False}).enable(['table', 'strikethrough'])
def local_image(renderer,tokens,index,options,env):
    token=tokens[index]
    if not re.fullmatch(r'/api/asset\?id=[a-zA-Z0-9_-]+(?:&preview=1)?',token.attrGet('src') or ''):
        return '<span>'+html.escape(token.content or 'Image')+' (à importer dans la médiathèque)</span>'
    return renderer.image(tokens,index,options,env)
parser.add_render_rule('image',local_image)
def editorial_styles(state, silent):
    match=re.match(r'^(\+\+|==|\^|~)([^\n]+?)\1',state.src[state.pos:])
    if not match or not match[2].strip() or (match[1] in ('^','~') and (re.search(r'\s',match[2]) or match[1] in match[2])):return False
    tag={'++':'u','==':'mark','^':'sup','~':'sub'}[match[1]]
    if not silent:
        state.push(tag+'_open',tag,1);token=state.push('text','',0);token.content=match[2];state.push(tag+'_close',tag,-1)
    state.pos+=len(match[0]);return True
parser.inline.ruler.before('emphasis','editorial_styles',editorial_styles)

def render(text):
    return parser.render(str(text or ''))

def pdf_flowables(text, body, heading, quote, width, image_loader):
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, XPreformatted, HRFlowable
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    # Generated markup is XML-compatible after normalizing void tags and nbsp.
    root = ET.fromstring('<root>'+render(text).replace('<hr>', '<hr/>').replace('&nbsp;', '&#160;')+'</root>')
    def inline(node):
        result=html.escape(node.text or '')
        for child in node:
            tag=child.tag;inner=inline(child)
            if tag in ('strong','em','s','code'):
                mapped={'strong':'b','em':'i','s':'strike','code':'font'}[tag]
                attrs=' name="Courier"' if tag=='code' else ''
                result+=f'<{mapped}{attrs}>{inner}</{mapped}>'
            elif tag=='a':result+='<a href="'+html.escape(child.get('href',''),quote=True)+'">'+inner+'</a>'
            elif tag=='br':result+='<br/>'
            elif tag in ('u','sup','sub'):result+=f'<{tag}>{inner}</{tag}>'
            elif tag=='mark':result+='<span backColor="#f0e3b5">'+inner+'</span>'
            elif tag=='img':result+=html.escape(child.get('alt',''))
            elif tag not in ('ul','ol','p') or node.tag!='li':result+=inner
            result+=html.escape(child.tail or '')
        return result
    def walk(node,style=body):
        out=[]
        for element in node:
            tag=element.tag
            if tag=='table':
                rows=element.findall('.//tr');count=max((len(row) for row in rows),default=1)
                cell=ParagraphStyle('Cell',parent=style,fontSize=style.fontSize*.85,leading=style.leading*.9,firstLineIndent=0)
                data=[[Paragraph(inline(td),ParagraphStyle('AlignedCell',parent=cell,alignment=2 if 'right' in td.get('style','') else 1 if 'center' in td.get('style','') else 0)) for td in row] for row in rows]
                table=Table(data,colWidths=[width/count]*count,repeatRows=1,hAlign='LEFT')
                table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cbd3c3')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8edde')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
                out.extend([table,Spacer(1,8)])
            elif tag in ('ul','ol'):
                for n,li in enumerate(element):
                    item=ParagraphStyle('List',parent=style,leftIndent=style.leftIndent+14,firstLineIndent=0,bulletIndent=style.leftIndent)
                    prefix=str(int(element.get('start','1'))+n)+'.' if tag=='ol' else '•'
                    if li.text and li.text.strip():out.append(Paragraph(inline(li),item,bulletText=prefix))
                    elif len(li) and li[0].tag=='p':out.append(Paragraph(inline(li[0]),item,bulletText=prefix))
                    else:out.append(Paragraph(inline(li),item,bulletText=prefix))
                    for nested in li:
                        if nested.tag in ('ul','ol'):
                            wrapper=ET.fromstring('<root/>');wrapper.append(nested);out.extend(walk(wrapper,item))
                    for extra in list(li)[1:]:
                        if extra.tag=='p':out.append(Paragraph(inline(extra),item))
            elif tag=='blockquote':out.extend(walk(element,quote))
            elif tag=='pre':
                code=ParagraphStyle('Code',parent=style,fontName='Courier',fontSize=style.fontSize*.85,leading=style.leading,firstLineIndent=0)
                # Wrap long code lines so narrow A5 pages remain printable.
                import textwrap
                source=''.join(element.itertext());limit=max(12,int(width/(code.fontSize*.6)))
                source='\n'.join('\n'.join(textwrap.wrap(line,limit,replace_whitespace=False,drop_whitespace=False)) or '' for line in source.splitlines())
                out.append(XPreformatted(html.escape(source),code))
            elif tag=='hr':out.extend([HRFlowable(width='100%',color=colors.HexColor('#cbd3c3')),Spacer(1,8)])
            else:
                images=element.findall('.//img')
                if images and not ''.join(element.itertext()).strip():
                    for im in images:
                        picture=image_loader(im.get('src',''))
                        if picture:out.append(picture)
                        else:out.append(Paragraph(html.escape(im.get('alt','Image non disponible')),style))
                else:out.append(Paragraph(inline(element),heading if tag in ('h1','h2','h3','h4','h5','h6') else style))
        return out
    return walk(root)
