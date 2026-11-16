"""Auditable, tag-only search cleanup inspired by OneTagger's MatchingUtils.

Search alternatives never become replacement metadata. Original spellings and
version disagreements remain evidence for the listener's explicit review.
"""
from difflib import SequenceMatcher
import re
import unicodedata

VERSIONS=re.compile(r'\b(remix|mix|edit|live|instrumental|dub|extended|radio|acoustic|remaster(?:ed)?|version)\b',re.I)


def folded(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().split())


def cleanup(title, artist=''):
    original={'title':str(title or ''),'artist':str(artist or '')}
    current=dict(original);steps=[]
    def apply(name,field,function):
        before=current[field];after=function(before).strip()
        if before!=after:
            steps.append({'step':name,'field':field,'before':before,'after':after})
            current[field]=after
    for field in ('title','artist'):
        apply('case_spacing_dashes',field,lambda s:' '.join(folded(s).replace('-',' ').split()))
    apply('leading_article','title',lambda s:re.sub(r'^(?:a|an|the)\s+','',s))
    apply('original_version','title',lambda s:re.sub(r'\s*[\[(]?original(?:\s+(?:mix|edit|version))?[\])]?\s*$','',s))
    apply('release_attributes','title',lambda s:re.sub(r'\s*[\[(](?:explicit|clean|bonus track|album version)[\])]','',s))
    for field in ('title','artist'):
        apply('featured_artists',field,lambda s:re.sub(r'\s*[\[(]?(?:feat|ft)\.?\s+[^\])]*(?:[\])]|$)','',s))
    return {'original':original,'cleaned':current,'steps':steps}


def version_terms(value):
    return set('remaster' if term.startswith('remaster') else term.casefold()
               for term in VERSIONS.findall(folded(value)))


def disagreements(track,title,artist,disambiguation='',duration_delta=None,isrc_exact=False):
    source=cleanup(track.get('title'),track.get('artist'))
    candidate=cleanup(title,artist)
    differences=[]
    def add(field,original,proposed,reason):
        differences.append({'field':field,'original':original,'candidate':proposed,'reason':reason})
    for field in ('title','artist'):
        before=source['original'][field];after=candidate['original'][field]
        if folded(before)!=folded(after):add(field,before,after,'different_tags')
    a=version_terms(track.get('title'));b=version_terms(str(title)+' '+str(disambiguation or ''))
    if a!=b:add('version',sorted(a),sorted(b),'version_disagreement')
    if duration_delta is not None and duration_delta>2:
        add('duration',track.get('duration'),duration_delta,'duration_delta_seconds')
    if track.get('isrc') and not isrc_exact:add('isrc',track['isrc'],None,'identifier_not_confirmed')
    return {'source_cleanup':source,'candidate_cleanup':candidate,'disagreements':differences,
            'version_needs_review':a!=b,
            'cleaned_title_similarity':round(SequenceMatcher(None,source['cleaned']['title'],candidate['cleaned']['title']).ratio(),3)}
