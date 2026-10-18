"""Live integration scan in a disposable copy: no sends or production-state push."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import run

def main():
    destination=ROOT/"validation-results"
    destination.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work=Path(tmp)
        for name in ("config.yaml","companies.yaml","source_registry.json"):
            shutil.copy(ROOT/name,work/name)
        shutil.copytree(ROOT/"data",work/"data")
        os.chdir(work)
        result=run.prepare()
        for name in ("vacancies.json","vacancies.csv","discovery_report.json"):
            source=work/"data"/name
            if source.exists():shutil.copy(source,destination/name)
        os.chdir(ROOT)
        if result:return result
    report=json.loads((destination/"discovery_report.json").read_text())
    print("LIVE_SCAN_CONFIRMED "+json.dumps(report))
    catalogue=json.loads((destination/"vacancies.json").read_text())
    fields=("company","title","location","country","priority","link","deadline","verification_status","date_last_verified","review_flags")
    sample=sorted((j for j in catalogue["jobs"].values() if j.get("geographic_priority")==1 and j.get("verification_status")=="open"),key=lambda j:-j.get("rank_score",0))[:12]
    print("VERIFIED_IRELAND_SAMPLE "+json.dumps([{k:j.get(k) for k in fields} for j in sample]))
    return 0
if __name__=="__main__":sys.exit(main())
