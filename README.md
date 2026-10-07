# Atelier — des sources au livre

Application personnelle en français pour transformer un fonds documentaire en idées sourcées et en plan de livre.

## Accès demandé : port réseau, routage géré par l'utilisateur

Le service est lancé en arrière-plan sur **0.0.0.0:8765**, accessible sur cet ordinateur à **http://192.168.0.40:8765**. Mot de passe dans `Acces-local.txt` (fichier privé, non versionné). Les réglages de cette machine sont dans `.local-config.json`, également privé. Le serveur utilise Waitress, une base persistante et un coffre chiffré pour les clés API. Le lancement se fait avec `Lancer-Atelier.ps1` ou `python atelier/run_local.py`. Le PC doit rester allumé ; relancer le script après un redémarrage Windows.

Le routage extérieur reste à configurer par l'utilisateur. Destination : **192.168.0.40**, port **TCP 8765**, protocole applicatif **HTTP**. Un proxy peut terminer HTTPS et conserver l'en-tête Host. L'application accepte le nom d'hôte choisi pour ce routage, tout en exigeant une origine identique pour les formulaires et un mot de passe pour les données.

L'ajout de la règle de pare-feu a échoué faute de droits administrateur. Si le port n'est pas déjà autorisé, lancer **Ouvrir-Port-8765.ps1** dans PowerShell en administrateur. La requête vers l'adresse LAN, la connexion, le refus sans mot de passe et le chargement des données ont été vérifiés depuis ce PC ; aucune vérification depuis une machine extérieure n'a été effectuée.

Les fichiers Docker/Dokploy ci-dessous restent une alternative d'hébergement, non utilisée pour ce lancement.

## État du fonds analysé

- 269 vidéos YouTube de **Line Borrajo** : 113 vidéos et 156 Shorts.
- 69 transcriptions disponibles ; 347 956 mots selon l'inventaire existant.
- 200 transcriptions manquantes : 198 collectes à reprendre après limitation YouTube, 2 sans sous-titres.
- 18 idées importées de l'analyse pilote existante, portant sur trois vidéos. Elles ne constituent pas une analyse exhaustive des 69 textes.
- Métadonnées, liens, langues, horodatages et chapitres de descriptions conservés.
- Les fichiers d'origine du répertoire `outputs` restent inchangés.

## Fonctionnalités

