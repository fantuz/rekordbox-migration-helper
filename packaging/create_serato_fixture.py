"""Generate three invented tracks with silence for a disposable Serato smoke test."""
import argparse
from pathlib import Path
import sys
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serato_bridge import draft_package


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    root=args.output.expanduser().resolve();root.mkdir(parents=True,exist_ok=False)
    music=root/'Synthetic music';music.mkdir();tracks=[]
    for i,name in enumerate(['Synthetic One','Synthetic café','Synthetic 日本 🎧']):
        path=music/(name+'.wav')
        with wave.open(str(path),'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(44100);audio.writeframes(b'\0\0'*44100)
        tracks.append({'id':str(i),'title':name,'artist':'Generated test artist','current_path':str(path),'duration':1})
    snapshot={'id':'synthetic-serato-smoke','tracks':tracks,'playlists':[
        {'id':'folder','name':'Synthetic tests','folder':True},
        {'id':'set','name':'Order and repetitions','parent':'folder','tracks':['2','0','1','0']}],
        'capabilities':{'playlist_order':True}}
    # This fixture chooses a destination explicitly; Linux is a generator host,
    # never a Serato target. Linux output is a simulated macOS volume layout.
    target_profile='windows' if sys.platform.startswith('win') else 'macos'
    target_root=root.anchor if sys.platform.startswith('win') or sys.platform=='darwin' else '/Volumes/DJSmoke'
    payload,manifest=draft_package(snapshot,root.anchor,target_profile,target_root)
    (root/'serato-draft.zip').write_bytes(payload)
    (root/'README.txt').write_text('SYNTHETIC SERATO TEST\n\nThree invented tracks; each contains one second of generated silence.\n'
        'On Windows/macOS the ZIP references the generated music paths on this computer.\n'
        'On Linux it simulates /Volumes/DJSmoke on macOS; inspect manifest target paths and copy the generated audio before testing there.\n'
        'If you move the files to another computer, run this generator there again.\n'
        'Use only a separate, backed-up test library. Never replace your working _Serato_ folder.\n'
        'Follow docs/SERATO-BRIDGE.md and check 3 tracks, Unicode, nesting and crate order 2,0,1,0.\n'
        'This fixture is not proof of Serato acceptance. No application import has been run by this generator.\n',encoding='utf-8')
    print('Generated three synthetic tracks and a validated draft in',root)

if __name__=='__main__':main()
