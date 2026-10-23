"""Manual scene-complexity discovery; does not change rendering or input PDFs.

Example: python -m tests.analyze_gpu_scene_complexity input.pdf --output report.json
Counts refer to extracted Python scene items, before native empty-layer removal.
Illustration compilation is disabled unless --compiled is requested.
Candidate boxes are discovery hints, not proof that a group can be composited
independently. Keep reports for private input documents outside source control.
"""

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import time

import pymupdf

from pdfeditor.gpu_raster import (
    ClipPop, ClipPush, ClipStrokePush, GroupPop, GroupPush, MaskBegin,
    MaskEnd, _item_bbox, vector_page_from_pymupdf,
)


def analyze_scene(scene, page_rect, *, min_items=128, max_page_fraction=.005):
    """Find small isolated knockout subtrees with many scene items."""
    items = scene.drawables
    nodes = []
    stack = []
    for index, item in enumerate(items):
        if isinstance(item, (GroupPush, ClipPush, ClipStrokePush, MaskBegin)):
            node = {
                "start": index, "kind": type(item).__name__,
                "parent": stack[-1] if stack else None,
                "depth": len(stack), "bbox": None,
                "properties": asdict(item) if isinstance(item, GroupPush) else {},
                "mask_build": isinstance(item, MaskBegin),
                "protected": any(n["mask_build"] for n in stack),
                "counts": Counter(),
            }
            stack.append(node)
            nodes.append(node)
        elif isinstance(item, MaskEnd):
            if not stack or stack[-1]["kind"] != "MaskBegin":
                raise ValueError("unbalanced mask transition")
            stack[-1]["mask_build"] = False
        elif isinstance(item, (GroupPop, ClipPop)):
            if not stack:
                raise ValueError("unbalanced scope end")
            node = stack.pop()
            if (node["kind"] == "GroupPush") != isinstance(item, GroupPop):
                raise ValueError("mismatched scope end")
            node["end"] = index
            if stack:
                stack[-1]["counts"].update(node["counts"])
                stack[-1]["counts"][node["kind"]] += 1
                _expand_box(stack[-1], node["bbox"])
        elif stack:
            stack[-1]["counts"][type(item).__name__] += 1
            _expand_box(stack[-1], _item_bbox(item))
    if stack:
        raise ValueError("unclosed scopes")

    page_area = max(0, page_rect.width) * max(0, page_rect.height)
    selected = []
    last_end = -1
    for node in nodes:
        props = node["properties"]
        box = node["bbox"]
        if node["start"] <= last_end or box is None or page_area <= 0:
            continue
        item_count = node["end"] - node["start"] + 1
        area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
        if not (props.get("isolated") and props.get("knockout")
                and props.get("blend_mode") == 0 and props.get("opacity") == 1
                and not node["protected"] and item_count >= min_items
                and 0 < area / page_area <= max_page_fraction):
            continue
        selected.append({
            "start": node["start"], "end": node["end"],
            "items": item_count, "depth": node["depth"],
            "bbox": box, "bbox_area": area,
            "page_fraction": area / page_area,
            "properties": props, "contents": dict(node["counts"]),
        })
        last_end = node["end"]
    covered = sum(n["items"] for n in selected)
    return {
        "supported": scene.supported, "features": scene.features,
        "scene_items": len(items),
        "types": dict(Counter(type(item).__name__ for item in items)),
        "max_scope_depth": max((n["depth"] + 1 for n in nodes), default=0),
        "candidate_count": len(selected), "covered_items": covered,
        "covered_fraction": covered / len(items) if items else 0,
        "bbox_area_sum_fraction": sum(n["bbox_area"] for n in selected) / page_area
        if page_area else 0,
        "items_after_one_image_per_candidate": len(items) - covered + len(selected),
        "candidates": selected,
    }


def _expand_box(node, box):
    if box is None:
        return
    old = node["bbox"]
    node["bbox"] = tuple(box) if old is None else (
        min(old[0], box[0]), min(old[1], box[1]),
        max(old[2], box[2]), max(old[3], box[3]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, nargs="+")
    parser.add_argument("--page", type=int, default=1, help="One-based page number")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiled", action="store_true",
                        help="Analyze after optional illustration compilation")
    parser.add_argument("--min-items", type=int, default=128)
    parser.add_argument("--max-page-fraction", type=float, default=.005)
    args = parser.parse_args()
    if args.page < 1 or args.min_items < 1 or not 0 < args.max_page_fraction <= 1:
        parser.error("invalid page, item threshold, or page fraction")
    records = []
    for filename in args.pdf:
        started = time.perf_counter()
        with pymupdf.open(filename) as pdf:
            page = pdf[args.page - 1]
            scene = vector_page_from_pymupdf(page, raster_scale=1,
                                           simplify_regions=args.compiled)
            if not scene.supported:
                raise RuntimeError(f"{filename.name}: {scene.reason}")
            record = analyze_scene(
                scene, page.rect, min_items=args.min_items,
                max_page_fraction=args.max_page_fraction,
            )
            record.update(file=filename.name, page=args.page,
                          page_size=[page.rect.width, page.rect.height])
        record["analysis_ms"] = (time.perf_counter() - started) * 1000
        records.append(record)
        print(filename.name, record["scene_items"], "items;",
              record["candidate_count"], "candidates covering",
              f"{record['covered_fraction']:.2%}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
