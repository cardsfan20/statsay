import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "toy-game"
RPGMAKER = ROOT / "fixtures" / "rpgmaker-mz"

sys.path.insert(0, str(ROOT / "scripts"))
