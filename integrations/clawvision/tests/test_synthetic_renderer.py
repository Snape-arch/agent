"""Pixel-level checks for bounded, reproducible geometry-derived annotations."""
import copy
import struct
import sys
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import synthetic_renderer as renderer
from asset_scene import canonicalize_mesh_asset, pack_glb
from errors import ValidationError
from scenario_service import normalize_config, variants

CUBE = b"""v -1 -1 -1
v 1 -1 -1
v 1 1 -1
v -1 1 -1
v -1 -1 1
v 1 -1 1
v 1 1 1
v -1 1 1
f 1 4 3 2
f 5 6 7 8
f 1 2 6 5
f 4 8 7 3
f 1 5 8 4
f 2 3 7 6
"""

def fixed_config(count=3):
    return normalize_config({"count": count, "ranges": {"cameraAzimuth": [0, 0], "cameraElevation": [0, 0],
        "cameraDistance": [3, 3], "lightAzimuth": [0, 0], "lightElevation": [30, 30], "lightIntensity": [2, 2],
        "roughness": [.4, .4], "metalness": [0, 0], "occluderSize": [0, 0]}})

def decode_png(content):
    """Read our filter-0 lossless PNG independently of the rasterizer."""
    np = renderer.numpy()
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    cursor, compressed = 8, b""
    while cursor < len(content):
        length = struct.unpack_from(">I", content, cursor)[0]
        kind, data = content[cursor+4:cursor+8], content[cursor+8:cursor+8+length]
        assert zlib.crc32(kind+data) & 0xffffffff == struct.unpack_from(">I", content, cursor+8+length)[0]
        if kind == b"IHDR": width, height, _, color, _, _, _ = struct.unpack(">IIBBBBB", data)
        if kind == b"IDAT": compressed += data
        cursor += length+12
    channels = 3 if color == 2 else 1
    rows = np.frombuffer(zlib.decompress(compressed), dtype=np.uint8).reshape(height, width*channels+1)
    assert not rows[:, 0].any()
    return rows[:, 1:].reshape((height, width, 3) if channels == 3 else (height, width))

