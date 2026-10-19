# Public Aquaveo component reuse

Research snapshot: 2026-10-19. Aquaveo publishes BSD-2-Clause source for
[xmsinterp](https://github.com/Aquaveo/xmsinterp) and
[xmsgrid](https://github.com/Aquaveo/xmsgrid). Reusing an appropriate public
component remains preferable to inferring a proprietary implementation when its
behavior, version and deployment are suitable. No component was installed,
built, wrapped or counted as implemented during this investigation.

The [official package index](https://public.aquapi.aquaveo.com/aquaveo/stable)
listed the following distributions at the investigation snapshot:

| Component | Latest listed version | Latest listed Linux version | Listed interpreter |
|---|---:|---:|---|
| xmsinterp | 7.0.12, Windows | 6.1.10 | CPython 3.10 |
| xmsgrid | 9.1.1, Windows | 7.9.1 | CPython 3.10 |

The complete wheel listings contained no CPython 3.12 build suitable for the
Linux runtime used here. PyPI's similarly named official packages were older
3.0.1 distributions for Python 3.6 Windows. Actual requests to the official index
and a selected Linux wheel URL returned HTTP 503 in this session; cached web
metadata is not proof of a downloaded or runnable wheel. Wheel contents, hashes
and native dependency compatibility therefore remain unverified.

The current public source uses C++/Conan/CMake and other XMS components; its
build automation is not an independently reproduced build here. The official
[build instructions](https://github.com/Aquaveo/xmscore/wiki/Building-Libraries)
are the next reproducible starting point in a compatible environment.

An eventual adapter must pin its actual source/package hash and license,
reproduce installation, and pass independent linear-plane and direct IDW
arithmetic checks before being advertised. The same library name does not
establish that the investigated GMS binary uses that exact build or settings,
nor that the whole GMS workbench is reconstructed.
