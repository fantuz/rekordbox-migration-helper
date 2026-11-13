# Interface translations

The interface supports English, German, French, Italian, Spanish, Greek, Polish, Czech and Russian. Choose a language in the header. The browser remembers it where local storage is available; otherwise the choice lasts for the page session. Initial selection uses a supported browser language, with English as the fallback. No translation service or internet connection is used.

Controls, short guidance, confirmations, accessibility labels and offline-explorer controls use the same bundled catalogue. Routine pages use technical wording. Import/export and destructive-cleanup confirmations retain explicit scope and backup instructions. Longer procedures are in collapsed help or the Documentation page, which reads the project's bundled Markdown. Full documentation, legal text and raw diagnostics currently retain their source language, usually English.

## Preserve the source data

Track titles, artists, albums, genres, playlists, comments, cue labels, file paths and user-defined colour meanings are data. They are never looked up in a translation dictionary. A song titled “Unknown” remains “Unknown” in every interface language. Format identifiers, database fields, API values, output filenames and JSON keys remain stable. Display formatting uses the selected locale; grouping identities and saved values remain independent of it.

Switching language refreshes views without submitting edit forms. Pending uploads or mutations finish first. Unsaved form values, filters and open editor panels are retained. The offline explorer carries all language resources and remains usable without the application. CSV headings follow its displayed table; source metadata remains unchanged and spreadsheet-formula protection still applies.

## Contributing translations

`static/locales.json` is the shared catalogue. English message strings identify interface messages; each entry supplies `de`, `fr`, `it`, `es`, `el`, `pl`, `cs` and `ru`. An optional `en` value can improve English wording without changing a message identifier. Update the message and its translations together, keeping terminology technical and concise.

- Keep every named placeholder, including `{count}` and `{slot0}`, exactly once where required. Slots represent existing controls, links or emphasized text; they are not HTML to be translated.
- Translate plain text only. Do not introduce markup, links, scripts, filenames or changed format identifiers.
- Keep product names and the documented English rekordbox menu commands recognizable. Cue labels, saved genres and other source metadata are outside the catalogue.
- Use native language names in the selector. Do not use country flags as language identifiers.
- Check narrow layouts, long labels, disabled controls and sensitive confirmations. Native-speaker review is welcome; automated checks establish structural correctness, not linguistic perfection.

New languages can be added to the supported-language registry after their catalogue and browser checks are complete. Missing messages fall back to English at runtime, while CI rejects incomplete supported-language catalogues. See [contributing](../CONTRIBUTING.md) and [Unicode/input tests](UNICODE-INPUTS.md).
