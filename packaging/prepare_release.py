"""Validate a manual release or the tested artifacts before any publication."""
import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from release_tools import release_plan, verify_assets


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--assets",type=Path)
    args=parser.parse_args()
    plan=release_plan(os.environ.get("REQUESTED_RELEASE_VERSION",""),os.environ["GITHUB_REF"])
    if args.assets:
        names=verify_assets(args.assets,plan["version"],os.environ["GITHUB_SHA"])
        notes=("Library Workbench "+plan["version"]+"\n\n"
               "A local library analyzer, duplicate-review utility and offline metadata explorer.\n\n"
               "- Windows x64: extract the complete ZIP and open Library Workbench.exe.\n"
               "- macOS: choose arm64 (Apple Silicon) or x86_64 (Intel), extract and open Library Workbench.app. These previews are ad-hoc signed, not notarized.\n"
               "- Linux: extract the source archive and run start.sh with Python 3.13 or newer.\n\n"
               "All packages passed their native CI runtime checks and share the release source. SHA256SUMS lists the four archives.\n"
               "Keep an untouched rekordbox Backup Library backup before transformation. Native ZIP restore inside rekordbox remains experimental; validate in an isolated library first.\n\n"
               "Source commit: "+os.environ["GITHUB_SHA"]+"\n")
        (args.assets/"RELEASE-NOTES.md").write_text(notes,encoding="utf-8")
        print("Verified",len(names),"archives from the release commit")
    else:
        repo=os.environ["GITHUB_REPOSITORY"]
        req=urllib.request.Request("https://api.github.com/repos/"+repo+"/git/ref/tags/"+plan["tag"],
             headers={"Authorization":"Bearer "+os.environ["GH_TOKEN"],"Accept":"application/vnd.github+json","User-Agent":"Library-Workbench-release"})
        try:
            with urllib.request.urlopen(req,timeout=25):pass
        except urllib.error.HTTPError as error:
            if error.code!=404:raise
        else:raise ValueError("This version tag already exists. Releases never overwrite existing tags or assets.")
        with Path(os.environ["GITHUB_OUTPUT"]).open("a",encoding="utf-8") as output:
            for key,value in plan.items():output.write(key+"="+value+"\n")
        print("Validated",plan["tag"],"from the default branch")


if __name__=="__main__":main()