- Bibliothèque : recherche SQLite FTS5 dans les titres, auteurs, tags et textes ; plusieurs mots dans un ordre différent, recherche sans accents et préfixes ; extraits classés par pertinence, ouverture directe du passage (timecode, page ou section) ; tri ; filtres par auteur, format, disponibilité, statut, tag et dossier ; favoris.
- Lecture : lecteur YouTube intégré, liens directs de secours, segments horodatés, sélection de passages, notes, tags, avancement et chapitres manuels.
- Idées : citations issues des vrais segments, plusieurs références conservées, classement, favoris, relecture, notes de contexte et limites.
- Rapprochements : similarité lexicale TF-IDF entre idées et tags, regroupement dans des dossiers. Il ne s'agit pas d'embeddings ni d'une validation sémantique ; les formulations différentes peuvent être manquées.
- Plusieurs projets de livres indépendants : intention, lecteur, voix, sélection de sources, plan, manuscrit et historique propres à chacun ; bibliothèque commune réutilisable.
- Accompagnement éditorial : parcours Intention → Matière → Plan → Écriture ; proposition de plan, brouillon de chapitre sourcé et relecture des lacunes/contradictions via le modèle configuré. Les propositions sont conservées et leurs éléments sont cochés avant ajout au manuscrit. Aucun remplacement automatique du texte existant.
- Éditeur mobile : copie de secours des brouillons dans IndexedDB par livre, récupération après fermeture ou coupure et reprise de l’enregistrement au retour du réseau ; chapitres et blocs réordonnables, texte, intertitres, citations, photos/schémas et sauts de page ; enregistrement automatique, conflits entre appareils détectés, versions datées avec ajouts/retraits et retour à une version antérieure.
- Médiathèque visuelle commune aux projets : import multiple de photos et schémas, réutilisation dans les chapitres, variantes de première et quatrième de couverture avec choix de la version publiée.
- Lecture par pages : balayage horizontal avec une page qui suit le doigt, défilement horizontal au pavé tactile, boutons et clavier ; balayage vers le haut ou défilement vers le haut pour ouvrir les chapitres et leurs pages cliquables ; retour en place pour les gestes courts, respect de la réduction des animations et taille de caractères réglable ; export PDF A5 illustré, EPUB et Markdown avec références.
- Les couvertures sélectionnées sont intégrées au PDF et à l’EPUB ; la première de couverture est déclarée comme couverture officielle dans le fichier EPUB.
- Sources complémentaires : YouTube, photos (dont HEIC), schémas, PDF, EPUB sans DRM, DOCX, ODT, TXT/Markdown et texte collé. Import multiple, 30 Mo par fichier. Les originaux sont conservés ; les formats non reconnus restent téléchargeables comme pièces jointes.
- PDF : extraction du texte et visualisation page par page ; les PDF numérisés nécessitent un texte ajouté manuellement (pas d’OCR). EPUB : extraction du texte et des images, lecture paginée. Les pages des PDF et les sections des livres accompagnent les références.
- IA : API compatible Chat Completions, modèles actualisables par `/models`, endpoint configurable, DeepSeek Flash/Pro proposés. Analyse par blocs avec idées, synthèses, tags et chapitres à relire. Les citations sont reconstruites à partir des indices de segments valides ; les indices inventés sont rejetés. Les prompts de chaque tâche (analyse, réécriture, chapitres, plan et rédaction, assistant) sont modifiables depuis les paramètres, leur contrat technique restant en lecture seule. Une proposition de chapitres peut être demandée seule, sans relancer l’analyse : elle s’appuie sur la version éditoriale quand elle existe, et ne repropose pas les chapitres déjà acceptés.
- Stockage SQLite côté serveur ; export JSON conservé via `/api/backup`. **Réglages → Sauvegardes** permet de télécharger et restaurer une archive ZIP contenant les livres, versions, sources, annotations, idées, conversations, prompts personnalisés et tous les originaux/aperçus de la médiathèque. Le mot de passe, les sessions, jetons et clés API sont exclus de cette archive et restent ceux de l’installation courante.

## Essayer sur cet ordinateur

Depuis `D:\BooksProject` :

```powershell
python atelier/run_local.py
```

Ouvrir `http://127.0.0.1:8765`. Le script `Lancer-Atelier.ps1` ouvre aussi le site et démarre Python en arrière-plan. Python 3.11 ou supérieur. Sans variables de production, le serveur écoute uniquement sur la boucle locale et la clé API est conservée en mémoire pour la session.

Les sous-titres d’une vidéo sont d’abord demandés à YouTube par l’API habituelle ; si elle est refusée (quota, blocage), l’import bascule sur `yt-dlp`, installé avec les dépendances. Quand les deux échouent, la vidéo est conservée sans texte et un bouton **Relancer la récupération** apparaît sur sa fiche, à côté de « Ajouter le texte ».

Mise à jour d’une copie locale : `git pull` dans le dossier de l’application, puis relancer `run_local.py` — le serveur recharge le code au démarrage.

## Déployer sur Dokploy

Le dossier `atelier` est autonome : `corpus/sources.json` et `corpus/ideas.json` contiennent le fonds initial portable, sans clé ni notes personnelles. Pour régénérer ce fonds depuis `outputs` : `python atelier/prepare_corpus.py`.

1. Utiliser une nouvelle application **Compose** dans Dokploy, séparée de Narrv. Fournir ce dossier comme contexte de construction et `docker-compose.yml` comme fichier Compose. Si le dépôt contient tout BooksProject, définir le chemin du Compose sur `atelier/docker-compose.yml`.
2. Configurer dans Dokploy les variables ci-dessous. Ne pas les committer dans Git :
   - `APP_URL` : l'adresse HTTPS définitive de ce nouvel atelier.
   - `ADMIN_PASSWORD` : mot de passe personnel d'au moins 16 caractères.
   - `ATELIER_ENCRYPTION_KEY` : clé de chiffrement de 32 octets encodée en base64 URL-safe. Générer avec `python -c "import secrets; print(secrets.token_urlsafe(32))"` et conserver une copie privée durable.
   - `DEEPSEEK_API_KEY` : facultatif, peut aussi être saisi dans l'interface. Le secret saisi dans le site est chiffré avec la clé précédente et persisté dans SQLite.
