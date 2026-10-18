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
    return 0
if __name__=="__main__":sys.exit(main())
