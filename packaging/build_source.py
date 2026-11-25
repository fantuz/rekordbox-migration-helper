"""Package application source from an explicit allowlist, excluding user data."""
from hashlib import sha256
from pathlib import Path
import tarfile
from io import BytesIO
from release_tools import build_version,archive_name

ROOT=Path(__file__).resolve().parents[1]
VERSION=build_version()


def main():
    destination=ROOT/"releases"/archive_name(VERSION,'linux-source')
    destination.parent.mkdir(exist_ok=True)
    files=list(ROOT.glob("*.py"))
    files+=[ROOT/name for name in (".gitattributes","start.sh","requirements.txt","requirements-build.txt","requirements-test.txt","requirements-browser.txt","README.md","CHANGELOG.md","CONTRIBUTING.md","LICENSE","SECURITY.md","THIRD-PARTY-NOTICES.txt")]
    files+=list((ROOT/"static").glob("*"))
    files+=list((ROOT/"packaging").glob("*.txt"))
    files+=list((ROOT/"packaging").glob("*.py"))+list((ROOT/"packaging").glob("*.c"))
    files+=list((ROOT/"docs").glob("*.md"))
    files+=list((ROOT/"docs").glob("*.json"))
    files.append(ROOT/"docs"/"screenshots"/"cloud-library-locations.png")
    files+=list((ROOT/"docs"/"fixtures").glob("onetagger-results-v*.json"))
    files+=[ROOT/"docs"/"screenshots"/name for name in ("readme-library-insights.png","readme-track-editor.png","readme-playlist-explorer.png",
                                                       "musicbrainz-enrichment-real.webp","library-bubbles-real.webp",
                                                       "formats-stems.png","beat-grid-nudge.png","native-source-insights.png","stems-workflows.png","recordbox-saved-stems.png","onetagger-results.png","onetagger-page.png",
                                                       "workflow-map.png","media-inventory.png","collection-cleanup.png","library-preparation.png","bubble-navigation.png",
                                                       "compact-bubble-filters.png","collection-statistics-distributions.png",
                                                       "cloud-file-health-filters.png","cloud-track-confirmation.png",
                                                       "dropbox-setup.png","dropbox-confirmation.png","dropbox-play-confirmation.png",
                                                       "cloud-connection-setup.png","cloud-attachment-preview.png",
                                                       "cloud-file-evidence.png","release-year-order.png",
                                                       "cloud-recorded-root-suggestions.png","google-drive-byte-progress.png",
                                                       "compact-workspace-toolbar.png","inline-star-ratings.png",
                                                       "cloud-analysis-statistics.png","metadata-sidecar-statistics.png")]
    with tarfile.open(destination,"w:gz") as archive:
        for file in sorted(files):
            if file.is_file():archive.add(file,arcname="library-workbench/"+str(file.relative_to(ROOT)),recursive=False)
        content=(VERSION+"\n").encode()
        info=tarfile.TarInfo("library-workbench/VERSION");info.size=len(content);info.mode=0o644
        archive.addfile(info,BytesIO(content))
    digest=sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".gz.sha256").write_text(digest+"  "+destination.name+"\n",encoding="utf-8")
    print(destination)


if __name__=="__main__":main()

