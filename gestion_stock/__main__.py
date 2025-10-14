"""Point d'entrée du module ``gestion_stock``.

Ce module est conçu pour fonctionner aussi bien avec
``python -m gestion_stock`` qu'avec un appel direct
``python gestion_stock/__main__.py``. Dans ce second cas, Python
considère le fichier comme un script isolé et interdit l'import relatif
``from . import main``. Nous détectons ce scénario et ajoutons la racine
du projet au ``sys.path`` pour récupérer la fonction
``gestion_stock.main``.
"""

from __future__ import annotations

import os
import sys


if __package__ in {None, ""}:  # Exécution en tant que script direct.
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    from gestion_stock import main  # type: ignore import-not-found
else:  # Exécution via ``python -m gestion_stock``.
    from . import main


if __name__ == "__main__":  # pragma: no cover - point d'entrée standard
    raise SystemExit(main())
