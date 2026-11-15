"""Strict independent reader for the subset emitted by our Serato draft writer.

No encoder imports or shared field tables. This checks bytes, not Serato acceptance.
It is deliberately not a general-purpose reader for arbitrary Serato libraries.
"""
import re
import struct

MAX_BYTES=64*1024**2


def chunks(data):
    if len(data)>MAX_BYTES:raise ValueError('Serato data exceeds 64 MB')
    offset=0
    while offset<len(data):
        if len(data)-offset<8:raise ValueError('Truncated Serato chunk header')
        tag=data[offset:offset+4]
        if not re.fullmatch(b'[a-z0-9]{4}',tag):raise ValueError('Invalid Serato field tag')
        length=struct.unpack_from('>I',data,offset+4)[0];offset+=8
        if not length or length>len(data)-offset:raise ValueError('Invalid Serato chunk length')
        yield tag.decode('ascii'),data[offset:offset+length]
        offset+=length


def text(data):
    try:return data.decode('utf-16-be',errors='strict')
    except UnicodeError as error:raise ValueError('Invalid Serato UTF-16 text') from error


def relative_path(value):
    if not value or value.startswith(('/', '\\')) or '\\' in value or ':' in value or any(ord(c)<32 for c in value):
        raise ValueError('Invalid Serato relative path')
    if any(part in ('','.','..') for part in value.split('/')):raise ValueError('Invalid Serato path component')
    return value


def records(data,version):
    fields=iter(chunks(data));header=next(fields,None)
    if header is None or header[0]!='vrsn' or text(header[1])!=version:
        raise ValueError('Unexpected Serato version header')
    for tag,payload in fields:
        if tag!='otrk':raise ValueError('Unexpected Serato object')
        values={}
        for name,value in chunks(payload):
            if name in values:raise ValueError('Duplicate Serato field')
            values[name]=text(value)
        yield values


def read_database(data):
    result=[];paths=set()
    allowed={'pfil','ttyp','tsng','tart','talb','tgen','tbpm','tkey','ttyr','tlbl','tcmp','tcom','tlen'}
    for row in records(data,'2.0/Serato Scratch LIVE Database'):
        if set(row)-allowed or 'pfil' not in row:raise ValueError('Unexpected Serato database fields')
        path=relative_path(row['pfil'])
        if path in paths:raise ValueError('Duplicate Serato database path')
        paths.add(path);result.append(row)
        if len(result)>100000:raise ValueError('Too many Serato records')
    return result


def read_crate(data):
    result=[]
    for row in records(data,'1.0/Serato ScratchLive Crate'):
        if set(row)!={'ptrk'}:raise ValueError('Unexpected Serato crate fields')
        result.append(relative_path(row['ptrk']))
    return result


def validate_export(database,crates,expected_records,expected_crates):
    decoded=read_database(database)
    if decoded!=expected_records:raise ValueError('Serato database readback differs from the export plan')
    paths={row['pfil'] for row in decoded}
    if set(crates)!=set(expected_crates):raise ValueError('Serato crate inventory differs from the export plan')
    entries=0
    for name,data in crates.items():
        rows=read_crate(data)
        if rows!=expected_crates[name]:raise ValueError('Serato crate order differs from the export plan')
        if any(path not in paths for path in rows):raise ValueError('Serato crate references a missing database record')
        entries+=len(rows)
    return {'status':'passed','database_records':len(decoded),'crate_files':len(crates),'crate_entries':entries,
            'checks':['chunk_lengths','strict_utf16','metadata_readback','crate_order','database_references'],
            'serato_application_verified':False}
