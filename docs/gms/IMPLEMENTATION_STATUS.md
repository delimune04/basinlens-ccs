# GMS implementation status

Selected documented GMS 10.9 capabilities, mapped exactly to the unchanged 163-entry investigation catalogue. This is a partial, nonexhaustive work inventory; no whole-product completion percentage is defined.

Whole-product barrier: **OPEN**. Inventory incomplete; unlisted functions remain unknown.
Native GPR writing is unimplemented. No whole-product completion claim follows from catalogue counts.

| Implementation state | Catalogue entries |
|---|---:|
| NONE | 147 |
| PARTIAL | 16 |
| SCOPED_COMPLETE | 0 |

| Original comparison state | Catalogue entries |
|---|---:|
| NOT_OBSERVED | 160 |
| OBSERVED_PARTIAL | 3 |
| VERIFIED | 0 |

Implementation and original comparison are independent. NONE means this documented capability is not implemented. PARTIAL names only the stated bounded original code. SCOPED_COMPLETE, when accepted, can cover only its explicit limited contract and leaves the broader capability open. OBSERVED_PARTIAL here means saved official GPR structure/geometry only; no original GMS numerical match is established. Current witnessed original GMS numerical comparisons and VERIFIED features are zero. Schema v1 refuses VERIFIED until a reviewed feature-specific acceptance/replay gate exists. The latest software evidence is an explicitly selected-module bootstrap, full_suite=false, excluding status accounting; the subsequent full-suite result is recorded separately. Software tests, own .blproj/native-MF6 round trips and shipped tutorial agreement do not establish original GMS equivalence. Source/test records are checksummed operator records, not independent authentication.

## Ordered next work

1. `interchange.gpr_container`: Resolve remaining saved GPR external dependencies/versioned semantics and loading diagnostics. Own .blproj exchange is available; native GPR writing still requires an established schema and authorized original save/reopen reference.
2. `workspace.project_save`: Extend original BasinLens package contracts only with explicit schema/tests; establish native GPR schema and an authorized original open/save/reopen reference before claiming GPR writing.
3. `geology.borehole_import`: Specify and implement a bounded borehole-log interval format with explicit depth/elevation datum, units, interval overlap/missing checks and synthetic import/export cases. Existing named flat strata are explicit model input and do not implement borehole interpretation.
4. `grid.structured_creation`: Extend one unsupported grid capability at a time, beginning with a reviewed nonuniform-spacing/inactive-cell contract; retain exact physical coordinate mapping and before/after native input/result checks.
5. `grid.initial_boundary_inputs`: Add the next documented package through an explicit typed contract and independent rate/storage checks, starting with EVT only after its support/units and dry-state semantics are specified; retain the six existing boundary checks.
6. `engine.modflow6.flow`: Retain the complete bounded load/save/geology/grid/6BC/export/run/view example and define the first authorized original GMS comparison case with identical inputs, geometry, units, schedule and observed outputs. Extend unsupported GWF packages separately with actual numerical checks.
7. `engine.modflow6.transport`: Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation.
8. `ugrid.creation`: Verify generated domain support, element types and cell identifiers.
9. `conceptual.coverages`: Maintain multiple coverages and remesh without losing original features.
10. `geostatistics.scatter_io`: Check coordinates, missing-data handling and dataset identities.
11. `visualization.cross_sections`: Compare section values and locations against the source field.
12. `calibration.manual`: Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation.

## Complete mapping of the pinned partial catalogue

