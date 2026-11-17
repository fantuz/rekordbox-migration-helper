"""Bounded, read-only format evidence. Structural validity never proves playback readiness."""
from collections import Counter
from pathlib import PurePosixPath
import binascii
import struct

SETTINGS = {'mysetting.dat':40, 'mysetting2.dat':40, 'devsetting.dat':32, 'djmmysetting.dat':52}
CATALOGS = {'export.pdb', 'exportext.pdb', 'exportlibrary.db'}
PROBE_LIMIT = 2 * 1024**2
MAX_STEM_FRAMES = 44100 * 60 * 60 * 12


def basename(name):
    return PurePosixPath(str(name).replace('\\', '/')).name.casefold()


def format_candidate(name):
    return basename(name) in SETTINGS.keys() | CATALOGS


def inspect_format(name, prefix, size):
    """Inspect a bounded prefix and independently supplied logical size, without allocations from headers."""
    result = {'validation':'unsupported', 'format':'unknown', 'detail':'Filename candidate; binary format is unrecognized',
              'native_stems_readiness':None, 'source_association':'unknown'}
    name = basename(name)
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
        return finish('recognized', 'recordbox_stems_v1',
                      'Recordbox four-source cache layout recognized; source audio, model and native readiness are unknown',
                      frames=frames, duration_seconds=frames/44100, sample_rate=44100, channels=8,
                      source_order=['drums','bass','other','vocals'], encoding='planar_pcm16_le',
                      payload_verified=False, association_metadata_present=False)
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
    if name.endswith(('.dat','.ext','.2ex','.3ex')) and name.startswith('anlz'):
        return finish('corrupt', 'anlz', 'Expected PMAI analysis header is absent')
    if name.endswith('.rbsc'):
        return finish('unsupported', 'rbsc_candidate', 'Documented DRUM CAPTURE filename type; binary contents are not decoded',
                      account_restrictions=True, whole_track_stems=False)
    if len(prefix) >= 12 and prefix[4:8] == b'ftyp':
        return finish('unsupported', 'iso_media_candidate',
                      'ISO media container signature found; stem streams, codec and target-player support are not validated')
    return result


def inspect_anlz(data, size, base):
    result = {**base, 'format':'anlz', 'sections':[], 'cue_groups':[], 'tempo_evidence':[],
              'phrase_evidence':False, 'vocal_activity_evidence':False}
    def finish(state, detail):
        result.update(validation=state, detail=detail)
        return result
    if len(data) < 12:
        return finish('corrupt', 'Truncated PMAI header')
    header, total = struct.unpack_from('>II', data, 4)
    if not 12 <= header <= total or total != size:
        return finish('corrupt', 'Invalid PMAI header or declared file length')
    offset = header
    counts = Counter()
    while offset < total:
        if len(result['sections']) >= 1024:
            return finish('not_checked', 'Analysis section-count budget reached')
        if offset + 12 > total:
            return finish('corrupt', 'Truncated analysis section header')
        if offset + 12 > len(data):
            return finish('not_checked', 'Analysis section headers exceed the inspection byte budget')
        raw_tag = data[offset:offset+4]
        if any(c < 32 or c > 126 for c in raw_tag):
            return finish('corrupt', 'Invalid analysis section identifier')
        tag = raw_tag.decode('ascii')
        hlen, length = struct.unpack_from('>II', data, offset+4)
        if not 12 <= hlen <= length or offset + length > total:
            return finish('corrupt', 'Invalid analysis section length')
        section = {'tag':tag, 'offset':offset, 'header_bytes':hlen, 'bytes':length}
        result['sections'].append(section);counts[tag] += 1
        # Read semantic fields only within this section, never from a following one.
        available = min(offset+length, len(data))
        if tag == 'PQTZ':
            if hlen < 24 or length < 24 or offset+24 > available:
                return finish('corrupt' if offset+24 <= len(data) else 'not_checked', 'Incomplete PQTZ header')
            n = struct.unpack_from('>I', data, offset+20)[0]
            if hlen + n*8 != length:
                return finish('corrupt', 'PQTZ beat count disagrees with section length')
            if offset+length <= len(data):
                tempos = set();previous = -1
                for at in range(offset+hlen, offset+length, 8):
                    beat, bpm100, ms = struct.unpack_from('>HHI', data, at)
                    if not 1 <= beat <= 4 or bpm100 == 0 or ms < previous:
                        return finish('corrupt', 'PQTZ contains invalid beats, tempo or nonmonotonic times')
                    tempos.add(bpm100/100);previous = ms
                result['tempo_evidence'].append({'tag':tag, 'beats':n, 'bpms':sorted(tempos)[:256],
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
        result['phrase_evidence'] |= tag == 'PSSI'
        result['vocal_activity_evidence'] |= tag == 'PVDI'
        offset += length
    result['section_counts'] = dict(counts)
    return finish('recognized', 'Analysis section framing recognized; phrase and vocal-activity tags do not establish STEMS readiness')


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
            try:entry['comment']=data[cursor+44:cursor+44+n].decode('utf-16-be').rstrip('\x00')
            except UnicodeError:return {**result,'entry_validation':'corrupt','entry_detail':'Invalid extended cue UTF-16 comment'}
        if len(result['positions'])<64:result['positions'].append(entry)
        cursor+=length
    if cursor!=end:return {**result,'entry_validation':'corrupt','entry_detail':'Cue entry count leaves unaccounted bytes'}
    return result
