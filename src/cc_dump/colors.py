"""Terminal color constants."""

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"

# Foreground
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[97m"

# Background
BG_RED = "\033[41m"
BG_GREEN = "\033[42m"
BG_YELLOW = "\033[43m"
BG_BLUE = "\033[44m"
BG_MAGENTA = "\033[45m"
BG_CYAN = "\033[46m"
BG_WHITE = "\033[47m"

# Tag color palette: light foreground on dark background of same hue
TAG_COLORS = [
    (CYAN, BG_BLUE),
    (GREEN, BG_GREEN + BLACK),
    (YELLOW, BG_YELLOW + BLACK),
    (MAGENTA, BG_MAGENTA),
    (RED, BG_RED),
    (BLUE, BG_BLUE + WHITE),
    (WHITE, BG_WHITE + BLACK),
    (CYAN, BG_CYAN + BLACK),
]

SEPARATOR = DIM + "\u2500" * 70 + RESET
THIN_SEP = DIM + "\u2504" * 40 + RESET
