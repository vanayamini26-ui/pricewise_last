"""Turns raw per-platform listings into the comparison table the UI shows."""
from dataclasses import asdict
from typing import Dict

from matching import (is_accessory, is_electronic, is_relevant, memory_label,
                      pair_score, parse_title)
from scrapers.common import FetchResult

MAX_ROWS = 12
PLATFORMS = ("amazon", "flipkart")


def _images(*listings):
    """Image addresses of a product from each store (best first, no duplicates), so the page can
    fall back to the other store's picture if one fails to load."""
    out = []
    for item in listings:
        if item and item.image and item.image not in out:
            out.append(item.image)
    return out


def build_comparison(query: str, data: Dict[str, FetchResult]) -> dict:
    qspec = parse_title(query)
    kept, meta = {}, {}
    for name in PLATFORMS:
        fr = data[name]
        rows = []
        for item in fr.listings:
            if not is_electronic(item.name) or is_accessory(item.name, query):
                continue
            spec = parse_title(item.name)
            if is_relevant(qspec, spec):
                rows.append((item, spec))
        kept[name] = rows
        meta[name] = {"status": fr.status, "message": fr.message,
                      "fetched_at": fr.fetched_at,
                      "checked": len(fr.listings), "matched": len(rows)}

    # One-to-one pairing, best score first.
    cands = []
    for i, (a, aspec) in enumerate(kept["amazon"]):
        for j, (f, fspec) in enumerate(kept["flipkart"]):
            s = pair_score(aspec, fspec)
            if s > 0:
                cands.append((s, -(a.rank + f.rank), i, j))
    cands.sort(reverse=True)
    used_a, used_f, pairs = set(), set(), []
    for s, _, i, j in cands:
        if i in used_a or j in used_f:
            continue
        used_a.add(i)
        used_f.add(j)
        pairs.append((i, j, s))

    def side_note(platform):
        st = data[platform].status
        if st in ("blocked", "error"):
            return "unavailable"
        return "no_match"

    rows = []
    for i, j, s in pairs:
        a, aspec = kept["amazon"][i]
        f, fspec = kept["flipkart"][j]
        diff = abs(a.price - f.price)
        cheaper = "same" if a.price == f.price else ("amazon" if a.price < f.price else "flipkart")
        rows.append({
            "name": a.name, "spec": memory_label(aspec) or memory_label(fspec),
            "image": a.image or f.image, "images": _images(a, f), "amazon": asdict(a), "flipkart": asdict(f),
            "amazon_note": None, "flipkart_note": None,
            "difference": diff, "cheaper": cheaper, "match_score": round(s, 2),
            "_order": min(a.rank, f.rank),
        })
    for i, (a, aspec) in enumerate(kept["amazon"]):
        if i not in used_a:
            rows.append({"name": a.name, "spec": memory_label(aspec), "image": a.image, "images": _images(a),
                         "amazon": asdict(a), "flipkart": None, "amazon_note": None,
                         "flipkart_note": side_note("flipkart"), "difference": None,
                         "cheaper": None, "match_score": None, "_order": 1000 + a.rank})
    for j, (f, fspec) in enumerate(kept["flipkart"]):
        if j not in used_f:
            rows.append({"name": f.name, "spec": memory_label(fspec), "image": f.image, "images": _images(f),
                         "amazon": None, "flipkart": asdict(f), "amazon_note": side_note("amazon"),
                         "flipkart_note": None, "difference": None, "cheaper": None,
                         "match_score": None, "_order": 1000 + f.rank})
    rows.sort(key=lambda r: r["_order"])
    for r in rows:
        r.pop("_order")
    return {"query": query, "platforms": meta, "results": rows[:MAX_ROWS],
            "paired": len(pairs)}
