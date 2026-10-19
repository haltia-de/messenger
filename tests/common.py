# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""Loads haltia-messenger (a script without .py) as a module, with HOME in a fresh
temporary directory so nothing of the real account is touched."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "haltia-messenger")
sys.path.insert(0, HERE)


def load():
    home = os.environ["HOME"] = tempfile.mkdtemp(prefix="haltia-messenger-test-")
    # the program finds its folders by GLib's XDG dirs: these go in there too
    for var, sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                     ("XDG_CACHE_HOME", ".cache")):
        os.environ[var] = os.path.join(home, sub)
    loader = importlib.machinery.SourceFileLoader("haltia_messenger", SCRIPT)
    spec = importlib.util.spec_from_loader("haltia_messenger", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def ok(what):
    print("%s ok" % what, flush=True)
