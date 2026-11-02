"""Real window: cold PDF -> 800% -> 3200% -> pan, with bounded viewport data."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from pdfeditor import app as application, settings, paths
from pdfeditor.__main__ import main as app_main
from tests.benchmark_gpu_pipeline import process_memory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pdf = args.pdf.resolve()
    output = args.output.resolve()
    original = application.new_window
    targets = [None, 800, 3200, 'pan']
    rows = []
    state = dict(stage=0, ready_at=None, success=False)

    def observe_window(*positional, **kwargs):
        # The harness owns QApplication through final cleanup, as the isolated
        # Qt test runner does. Avoid unrelated Qt DLL finalizer ordering here.
        state['application'] = QApplication.instance()
        window = original(*positional, **kwargs)
        window.resize(1100, 800)
        timer = QTimer(window)
        timer.setInterval(20)
        state['deadline'] = time.monotonic()+45
        def inspect():
            tab = window._tabs.currentWidget()
            view = getattr(tab, 'view', None)
            scene = view._display_vector_scene(0) if view is not None else None
            retained = view._d2d_vector_paths.get(0) if view is not None else None
            drawn = getattr(view, '_rasterized_pages', {}).get(0)
            ready = (scene is not None and scene.supported and retained is not None
                and retained[0] is scene and drawn in ('GPU','CPU+GPU'))
            if state['stage']:
                ready = ready and scene.raster_scale >= view._vector_raster_scale()
                if scene.viewport is not None:
                    ready = ready and view._viewport_scene_covers(0, scene)
            if ready:
                if state['ready_at'] is None:
                    state['ready_at'] = time.monotonic()
                # Allow optional sharp work to settle before sampling memory.
                if time.monotonic()-state['ready_at'] >= .4:
                    region = scene.viewport
                    pixels = ((region[2]-region[0])*(region[3]-region[1])*scene.raster_scale**2
                              if region is not None else None)
                    if pixels is not None:
                        assert pixels <= 12_000_001, pixels
                    assert view._tile_bytes <= 64*1024*1024
                    rows.append(dict(percent=tab.zoom_percent(),zoom=view.zoom,stage=targets[state['stage']],
                        drawn=drawn,scene_scale=scene.raster_scale,packet_bytes=len(scene.compiled_packet),
                        prepared_pixels=pixels,cpu_tile_bytes=view._tile_bytes,
                        percent_max=tab._zoom_input.maximum(),**process_memory()))
                    state['stage'] += 1
                    state['ready_at'] = None
                    state['deadline'] = time.monotonic()+45
                    if state['stage'] == len(targets):
                        state['success'] = True
                    elif targets[state['stage']] == 'pan':
                        view.horizontalScrollBar().setValue(
                            view.horizontalScrollBar().value()+round(view.viewport().width()*1.5))
                        view.verticalScrollBar().setValue(
                            view.verticalScrollBar().value()+round(view.viewport().height()*1.25))
                        view._schedule_vector_refine(0)
                    else:
                        tab._zoom_input.setValue(targets[state['stage']])
                        assert round(tab.zoom_percent()) == targets[state['stage']]
                        view._schedule_vector_refine(0)
            else:
                state['ready_at'] = None
            if state['success'] or time.monotonic()>state['deadline']:
                report = dict(success=state['success'],document=pdf.name,rows=rows,
                              diagnostic=view.render_diagnostic(0))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps(report),flush=True)
                timer.stop()
                QTimer.singleShot(0,window.close)
        timer.timeout.connect(inspect)
        timer.start()
        return window

    with tempfile.TemporaryDirectory(prefix='leaflet-high-zoom-') as directory:
        preference = Path(directory)/'settings.json'
        preference.write_text(json.dumps(dict(reader_resident=False,render_backend='gpu',
            render_diagnostics=True,disk_cache_mb=0)),encoding='utf-8')
        sys.argv = [sys.argv[0], '--no-updates','--no-resident','--workspace','reader',str(pdf)]
        with patch.object(settings,'PATH',str(preference)), \
                patch.object(paths,'user_data_dir',return_value=directory), \
                patch.object(application,'new_window',side_effect=observe_window):
            try: app_main(allow_residency=False)
            except SystemExit: pass
        store = getattr(state.get('application'), '_spdf_recovery_store', None)
        if store is not None:
            for lock in store._locks.values():
                lock.unlock()  # Release this harness's private recovery directory.
    os._exit(0 if state['success'] else 1)


if __name__ == '__main__': main()
