#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
# Run the tests: sh tests/run.sh [test_backend.py test_window.py ...]
# The first run makes .cache/venv (the system's PyGObject, plus the PyMax
# wheel install.sh pins, by the same name and sha256, and haltia-kit 2.2.0,
# or HALTIA_KIT=path/to/a/checkout); the window tests get
# a display of their own from broadwayd, stopped again at the end.
# HALTIA_SHOTS=dir keeps screenshots of the window there. HALTIA_PYTHON=python3
# runs them on that Python as it is, with no venv (an installed package's
# dependencies: the deb's check).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
top=$(dirname "$here")
cache=${HALTIA_CACHE:-$top/.cache}
venv=$cache/venv
whl=$(sed -n 's/^whl=//p' "$top/install.sh")
sum=$(sed -n 's/^echo "\([0-9a-f]\{64\}\) .*/\1/p' "$top/install.sh")

python=${HALTIA_PYTHON:-$venv/bin/python}
if [ -n "${HALTIA_PYTHON:-}" ]; then
	:
elif [ ! -x "$venv/bin/python" ]; then
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

# The kit, Haltia's shared library (a dependency of this one).
if [ -z "${HALTIA_PYTHON:-}" ] && ! "$venv/bin/python" -c "import haltia_kit.vault" 2>/dev/null; then
	compat=${HALTIA_KIT:-git+https://github.com/haltia-de/kit@v2.2.0}
	if command -v uv >/dev/null; then
		VIRTUAL_ENV=$venv uv pip install -q "$compat"
	else
		"$venv/bin/pip" install -q "$compat"
	fi
fi

# A display for GTK: the first free broadway one from :50, a new one for
# each test (a broadwayd takes no second program after the first is gone).
run=${XDG_RUNTIME_DIR:-/tmp}
bw=
display() {
	if [ -n "$bw" ]; then kill "$bw" 2>/dev/null || true; wait "$bw" 2>/dev/null || true; fi
	n=50
	while [ -e "$run/broadway$((n + 1)).socket" ]; do n=$((n + 1)); done
	broadwayd ":$n" >/dev/null 2>&1 &
	bw=$!
	i=0
	while [ ! -e "$run/broadway$((n + 1)).socket" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
}

[ $# -gt 0 ] || set -- test_chatlist.py test_media.py test_backend.py test_window.py test_login.py
cd "$here"
log=$(mktemp)
trap 'kill $bw 2>/dev/null; rm -f "$log"' EXIT INT TERM
for t in "$@"; do
	echo "== $t"
	display
	status=0
	GDK_BACKEND=broadway BROADWAY_DISPLAY=":$n" "$python" "$t" >"$log" 2>&1 || status=$?
	grep -v -e 'Gtk-WARNING' -e 'Gtk-CRITICAL' -e '^$' "$log" || true  # GTK's noise
	[ $status -eq 0 ] || { echo "FAILED: $t"; exit $status; }
done
echo "all passed"
