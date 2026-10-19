"""Original synthetic project trees and UUID registries; no vendor fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from basinlens_ccs.groundwater.gpr_project import GprProjectError, parse_project_tree, read_gpr_project


UUIDS = {name: f"a1234567-0000-4000-8000-{number:012d}"
         for number, name in enumerate(("project", "grid", "point", "top", "bottom", "saved", "solution", "simulation", "component", "pointer"), 1)}


def tree_fixture(*, unknown=False, repeated_components=0):
    records = ["BEGTREE"]

    def begin(code, identity=None):
        records.extend(["BEGTRNODE", "TRTYPE " + code, 'TRNAME "PRIVATE_LABEL"'])
        if identity:
            records.append("TRGUID " + UUIDS[identity])

    def end():
        records.append("ENDTRNODE")

    begin("Project", "project")
    records.append("TREXPANDED 1")
    records.append("BEGTRMOD 21")
    begin("TI_ROOT")
    begin("TIUGRID", "grid")
    for key in ("point", "top", "bottom"):
        begin("TIDSET", key)
        end()
    begin("TISOLUTIONFOLDER", "solution")
    begin("TIDSET", "saved")
    end()
    end()
    end()
    end()
    records.extend(["ENDTRMOD 21", "BEGTRMOD 39"])
    begin("TI_ROOT")
    begin("TIDYNAMIC_SIMULATION", "simulation")
    begin("TICOMPONENT", "component")
    end()
    for _ in range(repeated_components):
        begin("TICOMPONENT", "component")
        end()
    begin("TIUGRIDPTR", "pointer")
    end()
    begin("TIDATASETPTR", "saved")
    end()
    if unknown:
        begin("PRIVATE_UNKNOWN_TYPE")
        end()
    end()
    end()
    records.append("ENDTRMOD 39")
    end()
    records.append("ENDTREE")
    return records


def create_fixture(path, *, unknown=False, repeated_components=0, component_references=None):
    import h5py
    with h5py.File(path, "w") as project:
        def strings(location, values):
            project.create_dataset(location, data=np.array(values, dtype="S128"), compression="gzip")
        strings("Tree/Tree", tree_fixture(unknown=unknown, repeated_components=repeated_components))
        strings("GUID", [UUIDS["project"]])
        grid = "UnstructuredGridModule/PRIVATE_GRID_PATH"
        strings(grid + "/PROPERTIES/GUID", [UUIDS["grid"]])
        strings(grid + "/Datasets/Guid", [UUIDS["grid"]])
        for name, key in (("Point", "point"), ("Top", "top"), ("Bottom", "bottom")):
            strings(grid + f"/PROPERTIES/{name} Z Dataset Uuid", [UUIDS[key]])
        # Intentionally not a valid geometry packet: semantic inspection must not decode it.
        project.create_dataset(grid + "/Geometry.xmsgrid", data=np.array([1, 2, 3], dtype="i1"))
        saved = grid + "/Datasets/PRIVATE_DATASET_PATH"
        strings(saved + "/GUID", [UUIDS["saved"]])
        for name, values in (("Values", [[123.0, 456.0]]), ("Times", [8.0]), ("Active", [[1, 1]])):
            project.create_dataset(saved + "/" + name, data=values)
        solution = "SimSolutions/PRIVATE_FAMILY_PATH/PRIVATE_SOLUTION_PATH"
        strings(solution + "/GUID", [UUIDS["solution"]])
        strings(solution + "/SolutionDatasets", [UUIDS["saved"]])
        strings(solution + "/SolutionComponents", component_references or [UUIDS["component"]])


class ProjectTreeGrammarTests(unittest.TestCase):
    def test_hierarchy_and_module_envelopes_are_structural(self):
        nodes, modules = parse_project_tree(tree_fixture())
        self.assertEqual(len(nodes), 13)
        self.assertEqual([item["number"] for item in modules], [21, 39])
        grid = next(node for node in nodes if node.category == "grid")
        child = next(node for node in nodes if node.uuid == UUIDS["point"])
        self.assertEqual(child.parent_id, grid.id)
        self.assertEqual(child.module_id, modules[0]["id"])
        self.assertEqual(nodes[0].label, "PRIVATE_LABEL")

    def test_unbalanced_duplicate_unknown_and_executable_records_fail(self):
        original = tree_fixture()
        cases = [original[:-1], original[:5] + [original[4]] + original[5:],
                 [line.replace("ENDTRMOD 21", "ENDTRMOD 22") for line in original],
                 original[:2] + ["TRHIDDEN __import__('os').system('anything')"] + original[2:],
                 [line.replace('TRNAME "PRIVATE_LABEL"', 'TRNAME "unterminated') for line in original],
                 [line.replace("TREXPANDED 1", "TREXPANDED 9") for line in original]]
        for case in cases:
            with self.subTest(case=cases.index(case)), self.assertRaises(GprProjectError):
                parse_project_tree(case)

    def test_literal_uuid_text_and_unknown_types_are_preserved_privately(self):
        records = tree_fixture(unknown=True)
        records = [line.replace(UUIDS["grid"], UUIDS["grid"].upper()) for line in records]
        nodes, _ = parse_project_tree(records)
        self.assertEqual(next(node for node in nodes if node.category == "grid").uuid, UUIDS["grid"].upper())
        self.assertEqual(nodes[-1].category, "unknown")
        self.assertEqual(nodes[-1].type_code, "PRIVATE_UNKNOWN_TYPE")

    def test_record_node_depth_and_character_bounds_fail_closed(self):
        for name, value in (("MAX_TREE_RECORDS", 4), ("MAX_TREE_NODES", 3), ("MAX_DEPTH", 3)):
            with patch("basinlens_ccs.groundwater.gpr_project." + name, value), self.assertRaises(GprProjectError):
                parse_project_tree(tree_fixture())
        for bad in ("TRTYPE bad\x00type", "TRTYPE " + "a" * 5000):
            with self.assertRaises(GprProjectError):
                parse_project_tree(["BEGTREE", "BEGTRNODE", bad, "ENDTRNODE", "ENDTREE"])


@unittest.skipUnless(importlib.util.find_spec("h5py"), "h5py is optional")
class ProjectHdf5Tests(unittest.TestCase):
    def test_real_relationships_without_numeric_payload_reads_or_private_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PRIVATE_FILE.gpr"
            create_fixture(path, unknown=True)
            before = path.read_bytes()
            graph = read_gpr_project(path)
            summary = graph.public_summary()
            encoded = json.dumps(summary, allow_nan=False)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(summary["source"]["sha256"], hashlib.sha256(before).hexdigest())
            self.assertNotIn("PRIVATE", encoded)
            self.assertTrue(all(value not in encoded for value in UUIDS.values()))
            self.assertFalse(summary["read_audit"]["numeric_dataset_payloads_read"])
            self.assertFalse(summary["read_audit"]["external_files_followed"])
            self.assertTrue(any(edge["kind"] == "reference_to_saved_dataset" for edge in graph.relationships))
            self.assertTrue(any(item["kind"] == "grid_pointer_target" for item in graph.unresolved))
            self.assertTrue(any(item["kind"] == "unknown_tree_type" for item in graph.unresolved))
            self.assertTrue(any(item["kind"] == "external_component_payload" for item in graph.unresolved))
            self.assertIsNone(summary["coordinate_units"])

    def test_duplicate_uuid_fanout_is_explicit_and_aggregate_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            create_fixture(path, repeated_components=3, component_references=[UUIDS["component"]] * 3)
            graph = read_gpr_project(path)
            matches = [edge for edge in graph.relationships if edge["kind"] == "solution_component_reference_matches_tree"]
            self.assertEqual(len(matches), 12)
            self.assertTrue(all(edge["target_count"] == 4 and edge["basis"] == "uuid_equality" for edge in matches))
            for name, value, message in (("MAX_ENTITIES", 2, "entity"), ("MAX_RELATIONSHIPS", 10, "relationship"),
                                         ("MAX_JOIN_WORK", 5, "join-work"), ("MAX_TOTAL_STRING_BYTES", 10, "byte budget"),
                                         ("MAX_OBJECTS", 4, "budget")):
                with patch("basinlens_ccs.groundwater.gpr_project." + name, value):
                    with self.assertRaisesRegex(GprProjectError, message):
                        read_gpr_project(path)

    def test_case_different_uuid_is_not_silently_remapped(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            create_fixture(path)
            with h5py.File(path, "r+") as project:
                project["UnstructuredGridModule/PRIVATE_GRID_PATH/PROPERTIES/GUID"][0] = UUIDS["grid"].upper().encode()
            graph = read_gpr_project(path)
            self.assertTrue(any(item["reason"] == "uuid_sources_disagree" for item in graph.unresolved))
            self.assertFalse(any(edge["kind"] == "grid_identity_matches_tree" for edge in graph.relationships))

    def test_reference_matching_tree_is_not_claimed_as_saved_storage(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            create_fixture(path)
            with h5py.File(path, "r+") as project:
                del project["UnstructuredGridModule/PRIVATE_GRID_PATH/Datasets/PRIVATE_DATASET_PATH"]
            graph = read_gpr_project(path)
            reasons = [item["reason"] for item in graph.unresolved]
            self.assertIn("uuid_not_found_in_saved_dataset_inventory", reasons)
            self.assertIn("uuid_not_found_in_storage_or_geometry_declaration_inventory", reasons)

    def test_guid_only_group_is_not_claimed_as_numeric_storage(self):
        import h5py
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            create_fixture(path)
            with h5py.File(path, "r+") as project:
                for name in ("Values", "Times", "Active"):
                    del project["UnstructuredGridModule/PRIVATE_GRID_PATH/Datasets/PRIVATE_DATASET_PATH/" + name]
            graph = read_gpr_project(path)
            item = next(item for item in graph.entities if item["kind"] == "saved_dataset")
            self.assertEqual(item["role"], "saved_dataset_identity_record")
            self.assertIsNone(item["storage"]["values"])
            self.assertTrue(any(edge["kind"] == "saved_dataset_matches_tree" for edge in graph.relationships))
            reasons = {item["reason"] for item in graph.unresolved}
            self.assertIn("values_storage_not_available", reasons)
            self.assertIn("uuid_not_found_in_storage_or_geometry_declaration_inventory", reasons)

    def test_changed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.gpr"
            create_fixture(path)
            with patch("basinlens_ccs.groundwater.gpr_project._identity", side_effect=[{"sha256": "a"}, {"sha256": "b"}]):
                with self.assertRaisesRegex(GprProjectError, "changed"):
                    read_gpr_project(path)

    def test_indirect_hdf5_links_are_never_followed(self):
        import h5py
        for kind in ("soft", "external"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "synthetic.gpr"
                create_fixture(path)
                with h5py.File(path, "r+") as project:
                    del project["Tree"]
                    project["Tree"] = h5py.SoftLink("/missing") if kind == "soft" else h5py.ExternalLink("not-created.h5", "/Tree")
                with self.assertRaisesRegex(GprProjectError, "hard-link"):
                    read_gpr_project(path)
                self.assertFalse((Path(directory) / "not-created.h5").exists())

    def test_vds_external_storage_plugin_vlen_and_wrong_shapes_fail_before_payload(self):
        import h5py
        for kind in ("virtual", "external", "plugin", "variable", "shape", "nul", "chunk"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "synthetic.gpr"
                create_fixture(path)
                with h5py.File(path, "r+") as project:
                    del project["Tree/Tree"]
                    if kind == "virtual":
                        layout = h5py.VirtualLayout(shape=(2,), dtype="S64")
                        layout[:] = h5py.VirtualSource("not-created.h5", "Tree", shape=(2,))
                        project.create_virtual_dataset("Tree/Tree", layout)
                    elif kind == "external":
                        project.create_dataset("Tree/Tree", shape=(2,), dtype="S64", external=[("not-created.raw", 0, 128)])
                    elif kind == "plugin":
                        props = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
                        props.set_chunk((2,))
                        props.set_filter(32000, h5py.h5z.FLAG_OPTIONAL)
                        h5py.h5d.create(project["Tree"].id, b"Tree", h5py.h5t.py_create(np.dtype("S64")),
                                       h5py.h5s.create_simple((2,)), dcpl=props)
                    elif kind == "variable":
                        project.create_dataset("Tree/Tree", data=["BEGTREE", "ENDTREE"], dtype=h5py.string_dtype())
                    elif kind == "shape":
                        project.create_dataset("Tree/Tree", data=np.array([[b"BEGTREE", b"ENDTREE"]], dtype="S64"))
                    elif kind == "nul":
                        project.create_dataset("Tree/Tree", data=np.array([b"BEGTREE", b"BAD\x00DATA"], dtype="S64"))
                    else:
                        project.create_dataset("Tree/Tree", shape=(2,), maxshape=(None,), chunks=(2048,), dtype="S4096")
                with self.assertRaises(GprProjectError):
                    read_gpr_project(path)
                self.assertFalse((Path(directory) / "not-created.h5").exists())
                self.assertFalse((Path(directory) / "not-created.raw").exists())


if __name__ == "__main__":
    unittest.main()
