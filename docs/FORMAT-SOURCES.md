# Library formats and source references

These sources describe different layers. An XML schema version, an application version and a USB device-library format are not interchangeable. References reviewed on 13 November 2026; future versions still require validation.

| Layer | Main reference | What the Workbench supports |
| --- | --- | --- |
| Collection XML interchange | [Official XML format list](https://cdn.rekordbox.com/files/20200410160904/xml_format_list.pdf), linked from the [rekordbox developer page](https://rekordbox.com/en/support/developer/?lang=en) | Exported collection tags, tempo/cue data and playlist links where present; XML-only statistics and offline browsing, including older-version exports. |
| v5 desktop library | [Official v5 → v6 conversion guidance](https://rekordbox.com/en/support/faq/library-6/#faq-q60001) | Native `.edb` detection and file inventory. No native record decoder. Use an XML export for tags/statistics, or convert a copy using rekordbox. |
| v6/v7 desktop library | [Official v7 library FAQ](https://rekordbox.com/en/support/faq/library-7/#faq-70923), [community native-schema reference](https://pyrekordbox.readthedocs.io/en/latest/formats/db6.html) | Detached SQLCipher/SQLite `master.db` analysis, guarded by schema/capability checks. The FAQ says v6 → v7 needs no library conversion; that does not prove compatibility with every release or this tool's writer. |
| Analysis assets | [Community ANLZ reference](https://pyrekordbox.readthedocs.io/en/latest/formats/anlz.html) | Names, extensions, sizes, reference ownership and optional bounded byte comparisons. No claim that an extension establishes STEMS readiness. |
| USB device export | [Official USB export guide](https://cdn.rekordbox.com/files/20251021171528/USB_export_guide_en_251007.pdf), [OneLibrary / Device Library Plus relationship](https://support.alphatheta.com/en-US/articles/51301232380185) | Detection/inventory only. Classic `export.pdb` and OneLibrary are separate from the desktop v5 → v6 change. |

## XML across versions

The official public XML reference above is the shared interchange reference used here for v5/v6/v7 exports. We have not found a separate official public v6 or v7 native database format specification. We do not label the community native schema as an official specification or invent version-specific PDFs.

`DJ_PLAYLISTS Version="1.0.0"` describes the XML schema. `PRODUCT Version` identifies the exporting application when supplied. Neither proves every optional field is populated. Important distinctions include:

- `DateAdded` is library addition date; `Year` is release year. Migration/reimport can affect addition dates.
- `PlayCount` and optional `LastPlayed` are track summaries. XML has no documented native History-session collection. A history deliberately converted to a playlist is an ordinary playlist in an export; we cannot infer its provenance.
- `TotalTime` is track length in seconds, not time actually played during a session.
- XML rating encoding differs from native personal-star values. Readers normalize supported values rather than copying raw integers between formats.
- Playlist targets depend on the node's key type. Missing collection targets remain visible.

Version coverage follows [Compatibility and evidence](COMPATIBILITY.md). Genuine old-version fixtures remain necessary; an XML file that parses is not evidence of native restore compatibility.

## Operational guides, not native schema contracts

The [v6.7 manual](https://cdn.rekordbox.com/files/20230316171900/rekordbox6.7.0_manual_EN.pdf), [v7 manual](https://cdn.rekordbox.com/files/20260409151936/rekordbox7.214_manual_EN.pdf) and [STEMS FAQ](https://rekordbox.com/en/support/faq/stems-7/) explain application features. They do not document a persistent per-track STEMS-ready flag for this reader. Unknown indicators stay unavailable until validated.
