"""Reorder original PDF words using layout regions, without generating text."""
from collections import defaultdict


def text_in_layout_order(words, regions):
    buckets = defaultdict(list)
    for word in words:
        cx, cy = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
        enclosing = [i for i, box in enumerate(regions)
                     if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]]
        # Prefer a text-sized box over a containing illustration/table box.
        index = min(enclosing, key=lambda i: (regions[i][2] - regions[i][0]) *
                    (regions[i][3] - regions[i][1])) if enclosing else len(regions)
        buckets[index].append(word)
    paragraphs = []
    for index in sorted(buckets):
        lines = defaultdict(list)
        for word in buckets[index]:
            lines[(word[5], word[6])].append(word)
        ordered = sorted(lines.values(), key=lambda line: (
            min(w[1] for w in line), min(w[0] for w in line)))
        paragraphs.append(" ".join(" ".join(w[4] for w in sorted(line, key=lambda w: w[0]))
                                   for line in ordered))
    return "\n\n".join(paragraphs)
