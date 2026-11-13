"""Saved track-colour evidence. No universal mood or set-role inference."""
import re

PALETTE=(('Pink','#FF007F'),('Red','#FF0000'),('Orange','#FFA500'),('Yellow','#FFFF00'),
         ('Green','#00FF00'),('Turquoise','#25FDE9'),('Blue','#0000FF'),('Violet','#660099'))


def rgb(value):
    if isinstance(value,int) and not isinstance(value,bool):return '#'+format(value,'06X') if 0<=value<=0xFFFFFF else None
    match=re.fullmatch(r'(?:#|0x)?([0-9a-f]{6})',str(value or '').strip(),re.I)
    return '#'+match[1].upper() if match else None


def colour(status='unknown',key='unknown',name='Colour not captured',hex_value=None,basis='Unavailable'):
    return {'color_status':status,'color_key':key,'color_name':name,'color_hex':hex_value,'color_basis':basis}


def native_colour(identity,row=None,available=True):
    if not available:return colour()
    if identity in (None,'',0,'0'):return colour('unassigned','unassigned','No assigned colour',basis='Native ColorID is empty/zero')
    row=row or {};code=rgb(row.get('ColorCode'));label=str(row.get('Commnt') or '').strip()
    try:position=int(row.get('SortKey'))
    except (ValueError,TypeError):position=0
    basis='Saved native ColorCode' if code else 'Assigned native ColorID; RGB unavailable'
    if not code and 1<=position<=len(PALETTE):
        default,code=PALETTE[position-1];label=label or default
        basis='Standard rekordbox palette inferred from native SortKey; not a decoded RGB value'
    return colour('assigned','native:'+str(identity),label or code or 'Assigned colour '+str(identity),code,basis)


def xml_colour(value):
    if value is None:return colour()
    if value=='':return colour('unassigned','unassigned','No assigned colour',basis='Empty exported Colour field')
    code=rgb(value)
    if not code:return colour(name='Unrecognized Colour value',basis='Exported value is not supported RGB syntax')
    label=next((name for name,hex_value in PALETTE if hex_value==code),code)
    return colour('assigned','rgb:'+code,label,code,'Exported Colour RGB value')


def editable_colour(track):
    """Canonical sidecar value; unknown remains distinct from unassigned."""
    if track.get('color_status')=='unassigned':return ''
    return rgb(track.get('color_hex')) if track.get('color_status')=='assigned' else None


def colour_baseline(track):
    return {key:track.get(key) for key in ('color_status','color_key','color_hex','color_basis')}


def colour_support(columns,rows,clearable=False,clear_reason='Native clear representation is not verified'):
    """Map the palette to actual configured rows; IDs are never palette indexes."""
    available='ColorID' in columns.get('djmdContent',set()) and 'ID' in columns.get('djmdColor',set())
    palette=[]
    for name,code in PALETTE:
        matches=[r for r in rows if native_colour(r.get('ID'),r)['color_hex']==code and r.get('ID') not in (None,'',0,'0')]
        supported=available and len(matches)==1
        palette.append({'name':name,'value':code,'hex':code,'supported':supported,
                        'native_name':str(matches[0].get('Commnt') or '') if supported else '',
                        'reason':'' if supported else ('Native colour schema is unavailable' if not available else 'No unique configured native colour row matches this RGB value')})
    palette.append({'name':'No assigned colour','value':'','hex':None,'supported':clearable,
                    'reason':'' if clearable else clear_reason})
    return {'mode':'native','palette':palette}


def xml_colour_support():
    return {'mode':'xml','palette':[{'name':name,'value':code,'hex':code,'supported':True,'reason':''} for name,code in PALETTE]+[
        {'name':'No assigned colour','value':'','hex':None,'supported':True,'reason':''}]}


def snapshot_colour_support(snapshot):
    support=snapshot.get('colour_edit_support')
    if support:return support
    reason='Capture this library again to enable verified colour edits'
    return {'mode':'unsupported','palette':[{'name':name,'value':code,'hex':code,'supported':False,'reason':reason} for name,code in PALETTE]+[
        {'name':'No assigned colour','value':'','hex':None,'supported':False,'reason':reason}]}


def native_clear_value(db,identity=None):
    """Preserve an existing empty ID convention, then use the declared schema."""
    column=next((c for c in db.execute('PRAGMA table_info(djmdContent)') if c[1]=='ColorID'),None)
    if column is None:raise ValueError('Native colour export is unsupported: ColorID is unavailable')
    if identity is not None:
        current=db.execute('SELECT ColorID FROM djmdContent WHERE ID=?',(identity,)).fetchone()
        if current and current[0] in (None,'',0,'0'):return current[0]
    empty=db.execute("SELECT ColorID FROM djmdContent WHERE ColorID IS NULL OR ColorID IN ('',0,'0') LIMIT 1").fetchone()
    if empty:return empty[0]
    if not column[3]:return None
    default=str(column[4]).strip()
    if default in ("'0'",'"0"',"''",'""'):
        value=default[1:-1]
        return int(value) if value and 'INT' in str(column[2]).upper() else value
    if default=='0':return '0' if any(t in str(column[2]).upper() for t in ('CHAR','CLOB','TEXT')) else 0
    raise ValueError('Native colour export cannot safely clear this required ColorID representation')


def native_colour_support(db,columns,rows):
    try:native_clear_value(db);clearable=True;reason=''
    except ValueError as error:clearable=False;reason=str(error)
    return colour_support(columns,rows,clearable,reason)
