"""Measured cloud work for the local progress dialog and plain-text job clients."""
import json
import unicodedata


class CloudProgress(str):
    """Keep the two-argument progress callback, including its string message."""

    def __new__(cls, provider, phase, *, item='', unit=None, completed=0, total=None, pages=None):
        message = super().__new__(cls, f'{provider} · {phase}')
        # Only show the item name. Account paths, cursors and requests do not belong in job feedback.
        leaf = str(item or '').replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
        leaf = ''.join(char for char in leaf if char in '\u200c\u200d' or unicodedata.category(char) not in ('Cc', 'Cf', 'Cs'))[:180]
        message.detail = {'provider': provider, 'phase': phase, 'item': leaf}
        if unit is not None:
            message.detail.update(unit=unit, completed=completed, total=total)
        if pages is not None:
            message.detail['pages'] = pages
        return message


def matching_tracks(tracks, provider, checkpoint):
    total = len(tracks)
    for index, track in enumerate(tracks):
        if index % 100 == 0:
            item = track.get('current_path') or track.get('original_path') or track.get('title')
            checkpoint(70 + 25 * index / total, CloudProgress(provider, 'Matching library paths', item=item,
                       unit='tracks', completed=index, total=total))
        yield track
    checkpoint(95, CloudProgress(provider, 'Matching library paths', unit='tracks', completed=total, total=total))


def evidence_records(rows, binding, source, provider, progress):
    """Report rows consumed by SQLite inside the existing atomic replacement."""
    total = len(rows)
    for done, row in enumerate(rows, 1):
        yield binding, source, row['track_id'], json.dumps(row)
        if done % 500 == 0 or done == total:
            progress(98, CloudProgress(provider, 'Saving file evidence', unit='tracks', completed=done, total=total))
