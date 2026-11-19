# Google Drive connector

The Google Drive connector verifies cloud-file existence for a saved collection
and downloads an individually approved absent file. Use
[Cloud connections](CLOUD-CONNECTIONS.md) first to review the account, source,
remote folder and local selected-file destination together.

## Register a desktop OAuth client

Workbench uses Google's browser-based OAuth authorization with PKCE. It does
not ask for your Google password or read credentials from Drive for desktop.
You supply your own Google account and storage; this is not a Rekordbox-managed
Google team or storage bundle.

1. Create or select a project in the
   [Google Cloud console](https://console.cloud.google.com/).
2. Enable the Google Drive API and configure the OAuth consent screen. If the
   project is in Testing, add the intended Google account as a test user.
3. Create an OAuth client with the **Desktop app** application type. Supply its
   client ID in Workbench. An optional desktop client secret, when supplied,
   stays in memory or the approved operating-system credential store; it is
   not an account password and is not written to the library sidecar.
4. Use the local callback URL shown by Workbench. Complete authorization in the
   browser on the same computer running the application.

Use a **Desktop app** client, not a Web application client. Google's desktop
loopback rules differ from Dropbox's manually registered redirect-URI list;
do not copy the Dropbox setup procedure into a Google web-client redirect
configuration. If Google rejects the callback, check the OAuth client type,
client ID and the actual loopback URL shown by Workbench against Google's
native-app instructions.

The requested `drive.readonly` permission allows metadata validation and
reading an individually approved file. It does not grant cloud-file creation,
modification or deletion. Google's native-app authorization rules, consent
testing, production verification and organization policies still apply.
Testing-mode authorizations can expire sooner and require reconnecting.

See Google's [native application OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app)
and [Drive authorization scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

## Attach the intended folder

Google Drive names are not unique. Choose the remote folder by identity rather
than assuming that a folder named `rekordbox` is the right one. Match it to an
existing local destination and the selected collection's recorded root through
the preview in **Cloud connections**.

Rekordbox supports **selected music files** synchronization for Google Drive.
The provider desktop application is optional, and the local download folder
can be elsewhere. Workbench retains discovered Drive locations and their
evidence while allowing an explicitly reviewed selected-file destination.

Only complete, unambiguous relative-path evidence enables attachment. Duplicate
paths, unsupported entry types, unavailable folders or incomplete listings
stay unverified. No filename-only guess is used to attach a collection.

The provider permission and the folder identity define what can be checked.
They do not independently prove Rekordbox compatibility for organizational or
Shared Drive layouts. Unsupported folder contexts are reported explicitly.

## Metadata and downloads

Choose **Check remote files** to list metadata and match the saved references.
This operation reads no audio and does not call the content-download endpoint.
The indexed results retain the account, source, mapping and check time.
Filtering and pagination run across that whole checked scope.

To retrieve one absent recording, review its name, local destination and size
in the download confirmation. Cancel or Escape leaves it untouched. A
confirmation is short-lived, single-use and bound to the current file details.
Changed accounts, mappings or remote versions need another confirmation.

Downloads require a nonempty binary audio file with a provider checksum and
permission to download. Google documents, shortcuts and entries without
sufficient verification evidence are held. The stream is checked against its
advertised size and checksum, then published atomically from private staging
outside managed cloud folders. Existing local files and placeholders are never
overwritten. Parent folders must already exist, staging must share the
destination filesystem, and the current limit is 8 GiB per file.

The provider may reconcile the completed local file according to its own
policy. Workbench does not change stream/mirror settings, enable bulk
downloads or upload recordings. Native library references and audio tags
remain unchanged.

## Evidence limits

Google Drive API metadata, local residency and decodable audio are different
checks. A remote match is not proof that an existing local recording has the
same contents. A failed permission/network request does not prove deletion.

Automated verification uses a synthetic provider with real application
HTTP/SQLite/job behavior and temporary file transfers. No personal account,
real music or live Drive authorization is included in those fixtures. Actual
desktop streaming, managed Google accounts and provider reconciliation still
need validation in the corresponding real setup.
