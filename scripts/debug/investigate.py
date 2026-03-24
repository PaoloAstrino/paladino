#!/usr/bin/env python
"""
Paladino Terminal Investigator - Interactive REPL for Graph Intelligence.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

# Configure logger for cleaner output
logger.remove()
logger.add(sys.stderr, level="ERROR")


from rich.theme import Theme

# Custom theme for Paladino
paladin_theme = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "brand": "bold magenta",
        "highlight": "bold yellow",
    }
)

PALADIN_BANNER = r"""
          ______  _______  _        _______  ______  _________ _        _______ 
         (  __  \(  ___  )( \      (  ___  )(  __  \ \__   __/( (    /|(  ___  )
         | (  \  )| (   ) || (      | (   ) || (  \  )   ) (   |  \  ( || (   ) |
         | |   ) || (___) || |      | (___) || |   ) |   | |   |   \ | || |   | |
         | |   | ||  ___  || |      |  ___  || |   | |   | |   | (\ \) || |   | |
         | |   ) || (   ) || |      | (   ) || |   ) |   | |   | | \   || |   | |
         | (__/  )| )   ( || (____/\| )   ( || (__/  )___) (___| )  \  || (___) |
         (______/ |/     \|(_______/|/     \|(______/ \_______/|/    )_)(_______)
                                                                                  
                                 [ JUSTICE & DATA ]
                                        
                  ,                                     ,
                 / \                                   / \
                |   |                                 |   |
                |   |                                 |   |
               /_____\                               /_____\
              | o   o |           [ KNIGHT ]        | o   o |
              |  ___  |                             |  ___  |
               \_____/               OF              \_____/
                |   |             NEO4J               |   |
               /|   |\                               /|   |\
              / |   | \                             / |   | \
             /  |___|  \                           /  |___|  \
            /   /   \   \                         /   /   \   \
           /___/     \___\                       /___/     \___\
"""

from paladino.app.investigator import InvestigativeREPL


def main():
    """Main entry point."""
    repl = InvestigativeREPL()
    repl.run()


if __name__ == "__main__":
    main()
    """Main entry point."""
    repl = InvestigativeREPL()
    repl.run()


if __name__ == "__main__":
    main()
