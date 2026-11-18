"""Display-only chart projections. Unknown exclusion never changes a collection."""
from collections import Counter
from datetime import date
import re
import unicodedata

UNKNOWN_TEXT={'','unknown','unknown genre','unknown key','unclassified','no genre','none','n/a','n a','na','not set','?','null'}


def unknown_text(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().split()) in UNKNOWN_TEXT


def hide_unknown(value=False):
    if value in (False,None,'','0','false'):return False
    if value in (True,'1','true'):return True
    raise ValueError('Choose a supported unknown-value display filter')


def release_year(track):
    for field in ('year','release_year','ReleaseYear','release_date'):
        value=track.get(field)
        if isinstance(value,bool):continue
        if isinstance(value,(int,float)) and 1000<=value<=2999 and value==int(value):return str(int(value))
        text=str(value or '').strip()
        if re.fullmatch(r'[12]\d{3}',text):return text
        if re.fullmatch(r'[12]\d{3}-\d{2}(?:-\d{2})?',text):
            try:date.fromisoformat(text if len(text)==10 else text+'-01')
            except ValueError:continue
            return text[:4]
    return None


def chart(rows,unknown,total,hide):
    values=[dict(row) for row in rows]
    if unknown and not hide:values.append({'label':'Unknown','count':unknown,'unknown':True})
    return {'rows':values,'unknown':unknown,'excluded':unknown if hide else 0,
            'total':total,'known':total-unknown,'displayed':sum(row['count'] for row in values)}


def collection_charts(tracks,duration_bins,addition_dates,hide=False):
    hide=hide_unknown(hide);total=len(tracks)
    years=Counter(release_year(t) for t in tracks)
    genres=Counter(str(t.get('genre') or '').strip() for t in tracks if not unknown_text(t.get('genre')))
    genre_rows=[{'label':label,'count':count} for label,count in sorted(genres.items(),key=lambda p:(-p[1],p[0].casefold(),p[0]))]
    # Bound chart rendering even for a library with a unique tag per entry.
    if len(genre_rows)>60:
        remaining=genre_rows[60:]
        genre_rows=genre_rows[:60]+[{'label':'Other saved genres','count':sum(row['count'] for row in remaining),'other':True,'categories':len(remaining)}]
    result={
        'duration':chart(duration_bins,sum(t.get('duration',t.get('duration_seconds')) is None for t in tracks),total,hide),
        'added':chart([{'label':r['year'],'count':r['tracks']} for r in addition_dates['years']],addition_dates['unknown'],total,hide),
        'release_year':chart([{'label':year,'count':count} for year,count in sorted(years.items(),key=lambda p:p[0] or '') if year],years.get(None,0),total,hide),
        'genre':chart(genre_rows,total-sum(genres.values()),total,hide),
    }
    result['genre']['categories_total']=len(genres)
    return result
