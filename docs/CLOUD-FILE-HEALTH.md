# Cloud paths and file health

Open **File health**, choose the source in **Collection snapshot** above the
page header, and start **Scan local files**. The scan checks recorded paths and
saved audio-folder mappings. It inspects filesystem attributes, logical size
and local readability; it does not open audio, calculate audio hashes, launch a
player or call a cloud API.

The blue **Dropbox** and green **Google Drive** filters apply to the complete
saved scan before pagination. Labels describe configured provider roots or
recognizable directory names. A filename such as `Dropbox.mp3` alone is not a
provider match. Original and mapped paths can provide different provider
matches for the same library entry. **No cloud match** means no matching path
evidence; it does not prove that a file is outside all cloud storage.

The Cloud location column distinguishes detected roots from path-name hints.
Filenames and available logical sizes appear alongside track titles. These
sizes are filesystem metadata, not downloaded bytes or proof of resident audio.
Old scan rows show **Not classified** until an explicit new scan classifies them.

## Local absence and placeholders

A Dropbox recording can remain available to rekordbox even when selective sync
leaves no local file. Such paths show **Cloud availability unknown**, not proof
of deletion. An absent path cannot establish whether the remote file exists.
An OS-reported online-only placeholder is shown separately and is not marked
locally accessible just because it has a nonzero logical size. Windows offline
and recall attributes and macOS dataless attributes are recognized.

The existing four local statuses remain available. Cloud evidence supplements
them: **Unavailable** also includes known placeholders and cloud paths without
an accessible local file. Each entry counts once, even when several kinds of
evidence apply. Unknown, inaccessible and unchecked records require different
follow-up; none authorizes deletion. Re-scan after changing sync settings,
mounting a drive or saving different audio-folder mappings.

## Playing one track

Opening any detected cloud-managed audio path requires a separate **Open this
one track?** confirmation. Cancel and Escape leave the player closed. Approval
allows the operating system to open only that selected track; the sync app may
then download it. Consent is not saved or reused for the next track. The server
checks the selected source, track, current path, mappings and file attributes
again before dispatch. Expired or changed requests need a new Play action.

A cloud path with no local file or placeholder cannot be opened by Workbench.
Make that single recording available through Dropbox or rekordbox, then refresh.
Workbench has no account connection with which to request a remote download.
Google Drive support here is limited to path labels and local attributes;
provider account integration is deferred.

## Can a running Dropbox client supply an `ls` equivalent?

Official APIs can list remote metadata without downloading the recording:

| Interface | Metadata operation | Practical limit |
| --- | --- | --- |
| Dropbox HTTP API | `files/get_metadata`, `files/list_folder`, `files/list_folder/continue` | Requires separate account authorization and appropriate scopes; a logged-in desktop client does not authorize Workbench. |
| Dropbox Linux CLI | `dropbox filestatus [-l] [-a] [FILE]…`; `ls` aliases `filestatus -l` | Describes the documented local client interface. A complete inventory of remotely stored, selectively excluded files is not established. |
| Local filesystem | File names, logical sizes and supported placeholder attributes | Cannot establish remote existence when no local entry is present. |

No supported public Windows desktop-client interface for a complete remote
listing was established in this investigation. This feature therefore uses
local attributes and path evidence. It does not access private client
interfaces, recover client credentials or introduce an account authorization
flow. A future, separately authorized Dropbox API connection could supply
remote-presence evidence without a music download.

The remote API's `.tag` identifies entry kinds such as file and folder; it is
not an embedded music tag such as genre, key or artist. Audio tag extraction
is not part of this metadata-only scan.

Sources checked on 2026-11-18:

- [Dropbox file access guide](https://developers.dropbox.com/dbx-file-access-guide)
- [Dropbox Linux commands](https://help.dropbox.com/installs/linux-commands)
- [Windows file attribute constants](https://learn.microsoft.com/en-us/windows/win32/fileio/file-attribute-constants)

Regression tests use invented paths, synthetic OS attributes and a recording
stand-in for OS playback dispatch. Live Dropbox accounts, remote-presence
queries and actual Windows/macOS hydration have not been validated here.
