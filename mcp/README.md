# atelier-mcp — serveur MCP pour l'Atelier

Expose l'Atelier (« des sources au livre ») à n'importe quel client MCP : Hermes,
Claude Desktop, un agent maison. Un seul fichier, aucune dépendance : `python3` et un
jeton API Atelier suffisent.

## Ce que ça donne

57 outils, tous en français, documentés dans le protocole.

### Lire

| Outil | Ce qu'il donne |
|---|---|
| `etat_bibliotheque` | vue d'ensemble : sources, idées, tags, travaux en cours |
| `chercher_sources` | titres, auteurs, formats ; filtres favoris / archivées |
| `chercher_passages` | **recherche dans toutes les transcriptions**, passages horodatés |
| `lire_source` | transcription (filtre mot-clé), synthèse IA, tags proposés |
| `lister_idees` / `lire_idee` | idées sourcées : notes, tags, importance, citations |
| `rapprochements` | paires d'idées proches (à fusionner) |
| `lister_tags` | tags posés sur les sources, avec leur nombre |
| `lister_livres` / `lire_livre` | projets de livre : intention, chapitres, état de rédaction |
| `lire_chapitre` | le **texte** d'un chapitre, entier ou page par page (pagination explicite) |
| `matieres_livre` | sources rattachées au projet, et celles citées dans les chapitres sans l'être |
| `historique_livre` | versions datées d'un livre |
| `exporter_livre` | le livre en Markdown (manuscrit ; les sources restent dans l'atelier) |
| `verifier_export_livre` | l'export se génère bien (markdown, PDF ou EPUB) : taille du fichier produit |
| `suivre_redaction` | état d'une préparation éditoriale et, si elle est prête, la proposition complète avec ses indices |
| `lire_version_livre` | détail d'une version d'un livre : diff mot à mot de chaque changement |
| `lister_fichiers` | médias de l'atelier : images (couvertures possibles) et documents |
| `lire_reglages` / `lire_prompts_ia` / `lister_modeles_ia` | connexion IA, prompts des missions, modèles disponibles |

### Classer et corriger la bibliothèque

| Outil | Ce qu'il change |
|---|---|
| `creer_idee` / `supprimer_idee` | ajoute une idée sourcée, retire une idée (sources intactes) |
| `modifier_idees` | tags, statut, favori, archivage en masse (200 max) |
| `modifier_sources` | tags, favori, archivage en masse |
| `annoter_source` | tags d'une source — **valide aussi les tags proposés par l'IA** —, favori, dossier, notes |
| `ajouter_source` / `modifier_source` / `supprimer_source` | texte collé, correction, suppression (refusée si une idée s'appuie dessus) |
| `importer_youtube` | vidéo : transcription récupérée en arrière-plan |
| `ecrire_transcription` / `supprimer_transcription` / `rafraichir_transcription` | corriger, retirer ou relancer une transcription |
| `creer_dossier` / `renommer_dossier` / `supprimer_dossier` | ranger la bibliothèque (le contenu du dossier survit à sa suppression) |
| `synchroniser_bibliotheque` | importe le corpus local — n'écrase aucune source existante |

### Écrire et réviser le livre

| Outil | Ce qu'il fait |
|---|---|
| `definir_intention` | brief du livre : à qui il parle, ce qu'il promet |
| `ajouter_sources_livre` / `retirer_sources_livre` | rattache ou détache les sources du projet (onglet « Matière », 60 max) |
| `creer_livre` / `supprimer_livre` | nouveau projet (`book-main` protégé) ; suppression **définitive** sur confirmation |
| `ajouter_chapitre` / `ajouter_texte_chapitre` | plan, puis paragraphes sourcés |
| `renommer_chapitre` / `deplacer_chapitre` / `supprimer_chapitre` | titre et objectif, ordre, retrait (confirmation si le chapitre contient du texte) |
| `remplacer_texte_chapitre` | réécrit un chapitre au lieu d'empiler des paragraphes |
| `restaurer_version_livre` | revient à une version datée (la version remplacée reste dans l'historique) |
| `analyser_sources` | analyse IA de 1 à 20 sources (idées + tags) — **coût annoncé, confirmation exigée** |
| `proposer_chapitres` | plan de chapitres proposé par l'IA pour une source — **confirmation exigée** |
| `lancer_redaction` / `appliquer_proposition` | plan, brouillon de chapitre ou relecture critique par l'accompagnateur — **coût annoncé, confirmation exigée** — puis intégration au manuscrit des seuls éléments retenus |
| `reecrire_transcription` | transcription condensée en prose éditoriale sourcée — **confirmation exigée** |
| `definir_prompt_ia` / `regler_connexion_ia` | personnaliser un prompt de mission, régler modèle, adresse et instruction (la clé API ne passe jamais par le MCP) |
| `definir_couverture_livre` | première et quatrième de couverture, choisies parmi les images de l'atelier |

Deux principes ont guidé ce lot. D'abord la **symétrie** : un LLM qui n'a que « ajouter » crée des
doublons au lieu de corriger, et remplit la bibliothèque sans jamais pouvoir la ranger — chaque
création a donc désormais son pendant (modifier, déplacer, supprimer). Ensuite la **protection** :
`supprimer_chapitre` refuse un chapitre qui contient du texte sans `force=true`,
`supprimer_source` refuse tant qu'une idée s'appuie dessus (sauf `force=true`, qui nettoie les
références), `supprimer_livre` protège `book-main` et exige une confirmation dès qu'il contient du
texte, et les deux outils qui consomment des crédits IA refusent de partir sans `confirme=true`.
Chaque écriture de livre passe par `PATCH /api/v1/books/{id}`, qui enregistre une version datée
dans l'historique : une suppression reste récupérable par `restaurer_version_livre`.

Usage typique côté LLM : `chercher_passages("combien facturer un audit")` → passages
horodatés et sourcés → réponse **citée** (auteur, titre, horodatage) ; `modifier_idees`
pour trier une pile en masse ; `ajouter_texte_chapitre` pour rédiger avec appui sur les sources ;
`importer_youtube` puis `analyser_sources` pour transformer une vidéo fraîche en idées sourcées ;
`annoter_source` pour valider les tags proposés par l'IA ; `historique_livre` puis
`restaurer_version_livre` pour revenir sur une réécriture malheureuse.

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

## Mode HTTP — pour un client distant (ChatGPT, Claude web…)

Un client qui ne peut pas lancer de process local a besoin d'une **URL HTTPS publique** parlant
Streamable HTTP. Même fichier, même outils :

```bash
MCP_HTTP_TOKEN=<jeton-que-le-client-présentera> \
ATELIER_BASE=https://atelier.example.org \
ATELIER_TOKEN=<jeton-api> \
python3 atelier_mcp.py --http          # écoute sur 0.0.0.0:8080/mcp
```

| Variable | Défaut | Rôle |
|---|---|---|
| `MCP_HTTP_TOKEN` | — | jeton Bearer exigé (vide = serveur **ouvert**, à ne jamais exposer) |
| `MCP_HTTP_PORT` | `8080` | port d'écoute |
| `MCP_HTTP_HOST` | `0.0.0.0` | interface d'écoute |
| `MCP_READ_ONLY` | — | `1` : n'expose que les 21 outils de consultation |

Routes : `POST /mcp` (JSON-RPC ; réponse JSON, ou SSE si le client envoie
`Accept: text/event-stream`), `GET /health` (sans authentification, pour le proxy).
Toute requête sans jeton valide reçoit `401`.

Le jeton du client distant est **distinct** du jeton API Atelier : il se révoque en changeant
la variable, alors que le jeton Atelier ne quitte jamais le serveur.

### Docker

```bash
cd mcp
export ATELIER_BASE=https://atelier.example.org \
       ATELIER_TOKEN=atelier_xxx \
       MCP_HTTP_TOKEN=un-secret-long
docker compose up -d --build          # → http://localhost:8080/mcp
curl -s localhost:8080/health         # {"status": "ok", "outils": 57, ...}
```

Placer un **reverse proxy TLS** devant (Traefik, Caddy, nginx) : sans lui, les requêtes et le
jeton circulent en clair. Si le proxy tourne dans un autre conteneur, partager un réseau Docker
commun (voir le bloc commenté dans `docker-compose.yml`).

### ChatGPT

ChatGPT ne se connecte qu'à des serveurs **distants en HTTPS**, et uniquement sur les offres
payantes, dans le navigateur (pas l'application mobile). Réglages → **Applications /
Connecteurs** → mode développeur → créer une app avec l'URL `https://…/mcp` et l'authentification
**OAuth**. L'interface n'offre que « OAuth » ou « aucune authentification » : il n'existe pas de
champ pour un en-tête de clé. ChatGPT découvre alors les métadonnées publiées par le serveur,
s'enregistre tout seul, ouvre la page `/authorize` **dans votre navigateur** — vous y saisissez
`MCP_HTTP_TOKEN` pour consentir — puis échange le code contre un jeton d'accès (PKCE). Le serveur
doit donc être joignable depuis Internet : tunnel sortant (Cloudflare Tunnel, ngrok) ou machine
publique, plus le proxy TLS ci-dessus.

### OAuth 2.1 (connecteurs hébergés)

Le serveur fait aussi office de serveur d'autorisation : aucune dépendance, tout tient dans ce
fichier. Ce qu'il publie :

| Route | Rôle |
|---|---|
| `GET /.well-known/oauth-protected-resource` | métadonnées de la ressource (RFC 9728), visées par l'en-tête `WWW-Authenticate` du `401` |
| `GET /.well-known/oauth-authorization-server` | métadonnées du serveur d'autorisation (RFC 8414) |
| `POST /register` | enregistrement dynamique du client (RFC 7591) |
| `GET /authorize` | page de consentement : le jeton du serveur y est demandé |
| `POST /token` | code + PKCE `S256`, ou `refresh_token` (rotation à chaque usage) |

Le jeton Bearer statique `MCP_HTTP_TOKEN` reste accepté en parallèle : Claude, le CLI et les
clients qui savent poser un en-tête ne changent rien. Un jeton d'accès vit trente jours, un
refresh cent vingt ; l'état est écrit dans `MCP_OAUTH_STORE` (sur un volume en conteneur) pour
survivre à un redéploiement. Un code d'autorisation n'est consommé qu'à l'échange réussi : un
`code_verifier` erroné peut être réessayé.

| Variable | Défaut | Rôle |
|---|---|---|
| `MCP_OAUTH_STORE` | `oauth-store.json` à côté du script | clients enregistrés, codes et jetons émis |
| `MCP_PUBLIC_URL` | déduite de `Host` / `X-Forwarded-Host` | URL publique annoncée (derrière un proxy) |
| `MCP_OAUTH_ACCESS_TTL` | `2592000` (30 jours) | durée de vie d'un jeton d'accès |
| `MCP_OAUTH_REFRESH_TTL` | `10368000` (120 jours) | durée de vie d'un refresh |

Révoquer tous les accès OAuth : vider la clé `tokens` de `MCP_OAUTH_STORE` puis redémarrer ; le
jeton statique, lui, se change en modifiant `MCP_HTTP_TOKEN`.

## Déploiement (Dokploy)

Service Compose créé depuis ce dépôt :

| Réglage | Valeur |
|---|---|
| Dépôt / branche | ce dépôt, branche `main` |
| Chemin du compose | `./mcp/docker-compose.yml` |
| Port du domaine | `8080`, TLS par le resolver du reverse proxy |
| Variables d'environnement | `ATELIER_BASE`, `ATELIER_TOKEN`, `MCP_HTTP_TOKEN` |

**Piège du webhook** : l'URL de déploiement fournie par le panneau contient le *refresh token*
du service (`/api/deploy/compose/<refresh-token>`), pas son identifiant — un webhook GitHub
pointant sur `/api/deploy/compose/<composeId>` reçoit `404 Compose Not Found`. Le webhook doit
être déclaré sur l'événement `push` ; avec un vrai payload de push il répond
`Compose deployed successfully`.

## Vérifier sans client MCP

```bash
python3 atelier_mcp.py --selftest   # interroge la vraie API, ne modifie rien
python3 atelier_mcp.py --tools      # liste les outils, sans réseau

# test complet avec le SDK officiel (nécessite pip install mcp)
python3 test_mcp_client.py chercher_passages '{"q": "budget client"}'
```

Le serveur écrit son journal sur **stderr** (jamais sur stdout, réservé au protocole).

## Notes de conception

**Lire un manuscrit ne se fait jamais en un seul appel.** Un livre plein dépasse 200 Ko quand une réponse
d'outil est plafonnée (`ATELIER_MAX_CHARS`, 40 000 par défaut) : renvoyer « le livre entier » ne donnait
qu'un texte amputé et personne ne le savait. `lire_livre` est donc devenu un **plan** (chapitres, tailles,
sources, intention) et `lire_chapitre` sert le texte, page par page, avec un `suite` à repasser en `depuis`
— `suite=null` signifie « chapitre lu en entier ». Même logique pour `lire_source` (transcriptions longues)
et `lire_version_livre`. Règle : aucun outil de lecture ne coupe en silence ; quand il reste quelque chose,
la réponse dit où reprendre.

**Pilotage complet, sauf les secrets.** Tout ce que fait l'Atelier est accessible par l'API, et donc par
le MCP : bibliothèque, idées, dossiers, livre, chapitres, matières, accompagnement éditorial, transcription,
prompts et modèles. Trois choses restent volontairement hors du protocole, parce qu'elles ne se délèguent pas
à un modèle : la **clé API** (elle se saisit dans l'Atelier ; `regler_connexion_ia` règle le reste sans jamais
la transporter), la **gestion des jetons d'accès** et le **mot de passe** de l'application.

- **`chercher_passages` ne dépend pas de la recherche plein texte de l'API** : celle-ci filtre
  par sous-chaîne de la requête entière, donc une question en langage naturel ne renverrait
  rien. Ici, chaque mot-clé (≥ 4 lettres, accents ignorés) interroge `/api/v1/sources?q=`,
  les sources candidates sont classées par nombre de mots trouvés, puis la fenêtre de
  segments autour de chaque occurrence est renvoyée avec son horodatage.
- **Suppressions protégées, jamais aveugles** : `supprimer_chapitre`, `supprimer_source`,
  `supprimer_livre` et `supprimer_idee` existent parce qu'un LLM qui ne sait que créer laisse une
  bibliothèque ingérable. Chacune refuse le geste dangereux (chapitre plein, source citée par une
  idée, livre non vide) tant que l'appelant n'a pas confirmé explicitement, et propose l'alternative
  douce (archiver, sortir du dossier). Le tri courant passe toujours par `archived` et les tags,
  qui sont réversibles en un appel.
- **Ce qui consomme des crédits se demande** : `analyser_sources` et `proposer_chapitres` renvoient
  d'abord un devis (`confirmation_requise`, nombre de sources) et ne partent qu'avec
  `confirme=true` — l'agent doit donc annoncer le coût à l'utilisateur avant de l'engager.
- **Écriture prudente côté livre** : les outils relisent la révision juste avant l'enregistrement
  (sinon l'API refuse en conflit), ajoutent des blocs par défaut, et `remplacer_texte_chapitre`
  remplace au lieu d'empiler. Toute écriture crée une version datée : `restaurer_version_livre`
  permet de revenir en arrière.
- Le serveur n'appelle le réseau qu'au moment d'un outil : son démarrage reste instantané,
  ce qui compte pour la découverte des outils par le client.
