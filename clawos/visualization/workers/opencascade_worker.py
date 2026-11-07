"""OpenCascade worker for exact STEP/IGES/B-Rep operations and tolerance reports."""
from __future__ import annotations

import base64
import json
import math
import tempfile
from pathlib import Path


def emit(kind, **values):
    print(json.dumps({"type": kind, **values}), flush=True)


def _read_shape(path: Path, fmt: str):
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.IFSelect import IFSelect_RetDone

    if fmt in {"step", "stp"}:
        from OCP.STEPControl import STEPControl_Reader
        reader = STEPControl_Reader()
        if reader.ReadFile(str(path)) != IFSelect_RetDone:
            raise ValueError("OpenCascade could not read STEP input")
        reader.TransferRoots()
        return reader.OneShape()
    if fmt in {"iges", "igs"}:
        from OCP.IGESControl import IGESControl_Reader
        reader = IGESControl_Reader()
        if reader.ReadFile(str(path)) != IFSelect_RetDone:
            raise ValueError("OpenCascade could not read IGES input")
        reader.TransferRoots()
        return reader.OneShape()
    if fmt in {"brep", "brp"}:
        from OCP.TopoDS import TopoDS_Shape
        shape = TopoDS_Shape()
        if not BRepTools.Read_s(shape, str(path), BRep_Builder()):
            raise ValueError("OpenCascade could not read B-Rep input")
        return shape
    raise ValueError("OpenCascade worker expects STEP, IGES or B-Rep input")


def _write_shape(shape, path: Path, fmt: str) -> None:
    from OCP.IFSelect import IFSelect_RetDone

    if fmt in {"step", "stp"}:
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
        writer = STEPControl_Writer()
        writer.Transfer(shape, STEPControl_AsIs)
        if writer.Write(str(path)) != IFSelect_RetDone:
            raise RuntimeError("OpenCascade STEP export failed")
        return
    if fmt in {"iges", "igs"}:
        from OCP.IGESControl import IGESControl_Writer
        writer = IGESControl_Writer()
        writer.AddShape(shape)
        if not writer.Write(str(path)):
            raise RuntimeError("OpenCascade IGES export failed")
        return
    if fmt in {"brep", "brp"}:
        from OCP.BRepTools import BRepTools
        if not BRepTools.Write_s(shape, str(path)):
            raise RuntimeError("OpenCascade B-Rep export failed")
        return
    raise ValueError(f"unsupported exact output format: {fmt}")


def _count(shape, kind) -> int:
    from OCP.TopExp import TopExp_Explorer
    total = 0
    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        total += 1
        explorer.Next()
    return total


def _shape_stats(shape) -> dict:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX

    volume_props = GProp_GProps()
    surface_props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume_props)
    BRepGProp.SurfaceProperties_s(shape, surface_props)
    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds)
    minimum_x, minimum_y, minimum_z, maximum_x, maximum_y, maximum_z = bounds.Get()
    center = volume_props.CentreOfMass()
    return {
        "valid": bool(BRepCheck_Analyzer(shape).IsValid()),
        "volume": float(volume_props.Mass()),
        "surfaceArea": float(surface_props.Mass()),
        "centerOfMass": [float(center.X()), float(center.Y()), float(center.Z())],
        "bounds": [minimum_x, minimum_y, minimum_z, maximum_x, maximum_y, maximum_z],
        "topology": {
            "solids": _count(shape, TopAbs_SOLID), "shells": _count(shape, TopAbs_SHELL),
            "faces": _count(shape, TopAbs_FACE), "edges": _count(shape, TopAbs_EDGE),
            "vertices": _count(shape, TopAbs_VERTEX),
        },
    }


def _relative(first: float, second: float) -> float:
    return abs(first - second) / max(abs(first), 1e-12)


def _tolerance_report(before: dict, after: dict, requested: float) -> dict:
    bounds_delta = max(abs(float(a) - float(b)) for a, b in zip(before["bounds"], after["bounds"]))
    center_delta = math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(before["centerOfMass"], after["centerOfMass"])))
    volume_error = _relative(before["volume"], after["volume"])
    area_error = _relative(before["surfaceArea"], after["surfaceArea"])
    topology_preserved = before["topology"] == after["topology"]
    passed = bool(before["valid"] and after["valid"] and bounds_delta <= requested and center_delta <= requested and volume_error <= 1e-7 and area_error <= 1e-7 and topology_preserved)
    return {
        "requestedLinearTolerance": requested,
        "boundingBoxMaxDeviation": bounds_delta,
        "centerOfMassDeviation": center_delta,
        "volumeRelativeError": volume_error,
        "surfaceAreaRelativeError": area_error,
        "topologyPreserved": topology_preserved,
        "passed": passed,
    }


