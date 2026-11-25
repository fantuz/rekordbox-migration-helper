"""Bounded, read-only format evidence. Structural validity never proves playback readiness."""
from collections import Counter
from pathlib import Path, PurePosixPath
import binascii
import struct
from native_embedding import embedding_owner
from stems_formats import inspect_iso,inspect_cache_file,ContainerLimit,RECORDBOX_SAVED_NAME

SETTINGS = {'mysetting.dat':40, 'mysetting2.dat':40, 'devsetting.dat':32, 'djmmysetting.dat':52}
CATALOGS = {'export.pdb', 'exportext.pdb', 'exportlibrary.db'}
PROBE_LIMIT = 2 * 1024**2
MAX_STEM_FRAMES = 44100 * 60 * 60 * 12
# Observed PSSI format bytes, rotated by version and adjusted by the entry count.
PSSI_MASK = bytes.fromhex('cb e1 ee fa e5 ee ad ee e9 d2 e9 eb e1 e9 f3 e8 e9 f4 e1')


def basename(name):
    return PurePosixPath(str(name).replace('\\', '/')).name.casefold()


def format_candidate(name):
    return basename(name) in SETTINGS.keys() | CATALOGS


def inspect_format(name, prefix, size,read_at=None,provider_context=False):
    """Inspect a bounded prefix and independently supplied logical size, without allocations from headers."""
    result = {'validation':'unsupported', 'format':'unknown', 'detail':'Filename candidate; binary format is unrecognized',
              'native_stems_readiness':None, 'source_association':'unknown'}
    def finish(state, kind, detail, **facts):
        return {**result, 'validation':state, 'format':kind, 'detail':detail, **facts}
    if prefix.startswith(b'PDSTEMS1'):
        if len(prefix) < 16:
            return finish('corrupt', 'recordbox_stems_v1', 'Truncated Recordbox STEMS header')
        frames = struct.unpack_from('<Q', prefix, 8)[0]
        if frames == 0 or size != 16 + frames * 16:
            return finish('corrupt', 'recordbox_stems_v1', 'Invalid STEMS frame count or body length', frames=frames)
        if frames > MAX_STEM_FRAMES:
            return finish('not_checked', 'recordbox_stems_v1', 'STEMS duration exceeds the bounded inspection policy',frames=frames)
        saved_name = RECORDBOX_SAVED_NAME.fullmatch(Path(str(name)).name)
        identity = {}
        detail = 'Recordbox four-source cache layout recognized. The filename does not identify a saved model.'
        if saved_name:
            key, model = saved_name.groups()
            variant = 'speed' if model == 'htdemucs' else 'quality'
            identity = {'recordbox_key':key, 'recordbox_model':model, 'recordbox_variant':variant,
                        'recordbox_model_basis':'filename'}
            detail = f'Recordbox four-source cache layout recognized. The filename identifies the {variant} model ({model}).'
        return finish('recognized', 'recordbox_stems_v1', detail, **identity,
                      frames=frames, duration_seconds=frames/44100, sample_rate=44100, channels=8,
                      source_order=['drums','bass','other','vocals'], encoding='planar_pcm16_le',
                      payload_verified=False, association_metadata_present=False,
                      cache_retention='unknown', cache_eviction_possible=True,
                      cache_lifecycle_note='Current Recordbox source can evict caches to enforce a disk budget; retention is not recorded in this header')
    name = basename(name)
    if name in SETTINGS:
        if len(prefix) < 108 or size < 108:
            return finish('corrupt', 'player_settings', 'Truncated player-settings header')
        header, length = struct.unpack_from('<I', prefix, 0)[0], struct.unpack_from('<I', prefix, 100)[0]
        if header != 96 or size != 108 + length:
            return finish('corrupt', 'player_settings', 'Unexpected settings header, payload length or file size')
        if length != SETTINGS[name]:
            return finish('unsupported', 'player_settings', 'Unrecognized settings payload revision; checksum semantics were not assumed')
        if len(prefix) < size:
            return finish('not_checked', 'player_settings', 'Settings bytes exceed the inspection budget')
        end = 104 + length
        stored = struct.unpack_from('<I', prefix, end)[0]
        calculated = binascii.crc_hqx(prefix[:end] if name == 'djmmysetting.dat' else prefix[104:end], 0)
        return finish('recognized' if stored == calculated else 'corrupt', 'player_settings',
                      'Settings layout and CRC16/XMODEM match' if stored == calculated else 'Settings CRC16/XMODEM mismatch',
                      payload_bytes=length, crc_valid=stored == calculated,
                      crc_scope='header_and_payload' if name == 'djmmysetting.dat' else 'payload')
    if name == 'exportlibrary.db':
        return finish('unsupported', 'onelibrary_catalog',
                      'OneLibrary catalog filename detected; schema, encryption and records were not decoded',
                      catalog_layer='OneLibrary', classic_catalog_updates_apply=False)
    if name in ('export.pdb', 'exportext.pdb'):
        if len(prefix) < 28:
            return finish('corrupt', 'device_sql', 'Truncated DeviceSQL file header')
        zero, page_size, count = struct.unpack_from('<III', prefix, 0)
        if zero != 0 or page_size not in (512,1024,2048,4096,8192,16384,32768,65536) or count > 64 or size % page_size:
            return finish('corrupt', 'device_sql', 'Invalid DeviceSQL page size, table count or file alignment')
        if 28 + count * 16 > len(prefix):
            return finish('not_checked', 'device_sql', 'DeviceSQL table pointers exceed the inspection budget')
        tables = [struct.unpack_from('<4I', prefix, 28 + i*16) for i in range(count)]
        pages = size // page_size
        if len({t[0] for t in tables}) != count or any(t[2] >= pages or t[3] >= pages for t in tables):
            return finish('corrupt', 'device_sql', 'Duplicate table types or out-of-range DeviceSQL page pointers')
        return finish('recognized', 'device_sql', 'Classic device catalog header recognized; track rows and player compatibility were not decoded',
                      page_size=page_size, table_count=count, table_types=[t[0] for t in tables],
                      catalog_layer='classic_device', records_decoded=False)
    if prefix.startswith(b'PMAI'):
        return inspect_anlz(prefix, size, result)
    if name.startswith('anlz') and name.endswith('.3ex'):
        owner = embedding_owner(prefix) if len(prefix) == size else None
        if owner is not None:
            return finish('recognized', 'anlz_3ex', 'Known desktop embedding layout checked',
                          embedding_signature=True, embedding_profile_validated=True,
                          track_id_assigned=owner != '0', payload_verified=False)
        embedding = prefix.startswith((b'\x81\xa9embedding', b'\x81\xd9\x09embedding'))
        return finish('unsupported', 'anlz_3ex',
                      'Possible MessagePack embedding signature; payload is not decoded' if embedding else
                      'Non-PMAI .3EX analysis variant; payload is not decoded',
                      embedding_signature=embedding, payload_verified=False)
    cache=inspect_cache_file(name,prefix,size,provider_context)
    if cache is not None:return cache
    if name.endswith(('.dat','.ext','.2ex')) and name.startswith('anlz'):
        return finish('corrupt', 'anlz', 'Expected PMAI analysis header is absent')
    if name.endswith('.rbsc'):
        return finish('unsupported', 'rbsc_candidate', 'Documented DRUM CAPTURE filename type; binary contents are not decoded',
                      account_restrictions=True, whole_track_stems=False)
    if len(prefix) >= 12 and prefix[4:8] == b'ftyp':
        def bounded(at,length):
            if at+length>len(prefix):raise ContainerLimit('Required container metadata is outside the bounded prefix')
            return prefix[at:at+length]
        return inspect_iso(read_at or bounded,size)
    return result