3. Dans les domaines Dokploy, choisir le nouveau domaine, le service **atelier**, le port interne **8765** et activer HTTPS. Faire pointer le DNS vers le serveur existant selon votre configuration.
4. Déployer. Le volume `atelier_data` conserve la base lors des redéploiements. Ne pas supprimer ce volume. Le conteneur ne publie aucun port directement sur Internet ; l'accès passe par le proxy Dokploy.
5. Vérifier depuis un appareil extérieur : écran de connexion, bibliothèque inaccessible sans session, import du fonds, sauvegarde d'une note et persistance après reconnexion.

Le démarrage en écoute externe échoue si le mot de passe, HTTPS ou la clé de chiffrement manquent. Les cookies de session sont HttpOnly, SameSite=Strict et Secure en HTTPS. Les sessions expirent après 7 jours. Dix échecs de connexion bloquent les nouvelles tentatives pendant cinq minutes. C'est un espace personnel à mot de passe unique, pas une application multiutilisateur.

Pour les sauvegardes quotidiennes, utiliser **Réglages → Sauvegardes → Télécharger la sauvegarde complète**. Archive limitée à 256 Mo et contenu décompressé à 512 Mo ; au-delà, sauvegarder le volume avec une copie cohérente de SQLite (API backup SQLite ou arrêt temporaire du conteneur avant copie). Conserver aussi `ATELIER_ENCRYPTION_KEY` séparément ; sa perte rend la clé IA enregistrée illisible. Le changement du mot de passe doit s'accompagner de la suppression des sessions dans la base si toutes les connexions doivent être révoquées.

## API pour agents et automatisations

L’Atelier expose une API REST versionnée sur `/api/v1`. La page publique `/api` explique l’authentification et les opérations disponibles ; `/api/openapi.json` fournit le schéma OpenAPI 3.1 directement exploitable par un agent, et `/api/llms.txt` donne un point d’entrée textuel court.

### Serveur MCP (`mcp/`)

Le dossier `mcp/` contient un serveur MCP autonome (transport stdio, bibliothèque standard
uniquement) qui donne à un agent les mêmes moyens que l’interface : recherche de passages
horodatés dans toutes les transcriptions, lecture d’une source ou d’une idée, classement des
idées et des sources (tags, statut, favori, archivage réversible), et écriture du livre
(intention, chapitres, paragraphes sourcés). Aucun outil de suppression n’est exposé.

Le serveur se configure par variables d’environnement (`ATELIER_BASE`, `ATELIER_TOKEN` ou
`ATELIER_TOKEN_FILE`, `ATELIER_MAX_CHARS`) : le jeton n’est jamais transmis par le client MCP.
Pour vérifier sans client : `python3 mcp/atelier_mcp.py --selftest`. Détails et exemple de
configuration dans `mcp/README.md`.

Créer un jeton depuis **Paramètres → Accès API**. Le secret complet n’est affiché qu’une seule fois et seule son empreinte SHA-256 est conservée dans SQLite. L’administration affiche son nom, son préfixe, sa date de création, sa dernière utilisation et le nombre d’appels. La suppression révoque immédiatement l’accès.

### Rattraper une transcription manquée (`backfill_sous_titres.py`)

L’import d’une vidéo YouTube passe par une bibliothèque de sous-titres que la plateforme limite
parfois : la source reste alors sans texte, avec le statut « Texte non récupéré », alors que la
vidéo a des sous-titres. `backfill_sous_titres.py` refait le travail autrement (yt-dlp), puis écrit
la transcription dans la source existante via un `PATCH /api/v1/sources/<id>` — la source, ses
annotations et ses idées sont conservées.

```bash
python3 backfill_sous_titres.py --liste        # ce qui serait traité, sans rien écrire
python3 backfill_sous_titres.py --limite 10    # traite 10 sources, reprend ensuite où il s'est arrêté
```

Les sources archivées sont ignorées par défaut (`--avec-archives` pour les inclure) et l’état est
conservé dans `backfill-etat.json` : un échec définitif (« YouTube ne propose aucune piste ») n’est
pas retenté, alors qu’un refus temporaire (HTTP 429) l’est. Même configuration que le serveur MCP
(`ATELIER_BASE`, `ATELIER_TOKEN` ou `ATELIER_TOKEN_FILE`).

