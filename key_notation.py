"""Conservative key-tag display aliases; never analyze audio or rewrite a tag."""
from collections import Counter
import re
import unicodedata

from chart_views import unknown_text,UNKNOWN_TEXT

MODES=('source','alpha','camelot','open_key')
MISSING='key:missing'
UNRECOGNIZED='key:unrecognized'
KEYS={}
ALIASES={}


def normalized(value):
    text=unicodedata.normalize('NFKC',str(value or '')).strip().replace('♯','#').replace('♭','b')
    # CM means C major; Cm means C minor. Preserve this distinction before folding.
    if re.fullmatch(r'[A-Ga-g][#b]?M',text):text=text[:-1]+'major'
    return re.sub(r'\s+','',text).casefold()


_MAJOR=(11,6,1,8,3,10,5,0,7,2,9,4)
_MINOR=(8,3,10,5,0,7,2,9,4,11,6,1)
_NAMES={'major':('C','Db','D','Eb','E','F','F#','G','Ab','A','Bb','B'),
        'minor':('Cm','C#m','Dm','Ebm','Em','Fm','F#m','Gm','Abm','Am','Bbm','Bm')}
for mode,pitches in (('major',_MAJOR),('minor',_MINOR)):
    for number,pitch in enumerate(pitches,1):
        identity=f'key:{pitch}:{mode}'
        camelot=str(number)+('A' if mode=='minor' else 'B')
        open_key=str((number+4)%12+1)+('m' if mode=='minor' else 'd')
        KEYS[identity]={'alpha':_NAMES[mode][pitch],'camelot':camelot,'open_key':open_key,
                        'pitch_class':pitch,'mode':mode}
        ALIASES[normalized(camelot)]=identity
        ALIASES[normalized(open_key)]=identity
        ALIASES[normalized(f'{number:02}'+camelot[-1])]=identity
        ALIASES[normalized(f'{(number+4)%12+1:02}'+open_key[-1])]=identity
for letter,pitch in {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}.items():
    for accidental,offset in (('',0),('#',1),('b',-1)):
        root=letter+accidental
        for mode,suffixes in (('major',('','maj','major')),('minor',('m','min','minor'))):
            for suffix in suffixes:ALIASES[normalized(root+suffix)]=f'key:{(pitch+offset)%12}:{mode}'


def notation(value='source'):
    if value not in MODES:raise ValueError('Choose alphabetical, Camelot or Open Key display')
    return value


def parse(value):
    return ALIASES.get(normalized(value))


def group(value):
    return parse(value) or (MISSING if unknown_text(value) else UNRECOGNIZED)


def selected_group(value):
    if not isinstance(value,str):raise ValueError('Choose a saved musical key')
    if value.startswith('key:') and value not in KEYS and value not in (MISSING,UNRECOGNIZED):
        raise ValueError('Choose a recognized key group')
    return value if value in KEYS or value in (MISSING,UNRECOGNIZED) else group(value)


def label(identity,mode):
    mode=notation(mode)
    if identity in KEYS:return KEYS[identity]['alpha' if mode=='source' else mode]
    return 'Unknown / not captured' if identity==MISSING else 'Unrecognized key'


def source_counts(rows):
    counts=Counter()
    for row in rows:
        value=row.get('tonality')
        if unknown_text(value):kind='unknown'
        elif not parse(value):kind='unrecognized'
        elif re.fullmatch(r'(?:0?[1-9]|1[0-2])[ab]',normalized(value)):kind='camelot'
        elif re.fullmatch(r'(?:0?[1-9]|1[0-2])[dm]',normalized(value)):kind='open_key'
        else:kind='alphabetical'
        counts[kind]+=1
    return {**{key:counts[key] for key in ('alphabetical','camelot','open_key','unknown','unrecognized')},
            'numerical':counts['camelot']+counts['open_key'],'total':sum(counts.values())}


def breakdown(rows,limit=50):
    counts=Counter(row.get('tonality') or '' for row in rows)
    return [{'value':key,'tracks':count} for key,count in sorted(counts.items(),key=lambda item:(-item[1],item[0].casefold()))[:limit]]


def options(rows,mode):
    mode=notation(mode)
    counts=Counter(group(row.get('tonality')) for row in rows)
    return [{'key':key,'label':label(key,mode),'known':key in KEYS,'tracks':count}
            for key,count in sorted(counts.items(),key=lambda item:(item[0] not in KEYS,label(item[0],mode).casefold()))]


def register(app):
    from flask import Response
    from localization import script_data
    @app.get('/api/key-notation.js')
    def key_notation_data():
        return Response('window.WORKBENCH_KEY_NOTATION='+script_data({'keys':KEYS,'aliases':ALIASES,'unknown':sorted(UNKNOWN_TEXT)})+';',
                        mimetype='text/javascript',headers={'Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'})