def anlz_sections(data, size):
    """Return bounded section positions and distinguish malformed input from an incomplete probe."""
    sections = []
    if len(data) < 12 or data[:4] != b'PMAI':
        return sections, 'corrupt', 'Invalid or truncated PMAI header'
    header, total = struct.unpack_from('>II', data, 4)
    if not 12 <= header <= total or total != size:
        return sections, 'corrupt', 'Invalid PMAI header or declared file length'
    offset = header
    while offset < total:
        if len(sections) >= 1024:
            return sections, 'not_checked', 'Analysis section-count budget reached'
        if offset + 12 > total:
            return sections, 'corrupt', 'Truncated analysis section header'
        if offset + 12 > len(data):
            return sections, 'not_checked', 'Analysis section headers exceed the inspection byte budget'
        raw_tag = data[offset:offset+4]
        if any(c < 32 or c > 126 for c in raw_tag):
            return sections, 'corrupt', 'Invalid analysis section identifier'
        tag = raw_tag.decode('ascii')
        hlen, length = struct.unpack_from('>II', data, offset+4)
        if not 12 <= hlen <= length or offset + length > total:
            return sections, 'corrupt', 'Invalid analysis section length'
        section = {'tag':tag, 'offset':offset, 'header_bytes':hlen, 'bytes':length}
        sections.append(section)
        offset += length
    return sections, 'recognized', ''


