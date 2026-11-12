# Compatibility and evidence

The analyzer selects its reader using the file format and required schema columns. It does not guess an exact application release from a `master.db` filename. Optional user-supplied version information is labeled as such. Unsupported or incomplete schemas produce explicit messages and unavailable counters.

Rekordbox v5 used a DeviceSQL `.edb` desktop database. Version 6 introduced SQLCipher-encrypted SQLite `master.db`; version 7 retains this format family. Legacy `.edb` and USB/device databases currently receive detection and footprint reports only. No old-version record decoder or downgrade conversion is claimed.

- [AlphaTheta: conversion from v5 to v6](https://rekordbox.com/en/support/faq/library-6/#faq-q60001)
- [AlphaTheta: v6 to v7 does not require conversion](https://rekordbox.com/en/support/faq/library-7/#faq-70923)
- [pyrekordbox: desktop database format](https://pyrekordbox.readthedocs.io/en/latest/formats/db6.html)
- [Official Cloud Library Sync guide](https://cdn.rekordbox.com/files/20251202174725/rekordbox7.2.8_cloud_library_sync_operation_guide_EN.pdf)

Real-world validation currently uses v7.2.19 backup data on Linux. Earlier-version behavior and changes across newer versions need genuine sample fixtures. Synthetic SQLCipher/WAL fixtures establish implementation properties, not historical-format compatibility. CI runtime checks establish packaged startup and analyzer behavior on their runners; they do not run the licensed rekordbox application or test cloud reconciliation.

Source analysis opens original database files only as byte streams for a private snapshot. Database queries and journal recovery operate on that copy. Source database/journal timestamps, sizes and identities must remain stable across capture and inspection. Automated tests compare source hashes as well. Folder scans inspect metadata without reading audio contents. Analysis-folder absence is scoped to the selected source folder and is not proof of missing music.

The preparation workflow writes new copies. Native ZIP generation remains experimental, is gated to v7 inputs and requires an untouched-backup acknowledgement. It is not an in-place source-folder editor.

## Device-format roadmap

Classic USB Device Library uses `export.pdb`. OneLibrary is the new name for Device Library Plus; AlphaTheta documents full compatibility between them. It is a device-export family separate from the desktop `datafile.edb` → `master.db` transition. Current detection does not imply record decoding or conversion. A future device reader/comparator needs genuine fixtures for both classic and OneLibrary exports, including USBs containing both formats.

- [AlphaTheta: relationship between OneLibrary and Device Library Plus](https://support.alphatheta.com/en-US/articles/51301232380185)
- [Official USB export guide](https://cdn.rekordbox.com/files/20251021171528/USB_export_guide_en_251007.pdf)
