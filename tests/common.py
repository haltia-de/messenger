# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""Loads b8k-max (a script without .py) as a module, with HOME in a fresh
temporary directory so nothing of the real account is touched."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "b8k-max")
sys.path.insert(0, HERE)


def load():
    os.environ["HOME"] = tempfile.mkdtemp(prefix="b8k-max-test-")
    loader = importlib.machinery.SourceFileLoader("b8k_max", SCRIPT)
    spec = importlib.util.spec_from_loader("b8k_max", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def ok(what):
    print("%s ok" % what, flush=True)
