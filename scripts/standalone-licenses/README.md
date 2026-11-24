# Vendored license texts for the standalone GUI

The pinned `pyside6-essentials==6.12.0` and `shiboken6==6.12.0` wheels declare
`License: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` in their metadata but
do not ship the license texts themselves. The same license choice applies to
the bundled Qt 6 native libraries and Wayland plugins.

`scripts/standalone_sidecars.py` therefore emits these canonical SPDX license
texts into `dist/THIRD-PARTY-NOTICES.txt` and fails the build if any file here
is missing. The texts are the unmodified SPDX license list files from
`/usr/share/licenses/spdx/` (Fedora `license-files` package):

| File | SHA-256 |
| --- | --- |
| `GPL-2.0-only.txt` | `aaf135472f81c5b4a0dca9367e5bb5e9750032b5bebe5442b36e4c0a47430df3` |
| `GPL-3.0-only.txt` | `fb981668c18a279e285fc4d83fba1e836cc84dd4daa73c9697d3cfd2d8aca6e0` |
| `LGPL-3.0-only.txt` | `996af0513df21f7496288951c41428a03c174e9e4a9d63665c57d670f845ccb1` |

Including these texts does not by itself authorize redistribution; the
distribution terms remain those of the upstream projects.
