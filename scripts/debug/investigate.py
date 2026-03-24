#!/usr/bin/env python
"""
Paladino Terminal Investigator - Interactive REPL for Graph Intelligence.
"""

import sys
from pathlib import Path
from typing import Optional, Dict, List
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from paladino.db import get_driver, Neo4jConnection
from paladino.app.graphrag_agent import GraphRAGAgent
from paladino.schema_manager import SchemaManager

# Configure logger for cleaner output
logger.remove()
logger.add(sys.stderr, level="ERROR")


from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.status import Status
from rich.theme import Theme
from rich import box

# Custom theme for Paladino
paladin_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "brand": "bold magenta",
    "highlight": "bold yellow"
})

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
