from collections import Counter
from contextlib import ExitStack
from html.parser import HTMLParser
import ast
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import app as application
import documentation
from localization import LANGUAGES,PLACEHOLDERS,browser_catalogues,catalogues

ROOT=Path(__file__).parent
ASSETS=ROOT/'static'


class Markers(HTMLParser):
    def __init__(self):
        super().__init__();self.keys=set();self.unmarked=[];self.language_options=[];self.language_depth=0
    def handle_starttag(self,tag,attrs):
        attributes=dict(attrs)
        self.keys.update(value for key,value in attrs if key in ('data-i18n','data-i18n-placeholder','data-i18n-title','data-i18n-aria'))
        for name,marker in [('placeholder','data-i18n-placeholder'),('title','data-i18n-title'),('aria-label','data-i18n-aria')]:
            value=attributes.get(name,'')
            # The file-URI example is a literal path, not interface prose.
            if any(c.isalpha() for c in value) and not value.startswith('file://') and marker not in attributes:
                self.unmarked.append((tag,attributes.get('id'),name,value))
        if tag=='select' and (attributes.get('id')=='language' or 'data-language-select' in attributes):self.language_depth+=1
        if tag=='option' and self.language_depth:self.language_options.append([attributes.get('value'),''])
    def handle_data(self,data):
        if self.language_depth and self.language_options:self.language_options[-1][1]+=data
    def handle_endtag(self,tag):
        if tag=='select' and self.language_depth:self.language_depth-=1


# Inventory quoted literal keys without treating comments or HTML/string contents
# as JavaScript calls. Dynamic data/enum lookups remain outside this static check;
# the real-browser suite verifies their rendered behavior.
JS_TOKENS=re.compile(r'''/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|[^\s]''',re.S)
JS_REGEXP=re.compile(r'/((?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\[\\\r\n])*)/[a-z]*')
def javascript_tokens(source):
    tokens=[];offset=0
    while offset<len(source):
        match=JS_TOKENS.match(source,offset)
        if not match:offset+=1;continue
        token=match.group();offset=match.end()
        if token.startswith(('/*','//')):continue
        # Quotes inside a RegExp character class are not string delimiters.
        if token=='/' and (not tokens or tokens[-1] in ('=','(', '[','{',',',':','!','?',';','&','|','+','-','*','%','~','^','>','<','return','throw','case','yield','await')):
            regex=JS_REGEXP.match(source,match.start())
            if regex:tokens.append('<regexp>');offset=regex.end();continue
        tokens.append(token)
    return tokens

def literal_message_keys(source):
    tokens=javascript_tokens(source)
    for i in range(len(tokens)-4):
        if tokens[i:i+2]!=['I18n','.'] or tokens[i+2] not in ('t','html','text') or tokens[i+3]!='(':continue
        argument=i+4
        if tokens[i+2]=='text':
            depth=0
            while argument<len(tokens):
                token=tokens[argument]
                if token==',' and depth==0:argument+=1;break
                if token in ('(','[','{'):depth+=1
                elif token in (')',']','}'):
                    if depth==0:break
                    depth-=1
                argument+=1
        if argument<len(tokens) and tokens[argument].startswith(('"',"'")):
            # Project message keys use ordinary quoted strings; Python also
            # decodes their \u/\x escapes and escaped line continuations.
            yield ast.literal_eval(tokens[argument]).replace('\\/','/')