Chaque appel protégé utilise l’en-tête suivant :

```http
Authorization: Bearer atelier_VOTRE_JETON
```

Les ressources couvertes sont les sources et vidéos, les transcriptions (JSON structuré ou texte horodaté), les annotations, les idées sourcées, les dossiers, les projets de livre, les rapprochements et les analyses IA. Les listes prennent `limit` et `offset`; la recherche plein texte des sources utilise `q`. Un fichier jusqu’à 30 Mo peut être envoyé en binaire à `/api/v1/uploads`, et une vidéo YouTube peut être ajoutée par `/api/v1/sources/youtube`.

## IA : configuration et limites

Dans **Paramètres → Connexion au modèle**, choisir explicitement DeepSeek, OpenAI (GPT), Anthropic (Claude), Mistral, OpenRouter ou une API personnalisée compatible OpenAI. Chaque changement de fournisseur exige la clé API correspondante. Le bouton **Charger les modèles** interroge ensuite le compte du fournisseur et remplit une vraie liste déroulante. Les clés de fournisseur sont distinctes des jetons créés dans **Accès API**, qui servent aux agents pour appeler l’Atelier lui-même.

La clé fournisseur active est masquée après enregistrement et peut être remplacée ou effacée. Un jeton Atelier complet n’est affiché qu’à sa création ; s’il est perdu, le supprimer puis en générer un nouveau.

L’API officielle DeepSeek consultée le 27/09/2026 indique `deepseek-flash` (DeepSeek-V4.1-Flash) et `deepseek-v4-pro`. La liste obtenue avec la clé du compte doit primer : https://api-docs.deepseek.com/quick_start/pricing/ et https://api-docs.deepseek.com/api/list-models/.

Les analyses n'ont pas été exécutées avec une vraie clé : l'extraction a été testée avec une réponse simulée pour contrôler la provenance et les indices. Une analyse envoie les textes sélectionnés au fournisseur et consomme éventuellement des crédits. Un lot contient au plus 20 sources, traité séquentiellement. Les résultats d'une source sont sauvegardés lorsque son analyse complète réussit. Après un redémarrage, les travaux interrompus sont signalés et doivent être relancés ; aucune reprise automatique susceptible de facturer des appels supplémentaires.

La synchronisation relit les fichiers locaux `outputs` lorsqu’ils existent. Dans le conteneur autonome, elle réimporte uniquement le fonds embarqué manquant. L’ajout par lien YouTube recherche les métadonnées et les sous-titres disponibles. Une restriction YouTube peut empêcher cette récupération : le lien est conservé, avec la possibilité de coller une transcription. Les vidéos sont lues via YouTube, pas téléchargées.

L’accompagnateur utilise jusqu’à 60 sources choisies par livre et une sélection bornée de passages (environ 60 000 caractères, jusqu’à 12 passages par source), classés par correspondance lexicale avec le sujet et le chapitre. Il ne lit pas exhaustivement tout le fonds. Les documents sans texte sont signalés. Les références inexistantes sont rejetées ; la justesse de la paraphrase et la fiabilité des sources restent à vérifier par l’auteur. Les tests de génération utilisent une réponse simulée, sans appel facturé.

Pour commencer : ouvrir **Livre**, créer ou choisir un projet, remplir **Intention**, sélectionner **Matière**, puis demander un **Plan accompagné**. Choisir ensuite un chapitre et utiliser **Écriture accompagnée** pour préparer un brouillon ou relire. La dernière proposition reste accessible ; les précédentes figurent dans l’historique. Le travail manuel reste disponible sans clé IA.

Le site nécessite une connexion au serveur pour charger les écrans. Un livre déjà ouvert conserve ses modifications dans une copie locale IndexedDB et tente de les enregistrer au retour du réseau. Au prochain accès au livre, un brouillon non enregistré est proposé à la récupération. Une version serveur plus récente déclenche le parcours de conflit ; elle n’est jamais remplacée silencieusement. Une copie locale n’est pas une sauvegarde indépendante : effacer les données du navigateur l’efface aussi.

