"""Executa testes em base temporária; nunca reutiliza COLLECTOR_DATA operacional."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
root=Path(__file__).resolve().parents[1];os.chdir(root);sys.path.insert(0,str(root))
with tempfile.TemporaryDirectory(prefix='iphan-test-runner-') as temporary:
    os.environ['COLLECTOR_DATA']=temporary
    suite=unittest.defaultTestLoader.discover(str(root/'tests'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
