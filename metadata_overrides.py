"""Explicit, validated field edits applied only to generated library copies."""
from datetime import datetime,timezone

FIELDS=('title','artist','year','rating','album','genre','comment')
XML_FIELDS={'title':'Name','artist':'Artist','year':'Year','rating':'Rating','album':'Album','genre':'Genre','comment':'Comments'}


def validate(field,value):
    if field not in FIELDS:raise ValueError('Choose title, artist, year, rating, album, genre or comment')
    if field=='comment':
        value='' if value is None else str(value)
        if len(value)>4096 or any((ord(c)<32 and c not in '\t\n\r') or 0xD800<=ord(c)<=0xDFFF or ord(c) in (0xFFFE,0xFFFF) for c in value):
            raise ValueError('Comments support up to 4,096 characters, including line breaks and tabs, without invalid XML/control characters')
        return value
    if field in ('year','rating'):
        if value in (None,''):
            return 0 if field=='rating' else None
        try:number=int(value)
        except (ValueError,TypeError):raise ValueError('Enter a whole-number '+field) from None
        if isinstance(value,bool) or str(number)!=str(value).strip():raise ValueError('Enter a whole-number '+field)
        if field=='rating' and not 0<=number<=5:raise ValueError('Personal stars must be a whole number from 0 to 5')
        if field=='year' and not 1000<=number<=datetime.now(timezone.utc).year+1:raise ValueError('Enter a plausible four-digit year, or clear it')
        return number
    value='' if value is None else str(value).strip()
    if len(value)>255 or any(ord(c)<32 for c in value):raise ValueError('Use at most 255 characters without control characters')
    return value


def comparable(field,value):
    if field=='year' and value in (None,'',0):return None
    if field=='rating' and value is None:return 0
    return value or '' if field in ('title','artist','album','genre','comment') else value


def plan(catalog,mapping):
    result={}
    for track_id,fields in catalog.metadata.get('field_overrides',{}).items():
        if track_id not in catalog.tracks:raise ValueError('A metadata override refers to a track outside this workspace')
        keeper=mapping.get(track_id,track_id)
        for field,value in fields.items():
            value=validate(field,value)
            if field in result.get(keeper,{}) and result[keeper][field]!=value:
                raise ValueError('Merged siblings have conflicting '+field+' overrides. Reset one or choose the same value.')
            result.setdefault(keeper,{})[field]=value
    return result


def apply_xml(element,fields):
    for field,value in fields.items():
        key=XML_FIELDS[field]
        if field=='year' and value is None:element.attrib.pop(key,None)
        else:element.set(key,str(value*51 if field=='rating' else value))


def apply_native(db,tables,edits,update,timestamp,next_usn):
    """Update only a detached export DB, including exact named lookup rows."""
    from secrets import randbelow
    from uuid import uuid4
    named={'artist':('djmdArtist','ArtistID'),'album':('djmdAlbum','AlbumID'),'genre':('djmdGenre','GenreID')}
    columns={'title':'Title','year':'ReleaseYear','rating':'Rating','comment':'Commnt'}
    cache={};created=0
    def lookup(table,name):
        nonlocal created
        if not name:return None
        key=(table,name)
        if key in cache:return cache[key]
        if not {'ID','Name','UUID','rb_local_deleted'}<=tables.get(table,set()):raise ValueError('Unsupported metadata lookup schema: '+table)
        matches=list(db.execute('SELECT ID FROM "'+table+'" WHERE Name=? COLLATE BINARY AND coalesce(rb_local_deleted,0)=0',(name,)))
        if len(matches)>1:raise ValueError('Multiple active exact-name rows in '+table+'; review this value first')
        if matches:cache[key]=matches[0][0];return cache[key]
        identity=str(randbelow(2**28-100)+100)
        while db.execute('SELECT 1 FROM "'+table+'" WHERE ID=?',(identity,)).fetchone():identity=str(randbelow(2**28-100)+100)
        values={'ID':identity,'Name':name,'UUID':str(uuid4()),'created_at':timestamp,'updated_at':timestamp,
                'rb_local_deleted':0,'rb_local_synced':0,'rb_local_usn':0,'usn':None,'Compilation':0}
        values={k:v for k,v in values.items() if k in tables[table]}
        for column in db.execute('PRAGMA table_info("'+table+'")'):
            if column[3] and column[4] is None and column[1] not in values:raise ValueError('Unsupported required metadata column: '+table+'.'+column[1])
        if 'rb_local_usn' in values:values['rb_local_usn']=next_usn()
        fields=list(values)
        db.execute('INSERT INTO "'+table+'" ('+','.join('"'+f+'"' for f in fields)+') VALUES ('+','.join('?' for _ in fields)+')',[values[f] for f in fields])
        created+=1;cache[key]=identity;return identity
    for identity,fields in edits.items():
        values={}
        for field,value in fields.items():
            if field in named:
                table,column=named[field];values[column]=lookup(table,value)
            else:values[columns[field]]=0 if field=='year' and value is None else value
        if not set(values)<=tables['djmdContent']:raise ValueError('Unsupported content metadata schema')
        update('djmdContent','ID=? AND rb_local_deleted=0',(identity,),values)
        for field,value in fields.items():
            if field in named:
                table,column=named[field]
                actual=db.execute('SELECT n.Name FROM djmdContent c LEFT JOIN "'+table+'" n ON n.ID=c."'+column+'" WHERE c.ID=?',(identity,)).fetchone()
                expected=value or None
            else:
                actual=db.execute('SELECT "'+columns[field]+'" FROM djmdContent WHERE ID=?',(identity,)).fetchone()
                expected=0 if field=='year' and value is None else value
            if actual is None or actual[0]!=expected:raise ValueError('Native metadata verification failed: '+identity+' / '+field)
    return created
