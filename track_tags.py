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
