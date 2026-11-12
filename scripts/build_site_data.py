#!/usr/bin/env python3
"""Publish-safe snapshot of existing pilots and analyses. No API calls."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from shiritori_bench.public_site import build_public_payload
from shiritori_bench.results import read_jsonl
from shiritori_bench.bots import VocabularyGraph
from shiritori_bench.frequency_bot import load_frequency_vocabulary
from shiritori_bench.site_evaluation import WordStrength, annotate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--destination", type=Path, default=PROJECT_ROOT / "web/data/results.json")
    args = parser.parse_args()
    frequency = PROJECT_ROOT / "data/processed/word-frequency.json"
    sources = sorted((PROJECT_ROOT / "results/pilots").glob("*/matches.jsonl"))
    records = [record for path in sources for record in read_jsonl(path)]
    if len({m["match_id"] for m in records}) != len(records):
        raise SystemExit("Duplicate match IDs: refusing to double-count games")
    frequency_data = json.loads(frequency.read_text())
    research_path = PROJECT_ROOT / 'web/data/research.json'
    if args.analysis or args.diagnostics:
        if not (args.analysis and args.diagnostics):
            parser.error('Provide both --analysis and --diagnostics, or neither')
        analysis_data=json.loads(args.analysis.read_text())
        diagnostic_data=json.loads(args.diagnostics.read_text())
        if any(s.get('vocabulary_sha256') != frequency_data.get('vocabulary_sha256') for s in (analysis_data,diagnostic_data)):
            parser.error('Refusing to combine analyses from different vocabulary snapshots')
        research_payload=build_public_payload([],frequency_data,analysis_data,diagnostic_data)
        research={k:research_payload[k] for k in ('atlas','diagnostics')}
        research['provenance']=[{'file':str(p.relative_to(PROJECT_ROOT)), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (args.analysis,args.diagnostics,frequency)]
        research['label']='Offline research graph; separate from game outcomes and the selected move-strength metrics.'
        research_path.write_text(json.dumps(research,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    elif research_path.exists():
        research=json.loads(research_path.read_text())
    else:
        previous=json.loads(args.destination.read_text())
        research={k:previous[k] for k in ('atlas','diagnostics','provenance')}
        research['label']='Archived noun-v2 offline research graph; not the current per-move scoring graph.'
        research_path.write_text(json.dumps(research,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    database=PROJECT_ROOT/'data/processed/referee-vocabulary.sqlite'
    _,frequencies,scoring_provenance=load_frequency_vocabulary(database,frequency)
    scorer=WordStrength(VocabularyGraph.from_sqlite(str(database)),frequencies)
    payload=annotate(build_public_payload(records,frequency_data,{},{}),records,scorer)
    payload.update({k:research[k] for k in ('atlas','diagnostics')})
    payload['research_label']=research['label']
    payload['scoring']={'id':'two-ply-log-mass-v1','gamma':.85,'alpha':1,'threshold':1,
        'code_sha256':hashlib.sha256((PROJECT_ROOT/'src/shiritori_bench/site_evaluation.py').read_bytes()).hexdigest(),
        'comparison_pool':'All unused safe dictionary readings with support for the evaluated metric; midrank percentiles with equal weight per alternative.',
        'label':'Post-hoc scores use one fixed noun-v3/TUBELEX graph for both competitions; historical referee decisions are unchanged.',
        'provenance':scoring_provenance}
    payload["provenance"] = [{"file": str(path.relative_to(PROJECT_ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in [*sources, research_path, frequency, database]]
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Exported {len(payload['games'])} competitive games; {payload['summary']['excluded_games']} infrastructure error(s) excluded.")
    print(f"Saved public allowlisted data: {args.destination}")


if __name__ == "__main__":
    main()
