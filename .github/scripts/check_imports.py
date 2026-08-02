#!/usr/bin/env python3
import importlib
import sys

if len(sys.argv) < 2:
    print("Usage: check_imports.py module [module ...]")
    sys.exit(2)

failed = False
for mod in sys.argv[1:]:
    try:
        importlib.import_module(mod)
        print(f"{mod} OK")
    except Exception as e:
        print(f"{mod} import failed: {e}")
        failed = True

if failed:
    sys.exit(1)
else:
    sys.exit(0)
