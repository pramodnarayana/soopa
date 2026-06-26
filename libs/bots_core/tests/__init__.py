# -*- coding: utf-8 -*-

import unittest



def run_unitests():
    """Return unittest test suite to run
    """
    loader = unittest.TestLoader()
    test_suite = loader.discover('.', pattern='uniturl.py')
    # test_suite = loader.discover('.', pattern='unit*.py')
    return test_suite



class BotsTestCase(unittest.TestCase):
    pass
