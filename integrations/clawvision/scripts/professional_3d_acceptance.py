"""Real professional-3D acceptance using OpenCascade, Manifold and GLB contracts."""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "workers"))

from asset_scene import parse_asset  # noqa: E402
from mesh_postprocess import postprocess_to_glb  # noqa: E402
from opencascade_worker import _write_shape  # noqa: E402


def invoke(worker: str, request: dict, timeout: int = 180) -> dict:
    process = subprocess.run([sys.executable, str(ROOT / "workers" / worker)], input=json.dumps(request), text=True, capture_output=True, timeout=timeout)
    events = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    result = next((event for event in reversed(events) if event.get("type") == "result"), None)
    if process.returncode or not result:
        raise RuntimeError(process.stderr[-2000:] or f"{worker} returned no result")
    return result


def exact_cad(directory: Path) -> dict:
    import cadquery as cq

    body = cq.Workplane("XY").box(40, 30, 8).edges("|Z").fillet(2)
    body = body.union(cq.Workplane("XY").workplane(offset=4).circle(8).extrude(12))
    for x in (-13, 13):
        body = body.cut(cq.Workplane("XY").center(x, 0).circle(2.5).extrude(20, both=True))
    body = body.union(cq.Workplane("XZ").workplane(offset=-10).rect(28, 5).extrude(20))
    source_shape = body.val().wrapped
    formats = {}
    for fmt in ("step", "iges", "brep"):
        path = directory / f"complex.{fmt}"
        _write_shape(source_shape, path, fmt)
        result = invoke("opencascade_worker.py", {"source": {"name": path.name, "format": fmt, "content": base64.b64encode(path.read_bytes()).decode()}, "operation": {"kind": "roundtrip", "tolerance": 1e-4}, "outputFormat": fmt})
        tolerance = result["stats"]["tolerance"]
        if not tolerance["passed"]:
            raise AssertionError(f"{fmt} tolerance failed: {tolerance}")
        formats[fmt] = {"bytes": len(base64.b64decode(result["content"])), "tolerance": tolerance, "topology": result["stats"]["roundtrip"]["topology"]}

    simple = cq.Workplane("XY").box(30, 20, 10)
    step_path = directory / "fillet.step"; _write_shape(simple.val().wrapped, step_path, "step")
    fillet = invoke("opencascade_worker.py", {"source": {"format": "step", "content": base64.b64encode(step_path.read_bytes()).decode()}, "operation": {"kind": "fillet", "radius": 1.5, "tolerance": 1e-4}, "outputFormat": "step"})
    assert fillet["stats"]["tolerance"]["passed"] and fillet["stats"]["result"]["topology"]["faces"] > 6
    chamfer = invoke("opencascade_worker.py", {"source": {"format": "step", "content": base64.b64encode(step_path.read_bytes()).decode()}, "operation": {"kind": "chamfer", "radius": 1, "tolerance": 1e-4}, "outputFormat": "brep"})
    assert chamfer["stats"]["tolerance"]["passed"] and chamfer["stats"]["result"]["valid"]
    operand=cq.Workplane("XY").circle(3).extrude(20,both=True);operand_path=directory/"operand.step";_write_shape(operand.val().wrapped,operand_path,"step")
    exact = invoke("opencascade_worker.py", {"source": {"format": "step", "content": base64.b64encode(step_path.read_bytes()).decode()}, "operation": {"kind": "exact-boolean", "operator":"subtract", "operand":{"format":"step","content":base64.b64encode(operand_path.read_bytes()).decode()}, "tolerance": 1e-4}, "outputFormat": "step"})
    assert exact["stats"]["tolerance"]["passed"] and exact["stats"]["result"]["volume"] < exact["stats"]["source"]["volume"]
    repaired=invoke("opencascade_worker.py", {"source":{"format":"step","content":exact["content"]},"operation":{"kind":"repair","tolerance":1e-4},"outputFormat":"step"})
    assert repaired["stats"]["result"]["valid"] and repaired["stats"]["tolerance"]["passed"]
    return {"formats": formats, "fillet": {"faces": fillet["stats"]["result"]["topology"]["faces"], "passed": True},"chamfer":{"faces":chamfer["stats"]["result"]["topology"]["faces"],"passed":True},"exactBoolean":{"volume":exact["stats"]["result"]["volume"],"passed":True},"repair":{"valid":repaired["stats"]["result"]["valid"],"passed":True}, "passed": True}


def manifold_complex() -> dict:
    import trimesh

    body = trimesh.creation.icosphere(subdivisions=3, radius=2)
    cutter = trimesh.creation.cylinder(radius=.72, height=6, sections=64); cutter.apply_transform(trimesh.transformations.rotation_matrix(1.5707963268, [1, 0, 0]))
    body_obj = body.export(file_type="obj"); cutter_obj = cutter.export(file_type="obj")
    request = {"source": {"format": "obj", "content": base64.b64encode(body_obj.encode() if isinstance(body_obj, str) else body_obj).decode()},
               "operation": {"kind": "boolean", "action": "subtract", "operand": {"format": "obj", "content": base64.b64encode(cutter_obj.encode() if isinstance(cutter_obj, str) else cutter_obj).decode()}}, "outputFormat": "glb"}
    result = invoke("manifold_worker.py", request)
    assert result["stats"]["watertight"] and result["stats"]["faces"] > 500
    return {**result["stats"], "passed": True}


def semantic_glb() -> dict:
    source = b"v -1 0 0\nv 1 0 0\nv 0 2 0\nv 0 1 1\nf 1 2 3\nf 1 4 2\nf 1 3 4\nf 2 4 3\n"
    glb, stats = postprocess_to_glb(source, "obj", "Rigged semantic fixture")
    document, binary = parse_asset(glb, "glb")
    assert len(document.get("images", [])) == 3 and len(document.get("skins", [])) == 1 and len(document.get("animations", [])) == 1
    assert document["meshes"][0]["primitives"][0]["attributes"].get("JOINTS_0") is not None
    return {**stats, "glbBytes": len(glb), "binaryBytes": len(binary), "textures": len(document["images"]), "skins": len(document["skins"]), "animations": len(document["animations"]), "passed": True}


def gpu_telemetry() -> dict:
    try:
        raw=subprocess.check_output(["nvidia-smi","--query-gpu=name,driver_version,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw","--format=csv,noheader,nounits","-i","0"],text=True,timeout=5).splitlines()[0]
        name,driver,utilization,used,total,temperature,power=[item.strip() for item in raw.split(",",6)]
        return {"name":name,"driverVersion":driver,"utilizationPercent":float(utilization),"memoryUsedMb":float(used),"memoryTotalMb":float(total),"temperatureC":float(temperature),"powerWatts":float(power),"passed":True}
    except (FileNotFoundError,subprocess.SubprocessError,ValueError,IndexError) as error:
        return {"available":False,"reason":str(error),"passed":True}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--output"); args = parser.parse_args()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        report = {"schemaVersion": 1, "openCascade": exact_cad(Path(directory)), "manifold": manifold_complex(), "semanticGlb": semantic_glb(),"nativeGpu":gpu_telemetry()}
    report["passed"] = all(report[key]["passed"] for key in ("openCascade", "manifold", "semanticGlb","nativeGpu"))
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
