# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
"""Release versions and bilingual notes agree across package metadata."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parent.parent
news = (root / "NEWS.md").read_text()
latest = re.search(r"^## ([0-9.]+) \((\d{4}-\d{2}-\d{2})\)\n(.*?)(?=^## |\Z)",
                   news, re.M | re.S)
assert latest is not None
version, date, notes = latest.groups()
ru, en = notes.split("### Русский\n", 1)[1].split("### English\n", 1)
release = ET.parse(root / "data/io.github.haltia_de.Messenger.metainfo.xml").find(
    "./releases/release")
assert release.attrib == {"version": version, "date": date}
paragraphs = release.findall("./description/p")
lang = "{http://www.w3.org/XML/1998/namespace}lang"
for language, text in (("ru", ru), (None, en)):
    expected = text.strip().split("\n\n")
    actual = ["".join(p.itertext()) for p in paragraphs if p.get(lang) == language]
    assert actual == expected, (language, actual, expected)

apk = (root / "packaging/alpine/APKBUILD").read_text()
assert re.search(r"^pkgver=(.*)$", apk, re.M)[1] == version
assert re.search(r"^pkgrel=(.*)$", apk, re.M)[1] == "0"
changelog = (root / "debian/changelog").read_text()
assert changelog.startswith(f"haltia-messenger ({version}) unstable;")
print("release versions and bilingual notes ok")
