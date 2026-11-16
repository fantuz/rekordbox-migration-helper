"""Advisory captured metadata flags, independent of live audio availability."""
from metadata_export import number

FLAGS = {'zero_duration': 'Zero duration', 'zero_size': 'Zero recorded size'}


def flags(track):
    result=[]
    duration=track.get('duration',track.get('duration_seconds'))
    size=track.get('size',track.get('size_bytes'))
    # bools, blanks and unknown values are not recorded numeric zero.
    for key,value in (('zero_duration',duration),('zero_size',size)):
        if value is not None and not isinstance(value,bool) and str(value).strip() and number(value)==0:
            result.append(key)
    return result


def checked_flag(value):
    if value not in ('',*FLAGS):raise ValueError('Choose a supported metadata flag.')
    return value
