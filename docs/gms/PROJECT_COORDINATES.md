# Shared project coordinates

Shared project rows increase with local Y; native structured MODFLOW rows increase
toward decreasing Y. The legacy adapter previously described these opposite
directions as a translation. Mapping schema version 2 corrects that metadata:

```
project_x = origin_x + native_x
project_y = origin_y + nrow * delc - native_y
```

The shared origin is the outer lower-X, lower-Y corner, not the native first-row
cell centre. This legacy adapter retains cell indices and reflects local Y.
`subsurface.coordinates` validates this contract and maps actual native cell
centres. An asymmetric 3-row/5-column export/reload test checks all cells at a
nonzero origin. The native solver deck, array order and numerical values are
unchanged by this metadata correction. No CRS, datum, rotation or unit
transformation is performed.

Historical schema-1 receipts describe their historical source; they are not
silently upgraded. Re-export from the project using the current source to create
a fresh corrected receipt. Existing files are never overwritten.

The separate spatial model workflow uses a different, explicit mapping: it
reverses native row indices for every property, initial head and boundary, and
reverses result arrays back. Native and project physical XY then agree. Its
`row_mapping` receipt identifies that contract. Do not interchange the two
adapters' array mappings.

These are local-coordinate software checks. They establish neither survey
placement nor agreement with an original GMS session.
