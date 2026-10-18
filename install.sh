#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
# Install b8k-max (MAX): sh install.sh [ROOT] [PREFIX]
# ROOT empty or / for this system; PREFIX /usr/local unless given (a
# package passes /usr). It needs Python 3 with PyGObject (GTK 3),
# b8k-compat (github.com/trudenboy/b8k-compat) and PyMax's own Python
# packages (pydantic, aiohttp, websockets, …: see packaging/alpine/APKBUILD).
# The .desktop file shows it in any desktop's launcher; the b8k tablet shell
# puts it on its home screen (X-B8K-Home). An XDG autostart file starts it
# hidden with the session, to receive messages.
set -eu
root=${1:-}
root=${root%/}
prefix=${2:-/usr/local}
here=$(cd "$(dirname "$0")" && pwd)
share=$root$prefix/share
app=io.github.trudenboy.Max
install -D -m 755 "$here/b8k-max" "$root$prefix/bin/b8k-max"
install -D -m 644 "$here/data/$app.desktop" "$share/applications/$app.desktop"
install -D -m 644 "$here/data/$app.svg" "$share/icons/hicolor/scalable/apps/$app.svg"
install -D -m 644 "$here/data/$app.metainfo.xml" "$share/metainfo/$app.metainfo.xml"
install -D -m 644 "$here/data/$app.autostart.desktop" "$root/etc/xdg/autostart/$app.desktop"
# PyMax (MIT), MAX's web protocol: the pinned wheel from PyPI, checked
# against its sha256 and unpacked next to the program (PREFIX/lib/b8k-max).
# B8K_CACHE keeps the download between builds (a package gives its srcdir).
whl=maxapi_python-2.4.1-py3-none-any.whl
cache=${B8K_CACHE:-$here/.cache}
mkdir -p "$cache"
[ -f "$cache/$whl" ] || wget -q -O "$cache/$whl" \
	"https://files.pythonhosted.org/packages/py3/m/maxapi-python/$whl"
echo "49c996cebebdcd490b8fc1424c84faad3c33d0b75eff4bb86cf1de9d968d76ea  $cache/$whl" | sha256sum -c -
lib=$root$prefix/lib/b8k-max
rm -rf "$lib"
mkdir -p "$lib"
unzip -q -o "$cache/$whl" -d "$lib"
# The shell's old entry for this program, from before the .desktop file.
rm -f "$root/usr/local/share/b8k/apps.d/max.conf" "$root/usr/local/share/b8k/max.png"
