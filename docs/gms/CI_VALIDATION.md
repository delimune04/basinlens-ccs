# Required real-engine CI

The `groundwater` job in [ci.yml](../../.github/workflows/ci.yml) runs the full
suite with actual MF6, FloPy, h5py, Streamlit and Plotly. It fails on any skip,
loader error, missing/duplicate test ID, incomplete execution, expected failure
or test failure. Lightweight Python 3.10/3.12 matrix jobs still cover the base
package independently and may skip optional dependencies.

The job uses Ubuntu 24.04/Python 3.12 and pins its six direct numerical/UI
requirements to the locally validated versions. Transitive packages, actual
Python/platform/runner identity and `pip freeze` are recorded. This is not an
immutable operating-system image or a complete transitive lock.

## Exact public solver content

The explicitly invoked [CI helper](../../tools/ci_real_mf6.py) downloads the
[official executables 29.0 Linux asset](https://github.com/MODFLOW-ORG/executables/releases/tag/29.0),
extracts only its literal `mf6` member and verifies size, SHA256 and version
before test discovery and again after execution.

| Item | Accepted identity |
|---|---|
| Official asset | `linux.zip`, GitHub asset 430362036 |
| Archive size | 45,010,855 bytes |
| Archive SHA256 | `ab17192a3531dec61d4f4eab3da10f618e85d1f792d5edc71306a3e06e0e22c3` |
| MF6 size | 49,182,760 bytes |
| MF6 SHA256 | `479185be33167701696604f7bb55acb4f96476f396e9bb015cbe7da52e278ec4` |
| Actual version output | `mf6: 6.7.0 02/05/2026` |

The release is not marked immutable by GitHub. Exact content checks reject a
replacement at the versioned URL. Release prose lists 6.6.3; the verified binary
itself identifies 6.7.0. The job records that discrepancy instead of assigning a
binary version from release prose. The Linux x86-64 pin is CI-specific; normal
application run/export never downloads a solver.

## Evidence and local reproduction

Every run retains `solver.json`, `tests.json`, a dedicated `tests.log` and
`pip-freeze.txt` as GitHub artifacts for 14 days. Test evidence includes discovered
IDs, source hashes, checkout/GitHub identity, versions, errors and skip reasons.
Preparation failure and a runner that never started are separately recorded;
`not_run` is not a passed check. These execute repository tests and public USGS
physics; they do not run original GMS or establish product/field equivalence.

On Linux x86-64, install the exact direct dependencies from the workflow, then
use a fresh solver directory:

```bash
export MF6_EXE="$PWD/build/ci-mf6-bin/mf6"
export CI_SOLVER_REPORT="$PWD/build/ci-real-mf6"
python tools/ci_real_mf6.py prepare
python tools/ci_real_mf6.py test
```

The new strict runner passed 265/265 locally with zero skips/failures/errors in
47.560s. The local receipt describes working-tree base 872e6be and exact source
hashes matching candidate 77f0cedc; it is not a public CI result. Public run
identities and outcomes are recorded separately after execution.