| ID | Implementation | Original comparison | Implemented scope | Remaining scope | Next operation |
|---|---|---|---|---|---|
| workspace.modules | PARTIAL | NOT_OBSERVED / NONE | Explicit original BasinLens workspace loads a validated model JSON or own .blproj; edits and applies a draft; inspects named flat strata/cell properties/boundaries; exports/reloads native MF6; executes actual MF6 and views captured results. Existing native/GPR/transport sections remain separate supported scopes. | Complete GMS object-specific workspaces, synchronized native object editing/selection and complete documented data-type coverage remain absent. | Open the same project and select each applicable object workspace. |
| workspace.project_tree | PARTIAL | OBSERVED_PARTIAL / SAVED_ORIGINAL_FILE | Read-only saved GPR BEGTREE/UUID graph plus original BasinLens named flat-stratum/material/cell/boundary inspection. The measured saved tutorial has 29 nodes, 21 relationships and16 unresolved links. Own package preserves the explicit model case; no original native object synchronization. | Implement original object activation, visibility, editing, complete external dependency resolution and native GMS GPR project save/reopen. | Select, hide, show and activate each supported object/data type. |
| workspace.graphics_navigation | PARTIAL | NOT_OBSERVED / NONE | Original BasinLens/Plotly bounded 2D and3D cell previews with named material/stratum, supported property fields and boundary markers, plus layer/time captured-head views. Controls act on the applied validated case; unknown CRS/datum remain literal. | Native GMS picking, arbitrary geometry editing, complete rendering/display state and all documented object types remain absent. | Verify plan/oblique navigation, selection and query values on a known geometry. |
| workspace.xyzs_editing | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Complete documented object/project manipulation, editing and saved display state are absent. | Edit a permissible value; assert the correct object or dataset changes. |
| workspace.project_save | PARTIAL | NOT_OBSERVED / NONE | Original BasinLens .blproj v1 save/open/repack/reopen preserves typed project metadata, registered asset bytes and four bounded view fields; model bridge preserves authoritative named flat-stratum/spatial-property/6BC case and validates coherent outer metadata. This is not a GMS GPR writer. | Native GMS GPR writing, complete saved display state and original GMS open/save/reopen comparison remain unimplemented or unverified. Assets stay inert; no native GPR or unsupported geology conversion is implied. | Extend original BasinLens package contracts only with explicit schema/tests; establish native GPR schema and an authorized original open/save/reopen reference before claiming GPR writing. |
| workspace.projections | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Complete documented object/project manipulation, editing and saved display state are absent. | Import differently referenced data and verify its documented spatial alignment. |
| workspace.display_presets | PARTIAL | NOT_OBSERVED / NONE | Own .blproj stores and restores exactly selected_layer, selected_field, chart_mode and show_wells with explicit defaults and validation. These four view fields are original BasinLens state, not complete GMS display themes. | Complete reusable native GMS theme settings, contour/render/layout state and witnessed theme switching remain absent. | Switch themes and confirm dataset, contour and presentation state is restored. |
| conceptual.coverages | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS-style conceptual geometry creation, attributes, topology and mapping are absent. | Maintain multiple coverages and remesh without losing original features. |
| conceptual.points | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS-style conceptual geometry creation, attributes, topology and mapping are absent. | Create, select, move and query a feature point with retained attributes. |
| conceptual.arcs | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS-style conceptual geometry creation, attributes, topology and mapping are absent. | Edit endpoints/vertices while maintaining documented topology. |
| conceptual.polygons | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS-style conceptual geometry creation, attributes, topology and mapping are absent. | Build, select and edit bounded areas including shared-edge cases. |
| conceptual.feature_editing | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS-style conceptual geometry creation, attributes, topology and mapping are absent. | Compare object identity/topology/attributes before and after editing. |
| conceptual.grid_frames | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS-style conceptual geometry creation, attributes, topology and mapping are absent. | Resize and move a frame then verify the generated domain. |
| gis.shapefile_read | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Load point, line and polygon sources with known coordinates. |
| gis.attribute_table | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Verify typed attribute values and record identities survive import. |
| gis.to_scatter | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Compare exported sample coordinates/attributes against the source. |
| gis.to_features | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Verify selected attributes and topology in the resulting coverage. |
| gis.crs_assignment | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Verify that declared versus transformed references are distinguished. |
| gis.mixed_crs | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Check known control locations after the documented coordinate conversion. |
| gis.cad_import | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Import documented drawing formats and compare coordinate extents. |
| gis.georeferenced_images | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Check reference corners and image opacity against known control points. |
| gis.online_background | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Pan/zoom and test successful and unavailable-service responses. |
| gis.map_layer_display | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Verify layer order and transparency are preserved on save. |
| gis.map_snapshot | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Reopen the saved image without requiring the original map request. |
| gis.web_image_acquisition | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | GIS/CAD/image format reader and writer, attributes and reference transforms are absent. | Acquire a known extent and retain source/reference details. |
| raster.import_properties | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Raster import/manipulation/interpolation workflows are absent. | Verify extents, dimensions, reference and nodata from a known raster. |
| raster.visualization | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Raster import/manipulation/interpolation workflows are absent. | Check value queries, color treatment and nodata display. |
| raster.resample | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Raster import/manipulation/interpolation workflows are absent. | Compare documented resampling method and target support. |
| raster.merge_clip | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Raster import/manipulation/interpolation workflows are absent. | Verify overlap precedence and boundary/nodata behavior. |
| raster.catalog | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Raster import/manipulation/interpolation workflows are absent. | Verify source ordering/support across catalog boundaries. |
| raster.to_scatter | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Raster import/manipulation/interpolation workflows are absent. | Round-trip a small field and quantify expected resampling changes. |
| raster.interpolate | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Raster import/manipulation/interpolation workflows are absent. | Verify output values, support and coordinate correspondence. |
| lidar.import_filter | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Lidar point-cloud acquisition, filtering, conversion and export workflows are absent. | Check class filtering and retained coordinates on a small LAS fixture. |
| lidar.display | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Lidar point-cloud acquisition, filtering, conversion and export workflows are absent. | Confirm display decimation does not change stored/interpolated data. |
| lidar.trim_export | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Lidar point-cloud acquisition, filtering, conversion and export workflows are absent. | Verify exported count, classes and bounds match the requested filter. |
| lidar.to_raster | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Lidar point-cloud acquisition, filtering, conversion and export workflows are absent. | Verify interpolation and handling of sample-free areas. |
| lidar.to_ugrid | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Lidar point-cloud acquisition, filtering, conversion and export workflows are absent. | Compare interpolated values against independent known samples. |
| lidar.multifile_merge | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Lidar point-cloud acquisition, filtering, conversion and export workflows are absent. | Test overlap, coordinate consistency and multi-file coverage. |
| geology.borehole_import | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Specify and implement a bounded borehole-log interval format with explicit depth/elevation datum, units, interval overlap/missing checks and synthetic import/export cases. Existing named flat strata are explicit model input and do not implement borehole interpretation. |
| geology.borehole_materials | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Change one logged interval and verify only its intended assignment changes. |
| geology.borehole_sections | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Compare section endpoints and log contact elevations. |
| geology.section_surface_snap | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Verify section-top elevations against the chosen surface. |
| geology.section_editor | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Edit one correlation and verify the resulting interpreted region/topology. |
| geology.horizon_identity | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Verify consistent horizon ordering across a synthetic log network. |
| geology.solids_from_horizons | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Check bounded volumes, material identities and valid topological contacts. |
| geology.solids_section_constraints | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Confirm a changed interpretation changes only the documented solid constraints. |
| geology.solid_cross_sections | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Compare the section intersection against known simple solids. |
| geology.horizon_extent | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Check that generated solids respect the coverage boundary. |
| geology.auto_horizon_coverages | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Compare generated coverage geometry to a controlled log/section case. |
| geology.tin_construction | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Check triangle connectivity, vertex identities and elevations. |
| geology.tin_editing | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Verify editing operations preserve valid surface connectivity. |
| geology.tin_smoothing | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Borehole/section/horizon/TIN/solid construction and interpretation workflows are absent; shared metadata is not their implementation. | Quantify elevation changes and verify boundaries remain controlled. |
| mesh.horizon_surfaces | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Geological surface/volume mesh construction and remeshing workflows are absent. | Check horizon ordering and interpolation support on known data. |
| mesh.horizon_finite_elements | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Geological surface/volume mesh construction and remeshing workflows are absent. | Verify element orientation, layer/material association and valid thickness. |
| mesh.raster_horizons | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Geological surface/volume mesh construction and remeshing workflows are absent. | Verify catalog/horizon ordering and explicit fill/clip settings. |
| mesh.ugrid_from_rasters | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Geological surface/volume mesh construction and remeshing workflows are absent. | Check top/bottom surfaces, clipped support and sublayer mapping. |
| grid.structured_creation | PARTIAL | NOT_OBSERVED / NONE | Strict original flat-layer uniform-XY structured model: explicit southwest XY origin, south_to_north project rows, exact named-strata layer partition and material assignment to every active cell. Compiler reverses project/native row order explicitly and preserves physical XY. Legacy shared adapter has a separate documented mirrored-contract correction. | Nonuniform XY spacing, arbitrary layer surfaces, pinches, faults, inactive cells, rotated grids, conceptual/GIS remeshing and quadtree/DISV creation remain absent. Named flat strata are explicit input metadata, not inferred 3D geology. | Extend one unsupported grid capability at a time, beginning with a reviewed nonuniform-spacing/inactive-cell contract; retain exact physical coordinate mapping and before/after native input/result checks. |
| grid.direct_cell_data | PARTIAL | NOT_OBSERVED / NONE | Explicit global/layer/cell typed properties and named stratum/material assignments preserve exact support and values. Bounded model compilation uses spatial per-cell kx/ky/kz and Ss, per-cell initial heads and declared porosity metadata. Porosity is preserved and is not substituted for storage. | Arbitrary original GMS cell editing, general package/data synchronization and unsupported geometry/property transformations remain absent. | Edit selected cells and compare the resulting native model arrays. |
| grid.initial_boundary_inputs | PARTIAL | NOT_OBSERVED / NONE | Explicit period/cell CHD, RCH, WEL, GHB, DRN and RIV controls with strict units, conflicts and signs; every period has explicit records including shutoff. Actual MF6 saved-budget rates are checked independently against recharge area, conductance/threshold and river-bed formulas. | EVT/SFR/LAK and other packages, time-series interpolation, GIS conceptual assignment, movers, unsaturated/variable-density boundary physics and original GMS editing comparison remain absent. | Add the next documented package through an explicit typed contract and independent rate/storage checks, starting with EVT only after its support/units and dry-state semantics are specified; retain the six existing boundary checks. |
| grid.model_checker | PARTIAL | NOT_OBSERVED / NONE | Strict typed model/unit/reference, named-strata nonoverlap, exact material coverage, boundary/period conflict and native input graph checks. Captured results separately report water balance, every supported boundary rate and saturated confined head support. Failure receipts and exact source inputs are retained. | Complete original GMS checker coverage, all package/geometry interactions and witnessed checker diagnostics remain unverified. | Reject deliberately inconsistent geometry/control inputs and preserve diagnostics. |
| ugrid.import | PARTIAL | OBSERVED_PARTIAL / SAVED_ORIGINAL_FILE | Read-only level-zero single-layer Binary QuadtreeGrid3d Version1, XmUGrid Version2 type42 extruded quad cells with bounded topology and geometry validation. | Support other UGrid packets, refinement/layers and documented import formats; resolve unknown GPR units and raw Z differences. | Check cell connectivity and face orientation against a known fixture. |
| ugrid.creation | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented Unstructured geometry generation interface, its numerical settings and execution/visualization workflow are absent. | Verify generated domain support, element types and cell identifiers. |
| ugrid.conversions | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented Unstructured object conversions interface, its numerical settings and execution/visualization workflow are absent. | Compare cell support and projected extents before/after conversion. |
| ugrid.extrusion | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented Layered grid extrusion interface, its numerical settings and execution/visualization workflow are absent. | Check layer topology and surface elevations on a controlled prism grid. |
| ugrid.refinement_types | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented Alternative unstructured layouts interface, its numerical settings and execution/visualization workflow are absent. | Exercise each documented layout and verify connectivity and resolution. |
| ugrid.quadtree_refinement | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented Feature-based quadtree refinement interface, its numerical settings and execution/visualization workflow are absent. | Verify requested refinement around wells/rivers without invalid cells. |
| geostatistics.scatter_io | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Check coordinates, missing-data handling and dataset identities. |
| geostatistics.linear_2d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Reproduce an affine field inside its interpolation support. |
| geostatistics.idw_2d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Compare a small point configuration to an independent hand calculation. |
| geostatistics.kriging_2d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Check variogram/settings and a controlled independent reference result. |
| geostatistics.dataset_math | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Verify expressions, units interpretation and missing-value behavior. |
| geostatistics.idw_3d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Compare simple/gradient/quadratic settings on controlled fields. |
| geostatistics.kriging_3d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Verify covariance assumptions and an independent small reference. |
| geostatistics.vertical_anisotropy | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Show that changing anisotropy produces the expected support weighting. |
| geostatistics.bounds_truncation | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Spatial sample I/O, interpolation, kriging and dataset mathematics are absent. | Test out-of-range estimates and explicitly retained/truncated values. |
| visualization.isosurfaces | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented volume operation is absent; existing bounded head surfaces and cell-center plots do not implement it. | Compare surfaces to a field with an analytic level set. |
| visualization.cross_sections | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented volume operation is absent; existing bounded head surfaces and cell-center plots do not implement it. | Compare section values and locations against the source field. |
| visualization.moving_sections | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented volume operation is absent; existing bounded head surfaces and cell-center plots do not implement it. | Verify frame positions, scalar values and exported timing. |
| visualization.moving_isosurfaces | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented volume operation is absent; existing bounded head surfaces and cell-center plots do not implement it. | Verify chosen levels and the generated frame sequence. |
| visualization.clipping_planes | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented volume operation is absent; existing bounded head surfaces and cell-center plots do not implement it. | Check clipping geometry on a simple block with known intersections. |
| visualization.scalar_clipping | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented volume operation is absent; existing bounded head surfaces and cell-center plots do not implement it. | Verify visible cells against exact scalar inequalities. |
| visualization.cell_visibility | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented volume operation is absent; existing bounded head surfaces and cell-center plots do not implement it. | Verify visibility state independently from cell activity/model data. |
| presentation.annotation_objects | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented annotation/layout/export workflow is absent. | Check object placement/scaling in screen and printed output. |
| presentation.annotation_io | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented annotation/layout/export workflow is absent. | Round-trip annotation placement and formatting. |
| presentation.layout_pages | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented annotation/layout/export workflow is absent. | Verify map extents, scale and page/export dimensions. |
| presentation.layout_io | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented annotation/layout/export workflow is absent. | Round-trip multiple views and layout elements. |
| presentation.image_export | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This documented annotation/layout/export workflow is absent. | Compare exported size, legends and content to the selected model view. |
| automation.toolbox_execution | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented GMS processing toolbox/history interface is absent; standalone CLI commands are a separate facility. | Run one tool and compare its result and preserved parameter values. |
| automation.toolbox_history | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented GMS processing toolbox/history interface is absent; standalone CLI commands are a separate facility. | Rerun from saved history and compare output geometry/data. |
| interchange.modflow_native_text | PARTIAL | NOT_OBSERVED / NONE | Bounded original model writes complete deterministic native MF6 plus own settings sidecar; actual FloPy load/rewrite is checked with full ordered token fingerprints and retained input inventories. Optional actual MF6 before/after runs compare captured heads/budget columns and physical gates. Existing strict native input execution preserves declared units. | Classic/USG export, general arbitrary MF6 semantic equivalence, unsupported edit synchronization and witnessed GMS import/export round trips remain absent. | Run the exported case with the corresponding unmodified engine. |
| interchange.external_arrays | PARTIAL | NOT_OBSERVED / NONE | Retain bounded declared native MF6 external input files unchanged in isolated native executions. No new external-array authoring interface. | Implement external-array writing, edit synchronization and round-trip contracts for supported formats. | Verify array paths, shapes and values after moving the export bundle. |
| interchange.modflow6_conversion | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented Export classic/USG models to MF6 interface, its numerical settings and execution/visualization workflow are absent. | Verify conversion warnings, explicitly unsupported controls and reference outputs. |
| interchange.unsupported_packages | PARTIAL | NOT_OBSERVED / NONE | Preserve native MF6 files and opaque bounded JSON/SQLite sidecars without synchronizing them. Execution uses existing supported MF6 files. | Implement documented GMS unsupported-package translation and edit-preserving export; sidecars remain opaque. | Preserve package bytes/paths and run the explicitly selected compatible executable. |
| interchange.gpr_container | PARTIAL | OBSERVED_PARTIAL / SAVED_ORIGINAL_FILE | Bounded read-only HDF5 inventory/arrays, strict raw-chunk budgets, saved project relationships and two measured geometry protocols. Five additional official GPR inventory/tree cases. | Implement native GPR writing, complete versioned schema and lossless read/write/reopen validation in original GMS; no native GPR writer exists. | Resolve remaining saved GPR external dependencies/versioned semantics and loading diagnostics. Own .blproj exchange is available; native GPR writing still requires an established schema and authorized original save/reopen reference. |
| interchange.legacy_gms_formats | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented Legacy GMS formats interface, its numerical settings and execution/visualization workflow are absent. | Enumerate documented legacy formats and verify imports against licensed or independently generated fixtures. |
| licensing.edition_matrix | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | License enforcement and paid modules are not reproduced. Use only ordinary authorized access; edition entitlement remains unknown. | Freeze the target edition and separately enumerate licensed modules and external engine entitlements. |
| licensing.community_limits | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | License enforcement and paid modules are not reproduced. Use only ordinary authorized access; edition entitlement remains unknown. | Identify whether each reference experiment lies within the observed edition permissions. |
| engine.modflow.classic | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW 88 / 96 / 2000 / 2005 interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modflow.nwt | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW-NWT interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modflow.lgr | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW-LGR interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modflow.usg | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW-USG interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modflow.usg_transport | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW-USG-Transport interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modflow6.flow | PARTIAL | NOT_OBSERVED / NONE | Actual USGS MF6/FloPy bounded confined water workflow with named explicit flat strata, spatial K/Ss, six period/cell boundary types, saved input load/rewrite and actual before/after numerical comparisons. Captured-case results verify physical row mapping, water/boundary rates and confined head support. Existing native-input executor retains its separate broader native contract. | Complete GMS model-building/package interfaces and witnessed same-case original GMS numerical comparisons remain absent. CO2-brine/black-oil, field validation, unsaturated or density-dependent interpretations are outside the confined-water contract. | Retain the complete bounded load/save/geology/grid/6BC/export/run/view example and define the first authorized original GMS comparison case with identical inputs, geometry, units, schedule and observed outputs. Extend unsupported GWF packages separately with actual numerical checks. |
| engine.modflow6.transport | PARTIAL | NOT_OBSERVED / NONE | Standalone strict SI 1D saturated conservative-solute GWF/GWT export/run/results with pore-water concentration, boundary mass flux and every-step balances. Explicit-case UI supports profile/mass plots and captured downloads. | Implement general 3D GWT, additional boundaries/reactions, shared-project adapter and witnessed original GMS comparison; no CO2 or density-dependent physics. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modflow6.energy | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW 6 GWE interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modpath | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODPATH interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modpath3du | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented mod-PATH3DU interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.mt3dms | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MT3DMS interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.mt3d_usgs | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MT3D-USGS interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.rt3d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented RT3D interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.seam3d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented SEAM3D interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.seawat | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented SEAWAT interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.pht3d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented PHT3D interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.hgs | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented HydroGeoSphere interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.femwater | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented FEMWATER interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.modaem | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODAEM interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| engine.seep2d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented SEEP2D interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| geometry.feflow | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented FEFLOW geometry interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| geometry.tough2 | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented TOUGH2 geometry interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.pest | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.mf6_observations | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| uncertainty.tprogs | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This stochastic groundwater/transport workflow is absent; separate volumetric Monte Carlo is not its implementation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| solver.samg | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented SAMG / SAMG-MODFLOW+ interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| analysis.zonebudget | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented ZONEBUDGET interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| historical.utexas | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented UTEXAS interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| historical.utchem | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented UTCHEM interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.manual | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.pest_zonal | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.pilot_points | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.pilot_points_advanced | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.pest_svd | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.pest_svd_assist | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.pest_parallel | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.parameter_instances_clusters | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.transient_pumping | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| calibration.transient_data | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | Parameter estimation/observation calibration is absent; preserving observation metadata is not assimilation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| uncertainty.parameter_randomization | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This stochastic groundwater/transport workflow is absent; separate volumetric Monte Carlo is not its implementation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| uncertainty.transport_threshold | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This stochastic groundwater/transport workflow is absent; separate volumetric Monte Carlo is not its implementation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| uncertainty.indicator_simulations | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This stochastic groundwater/transport workflow is absent; separate volumetric Monte Carlo is not its implementation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| uncertainty.stochastic_inverse | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This stochastic groundwater/transport workflow is absent; separate volumetric Monte Carlo is not its implementation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| uncertainty.nsmc_generate | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This stochastic groundwater/transport workflow is absent; separate volumetric Monte Carlo is not its implementation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| uncertainty.nsmc_reuse | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | This stochastic groundwater/transport workflow is absent; separate volumetric Monte Carlo is not its implementation. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.drt | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW DRT interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.ets | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW ETS interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.gage | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW GAGE interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.lak3 | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW LAK3 interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.mnw1 | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW MNW1 interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.mnw2 | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW MNW2 interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.mnw2_nonvertical | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MNW2 nonvertical wells and pump capacity interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.sfr2 | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW SFR1/SFR2 streams interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.str | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW STR streams interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.sub | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW SUB interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.swi2 | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW SWI2 interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.classic.uzf | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW UZF interface interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usg.gnc | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW-USG GNC interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usg.cln | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MODFLOW-USG CLN multilayer wells interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usg.cln_shapefile | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented Shapefile to CLN mapping interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usg.cln_observations | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented CLN well observations interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usgt.pfas | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented USG-Transport PFAS inputs interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usgt.mdt_discrete_fracture | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MDT discrete-fracture example interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usgt.mdt_equivalent_porous | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MDT equivalent porous-media example interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usgt.mdt_matrix | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MDT heterogeneous matrix example interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |
| package.usgt.mdt_3d | NONE | NOT_OBSERVED / NONE | No implementation of this catalogue capability is established. | The documented MDT field-scale 3D example interface, its numerical settings and execution/visualization workflow are absent. | Pin the supported engine version; reproduce the documented interface workflow and independent physical checks within the supported formulation. |

