"""Read-only conversion of saved acquisitions to separate EEG-BIDS datasets."""
from pathlib import Path
import argparse, json, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_eeg.utils.bids_export import discover, export_recording, validate_dataset

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,help='Saved recording, Session or subject directory; finish acquisition first')
    p.add_argument('--output',required=True,help='Separate BIDS dataset root')
    p.add_argument('--protocol',choices=('v1','v2'),required=True)
    p.add_argument('--validate',action='store_true',help='Run bundled official validator offline')
    args=p.parse_args(); errors=[]; recordings=discover(args.source)
    if not recordings: p.error('No saved metadata.json recordings found')
    for directory in recordings:
        try: print(json.dumps(export_recording(directory,args.output,protocol=args.protocol),ensure_ascii=False),flush=True)
        except Exception as exc:
            errors.append(str(directory)+': '+str(exc)); print(errors[-1],file=sys.stderr,flush=True)
    if args.validate and not errors:
        try: print(json.dumps(validate_dataset(args.output),ensure_ascii=False))
        except Exception as exc: errors.append(str(exc)); print(exc,file=sys.stderr)
    return 1 if errors else 0
if __name__=='__main__': raise SystemExit(main())
