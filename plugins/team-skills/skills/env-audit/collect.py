import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from envaudit.core.cli import main


sys.exit(main(sys.argv[1:]))
