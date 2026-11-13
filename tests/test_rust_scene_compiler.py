"""Independent compiler core; not a claim of a new rendering backend."""
import gc
import unittest
from pdfeditor import gpu_raster as g
try:
    from pdfeditor._path_packer import compile_scene
except ImportError:
    compile_scene=None

PATH=(('move',0.,0.),('line',10.,0.),('line',10.,10.),('close',))


@unittest.skipIf(compile_scene is None,'Rust scene compiler not built')
class RustSceneCompilerTests(unittest.TestCase):
    def scene(self,*items):
        return g.VectorPage(True,items=items)

    def test_every_operation_and_shared_resources_are_owned(self):
        style=(0,1,2,0,10.,0.,(2.,1.))
        source=self.scene(
            g.GroupPush(.75),g.ClipPush(PATH),
            g.VectorPath(PATH,fill_argb=0xff112233),
            g.VectorPath(PATH,stroke_argb=0xff8899aa,stroke_style=style),
            g.VectorLinearGradient(PATH,(0.,0.),(10.,0.),((0.,0xff000000),(1.,0xffffffff))),
            g.VectorRadialGradient(PATH,(5.,5.),(0.,0.),(5.,5.),((0.,0xff000000),(1.,0xffffffff))),
            g.ClipStrokePush(PATH,1.,style),g.ClipPop(),
            g.VectorImage(b'abcd',1,1,4,(1.,0.,0.,1.,0.,0.)),
            g.MaskBegin((0.,0.,10.,10.),False,0),g.VectorPath(PATH,fill_argb=0xffffffff),
            g.MaskEnd((0.,.5,1.)),g.ClipPop(),g.ClipPop(),g.GroupPop())
        compiled=compile_scene(source)
        self.assertEqual(compiled.command_count,len(source.drawables))
        self.assertEqual(compiled.resource_count,2)
        self.assertEqual(compiled.image_bytes,4)
        wire=compiled.to_bytes()
        self.assertTrue(wire.startswith(b'LFSC\x03\0\0\0'))
        del source;gc.collect()
        self.assertEqual(compiled.to_bytes(),wire)

    def test_mask_capture_and_apply_have_separate_endpoints(self):
        compiled=compile_scene(self.scene(g.MaskBegin((0.,0.,10.,10.),True,0),
                              g.VectorPath(PATH,fill_argb=0xffffffff),g.MaskEnd(),
                              g.VectorPath(PATH,fill_argb=0xff112233),g.ClipPop()))
        plan=compiled.scope_plan()
        self.assertEqual(plan[0],(4,2,0))
        self.assertEqual(plan[1][2],1)
        self.assertEqual(plan[3][2],1)
        self.assertEqual(compiled.viewport_plan((100.,100.,110.,110.),1.),list(range(5)))

    def test_conservative_viewport_plan_keeps_barriers_and_strokes(self):
        compiled=compile_scene(self.scene(g.GroupPush(1.),
            g.VectorPath(PATH,fill_argb=0xffffffff),g.GroupPop(),
            g.VectorPath(PATH,stroke_argb=0xffffffff,stroke_width=1000.)))
        self.assertEqual(compiled.viewport_plan((100.,100.,110.,110.),1.),[0,2,3])
        complex_scene=compile_scene(self.scene(g.GroupPush(1.,blend_mode=1),
                                   g.VectorPath(PATH,fill_argb=0xffffffff),g.GroupPop()))
        self.assertEqual(complex_scene.viewport_plan((100.,100.,110.,110.),1.),[0,1,2])

    def test_transformed_glyph_runs_are_compiled_into_geometry_groups(self):
        source=self.scene(g.VectorPath(PATH,fill_argb=0xff112233,groupable=True,
                          transform=(1.,0.,0.,1.,0.,0.)),
                          g.VectorPath(PATH,fill_argb=0xff112233,groupable=True,
                          transform=(1.,0.,0.,1.,20.,0.)))
        compiled=compile_scene(source)
        self.assertEqual(compiled.source_command_count,2)
        self.assertEqual(compiled.command_count,1)
        self.assertEqual(compiled.resource_count,1)

    def test_malformed_scopes_geometry_and_images_fail(self):
        for items in ((g.ClipPop(),),(g.GroupPush(1.),),
                      (g.MaskBegin((0.,0.,1.,1.),False,0),g.GroupPop()),
                      (g.GroupPush(float('nan')),),
                      (g.VectorImage(b'abc',1,1,4,(1.,0.,0.,1.,0.,0.)),),
                      (g.VectorPath((('move',1.),)),)):
            with self.subTest(items=items),self.assertRaises((ValueError,IndexError)):
                compile_scene(self.scene(*items))

    def test_unknown_operations_unsupported_input_and_depth_are_rejected(self):
        with self.assertRaises(ValueError):compile_scene(g.VectorPage(False,reason='unsupported'))
        with self.assertRaises(ValueError):compile_scene(self.scene(object()))
        with self.assertRaises(ValueError):compile_scene(self.scene(*([g.GroupPush(1.)]*4097)))
        compiled=compile_scene(self.scene(g.VectorPath(PATH)))
        for rect,padding in (((0.,0.,1.,1.),-1.),((2.,2.,1.,1.),0.)):
            with self.assertRaises(ValueError):compiled.viewport_plan(rect,padding)

    def test_path_segment_budget_is_checked_before_owned_copy(self):
        from pdfeditor.scene_transfer import PackedCommands
        commands=PackedCommands(b'\x04'*(1048576+1),1048576+1)
        with self.assertRaisesRegex(ValueError,'segment limit'):
            compile_scene(self.scene(g.VectorPath(commands)))
