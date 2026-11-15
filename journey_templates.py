"""Guided entry points into existing tools; no conversion is implied by a checklist."""

def step(identity,title,view=None,*,tab=None,doc=None,target=None,optional=False):
    return dict(id=identity,title=title,view=view,tab=tab,doc=doc,target=target,optional=optional)

BACKUP=step('backup','Keep a separate backup',doc='inputs-and-restore')
CAPTURE=step('capture','Capture the source library','analyzer')
SNAPSHOT=step('snapshot','Save a snapshot for insight tools','lab')
CHECK=step('check','Collection statistics','statistics')
TEMPLATES={
    'guide-rb-serato':dict(title='Rekordbox → Serato',group='migration',
        note='Serato export is a draft. Verify it in a separate Serato library.',
        steps=[BACKUP,CAPTURE,SNAPSHOT,step('review','Review optional cleanup','review',optional=True),
               step('draft','Serato interoperability draft','intelligence',target='.serato-entry'),
               step('verify','Check the destination application',doc='serato-bridge')]),
    'guide-serato-rb':dict(title='Serato → Rekordbox',group='migration',
        note='Serato import is not implemented. This checklist records preparation and checks around a migration performed outside Workbench.',
        steps=[step('backup','Keep a separate backup',doc='predefined-journeys'),
               step('limits','Review migration limits',doc='serato-bridge'),
               step('external','Migration outside Workbench',doc='predefined-journeys'),
               CAPTURE,CHECK,step('playlists','Playlist explorer','intelligence'),
               step('verify','Check the destination application',doc='predefined-journeys')]),
    'guide-health':dict(title='Check library health',group='library',note='Integrity, references and preparation evidence',
        steps=[CAPTURE,CHECK,step('consistency','Library lab','lab',tab='checks'),step('references','File references','reference'),step('history','Play history','history')]),
    'guide-cleanup':dict(title='Review duplicates',group='library',note='Compare evidence and stage copy changes',
        steps=[BACKUP,CAPTURE,step('review','Duplicate review','review'),step('impact','Library intelligence','intelligence'),step('export','Create copy exports','exports')]),
    'guide-enrichment':dict(title='MusicBrainz metadata',group='library',note='Preview community matches, years, genres and available ratings.',
        steps=[CAPTURE,SNAPSHOT,step('pilot','MusicBrainz metadata','musicbrainz'),step('review','Metadata editor','lab',tab='editor'),step('export','Create copy exports','exports')]),
    'guide-refinement':dict(title='Metadata editor',group='library',note='Review tags and stage field, comment or colour edits.',
        steps=[CAPTURE,SNAPSHOT,step('insights','Library bubbles','bubbles'),step('edit','Metadata editor','lab',tab='editor'),step('compare','Compare snapshots','lab',tab='compare')]),
    'guide-sharing':dict(title='Share & offline summary',group='library',note='Sharing exports metadata only; audio files are not included.',
        steps=[CAPTURE,step('share','Share & offline summary','quick'),step('review','Review sharing privacy',doc='predefined-journeys')]),
    'guide-backup':dict(title='Backup and recovery',group='library',note='Create and restore backups in rekordbox. Workbench checks captured evidence.',
        steps=[BACKUP,CAPTURE,SNAPSHOT,step('restore','Restore on the destination',doc='inputs-and-restore'),step('compare','Compare snapshots','lab',tab='compare')]),
}