def inspect_anlz(data, size, base):
    result = {**base, 'format':'anlz', 'sections':[], 'cue_groups':[], 'tempo_evidence':[], 'extended_grid_evidence':[],
              'beat_grid_evidence':[], 'phrase_structure_evidence':[],
              'phrase_evidence':False, 'vocal_activity_evidence':False}
    def finish(state, detail):
        result.update(validation=state, detail=detail)
        return result
    sections, framing, detail = anlz_sections(data, size)
    counts = Counter()
    for section in sections:
        tag, offset = section['tag'], section['offset']
        hlen, length = section['header_bytes'], section['bytes']
        result['sections'].append(section);counts[tag] += 1
        # Read semantic fields only within this section, never from a following one.
        available = min(offset+length, len(data))
        if tag == 'PQT2':
            grid = {'tag':tag, 'validation':'unsupported',
                    'detail':'Extended-grid revision is not decoded', 'checksum_validation':'not_checked'}
            result['extended_grid_evidence'].append(grid)
            if hlen == 56 and offset+56 <= available:
                revision = struct.unpack_from('>I', data, offset+16)[0]
                grid['revision'] = revision
                if revision in (0x01000002, 0x02000002):
                    n, checksum = struct.unpack_from('>II', data, offset+40)
                    grid.update(beats=n, stored_checksum=checksum)
                    if 56 + n*2 != length:
                        grid.update(validation='corrupt', detail='PQT2 beat count disagrees with section length')
                        return finish('corrupt', 'PQT2 beat count disagrees with section length')
                    if revision == 0x02000002:
                        reserved = data[offset+12:offset+16] + data[offset+20:offset+24] + data[offset+48:offset+56]
                        if any(reserved) or (not n and any(data[offset+24:offset+56])):
                            grid.update(validation='corrupt', detail='Invalid desktop PQT2 header or empty-table marker')
                            return finish('corrupt', grid['detail'])
                        grid['table_state'] = 'populated' if n else 'cleared'
                    grid.update(validation='not_checked', detail='Extended-grid fractions exceed the inspection byte budget')
                    if offset+length <= len(data):
                        low = high = None
                        for (value,) in struct.iter_unpack('>H', memoryview(data)[offset+56:offset+length]):
                            if value > 999:
                                grid.update(validation='corrupt', detail='PQT2 contains an invalid sub-millisecond fraction')
                                return finish('corrupt', 'PQT2 contains an invalid sub-millisecond fraction')
                            low = value if low is None else min(low, value)
                            high = value if high is None else max(high, value)
                        grid.update(validation='recognized', fraction_unit='microseconds within a millisecond',
                                    min_fraction=low, max_fraction=high,
                                    detail='Extended-grid count and fractions checked; matching its checksum requires the companion DAT')
            elif offset+hlen > available:
                grid.update(validation='not_checked', detail='Extended-grid header exceeds the inspection byte budget')
        if tag == 'PQTZ':
            grid = {'tag':tag, 'validation':'unsupported', 'detail':'Beat-grid header revision is not decoded'}
            result['beat_grid_evidence'].append(grid)
            if hlen == 24 and offset+24 <= available:
                n = struct.unpack_from('>I', data, offset+20)[0]
                shift = struct.unpack_from('>h', data, offset+18)[0]
                grid.update(beats=n, header_shift_ms=shift, time_unit='milliseconds')
                if 24 + n*8 != length:
                    grid.update(validation='corrupt', detail='PQTZ beat count disagrees with section length')
                    return finish('corrupt', grid['detail'])
                grid.update(validation='not_checked', detail='Beat-grid entries exceed the inspection byte budget')
            elif hlen == 24:
                grid.update(validation='not_checked', detail='Beat-grid header exceeds the inspection byte budget')
            if hlen == 24 and offset+length <= len(data):
                tempos = set();previous = -1
                first = last = None
                for at in range(offset+hlen, offset+length, 8):
                    beat, bpm100, ms = struct.unpack_from('>HHI', data, at)
                    if not 1 <= beat <= 4 or bpm100 == 0 or ms <= previous:
                        grid.update(validation='corrupt', detail='PQTZ contains invalid beats, tempo or nonmonotonic times')
                        return finish('corrupt', 'PQTZ contains invalid beats, tempo or nonmonotonic times')
                    tempos.add(bpm100/100);previous = ms
                    first = ms if first is None else first;last = ms
                # Signed shifts can retain preroll before zero; report it without clamping or wrapping.
                grid.update(validation='recognized', raw_first_ms=first, raw_last_ms=last,
                            effective_first_ms=None if first is None else first+shift,
                            effective_last_ms=None if last is None else last+shift,
                            has_negative_effective_times=first is not None and first+shift<0,
                            detail='Known beat-grid count, tempo and signed header shift checked; extended-grid association is not inferred')
                result['tempo_evidence'].append({**grid, 'bpms':sorted(tempos)[:256],
                                                'bpms_complete':len(tempos)<=256,'distinct_tempo_count':len(tempos),'unit':'BPM',
                                                'variable_tempo':len(tempos)>1})
        if tag in ('PCOB','PCO2'):
            minimum = 24 if tag == 'PCOB' else 20
            if hlen < minimum or length < minimum:
                return finish('corrupt', 'Incomplete cue-group header')
            if offset+minimum <= available:
                kind = struct.unpack_from('>I', data, offset+12)[0]
                n = struct.unpack_from('>H', data, offset+(18 if tag=='PCOB' else 16))[0]
                group={'tag':tag, 'kind':kind, 'entries':n,'entry_validation':'not_checked'}
                result['cue_groups'].append(group)
                if offset+length <= len(data):
                    group.update(inspect_cues(data,offset+hlen,offset+length,tag,n))
                    if group['entry_validation']=='corrupt':
                        return finish('corrupt',group['entry_detail'])
        if tag == 'PSSI':
            result['phrase_evidence'] = True
            phrases = inspect_phrase_structure(data, offset, hlen, length)
            result['phrase_structure_evidence'].append(phrases)
            if phrases['validation'] == 'corrupt':return finish('corrupt', phrases['detail'])
        result['vocal_activity_evidence'] |= tag == 'PVDI'
    if framing != 'recognized':
        return finish(framing, detail)
    result['section_counts'] = dict(counts)
    return finish('recognized', 'Analysis section framing recognized; phrase and vocal-activity tags do not establish STEMS readiness')


