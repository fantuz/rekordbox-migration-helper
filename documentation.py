"""Read only the bundled project Markdown; no user-supplied document paths."""
import html
from pathlib import Path
import posixpath
from urllib.parse import quote,unquote,urlsplit

ROOT=Path(__file__).resolve().parent
FILES={'overview':'README.md','changelog':'CHANGELOG.md','security':'SECURITY.md','contributing':'CONTRIBUTING.md','license':'LICENSE','third-party-notices':'THIRD-PARTY-NOTICES.txt',
       **{p.stem.lower():'docs/'+p.name for p in (ROOT/'docs').glob('*.md') if not p.name.startswith('.')}}


def render_document(name,root=ROOT):
    from markdown_it import MarkdownIt
    if name not in FILES:raise ValueError('Unknown documentation chapter')
    source=FILES[name];text=(Path(root)/source).read_text(encoding='utf-8')
    parser=MarkdownIt('js-default').enable('table')
    tokens=parser.parse(text)
    def links(items):
        for token in items:
            if token.type=='link_open':
                href=token.attrGet('href') or ''
                try:parts=urlsplit(href)
                except ValueError:parts=None
                if parts and parts.scheme in ('https','http') and parts.netloc:
                    token.attrSet('target','_blank');token.attrSet('rel','noopener noreferrer')
                elif parts and not parts.scheme and not parts.netloc and not href.startswith(('/','\\')):
                    relative=posixpath.normpath(posixpath.join(posixpath.dirname(source),unquote(parts.path)))
                    match=next((key for key,value in FILES.items() if value==relative),None)
                    if match:token.attrSet('href','#documentation/'+match);token.attrSet('data-help-doc',match)
                    elif not parts.path:token.attrSet('href','#')
                    elif relative.startswith('docs/') and relative.endswith('.json'):
                        token.attrSet('href','https://github.com/fantuz/rekordbox-migration-helper/blob/main/'+quote(relative));token.attrSet('target','_blank');token.attrSet('rel','noopener noreferrer')
                    else:token.attrSet('href','#');token.attrSet('aria-disabled','true')
                else:token.attrSet('href','#');token.attrSet('aria-disabled','true')
            if token.children:links(token.children)
    links(tokens)
    # README badges and external images must not cause automatic network requests.
    parser.renderer.rules['image']=lambda tokens,idx,options,env:'<span class="documentation-image">'+html.escape(tokens[idx].content)+'</span>'
    return {'id':name,'file':source,'language':'en','html':parser.renderer.render(tokens,parser.options,{})}


def register(app):
    from flask import jsonify,send_file
    @app.get('/api/docs')
    def document_index():
        return jsonify(language='en',chapters=[{'id':key,'file':value,'title':key.replace('-',' ').title()} for key,value in FILES.items()])
    @app.get('/api/docs/<name>')
    def document_page(name):return jsonify(render_document(name))
    @app.get('/api/docs/<name>/source')
    def document_source(name):
        if name not in FILES:raise ValueError('Unknown documentation chapter')
        return send_file(ROOT/FILES[name],mimetype='text/markdown; charset=utf-8',as_attachment=True,download_name=Path(FILES[name]).name)