def _mesh_payload(shape, directory: Path, output_format: str, tolerance: float):
    import cadquery as cq
    import trimesh

    stl = directory / "tessellated.stl"
    cq.exporters.export(cq.Shape.cast(shape), str(stl), tolerance=tolerance, angularTolerance=.1)
    mesh = trimesh.load_mesh(stl)
    output = mesh.export(file_type=output_format)
    if isinstance(output, str):
        output = output.encode()
    return output, {"vertices": len(mesh.vertices), "faces": len(mesh.faces), "watertight": bool(mesh.is_watertight)}


def main():
    import cadquery as cq

    request = json.load(__import__("sys").stdin)
    source = request["source"]
    source_format = str(source["format"]).lower()
    operation = request.get("operation") or {}
    requested_tolerance = max(1e-7, float(operation.get("tolerance") or request.get("tolerance") or 1e-4))
    with tempfile.TemporaryDirectory() as raw_directory:
        directory = Path(raw_directory)
        source_path = directory / f"input.{source_format}"
        source_path.write_bytes(base64.b64decode(source["content"]))
        emit("progress", progress=10, stage="brep-import")
        original = _read_shape(source_path, source_format)
        before = _shape_stats(original)
        if not before["valid"]:
            raise ValueError("input B-Rep is invalid")

        shape = cq.Shape.cast(original)
        kind = str(operation.get("type") or operation.get("kind") or "roundtrip")
        radius = float(operation.get("radius") or operation.get("distance") or .5)
        if kind == "fillet":
            shape = shape.fillet(radius, shape.Edges())
        elif kind == "chamfer":
            shape = shape.chamfer(radius, None, shape.Edges())
        elif kind == "exact-boolean":
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
            operand = operation.get("operand")
            if not isinstance(operand, dict) or not operand.get("content") or not operand.get("format"):
                raise ValueError("exact-boolean requires an operand with format and content")
            operand_format = str(operand["format"]).lower(); operand_path = directory / f"operand.{operand_format}"
            operand_path.write_bytes(base64.b64decode(operand["content"])); other = _read_shape(operand_path, operand_format)
            action = str(operation.get("operator") or operation.get("action") or "union")
            algorithm = {"union":BRepAlgoAPI_Fuse,"subtract":BRepAlgoAPI_Cut,"intersect":BRepAlgoAPI_Common}.get(action)
            if not algorithm: raise ValueError("exact-boolean operator must be union, subtract or intersect")
            calculated = algorithm(shape.wrapped, other); calculated.Build()
            if not calculated.IsDone(): raise RuntimeError("OpenCascade exact boolean failed")
            shape = cq.Shape.cast(calculated.Shape())
        elif kind == "repair":
            from OCP.ShapeFix import ShapeFix_Shape
            fixer=ShapeFix_Shape(shape.wrapped);fixer.SetPrecision(requested_tolerance);fixer.Perform();shape=cq.Shape.cast(fixer.Shape())
        elif kind not in {"roundtrip", "convert", "tessellate"}:
            raise ValueError(f"unsupported OpenCascade operation: {kind}")
        result_shape = shape.wrapped
        emit("checkpoint", progress=45, stage="brep-operation", checkpoint={"operation": kind, "valid": bool(_shape_stats(result_shape)["valid"])})

        output_format = str(request.get("outputFormat") or operation.get("outputFormat") or "glb").lower()
        roundtrip_format = output_format if output_format in {"step", "stp", "iges", "igs", "brep", "brp"} else source_format
        roundtrip_path = directory / f"roundtrip.{roundtrip_format}"
        _write_shape(result_shape, roundtrip_path, roundtrip_format)
        restored_shape = _read_shape(roundtrip_path, roundtrip_format)
        current = _shape_stats(result_shape)
        restored = _shape_stats(restored_shape)
        tolerance = _tolerance_report(current, restored, requested_tolerance)
        emit("progress", progress=75, stage="brep-roundtrip-verified")

        if output_format in {"step", "stp", "iges", "igs", "brep", "brp"}:
            payload = roundtrip_path.read_bytes()
            mesh_stats = {}
        else:
            payload, mesh_stats = _mesh_payload(result_shape, directory, output_format, max(requested_tolerance, 1e-3))
        stats = {
            **mesh_stats, "kernel": "OpenCascade", "exactBRep": True, "operation": kind,
            "source": before, "result": current, "roundtrip": restored, "tolerance": tolerance,
        }
        emit("result", content=base64.b64encode(payload).decode(), format=output_format, stats=stats)


if __name__ == "__main__":
    main()
