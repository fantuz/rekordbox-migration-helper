"""Interface catalogues only. Library metadata and machine-readable keys stay raw."""
import json
from pathlib import Path
import re

LANGUAGES={'en':'English','de':'Deutsch','fr':'Français','it':'Italiano','es':'Español',
           'el':'Ελληνικά','pl':'Polski','cs':'Čeština','ru':'Русский'}
PLACEHOLDERS=re.compile(r'\{([a-zA-Z][a-zA-Z0-9_]*)\}')


def catalogues(assets):
    messages=json.loads((Path(assets)/'locales.json').read_text(encoding='utf-8'))['messages']
    return {code:{key:values.get(code,key) for key,values in messages.items()} for code in LANGUAGES}


def script_data(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')


def browser_catalogues(assets):
    return 'window.WORKBENCH_LOCALES='+script_data({'languages':LANGUAGES,'messages':catalogues(assets)})+';'


def register(app, assets):
    from flask import Response
    @app.get('/api/i18n.js')
    def interface_catalogues():
        return Response(browser_catalogues(assets),mimetype='text/javascript',headers={'Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'})
