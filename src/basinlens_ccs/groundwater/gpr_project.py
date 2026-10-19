"""Bounded, read-only GPR tree and observed UUID relationship inspection.

This original parser supports a measured subset of the line-oriented Tree/Tree
grammar and selected fixed-width UUID vectors. It follows no external files,
loads no numeric dataset payloads, and writes no project. Use public_summary()
for disclosure: the in-memory graph retains private labels, UUIDs and HDF5 paths.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re

from .gpr_hdf5 import BUILTIN_READ_FILTERS, GprInspectionError, MAX_GPR_BYTES, _filters, _h5py
from .gpr_storage import StorageReadError, read_fixed_array


MAX_TREE_RECORDS = 20000
MAX_TREE_NODES = 4096
MAX_DEPTH = 128
MAX_STRING_BYTES = 4 * 1024 * 1024
MAX_TOTAL_STRING_BYTES = 8 * 1024 * 1024
MAX_OBJECTS = 20000
MAX_ENTITIES = 8192
MAX_RELATIONSHIPS = 32768
MAX_UNRESOLVED = 16384
MAX_JOIN_WORK = 1_000_000
MAX_TOTAL_STORED_BYTES = 16 * 1024 * 1024
MAX_TOTAL_DECODED_BYTES = 16 * 1024 * 1024
MAX_TOTAL_CHUNKS = 4096
TYPE_CATEGORIES = {
    "Project": "project", "TI_ROOT": "module_root", "TIUGRID": "grid", "TIDSET": "dataset",
    "TISOLUTIONFOLDER": "solution_folder", "TIFOLDER": "folder",
    "TIDYNAMIC_SIMULATION_FOLDER": "simulation_collection", "TIDYNAMIC_SIMULATION": "simulation",
    "TICOMPONENT": "component", "TIUGRIDPTR": "grid_pointer", "TIDATASETPTR": "dataset_pointer",
}
INTEGER_FIELDS = {"TRID", "TREXPANDED", "TRSTATE", "TRACTIVE"}


class GprProjectError(GprInspectionError):
    """The project exceeds the supported tree/reference inspection boundary."""


def _check(condition, message):
    if not condition:
        raise GprProjectError(message)


def _uuid(text):
    _check(isinstance(text, str) and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", text),
           "Expected a canonical UUID string")
    # Equality is literal: no case folding, trimming, name matching or remapping
    # between the distinct UUID-bearing contexts is inferred.
    return text


class _BoundedList(list):
    def __init__(self, limit, label):
        super().__init__()
        self.limit, self.label = limit, label

    def append(self, item):
        _check(len(self) < self.limit, f"{self.label} budget exceeded")
        super().append(item)


@dataclass
class TreeNode:
    id: str
    parent_id: str | None
    module_id: str | None
    type_code: str = ""
    label: str | None = None
    uuid: str | None = None
    fields: dict = field(default_factory=dict)

    @property
    def category(self):
        return TYPE_CATEGORIES.get(self.type_code, "unknown")


def parse_project_tree(records) -> tuple[list[TreeNode], list[dict]]:
    """Parse balanced tree/node/module records; never evaluate a serialized value."""
    _check(isinstance(records, (list, tuple)) and 2 <= len(records) <= MAX_TREE_RECORDS,
           "Tree record count exceeds the supported range")
    _check(all(isinstance(line, str) and 0 < len(line.encode("utf-8")) <= 4096
               and not any(ord(char) < 32 for char in line) for line in records), "Invalid tree record text")
    _check(records[0] == "BEGTREE" and records[-1] == "ENDTREE", "Missing tree envelope")
    nodes, modules, stack = [], [], []
    for record_number, line in enumerate(records[1:-1], 2):
        command, separator, value = line.partition(" ")
        if command == "BEGTRNODE" and not separator:
            _check(len(nodes) < MAX_TREE_NODES and len(stack) < MAX_DEPTH, "Tree node/depth limit exceeded")
            parent = next((entry[1] for entry in reversed(stack) if entry[0] == "node"), None)
            module = next((entry[1]["id"] for entry in reversed(stack) if entry[0] == "module"), None)
            node = TreeNode(f"node_{len(nodes) + 1:04d}", parent.id if parent else None, module)
            nodes.append(node)
            stack.append(("node", node))
        elif command == "ENDTRNODE" and not separator:
            _check(stack and stack[-1][0] == "node" and stack[-1][1].type_code, "Unbalanced or untyped tree node")
            stack.pop()
        elif command == "BEGTRMOD" and separator:
            _check(stack and stack[-1][0] == "node" and value.isascii() and value.isdigit()
                   and len(value) <= 10 and int(value) <= 2147483647 and len(stack) < MAX_DEPTH,
                   "Invalid module envelope")
            module = {"id": f"module_{len(modules) + 1:04d}", "number": int(value), "parent_id": stack[-1][1].id}
            modules.append(module)
            stack.append(("module", module))
        elif command == "ENDTRMOD" and separator:
            _check(stack and stack[-1][0] == "module" and value.isascii() and value.isdigit()
                   and len(value) <= 10 and int(value) == stack[-1][1]["number"], "Unbalanced module envelope")
            stack.pop()
        elif command in {"TRTYPE", "TRNAME", "TRGUID", *INTEGER_FIELDS} and separator:
            _check(stack and stack[-1][0] == "node", "Tree field outside a node")
            node = stack[-1][1]
            _check(command not in node.fields, "Duplicate tree field")
            if command == "TRTYPE":
                _check(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", value), "Invalid tree type token")
                node.type_code = value
                parsed = value
            elif command == "TRNAME":
                _check(len(value) >= 2 and value[0] == value[-1] == '"' and '"' not in value[1:-1],
                       "Unsupported quoted tree label")
                node.label = value[1:-1]
                parsed = node.label
            elif command == "TRGUID":
                node.uuid = _uuid(value)
                parsed = node.uuid
            else:
                _check(re.fullmatch(r"-?[0-9]{1,10}", value), "Invalid integer tree field")
                parsed = int(value)
                _check(-2147483648 <= parsed <= 2147483647, "Integer tree field out of range")
                if command == "TREXPANDED":
                    _check(parsed in (0, 1), "Unsupported expansion flag")
            node.fields[command] = parsed
        else:
            raise GprProjectError(f"Unsupported or misplaced tree record at position {record_number}")
    _check(not stack and nodes and sum(node.parent_id is None for node in nodes) == 1
           and nodes[0].type_code == "Project" and sum(node.type_code == "Project" for node in nodes) == 1,
           "Incomplete or unsupported tree hierarchy")
    return nodes, modules


def _identity(path):
    _check(path.is_file() and path.stat().st_size <= MAX_GPR_BYTES, "Project file exceeds the supported byte limit")
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while data := source.read(1024 * 1024):
            size += len(data)
            _check(size <= MAX_GPR_BYTES, "Project file exceeds the supported byte limit")
            digest.update(data)
    return {"bytes": size, "sha256": digest.hexdigest()}


class _Reader:
    def __init__(self, project):
        self.project = project
        self.h5py = _h5py()
        self.total_bytes = 0
        self.objects = 0
        self.read_paths = []
        self.total_stored_bytes = 0
        self.total_chunks = 0
        self.total_decoded_bytes = 0

    def obj(self, path, *, optional=False):
        self.objects += 1
        _check(self.objects <= MAX_OBJECTS, "Project object inspection budget exceeded")
        parts = path.strip("/").split("/")
        _check(path.startswith("/") and all(part not in ("", ".", "..") for part in parts), "Invalid HDF5 path")
        item = self.project
        for part in parts:
            _check(isinstance(item, self.h5py.Group), "Expected an HDF5 group")
            link = item.get(part, getlink=True)
            if link is None and optional:
                return None
            _check(isinstance(link, self.h5py.HardLink), "Project inspection requires complete hard-link paths")
            item = item[part]
        return item

    def strings(self, path, *, optional=False):
        dataset = self.obj(path, optional=optional)
        if dataset is None:
            return None
        _check(isinstance(dataset, self.h5py.Dataset) and dataset.ndim == 1
               and dataset.dtype.kind == "S" and 0 < dataset.dtype.itemsize <= 4096
               and len(dataset) <= MAX_TREE_RECORDS, "Expected a bounded fixed-width string vector")
        _check(not dataset.is_virtual and not dataset.external, "Virtual/external-storage strings are unsupported")
        _check(all(number in BUILTIN_READ_FILTERS for number in _filters(dataset)), "Unsupported/plugin HDF5 filter")
        count = dataset.size * dataset.dtype.itemsize
        _check(count <= MAX_STRING_BYTES and self.total_bytes + count <= MAX_TOTAL_STRING_BYTES,
               "Project string payload byte budget exceeded")
        _check(dataset.chunks is None or math.prod(dataset.chunks) * dataset.dtype.itemsize <= MAX_STRING_BYTES,
               "Project string chunk byte budget exceeded")
        self.total_bytes += count
        self.read_paths.append(path)
        try:
            array, receipt = read_fixed_array(dataset, max_bytes=MAX_STRING_BYTES,
                                              max_stored_bytes=MAX_TOTAL_STORED_BYTES - self.total_stored_bytes,
                                              max_decoded_bytes=min(MAX_STRING_BYTES, MAX_TOTAL_DECODED_BYTES - self.total_decoded_bytes),
                                              max_chunks=MAX_TOTAL_CHUNKS - self.total_chunks)
        except StorageReadError as error:
            raise GprProjectError(str(error)) from error
        self.total_stored_bytes += receipt["stored_bytes_read"]
        self.total_chunks += receipt["chunks_read"]
        self.total_decoded_bytes += receipt["decoded_chunk_bytes"]
        result = []
        for raw in array:
            try:
                value = bytes(raw).decode("utf-8")
            except UnicodeError as error:
                raise GprProjectError("Unsupported project string encoding") from error
            _check("\x00" not in value, "Embedded NUL in project string")
            result.append(value)
        return result

    def guids(self, path, *, optional=False, single=False):
        strings = self.strings(path, optional=optional)
        if strings is None:
            return None
        _check(not single or len(strings) == 1, "Expected a single UUID value")
        return [_uuid(value) for value in strings]

    def groups(self, path):
        group = self.obj(path, optional=True)
        if group is None:
            return []
        _check(isinstance(group, self.h5py.Group) and len(group) <= MAX_OBJECTS - self.objects,
               "Project child inventory limit exceeded")
        children = []
        for name in sorted(group.keys()):
            child = path + "/" + name
            item = self.obj(child)
            if isinstance(item, self.h5py.Group):
                children.append(child)
        return children

    def numeric_storage(self, path):
        dataset = self.obj(path, optional=True)
        if dataset is None:
            return None
        _check(isinstance(dataset, self.h5py.Dataset) and dataset.shape is not None
               and dataset.dtype.kind in "biuf", "Expected numeric dataset storage metadata")
        _check(not dataset.is_virtual and not dataset.external, "Virtual/external-storage numeric datasets are unsupported")
        _check(all(number in BUILTIN_READ_FILTERS for number in _filters(dataset)), "Unsupported/plugin HDF5 filter")
        return {"shape": list(dataset.shape), "dtype": str(dataset.dtype), "payload_read": False}


@dataclass
class ProjectGraph:
    """Private graph: labels/UUIDs/paths are retained only for explicit caller use."""

    source: dict
    nodes: list[TreeNode]
    modules: list[dict]
    entities: list[dict]
    relationships: list[dict]
    unresolved: list[dict]
    tree_sha256: str
    read_audit: dict

    def public_summary(self):
        """Produce a fixed-schema projection without original labels, UUIDs or paths."""
        return {"schema": "basinlens-gpr-project-graph-v1", "source": self.source,
                "tree_records_sha256": self.tree_sha256,
                "counts": {"tree_nodes": len(self.nodes), "module_envelopes": len(self.modules),
                           "entities": len(self.entities), "relationships": len(self.relationships),
                           "unresolved": len(self.unresolved),
                           "node_categories": dict(sorted(Counter(node.category for node in self.nodes).items())),
                           "entity_categories": dict(sorted(Counter(item["kind"] for item in self.entities).items()))},
                "nodes": [{"id": node.id, "parent_id": node.parent_id, "module_id": node.module_id,
                           "category": node.category, "uuid_present": node.uuid is not None,
                           "label_present": node.label is not None} for node in self.nodes],
                "modules": [{"id": item["id"], "parent_id": item["parent_id"]} for item in self.modules],
                "entities": [{"id": item["id"], "category": item["kind"], "role": item["role"],
                              "storage": item["storage"]} for item in self.entities],
                "relationships": self.relationships, "unresolved": self.unresolved,
                "read_audit": {"string_vectors_read": self.read_audit["string_vectors_read"],
                               "string_payload_bytes": self.read_audit["string_payload_bytes"],
                               "stored_string_bytes_read": self.read_audit["stored_string_bytes_read"],
                               "raw_chunks_read": self.read_audit["raw_chunks_read"],
                               "decoded_string_chunk_bytes": self.read_audit["decoded_string_chunk_bytes"],
                               "hdf5_filter_decode_invoked": False,
                               "numeric_dataset_payloads_read": False, "external_files_followed": False,
                               "indirect_hdf5_links_followed": False},
                "original_labels_included": False, "raw_uuids_included": False,
                "original_hdf5_paths_included": False, "coordinate_units": None, "crs": None,
                "vertical_datum": None, "units_converted": False, "gms_runtime_executed": False,
                "scope": "Partial serialized tree and UUID equality relationships only; no project writer, external component synchronization or full GMS equivalence."}


def read_gpr_project(path: str | Path) -> ProjectGraph:
    """Inspect observed project relationships without loading geometry/field payloads."""
    path = Path(path).resolve(strict=True)
    before = _identity(path)
    entities = _BoundedList(MAX_ENTITIES, "Project entity")
    relationships = _BoundedList(MAX_RELATIONSHIPS, "Project relationship")
    unresolved = _BoundedList(MAX_UNRESOLVED, "Unresolved relationship")
    h5py = _h5py()
    with h5py.File(path, "r") as project:
        reader = _Reader(project)
        records = reader.strings("/Tree/Tree")
        nodes, modules = parse_project_tree(records)
        by_uuid = defaultdict(list)
        for node in nodes:
            if node.uuid:
                by_uuid[node.uuid].append(node)
        entity_index = defaultdict(list)
        join_work = 0

        def entity(kind, role, entity_uuid, location, storage=None):
            item = {"id": f"entity_{len(entities) + 1:04d}", "kind": kind, "role": role,
                    "uuid": entity_uuid, "path": location, "storage": storage}
            entities.append(item)
            entity_index[(kind, entity_uuid)].append(item)
            return item

        def join_tree(item, categories, relation):
            nonlocal join_work
            join_work += len(by_uuid[item["uuid"]])
            _check(join_work <= MAX_JOIN_WORK, "Project UUID join-work budget exceeded")
            candidates = [node for node in by_uuid[item["uuid"]] if node.category in categories]
            if not candidates:
                unresolved.append({"source": item["id"], "kind": relation, "reason": "uuid_not_found_in_expected_tree_category"})
            else:
                for target in candidates:
                    relationships.append({"source": item["id"], "target": target.id, "kind": relation,
                                          "basis": "uuid_equality", "target_count": len(candidates)})

        project_guid = reader.guids("/GUID", optional=True, single=True)
        if project_guid:
            item = entity("project", "project_identity", project_guid[0], "/GUID")
            join_tree(item, {"project"}, "project_identity_matches_tree")

        for grid_path in reader.groups("/UnstructuredGridModule"):
            guid = reader.guids(grid_path + "/PROPERTIES/GUID", optional=True, single=True)
            if guid is None:
                unresolved.append({"source": "project", "kind": "grid_identity", "reason": "grid_guid_not_available"})
                continue
            geometry_storage = reader.numeric_storage(grid_path + "/Geometry.xmsgrid")
            grid = entity("grid", "grid_identity", guid[0], grid_path, {"geometry_packet": geometry_storage})
            if geometry_storage is None:
                unresolved.append({"source": grid["id"], "kind": "geometry_packet_storage", "reason": "geometry_packet_not_available"})
            join_tree(grid, {"grid"}, "grid_identity_matches_tree")
            alias = reader.guids(grid_path + "/Datasets/Guid", optional=True, single=True)
            if alias is not None:
                if alias[0] == guid[0]:
                    relationships.append({"source": grid["id"], "target": grid["id"],
                                          "kind": "grid_dataset_container_identity_agrees", "basis": "uuid_equality", "target_count": 1})
                else:
                    unresolved.append({"source": grid["id"], "kind": "grid_dataset_container_identity",
                                       "reason": "uuid_sources_disagree"})
            for field_name, role in (("Point Z Dataset Uuid", "point_elevation"),
                                     ("Top Z Dataset Uuid", "cell_top"), ("Bottom Z Dataset Uuid", "cell_bottom")):
                guid = reader.guids(grid_path + "/PROPERTIES/" + field_name, optional=True, single=True)
                if guid:
                    item = entity("declared_geometry_field", role, guid[0], grid_path + "/PROPERTIES/" + field_name)
                    relationships.append({"source": grid["id"], "target": item["id"], "kind": "declares_geometry_field",
                                          "basis": "explicit_property", "target_count": 1})
                    join_tree(item, {"dataset"}, "declared_geometry_field_matches_tree")
            for dataset_path in reader.groups(grid_path + "/Datasets"):
                guid = reader.guids(dataset_path + "/GUID", optional=True, single=True)
                if not guid:
                    unresolved.append({"source": grid["id"], "kind": "saved_dataset_identity", "reason": "dataset_guid_not_available"})
                    continue
                storage = {key.lower(): reader.numeric_storage(dataset_path + "/" + key) for key in ("Values", "Times", "Active")}
                item = entity("saved_dataset", "saved_dataset_identity_record", guid[0], dataset_path, storage)
                if storage["values"] is None:
                    unresolved.append({"source": item["id"], "kind": "saved_numeric_storage",
                                       "reason": "values_storage_not_available"})
                relationships.append({"source": grid["id"], "target": item["id"], "kind": "contains_saved_dataset",
                                      "basis": "hdf5_containment", "target_count": 1})
                join_tree(item, {"dataset", "dataset_pointer"}, "saved_dataset_matches_tree")

        for family_path in reader.groups("/SimSolutions"):
            for solution_path in reader.groups(family_path):
                guid = reader.guids(solution_path + "/GUID", optional=True, single=True)
                if not guid:
                    unresolved.append({"source": "project", "kind": "solution_identity", "reason": "solution_guid_not_available"})
                    continue
                solution = entity("solution", "serialized_solution_record", guid[0], solution_path)
                join_tree(solution, {"solution_folder"}, "solution_identity_matches_tree")
                for key, kind, target_kind in (("SolutionDatasets", "solution_dataset_reference", "saved_dataset"),
                                               ("SolutionComponents", "solution_component_reference", "component")):
                    values = reader.guids(solution_path + "/" + key, optional=True)
                    if values is None:
                        continue
                    for index, value in enumerate(values):
                        reference = entity("reference", kind, value, solution_path + "/" + key + f"[{index}]")
                        relationships.append({"source": solution["id"], "target": reference["id"], "kind": kind,
                                              "basis": "explicit_uuid_vector", "target_count": 1})
                        categories = {"dataset", "dataset_pointer"} if target_kind == "saved_dataset" else {"component"}
                        join_tree(reference, categories, kind + "_matches_tree")
                        if target_kind == "saved_dataset":
                            targets = entity_index[(target_kind, value)]
                            join_work += len(targets)
                            _check(join_work <= MAX_JOIN_WORK, "Project UUID join-work budget exceeded")
                            if not targets:
                                unresolved.append({"source": reference["id"], "kind": "reference_to_saved_dataset",
                                                   "reason": "uuid_not_found_in_saved_dataset_inventory"})
                            for target in targets:
                                relationships.append({"source": reference["id"], "target": target["id"],
                                                      "kind": "reference_to_saved_dataset", "basis": "uuid_equality", "target_count": len(targets)})

        matched_nodes = {item["target"] for item in relationships if item["target"].startswith("node_")}
        saved_with_values = {item["id"] for item in entities if item["kind"] == "saved_dataset" and item["storage"]["values"] is not None}
        storage_matched_nodes = {item["target"] for item in relationships
                                 if item["kind"] == "declared_geometry_field_matches_tree"
                                 or (item["kind"] == "saved_dataset_matches_tree" and item["source"] in saved_with_values)}
        for node in nodes:
            if node.category == "grid_pointer":
                unresolved.append({"source": node.id, "kind": "grid_pointer_target", "reason": "pointer_target_encoding_not_established"})
            elif node.category in {"dataset", "dataset_pointer"} and node.id not in storage_matched_nodes:
                unresolved.append({"source": node.id, "kind": "dataset_identity", "reason": "uuid_not_found_in_storage_or_geometry_declaration_inventory"})
            elif node.category == "component":
                unresolved.append({"source": node.id, "kind": "external_component_payload", "reason": "external_component_files_not_inspected"})
            elif node.category == "simulation":
                unresolved.append({"source": node.id, "kind": "simulation_component_mapping", "reason": "editor_component_mapping_not_established"})
            elif node.category in {"project", "grid", "solution_folder"} and node.id not in matched_nodes:
                unresolved.append({"source": node.id, "kind": "serialized_identity", "reason": "uuid_not_found_in_supported_identity_inventory"})
            elif node.category == "unknown":
                unresolved.append({"source": node.id, "kind": "unknown_tree_type", "reason": "type_semantics_not_established"})
        audit = {"string_vectors_read": len(reader.read_paths), "string_payload_bytes": reader.total_bytes,
                 "stored_string_bytes_read": reader.total_stored_bytes, "raw_chunks_read": reader.total_chunks,
                 "decoded_string_chunk_bytes": reader.total_decoded_bytes,
                 "private_read_paths": reader.read_paths}
    after = _identity(path)
    _check(before == after, "Project bytes changed during tree inspection")
    tree_digest = hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()
    return ProjectGraph({**before, "identity_verified_after_read": True}, nodes, modules, entities, relationships,
                        unresolved, tree_digest, audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        graph = read_gpr_project(args.project)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Project inspection failed ({type(error).__name__}); no graph was emitted.\n")
    print(json.dumps(graph.public_summary(), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
