# atelier-mcp — serveur MCP pour l'Atelier

Expose l'Atelier (« des sources au livre ») à n'importe quel client MCP : Hermes,
Claude Desktop, un agent maison. Un seul fichier, aucune dépendance : `python3` et un
jeton API Atelier suffisent.

## Ce que ça donne

18 outils, tous en français, documentés dans le protocole :

| Lire | Trier / classer | Rédiger |
|---|---|---|
| `etat_bibliotheque` — vue d'ensemble | `modifier_idees` — tags, statut, favori, archivage (200 max) | `definir_intention` — brief du livre |
| `chercher_sources` — titres, auteurs, formats | `modifier_sources` — tags, favori, archivage | `creer_dossier` |
| `chercher_passages` — **recherche dans toutes les transcriptions**, passages horodatés | `creer_idee` — idée sourcée | `ajouter_chapitre` |
| `lire_source` — transcription (+ filtre mot-clé), synthèse IA | `rapprochements` — idées proches | `ajouter_texte_chapitre` — paragraphe sourcé |
| `lister_idees`, `lire_idee`, `lister_tags`, `lister_livres`, `lire_livre`, `exporter_livre` | | |

Usage typique côté LLM : `chercher_passages("combien facturer un audit")` → passages
horodatés et sourcés → réponse **citée** (auteur, titre, horodatage) ; `modifier_idees`
pour trier une pile en masse ; `ajouter_texte_chapitre` pour rédiger avec appui sur les sources.

## Configuration

Le jeton se crée dans **Atelier → Paramètres → Accès API** et ne sert qu'ici : il n'est
jamais passé par le client MCP, ni journalisé.

| Variable | Défaut | Rôle |
|---|---|---|
| `ATELIER_BASE` | `http://127.0.0.1:8765` | URL de l'Atelier |
| `ATELIER_FALLBACK_BASE` | — | seconde URL essayée si la première est injoignable |
| `ATELIER_TOKEN` | — | jeton `atelier_…` |
| `ATELIER_TOKEN_FILE` | `atelier-token.txt` à côté du script | fichier contenant le jeton |
| `ATELIER_MAX_CHARS` | `40000` | taille maximale d'une réponse d'outil |

`atelier-token.txt` est ignoré par git : y déposer le jeton avec `chmod 600`.

## Brancher sur Hermes

```yaml
mcp_servers:
  atelier:
    command: "python3"
    args: ["/chemin/vers/mcp/atelier_mcp.py"]
    env:
      ATELIER_BASE: "http://127.0.0.1:8765"
      ATELIER_TOKEN_FILE: "/chemin/vers/atelier-token.txt"
    timeout: 180
```

Redémarrer l'agent : les serveurs MCP sont lus au démarrage, sans rechargement à chaud.
Les outils apparaissent en `mcp_atelier_*`. Le même fichier de configuration se décline
pour tout autre client MCP (stdio, commande `python3 atelier_mcp.py`).

## Vérifier sans client MCP

```bash
python3 atelier_mcp.py --selftest   # interroge la vraie API, ne modifie rien
python3 atelier_mcp.py --tools      # liste les outils, sans réseau

# test complet avec le SDK officiel (nécessite pip install mcp)
python3 test_mcp_client.py chercher_passages '{"q": "budget client"}'
```

Le serveur écrit son journal sur **stderr** (jamais sur stdout, réservé au protocole).

## Notes de conception

- **`chercher_passages` ne dépend pas de la recherche plein texte de l'API** : celle-ci filtre
  par sous-chaîne de la requête entière, donc une question en langage naturel ne renverrait
  rien. Ici, chaque mot-clé (≥ 4 lettres, accents ignorés) interroge `/api/v1/sources?q=`,
  les sources candidates sont classées par nombre de mots trouvés, puis la fenêtre de
  segments autour de chaque occurrence est renvoyée avec son horodatage.
- **Écriture prudente** : aucun outil de suppression. Le tri passe par `archived` (réversible
  en un appel) et par les tags. Les écritures de livre relisent la révision juste avant
  l'enregistrement (sinon l'API refuse en conflit) et ajoutent des blocs, jamais en
  remplacement.
- Le serveur n'appelle le réseau qu'au moment d'un outil : son démarrage reste instantané,
  ce qui compte pour la découverte des outils par le client.
