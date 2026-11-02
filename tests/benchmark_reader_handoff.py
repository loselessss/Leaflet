"""Warm result-receive responsiveness and CPU tile transfer; no PDF writes."""
import argparse
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import time
import tracemalloc

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pymupdf
from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication
from pdfeditor.core import Document
from pdfeditor.paths import gpu_scene_worker_command
from pdfeditor.raster_buffer import RasterBuffer
from pdfeditor.scene_worker_result import load, SceneResultRead
from pdfeditor.widgets import qimage_from_render
from tests.test_raster_handoff import rgb


def result_trial(source, asynchronous, parent):
    directory = Path(tempfile.mkdtemp(dir=parent))
    path = directory/'result.scene'
    shutil.copyfile(source, path)  # Input setup/warm file cache outside timing.
    loop, heartbeat, poll = QEventLoop(), QTimer(), QTimer()
    state = dict(last=time.perf_counter(), gaps=[], reader=None, scene=None)
    def tick():
        now = time.perf_counter()
        state['gaps'].append((now-state['last'])*1000)
        state['last'] = now
        if now-state['origin'] > 10:
            loop.quit()
        if 'finished' in state and now-state['finished'] > .015:
            loop.quit()
    def start():
        state['started'] = time.perf_counter()
        if asynchronous:
            state['reader'] = SceneResultRead(str(path), str(directory))
        else:
            with path.open('rb') as stream:
                state['scene'] = load(stream)
            shutil.rmtree(directory)
            state['finished'] = time.perf_counter()
        state['dispatch_ms'] = (time.perf_counter()-state['started'])*1000
    def collect():
        reader = state['reader']
        if reader is not None and reader.done() and 'finished' not in state:
            state['scene'], error = reader.take()
            assert error is None, error
            state['finished'] = time.perf_counter()
    state['origin'] = time.perf_counter()
    heartbeat.timeout.connect(tick)
    poll.timeout.connect(collect)
    heartbeat.start(1)
    poll.start(5)  # Same result-collection interval as ReaderPageView.
    QTimer.singleShot(20, start)
    loop.exec_()
    heartbeat.stop()
    poll.stop()
    assert 'finished' in state, 'result decode timed out'
    scene = state['scene']
    assert scene.supported and scene.compiled_packet
    return dict(dispatch_ms=state['dispatch_ms'],
        receive_ms=(state['finished']-state['started'])*1000,
        max_gui_gap_ms=max(state['gaps']),packet_bytes=len(scene.compiled_packet),
        sha256=hashlib.sha256(scene.compiled_packet).hexdigest())


def result_benchmark(pdf, root, runs):
    rows = []
    for scale in (1., 8.):
        source = root/(pdf.stem+f'-{scale}.scene')
        subprocess.run([*gpu_scene_worker_command(), str(pdf), str(source), '--scale', str(scale),
            '--timeout', '30'], check=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
        modes = {False: [], True: []}
        for repeat in range(runs+1):
            for mode in ((False,True) if repeat%2==0 else (True,False)):
                row = result_trial(source, mode, root)
                if repeat:
                    modes[mode].append(row)
        assert len({r['sha256'] for values in modes.values() for r in values})==1
        for mode, values in modes.items():
            row = dict(document=pdf.name, scale=scale, asynchronous=mode,
                packet_bytes=values[0]['packet_bytes'], sha256=values[0]['sha256'])
            for metric in ('dispatch_ms','receive_ms','max_gui_gap_ms'):
                row[metric] = statistics.median(r[metric] for r in values)
            rows.append(row)
            print(json.dumps(dict(kind='result',**row)),flush=True)
    return rows


def tile_benchmark(pdf, runs):
    rows = []
    for rotation in (0,90):
        document = Document(str(pdf), read_only=True)
        try:
            page = document._doc[0]
            page.set_rotation(rotation)
            document.invalidate_render()
            for scale in (1.375,8.):
                rect = page.rect
                x = math.floor((rect.x0+rect.x1)*.5*scale/512)
                y = math.floor((rect.y0+rect.y1)*.5*scale/512)
                clip = ((x*512-1)/scale,(y*512-1)/scale,((x+1)*512+1)/scale,((y+1)*512+1)/scale)
                sdk = document._display_list(0).get_pixmap(matrix=pymupdf.Matrix(scale,scale),
                    clip=pymupdf.Rect(clip),alpha=False)
                def handoff(borrow):
                    samples = RasterBuffer(sdk) if borrow else sdk.samples
                    image = qimage_from_render(sdk.width,sdk.height,sdk.stride,samples)
                    return image,QPixmap.fromImage(image)
                reference = rgb(handoff(False)[0])
                assert rgb(handoff(True)[0])==reference
                for borrow in (False,True):
                    transfer, total = [], []
                    for _ in range(3): handoff(borrow)
                    for _ in range(60):
                        started=time.perf_counter()
                        image,pixmap=handoff(borrow)
                        transfer.append((time.perf_counter()-started)*1000)
                    assert rgb(pixmap.toImage())==reference
                    gc.collect()
                    tracemalloc.start()
                    image,pixmap=handoff(borrow)
                    peak=tracemalloc.get_traced_memory()[1]
                    tracemalloc.stop()
                    for _ in range(runs):
                        started=time.perf_counter()
                        actual=document.render_region(0,scale,clip,copy_pixels=not borrow)
                        image=qimage_from_render(*actual[2:])
                        pixmap=QPixmap.fromImage(image)
                        total.append((time.perf_counter()-started)*1000)
                    assert rgb(image)==reference
                    assert actual[:2]==(sdk.x,sdk.y)
                    row=dict(document=pdf.name,scale=scale,rotation=rotation,borrow=borrow,
                        width=sdk.width,height=sdk.height,transfer_ms=statistics.median(transfer),
                        raster_and_transfer_ms=statistics.median(total),python_transfer_peak_bytes=peak,
                        changed_channels=0,sha256=hashlib.sha256(reference).hexdigest())
                    rows.append(row)
                    print(json.dumps(dict(kind='tile',**row)),flush=True)
        finally:
            document.close()
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path,nargs='+')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--runs',type=int,default=5)
    args=parser.parse_args()
    app=QApplication([])
    rows=dict(results=[],tiles=[])
    with tempfile.TemporaryDirectory(prefix='leaflet-handoff-bench-') as directory:
        for pdf in args.pdf:
            rows['results'].extend(result_benchmark(pdf.resolve(),Path(directory),args.runs))
            rows['tiles'].extend(tile_benchmark(pdf.resolve(),args.runs))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(rows,indent=2),encoding='utf-8')
    os._exit(0)


if __name__=='__main__':main()
