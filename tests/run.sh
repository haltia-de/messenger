#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
# Run the tests: sh tests/run.sh [test_backend.py test_window.py ...]
# The first run makes .cache/venv (the system's PyGObject, plus the PyMax
# wheel install.sh pins, by the same name and sha256); the window tests get
# a display of their own from broadwayd, stopped again at the end.
# B8K_SHOTS=dir keeps screenshots of the window there.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
top=$(dirname "$here")
cache=${B8K_CACHE:-$top/.cache}
venv=$cache/venv
whl=$(sed -n 's/^whl=//p' "$top/install.sh")
sum=$(sed -n 's/^echo "\([0-9a-f]\{64\}\) .*/\1/p' "$top/install.sh")

if [ ! -x "$venv/bin/python" ]; then
	mkdir -p "$cache"
	[ -f "$cache/$whl" ] || wget -q -O "$cache/$whl" \
		"https://files.pythonhosted.org/packages/py3/m/maxapi-python/$whl"
	echo "$sum  $cache/$whl" | sha256sum -c -
	if command -v uv >/dev/null; then
		uv venv -q -p /usr/bin/python3 --system-site-packages "$venv"
		VIRTUAL_ENV=$venv uv pip install -q "$cache/$whl"
	else
		/usr/bin/python3 -m venv --system-site-packages "$venv"
		"$venv/bin/pip" install -q "$cache/$whl"
	fi
fi

# A display for GTK: the first free broadway one from :50.
n=50
run=${XDG_RUNTIME_DIR:-/tmp}
while [ -e "$run/broadway$((n + 1)).socket" ]; do n=$((n + 1)); done
broadwayd ":$n" >/dev/null 2>&1 &
bw=$!
trap 'kill $bw 2>/dev/null' EXIT INT TERM
i=0
while [ ! -e "$run/broadway$((n + 1)).socket" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i + 1)); done

[ $# -gt 0 ] || set -- test_chatlist.py test_backend.py test_window.py
cd "$here"
log=$(mktemp)
trap 'kill $bw 2>/dev/null; rm -f "$log"' EXIT INT TERM
for t in "$@"; do
	echo "== $t"
	status=0
	GDK_BACKEND=broadway BROADWAY_DISPLAY=":$n" "$venv/bin/python" "$t" >"$log" 2>&1 || status=$?
	grep -v -e 'Gtk-WARNING' -e 'Gtk-CRITICAL' -e '^$' "$log" || true  # GTK's noise
	[ $status -eq 0 ] || { echo "FAILED: $t"; exit $status; }
done
echo "all passed"