La restauration ZIP demande de sélectionner l’archive, vérifier ses nombres de livres/sources/fichiers, puis cocher le remplacement. Elle est réservée à une session de l’interface (aucun accès par jeton agent), attend l’arrêt des travaux en cours et conserve une archive de l’état précédent dans `data/backups/avant-restauration-….zip`, téléchargeable à la fin. Les vérifications de schéma et d’intégrité précèdent l’écriture ; les données sont remplacées dans une transaction SQLite. Les anciens fichiers de médias restent sur disque. Les révisions de livres sont renouvelées pour détecter les appareils ouverts sur l’ancienne version. Les archives de sécurité ne sont pas purgées automatiquement.

L’export JSON historique contient les métadonnées des fichiers, pas leurs contenus binaires, et n’est pas un format de restauration. Pour une copie complète de l’installation incluant sa configuration privée, conserver séparément une copie cohérente de `data/atelier.sqlite`, `data/media` et la clé de chiffrement.

## Éditer pendant la lecture

Dans **Mon livre**, les modes **Écrire**, **Lire** et **Relire** donnent accès au manuscrit, à la lecture paginée et aux notes de relecture. Les commandes de couverture, médias, export, mise en page et historique sont regroupées dans **Outils du livre**.

Pendant la lecture, touchez un paragraphe puis **Modifier**. Un panneau latéral s’ouvre sur ordinateur ; sur téléphone, il occupe l’écran. Le paragraphe entier est éditable, même s’il s’étend sur plusieurs pages, avec le contexte précédent et suivant. **Enregistrer et reprendre la lecture** retrouve ce passage après la nouvelle pagination. Les corrections et les notes utilisent les mêmes brouillons locaux, versions et protections contre les conflits que l’éditeur.

**À revoir / Note** ajoute une note au passage et place le chapitre dans l’état **À revoir**. **Relire** affiche les notes, permet de retrouver leur passage et de les marquer comme terminées. Les notes restent conservées si leur passage est retiré. **Sources** consulte les références associées sans quitter la lecture. Le sommaire affiche les pages, le statut et une commande pour éditer le chapitre. Les statuts disponibles sont **Brouillon**, **À revoir** et **Terminé**.

La dernière position de lecture est mémorisée pour chaque livre sur ce navigateur, par chapitre, bloc et position dans le texte ; elle est conservée lors des changements de taille de caractères et d’écran. Sur téléphone, **Sélectionner du texte** permet la sélection native ; **Reprendre les gestes** réactive le changement de page par balayage. Les flèches et le sommaire restent disponibles dans les deux cas.

## Vérifications

```powershell
$env:PYTHONPATH='D:\BooksProject\atelier\.runtime;D:\BooksProject\atelier'
python -m unittest discover -s atelier -p 'test_*.py' -v
node --check atelier/public/app.js
node --check atelier/public/studio.js
node --check atelier/public/editorial.js
node --check atelier/public/author.js
```

Le parcours de lecture est aussi vérifié dans un vrai navigateur avec une base temporaire : `node atelier/tests/reader-author.cjs` (Playwright et son Chromium doivent être installés). Il couvre les écrans ordinateur et téléphone, les sources, l’édition, les notes, la reprise après pagination, les statuts, la panne réseau et le conflit entre sessions.

Installer `requirements.txt` avant les tests pour vérifier aussi le coffre chiffré. Le déploiement utilise Waitress ; le serveur HTTP de développement est réservé à l'aperçu local.

Les tests utilisent une base temporaire : authentification et déconnexion, limitation des essais, protection des origines, annotations persistantes, import d'un second auteur, export sourcé, validation des citations, coffre chiffré, absence de secrets dans les exports, transport WSGI et réponse IA simulée. Le build Docker doit être exécuté sur une machine disposant de Docker ; il n'a pas été exécuté sur cet ordinateur lors de la création.

## Modifier le mot de passe

Dans **Réglages → Mot de passe de l’atelier**, saisir le mot de passe actuel, puis le nouveau deux fois (6 à 256 caractères, sans règle de composition). Toutes les sessions sont déconnectées après validation. Le nouveau mot de passe est enregistré uniquement sous forme d’empreinte scrypt salée dans la base SQLite, hors export JSON, et prime sur le mot de passe initial de `.local-config.json` au redémarrage. Le fichier `Acces-local.txt` contient uniquement le mot de passe initial et ne sera plus à jour après ce changement.
