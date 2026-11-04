"""Compare PDF core and optional layout resources in isolated processes.

Pass a pip --target directory containing PyMuPDF 2.x and psutil. The current
application environment supplies the baseline; no production packages change.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def probe(args):
    sys.path.insert(0, str(Path(args.packages).resolve()))
    import psutil
    if args.mode == "baseline":
        sys.path.pop(0)
    process = psutil.Process()
    rows = []

    def stage(name, function):
        wall, cpu = time.perf_counter(), time.process_time()
        result = function()
        info = process.memory_info()
        row = dict(stage=name, wall_ms=(time.perf_counter()-wall)*1000,
            cpu_ms=(time.process_time()-cpu)*1000, rss_mib=info.rss/1048576,
            peak_mib=getattr(info, "peak_wset", info.rss)/1048576,
            threads=process.num_threads(), onnx_loaded="onnxruntime" in sys.modules,
            layout_loaded="pymupdf.layout" in sys.modules)
        rows.append(row)
        print(json.dumps(dict(event="stage", **row)), flush=True)
        return result

    pdf = stage("import", lambda: __import__("pymupdf"))
    document = stage("open", lambda: pdf.open(args.document[0]))
    page = document[0]
    def ordinary():
        text = page.get_text("dict")
        scale = min(1100/page.rect.width, 800/page.rect.height)
        pix = page.get_pixmap(matrix=pdf.Matrix(scale, scale), alpha=False)
        return dict(blocks=len(text["blocks"]), pixels=pix.width*pix.height)
    ordinary_result = stage("ordinary", ordinary)
    layout_summary = None
    if args.mode == "layout":
        def initialize_layout():
            if args.threads or args.no_spin:
                import onnxruntime as ort
                original = ort.SessionOptions
                def options():
                    value = original()
                    if args.threads:
                        value.intra_op_num_threads = args.threads
                        value.inter_op_num_threads = 1
                    if args.no_spin:
                        value.add_session_config_entry("session.intra_op.allow_spinning", "0")
                        value.add_session_config_entry("session.inter_op.allow_spinning", "0")
                    return value
                # Experiment-local configuration; no installed package is edited.
                ort.SessionOptions = options
            return __import__("pymupdf.layout")
        stage("layout_init", initialize_layout)
        stage("layout_first", page.get_layout)
        value = page.layout_information
        import hashlib
        from collections import Counter
        normalized = [[round(float(x), 4) for x in row[:4]] + [str(row[4])] for row in value]
        layout_summary = dict(type=type(value).__name__, count=len(value),
            labels=dict(Counter(row[4] for row in normalized)),
            boxes_sha256=hashlib.sha256(json.dumps(normalized).encode()).hexdigest())
        stage("layout_second", page.get_layout)
    stage("idle_first", lambda: time.sleep(2))
    stage("idle_settled", lambda: time.sleep(2))
    print(json.dumps(dict(event="result", version=pdf.VersionBind, mupdf=pdf.VersionFitz,
        mode=args.mode, label=args.label, threads_limit=args.threads, no_spin=args.no_spin, stages=rows, ordinary=ordinary_result,
        layout=layout_summary)), flush=True)
    document.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages",type=Path,required=True)
    parser.add_argument("--document",type=Path,action="append",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--repeat",type=int,default=2)
    parser.add_argument("--probe",action="store_true")
    parser.add_argument("--threads",type=int,default=0)
    parser.add_argument("--no-spin",action="store_true")
    parser.add_argument("--modes",nargs="+",choices=("baseline","core","layout"),default=["baseline","core","layout"])
    parser.add_argument("--mode",choices=("baseline","core","layout"))
    parser.add_argument("--label",default="document")
    args=parser.parse_args()
    if args.probe:
        probe(args)
        return
    sys.path.insert(0,str(args.packages.resolve()))
    import psutil
    sys.path.pop(0)
    args.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for index,document in enumerate(args.document):
        for mode in args.modes:
            for repeat in range(args.repeat):
                label=document.stem
                command=[sys.executable,str(Path(__file__).resolve()),"--probe",
                    "--packages",str(args.packages.resolve()),"--document",str(document.resolve()),
                    "--output",str(args.output.resolve()),"--mode",mode,"--label",label,
                    "--threads",str(args.threads)]
                if args.no_spin:
                    command.append("--no-spin")
                stem=f"doc{index}-{mode}-{repeat}"
                stdout=args.output/(stem+".stdout.log")
                stderr=args.output/(stem+".stderr.log")
                start=time.perf_counter();aborted=None
                with stdout.open("wb") as out,stderr.open("wb") as err:
                    child=subprocess.Popen(command,stdout=out,stderr=err,
                        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                    monitored=psutil.Process(child.pid)
                    while child.poll() is None:
                        try:
                            if monitored.memory_info().rss > 2*1024**3:
                                aborted="RSS exceeded 2 GiB"
                        except psutil.NoSuchProcess:
                            pass
                        if time.perf_counter()-start>120:
                            aborted="120 second timeout"
                        if aborted:
                            child.kill();child.wait();break
                        time.sleep(.025)
                result=None
                for line in stdout.read_text(encoding="utf-8",errors="replace").splitlines():
                    try:message=json.loads(line)
                    except ValueError:continue
                    if message.get("event")=="result":result=message
                row=dict(label=label,mode=mode,repeat=repeat,returncode=child.returncode,
                    aborted=aborted,total_ms=(time.perf_counter()-start)*1000,result=result,
                    stderr=str(stderr.resolve()))
                rows.append(row)
                (args.output/"results.json").write_bytes(json.dumps(rows,indent=2).encode())
                print(json.dumps(dict(label=label,mode=mode,repeat=repeat,
                    success=result is not None and child.returncode==0)),flush=True)
    if any(r["returncode"] or r["result"] is None for r in rows):
        raise SystemExit(1)


if __name__=="__main__":
    main()
