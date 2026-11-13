"""Repack the Linux application only after its native host runtime check passes."""
import json
import os
from pathlib import Path
import sys
from build_linux import pack


def main():
    folder=Path(sys.argv[1]).resolve()
    validation=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    manifest_path=folder/'BUILD-MANIFEST.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if sys.platform!='linux' or validation.get('status')!='passed' or manifest.get('commit')!=os.environ.get('GITHUB_SHA'):
        raise RuntimeError('A successful Linux runtime check for this commit is required')
    if validation.get('launcher')!='Linux portable ELF' or validation.get('external_python_unavailable') is not True:
        raise RuntimeError('Validate the actual bundled executable without external Python')
    manifest.update(linux_runtime_test='passed', runtime_validation=validation)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(pack(folder, Path('releases'), manifest['version']))


if __name__=='__main__':main()
