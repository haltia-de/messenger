#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
# Install haltia-messenger (Сообщения, a client for MAX): sh install.sh [ROOT] [PREFIX]
# ROOT empty or / for this system; PREFIX /usr/local unless given (a
# package passes /usr). It needs Python 3 with PyGObject (GTK 3),
# haltia-kit 2 (github.com/haltia-de/kit) and PyMax's own Python
# packages (pydantic, aiohttp, websockets, …: see packaging/alpine/APKBUILD).
# The .desktop file shows it in any desktop's launcher; the Haltia shell
# puts it on its home screen (X-B8K-Home). An XDG autostart file starts it
# hidden with the session, to receive messages.
set -eu
root=${1:-}
root=${root%/}
prefix=${2:-/usr/local}
here=$(cd "$(dirname "$0")" && pwd)
share=$root$prefix/share
app=io.github.haltia_de.Messenger
old=io.github.trudenboy.Max  # b8k-max before 2.0
install -D -m 644 "$here/data/$app.desktop" "$share/applications/$app.desktop"
install -D -m 644 "$here/data/$app.svg" "$share/icons/hicolor/scalable/apps/$app.svg"
install -D -m 644 "$here/data/$app.metainfo.xml" "$share/metainfo/$app.metainfo.xml"
install -D -m 644 "$here/data/ringtone.wav" "$share/haltia-messenger/ringtone.wav"
install -D -m 644 "$here/data/ringtone.md" "$share/haltia-messenger/ringtone.md"
install -D -m 644 "$here/data/$app.autostart.desktop" "$root/etc/xdg/autostart/$app.desktop"
# The old id's .desktop file, hidden: pins and links to it still start the program.
install -D -m 644 "$here/data/$old.desktop" "$share/applications/$old.desktop"
# PyMax (MIT), MAX's web protocol: the pinned wheel from PyPI, checked
# against its sha256 and unpacked next to the program (PREFIX/lib/haltia-messenger).
# HALTIA_CACHE keeps the download between builds (a package gives its srcdir).
whl=maxapi_python-2.4.1-py3-none-any.whl
cache=${HALTIA_CACHE:-$here/.cache}
mkdir -p "$cache"
[ -f "$cache/$whl" ] || wget -q -O "$cache/$whl" \
	"https://files.pythonhosted.org/packages/py3/m/maxapi-python/$whl"
echo "49c996cebebdcd490b8fc1424c84faad3c33d0b75eff4bb86cf1de9d968d76ea  $cache/$whl" | sha256sum -c -
lib=$root$prefix/lib/haltia-messenger
rm -rf "$lib"
mkdir -p "$lib"
unzip -q -o "$cache/$whl" -d "$lib"
# The program runs from a module, which Python loads compiled (its
# __pycache__, made by the package), while the script Python is started
# with is compiled anew at every start. PREFIX/bin/haltia-messenger is a stub that
# runs the module as __main__ with sys.argv as given: the shell knows the
# program by its command line, python3 PREFIX/bin/haltia-messenger.
install -D -m 644 "$here/haltia-messenger" "$root$prefix/lib/haltia-messenger/haltia_messenger_main.py"
mkdir -p "$root$prefix/bin"
cat > "$root$prefix/bin/haltia-messenger" <<EOF
#!/usr/bin/env python3
# The code is $prefix/lib/haltia-messenger/haltia_messenger_main.py, run from there so that Python loads it compiled.
import runpy
import sys
sys.path.insert(0, "$prefix/lib/haltia-messenger")
runpy.run_module("haltia_messenger_main", run_name="__main__", alter_sys=False)
EOF
chmod 755 "$root$prefix/bin/haltia-messenger"
# The old command, till 3.0.
ln -sf haltia-messenger "$root$prefix/bin/b8k-max"
# What b8k-max (before 2.0) installed under this prefix, and the shell's
# old entry for it from before the .desktop file (a package's old files go
# with the old package).
rm -rf "$root$prefix/lib/b8k-max" \
	"$share/icons/hicolor/scalable/apps/$old.svg" "$share/metainfo/$old.metainfo.xml" \
	"$root/etc/xdg/autostart/$old.desktop" \
	"$root/usr/local/share/b8k/apps.d/max.conf" "$root/usr/local/share/b8k/max.png"
