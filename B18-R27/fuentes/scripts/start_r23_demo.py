"""Start the fresh R23 fictional presentation on loopback."""
import sys
from scripts.start_r22_demo import main

if __name__ == '__main__':
    if '--name' not in sys.argv:
        sys.argv.extend(['--name','presentacion-R23'])
    main()
