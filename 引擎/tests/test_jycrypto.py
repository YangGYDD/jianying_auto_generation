# -*- coding: utf-8 -*-
import os
import sys
import unittest


ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

from jycrypto import JianyingCrypto  # noqa: E402


class PlaintextDraftTests(unittest.TestCase):
    def test_plaintext_json_does_not_call_dll_decrypt(self):
        crypto = JianyingCrypto.__new__(JianyingCrypto)

        result = crypto.decrypt(b'\xef\xbb\xbf{"tracks":[]}')

        self.assertEqual(result, b'{"tracks":[]}')


if __name__ == "__main__":
    unittest.main()
