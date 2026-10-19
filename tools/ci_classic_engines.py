"""Explicit CI preparation from the already pinned public executable archive.

No download occurs here. Ordinary application actions never call this module.
Only the two exact double-precision classic engines are extracted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from basinlens_ccs.subsurface.classic import PINNED

ARCHIVE_BYTES=45010855
ARCHIVE_SHA="ab17192a3531dec61d4f4eab3da10f618e85d1f792d5edc71306a3e06e0e22c3"


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):digest.update(chunk)
    return digest.hexdigest()


def prepare(archive,output_dir):
    archive=Path(archive);output=Path(output_dir)
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size!=ARCHIVE_BYTES or sha(archive)!=ARCHIVE_SHA:
        raise ValueError("The original pinned public archive bytes are required")
    if output.is_symlink() or not output.is_dir():raise ValueError("Choose an existing trusted solver directory")
    paths={key:output/value["member"] for key,value in PINNED.items()}
    if any(p.exists() or p.is_symlink() for p in paths.values()):raise FileExistsError("Classic executables already exist")
    payloads={}
    with zipfile.ZipFile(archive) as zipped:
        entries=zipped.infolist()
        if len(entries)>64:raise ValueError("Unexpected public archive member count")
        for key,spec in PINNED.items():
            matching=[e for e in entries if e.filename==spec["member"]]
            if len(matching)!=1 or matching[0].file_size!=spec["bytes"]:
                raise ValueError("Pinned classic member missing, duplicated or changed")
            raw=zipped.read(matching[0])
            if hashlib.sha256(raw).hexdigest()!=spec["sha256"]:raise ValueError("Classic binary digest mismatch")
            payloads[key]=raw
    written=[]
    try:
        for key,path in paths.items():
            with path.open("xb") as target:target.write(payloads[key])
            written.append(path);path.chmod(0o755)
        for key,path in paths.items():
            if sha(path)!=PINNED[key]["sha256"]:raise ValueError("Extracted binary changed")
    except BaseException:
        for path in written:path.unlink(missing_ok=True)
        raise
    return {"schema":"basinlens-classic-ci-preparation-v1","archive_sha256":ARCHIVE_SHA,
        "archive_bytes":ARCHIVE_BYTES,"automatic_download":False,
        "executables":{key:{**PINNED[key],"path":str(path.absolute())} for key,path in paths.items()}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True);args=parser.parse_args(argv)
    if args.report.exists():parser.error("Choose a new evidence file")
    result=prepare(args.archive,args.output)
    with args.report.open("x",encoding="utf-8") as target:json.dump(result,target,indent=2,sort_keys=True);target.write("\n")
    print(json.dumps({"prepared":list(result["executables"]),"archive_sha256":ARCHIVE_SHA}))


if __name__=="__main__":main()
