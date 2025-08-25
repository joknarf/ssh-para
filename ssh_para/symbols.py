import os

SYMBOL_END = os.environ.get("SSHP_SYM_BEG") or "\ue0b4"  # 
SYMBOL_BEGIN = os.environ.get("SSHP_SYM_END") or "\ue0b6"  # 
SYMBOL_PROG = os.environ.get("SSHP_SYM_PROG") or "\u25a0"  # ■
SYMBOL_RES = os.environ.get("SSHP_SYM_RES") or "\u25ba"  # b6 ▶
