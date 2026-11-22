# Adaptateur du green Bilel (V5)

Le code de Bilel est pris **tel quel** : `buildforge-server`, branche `dev` de BuildForge, commit `7785634`
(worktree en lecture seule, rien n'y est modifié). L'adaptateur fabrique un `Document` à partir des pages
(`pdftotext` pour les RC publics, texte du générateur pour les synthétiques) et appelle `dce::facts::extract`.

    CARGO_TARGET_DIR=/home/user/v5work/target cargo build --release
    EXTRACTOR_URL=http://127.0.0.1:8080 green-bilel < '{"pages": [...]}'

Le serveur llama.cpp : `llama-server -m NuExtract3-Q4_K_M.gguf --ctx-size 8192 --threads 4 --jinja -np 1`
(sha256 du modèle : 7ee3c0ee9e5699a4391624ae758487f583f73b3242aa4e73dc2bb33e508d703e ; llama.cpp tag b11723 comme en production,
compilé sur place, interface web remplacée par des fichiers vides).
La référence B de H23 (sonnet) passe par `outils/v5/shim_sonnet.py`, un faux serveur llama.cpp : même pipeline, même vérification.
