"""Bounded read-only HDF5 inspection for GMS .gpr project containers.

Inventory never reads dataset payloads or follows soft/external links. Explicit
numeric reads support hard-linked fixed-width arrays with unfiltered storage or
a single deflate filter decoded through bounded raw chunks;
they do not decode GMS tree semantics, geometry packets, or GUI behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from .gpr_storage import StorageReadError, read_fixed_array


MAX_GPR_BYTES = 512 * 1024 * 1024
MAX_ARRAY_BYTES = 32 * 1024 * 1024
BUILTIN_READ_FILTERS = {1, 2, 3}  # Preliminary allowlist; storage reader narrows payload support to []/[1].


class GprInspectionError(ValueError):
    """The requested project operation exceeds the supported HDF5 boundary."""


def _h5py():
    try:
        import h5py
    except ImportError as error:
        raise GprInspectionError("Install h5py to inspect GPR/HDF5 files") from error
    return h5py


def _input(path: str | Path) -> Path:
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > MAX_GPR_BYTES:
        raise GprInspectionError(f"Expected a project file no larger than {MAX_GPR_BYTES} bytes")
    return path


def _filters(dataset) -> list[int]:
    properties = dataset.id.get_create_plist()
    return [int(properties.get_filter(index)[0]) for index in range(properties.get_nfilters())]


def _attributes(obj) -> list[str]:
    if len(obj.attrs) > 4096:
        raise GprInspectionError("HDF5 attribute inventory limit exceeded")
    return sorted(obj.attrs.keys())


def _descriptor(dataset) -> dict:
    return {"shape": list(dataset.shape) if dataset.shape is not None else None,
            "dtype": str(dataset.dtype), "attributes": _attributes(dataset),
            "chunks": list(dataset.chunks) if dataset.chunks is not None else None,
            "filter_ids": _filters(dataset), "virtual": bool(dataset.is_virtual),
            "external_storage": bool(dataset.external)}


def _hard_path(file, path: str):
    h5py = _h5py()
    parts = path.strip("/").split("/")
    if not path.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise GprInspectionError("Dataset path must be an absolute HDF5 path without dot segments")
    obj = file
    for part in parts:
        if not isinstance(obj, h5py.Group) or not isinstance(obj.get(part, getlink=True), h5py.HardLink):
            raise GprInspectionError("Explicit reads require a complete hard-link path")
        obj = obj[part]
    return obj


def inventory_gpr(path: str | Path, *, max_objects: int = 20000) -> dict:
    """Read dataset metadata only; never load data or follow indirect links."""
    if type(max_objects) is not int or not 1 <= max_objects <= 100000:
        raise GprInspectionError("max_objects must be an integer in [1, 100000]")
    path = _input(path)
    h5py = _h5py()
    objects, seen = [], {}
    with h5py.File(path, "r") as project:
        pending = [("/", project)]
        while pending:
            parent_path, group = pending.pop()
            if len(group) > max_objects - len(objects):
                raise GprInspectionError("HDF5 object inventory limit exceeded")
            for name in sorted(group.keys()):
                if len(objects) >= max_objects:
                    raise GprInspectionError("HDF5 object inventory limit exceeded")
                child_path = parent_path.rstrip("/") + "/" + name
                link = group.get(name, getlink=True)
                if isinstance(link, h5py.SoftLink):
                    objects.append({"path": child_path, "kind": "soft_link", "target": link.path,
                                    "followed": False})
                    continue
                if isinstance(link, h5py.ExternalLink):
                    objects.append({"path": child_path, "kind": "external_link", "file": link.filename,
                                    "target": link.path, "followed": False})
                    continue
                if not isinstance(link, h5py.HardLink):
                    objects.append({"path": child_path, "kind": "unsupported_link", "followed": False})
                    continue
                obj = group[name]
                address = int(h5py.h5o.get_info(obj.id).addr)
                if address in seen:
                    objects.append({"path": child_path, "kind": "hard_link_alias", "target": seen[address]})
                    continue
                seen[address] = child_path
                if isinstance(obj, h5py.Group):
                    objects.append({"path": child_path, "kind": "group", "attributes": _attributes(obj)})
                    pending.append((child_path, obj))
                elif isinstance(obj, h5py.Dataset):
                    objects.append({"path": child_path, "kind": "dataset", **_descriptor(obj)})
                else:
                    objects.append({"path": child_path, "kind": "unsupported_object"})
        root_attributes = _attributes(project)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(1024 * 1024):
            digest.update(data)
    return {"schema": "basinlens-gpr-hdf5-inventory-v1", "file": path.name,
            "bytes": path.stat().st_size, "sha256": digest.hexdigest(),
            "dataset_payloads_read": False, "indirect_links_followed": False,
            "root_attributes": root_attributes, "objects": objects,
            "object_count": len(objects),
            "scope": "HDF5 structure only; no GMS project round trip, geometry decoding, or runtime equivalence claimed."}


def read_gpr_numeric_array(path: str | Path, dataset_path: str, *, max_bytes: int = MAX_ARRAY_BYTES):
    """Read one explicitly selected fixed-width numeric array and its metadata.

    Returns (NumPy array, descriptor). Units, ordering and physical meaning must
    be established by the caller; this function makes no unit conversions.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_ARRAY_BYTES:
        raise GprInspectionError(f"max_bytes must be an integer in [1, {MAX_ARRAY_BYTES}]")
    path = _input(path)
    h5py = _h5py()
    with h5py.File(path, "r") as project:
        dataset = _hard_path(project, dataset_path)
        if not isinstance(dataset, h5py.Dataset) or dataset.shape is None:
            raise GprInspectionError("Expected a non-null HDF5 dataset")
        description = _descriptor(dataset)
        if description["virtual"] or description["external_storage"]:
            raise GprInspectionError("Virtual or external-storage datasets are not supported")
        if any(filter_id not in BUILTIN_READ_FILTERS for filter_id in description["filter_ids"]):
            raise GprInspectionError("Dataset uses an unsupported/plugin HDF5 filter")
        if dataset.dtype.kind not in "biuf" or dataset.dtype.hasobject:
            raise GprInspectionError("Only fixed-width boolean, integer and real arrays are supported")
        byte_count = math.prod(dataset.shape) * dataset.dtype.itemsize
        if byte_count > max_bytes:
            raise GprInspectionError("Requested array exceeds the explicit read budget")
        if dataset.chunks is not None and math.prod(dataset.chunks) * dataset.dtype.itemsize > max_bytes:
            raise GprInspectionError("HDF5 chunk exceeds the explicit read budget")
        try:
            array, storage_receipt = read_fixed_array(dataset, max_bytes=max_bytes)
        except StorageReadError as error:
            raise GprInspectionError(str(error)) from error
    return array, {"path": dataset_path, "logical_bytes": byte_count, **description,
                   "units_converted": False, "storage_read": storage_receipt}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        report = inventory_gpr(args.project)
    except (OSError, ValueError) as error:
        parser.exit(1, f"GPR inspection failed: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
