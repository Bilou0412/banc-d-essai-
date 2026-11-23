#!/bin/bash
cd /home/claude/banc-d-essai-
python3 outils/boucle.py lot --it 6 --lot A && echo "ETAPE lot it6 fini" && python3 outils/boucle.py analyser --it 6 --lot A && echo "ETAPE it6 finie" || echo "ERREUR it6"
