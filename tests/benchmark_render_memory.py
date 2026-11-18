"""Own one Reader window and measure memory after opening, zooming and panning."""
import argparse
from dataclasses import asdict
import gc
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import psutil
import pymupdf
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from pdfeditor import app as application, settings, paths
from pdfeditor.core import _gpu_scene_cost


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--renderer', choices=('gpu', 'cpu'), default='gpu')
    parser.add_argument('--cache-mb', type=int, default=0)
    args = parser.parse_args()
    pdf = args.pdf.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()
    rows = []
    peak = {'rss': 0, 'private': 0, 'children_rss': 0}
    state = dict(stage=0, stable=None, deadline=time.monotonic()+90, origin=None, fit=None)
    stages = ('fit', '800', 'pan', 'back', '3200', 'fit_return', 'purge_mupdf',
              'release_scenes', 'release_gpu', 'closed')
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app._spdf_standalone_reader = True

    def memory():
        m = process.memory_info()
        children = []
        for child in process.children(recursive=True):
            try:
                cm = child.memory_info()
                children.append(dict(pid=child.pid, rss=cm.rss, private=getattr(cm, 'private', cm.vms)))
            except psutil.Error:
                pass
        result = dict(rss=m.rss, private=getattr(m, 'private', m.vms),
                      children_rss=sum(c['rss'] for c in children), children=children)
        for key in peak:
            peak[key] = max(peak[key], result[key])
        return result

    def sample(label, view=None, tab=None):
        row = dict(stage=label, memory=memory(), mupdf_store=pymupdf.TOOLS.store_size(),
                   mupdf_store_limit=pymupdf.TOOLS.store_maxsize())
        if view is not None and view._document is not None:
            doc = view._document
            archive = getattr(doc, '_gpu_packed_cache', None)
            row['prefetch'] = view.prefetch_diagnostic()
            row['packed_bytes'] = archive.bytes if archive else 0
            groups = {'document': list(doc._gpu_vector_cache.values()),
                      'view': list(view._vector_pages.values()),
                      'viewport': list(view._vector_viewport_pages.values()),
                      'native_sources': [v[0] for v in view._d2d_vector_paths.values()]}
            unique = {id(scene): scene for group in groups.values() for scene in group if scene is not None}
            packets = {id(s.compiled_packet): s.compiled_packet for s in unique.values() if s.compiled_packet}
            row['scene_objects'] = len(unique)
            row['unique_packet_bytes'] = sum(map(len, packets.values()))
            row['scene_estimated_bytes'] = sum(_gpu_scene_cost(s) for s in unique.values())
            row['scenes'] = [dict(scale=s.raster_scale, viewport=s.viewport, packet_bytes=len(s.compiled_packet))
                             for s in unique.values()]
            previews = {p.cacheKey(): p for p in view._previews.values()}
            row['preview_pixels_bytes'] = sum(p.width()*p.height()*4 for p in previews.values())
            row['cpu_tile_bytes'] = view._tile_bytes
            row['display_lists'] = len(doc._display_cache)
            row['zoom_percent'] = tab.zoom_percent()
            row['render_status'] = view.render_diagnostic(0)
            surface = view._d2d_surface
            if surface is not None:
                row['native'] = surface.memory_statistics()
                row['video_budget_usage'] = surface.video_memory()
                row['device'] = asdict(surface.info)
        rows.append(row)
        print(json.dumps(row), flush=True)
        args.output.write_text(json.dumps(dict(pdf_bytes=pdf.stat().st_size, renderer=args.renderer,
            rows=rows, peak=peak), indent=2), encoding='utf-8')

    with tempfile.TemporaryDirectory(prefix='leaflet-memory-') as directory:
        preference = Path(directory)/'settings.json'
        preference.write_text(json.dumps(dict(render_backend=args.renderer, reader_resident=False,
            disk_cache_mb=0, render_cache_mb=args.cache_mb)), encoding='utf-8')
        with patch.object(settings, 'PATH', str(preference)), \
                patch.object(paths, 'user_data_dir', return_value=directory), \
                patch.dict(os.environ, {'LOCALAPPDATA': directory}):
            sample('empty')
            window = application.new_window(str(pdf), workspace_mode='reader', updates_enabled=False)
            window.resize(1100, 800)
            timer = QTimer(window)
            timer.setInterval(50)

            def inspect():
                memory()
                tab = window._tabs.currentWidget()
                view = getattr(tab, 'view', None)
                stage = stages[state['stage']]
                if view is None or tab.doc is None:
                    return
                scene = view._display_vector_scene(0)
                if stage == 'release_scenes':
                    ready = True
                elif args.renderer == 'gpu' and stage != 'release_gpu':
                    native = view._d2d_vector_paths.get(0)
                    ready = (scene is not None and scene.supported and native is not None and
                             native[0] is scene and scene.raster_scale >= view._vector_raster_scale() and
                             not view._image_refinement_pending(0, scene) and not view._sharp_poll_timer.isActive())
                    if scene is not None and scene.viewport is not None:
                        ready = ready and view._viewport_scene_covers(0, scene)
                else:
                    ready = not view._pending and not view._tile_timer.isActive()
                ready = ready and view.prefetch_diagnostic()['active_workers'] == 0
                if ready:
                    if state['stable'] is None:
                        state['stable'] = time.monotonic()
                    ready = time.monotonic()-state['stable'] > 3.0
                else:
                    state['stable'] = None
                if time.monotonic() > state['deadline']:
                    sample('TIMEOUT_'+stage, view, tab)
                    timer.stop(); app.exit(1); return
                if not ready:
                    return
                sample(stage, view, tab)
                if stage == 'fit':
                    state['fit'] = tab.zoom_percent()
                state['stage'] += 1
                state['stable'] = None
                state['deadline'] = time.monotonic()+90
                next_stage = stages[state['stage']]
                if next_stage in ('800', '3200'):
                    tab._zoom_input.setValue(int(next_stage))
                    view._schedule_vector_refine(0)
                elif next_stage == 'pan':
                    state['origin'] = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
                    view.horizontalScrollBar().setValue(state['origin'][0] + view.viewport().width()*2)
                    view.verticalScrollBar().setValue(state['origin'][1] + view.viewport().height()*2)
                    view._schedule_vector_refine(0)
                elif next_stage == 'back':
                    view.horizontalScrollBar().setValue(state['origin'][0])
                    view.verticalScrollBar().setValue(state['origin'][1])
                    view._schedule_vector_refine(0)
                elif next_stage == 'fit_return':
                    tab.set_zoom_percent(state['fit'])
                    view._schedule_vector_refine(0)
                elif next_stage == 'purge_mupdf':
                    pymupdf.TOOLS.store_shrink(100)
                    gc.collect()
                elif next_stage == 'release_scenes':
                    view.setUpdatesEnabled(False)
                    view.stop_rendering()
                    for page in tuple(view._d2d_vector_paths):
                        view._discard_native_vector_page(page)
                    gc.collect()
                elif next_stage == 'release_gpu':
                    view.set_render_backend('cpu')
                    view.setUpdatesEnabled(True)
                    gc.collect()
                elif next_stage == 'closed':
                    timer.stop()
                    window.close_tab(tab)
                    def finish():
                        gc.collect()
                        sample('closed')
                        window.close(); app.quit()
                    QTimer.singleShot(1500, finish)

            timer.timeout.connect(inspect)
            timer.start()
            result = app.exec_()
            descendants = process.children(recursive=True)
            for child in descendants:
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            _, remaining = psutil.wait_procs(descendants, timeout=2)
            for child in remaining:
                try:
                    child.kill()
                except psutil.Error:
                    pass
    os._exit(result)


if __name__ == '__main__':
    main()