class LocalizationTests(unittest.TestCase):
    def test_catalogue_has_no_duplicate_keys_or_unknown_language_codes(self):
        duplicates=[]
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:duplicates.append(key)
                result[key]=value
            return result
        raw=json.loads((ASSETS/'locales.json').read_text(encoding='utf-8'),object_pairs_hook=unique)
        self.assertEqual(duplicates,[],duplicates)
        self.assertEqual(raw['schema'],1)
        for key,values in raw['messages'].items():self.assertFalse(set(values)-set(LANGUAGES),(key,set(values)-set(LANGUAGES)))

    def test_every_supported_language_has_complete_safe_messages_and_matching_slots(self):
        raw=json.loads((ASSETS/'locales.json').read_text(encoding='utf-8'))['messages']
        self.assertEqual(set(LANGUAGES),{'en','de','fr','it','es','el','pl','cs','ru'})
        self.assertGreater(len(raw),100)
        for key,values in raw.items():
            self.assertNotIn('@@',key)
            original=Counter(PLACEHOLDERS.findall(values.get('en',key)))
            for language in set(LANGUAGES)-{'en'}:
                self.assertIn(language,values,(key,language))
                text=values[language]
                self.assertIsInstance(text,str,(key,language));self.assertTrue(text.strip(),(key,language))
                self.assertEqual(Counter(PLACEHOLDERS.findall(text)),original,(key,language))
                self.assertNotRegex(text,r'<(?:script|img|iframe|style)\b')

    def test_source_markers_have_catalogues_without_translating_machine_keys(self):
        available=catalogues(ASSETS)['en']
        for name in ('index.html','explorer.html'):
            parser=Markers();parser.feed((ASSETS/name).read_text(encoding='utf-8'))
            self.assertFalse(parser.keys-set(available),(name,parser.keys-set(available)))
        self.assertNotIn('use strict',available)
        self.assertNotIn('(prefers-color-scheme: light)',available)
        self.assertNotIn('POST',available)
        self.assertNotIn('source_track',available)
        script=browser_catalogues(ASSETS)
        self.assertNotIn('</script>',script.lower());self.assertNotIn('\u2028',script)
        client=application.app.test_client();response=client.get('/api/i18n.js')
        self.assertEqual(response.status_code,200);self.assertIn('text/javascript',response.content_type)

    def test_interface_attributes_and_native_language_selectors_are_prepared(self):
        for name in ('index.html','explorer.html'):
            parser=Markers();parser.feed((ASSETS/name).read_text(encoding='utf-8'))
            self.assertEqual(parser.unmarked,[],(name,parser.unmarked))
            self.assertEqual([(code,label.strip()) for code,label in parser.language_options],list(LANGUAGES.items()),name)

    def test_literal_javascript_messages_exist_in_the_shared_catalogue(self):
        available=set(catalogues(ASSETS)['en'])
        for path in sorted(ASSETS.glob('*.js')):
            if path.name.endswith('.min.js'):continue
            keys=set(literal_message_keys(path.read_text(encoding='utf-8')))
            self.assertFalse(keys-available,(path.name,sorted(keys-available)))

    def test_offline_template_replacement_tokens_occur_once(self):
        text=(ASSETS/'explorer.html').read_text(encoding='utf-8')
        for token in ('@@TITLE@@','@@VIEW@@','@@MODE@@','@@STYLES@@','@@DATA@@','@@APP@@'):self.assertEqual(text.count(token),1,token)

    def test_documentation_disables_html_and_network_images_and_keeps_local_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'docs').mkdir()
            (root/'docs'/'sample.md').write_text('# Sample\n\n<script>window.bad=1</script>\n\n![image](https://example.invalid/pixel)\n\n[Next](next.md) [bad](javascript:alert(1)) [file](/etc/passwd)\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n',encoding='utf-8')
            with patch.dict(documentation.FILES,{'sample':'docs/sample.md','next':'docs/next.md'},clear=True):result=documentation.render_document('sample',root)
            text=result['html'];self.assertNotIn('<script>',text);self.assertNotIn('<img',text);self.assertNotIn('href="javascript:',text);self.assertNotIn('href="/etc/',text)
            self.assertIn('data-help-doc="next"',text);self.assertIn('<table>',text)
            with self.assertRaises(ValueError):documentation.render_document('../outside',root)

    def test_bundled_documentation_and_downloads_are_readable(self):
        client=application.app.test_client();index=client.get('/api/docs').json
        self.assertEqual(index['language'],'en');self.assertTrue(index['chapters'])
        self.assertIn('interface',{r['id'] for r in index['chapters']})
        for chapter in index['chapters']:
            page=client.get('/api/docs/'+chapter['id']);self.assertEqual(page.status_code,200,chapter)
            self.assertIn('html',page.json)
        response=client.get('/api/docs/interface/source');self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(client.get('/api/docs/not-a-chapter').status_code,400)

    def test_unicode_upload_names_are_display_metadata_not_paths(self):
        client=application.app.test_client();headers={'X-Workbench-Token':application.TOKEN}
        with tempfile.TemporaryDirectory() as tmp:
            from temporary_files import TemporaryWorkspace
            workspace=TemporaryWorkspace(Path(tmp))
            with patch.object(application,'TEMPORARY',workspace),ExitStack() as cleanup:
                cleanup.callback(workspace.best_effort_cleanup)
                response=client.post('/api/import',json={'zip':'Συλλογή Łódź 🎧.zip','xml':'Český Русский.xml'},headers=headers)
                self.assertEqual(response.status_code,200,response.json)
                info=json.loads((workspace.folder(response.json['session'])/'upload.json').read_text(encoding='utf-8'))
                self.assertEqual(info['zip'],'Συλλογή Łódź 🎧.zip');self.assertEqual(info['xml'],'Český Русский.xml')
                for bad in ('bad\0.zip','bad\ud800.zip'):
                    response=client.post('/api/import',json={'zip':bad,'xml':'ok.xml'},headers=headers);self.assertEqual(response.status_code,400)
                self.assertEqual(client.post('/api/import',json=[],headers=headers).status_code,400)
