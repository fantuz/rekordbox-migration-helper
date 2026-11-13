"""Validate a manual/tag release and its tested artifacts before publication."""
import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import quote

from release_tools import ROOT, release_notes, release_plan, verify_assets


def github_reader(repo):
    def read(path):
        req=urllib.request.Request("https://api.github.com/repos/"+repo+"/"+path,
             headers={"Authorization":"Bearer "+os.environ["GH_TOKEN"],"Accept":"application/vnd.github+json",
                      "X-GitHub-Api-Version":"2022-11-28","User-Agent":"Library-Workbench-release"})
        with urllib.request.urlopen(req,timeout=25) as response:return json.load(response)
    return read


def validate_release_target(plan, ref, commit, read, default_branch="main"):
    """Allow a fresh manual tag or an existing tag at a reviewed main commit."""
    tag=quote(plan["tag"],safe="")
    try:
        read("releases/tags/"+tag)
    except urllib.error.HTTPError as error:
        if error.code!=404:raise
    else:raise ValueError("This release already exists. Releases never overwrite existing assets.")
    try:
        target=read("git/ref/tags/"+tag)["object"]
    except urllib.error.HTTPError as error:
        if error.code!=404:raise
        if ref.startswith("refs/tags/"):raise ValueError("The triggering release tag no longer exists") from error
        return
    if not ref.startswith("refs/tags/"):
        raise ValueError("This version tag already exists. Use its automatic tag build; manual releases never overwrite tags.")
    seen=set()
    while target.get("type")=="tag":
        sha=target["sha"]
        if sha in seen or len(seen)>=8:raise ValueError("Invalid annotated release tag chain")
        seen.add(sha)
        target=read("git/tags/"+quote(sha,safe=""))["object"]
    if target.get("type")!="commit" or target.get("sha")!=commit:
        raise ValueError("Release tag no longer points at the checked commit")
    comparison=read("compare/"+quote(commit,safe="")+"..."+quote(default_branch,safe=""))
    if comparison.get("merge_base_commit",{}).get("sha")!=commit or comparison.get("status") not in ("ahead","identical"):
        raise ValueError("Release tags must point to a commit already merged into the default branch")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--assets",type=Path)
    args=parser.parse_args()
    ref=os.environ["GITHUB_REF"]
    default_branch=os.environ.get("RELEASE_DEFAULT_BRANCH") or "main"
    plan=release_plan(os.environ.get("REQUESTED_RELEASE_VERSION",""),ref,default_branch)
    validate_release_target(plan,ref,os.environ["GITHUB_SHA"],github_reader(os.environ["GITHUB_REPOSITORY"]),default_branch)
    if args.assets:
        names=verify_assets(args.assets,plan["version"],os.environ["GITHUB_SHA"])
        changelog=ROOT/"CHANGELOG.md"
        notes=release_notes(plan["version"],os.environ["GITHUB_SHA"],changelog.read_text(encoding="utf-8") if changelog.is_file() else "")
        (args.assets/"RELEASE-NOTES.md").write_text(notes,encoding="utf-8")
        print("Verified",len(names),"archives from the release commit")
    else:
        with Path(os.environ["GITHUB_OUTPUT"]).open("a",encoding="utf-8") as output:
            for key,value in plan.items():output.write(key+"="+value+"\n")
        print("Validated",plan["tag"],"from",ref)


if __name__=="__main__":main()
