"""Explicit local status updates; discovery never submits an application."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sources.catalogue import STATUSES,set_status,validate_applications,validate_catalogue,empty_catalogue
from sources.state import load_json,save_json

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("catalogue_id");p.add_argument("status",choices=sorted(STATUSES));p.add_argument("--note",default="")
    args=p.parse_args()
    catalogue=load_json(Path("data/vacancies.json"),validate_catalogue,empty_catalogue())
    if args.catalogue_id not in catalogue["jobs"]:p.error("Unknown catalogue ID")
    path=Path("data/applications.json")
    ledger=load_json(path,validate_applications,{"version":1,"records":{}})
    set_status(ledger,args.catalogue_id,args.status,args.note)
    save_json(path,ledger,validate_applications)
    print(f"Saved {args.status}; no application was submitted by this command")
if __name__=="__main__":main()