def inspect_phrase_structure(data, start, header, length):
    """Check known PSSI header semantics without decoding phrase entries or guessing future revisions."""
    result = {'tag':'PSSI', 'validation':'unsupported', 'detail':'Phrase-structure header revision is not decoded',
              'entry_semantics_decoded':False, 'native_stems_readiness':None}
    if header != 32:return result
    if start+18 > len(data):
        return {**result, 'validation':'not_checked', 'detail':'Phrase-structure header exceeds the inspection byte budget'}
    version, entry_size, count = struct.unpack_from('>HHH', data, start+12)
    result.update(version=version, entry_bytes=entry_size, entries=count)
    if version not in (0,1) or entry_size != 24:
        return {**result, 'detail':'Phrase-structure version or entry size is not decoded'}
    if 32 + count*24 != length:
        return {**result, 'validation':'corrupt', 'detail':'PSSI entry count disagrees with section length'}
    if start+32 > len(data):
        return {**result, 'validation':'not_checked', 'detail':'Phrase-structure header exceeds the inspection byte budget'}
    body = data[start+18:start+32]
    mood = struct.unpack_from('>H', body)[0]
    encoding = 'unmasked'
    if mood not in (1,2,3):
        # Only the fixed-size header is decoded. The mask is inferred from mood, not authenticated.
        body = bytes(value ^ ((PSSI_MASK[(i+version)%len(PSSI_MASK)]+count)&255)
                     for i,value in enumerate(body))
        mood = struct.unpack_from('>H', body)[0]
        encoding = 'xor_mask_inferred'
    if mood not in (1,2,3):
        return {**result, 'validation':'corrupt', 'detail':'PSSI mood is invalid for the known plain or masked profile'}
    result.update(mood=mood, mood_name={1:'high',2:'mid',3:'low'}[mood], body_encoding=encoding,
                  end_beat=struct.unpack_from('>H', body, 8)[0], bank=body[12])
    if start+length > len(data):
        return {**result, 'validation':'not_checked', 'detail':'Phrase entries exceed the inspection byte budget'}
    return {**result, 'validation':'recognized',
            'detail':'Known phrase header, count and mood checked; phrase-entry semantics and STEMS readiness are not established'}


