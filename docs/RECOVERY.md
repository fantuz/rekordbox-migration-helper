# Missing files and advanced relocation

File health checks the captured paths. **Missing** means a specific file is absent while its parent folder is reachable; **Inaccessible** indicates an access problem. **Unverified** can mean an offline drive, an unsupported path, or insufficient evidence. The **Not playable** filter includes Missing and Inaccessible, not unchecked or uncertain entries. None of these states proves that audio is gone forever.

## Search beyond the recorded paths

Load the matching XML/ZIP workspace and open **Media inventory**. Enable **Advanced relocate**, enter local music folders, and choose **Scan these folders**. This opt-in search reads audio tags and duration with the bundled reader; it does not upload metadata, download cloud placeholders, move audio, or edit the live Rekordbox library. Saved snapshots in File health remain read-only; load their original matching pair to stage relocation changes.

The search combines mapped path and byte size, normalized filename and byte size, and embedded title/artist tags with duration within two seconds. Tag matching can find a renamed file even when its byte size differs. Normalization preserves remix/version words and digits. This is metadata evidence, not acoustic fingerprinting or proof that two recordings sound identical.

Candidates show their local paths, proposed export URIs, evidence, and available tags. Evidence ranks mapped paths before filename matches, then tag matches. Multiple plausible files stay **Several candidates** even if one ranks higher. A candidate whose tags or duration conflict with captured metadata stays **Needs review**. Audio already available at a recorded path is **Playable**.

For one candidate from a complete search, review the displayed path and tags and click **Stage reference**. **Undo** clears that staged change. The default destination is the local file URI; an optional export root supports a different destination computer. The application verifies the local candidate again before staging and rejects changed files, links, cloud placeholders, stale scan results, and a changed workspace. The existing export workflow creates a separate XML/ZIP copy with the staged references. Its backup acknowledgement and native cloud-reference restrictions still apply.

## Understand unresolved results

Choose **Unresolved** to see no-match, ambiguous, cloud-only, incomplete, and conflicting cases together. **Not found** means no candidate met the matching rules in the selected folders. It is not a claim that every possible copy has been searched. Files with missing tags, unsupported formats, changed versions, or different encodings can escape these rules.

Each advanced search accepts up to 20 explicit folders and 250,000 library records. It stops indexing at 50,000 audio files, 200,000 visited entries, or a cooperative 120-second limit. Checks run between filesystem and tag-reader calls; a slow individual operating-system read can take longer. Cancellation preserves the preceding saved inventory. Unavailable roots, skipped links, cloud placeholders, unreadable audio, conflicting root mappings, or limits make the search incomplete. Results then remain held for review rather than claiming a unique relocation. Choose smaller folders or resolve the warnings before scanning again.

Only the first 20 candidates per track are displayed and included in the report; the full candidate count remains visible. No candidates are automatically selected from an ambiguous set. Overlapping roots pointing to the same file and destination do not create duplicate candidates.

## Backup before removing entries

1. Connect all external drives, restore any offline storage, and download cloud audio through its provider. Search those folders as well as existing music backups.
2. Create an untouched **File → Library → Backup Library** ZIP and matching **File → Export Collection in xml format** XML in Rekordbox. Keep them on separate storage outside the application workspace. Preserve available music separately when the ZIP excludes audio.
3. Download the JSON recovery report from Media inventory. It records the scan scope, warnings, track IDs, captured metadata and playlist IDs, candidates, and staged destinations. Keep it private: it includes local file paths. It is an audit aid, not a native backup and not a copy of the audio.
4. Verify the backup by restoring it into a separate library and checking playlists, cues, and sample playback. Neither an XML nor a metadata report can reconstruct audio that is absent from every backup.
5. If an entry is individually confirmed unwanted after those checks, remove that library entry in Rekordbox. Keep the untouched backup and recovery report for reversal. This feature does not erase library entries or media automatically; it focuses on recovering references first.

An advanced search cannot certify “files gone forever.” A future removal/export feature needs its own explicit selection, playlist/cue preservation, and tested restore path; an empty search result must never serve as deletion consent.