class SyntheticRendererTests(unittest.TestCase):
    def setUp(self):
        self.mesh = renderer.load_mesh(CUBE, "obj")
        self.config = fixed_config()
        self.parameters = variants(self.config)[0]["parameters"]

    def test_pixels_bbox_png_and_column_major_rle_agree(self):
        output, annotation = renderer.render(self.mesh, self.parameters, self.config)
        mask = decode_png(output["mask"]) > 0
        self.assertEqual(mask.shape, (512, 512))
        self.assertEqual(annotation["bbox"], [112, 112, 288, 288])
        self.assertEqual(annotation["visiblePixels"], 288**2)
        self.assertEqual(annotation["amodalPixels"], annotation["visiblePixels"])
        self.assertEqual(annotation["visibleFraction"], 1)
        self.assertFalse(annotation["clipped"])
        counts = annotation["segmentation"]["counts"]
        np = renderer.numpy()
        decoded = np.repeat(np.arange(len(counts)) % 2, counts).reshape(512, 512, order="F")
        np.testing.assert_array_equal(decoded, mask)
        self.assertEqual(output, renderer.render(self.mesh, self.parameters, self.config)[0])
        self.assertEqual(output["mask"], output["amodalMask"])
        self.assertEqual(decode_png(output["image"]).shape, (512, 512, 3))

    def test_occlusion_is_depth_based_and_retains_amodal_pixels(self):
        full, baseline = renderer.render(self.mesh, self.parameters, self.config)
        partial, partly = renderer.render(self.mesh, {**self.parameters, "occluderSize": .6}, self.config)
        empty, hidden = renderer.render(self.mesh, {**self.parameters, "occluderSize": 1.5}, self.config)
        self.assertLess(partly["visibleFraction"], 1)
        self.assertGreater(partly["visibleFraction"], 0)
        self.assertEqual(partial["amodalMask"], full["amodalMask"])
        self.assertEqual(hidden["amodalPixels"], baseline["visiblePixels"])
        self.assertEqual(hidden["visiblePixels"], 0)
        self.assertIsNone(hidden["bbox"])
        self.assertFalse(decode_png(empty["mask"]).any())
        # Triangle submission order cannot override the z-buffer.
        vertices, faces, normals = self.mesh
        self.assertEqual(full["mask"], renderer.render((vertices, faces[::-1], normals), self.parameters, self.config)[0]["mask"])

    def test_camera_light_material_and_border_have_actual_pixel_effects(self):
        baseline, _ = renderer.render(self.mesh, self.parameters, self.config)
        camera, _ = renderer.render(self.mesh, {**self.parameters, "cameraAzimuth": 40}, self.config)
        dark, _ = renderer.render(self.mesh, {**self.parameters, "lightIntensity": 0}, self.config)
        material, _ = renderer.render(self.mesh, {**self.parameters, "metalness": .9, "roughness": .9}, self.config)
        _, close = renderer.render(self.mesh, {**self.parameters, "cameraDistance": 1.5}, self.config)
        self.assertNotEqual(baseline["mask"], camera["mask"])
        self.assertEqual(baseline["mask"], dark["mask"])
        self.assertNotEqual(baseline["image"], dark["image"])
        self.assertNotEqual(baseline["image"], material["image"])
        self.assertTrue(close["clipped"])
        with self.assertRaises(ValidationError): renderer.render(self.mesh, self.parameters, self.config, deadline=time.monotonic()-1)
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            renderer.render(self.mesh, self.parameters, self.config, check=lambda: (_ for _ in ()).throw(RuntimeError("cancelled")))

    def test_static_glb_hierarchy_and_stl_match_obj_geometry(self):
        np = renderer.numpy()
        document, binary = canonicalize_mesh_asset(CUBE, "obj")
        glb = pack_glb(document, binary)
        np.testing.assert_allclose(renderer.load_mesh(glb, "glb")[0], self.mesh[0])
        document["nodes"].append({"children": [0], "translation": [4, 7, -3], "scale": [2, 2, 2]})
        document["scenes"][0]["nodes"] = [1]
        np.testing.assert_allclose(renderer.load_mesh(pack_glb(document, binary), "glb")[0], self.mesh[0], atol=1e-12)
        vertices, faces, _ = self.mesh
        stl = b"\0"*80 + struct.pack("<I", len(faces))
        for face in faces:
            stl += struct.pack("<12fH", 0, 0, 0, *vertices[face].flatten(), 0)
        self.assertEqual(len(renderer.load_mesh(stl, "stl")[1]), len(faces))
        matrix = renderer._matrix({"matrix": [1,0,0,0,0,1,0,0,0,0,1,0,3,4,5,1]})
        np.testing.assert_array_equal(matrix[:3, 3], [3,4,5])
        np.testing.assert_allclose(renderer._matrix({"rotation": [0,0,1,0]})[:3,:3], np.diag([-1,-1,1]))

    def test_invalid_or_unsupported_glb_never_gets_fallback_geometry(self):
        original, binary = canonicalize_mesh_asset(CUBE, "obj")
        invalid = []
        for key, value in (("animations", [{}]), ("skins", [{}]), ("extensionsRequired", ["KHR_draco_mesh_compression"])):
            doc = copy.deepcopy(original); doc[key] = value; invalid.append(doc)
        for change in ({"children": [0]}, {"mesh": -1}, {"scale": [0,1,1]}, {"rotation": [0,0,0,0]}, {"skin": 0}):
            doc = copy.deepcopy(original); doc["nodes"][0].update(change); invalid.append(doc)
        for change in ({"sparse": {}}, {"count": 60001}, {"byteOffset": 10**8}, {"normalized": True}):
            doc = copy.deepcopy(original); doc["accessors"][0].update(change); invalid.append(doc)
        for change in ({"mode": 1}, {"targets": [{}]}, {"extensions": {"bad": {}}}):
            doc = copy.deepcopy(original); doc["meshes"][0]["primitives"][0].update(change); invalid.append(doc)
        doc = copy.deepcopy(original); doc["scenes"][0]["nodes"] = [-1]; invalid.append(doc)
        doc = copy.deepcopy(original); doc["scenes"][0]["nodes"] = []; invalid.append(doc)
        doc = copy.deepcopy(original); doc["buffers"].append({"byteLength": 0, "uri": "outside.bin"}); invalid.append(doc)
        for index, doc in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValidationError):
                renderer.load_mesh(pack_glb(doc, binary), "glb")
        with self.assertRaises(ValidationError): renderer.load_mesh(b"v 0 0 0\nf 1 1 1", "obj")
        with patch.object(renderer, "MAX_TRIANGLES", 1), self.assertRaises(ValidationError): renderer.load_mesh(CUBE, "obj")
        with self.assertRaises(ValidationError): renderer._accessor(original, binary, -1)
        self.assertEqual(renderer.rle(renderer.numpy().ones((2, 3), dtype=bool))["counts"], [0, 6])
        self.assertEqual(len(renderer.source_digest()), 64)
