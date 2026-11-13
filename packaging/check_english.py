"""Check English UI messages and repository documentation without reading user data."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from localization import catalogues


def text_values(value):
    if isinstance(value,dict):
        for child in value.values():yield from text_values(child)
    elif isinstance(value,str):yield value


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'ci-output');args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    english=list(text_values(catalogues(ROOT/'static')['en']))
    exported=args.output/'english-interface.txt';exported.write_text('\n'.join(english)+'\n',encoding='utf-8')
    docs=sorted({*ROOT.glob('*.md'),*(ROOT/'docs').rglob('*.md')})
    command=[sys.executable,'-m','codespell_lib','--builtin','clear,rare','--ignore-words',str(ROOT/'packaging/spelling-allowlist.txt'),str(exported),*[str(p) for p in docs]]
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    diagnostics=result.stdout+result.stderr
    report={'status':'passed' if result.returncode==0 else 'failed','english_ui_messages':len(english),
            'documentation_files':[str(p.relative_to(ROOT)) for p in docs],
            'scope':'English display messages and Markdown documentation; no translations, library metadata or inputs',
            'diagnostics':diagnostics}
    (args.output/'english-spelling.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if diagnostics:print(diagnostics,end='')
    print('English UI messages:',len(english),'Documentation files:',len(docs))
    raise SystemExit(result.returncode)


if __name__=='__main__':main()
