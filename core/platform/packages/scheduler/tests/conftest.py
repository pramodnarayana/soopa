import os
import sys

# Add the package root to sys.path so 'tests.fakes' resolves correctly
package_root = os.path.dirname(os.path.dirname(__file__))
if package_root not in sys.path:
    sys.path.insert(0, package_root)