def inspect_cues(data,start,end,tag,count):
    """Check nested entries independently of the repeated outer groups; retain complementary evidence."""
    result={'entry_validation':'recognized','positions':[],'positions_truncated':count>64}
    minimum=40 if tag=='PCOB' else 44
    if count*minimum>end-start:
        return {**result,'entry_validation':'corrupt','entry_detail':'Cue entry count exceeds section capacity'}
    if count>4096:return {**result,'entry_validation':'not_checked','entry_detail':'Cue entry-count budget reached'}
    cursor=start
    for _ in range(count):
        if cursor+12>end:return {**result,'entry_validation':'corrupt','entry_detail':'Truncated cue entry header'}
        hlen,length=struct.unpack_from('>II',data,cursor+4)
        expected=b'PCPT' if tag=='PCOB' else b'PCP2'
        if data[cursor:cursor+4]!=expected:
            return {**result,'entry_validation':'unsupported','entry_detail':'Unrecognized nested cue-entry type'}
        if not 12<=hlen<=length or length<minimum or cursor+length>end:
            return {**result,'entry_validation':'corrupt','entry_detail':'Invalid nested cue-entry length'}
        if hlen!=(28 if tag=='PCOB' else 16):
            return {**result,'entry_validation':'unsupported','entry_detail':'Unrecognized cue-entry header revision'}
        hot=struct.unpack_from('>I',data,cursor+12)[0]
        kind=data[cursor+(28 if tag=='PCOB' else 16)]
        time_at=cursor+(32 if tag=='PCOB' else 20)
        in_ms,out_ms=struct.unpack_from('>II',data,time_at)
        entry={'hot_cue_number':hot,'kind':kind,'in_ms':in_ms,'out_ms':out_ms,
               'active_loop':struct.unpack_from('>I',data,cursor+16)[0]==4 if tag=='PCOB' else None}
        if kind not in (1,2):result.update(entry_validation='unsupported',entry_detail='Unrecognized cue type retained')
        if kind==2 and (out_ms==2**32-1 or out_ms<=in_ms):
            return {**result,'entry_validation':'corrupt','entry_detail':'Cue loop end does not follow its start'}
        if tag=='PCO2':
            n=struct.unpack_from('>I',data,cursor+40)[0]
            if n%2 or 44+n>length:
                return {**result,'entry_validation':'corrupt','entry_detail':'Invalid extended cue comment length'}
            comment=data[cursor+44:cursor+44+n]
            if n and comment[-2:]!=b'\x00\x00':
                return {**result,'entry_validation':'corrupt','entry_detail':'Extended cue comment is missing its UTF-16 terminator'}
            try:entry['comment']=(comment[:-2] if n else comment).decode('utf-16-be')
            except UnicodeError:return {**result,'entry_validation':'corrupt','entry_detail':'Invalid extended cue UTF-16 comment'}
        if len(result['positions'])<64:result['positions'].append(entry)
        cursor+=length
    if cursor!=end:return {**result,'entry_validation':'corrupt','entry_detail':'Cue entry count leaves unaccounted bytes'}
    return result
