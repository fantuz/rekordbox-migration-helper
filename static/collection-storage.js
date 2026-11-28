/* Recorded size totals and optional observations from the explicit File health scan. */
window.CollectionStorage = (() => {
  const label = key => esc(I18n.t(key));
  const size = value => value === null ? label('Unknown') : esc(bytes(value));
  const coverage = (known, total) => esc(I18n.t('{known} of {total} entries with size evidence', {known, total}));

  function card(key, title, row) {
    const conflicts = row.conflicts ? ' · ' + esc(I18n.t('{count} recorded paths with conflicting sizes', {count: row.conflicts})) : '';
    return '<article class="stat-card" data-storage-card="' + key + '"><span>' + label(title) +
      '</span><strong>' + size(row.bytes) + '</strong><small>' + coverage(row.known, row.total) + conflicts + '</small></article>';
  }

  function measurements(observed) {
    const names = {current: 'Found at current path', alternate: 'Found at an alternate recorded path',
      mapped: 'Found through an audio folder mapping', placeholder: 'Online-only placeholder'};
    const rows = Object.entries(names).map(([kind, title]) => {
      const item = observed.locations[kind];
      const sameEntries = item.paired && item.paired < item.entries
        ? '<br><small class="subtle">' + label('Logical size') + ' · ' + size(item.paired_bytes) + '</small>' : '';
      const mismatches = item.paired ? esc(num(item.mismatches)) + ' / ' + esc(num(item.paired)) : label('Unknown');
      return '<tr data-storage-location="' + kind + '"><th scope="row">' + label(title) +
        '</th><td>' + size(item.bytes) + ' · ' + esc(num(item.entries)) + '</td><td>' + size(item.recorded_bytes) +
        sameEntries + '</td><td>' + mismatches + '</td></tr>';
    }).join('');
    const when = snapshotMoment(new Date(observed.checked_at * 1000).toISOString());
    return '<p class="subtle">' + label('Last checked') + ' · ' + esc(when) + ' · ' + label('Checked') + ' ' +
      esc(num(observed.checked)) + ' / ' + esc(num(observed.total)) + '</p>' +
      '<div class="native-table"><table><thead><tr><th scope="col">' + label('Location') +
      '</th><th scope="col">' + label('Logical size') + ' · ' + label('Entries') +
      '</th><th scope="col">' + label('Recorded size for these entries') +
      '</th><th scope="col">' + label('Recorded size differs') + '</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  function render(storage, source) {
    const host = document.getElementById('stats-storage');
    host.hidden = !storage;
    if (!storage) {
      host.replaceChildren();
      return;
    }
    const observed = storage.observed;
    const messages = {
      workspace: 'Local observations come from the last File health scan. Capture a snapshot to check the loaded workspace.',
      mapping_changed: 'Audio folder mappings changed. Run File health again.',
      legacy: 'Run File health to collect size evidence.',
      not_started: 'Run File health to collect size evidence.'
    };
    host.innerHTML = '<h3>' + label('Storage') + '</h3><p class="subtle">' +
      label('Sizes are logical bytes. Cloud locations are path hints. Entries may share a file.') +
      '</p><div class="stats-cards">' + card('recorded', 'Recorded total', storage.recorded) +
      card('unique-paths', 'Distinct recorded paths', storage.unique_paths) +
      card('cloud', 'Recorded cloud-location size', storage.cloud) +
      card('streaming', 'Streaming references', storage.streaming) + '</div>' +
      (observed.locations ? measurements(observed) : '<p class="subtle">' + label(messages[observed.state]) + '</p>') +
      '<button type="button" class="button secondary small" id="stats-file-health">' + label('File health') + '</button>';
    host.querySelector('#stats-file-health').onclick = () => {
      if (source) window.FileHealth?.forSource(source);
      showView('file-health');
    };
  }

  return {render};
})();
