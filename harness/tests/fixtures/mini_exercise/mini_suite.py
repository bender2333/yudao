import unittest
from mini import add

class MiniTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
