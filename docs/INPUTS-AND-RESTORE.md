# Create your input files and restore an edited copy

**Before you start: keep a recent, untouched rekordbox library backup and collection XML outside the Workbench workspace. Keep your music safe too. Workbench works with copies; restoring a library in rekordbox can replace your current collection.**

For duplicate review and transformed exports you need **two files from the same library state**: a Backup Library **ZIP** and an Export Collection **XML**. Create them one after the other without adding, removing or editing tracks between them. The read-only Source analyzer is a separate option and does not require this pair.

Menu names below use the English rekordbox interface. Your version or interface language may show slightly different labels. The [official rekordbox manual](https://rekordbox.com/en/download/#manual) is the reference if a menu differs.

## 1. Save the ZIP backup

1. Open rekordbox on Windows or macOS. Wait for your collection and any pending sync to finish.
2. Open **File → Library → Backup Library**.
3. When asked whether to back up music files as well, **No is recommended for this analysis**: the backup is smaller and quicker. Workbench also accepts a backup made with **Yes**. Choosing No does **not** back up your audio; keep a separate copy of your music. When moving to another computer, preserve or transfer that music as well.
4. Choose a folder you can find easily, for example **Documents → rekordbox review**, and save the backup. Wait until it finishes. Keep the ZIP intact; do not extract it.

This is the desktop library backup, not a USB device export. A backup without audio can still be large because it contains analysis data.

## 2. Save the XML export immediately afterwards

1. Without changing the collection, open **File → Export Collection in xml format**.
2. Save the XML in the same folder as the ZIP, for example as **collection.xml**. Any filename is accepted.
3. Wait for the export to finish. You now have two different files: one ending in **.zip**, the other in **.xml**.

If you want beatgrid information in the XML, check **Preferences → Advanced → Database → rekordbox xml → Export BeatGrid information** before making the pair. The ZIP contains native analysis; the XML is not a complete replacement for the native backup.

For Cloud Library Sync with **Dropbox or Google Drive**, export from the computer holding the intended collection. rekordbox may omit cloud tracks belonging only to other computers or mobile devices from XML. A matching pair can therefore have different XML/native track counts; Workbench shows the scope and validates IDs rather than assuming the counts must match.

## 3. Load and review in Workbench

1. Open **Files & workflow → Import XML + ZIP**.
2. Under **Choose files**, select your ZIP and XML, then choose **Copy files and analyze**. Copies stay on this computer; the original files are unchanged. Large backups need space for these copies and a new output ZIP.
3. Alternatively, **Use existing files** reads the two originals at their full paths without another large input copy. Leave them unchanged and available while you work.
4. Review duplicates, references and the proposed changes. In **Prepare export**, confirm that your separate untouched backup exists, then choose **Generate XML + ZIP together**.
5. Keep the generated files and **report.json**. Read the report before attempting a restore. The output is a working copy; file validation does not prove every rekordbox feature will restore correctly.

## 4. Restore the generated ZIP — test first

**Use a separate test computer or operating-system user profile first. Restoring may replace that profile's current rekordbox collection. Keep Cloud Library Sync paused on the test instance.**

1. Download or locate **edited-library.zip** from **Completed exports**. Do not extract it.
2. Open the test instance of rekordbox and choose **File → Library → Restore Library**.
3. Select **edited-library.zip**, open it and follow rekordbox's confirmation prompts. Let the restore finish, including any requested restart.
4. Check track counts, playlists, ratings, memory/hot cues, loops, beatgrids and playback. Check file references: a library backup without music cannot supply missing audio. A move to another computer may require relocation to the new music folders.
5. Keep your original backup until you have checked the restored library and decided how to reconcile cloud synchronization. See the [restore checklist](RESTORE-TEST.md).

Workbench never overwrites the running rekordbox library itself. The restore above is an action **you choose inside rekordbox**.

## Alternative: import the XML

**Choose this route instead of a native ZIP restore. Do not import the XML again after a successful ZIP restore.** XML contains a narrower set of library information and does not carry the audio or all native features.

1. In rekordbox, open **Preferences → Advanced → Database**. In **rekordbox xml**, use **Imported Library** to select **edited-collection.xml**.
2. If **rekordbox xml** is hidden, enable it under **Preferences → View → Layout → Media Browser**.
3. Open **rekordbox xml** in the browser tree, then **All Tracks**. Review the tracks before dragging the wanted entries into **Collection**.
4. To import a playlist, expand its folder in the XML tree and right-click the playlist to choose **Import Playlist**. Menu wording can vary by version.
5. Check counts and preparation in the test library before adopting it. The XML file is not an input for **Restore Library**.

## Sources and tested scope

The [official rekordbox 7 instruction manual](https://cdn.rekordbox.com/files/20260409151936/rekordbox7.214_manual_EN.pdf) documents backup/restore on pages 21–22, XML browsing on page 19, playlist XML import on page 45, and the File menu on pages 245–246. The [XML format specification](https://cdn.rekordbox.com/files/20200410160904/xml_format_list.pdf) describes exported fields. These formats do not imply that all desktop, cloud and device libraries are interchangeable.

Native transformed ZIP generation is currently limited to supported v7 inputs. The project has a user-reported successful Windows 11 restore, with the rekordbox version recalled approximately as 7.2.19; that report does not certify other installations or every restore scenario.
