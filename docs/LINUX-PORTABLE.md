# Linux portable application

The **linux-x86_64-portable** artifact contains a TAR.GZ with Python and the application dependencies included. No system Python, virtual environment, pip or shell setup is needed to run it.

1. Download the Linux x86-64 portable archive. For development builds, GitHub first supplies an outer artifact ZIP; extract it to find the TAR.GZ. Stable releases supply the TAR.GZ directly.
2. Extract the complete TAR.GZ into a local folder. Open **Library Workbench**, then double-click the executable named **Library Workbench** inside it. Keep `_internal` beside the executable.
3. If your file manager asks what to do, choose **Run**. The app opens the local interface in your default browser. If execution is disabled for downloaded files, use your file manager's Properties/Permissions to allow execution. A filesystem mounted with `noexec` cannot run the bundle; choose another location.
4. Use **Stop and clean up** in the interface when finished. Closing the browser tab leaves the local application running.

Terminal fallback, from the extracted folder: `./"Library Workbench"`.

## Compatibility and workspace

This package is for **x86-64 desktop Linux with glibc 2.28 or newer** and a browser. It is not an ARM or Alpine/musl binary. The build runs in a pinned manylinux_2_28 image; the actual executable is exercised in that container and again on Ubuntu 22.04. This establishes the tested baseline, not a guarantee for every distribution, desktop integration or browser. The [PyInstaller documentation](https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible) explains why the system C library is not bundled. The build image is maintained by [PyPA manylinux](https://github.com/pypa/manylinux).

Data is stored outside the extracted application, in **$XDG_DATA_HOME/LibraryWorkbench**, or **~/.local/share/LibraryWorkbench** when that variable is absent. `LIBRARY_WORKBENCH_DATA_DIR` overrides it. The source version keeps its existing `.data` location; the portable app does not silently migrate a source workspace. You can deliberately point both at the same workspace when only one instance is running.

Original input files remain unchanged. Uploaded analysis copies are temporary; decisions, small reports and deliberate XML/ZIP/HTML exports are retained according to the [cleanup guide](TEMPORARY-FILES.md). Linux can analyze a copied or already-mounted Windows/Mac library through manual paths; it does not install rekordbox or mount other operating systems' drives.

## Build and evidence

GitHub builds the package with pinned PyInstaller and CPython 3.13.18 in a digest-pinned manylinux_2_28 x86-64 container. The container's wheel-building interpreter is static, so the workflow first builds shared CPython from the official, SHA-256-pinned source archive. Its origin and checksum are recorded in the manifest, and its license is included under `_internal/licenses`. Inputs are the public application checkout and dependencies, never a user's library. The package preserves shared-library symlinks and executable permissions in TAR format.

The host check extracts into a path with spaces and Unicode, clears Python environment variables and points `PATH` at a nonexistent folder before running the bundled ELF. It exercises encrypted synthetic database reads, source hash preservation, browser-server startup, repeat launch, translated resources, snapshots, offline exports and acknowledged cleanup. The harness uses its own Python only to create synthetic fixtures and send HTTP checks; the application must run independently.

Only after the native check passes is `linux_runtime_test` marked **passed** in `BUILD-MANIFEST.json`. Release collection checks the version, commit, source digests, native evidence and SHA-256 alongside the Windows/Mac packages and source archive. A successful runtime check does not establish native rekordbox restore compatibility; Linux does not run that licensed application in CI.
