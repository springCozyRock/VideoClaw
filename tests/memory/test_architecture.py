import ast
import importlib
from pathlib import Path
import unittest

class ArchitectureTests(unittest.TestCase):
    def test_no_legacy_or_forwarding_modules(self):
        import memory
        root=Path(memory.__file__).parent
        for name in ('legacy','plugin','core','controller.py','store.py','service.py'):
            self.assertFalse((root/name).exists(), name)
        self.assertFalse(hasattr(memory, 'LegacyMemoryPlugin'))

    def test_active_domains_do_not_import_legacy_or_host_sdk(self):
        import memory
        root=Path(memory.__file__).parent
        for directory in ('runtime','world','narrative','harness','contracts'):
            for p in (root/directory).rglob('*.py'):
                for node in ast.walk(ast.parse(p.read_text())):
                    if isinstance(node,ast.ImportFrom):
                        module=node.module or ''
                        self.assertFalse(module.startswith(('memory.legacy','memory.adapters','core.agents','models.')),str(p)+': '+module)
    def test_sqlite_store_does_not_inherit_legacy_json_store(self):
        from memory.assets.store import MemoryStore
        self.assertEqual(MemoryStore.__bases__,(object,))