## Official-source reconciliation and open inventory

Substantive items visible in the consulted official 10.9 tutorial index, official model families and selected detailed primary-page rows. Labels are analyst paraphrases for matching, not vendor implementation names. MAPPED means a documentary relationship only; it does not mean the entire source row is specified, implemented or compared. Detailed pages, additional versions, dynamic menus and undiscovered functionality remain open.

Checked: 2026-10-19. Reconciliation is **OPEN** and nonexhaustive.

A catalogue mapping is not an implementation claim. Unmapped observed source items remain explicit open work.

| Source | Source item / locator | Mapping | Catalogue IDs |
|---|---|---|---|
| tutorials | Introduction / startup/project basics | MAPPED | workspace.modules, workspace.project_tree, workspace.project_save |
| tutorials | Introduction / feature geometry | MAPPED | conceptual.points, conceptual.arcs, conceptual.polygons, conceptual.feature_editing |
| tutorials | Introduction / print and image output | MAPPED | presentation.image_export |
| tutorials | Introduction / display themes | MAPPED | workspace.display_presets |
| tutorials | Introduction / print layout | MAPPED | presentation.layout_pages, presentation.layout_io |
| tutorials | Introduction / UGrid clipping | MAPPED | visualization.clipping_planes, visualization.scalar_clipping, visualization.cell_visibility |
| tutorials | Introduction / web import | MAPPED | gis.web_image_acquisition |
| tutorials | Annotations / annotation tools | MAPPED | presentation.annotation_objects, presentation.annotation_io |
| tutorials | Stratigraphy / TIN surfaces | MAPPED | geology.tin_construction, geology.tin_editing, geology.tin_smoothing |
| tutorials | Stratigraphy / boreholes and sections | MAPPED | geology.borehole_import, geology.borehole_sections, geology.section_editor |
| tutorials | Stratigraphy / horizons and solids | MAPPED | geology.horizon_identity, geology.solids_from_horizons |
| tutorials | Stratigraphy / horizon TIN mesh workflow | MAPPED | mesh.horizon_surfaces, mesh.horizon_finite_elements |
| tutorials | Stratigraphy / horizon coverages | MAPPED | geology.horizon_extent, geology.auto_horizon_coverages |
| tutorials | Stratigraphy / raster horizons | MAPPED | mesh.raster_horizons, mesh.ugrid_from_rasters |
| tutorials | Geostatistics / 2D interpolation | MAPPED | geostatistics.linear_2d, geostatistics.idw_2d, geostatistics.kriging_2d |
| tutorials | Geostatistics / 3D interpolation | MAPPED | geostatistics.idw_3d, geostatistics.kriging_3d |
| tutorials | GIS / GIS geometry/attributes | MAPPED | gis.shapefile_read, gis.attribute_table, gis.to_features |
| tutorials | GIS / online maps | MAPPED | gis.online_background, gis.map_snapshot |
| tutorials | GIS / rasters | MAPPED | raster.import_properties, raster.resample, raster.merge_clip |
| tutorials | GIS / projections | MAPPED | gis.crs_assignment, gis.mixed_crs |
| tutorials | GIS / single lidar source | MAPPED | lidar.import_filter, lidar.to_raster |
| tutorials | GIS / multiple lidar sources | MAPPED | lidar.multifile_merge |
| tutorials | Other / processing toolbox | MAPPED | automation.toolbox_execution, automation.toolbox_history |
| tutorials | Classic MODFLOW general / grid construction | MAPPED | grid.structured_creation, grid.direct_cell_data, grid.initial_boundary_inputs, grid.model_checker |
| tutorials | Classic MODFLOW general / conceptual approach 1 | MAPPED | conceptual.coverages |
| tutorials | Classic MODFLOW general / conceptual approach 2 | MAPPED | conceptual.coverages |
| tutorials | Classic MODFLOW general / conceptual approach 3 | MAPPED | conceptual.coverages |
| tutorials | Classic MODFLOW general / conceptual approach 4 | MAPPED | conceptual.coverages |
| tutorials | Classic MODFLOW general / transient data management | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | Classic MODFLOW general / layer interpolation | MAPPED | mesh.horizon_surfaces |
| tutorials | Classic MODFLOW general / solid-to-grid parameters | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | Classic MODFLOW general / NWT | MAPPED | engine.modflow.nwt |
| tutorials | Classic MODFLOW general / ZONEBUDGET | MAPPED | analysis.zonebudget |
| tutorials | Classic MODFLOW general / native text writing | MAPPED | interchange.modflow_native_text, interchange.external_arrays |
| tutorials | Classic MODFLOW general / MF6 conversion | MAPPED | interchange.modflow6_conversion |
| tutorials | Classic MODFLOW general / unsupported native packages | MAPPED | interchange.unsupported_packages |
| tutorials | Classic MODFLOW packages / DRT | MAPPED | package.classic.drt |
| tutorials | Classic MODFLOW packages / ETS | MAPPED | package.classic.ets |
| tutorials | Classic MODFLOW packages / GAGE | MAPPED | package.classic.gage |
| tutorials | Classic MODFLOW packages / LAK | MAPPED | package.classic.lak3 |
| tutorials | Classic MODFLOW packages / MNW1 | MAPPED | package.classic.mnw1 |
| tutorials | Classic MODFLOW packages / MNW2 | MAPPED | package.classic.mnw2 |
| tutorials | Classic MODFLOW packages / MNW2 nonvertical pump limits | MAPPED | package.classic.mnw2_nonvertical |
| tutorials | Classic MODFLOW packages / SFR2 | MAPPED | package.classic.sfr2 |
| tutorials | Classic MODFLOW packages / STR | MAPPED | package.classic.str |
| tutorials | Classic MODFLOW packages / SUB | MAPPED | package.classic.sub |
| tutorials | Classic MODFLOW packages / SWI | MAPPED | package.classic.swi2 |
| tutorials | Classic MODFLOW packages / UZF | MAPPED | package.classic.uzf |
| tutorials | Classic MODFLOW packages / classic recharge | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | Regional/local / LGR | MAPPED | engine.modflow.lgr |
| tutorials | Regional/local / dual LGR | MAPPED | engine.modflow.lgr |
| tutorials | Regional/local / steady regional/local | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | Regional/local / transient regional/local | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | Calibration / manual calibration | MAPPED | calibration.manual |
| tutorials | Calibration / automated estimation | MAPPED | calibration.pest_zonal |
| tutorials | Calibration / pilot points | MAPPED | calibration.pilot_points |
| tutorials | Calibration / advanced pilot points | MAPPED | calibration.pilot_points_advanced |
| tutorials | Calibration / SVD and parallel | MAPPED | calibration.pest_svd, calibration.pest_svd_assist, calibration.pest_parallel |
| tutorials | Calibration / advanced parameters | MAPPED | calibration.parameter_instances_clusters |
| tutorials | Calibration / pumping-test calibration | MAPPED | calibration.transient_pumping |
| tutorials | Calibration / transient calibration | MAPPED | calibration.transient_data |
| tutorials | Calibration / USG PEST | MAPPED | calibration.pest |
| tutorials | Stochastic / parameter randomization | MAPPED | uncertainty.parameter_randomization |
| tutorials | Stochastic / indicator realizations | MAPPED | uncertainty.indicator_simulations |
| tutorials | Stochastic / stochastic inverse | MAPPED | uncertainty.stochastic_inverse |
| tutorials | Stochastic / null-space Monte Carlo I | MAPPED | uncertainty.nsmc_generate |
| tutorials | Stochastic / null-space Monte Carlo II | MAPPED | uncertainty.nsmc_reuse |
| tutorials | USG / UGrid construction | MAPPED | ugrid.creation |
| tutorials | USG / classic-to-USG conversion | MAPPED | ugrid.conversions |
| tutorials | USG / quadtree refinement | MAPPED | ugrid.quadtree_refinement |
| tutorials | USG / complex layouts | MAPPED | ugrid.refinement_types |
| tutorials | USG / USG regional/local | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | USG / USG calibration | MAPPED | calibration.pest |
| tutorials | USG / GNC | MAPPED | package.usg.gnc |
| tutorials | USG / CLN | MAPPED | package.usg.cln |
| tutorials | USG / shapefile CLN | MAPPED | package.usg.cln_shapefile |
| tutorials | USG / CLN observations | MAPPED | package.usg.cln_observations |
| tutorials | USG transport / USGT grid approach | MAPPED | engine.modflow.usg_transport |
| tutorials | USG transport / PFAS | MAPPED | package.usgt.pfas |
| tutorials | USG transport / TVM | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | USG transport / MDT discrete fractures | MAPPED | package.usgt.mdt_discrete_fracture |
| tutorials | USG transport / MDT porous equivalent | MAPPED | package.usgt.mdt_equivalent_porous |
| tutorials | USG transport / MDT matrix diffusion | MAPPED | package.usgt.mdt_matrix |
| tutorials | USG transport / MDT 3D | MAPPED | package.usgt.mdt_3d |
| tutorials | MF6 / conceptual approach | MAPPED | engine.modflow6.flow |
| tutorials | MF6 / grid approach | MAPPED | engine.modflow6.flow |
| tutorials | MF6 / EVT | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | MF6 / GWE | MAPPED | engine.modflow6.energy |
| tutorials | MF6 / GWE borehole heat exchange | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | MF6 / SFR | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | MF6 / transient | MAPPED | engine.modflow6.flow |
| tutorials | MF6 / transport grid | MAPPED | engine.modflow6.transport |
| tutorials | MF6 / uncoupled transport | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | MF6 / MDT 3D | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | MF6 / MDT discrete fractures | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | MF6 / MDT porous equivalent | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | MF6 / MDT sand tank | UNMAPPED_OPEN | Unmapped / OPEN |
| tutorials | MF6 / steady PEST observations | MAPPED | calibration.mf6_observations |
| tutorials | MF6 / transient PEST observations | MAPPED | calibration.mf6_observations |
| tutorials | MF6 / MF6 ZONEBUDGET | MAPPED | analysis.zonebudget |
| tutorials | Particles / MODPATH | MAPPED | engine.modpath |
| tutorials | Particles / mod-PATH3DU | MAPPED | engine.modpath3du |
| tutorials | Particles / transient mod-PATH3DU | MAPPED | engine.modpath3du |
| tutorials | SEAWAT / Hele-Shaw | MAPPED | engine.seawat |
| tutorials | SEAWAT / conceptual approach | MAPPED | engine.seawat |
| tutorials | SEAWAT / concentration/temperature | MAPPED | engine.seawat |
| tutorials | SEAWAT / thermal coupling | MAPPED | engine.seawat |
| tutorials | SEAWAT / viscosity/pressure | MAPPED | engine.seawat |
| tutorials | SEAWAT / Goswami/Clement | MAPPED | engine.seawat |
| tutorials | MT3DMS / grid approach | MAPPED | engine.mt3dms |
| tutorials | MT3DMS / conceptual approach | MAPPED | engine.mt3dms |
| tutorials | MT3DMS / advanced transport | MAPPED | engine.mt3dms |
| tutorials | MT3DMS / heat | MAPPED | engine.mt3dms |
| tutorials | MT3D-USGS / Keating | MAPPED | engine.mt3d_usgs |
| tutorials | SEAM3D / BTEX | MAPPED | engine.seam3d |
| tutorials | SEAM3D / chlorinated ethenes | MAPPED | engine.seam3d |
| tutorials | RT3D / aerobic instantaneous | MAPPED | engine.rt3d |
| tutorials | RT3D / BTEX acceptors | MAPPED | engine.rt3d |
| tutorials | RT3D / double Monod | MAPPED | engine.rt3d |
| tutorials | RT3D / rate-limited sorption | MAPPED | engine.rt3d |
| tutorials | RT3D / anaerobic sequence | MAPPED | engine.rt3d |
| tutorials | PHT3D / exchange and surfaces | MAPPED | engine.pht3d |
| tutorials | PHT3D / mineral reactions | MAPPED | engine.pht3d |
| tutorials | HGS / porous medium | MAPPED | engine.hgs |
| tutorials | HGS / surface flow and ET | MAPPED | engine.hgs |
| tutorials | HGS / postprocessing | MAPPED | engine.hgs |
| tutorials | MODAEM / analytic element | MAPPED | engine.modaem |
| tutorials | T-PROGS / transition probabilities | MAPPED | uncertainty.tprogs |
| tutorials | FEMWATER / flow | MAPPED | engine.femwater |
| tutorials | FEMWATER / transport | MAPPED | engine.femwater |
| tutorials | SEEP2D / sheet pile | MAPPED | engine.seep2d |
| tutorials | SEEP2D / dam | MAPPED | engine.seep2d |
| modflow | package table / BAS6 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / BCF6 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / CHD1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / DE4 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / DRN1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / DRT1 | MAPPED | package.classic.drt |
| modflow | package table / EVT1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / ETS1 | MAPPED | package.classic.ets |
| modflow | package table / GAGE | MAPPED | package.classic.gage |
| modflow | package table / GHB1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / GMG | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / HFB1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / HUF | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / LAK3 | MAPPED | package.classic.lak3 |
| modflow | package table / LPF | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / MNW1 | MAPPED | package.classic.mnw1 |
| modflow | package table / MNW2 | MAPPED | package.classic.mnw2 |
| modflow | package table / NWT | MAPPED | engine.modflow.nwt |
| modflow | package table / OUT1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / PCG2 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / PCGN | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / RCH1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / RIV1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / SAMG | MAPPED | solver.samg |
| modflow | package table / SFR2 | MAPPED | package.classic.sfr2 |
| modflow | package table / SIP | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / SOR | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / SUB | MAPPED | package.classic.sub |
| modflow | package table / STR1 | MAPPED | package.classic.str |
| modflow | package table / SWI | MAPPED | package.classic.swi2 |
| modflow | package table / WEL1 | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / UPW | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | package table / UZF1 | MAPPED | package.classic.uzf |
| models | documented family / MODFLOW | MAPPED | engine.modflow.classic |
| models | documented family / USG | MAPPED | engine.modflow.usg |
| models | documented family / NWT | MAPPED | engine.modflow.nwt |
| models | documented family / LGR | MAPPED | engine.modflow.lgr |
| models | documented family / MODPATH | MAPPED | engine.modpath |
| models | documented family / MT3DMS | MAPPED | engine.mt3dms |
| models | documented family / PHT3D | MAPPED | engine.pht3d |
| models | documented family / SEAWAT | MAPPED | engine.seawat |
| models | documented family / RT3D | MAPPED | engine.rt3d |
| models | documented family / SEAM3D | MAPPED | engine.seam3d |
| models | documented family / HGS | MAPPED | engine.hgs |
| models | documented family / MODAEM | MAPPED | engine.modaem |
| models | documented family / SEEP2D | MAPPED | engine.seep2d |
| models | documented family / FEMWATER | MAPPED | engine.femwater |
| models | documented family / FEFLOW | MAPPED | geometry.feflow |
| models | documented family / TOUGH2 | MAPPED | geometry.tough2 |
| models | documented family / PEST | MAPPED | calibration.pest |
| models | documented family / ZONEBUDGET | MAPPED | analysis.zonebudget |
| models | documented family / SAMG | MAPPED | solver.samg |
| models | documented family / T-PROGS | MAPPED | uncertainty.tprogs |
| transport | documented family / MODPATH | MAPPED | engine.modpath |
| transport | documented family / MT3DMS | MAPPED | engine.mt3dms |
| transport | documented family / PHT3D | MAPPED | engine.pht3d |
| transport | documented family / SEAWAT | MAPPED | engine.seawat |
| transport | documented family / RT3D | MAPPED | engine.rt3d |
| transport | documented family / SEAM3D | MAPPED | engine.seam3d |
| introduction | photorealistic rendering | UNMAPPED_OPEN | Unmapped / OPEN |
| introduction | general animation movie export | UNMAPPED_OPEN | Unmapped / OPEN |
| introduction | GIS geodatabase input | UNMAPPED_OPEN | Unmapped / OPEN |
| introduction | spreadsheet and delimited import wizard | UNMAPPED_OPEN | Unmapped / OPEN |
| introduction | geophysical borehole attributes | UNMAPPED_OPEN | Unmapped / OPEN |
| introduction | natural-neighbor interpolation | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | GIS geodatabase writing | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | shapefile writing | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | Arc Hydro Groundwater integration | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | real calendar transient schedule | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | transient input interpolation | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | Latin-hypercube flow sampling | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | Gaussian spatial-field sampling | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | capture-zone risk wizard | UNMAPPED_OPEN | Unmapped / OPEN |
| modflow | lighting/specularity | UNMAPPED_OPEN | Unmapped / OPEN |
| pricing | Clough-Tocher interpolation | UNMAPPED_OPEN | Unmapped / OPEN |
| pricing | natural-neighbor interpolation | UNMAPPED_OPEN | Unmapped / OPEN |
| pricing | fence diagrams | UNMAPPED_OPEN | Unmapped / OPEN |
| pricing | finite-element mesh editing outside horizon workflow | UNMAPPED_OPEN | Unmapped / OPEN |
| pricing | transient movie encoding/view animation | UNMAPPED_OPEN | Unmapped / OPEN |
| pricing | grid import/edit/view | MAPPED | grid.structured_creation, grid.direct_cell_data |
| pricing | conceptual objects | MAPPED | conceptual.coverages |
| pricing | online maps | MAPPED | gis.online_background |
| pricing | GIS input | MAPPED | gis.shapefile_read |
| pricing | CAD imagery DEM | MAPPED | gis.cad_import, gis.georeferenced_images, raster.import_properties |
| pricing | annotations | MAPPED | presentation.annotation_objects |
| pricing | MF6 | MAPPED | engine.modflow6.flow |
| pricing | USGT | MAPPED | engine.modflow.usg_transport |
| pricing | mod-PATH3DU | MAPPED | engine.modpath3du |
| pricing | MT3D-USGS | MAPPED | engine.mt3d_usgs |
| pricing | SAMG plus CLN | MAPPED | solver.samg |
| pricing | edition restrictions | MAPPED | licensing.edition_matrix, licensing.community_limits |

