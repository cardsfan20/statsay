import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "toy-game"

sys.path.insert(0, str(ROOT / "scripts"))
