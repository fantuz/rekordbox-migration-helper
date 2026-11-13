# Unicode and input-format checks

The application uses Unicode strings and UTF-8 for its own JSON, HTML and text outputs. Interface language does not change library metadata. Comparisons may create normalized search or candidate keys; they do not rename files or rewrite source tags. Canonically equivalent NFC/NFD filenames remain distinct path identities unless the operating system resolves them to the same physical file.

## What CI exercises

Synthetic fixtures cover accents, combining marks, German ß, Turkish dotted/dotless I, Greek, Polish, Czech, Cyrillic, CJK, supplementary characters, emoji, bidirectional controls, whitespace, quotes, XML entities, HTML/script-like text and spreadsheet-formula prefixes.

- Property-based XML copy round trips check track/artist/album values, playlist references, escaped product-version attributes and unchanged input hashes.
- SQLite/JSON/HTML property tests check retained source strings and safe inline JSON embedding. A title containing `</script>` is data, not executable markup.
- ZIP tests cover UTF-8 names, legacy CP437 names, stored/deflated members, ZIP64 and byte-preserving copies. Traversal-like member names are not extracted to the filesystem by the raw-copy writer.
- Invalid XML characters, lone surrogates, DTD/entities, malformed documents and missing required identifiers are rejected. Null or invalid-Unicode import/path strings produce explicit errors.
- Browser tests exercise all supported languages in Chromium, Firefox and WebKit, including literal metadata that matches an interface label, unsaved comments, edit locks and offline HTML. Language changes must not submit mutations or query external services.
- Native Windows and both Mac packaged applications must serve bundled language resources and documentation. The existing encrypted native-copy tests remain part of the suite.

Install `requirements-test.txt` for the bounded Hypothesis tests, and `requirements-browser.txt` plus the matching Playwright browser for UI checks. GitHub performs these checks automatically. Property tests are deterministic, bounded and synthetic; they are not an exhaustive or continuous coverage-guided fuzzing campaign.

## Format and operating-system limits

“Unicode supported” does not mean every byte sequence is a legal filename on every platform. Windows reserved names/characters and path-length configuration, filesystem normalization and case sensitivity, legacy archive encodings, inaccessible cloud placeholders and rekordbox's own format constraints still apply. The tool does not silently rename a file to make it portable.

XML 1.0 cannot represent nulls, lone surrogates or some control characters. They cannot be preserved by inventing an XML escape. Unsupported input is rejected rather than silently replaced. Upload display names retain valid Unicode, while temporary upload bytes use fixed session paths; an uploaded filename cannot choose a filesystem destination.

CSV export prefixes potentially executable spreadsheet cells with an apostrophe. This protection is specific to CSV and does not alter XML, native database values or the source files. HTML snapshots preserve metadata but deliberately omit private comments and paths unless an applicable export option includes paths.

Passing these checks does not prove native rekordbox restore compatibility. Keep an untouched backup and follow the [isolated restore procedure](RESTORE-TEST.md).