Review each UNMAPPED_OPEN item against its primary tutorial/page and create separately versioned catalogue contracts; preserve this source snapshot and the genuine REA ledger unchanged. Repeat source reconciliation on official version/page changes.

## Primary source index

- [GMS introduction](https://aquaveo.com/software/gms/introduction) (consulted 2026-10-19): Conceptual/grid approaches, spatial inputs, 3D viewing, subsurface characterization. Current page identifies GMS 10.9 requirements; statements are documentation, not runtime evidence.
- [MODFLOW modeling with GMS](https://aquaveo.com/software/gms/models-utilities/modflow) (consulted 2026-10-19): Documented MODFLOW versions/packages, structured/unstructured grids, calibration, native import and GIS integration. This page mixes current and historical GMS 10.0 wording. It does not establish every feature in every edition or version.
- [Transport modeling with GMS](https://aquaveo.com/software/gms/transport) (consulted 2026-10-19): Documented particle, conservative/reactive, variable-density and multicomponent model families. Listed integrations are distinct solvers; a bounded MF6 GWT implementation does not implement the other transport engines.
- [GMS supported models and utilities](https://aquaveo.com/software/gms/models-utilities) (consulted 2026-10-19): Official groundwater/transport model and utility families. Model listing establishes documented support, not entitlement, a new implemented adapter or observed numerical behavior.
- [GMS 10.9 editions and pricing](https://aquaveo.com/software/gms/pricing) (consulted 2026-10-19): Edition-dependent interfaces and documented core/model tools. Edition availability and restrictions require authorized entitlement. Documentation is not a license probe; no price value is replicated.
- [GMS 10.9 tutorials](https://aquaveo.com/software/gms/learning-tutorials) (consulted 2026-10-19): Official index anchors the pre-existing 163-entry selected catalogue and its per-feature tutorial locators. The 163 analytical entries are a partial decomposition, not an official feature total or exhaustive inventory.

## Reproduce this status

```bash
python -m basinlens_ccs.reconstruction.status validate
python -m basinlens_ccs.reconstruction.status report --format markdown
```

Validation checks source-catalogue identity, every catalogue ID, evidence bytes, executed test/source bindings, and comparison gates.
The source catalogue and genuine REA obligation ledger are not modified by this registry.
Hashes detect changes; they do not independently authenticate vendor execution or test operators.

## Updating evidence after code changes

Changing a referenced source or test intentionally invalidates its old test claim, even if its file hash is refreshed.
First run the affected implementation tests with actual required dependencies/solver and retain a strict runner receipt.
A bootstrap receipt uses `basinlens-feature-tests-v1`, preserving explicit selected modules, unselected modules and full_suite=false.
The historical complete-suite schema `basinlens-ci-real-mf6-tests-v1` is also accepted, as standalone tests.json or the retained public-CI wrapper.
It must contain every executed test ID, matching source SHA256 bindings, a passed result and zero skips/errors/failures/discovery issues.
A targeted pre-integration receipt executes affected implementation tests before this accounting suite is run; it lists only the tests it actually ran and is never full CI.
For example: `MF6_EXE=/absolute/path/to/mf6 PYTHONPATH=src python tools/update_gms_status.py run --test-module test_subsurface --output docs/gms/feature_test_record_v3.json`.
Add that receipt as new EXECUTED_TEST_RECORD evidence; update the changed SOURCE/TEST_FILE identities and the affected rows' execution_record_ref.
Then validate this registry and run the full regression suite. Preserve older records as historical evidence rather than relabeling them as a newer run.
New exchange-package or geological-workflow modules remain pending here until their implementation and execution records are integrated.
