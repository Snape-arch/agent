# Professional 3D baseline

ClawVision 0.22 closes the engineering gap between the interactive 3D demo and
a reproducible professional-geometry pipeline. It does not embed Blender or a
CAD desktop application; exact operations remain isolated workers so the API
process stays deterministic and restartable.

## Exact CAD and mesh kernels

`workers/opencascade_worker.py` reads and writes STEP, IGES and native B-Rep.
Every exact round trip records validity, volume, surface area, center of mass,
bounds and solid/shell/face/edge/vertex counts. The tolerance gate checks
linear bounds/center deviation, relative area/volume error and topology
preservation. Fillet, chamfer, exact union/subtract/intersect and ShapeFix repair
run on the B-Rep before optional tessellation.

The committed Windows acceptance uses CadQuery 2.8/OpenCascade and validates a
22-face part through all three exact formats. It also runs fillet, chamfer,
exact subtraction and repair. Manifold3D separately subtracts a 64-segment
cutter from a subdivided sphere and requires a watertight result.

```powershell
$env:GEOMETRY_OPENCASCADE_COMMAND='conda run --no-capture-output -n clawvision-geometry python workers/opencascade_worker.py'
$env:GEOMETRY_MANIFOLD_COMMAND='conda run --no-capture-output -n clawvision-geometry python workers/manifold_worker.py'
conda run --no-capture-output -n clawvision-geometry python scripts/professional_3d_acceptance.py
```

## Local and neural Text-to-3D

Three local tiers are explicit:

- `local-implicit`: fast CPU preview.
- `local-semantic`: higher-resolution offline semantic surface followed by
  cleanup, normals, UV, base-color/normal/ORM PBR textures, a generated skin and
  an idle animation. This is the default Studio path and needs no API key.
- `local-neural`: an isolated GPU JSONL worker selected with
  `TEXT3D_LOCAL_NEURAL_COMMAND`. It accepts text and reference images and can
  host locally licensed TRELLIS/Hunyuan/TripoSR weights without changing the API.

Thus external Meshy/Tripo APIs are optional production providers rather than a
hard dependency. Neural weights are intentionally not committed to Git because
of their size and upstream licenses.

## Rendering, animation and telemetry

The CAD renderer preserves glTF PBR materials, applies ACES tone mapping and
anisotropic filtering, plays every glTF animation clip and can display the
skeleton of skinned meshes. Generated semantic GLBs include three embedded PBR
textures, two joints and one animation; imported GLB/GLTF assets retain their
own complex materials, skins and animations.

Browser telemetry combines CPU frame time, `EXT_disjoint_timer_query_webgl2`
GPU frame time, unmasked adapter/vendor, WebGL version, render resolution,
geometry/texture/draw-call/triangle counts, heap, transferred bytes and context
losses. `POST /api/telemetry/3d` correlates that sample with native `nvidia-smi`
utilization, VRAM, temperature, power and driver data when NVIDIA telemetry is
available. Migration 17 persists the samples for regression analysis.

## Large asset streaming

Every new model asset stores a raw binary object in addition to its compatibility
manifest. `GET /api/model-assets/:id/stream-manifest` reports size and resources;
`GET /api/model-assets/:id/content` supports HTTP Range on both local storage and
S3/MinIO. The CAD renderer reads the authenticated response as a browser stream,
shows transfer progress and records transferred bytes instead of embedding a
large base64 payload in the application state. Existing pre-0.22 assets retain a
decoded compatibility fallback.

The reproducible evidence is
[`docs/benchmarks/professional-3d-windows.json`](benchmarks/professional-3d-windows.json).
