# Library formats and source references

These sources describe different layers. An XML schema version, an application version and a USB device-library format are not interchangeable. References reviewed on 13 November 2026; future versions still require validation.

| Layer | Main reference | What the Workbench supports |
| --- | --- | --- |
| Collection XML interchange | [Official XML format list](https://cdn.rekordbox.com/files/20200410160904/xml_format_list.pdf), linked from the [rekordbox developer page](https://rekordbox.com/en/support/developer/?lang=en) | Exported collection tags, tempo/cue data and playlist links where present; XML-only statistics and offline browsing, including older-version exports. |
| v5 desktop library | [Official v5 → v6 conversion guidance](https://rekordbox.com/en/support/faq/library-6/#faq-q60001) | Native `.edb` detection and file inventory. No native record decoder. Use an XML export for tags/statistics, or convert a copy using rekordbox. |
| v6/v7 desktop library | [Official v7 library FAQ](https://rekordbox.com/en/support/faq/library-7/#faq-70923), [community native-schema reference](https://pyrekordbox.readthedocs.io/en/latest/formats/db6.html) | Detached SQLCipher/SQLite `master.db` analysis, guarded by schema/capability checks. The FAQ says v6 → v7 needs no library conversion; that does not prove compatibility with every release or this tool's writer. |
| Analysis assets | [Community ANLZ reference](https://pyrekordbox.readthedocs.io/en/latest/formats/anlz.html), [pinned Recordbox/public-fixture review](RECORDBOX-INTEGRITY-REVIEW.md) | Names, extensions, sizes, references, bounded PMAI/grid/cue checks and optional byte comparisons. Repeated groups are preserved. Known PQT2 count/fraction checks and unsupported non-PMAI `.3EX` variants stay separate. No extension or analysis tag establishes STEMS readiness. |
| USB device export | [Official USB export guide](https://cdn.rekordbox.com/files/20251021171528/USB_export_guide_en_251007.pdf), [OneLibrary / Device Library Plus relationship](https://support.alphatheta.com/en-US/articles/51301232380185) | Classic catalog header checks, settings CRC checks and separate OneLibrary detection. Device records and OneLibrary schemas are not decoded. Classic `export.pdb` and OneLibrary are separate from the desktop v5 → v6 change. |

## XML across versions

The official public XML reference above is the shared interchange reference used here for v5/v6/v7 exports. We have not found a separate official public v6 or v7 native database format specification. We do not label the community native schema as an official specification or invent version-specific PDFs.

`DJ_PLAYLISTS Version="1.0.0"` describes the XML schema. `PRODUCT Version` identifies the exporting application when supplied. Neither proves every optional field is populated. Important distinctions include:

- `DateAdded` is library addition date; `Year` is release year. Migration/reimport can affect addition dates.
- `PlayCount` and optional `LastPlayed` are track summaries. XML has no documented native History-session collection. A history deliberately converted to a playlist is an ordinary playlist in an export; we cannot infer its provenance.
- `TotalTime` is track length in seconds, not time actually played during a session.
- XML rating encoding differs from native personal-star values. Readers normalize supported values rather than copying raw integers between formats.
- Playlist targets depend on the node's key type. Missing collection targets remain visible.

Version coverage follows [Compatibility and evidence](COMPATIBILITY.md). Genuine old-version fixtures remain necessary; an XML file that parses is not evidence of native restore compatibility.

## Database and journal capture

Source analyzer copies the selected `master.db` and any WAL or rollback journal
into a private workspace before making database connections. It checks file
size, timestamps and available device/inode identity before and after copying.
The saved journal monitor uses the fields recorded by each capture, so older
reports remain readable. Change-time information depends on the platform;
Windows can report creation time instead. Close rekordbox and pause library
sync before capture to obtain stable inputs.

Before opening a private copy with a nonempty WAL, the reader checks its header
and compares its page size with the database. For encrypted databases, a
read-only immutable connection probes only the detached base file and ignores
its journals. Matching inputs can then recover committed WAL data on the private
copy. An incomplete final WAL frame remains eligible for SQLite's ordinary
committed-prefix recovery. A page-size mismatch, invalid header, or simultaneous
nonempty WAL and rollback journal requires a fresh capture; the app does not
guess a recovery order or modify the source.

These checks add a boundary around the current SQLCipher wheel's older SQLite
reader. They do not upgrade that bundled engine or establish that every damaged
database is safe or recoverable. SQLite still validates WAL frames and
transactions. Captures and their retained metadata remain local; no cloud
download or source checkpoint is triggered by these checks.

## Operational guides, not native schema contracts

The [v6.7 manual](https://cdn.rekordbox.com/files/20230316171900/rekordbox6.7.0_manual_EN.pdf), [v7 manual](https://cdn.rekordbox.com/files/20260409151936/rekordbox7.214_manual_EN.pdf) and [STEMS FAQ](https://rekordbox.com/en/support/faq/stems-7/) explain application features. They do not document a persistent per-track STEMS-ready flag for this reader. Unknown indicators stay unavailable until validated.

The [format/STEMS inspector](FORMATS-AND-STEMS.md) records the new check boundaries and pinned community sources. The current official v7 FAQ describes three- and four-stem modes; this does not establish a compatible persistent cache format. Recordbox open-model caches, phrase/vocal-activity analysis and native rekordbox preparedness remain distinct.

## Focused ANLZ review, 19 November 2026

The following public references informed independently written readers and
synthetic regressions; no implementation code or private library fixtures were
copied:

- [PQTZ signed-shift discovery](https://github.com/teknopaul/vdj-ui/commit/7b33c57344c4cb6bb745d8f84dea445c732bc2a1)
  and its public timing examples support reading a signed big-endian 16-bit
  shift at section offset `0x12`. Raw and effective timestamps remain distinct.
- [Pyrekordbox PSSI schema](https://github.com/dylanljones/pyrekordbox/blob/50b4604d98dfd52740aa9e76d80c3a32dfa451ba/pyrekordbox/anlz/structs.py#L246-L260)
  and [mask handling](https://github.com/dylanljones/pyrekordbox/blob/50b4604d98dfd52740aa9e76d80c3a32dfa451ba/pyrekordbox/anlz/file.py#L123-L142)
  distinguish version and entry size and rotate the mask for version 1.
  Workbench checks bounded structure and header values and reads the twelve
  big-endian words of each retained record. Its kind labels follow the
  [mood-specific recordbox mapping](https://github.com/adamsardo/recordbox/blob/3cc12d95cd5da40925491b20ec1220925c4cd3c1/app/src/phrase.rs#L186).
  Extra words retain their numeric values. Unknown revisions remain unsupported.
- [Rekordcrate cue-comment correction](https://github.com/RobinMcCorkell/rekordcrate/blob/85f25448950b8cb665449a305e71eb61d332df5b/src/anlz.rs#L285-L315)
  corroborates byte counts and final UTF-16 NUL handling. A generated missing-NUL
  entry reproduced the earlier overpermissive Workbench classification.

These source comparisons establish specific parser behavior, not universal
player compatibility. No new native STEMS-ready field or non-PMAI `.3EX`
decoder was established.
