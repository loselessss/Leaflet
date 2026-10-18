import unittest

from pdfeditor.object_snapping import SnapTargets


class ObjectSnappingTests(unittest.TestCase):
    def setUp(self):
        self.targets = SnapTargets([(0, 0, 400, 600), (150, 180, 230, 240)])

    def test_edges_snap_and_preserve_size(self):
        rect, guides = self.targets.place((98, 178, 148, 218), (6, 6))
        self.assertEqual(rect, (100, 180, 150, 220))
        self.assertEqual([(g.axis, g.position) for g in guides], [(0, 150), (1, 180)])
        self.assertLessEqual(guides[0].start, 180)
        self.assertGreaterEqual(guides[0].end, 240)

    def test_page_and_peer_centers(self):
        rect, _ = self.targets.place((164, 85, 214, 135), (3, 3))
        self.assertEqual(rect, (165, 85, 215, 135))  # peer center 190
        rect, _ = self.targets.place((173, 275, 223, 315), (3, 3))
        self.assertEqual(rect, (175, 275, 225, 315))  # page center 200

    def test_ctrl_bypass_keeps_guides_and_raw_geometry(self):
        raw = (98, 178, 148, 218)
        rect, guides = self.targets.place(raw, (6, 6), bypass=True)
        self.assertEqual(rect, raw)
        self.assertEqual(len(guides), 2)

    def test_outside_tolerance_does_not_snap(self):
        raw = (87, 155, 137, 195)
        self.assertEqual(self.targets.place(raw, (3, 3)), (raw, []))

    def test_locked_axis_never_moves_or_gets_guide(self):
        rect, guides = self.targets.place((98, 178, 148, 218), (6, 6), allowed=(True, False))
        self.assertEqual(rect, (100, 178, 150, 218))
        self.assertEqual([g.axis for g in guides], [0])

    def test_tolerance_scales_independently_per_axis(self):
        rect, guides = self.targets.place((98, 178, 148, 218), (1, 3))
        self.assertEqual(rect, (98, 180, 148, 220))
        self.assertEqual([g.axis for g in guides], [1])

    def test_empty_targets_and_negative_page_coordinates(self):
        self.assertEqual(SnapTargets([]).place((1, 2, 3, 4), (6, 6)), ((1, 2, 3, 4), []))
        rect, guides = SnapTargets([(-100, -200, 100, 200)]).place((-102, -80, -52, -30), (6, 6))
        self.assertEqual(rect, (-100, -80, -50, -30))
        self.assertEqual(guides[0].position, -100)
