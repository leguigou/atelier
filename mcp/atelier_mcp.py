#!/usr/bin/env python3
"""Serveur MCP (Model Context Protocol) pour l'Atelier — « des sources au livre ».

Expose la bibliothèque de l'Atelier (sources, transcriptions, idées, dossiers, livres)
à n'importe quel client MCP : Hermes, Claude Desktop, un agent maison…

Transport : JSON-RPC 2.0, protocole MCP. Aucune dépendance hors bibliothèque standard :
il suffit d'un python3 et d'un jeton API Atelier.

Deux transports, même code métier :
  stdio (défaut)  client local qui lance le process (Hermes, Claude Desktop, Cursor…)
  HTTP (--http)   Streamable HTTP pour un client distant (ChatGPT, Claude web…),
                  protégé par un jeton Bearer (MCP_HTTP_TOKEN)

En mode HTTP, le serveur fait aussi office de serveur d'autorisation OAuth 2.1 minimal :
l'interface des connecteurs ChatGPT n'accepte qu'« OAuth » ou « aucune authentification »,
jamais un en-tête de clé. Le jeton Bearer statique reste accepté : les autres clients ne
changent rien. Le consentement se donne sur /authorize, en saisissant le même MCP_HTTP_TOKEN.

Configuration (variables d'environnement) :
  ATELIER_BASE           URL de l'Atelier (défaut : http://127.0.0.1:8765)
  ATELIER_FALLBACK_BASE  seconde URL essayée si la première est injoignable
  ATELIER_TOKEN          jeton API « atelier_… »
  ATELIER_TOKEN_FILE     fichier contenant le jeton (défaut : atelier-token.txt, à côté du script)
  ATELIER_MAX_CHARS      taille maximale d'une réponse d'outil (défaut 40000)
  MCP_HTTP_TOKEN         jeton Bearer exigé en mode HTTP (vide = aucune authentification)
  MCP_HTTP_PORT          port d'écoute en mode HTTP (défaut 8080)
  MCP_READ_ONLY=1        n'expose que les outils de lecture (écriture masquée)
  MCP_OAUTH_STORE        fichier d'état OAuth (défaut : à côté du script ; /data en conteneur)
  MCP_PUBLIC_URL         URL publique du serveur (défaut : déduite de l'en-tête Host)

Lancer : python3 atelier_mcp.py            (mode serveur MCP sur stdin/stdout)
         python3 atelier_mcp.py --http     (mode Streamable HTTP sur /mcp)
         python3 atelier_mcp.py --selftest (vérifie l'API sans client MCP)
         python3 atelier_mcp.py --tools    (liste les outils, sans réseau)
"""
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import log
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
KNOWN_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
SERVER_NAME = "atelier"
SERVER_VERSION = "1.0.0"

DEFAULT_BASE = "http://127.0.0.1:8765"
DEFAULT_TOKEN_FILE = "atelier-token.txt"  # à côté du script
MAX_CHARS = int(os.environ.get("ATELIER_MAX_CHARS", "40000"))
STOPWORDS = set(
    "les des une dans pour avec que qui par sur est sont pas plus cette comme ces aux ses "
    "son leur elle elles ils nous vous mais entre avant avoir faire etre aussi peut tout sans "
    "tres deux trois the and for with that this from".split()
)

HTTP_TOKEN = os.environ.get("MCP_HTTP_TOKEN", "").strip()
HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "8080"))
HTTP_HOST = os.environ.get("MCP_HTTP_HOST", "0.0.0.0")
READ_ONLY = os.environ.get("MCP_READ_ONLY", "").strip().lower() in ("1", "true", "oui", "yes")
# OAuth 2.1 : état des clients, codes et jetons (voir « OAuth » plus bas dans le fichier).
OAUTH_STORE = Path(os.environ.get("MCP_OAUTH_STORE") or Path(__file__).with_name("oauth-store.json"))
OAUTH_PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "").strip().rstrip("/")
OAUTH_ACCESS_TTL = int(os.environ.get("MCP_OAUTH_ACCESS_TTL") or 30 * 24 * 3600)
OAUTH_REFRESH_TTL = int(os.environ.get("MCP_OAUTH_REFRESH_TTL") or 120 * 24 * 3600)
OAUTH_CODE_TTL = 300  # un code d'autorisation vit cinq minutes
# Outils qui modifient la bibliothèque — masqués quand READ_ONLY est actif.
WRITE_TOOLS = frozenset({
    "modifier_idees",
    "modifier_sources",
    "creer_idee",
    "creer_dossier",
    "definir_intention",
    "ajouter_chapitre",
    "ajouter_texte_chapitre",
    "renommer_chapitre",
    "deplacer_chapitre",
    "supprimer_chapitre",
    "remplacer_texte_chapitre",
    "creer_livre",
    "supprimer_livre",
    "ajouter_source",
    "importer_youtube",
    "modifier_source",
    "supprimer_source",
    "annoter_source",
    "ecrire_transcription",
    "supprimer_transcription",
    "rafraichir_transcription",
    "supprimer_idee",
    "renommer_dossier",
    "supprimer_dossier",
    "analyser_sources",
    "proposer_chapitres",
    "synchroniser_bibliotheque",
    "ajouter_sources_livre",
    "retirer_sources_livre",
    "definir_prompt_ia",
    "regler_connexion_ia",
    "lancer_redaction",
    "appliquer_proposition",
    "reecrire_transcription",
    "definir_couverture_livre",
    "restaurer_version_livre",
})


def folded(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(c for c in text if unicodedata.category(c) != "Mn").casefold()


def terms_of(query):
    return [t for t in re.findall(r"[a-zA-Zà-ÿ0-9]{4,}", folded(query)) if t not in STOPWORDS]


def stamp(seconds):
    total = int(float(seconds or 0))
    if total >= 3600:
        return "%02d:%02d:%02d" % (total // 3600, total % 3600 // 60, total % 60)
    return "%02d:%02d" % (total // 60, total % 60)


def clip(text, limit=MAX_CHARS):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… [tronqué : %d caractères sur %d]" % (limit, len(text))


# Une page de lecture reste nettement sous MAX_CHARS : l'enveloppe JSON et les métadonnées comptent aussi.
MAX_PAGE = max(8000, MAX_CHARS // 2)


def page_de(items, depuis, budget=MAX_PAGE, cout=None):
    """Page d'éléments à partir de `depuis`. Renvoie (indices, suite) ; suite vaut None quand tout est passé.

    Aucune coupe muette : quand la page s'arrête avant la fin, l'appelant sait **où reprendre**.
    """
    cout = cout or (lambda x: len(str(x)))
    pris, taille = [], 0
    for indice in range(depuis, len(items)):
        poids = cout(items[indice])
        if pris and taille + poids > budget:
            break
        pris.append(indice)
        taille += poids
    jusqua = depuis + len(pris)
    return pris, (jusqua if jusqua < len(items) else None)


def trouver_chapitre(chapitres, cible):
    """Retrouve un chapitre par identifiant, numéro (1..N) ou titre. Renvoie (chapitre, numéro)."""
    texte = str(cible or "").strip()
    if not texte:
        raise ApiError("chapitre requis : son identifiant, son numéro (1 à %d) ou son titre." % len(chapitres))
    for numero, chapitre in enumerate(chapitres, 1):
        if texte == str(chapitre.get("id")):
            return chapitre, numero
    if texte.isdigit() and 1 <= int(texte) <= len(chapitres):
        return chapitres[int(texte) - 1], int(texte)
    plie, catalogue = folded(texte), []
    exacts = [(n, c) for n, c in enumerate(chapitres, 1) if folded(c.get("title", "")) == plie]
    if len(exacts) == 1:
        return exacts[0][1], exacts[0][0]
    proches = [(n, c) for n, c in enumerate(chapitres, 1) if plie in folded(c.get("title", ""))]
    for candidats in (exacts, proches):
        if len(candidats) == 1:
            return candidats[0][1], candidats[0][0]
        if len(candidats) > 1:
            raise ApiError("Plusieurs chapitres correspondent : %s. Précisez le numéro."
                           % " ; ".join("%d. %s" % (n, c.get("title", "")) for n, c in candidats[:6]))
    catalogue = " ; ".join("%d. %s" % (n, c.get("title", "")) for n, c in enumerate(chapitres, 1))
    raise ApiError("Chapitre introuvable. Chapitres du livre : %s." % catalogue)


class ApiError(RuntimeError):
    pass


class Atelier:
    """Client HTTP minimal de l'API v1 de l'Atelier, avec bascule LAN → WAN."""

    def __init__(self):
        base = os.environ.get("ATELIER_BASE", "").strip().rstrip("/")
        bases = [base or DEFAULT_BASE]
        fallback = os.environ.get("ATELIER_FALLBACK_BASE", "").strip().rstrip("/")
        if fallback and fallback not in bases:
            bases.append(fallback)
        self.bases = bases
        self.token = os.environ.get("ATELIER_TOKEN", "").strip()
        if not self.token:
            configured = os.environ.get("ATELIER_TOKEN_FILE", "").strip()
            path = Path(configured).expanduser() if configured else Path(__file__).resolve().parent / DEFAULT_TOKEN_FILE
            if path.exists():
                self.token = path.read_text(encoding="utf-8").strip()
        self.base = None

    def _fetch(self, method, path, query=None, body=None, base=None):
        url = (base or self.base or self.bases[0]) + path
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if data:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            ctype = response.headers.get("Content-Type", "")
        if ctype.startswith("application/json"):
            return json.loads(raw.decode("utf-8"))
        return raw.decode("utf-8", "replace")

    def call(self, method, path, query=None, body=None, text=False):
        if not self.token:
            raise ApiError("Jeton API Atelier absent : renseignez ATELIER_TOKEN ou ATELIER_TOKEN_FILE.")
        failures = []
        for base in ([self.base] if self.base else self.bases):
            try:
                result = self._fetch(method, path, query=query, body=body, base=base)
                self.base = base
                return result
            except urllib.error.HTTPError as error:
                detail = ""
                try:
                    payload = json.loads(error.read().decode("utf-8", "replace"))
                    detail = payload.get("error") or payload.get("detail") or ""
                except Exception:
                    pass
                if error.code in (401, 403):
                    raise ApiError("Atelier a refusé le jeton (%s). %s" % (error.code, detail)) from None
                raise ApiError("Atelier : HTTP %s. %s" % (error.code, detail)) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                failures.append("%s → %s" % (base, error))
        raise ApiError("Atelier injoignable : " + " ; ".join(failures))


api = Atelier()


# --------------------------------------------------------------------------- lecture

def etat_bibliotheque(_=None):
    out = {}
    total = api.call("GET", "/api/v1/sources", {"limit": 1})
    out["sources"] = total.get("total", 0)
    out["sources_transcrites"] = api.call(
        "GET", "/api/v1/sources", {"limit": 1, "has_transcript": "true"}
    ).get("total", 0)
    out["sources_sans_texte"] = out["sources"] - out["sources_transcrites"]
    idees = api.call("GET", "/api/v1/ideas", {"limit": 1})
    out["idees"] = idees.get("total", 0)
    out["idees_archivees"] = api.call(
        "GET", "/api/v1/ideas", {"limit": 1, "archived": "true"}
    ).get("total", 0)
    out["idees_visibles"] = out["idees"] - out["idees_archivees"]
    out["dossiers"] = [f["name"] for f in api.call("GET", "/api/v1/folders").get("items", [])]
    books = api.call("GET", "/api/v1/books").get("items", [])
    out["livres"] = [dict(id=b["id"], titre=b["title"], chapitres=b["chapters"]) for b in books]
    tags = api.call("GET", "/api/v1/tags").get("items", [])
    out["tags_principaux"] = ["%s (%s)" % (t["name"], t["count"]) for t in tags[:15]]
    out["travaux_ia_en_cours"] = [
        j for j in api.call("GET", "/api/v1/jobs").get("items", [])
        if j.get("status") in ("queued", "running")
    ]
    return out


LINK_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^\s&]*&)*v=|shorts/|embed/|live/)|^)([A-Za-z0-9_-]{11})(?:[?&#/\s]|$)",
    re.IGNORECASE,
)


def youtube_ref(value):
    """Identifiant YouTube contenu dans un lien (ou référence brute), sinon chaîne vide."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = LINK_RE.search(text)
    if match:
        return match.group(1)
    return text if re.fullmatch(r"[A-Za-z0-9_-]{11}", text) else ""


def resolve_source(value):
    """Identifiant Atelier d'une source, depuis un identifiant, un identifiant YouTube ou un lien.

    Nécessaire parce que la recherche de l'API ne parcourt que titre/auteur/transcription : un lien
    collé tel quel ne renvoie rien, alors que c'est la façon la plus naturelle de désigner une vidéo.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:  # identifiant Atelier direct
        api.call("GET", "/api/v1/sources/%s" % text)
        return text
    except ApiError:
        pass
    ref = youtube_ref(text)
    if not ref:
        return ""
    offset, seen = 0, 0  # repli : parcourir le catalogue à la recherche de la vidéo
    while True:
        page = api.call("GET", "/api/v1/sources", {"limit": 200, "offset": offset})
        items = page.get("items") or []
        for source in items:
            if source.get("youtube_id") == ref or ref in str(source.get("url", "")):
                return source["id"]
        seen += len(items)
        if not items or seen >= int(page.get("total") or 0):
            return ""
        offset = seen


def source_item(source):
    """Vue allégée d'une source, telle que renvoyée par les outils de recherche."""
    return dict(
        id=source["id"], titre=source["title"], auteur=source.get("author", ""),
        format=source.get("kind", ""), date=source.get("date", ""),
        duree=stamp(source.get("duration")),
        segments=source.get("segment_count", len(source.get("segments") or [])),
        url=source.get("url", ""), statut=source.get("status", ""),
        tags=(source.get("annotation") or {}).get("tags", []),
        favori=bool((source.get("annotation") or {}).get("liked")),
        archive=bool((source.get("annotation") or {}).get("archived")),
    )


def chercher_sources(args):
    args = args or {}
    query = {"limit": str(min(200, int(args.get("limite") or 25)))}
    if args.get("q"):
        query["q"] = str(args["q"])
    if args.get("format"):
        query["kind"] = str(args["format"])
    if args.get("auteur"):
        query["author"] = str(args["auteur"])
    if args.get("avec_texte") is True:
        query["has_transcript"] = "true"
    if args.get("avec_texte") is False:
        query["has_transcript"] = "false"
    data = api.call("GET", "/api/v1/sources", query)
    items = [source_item(s) for s in data.get("items", [])]
    total = data.get("total", 0)
    if not items and args.get("q"):
        # Lien ou identifiant YouTube collé comme requête : la recherche textuelle ne le voit pas.
        linked = resolve_source(args["q"])
        if linked:
            try:
                items = [source_item(api.call("GET", "/api/v1/sources/%s" % linked))]
                total = 1
            except ApiError:
                pass
    return dict(total=total, renvoye=len(items), sources=items)


def _hit_windows(segments, needles, context=1, per_source=6, strong=None, weights=None):
    """Repère les segments contenant un mot-clé et rend la fenêtre autour.

    ``strong`` limite aux passages qui contiennent au moins un mot discriminant ;
    ``weights`` (idf) classe les passages du plus pertinent au moins pertinent.
    """
    hits = [i for i, seg in enumerate(segments) if any(n in folded(seg.get("text", "")) for n in needles)]
    windows, used = [], set()
    for index in hits:
        start = max(0, index - context)
        end = min(len(segments) - 1, index + context)
        if any(i in used for i in range(start, end + 1)):
            continue
        text = " ".join(s.get("text", "").strip() for s in segments[start:end + 1])
        found = [n for n in needles if n in folded(text)]
        if strong and not set(found) & strong:
            continue
        used.update(range(start, end + 1))
        score = sum(weights.get(n, 1.0) for n in found) if weights else float(len(found))
        windows.append(dict(
            debut=stamp(segments[start].get("start", 0)),
            start=segments[start].get("start", 0),
            page=segments[start].get("page"),
            section=segments[start].get("section"),
            mots=found,
            score=round(score, 3),
            texte=clip(text, 1800),
        ))
    windows.sort(key=lambda w: (-w["score"], w["start"]))
    return windows[:per_source]


def chercher_passages(args):
    args = args or {}
    question = str(args.get("q") or "").strip()
    if not question:
        raise ApiError("Donnez une question ou des mots-clés (champ q).")
    needles = terms_of(question) or [folded(question)]
    limite = max(1, min(20, int(args.get("limite") or 6)))
    sources_max = max(1, min(30, int(args.get("sources_max") or 12)))
    transcription_total = api.call(
        "GET", "/api/v1/sources", {"limit": 1, "has_transcript": "true"}).get("total", 0)
    # Une vidéo désignée par son lien doit être interrogée même si aucun de ses mots ne ressort :
    # c'est le cas d'usage « résume-moi cette vidéo » collé depuis le navigateur.
    linked_id = resolve_source(youtube_ref(question)) if youtube_ref(question) else ""

    # Le corpus sert de référence : un mot présent partout (« comment », « quand ») ne discrimine
    # rien et ramènerait du bruit. L'API renvoie, pour chaque mot, le nombre de sources qui le
    # contiennent : c'est la fréquence documentaire, donc des poids idf exploitables.
    candidates, catalogue, frequencies = [], {}, {}
    for needle in needles[:6]:
        page = api.call("GET", "/api/v1/sources",
                        {"q": needle, "has_transcript": "true", "limit": 200})
        frequencies[needle] = page.get("total", 0)
        for s in page.get("items", []):
            catalogue[s["id"]] = s
            candidates.append(s["id"])
    total = max(1, transcription_total or len(catalogue))
    # df = 0 est un artefact : la recherche de l'API est sensible aux accents (« debute » ne
    # trouve pas « débutes ») alors que la nôtre ne l'est pas. Un tel mot n'est pas un
    # discriminant fiable : poids faible, et il ne peut pas servir de filtre à lui seul.
    weights = {t: (round(log(1 + total / (1 + df)), 3) if df else 0.5)
               for t, df in frequencies.items()}
    strong = {t for t, df in frequencies.items() if 0 < df <= 0.35 * total}
    ranked = [sid for sid, _ in Counter(candidates).most_common(sources_max)]
    if not strong:
        # Aucun mot ne filtre utilement : on garde les mots les plus rares plutôt que rien.
        ranked_terms = sorted((t for t in frequencies if frequencies[t]), key=lambda t: frequencies[t])
        strong = set(ranked_terms[:1]) or set(frequencies)
    if linked_id:
        try:
            catalogue.setdefault(linked_id, api.call("GET", "/api/v1/sources/%s" % linked_id))
            ranked = [linked_id] + [sid for sid in ranked if sid != linked_id]
        except ApiError:
            linked_id = ""

    found = []
    for sid in ranked:
        meta = catalogue[sid]
        try:
            transcript = api.call("GET", "/api/v1/sources/%s/transcript" % sid)
        except ApiError:
            continue
        # Sur la vidéo explicitement citée, on ne filtre pas : l'utilisateur veut son contenu,
        # pas les seuls passages qui contiennent un mot rare.
        windows = _hit_windows(transcript.get("segments", []), needles, per_source=6,
                               strong=(None if sid == linked_id else strong), weights=weights)
        if not windows and sid == linked_id:
            found.append(dict(
                source_id=sid, titre=meta["title"], auteur=meta.get("author", ""),
                format=meta.get("kind", ""), date=meta.get("date", ""), url=meta.get("url", ""),
                duree=stamp(meta.get("duration", 0)), passages=[],
                note=("Vidéo citée par son lien : appelez lire_source avec source_id=%s "
                      "pour sa transcription complète." % sid),
            ))
            continue
        if not windows:
            continue
        found.append(dict(
            source_id=sid, titre=meta["title"], auteur=meta.get("author", ""),
            format=meta.get("kind", ""), date=meta.get("date", ""), url=meta.get("url", ""),
            duree=stamp(meta.get("duration", 0)), passages=windows,
        ))
    found.sort(key=lambda item: -(item["passages"][0]["score"] if item["passages"] else -1))
    found = found[:limite]
    return dict(
        requete=question, mots_cles=needles,
        frequences_sources={t: frequencies.get(t, 0) for t in needles},
        mots_discriminants=sorted(strong), sources_candidates=len(catalogue),
        sources_avec_passages=len(found), resultats=found,
        note="Passages bruts, classés par pertinence : citez l'auteur, le titre et l'horodatage.",
    )



def lire_source(args):
    args = args or {}
    asked = str(args.get("source_id") or "").strip()
    if not asked:
        raise ApiError("source_id requis (identifiant Atelier, identifiant YouTube ou lien).")
    sid = resolve_source(asked)
    if not sid:
        raise ApiError("Source introuvable : %s" % asked)
    source = api.call("GET", "/api/v1/sources/%s" % sid)
    segments = source.get("segments") or []
    annotation = source.get("annotation") or {}
    query = str(args.get("q") or "").strip()
    depuis = max(0, int(args.get("depuis") or 0))
    body, suite = [], None
    if query:
        needles = terms_of(query) or [folded(query)]
        windows = _hit_windows(segments, needles, per_source=40)
        body = ["[%s] %s" % (w["debut"], w["texte"]) for w in windows]
    else:
        transcrits = [s for s in segments if s.get("text")]
        if depuis >= len(transcrits) and transcrits:
            raise ApiError("Cette transcription compte %d passages : `depuis` doit rester inférieur."
                           % len(transcrits))
        indices, suite = page_de(transcrits, depuis, cout=lambda s: len(s.get("text") or "") + 40)
        body = ["[%s] %s" % (stamp(transcrits[i].get("start", 0)), (transcrits[i].get("text") or "").strip())
                for i in indices]
    message = ""
    if suite is not None:
        message = ("Transcription longue : passages %d à %d sur %d. Rappelez l'outil avec depuis=%d pour la suite, "
                   "ou utilisez q pour cibler un passage." % (depuis + 1, depuis + len(body), len(segments), suite))
    return dict(
        id=sid, titre=source.get("title", ""), auteur=source.get("author", ""),
        format=source.get("kind", ""), date=source.get("date", ""), url=source.get("url", ""),
        statut=source.get("status", ""), duree=stamp(source.get("duration", 0)),
        segments=len(segments), depuis=depuis, suite=suite, message=message,
        tags=annotation.get("tags", []),
        synthese_ia=annotation.get("summary", ""),
        chapitres_proposes=annotation.get("suggested_chapters", []),
        notes_personnelles=annotation.get("notes", ""),
        transcription=clip("\n".join(body)),
    )


def lister_idees(args):
    args = args or {}
    query = {"limit": str(min(200, int(args.get("limite") or 30)))}
    if args.get("offset"):
        query["offset"] = str(int(args["offset"]))
    if args.get("q"):
        query["q"] = str(args["q"])
    if args.get("archivees") is True:
        query["archived"] = "true"
    elif args.get("archivees") is False or not args.get("tout"):
        # Par défaut on ne montre pas les archives : c'est la pile de tri, pas le corpus actif.
        query["archived"] = "false"
    data = api.call("GET", "/api/v1/ideas", query)
    ideas = []
    for i in data.get("items", []):
        ideas.append(dict(
            id=i["id"], titre=i.get("title", ""), nature=i.get("nature", ""),
            importance=i.get("importance"), statut=i.get("status", ""),
            archive=bool(i.get("archived")), favori=bool(i.get("liked")),
            tags=i.get("tags", []), dossier=i.get("folder", ""),
            notes=clip(i.get("notes", ""), 700),
            references=[dict(source_id=r.get("source_id"), debut=stamp(r.get("start", 0)),
                             fin=stamp(r.get("end", 0)), citation=clip(r.get("quote", ""), 300))
                        for r in i.get("refs", [])],
        ))
    return dict(total=data.get("total", 0), renvoye=len(ideas), idees=ideas,
                tags_frequents=["%s (%s)" % (t, n) for t, n in
                                Counter(t for i in ideas for t in i["tags"]).most_common(12)])


def lire_idee(args):
    args = args or {}
    iid = str(args.get("idea_id") or "").strip()
    if not iid:
        raise ApiError("idea_id requis.")
    return api.call("GET", "/api/v1/ideas/%s" % iid)


def rapprochements(_=None):
    pairs = api.call("GET", "/api/v1/related").get("items", [])
    out = []
    for pair in pairs[:40]:
        out.append(dict(a=pair["a"], b=pair["b"], score=pair["score"], mots=pair["words"]))
    return dict(total=len(pairs), rapprochements=out)


def lister_tags(_=None):
    return dict(tags=api.call("GET", "/api/v1/tags").get("items", []))


def lister_livres(_=None):
    return dict(livres=api.call("GET", "/api/v1/books").get("items", []))


def creer_livre(args):
    """Crée un projet de livre vide : le bon geste pour démarrer un nouveau livre."""
    args = args or {}
    title = str(args.get("title") or "").strip()
    if not title:
        raise ApiError("title requis.")
    author = str(args.get("author") or "").strip()[:300]
    book = api.call("POST", "/api/v1/books", body=dict(title=title[:300], author=author))
    return dict(livre=book.get("title", title), book_id=book.get("_book_id") or book.get("id"),
                auteur=book.get("author", ""), chapitres=0, revision=book.get("_revision"),
                suite="Utilisez ce book_id pour ajouter_chapitre et definir_intention.")


def supprimer_livre(args):
    """Supprime un projet de livre. Définitif : les versions datées partent avec lui."""
    args = args or {}
    book_id = str(args.get("book_id") or "").strip()
    force = bool(args.get("force"))
    if not book_id:
        raise ApiError("book_id requis — listez les projets avec lister_livres.")
    if book_id == "book-main":
        raise ApiError("Le projet principal ne peut pas être supprimé.")
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    words = sum(len((b.get("text") or "").split())
                for c in (book.get("chapters") or []) for b in (c.get("blocks") or []))
    if words and not force:
        raise ApiError("Le livre « %s » contient %d mots : confirmez avec force=true. La suppression "
                       "d'un livre est définitive, son historique part avec lui."
                       % (book.get("title", ""), words))
    api.call("DELETE", "/api/v1/books/%s" % book_id)
    return dict(livre=book.get("title", ""), book_id=book_id,
                chapitres_supprimes=len(book.get("chapters") or []), mots_perdus=words)


def lire_livre(args):
    """Plan du projet : chapitres (titre, objectif, taille, sources), intention, matières.

    Le manuscrit complet est bien trop gros pour un seul appel : le texte se lit avec lire_chapitre.
    """
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    avec_texte = bool(args.get("avec_texte"))
    chapitres, mots_total = [], 0
    for numero, chapitre in enumerate(book.get("chapters") or [], 1):
        blocs = chapitre.get("blocks") or []
        texte = "\n\n".join(
            b.get("text", "") for b in blocs
            if b.get("type") in ("text", "heading", "quote")
        )
        mots = len(texte.split())
        mots_total += mots
        item = dict(
            numero=numero, id=chapitre.get("id"), titre=chapitre.get("title", ""),
            objectif=chapitre.get("purpose", ""), blocs=len(blocs), mots=mots,
            ecrit=bool(texte.strip()),
            sources=sorted({s for b in blocs for s in (b.get("source_ids") or [])}),
        )
        if avec_texte:
            item["texte"] = texte
        chapitres.append(item)
    taille = len(json.dumps(book, ensure_ascii=False))
    conseil = ("Le manuscrit fait %d Ko : il ne tient pas dans un seul appel. Lisez le texte par chapitre avec "
               "lire_chapitre (chapitre = numéro, titre ou identifiant), page par page si la réponse donne `suite`."
               % round(taille / 1024))
    if avec_texte:
        conseil = ("avec_texte=true ne renvoie que ce qui tient dans une réponse : pour un livre de cette taille, "
                   "préférez lire_chapitre, chapitre par chapitre.")
    return dict(id=book_id, titre=book.get("title", ""), auteur=book.get("author", ""),
                revision=book.get("_revision"), intention=book.get("brief", {}),
                sources_du_livre=book.get("source_ids", []), chapitres=chapitres,
                chapitres_total=len(chapitres), mots_total=mots_total,
                taille_manuscrit_octets=taille, conseil=conseil)


def lire_chapitre(args):
    """Texte d'un chapitre, entier ou par pages : aucune coupe silencieuse.

    `chapitre` accepte l'identifiant, le numéro (1..N) ou le titre. Si la réponse donne `suite`,
    rappeler l'outil avec depuis=suite pour la page suivante.
    """
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    chapitres = book.get("chapters") or []
    if not chapitres:
        raise ApiError("Ce livre n'a pas encore de chapitre : écrivez-en un ou demandez un plan.")
    chapitre, numero = trouver_chapitre(chapitres, args.get("chapitre"))
    blocs = chapitre.get("blocks") or []
    if not blocs:
        return dict(livre=book.get("title", ""), book_id=book_id, chapitre=chapitre.get("id"), numero=numero,
                    titre=chapitre.get("title", ""), objectif=chapitre.get("purpose", ""),
                    blocs_total=0, mots=0, blocs=[], suite=None,
                    message="Ce chapitre est encore vide : rien à lire, il attend son texte.")
    depuis = max(0, int(args.get("depuis") or 0))
    if depuis >= len(blocs):
        raise ApiError("Ce chapitre compte %d blocs : `depuis` doit rester inférieur (les blocs sont numérotés de 1 à %d)."
                       % (len(blocs), len(blocs)))
    indices, suite = page_de(blocs, depuis, cout=lambda b: len(b.get("text") or "") + 200)
    texte_total = "\n\n".join(b.get("text", "") for b in blocs if b.get("type") in ("text", "heading", "quote"))
    page = [dict(numero=i + 1, type=blocs[i].get("type", "text"), texte=blocs[i].get("text") or "",
                 sources=blocs[i].get("source_ids") or []) for i in indices]
    message = ("Chapitre lu en entier (%d bloc%s)." % (len(blocs), "s" if len(blocs) > 1 else ""))
    if suite is not None:
        message = ("Page %d à %d sur %d blocs : rappelez l'outil avec depuis=%d pour la suite."
                   % (indices[0] + 1, indices[-1] + 1, len(blocs), suite))
    return dict(livre=book.get("title", ""), book_id=book_id, chapitre=chapitre.get("id"), numero=numero,
                titre=chapitre.get("title", ""), objectif=chapitre.get("purpose", ""),
                revision=book.get("_revision"), blocs_total=len(blocs),
                mots=len(texte_total.split()),
                sources=sorted({s for b in blocs for s in (b.get("source_ids") or [])}),
                depuis=depuis, blocs=page, suite=suite, message=message)


def _index_sources():
    """Index id → fiche source, en deux pages (la liste plafonne à 200 par appel)."""
    index = {}
    offset = 0
    while offset < 1000:
        page = api.call("GET", "/api/v1/sources", {"limit": 200, "offset": offset})
        items = page.get("items") or []
        for source in items:
            index[str(source.get("id"))] = source
        offset += 200
        if not items or offset >= (page.get("total") or 0):
            break
    return index


def matieres_livre(args):
    """Sources qui nourrissent un projet de livre, et celles citées dans les chapitres sans l'être encore."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    declarees = [str(x) for x in (book.get("source_ids") or [])]
    citees = []
    for chapter in book.get("chapters", []):
        for block in chapter.get("blocks", []):
            for sid in (block.get("source_ids") or []):
                if str(sid) not in citees:
                    citees.append(str(sid))
    manquantes = [sid for sid in citees if sid not in declarees]
    index = _index_sources()

    def fiche(sid):
        source = index.get(sid) or {}
        return dict(source_id=sid, titre=source.get("title") or "(source introuvable)",
                    auteur=source.get("author", ""),
                    transcription=bool(source.get("segment_count")))

    return dict(livre=book.get("title", ""), book_id=book_id, maximum=60,
                matieres=[fiche(sid) for sid in declarees],
                citees_sans_matiere=[fiche(sid) for sid in manquantes],
                place_restante=max(0, 60 - len(declarees)),
                suite=("Ces sources sont citées dans le manuscrit sans nourrir le projet : rattachez-les avec "
                       "ajouter_sources_livre, sinon l'accompagnement éditorial travaille sans elles."
                       if manquantes else ""))


def _matieres_ecrire(book_id, ids, retirer=False):
    """Relit le livre juste avant d'écrire : le PATCH exige la révision courante."""
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    actuelles = [str(x) for x in (book.get("source_ids") or [])]
    if retirer:
        restantes = [sid for sid in actuelles if sid not in ids]
        touchees = [sid for sid in ids if sid in actuelles]
        inutiles = [sid for sid in ids if sid not in actuelles]
    else:
        nouvelles = [sid for sid in ids if sid not in actuelles]
        restantes = actuelles + nouvelles
        touchees = nouvelles
        inutiles = [sid for sid in ids if sid in actuelles]
    if len(restantes) > 60:
        raise ApiError("Un livre accepte 60 sources au maximum : %d déjà rattachées, %d nouvelles, %d en trop. "
                       "Retirez d'abord des sources (retirer_sources_livre) ou rattachez-en moins."
                       % (len(actuelles), len(restantes) - len(actuelles), len(restantes) - 60))
    if not touchees:
        return None, dict(livre=book.get("title", ""), book_id=book_id, matieres=actuelles,
                          modifiees=[], deja_a_jour=inutiles, total=len(actuelles),
                          place_restante=60 - len(actuelles))
    maj = api.call("PATCH", "/api/v1/books/%s" % book_id,
                   body={"_revision": book.get("_revision"), "source_ids": restantes})
    return maj, None


def ajouter_sources_livre(args):
    """Rattache des sources de la bibliothèque au projet de livre (l'onglet « Matière »)."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    ids = [str(x).strip() for x in (args.get("source_ids") or []) if str(x).strip()]
    if not ids:
        raise ApiError("source_ids requis : les sources à rattacher au projet (chercher_sources pour les trouver).")
    ids = list(dict.fromkeys(ids))
    index = _index_sources()
    inconnues = [sid for sid in ids if sid not in index]
    if inconnues:
        raise ApiError("Source(s) introuvable(s) : %s. Vérifiez les identifiants avec chercher_sources."
                       % ", ".join(inconnues[:5]))
    maj, inutile = _matieres_ecrire(book_id, ids)
    if inutile:
        return inutile
    matieres = [str(x) for x in (maj.get("source_ids") or [])]
    return dict(livre=maj.get("title", ""), book_id=book_id, matieres=matieres,
                ajoutees=[sid for sid in ids if sid in matieres],
                total=len(matieres), place_restante=60 - len(matieres))


def retirer_sources_livre(args):
    """Détache des sources des matières d'un projet (les sources restent dans la bibliothèque)."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    ids = [str(x).strip() for x in (args.get("source_ids") or []) if str(x).strip()]
    if not ids:
        raise ApiError("source_ids requis : les sources à détacher du projet.")
    ids = list(dict.fromkeys(ids))
    maj, inutile = _matieres_ecrire(book_id, ids, retirer=True)
    if inutile:
        return inutile
    matieres = [str(x) for x in (maj.get("source_ids") or [])]
    return dict(livre=maj.get("title", ""), book_id=book_id, matieres=matieres,
                retirees=[sid for sid in ids if sid not in matieres],
                total=len(matieres), place_restante=60 - len(matieres))


def exporter_livre(args):
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    return clip(api.call("GET", "/api/export", {"book_id": book_id}))


# --------------------------------------------------------------------------- écriture

def modifier_idees(args):
    args = args or {}
    ids = [str(x) for x in (args.get("idea_ids") or [])][:200]
    if not ids:
        raise ApiError("idea_ids requis (1 à 200 identifiants).")
    body = {"idea_ids": ids}
    if args.get("tags"):
        body["tags"] = [str(t) for t in args["tags"]]
        body["mode"] = str(args.get("mode") or "add")
    for key in ("liked", "archived"):
        if isinstance(args.get(key), bool):
            body[key] = args[key]
    result = {}
    if len(body) > 1:
        result["lots"] = api.call("POST", "/api/v1/ideas/batch", body=body)
    if args.get("statut"):
        changed = 0
        for iid in ids:
            idea = api.call("GET", "/api/v1/ideas/%s" % iid)
            idea["status"] = str(args["statut"])
            api.call("PATCH", "/api/v1/ideas/%s" % iid, body=idea)
            changed += 1
        result["statut"] = {"statut": args["statut"], "count": changed}
    if not result:
        raise ApiError("Précisez tags, liked, archived ou statut.")
    return result


def modifier_sources(args):
    args = args or {}
    ids = [str(x) for x in (args.get("source_ids") or [])][:200]
    if not ids:
        raise ApiError("source_ids requis (1 à 200 identifiants).")
    body = {"source_ids": ids}
    if args.get("tags"):
        body["tags"] = [str(t) for t in args["tags"]]
        body["mode"] = str(args.get("mode") or "add")
    for key in ("liked", "archived"):
        if isinstance(args.get(key), bool):
            body[key] = args[key]
    if len(body) == 1:
        raise ApiError("Précisez tags, liked ou archived.")
    return api.call("POST", "/api/v1/sources/batch", body=body)


def creer_idee(args):
    args = args or {}
    refs = []
    for ref in args.get("refs") or []:
        refs.append(dict(
            source_id=str(ref.get("source_id")),
            start=float(ref.get("start") or 0),
            end=float(ref.get("end") or ref.get("start") or 0),
            quote=str(ref.get("quote") or ""),
        ))
    if not refs:
        raise ApiError("Une idée doit garder au moins une référence {source_id, start, end}.")
    body = dict(title=str(args.get("title") or "").strip(), refs=refs)
    for key in ("notes", "nature", "importance", "status"):
        if args.get(key):
            body[key] = str(args[key])
    if args.get("tags"):
        body["tags"] = [str(t) for t in args["tags"]]
    if args.get("folder"):
        body["folder"] = str(args["folder"])
    for key in ("liked", "archived"):
        if isinstance(args.get(key), bool):
            body[key] = args[key]
    if not body["title"]:
        raise ApiError("title requis.")
    return api.call("POST", "/api/v1/ideas", body=body)


def creer_dossier(args):
    args = args or {}
    name = str(args.get("name") or "").strip()
    if not name:
        raise ApiError("name requis.")
    return api.call("POST", "/api/v1/folders", body={"name": name})


def definir_intention(args):
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    brief = dict(book.get("brief") or {})
    for key in ("intention", "reader", "promise", "voice"):
        if args.get(key) is not None:
            brief[key] = str(args[key])[:6000]
    if not brief.get("intention"):
        raise ApiError("Le champ intention est obligatoire.")
    return api.call("PATCH", "/api/v1/books/%s" % book_id, body={"brief": brief})


def _chapters_with(book_id, mutate):
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    chapters = json.loads(json.dumps(book.get("chapters", [])))
    result = mutate(chapters)
    saved = api.call("PATCH", "/api/v1/books/%s" % book_id, body={"chapters": chapters})
    return dict(result=result, revision=saved.get("_revision"),
                chapitres=[c.get("title", "") for c in saved.get("chapters", [])])


def ajouter_chapitre(args):
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    title = str(args.get("title") or "").strip()
    if not title:
        raise ApiError("title requis.")
    chapter = dict(id=uuid.uuid4().hex[:16], title=title[:500],
                   purpose=str(args.get("purpose") or "")[:2500], ideas=[], blocks=[])

    def mutate(chapters):
        position = args.get("position")
        if isinstance(position, int):
            chapters.insert(max(0, min(position, len(chapters))), chapter)
        else:
            chapters.append(chapter)
        return dict(chapitre=chapter["title"], chapter_id=chapter["id"], position=len(chapters))

    return _chapters_with(book_id, mutate)


def ajouter_texte_chapitre(args):
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    chapter_id = str(args.get("chapter_id") or "").strip()
    text = str(args.get("text") or "").strip()
    if not chapter_id or not text:
        raise ApiError("chapter_id et text sont requis.")
    source_ids = [str(x) for x in (args.get("source_ids") or [])][:60]

    def mutate(chapters):
        chapter = next((c for c in chapters if c.get("id") == chapter_id), None)
        if not chapter:
            raise ApiError("Chapitre introuvable : %s" % chapter_id)
        chapter.setdefault("blocks", []).append(dict(
            id=uuid.uuid4().hex[:16], type="text", text=text[:50000], source_ids=source_ids))
        return dict(chapitre=chapter.get("title", ""), blocs=len(chapter["blocks"]),
                    mots_ajoutes=len(text.split()))

    return _chapters_with(book_id, mutate)


def renommer_chapitre(args):
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    chapter_id = str(args.get("chapter_id") or "").strip()
    if not chapter_id:
        raise ApiError("chapter_id requis.")
    title, purpose = args.get("title"), args.get("purpose")
    if not isinstance(title, str) and not isinstance(purpose, str):
        raise ApiError("Donnez au moins title ou purpose.")

    def mutate(chapters):
        chapter = next((c for c in chapters if c.get("id") == chapter_id), None)
        if not chapter:
            raise ApiError("Chapitre introuvable : %s" % chapter_id)
        before = chapter.get("title", "")
        renamed = bool(isinstance(title, str) and title.strip())
        if renamed:
            chapter["title"] = title.strip()[:500]
        if isinstance(purpose, str):
            chapter["purpose"] = purpose.strip()[:2500]
        return dict(chapitre=chapter.get("title", ""), ancien_titre=before,
                    titre_change=renamed and chapter.get("title") != before,
                    objectif=chapter.get("purpose", ""))

    return _chapters_with(book_id, mutate)


def deplacer_chapitre(args):
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    chapter_id = str(args.get("chapter_id") or "").strip()
    position = args.get("position")
    if not chapter_id:
        raise ApiError("chapter_id requis.")
    if not isinstance(position, int) or isinstance(position, bool):
        raise ApiError("position (entier, 0 = début du livre) requis.")

    def mutate(chapters):
        chapter = next((c for c in chapters if c.get("id") == chapter_id), None)
        if not chapter:
            raise ApiError("Chapitre introuvable : %s" % chapter_id)
        before = chapters.index(chapter)
        chapters.remove(chapter)
        chapters.insert(max(0, min(position, len(chapters))), chapter)
        return dict(chapitre=chapter.get("title", ""), avant=before,
                    apres=chapters.index(chapter),
                    ordre=[c.get("title", "") for c in chapters])

    return _chapters_with(book_id, mutate)


def supprimer_chapitre(args):
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    chapter_id = str(args.get("chapter_id") or "").strip()
    force = bool(args.get("force"))
    if not chapter_id:
        raise ApiError("chapter_id requis.")

    def mutate(chapters):
        chapter = next((c for c in chapters if c.get("id") == chapter_id), None)
        if not chapter:
            raise ApiError("Chapitre introuvable : %s" % chapter_id)
        words = sum(len((b.get("text") or "").split()) for b in (chapter.get("blocks") or []))
        if words and not force:
            raise ApiError("Le chapitre « %s » contient %d mots : confirmez la suppression avec "
                           "force=true. La version supprimée reste dans l'historique du livre."
                           % (chapter.get("title", ""), words))
        chapters.remove(chapter)
        return dict(chapitre=chapter.get("title", ""), mots_perdus=words, force=force,
                    restants=[c.get("title", "") for c in chapters])

    return _chapters_with(book_id, mutate)


def remplacer_texte_chapitre(args):
    """Remplace le texte d'un chapitre au lieu d'empiler des paragraphes."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    chapter_id = str(args.get("chapter_id") or "").strip()
    if not chapter_id:
        raise ApiError("chapter_id requis.")
    source_ids = [str(x) for x in (args.get("source_ids") or [])][:60]
    paragraphs = args.get("paragraphs")
    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    if paragraphs is None and isinstance(args.get("text"), str):
        paragraphs = [args["text"]]
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ApiError("paragraphs (liste de textes) requis, ou text pour un paragraphe unique.")
    blocks = [dict(id=uuid.uuid4().hex[:16], type="text", text=str(p).strip()[:50000],
                   source_ids=source_ids)
              for p in paragraphs if str(p).strip()]
    if not blocks:
        raise ApiError("Aucun paragraphe exploitable.")
    keep_media = args.get("keep_media") is not False

    def mutate(chapters):
        chapter = next((c for c in chapters if c.get("id") == chapter_id), None)
        if not chapter:
            raise ApiError("Chapitre introuvable : %s" % chapter_id)
        previous = chapter.get("blocks") or []
        media = [b for b in previous if b.get("type") != "text"] if keep_media else []
        chapter["blocks"] = [*blocks, *media]
        return dict(chapitre=chapter.get("title", ""), anciens_blocs=len(previous),
                    nouveaux_blocs=len(chapter["blocks"]),
                    mots=sum(len(b["text"].split()) for b in blocks))

    return _chapters_with(book_id, mutate)


def ajouter_source(args):
    """Crée une source documentaire (texte collé) dans la bibliothèque."""
    args = args or {}
    title = str(args.get("title") or "").strip()
    author = str(args.get("author") or "").strip()
    if not title:
        raise ApiError("title requis.")
    if not author:
        raise ApiError("author requis : indiquez l'auteur, ou « Auteur inconnu ».")
    body = {"title": title[:1000], "author": author[:300]}
    for key, limit in (("url", 2000), ("kind", 60), ("description", 4000), ("date", 20)):
        if isinstance(args.get(key), str) and args[key].strip():
            body[key] = args[key].strip()[:limit]
    if isinstance(args.get("tags"), list):
        body["original_tags"] = [str(x).strip()[:80] for x in args["tags"] if str(x).strip()][:50]
    if isinstance(args.get("text"), str) and args["text"].strip():
        body["text"] = args["text"]
    elif isinstance(args.get("segments"), list) and args["segments"]:
        body["segments"] = args["segments"]
    source = api.call("POST", "/api/v1/sources", body=body)
    return dict(source=source.get("title", title), source_id=source.get("id"),
                auteur=source.get("author", ""), segments=len(source.get("segments") or []),
                statut=source.get("status", ""),
                suite="Lisez-la avec lire_source, puis analysez-la avec analyser_sources.")


def importer_youtube(args):
    """Importe une vidéo YouTube : la transcription est récupérée en arrière-plan."""
    args = args or {}
    url = str(args.get("url") or "").strip()
    if not url:
        raise ApiError("url requis : le lien d'une vidéo YouTube, pas d'une chaîne ni d'une playlist.")
    body = {"url": url}
    for key in ("title", "author"):
        if isinstance(args.get(key), str) and args[key].strip():
            body[key] = args[key].strip()
    out = api.call("POST", "/api/v1/sources/youtube", body=body)
    source, job = out.get("source") or {}, out.get("job") or {}
    return dict(source=source.get("title", ""), source_id=source.get("id"),
                deja_presente=bool(out.get("already_present")), job=job.get("id"),
                etat=job.get("status") or ("déjà importée" if out.get("already_present") else ""),
                suite="Suivez la récupération avec etat_bibliotheque, puis lisez le texte avec lire_source.")


def modifier_source(args):
    """Corrige les métadonnées d'une source (titre, auteur, description, format, lien)."""
    args = args or {}
    sid = str(args.get("source_id") or "").strip()
    if not sid:
        raise ApiError("source_id requis.")
    body = {}
    for key, limit in (("title", 1000), ("author", 300), ("description", 4000),
                       ("kind", 60), ("date", 20), ("url", 2000)):
        if isinstance(args.get(key), str) and args[key].strip():
            body[key] = args[key].strip()[:limit]
    if not body:
        raise ApiError("Indiquez au moins un champ : title, author, description, kind, date ou url.")
    source = api.call("PATCH", "/api/v1/sources/%s" % sid, body=body)
    return dict(source=source.get("title", ""), source_id=sid, auteur=source.get("author", ""),
                format=source.get("kind", ""), description=(source.get("description") or "")[:200])


def supprimer_source(args):
    """Supprime une source. Refuse si des idées s'appuient dessus, sauf force=true (références nettoyées)."""
    args = args or {}
    sid = str(args.get("source_id") or "").strip()
    force = bool(args.get("force"))
    if not sid:
        raise ApiError("source_id requis.")
    source = api.call("GET", "/api/v1/sources/%s" % sid)
    try:
        api.call("DELETE", "/api/v1/sources/%s" % sid, query={"force": "true"} if force else None)
    except ApiError as error:
        raise ApiError("%s Alternative plus douce : gardez la source et archivez-la avec annoter_source "
                       "(archived=true)." % error)
    return dict(source=source.get("title", ""), source_id=sid, supprime=True, force=force,
                segments=len(source.get("segments") or []))


def annoter_source(args):
    """Classe une source : tags (valide aussi les tags proposés par l'IA), favori, archivage, dossier, notes."""
    args = args or {}
    sid = str(args.get("source_id") or "").strip()
    if not sid:
        raise ApiError("source_id requis.")
    body = {}
    if isinstance(args.get("tags"), list):
        body["tags"] = [str(x).strip()[:80] for x in args["tags"] if str(x).strip()][:50]
    for key in ("liked", "archived"):
        if isinstance(args.get(key), bool):
            body[key] = args[key]
    if isinstance(args.get("notes"), str):
        body["notes"] = args["notes"][:8000]
    if isinstance(args.get("folder"), str) and args["folder"].strip():
        body["folder"] = args["folder"].strip()
    if not body:
        raise ApiError("Indiquez au moins tags, liked, archived, notes ou folder.")
    item = api.call("PUT", "/api/v1/sources/%s/annotation" % sid, body=body)
    return dict(source_id=sid, tags=item.get("tags", []), favori=bool(item.get("liked")),
                archive=bool(item.get("archived")), dossier=item.get("folder", ""),
                notes=(item.get("notes") or "")[:200])


def ecrire_transcription(args):
    """Écrit ou corrige la transcription d'une source (texte horodaté, ou segments structurés)."""
    args = args or {}
    sid = str(args.get("source_id") or "").strip()
    if not sid:
        raise ApiError("source_id requis.")
    body = {}
    if isinstance(args.get("text"), str) and args["text"].strip():
        body["text"] = args["text"]
    elif isinstance(args.get("segments"), list) and args["segments"]:
        body["segments"] = args["segments"]
    else:
        raise ApiError("Fournissez text (une ligne par passage, horodatage optionnel en début de ligne) "
                       "ou segments.")
    if isinstance(args.get("language"), str) and args["language"].strip():
        body["language"] = args["language"].strip()[:30]
    source = api.call("POST", "/api/v1/sources/%s/transcript" % sid, body=body)
    return dict(source_id=sid, titre=source.get("title", ""), segments=len(source.get("segments") or []),
                statut=source.get("status", ""))


def supprimer_transcription(args):
    """Retire la transcription d'une source : la source reste, avec ses métadonnées et ses idées."""
    args = args or {}
    sid = str(args.get("source_id") or "").strip()
    if not sid:
        raise ApiError("source_id requis.")
    source = api.call("DELETE", "/api/v1/sources/%s/transcript" % sid)
    return dict(source_id=sid, titre=source.get("title", ""), segments=0,
                statut=source.get("status", ""), note="La source reste dans la bibliothèque, sans texte.")


def rafraichir_transcription(args):
    """Relance la récupération du texte d'une source YouTube dont la transcription manque ou a échoué."""
    args = args or {}
    sid = str(args.get("source_id") or "").strip()
    if not sid:
        raise ApiError("source_id requis.")
    out = api.call("POST", "/api/refetch-transcript", body={"id": sid})
    source, job = out.get("source") or {}, out.get("job") or {}
    return dict(source=source.get("title", ""), source_id=sid, job=job.get("id"),
                etat=job.get("status") or "une récupération est déjà en cours",
                suite="Suivez-la avec etat_bibliotheque.")


def supprimer_idee(args):
    """Supprime une idée. Les fiches sources qu'elle citait ne sont pas touchées."""
    args = args or {}
    iid = str(args.get("idea_id") or "").strip()
    if not iid:
        raise ApiError("idea_id requis — retrouvez-les avec lister_idees.")
    idea = api.call("GET", "/api/v1/ideas/%s" % iid)
    api.call("DELETE", "/api/v1/ideas/%s" % iid)
    return dict(idee=idea.get("title", ""), idea_id=iid, supprime=True,
                note="Si vous vouliez seulement l'écarter, modifier_idees sait l'archiver sans la perdre.")


def renommer_dossier(args):
    """Renomme un dossier (les sources et idées rangées dedans ne bougent pas)."""
    args = args or {}
    fid = str(args.get("folder_id") or "").strip()
    name = str(args.get("name") or "").strip()
    if not fid or not name:
        raise ApiError("folder_id et name sont requis.")
    out = api.call("PATCH", "/api/v1/folders/%s" % fid, body={"name": name[:150]})
    return dict(dossier=out.get("name", name), folder_id=fid)


def supprimer_dossier(args):
    """Supprime un dossier : les sources et idées rangées dedans sont détachées, jamais supprimées."""
    args = args or {}
    fid = str(args.get("folder_id") or "").strip()
    if not fid:
        raise ApiError("folder_id requis — retrouvez-les avec etat_bibliotheque.")
    api.call("DELETE", "/api/v1/folders/%s" % fid)
    return dict(folder_id=fid, supprime=True,
                note="Le dossier est retiré, son contenu reste dans la bibliothèque, sans dossier.")


def analyser_sources(args):
    """Lance l'analyse IA de 1 à 20 sources : idées sourcées et tags proposés. Consomme des crédits."""
    args = args or {}
    ids = [str(x) for x in (args.get("source_ids") or []) if str(x).strip()]
    if not ids:
        raise ApiError("source_ids requis (1 à 20 sources déjà transcrites).")
    if len(ids) > 20:
        raise ApiError("L'analyse porte sur 1 à 20 sources à la fois : %d sélectionnées. Faites plusieurs appels."
                       % len(ids))
    if args.get("confirme") is not True:
        return dict(confirmation_requise=True, sources=len(ids),
                    cout="Chaque source analysée consomme des crédits du fournisseur IA (DeepSeek).",
                    a_faire="Annoncez le coût à l'utilisateur, puis rappelez l'outil avec confirme=true.")
    job = api.call("POST", "/api/v1/analysis", body={"source_ids": ids})
    return dict(job=job.get("id"), etat=job.get("status"), sources=len(ids),
                suite="Suivez l'avancement avec etat_bibliotheque ; les idées arrivent ensuite dans lister_idees.")


def proposer_chapitres(args):
    """Demande à l'IA un plan de chapitres pour une source transcrite. Consomme des crédits."""
    args = args or {}
    sid = str(args.get("source_id") or "").strip()
    if not sid:
        raise ApiError("source_id requis.")
    source = api.call("GET", "/api/v1/sources/%s" % sid)
    if not (source.get("segments") or []):
        raise ApiError("Cette source n'a pas de transcription : rien à découper en chapitres.")
    if args.get("confirme") is not True:
        return dict(confirmation_requise=True, source=source.get("title", ""), source_id=sid,
                    cout="La proposition de chapitres consomme des crédits du fournisseur IA.",
                    a_faire="Annoncez le coût à l'utilisateur, puis rappelez l'outil avec confirme=true.")
    job = api.call("POST", "/api/chapters", body={"id": sid})
    return dict(source=source.get("title", ""), source_id=sid, job=job.get("id"), etat=job.get("status"))


def synchroniser_bibliotheque(_=None):
    """Importe les sources déposées sur le serveur (corpus et inventaires locaux). Rien n'est écrasé."""
    out = api.call("POST", "/api/sync", body={})
    return dict(importees=out.get("imported", 0))


def historique_livre(args):
    """Liste les versions enregistrées d'un livre, pour retrouver un état antérieur."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    versions = api.call("GET", "/api/history", {"book_id": book_id}) or []
    return dict(livre=book_id, versions=[dict(id=v.get("id"), date=v.get("created"), label=v.get("label"),
                                              changements=v.get("changes") or [])
                                         for v in versions][:50],
                suite="Restaurez-en une avec restaurer_version_livre (version_id).")


def restaurer_version_livre(args):
    """Remet un livre dans l'état d'une version enregistrée. L'état actuel reste dans l'historique."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    version_id = str(args.get("version_id") or "").strip()
    if not version_id:
        raise ApiError("version_id requis — listez-les avec historique_livre.")
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    out = api.call("POST", "/api/restore", body={"id": version_id, "revision": book.get("_revision")})
    chapters = out.get("chapters") or []
    return dict(livre=out.get("title", book.get("title", "")), book_id=book_id, version_restauree=version_id,
                chapitres=[c.get("title", "") for c in chapters],
                mots=sum(len((b.get("text") or "").split()) for c in chapters
                         for b in (c.get("blocks") or [])))


MODES_REDACTION = ("plan", "draft", "review")
MODES_LIBELLES = {"plan": "plan de chapitres", "draft": "brouillon de chapitre", "review": "relecture critique"}
FACES_COUVERTURE = {"front": "première de couverture", "back": "quatrième de couverture"}


def _proposition(result):
    """Met en forme la proposition éditoriale : les indices servent à appliquer_proposition."""
    if not isinstance(result, dict):
        return {}
    chapitres = result.get("chapters") or []
    paragraphes = result.get("paragraphs") or []
    out = dict(mode=result.get("mode", ""), chapitre=str(result.get("chapter_id") or ""),
               modele=result.get("model", ""), cree=result.get("created", ""),
               justification=clip(result.get("rationale", ""), 6000),
               questions=[str(q)[:2000] for q in (result.get("questions") or [])],
               analyse=clip(result.get("analysis", ""), 6000),
               interpretation=clip(result.get("interpretation", ""), 4000),
               idees_mobilisees=[dict(idee_id=i.get("idea_id"), titre=i.get("title", ""), nature=i.get("nature", ""))
                                 for i in (result.get("ideas_used") or [])],
               passages_retenus=len(result.get("evidence") or []),
               passages_ignores=len(result.get("omitted") or []),
               avertissement=result.get("notice", ""))
    if chapitres:
        out["chapitres_proposes"] = [dict(indice=n, titre=c.get("title", ""), objectif=c.get("purpose", ""),
                                          references=c.get("evidence_ids", []))
                                     for n, c in enumerate(chapitres)]
    if paragraphes:
        out["paragraphes_proposes"] = [dict(indice=n, texte=clip(c.get("text", ""), 4000),
                                            references=c.get("evidence_ids", []))
                                       for n, c in enumerate(paragraphes)]
    return out


def _job_editorial(job):
    if not isinstance(job, dict):
        return {}
    out = dict(job_id=job.get("id", ""), livre=job.get("book_id", ""), mode=job.get("mode", ""),
               mode_libelle=MODES_LIBELLES.get(job.get("mode", ""), job.get("mode", "")),
               statut=job.get("status", ""), etape=job.get("stage", ""), message=job.get("message", ""),
               avancement=job.get("progress", 0), cree=job.get("created", ""), maj=job.get("updated", ""))
    out.update(_proposition(job.get("result")))
    return out


def _reglages():
    return api.call("GET", "/api/library", {"compact": "1"}).get("settings") or {}


def lire_reglages(_=None):
    """Connexion IA et réglages de l'atelier — jamais la clé elle-même."""
    cfg = _reglages()
    return dict(fournisseur=cfg.get("provider", ""), modele=cfg.get("model", ""),
                base_url=cfg.get("base_url", ""), instruction=cfg.get("instruction", ""),
                cle_enregistree=bool(cfg.get("has_key")), cle_persistante=bool(cfg.get("key_persistent")),
                mot_de_passe_actif=bool(cfg.get("authentication")),
                note="La clé API ne sort jamais de l'Atelier : ni lisible ni modifiable par le MCP.")


def lire_prompts_ia(_=None):
    """Prompts des missions IA : libellé, texte courant, et s'il a été personnalisé."""
    prompts = api.call("GET", "/api/prompts").get("prompts") or []
    return dict(total=len(prompts),
                prompts=[dict(cle=p.get("key"), libelle=p.get("label"), personnalise=bool(p.get("customized")),
                              aide=p.get("help", ""), defaut=clip(p.get("default", ""), 3000),
                              longueur=len(p.get("value") or ""),
                              tronque=len(p.get("value") or "") > 12000,
                              texte=clip(p.get("value", ""), 12000)) for p in prompts])


def lister_modeles_ia(_=None):
    """Modèles proposés par le fournisseur IA configuré."""
    data = api.call("POST", "/api/models", body={})
    items = data.get("data") if isinstance(data, dict) else data
    noms = sorted(str(m.get("id")) for m in (items or []) if isinstance(m, dict) and m.get("id"))
    cfg = _reglages()
    return dict(fournisseur=cfg.get("provider", ""), modele_actuel=cfg.get("model", ""),
                total=len(noms), modeles=noms)


def lire_version_livre(args):
    """Détail d'une version d'un livre : libellé, date, et diff mot à mot de chaque changement."""
    args = args or {}
    vid = str(args.get("version_id") or args.get("id") or "").strip()
    if not vid:
        raise ApiError("version_id requis : obtenez-les avec historique_livre (champ id).")
    version = api.call("GET", "/api/version", {"id": vid})
    changements = []
    for change in version.get("changes") or []:
        item = {}
        for cle, valeur in change.items():
            if cle in ("before", "after"):
                continue
            if cle == "diff":
                item["diff"] = clip(str(valeur), 4000)
            elif isinstance(valeur, (dict, list)):
                item[cle] = clip(json.dumps(valeur, ensure_ascii=False), 1200)
            else:
                item[cle] = valeur
        changements.append(item)
    return dict(version_id=vid, book_id=version.get("book_id", ""), libelle=version.get("label", ""),
                cree=version.get("created", ""), sequence=version.get("seq", ""),
                changements=changements)


def lister_fichiers(_=None):
    """Médias de l'atelier : images (dont les couvertures possibles) et documents importés."""
    assets = api.call("GET", "/api/assets") or []
    return dict(total=len(assets),
                fichiers=[dict(fichier_id=a.get("id"), nom=a.get("name"), type=a.get("mime", ""),
                               octets=a.get("size", 0), image=bool(a.get("preview")),
                               ajoute_le=a.get("created", "")) for a in assets])


def suivre_redaction(args=None):
    """État d'une préparation éditoriale et, si elle est prête, la proposition complète à appliquer."""
    args = args or {}
    jid = str(args.get("job_id") or "").strip()
    if jid:
        return _job_editorial(api.call("GET", "/api/editorial-job", {"id": jid}))
    book_id = str(args.get("book_id") or "book-main")
    jobs = api.call("GET", "/api/editorial-job", {"book_id": book_id}) or []
    return dict(livre=book_id, total=len(jobs), preparations=[_job_editorial(j) for j in jobs[:10]])


def verifier_export_livre(args):
    """Vérifier qu'un livre s'exporte (md, pdf, epub) : le fichier se génère, taille à l'appui."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    fmt = str(args.get("format") or "pdf").strip().lower()
    routes = {"md": ("/api/export", "mon-livre.md"), "pdf": ("/api/book.pdf", "mon-livre-A5.pdf"),
              "epub": ("/api/book.epub", "mon-livre.epub")}
    if fmt not in routes:
        raise ApiError("format requis : md (Markdown), pdf ou epub.")
    chemin, nom = routes[fmt]
    url = (api.base or api.bases[0]) + chemin + "?book_id=" + urllib.parse.quote(book_id)
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + api.token})
    with urllib.request.urlopen(request, timeout=300) as response:
        raw = response.read()
    return dict(book_id=book_id, format=fmt, fichier=nom, octets=len(raw),
                mega=round(len(raw) / 1048576, 2), exportable=len(raw) > 0,
                message="Le MCP ne transporte pas de fichier : téléchargez-le depuis l'Atelier (Exporter).")


def definir_prompt_ia(args):
    """Personnaliser un prompt de mission IA (texte vide = retour au prompt d'origine)."""
    args = args or {}
    cle = str(args.get("cle") or "").strip()
    if not cle:
        raise ApiError("cle requise : obtenez-la avec lire_prompts_ia.")
    texte = str(args.get("texte") or "")
    if not texte.strip() and not args.get("confirme"):
        prompts = {p.get("key"): p for p in (api.call("GET", "/api/prompts").get("prompts") or [])}
        actuel = prompts.get(cle) or {}
        if actuel.get("customized"):
            raise ApiError("« %s » est personnalisé : un texte vide rétablit le prompt d'origine et efface "
                           "cette personnalisation, qui n'existe alors plus nulle part. Recopiez-la d'abord "
                           "(lire_prompts_ia), ou rappelez l'outil avec confirme=true pour l'effacer vraiment."
                           % (actuel.get("label") or cle))
    data = api.call("POST", "/api/prompts", body={"key": cle, "text": texte})
    prompt = next((p for p in (data.get("prompts") or []) if p.get("key") == cle), {})
    return dict(cle=cle, personnalise=bool(prompt.get("customized")), texte=clip(prompt.get("value", ""), 12000),
                message="Prompt d'origine rétabli." if not texte.strip() else "Prompt enregistré.")


def regler_connexion_ia(args):
    """Régler le modèle, l'adresse et l'instruction de l'IA — la clé API reste dans l'Atelier."""
    args = args or {}
    if args.get("api_key") or args.get("cle_api") or args.get("cle"):
        raise ApiError("La clé API ne transite pas par le MCP : saisissez-la dans l'Atelier → Paramètres. "
                       "Ici se règlent le modèle, l'adresse et l'instruction du fournisseur déjà configuré.")
    actuel = _reglages()
    fournisseur = str(args.get("fournisseur") or "").strip()
    if fournisseur and fournisseur != actuel.get("provider"):
        raise ApiError("Changer de fournisseur (%s → %s) exige sa clé API : faites-le dans l'Atelier → "
                       "Paramètres. Ici vous pouvez régler le modèle, l'adresse et l'instruction du "
                       "fournisseur actuel (%s)." % (actuel.get("provider"), fournisseur, actuel.get("provider")))
    corps = dict(provider=actuel.get("provider") or "custom", model=actuel.get("model"),
                 base_url=actuel.get("base_url"), instruction=actuel.get("instruction", ""))
    modifie = False
    for source, cible in (("modele", "model"), ("base_url", "base_url"), ("instruction", "instruction")):
        if args.get(source) is not None:
            corps[cible] = str(args[source])
            modifie = True
    if not modifie:
        raise ApiError("Rien à modifier : indiquez modele, base_url ou instruction. "
                       "Un champ laissé de côté n'est pas touché ; une chaîne vide vide le champ.")
    result = api.call("POST", "/api/settings", body=corps)
    return dict(fournisseur=result.get("provider", ""), modele=result.get("model", ""),
                base_url=result.get("base_url", ""), instruction=result.get("instruction", ""),
                cle_enregistree=bool(result.get("has_key")),
                message="Connexion IA mise à jour. Les travaux IA en cours doivent être terminés avant de changer.")


def lancer_redaction(args):
    """Demander une proposition à l'accompagnateur du livre — interroge l'IA, consomme des crédits."""
    args = args or {}
    mode = str(args.get("mode") or "plan").strip().lower()
    if mode not in MODES_REDACTION:
        raise ApiError("mode requis : plan (plan de chapitres), draft (brouillon d'un chapitre) "
                       "ou review (relecture critique d'un chapitre).")
    book_id = str(args.get("book_id") or "book-main")
    chapitre = str(args.get("chapter_id") or "").strip()
    instruction = str(args.get("instruction") or "")
    if mode in ("draft", "review") and not chapitre:
        raise ApiError("chapter_id requis pour une %s : listez les chapitres avec lire_livre." % MODES_LIBELLES[mode])
    if not args.get("confirme"):
        book = api.call("GET", "/api/v1/books/%s" % book_id)
        if mode == "plan":
            travail = "un plan de chapitres à partir des %d sources du projet" % len(book.get("source_ids") or [])
        else:
            travail = "un %s sur « %s », appuyé sur les sources du projet" % (
                MODES_LIBELLES[mode], next((c.get("title", "") for c in book.get("chapters", [])
                                            if c.get("id") == chapitre), chapitre))
        return dict(devis=True, livre=book.get("title", ""), book_id=book_id, mode=mode,
                    mode_libelle=MODES_LIBELLES[mode], chapitre=chapitre,
                    sources_du_projet=len(book.get("source_ids") or []),
                    message="Demande prête : l'IA prépare %s. Cela consomme des crédits (%s) et prend "
                            "une à quelques minutes. Rappelez l'outil avec confirme=true."
                            % (travail, book.get("source_ids") and "selon le modèle configuré" or "attention, "
                               "aucune source n'est rattachée au projet : utilisez ajouter_sources_livre"))
    corps = dict(book_id=book_id, mode=mode)
    if chapitre:
        corps["chapter_id"] = chapitre
    if instruction:
        corps["instruction"] = instruction
    job = api.call("POST", "/api/editorial", body=corps)
    return dict(job=_job_editorial(job),
                message="Préparation lancée. Suivez-la avec suivre_redaction (job_id %s), puis appliquez "
                        "ce que vous gardez avec appliquer_proposition." % (job or {}).get("id", ""))


def appliquer_proposition(args):
    """Intégrer au manuscrit les éléments retenus d'une proposition (indices fournis par suivre_redaction)."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    picked = args.get("picked")
    if not isinstance(picked, list) or not picked:
        book = api.call("GET", "/api/v1/books/%s" % book_id)
        proposition = book.get("editorial_proposal") or {}
        items = (proposition.get("chapters") if proposition.get("mode") == "plan"
                 else proposition.get("paragraphs")) or []
        return dict(en_attente=bool(proposition), deja_integree=bool(proposition.get("applied_at")),
                    mode=proposition.get("mode", ""), elements=[dict(id_inconnu=False, indice=n,
                                                                     texte=clip(c.get("title") or c.get("text", ""), 300))
                                                                for n, c in enumerate(items)],
                    message="picked requis : les indices à intégrer (0 pour le premier élément). "
                            "Rien n'est appliqué tant que picked est vide.")
    job_result = api.call("POST", "/api/editorial-apply",
                          body=dict(book_id=book_id, chapter_id=args.get("chapter_id") or "", picked=picked))
    chapitres = job_result.get("chapters") or []
    return dict(book_id=book_id, titre=job_result.get("title", ""), elements_integres=len(picked),
                chapitres=len(chapitres),
                mots=sum(len((b.get("text") or "").split()) for c in chapitres for b in (c.get("blocks") or [])),
                message="Éléments intégrés au manuscrit.")


def reecrire_transcription(args):
    """Réécriture éditoriale d'une transcription (condensé sourcé) — travail IA, consomme des crédits."""
    args = args or {}
    sid = str(args.get("source_id") or args.get("id") or "").strip()
    if not sid:
        raise ApiError("source_id requis (chercher_sources pour le trouver).")
    if not args.get("confirme"):
        source = api.call("GET", "/api/v1/sources/%s" % sid)
        return dict(devis=True, source_id=sid, titre=source.get("title", ""),
                    minutes=round(int(source.get("duration") or 0) / 60),
                    message="La réécriture condense la transcription en prose éditoriale sourcée : "
                            "cela consomme des crédits et se fait par lots. Rappelez l'outil avec confirme=true.")
    job = api.call("POST", "/api/rewrite", body={"id": sid})
    return dict(job_id=(job or {}).get("id", ""), source_id=sid, statut=(job or {}).get("status", ""),
                lots=(job or {}).get("total", 0), message=(job or {}).get("message", "Réécriture lancée."))


def definir_couverture_livre(args):
    """Choisir la première ou la quatrième de couverture d'un livre parmi les médias de l'atelier."""
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    face = str(args.get("face") or "front").strip().lower()
    if face not in FACES_COUVERTURE:
        raise ApiError("face requise : front (première de couverture) ou back (quatrième de couverture).")
    asset_id = str(args.get("asset_id") or "").strip()
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    covers = dict(book.get("covers") or {})
    for cote in ("front", "back"):
        covers.setdefault(cote, "")
        covers.setdefault(cote + "_variants", [])
    couv = FACES_COUVERTURE[face]
    if asset_id:
        medias = {a.get("id"): a for a in (api.call("GET", "/api/assets") or [])}
        if asset_id not in medias:
            raise ApiError("Média introuvable : choisissez un fichier avec lister_fichiers.")
        if not medias[asset_id].get("preview"):
            raise ApiError("« %s » n'est pas une image : une couverture doit être une image (lister_fichiers)."
                           % medias[asset_id].get("name", asset_id))
        variantes = covers[face + "_variants"]
        if asset_id not in variantes:
            variantes.append(asset_id)
        covers[face] = asset_id
        action = "%s choisie." % couv.capitalize()
    else:
        covers[face] = ""
        action = "%s retirée." % couv.capitalize()
    maj = api.call("PATCH", "/api/v1/books/%s" % book_id,
                   body={"_revision": book.get("_revision"), "covers": covers})
    couvertures = maj.get("covers") or {}
    return dict(book_id=book_id, face=face, couverture=couvertures.get(face, ""),
                variantes=couvertures.get(face + "_variants", []), message=action)


TOOLS = [
    dict(name="etat_bibliotheque",
         description="Vue d'ensemble de l'Atelier : nombre de sources et de transcriptions, "
                     "idées totales/archivées, dossiers, livres, tags principaux, travaux IA en cours.",
         inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
         handler=etat_bibliotheque),
    dict(name="chercher_sources",
         description="Chercher des sources (vidéos, documents) dans l'Atelier par mots-clés, "
                     "auteur ou format. Renvoie les métadonnées, pas la transcription. "
                     "Accepte aussi un lien YouTube ou un identifiant de vidéo.",
         inputSchema={"type": "object", "properties": {
             "q": {"type": "string", "description": "Mots-clés (titres, auteurs, texte), ou un lien YouTube."},
             "auteur": {"type": "string", "description": "Auteur exact."},
             "format": {"type": "string", "description": "Vidéo, Short, PDF, EPUB, Document…"},
             "avec_texte": {"type": "boolean", "description": "Ne garder que les sources transcrites."},
             "limite": {"type": "integer", "description": "Nombre de sources (max 200, défaut 25)."}},
             "additionalProperties": False},
         handler=chercher_sources),
    dict(name="chercher_passages",
         description="LA recherche à utiliser pour répondre à une question sur le contenu : "
                     "cherche dans TOUTES les transcriptions et renvoie les passages horodatés "
                     "correspondants, avec source, auteur et horodatage. Si la question contient "
                     "un lien YouTube, cette vidéo est interrogée en priorité.",
         inputSchema={"type": "object", "properties": {
             "q": {"type": "string", "description": "Question ou mots-clés à chercher (lien YouTube accepté)."},
             "limite": {"type": "integer", "description": "Sources à détailler (défaut 6, max 20)."},
             "sources_max": {"type": "integer", "description": "Sources candidates à balayer (défaut 12)."}},
             "required": ["q"], "additionalProperties": False},
         handler=chercher_passages),
    dict(name="lire_source",
         description="Lire une source précise : transcription horodatée (complète ou filtrée sur "
                     "un mot-clé), métadonnées, synthèse IA, tags et notes. L'identifiant peut être "
                     "celui de l'Atelier, l'identifiant YouTube ou le lien de la vidéo.",
         inputSchema={"type": "object", "properties": {
             "source_id": {"type": "string", "description": "Identifiant de la source, identifiant YouTube ou lien."},
             "q": {"type": "string", "description": "Filtrer la transcription sur ces mots-clés."},
             "depuis": {"type": "integer", "description": "Premier passage de la page (0 par défaut, ou la valeur `suite`)."}},
             "required": ["source_id"], "additionalProperties": False},
         handler=lire_source),
    dict(name="lister_idees",
         description="Lister les idées sourcées de l'Atelier, avec notes, tags, statut et références. "
                     "Par défaut seules les idées actives (non archivées) ; archivees=true pour la "
                     "pile archivée, tout=true pour tout.",
         inputSchema={"type": "object", "properties": {
             "q": {"type": "string"}, "archivees": {"type": "boolean"},
             "tout": {"type": "boolean", "description": "Inclure aussi les idées archivées."},
             "limite": {"type": "integer", "description": "Défaut 30, max 200."},
             "offset": {"type": "integer"}},
             "additionalProperties": False},
         handler=lister_idees),
    dict(name="lire_idee",
         description="Lire une idée complète (notes, importance, statut, références et citations).",
         inputSchema={"type": "object", "properties": {
             "idea_id": {"type": "string"}}, "required": ["idea_id"], "additionalProperties": False},
         handler=lire_idee),
    dict(name="rapprochements",
         description="Paires d'idées proches (similarité de mots et de tags) : pistes de "
                     "regroupement pour trier, pas une équivalence sémantique.",
         inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
         handler=rapprochements),
    dict(name="lister_tags",
         description="Tags posés sur les sources (annotations) avec leur nombre d'occurrences : "
                     "utile pour réutiliser les tags déjà en place plutôt que d'en inventer.",
         inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
         handler=lister_tags),
    dict(name="lister_livres",
         description="Lister les projets de livre (id, titre, nombre de chapitres).",
         inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
         handler=lister_livres),
    dict(name="creer_livre",
         description="Créer un nouveau projet de livre (vide) : le bon geste pour démarrer un livre. "
                     "Renvoie son book_id, à passer ensuite à ajouter_chapitre, definir_intention et "
                     "lire_livre. Ne touche à aucun livre existant.",
         inputSchema={"type": "object", "properties": {
             "title": {"type": "string"}, "author": {"type": "string"}},
             "required": ["title"], "additionalProperties": False},
         handler=creer_livre),
    dict(name="supprimer_livre",
         description="Supprimer un projet de livre entier, chapitres compris. Le projet principal "
                     "book-main est protégé. Refuse sans force=true si le livre contient du texte : "
                     "la suppression est définitive, l'historique du livre part avec lui.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "force": {"type": "boolean"}},
             "required": ["book_id"], "additionalProperties": False},
         handler=supprimer_livre),
    dict(name="lire_livre",
         description="Plan d'un projet de livre : intention (brief), matières rattachées, et pour chaque "
                     "chapitre son numéro, son titre, son objectif, sa taille en mots et ses sources. "
                     "Le manuscrit complet (souvent plus de 200 Ko) ne tient pas dans un appel : pour lire "
                     "le texte, utiliser lire_chapitre. avec_texte=true ne renvoie que ce qui tient.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Défaut : book-main."},
             "avec_texte": {"type": "boolean", "description": "Inclure le texte, tronqué à la taille d'une réponse. À éviter sur un gros livre."}},
             "additionalProperties": False},
         handler=lire_livre),
    dict(name="lire_chapitre",
         description="Lire le TEXTE d'un chapitre, entier ou page par page — c'est la façon de lire un "
                     "manuscrit sans rien perdre. `chapitre` accepte le numéro (1..N), le titre ou "
                     "l'identifiant. Si la réponse contient `suite`, rappeler l'outil avec depuis=suite "
                     "pour la page suivante ; suite=null signifie que le chapitre est lu en entier.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Défaut : book-main."},
             "chapitre": {"type": "string", "description": "Numéro (1..N), titre ou identifiant du chapitre."},
             "depuis": {"type": "integer", "description": "Premier bloc de la page (0 par défaut, ou la valeur `suite`)."}},
             "required": ["chapitre"], "additionalProperties": False},
         handler=lire_chapitre),
    dict(name="exporter_livre",
         description="Exporter le livre en Markdown (chapitres, idées, citations et bibliographie).",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Défaut : book-main."}},
             "additionalProperties": False},
         handler=exporter_livre),
    dict(name="modifier_idees",
         description="Trier des idées en masse (max 200) : tags, statut « Relue »/« À vérifier », "
                     "favori, archivage. L'archivage est réversible : c'est le bon levier de tri.",
         inputSchema={"type": "object", "properties": {
             "idea_ids": {"type": "array", "items": {"type": "string"}},
             "tags": {"type": "array", "items": {"type": "string"}},
             "mode": {"type": "string", "enum": ["add", "remove", "replace"]},
             "statut": {"type": "string", "description": "« Relue » ou « À vérifier »."},
             "liked": {"type": "boolean"}, "archived": {"type": "boolean"}},
             "required": ["idea_ids"], "additionalProperties": False},
         handler=modifier_idees),
    dict(name="modifier_sources",
         description="Classer des sources en masse (max 200) : tags, favori, archivage.",
         inputSchema={"type": "object", "properties": {
             "source_ids": {"type": "array", "items": {"type": "string"}},
             "tags": {"type": "array", "items": {"type": "string"}},
             "mode": {"type": "string", "enum": ["add", "remove", "replace"]},
             "liked": {"type": "boolean"}, "archived": {"type": "boolean"}},
             "required": ["source_ids"], "additionalProperties": False},
         handler=modifier_sources),
    dict(name="creer_idee",
         description="Créer une idée sourcée. Au moins une référence {source_id, start, end} est "
                     "obligatoire : reprenez les horodatages renvoyés par chercher_passages.",
         inputSchema={"type": "object", "properties": {
             "title": {"type": "string"}, "notes": {"type": "string"},
             "nature": {"type": "string", "description": "Conseil, Méthode, Opinion, Fait vérifié…"},
             "importance": {"type": "string",
                            "enum": ["Fondamentale", "Opérationnelle", "Contextuelle"]},
             "tags": {"type": "array", "items": {"type": "string"}},
             "refs": {"type": "array", "items": {"type": "object", "properties": {
                 "source_id": {"type": "string"}, "start": {"type": "number"},
                 "end": {"type": "number"}, "quote": {"type": "string"}}}},
             "folder": {"type": "string"}, "status": {"type": "string"}},
             "required": ["title", "refs"], "additionalProperties": False},
         handler=creer_idee),
    dict(name="creer_dossier",
         description="Créer un dossier pour regrouper sources et idées autour d'un sujet.",
         inputSchema={"type": "object", "properties": {"name": {"type": "string"}},
                      "required": ["name"], "additionalProperties": False},
         handler=creer_dossier),
    dict(name="definir_intention",
         description="Renseigner l'intention du livre (brief) : ce que le livre doit transmettre, "
                     "à qui, la promesse et la voix. Prérequis pour l'accompagnement éditorial.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "intention": {"type": "string"},
             "reader": {"type": "string"}, "promise": {"type": "string"}, "voice": {"type": "string"}},
             "required": ["intention"], "additionalProperties": False},
         handler=definir_intention),
    dict(name="ajouter_chapitre",
         description="Ajouter un chapitre à un livre (titre, objectif, position facultative). "
                     "Crée une version du livre dans l'historique.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "title": {"type": "string"},
             "purpose": {"type": "string"}, "position": {"type": "integer"}},
             "required": ["title"], "additionalProperties": False},
         handler=ajouter_chapitre),
    dict(name="ajouter_texte_chapitre",
         description="Ajouter un paragraphe rédigé à un chapitre existant, avec les sources qui "
                     "l'appuient. Le texte est ajouté au manuscrit, jamais en remplacement.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "chapter_id": {"type": "string"},
             "text": {"type": "string"},
             "source_ids": {"type": "array", "items": {"type": "string"}}},
             "required": ["chapter_id", "text"], "additionalProperties": False},
         handler=ajouter_texte_chapitre),
    dict(name="renommer_chapitre",
         description="Renommer un chapitre existant et/ou corriger son objectif (purpose). "
                     "Sert aussi à reformuler un titre sans toucher au texte : rien n'est ajouté au manuscrit.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "chapter_id": {"type": "string"},
             "title": {"type": "string"}, "purpose": {"type": "string"}},
             "required": ["chapter_id"], "additionalProperties": False},
         handler=renommer_chapitre),
    dict(name="deplacer_chapitre",
         description="Déplacer un chapitre à une autre position dans le livre (0 = début), pour "
                     "réordonner le plan sans supprimer ni recréer de chapitre.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "chapter_id": {"type": "string"},
             "position": {"type": "integer"}},
             "required": ["chapter_id", "position"], "additionalProperties": False},
         handler=deplacer_chapitre),
    dict(name="supprimer_chapitre",
         description="Supprimer un chapitre du livre (utile pour retirer un chapitre créé en trop). "
                     "Refuse d'effacer un chapitre contenant du texte sans force=true : dans ce cas "
                     "le chapitre est perdu du manuscrit, mais reste récupérable dans l'historique du livre.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "chapter_id": {"type": "string"},
             "force": {"type": "boolean"}},
             "required": ["chapter_id"], "additionalProperties": False},
         handler=supprimer_chapitre),
    dict(name="remplacer_texte_chapitre",
         description="Remplacer TOUT le texte rédigé d'un chapitre par de nouveaux paragraphes "
                     "(au lieu d'en ajouter à la suite). À utiliser pour une réécriture : les "
                     "anciens paragraphes sont remplacés, les images du chapitre sont conservées "
                     "et les idées rattachées ne sont pas touchées. La version précédente reste "
                     "dans l'historique du livre.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "chapter_id": {"type": "string"},
             "paragraphs": {"type": "array", "items": {"type": "string"}},
             "text": {"type": "string"},
             "source_ids": {"type": "array", "items": {"type": "string"}},
             "keep_media": {"type": "boolean"}},
             "required": ["chapter_id"], "additionalProperties": False},
         handler=remplacer_texte_chapitre),
    dict(name="ajouter_source",
         description="Ajouter une source documentaire à la bibliothèque (texte collé, notes, article). "
                     "Elle devient consultable par chercher_sources, lire_source et analyser_sources.",
         inputSchema={"type": "object", "properties": {
             "title": {"type": "string"}, "author": {"type": "string"},
             "text": {"type": "string", "description": "Le contenu, une ligne par passage (horodatage optionnel en début de ligne)."},
             "segments": {"type": "array", "items": {"type": "object"}},
             "url": {"type": "string"}, "kind": {"type": "string"},
             "description": {"type": "string"}, "date": {"type": "string"},
             "tags": {"type": "array", "items": {"type": "string"}}},
             "required": ["title", "author"], "additionalProperties": False},
         handler=ajouter_source),
    dict(name="importer_youtube",
         description="Importer une vidéo YouTube par son lien : la source est créée tout de suite, la "
                     "transcription est récupérée en arrière-plan. Suivre avec etat_bibliotheque.",
         inputSchema={"type": "object", "properties": {
             "url": {"type": "string"}, "title": {"type": "string"}, "author": {"type": "string"}},
             "required": ["url"], "additionalProperties": False},
         handler=importer_youtube),
    dict(name="modifier_source",
         description="Corriger les métadonnées d'une source existante : titre, auteur, description, "
                     "format, date ou lien. Ne touche ni au texte ni aux idées.",
         inputSchema={"type": "object", "properties": {
             "source_id": {"type": "string"}, "title": {"type": "string"}, "author": {"type": "string"},
             "description": {"type": "string"}, "kind": {"type": "string"},
             "date": {"type": "string"}, "url": {"type": "string"}},
             "required": ["source_id"], "additionalProperties": False},
         handler=modifier_source),
    dict(name="supprimer_source",
         description="Supprimer une source de la bibliothèque. Refuse si des idées s'appuient dessus, "
                     "sauf force=true (les références sont alors nettoyées). Pour un simple retrait, "
                     "préférer annoter_source avec archived=true.",
         inputSchema={"type": "object", "properties": {
             "source_id": {"type": "string"}, "force": {"type": "boolean"}},
             "required": ["source_id"], "additionalProperties": False},
         handler=supprimer_source),
    dict(name="annoter_source",
         description="Classer une source : poser ses tags (c'est aussi ainsi qu'on valide les tags "
                     "proposés par l'analyse IA), la marquer favorite, l'archiver, la ranger dans un "
                     "dossier ou y déposer des notes personnelles.",
         inputSchema={"type": "object", "properties": {
             "source_id": {"type": "string"},
             "tags": {"type": "array", "items": {"type": "string"}},
             "liked": {"type": "boolean"}, "archived": {"type": "boolean"},
             "notes": {"type": "string"}, "folder": {"type": "string"}},
             "required": ["source_id"], "additionalProperties": False},
         handler=annoter_source),
    dict(name="ecrire_transcription",
         description="Écrire ou corriger la transcription d'une source : remplace le texte existant par "
                     "celui fourni (une ligne par passage, horodatage optionnel). Les idées déjà "
                     "extraites ne sont pas touchées.",
         inputSchema={"type": "object", "properties": {
             "source_id": {"type": "string"}, "text": {"type": "string"},
             "segments": {"type": "array", "items": {"type": "object"}},
             "language": {"type": "string"}},
             "required": ["source_id"], "additionalProperties": False},
         handler=ecrire_transcription),
    dict(name="supprimer_transcription",
         description="Retirer la transcription d'une source. La source, ses métadonnées et ses idées "
                     "restent dans la bibliothèque.",
         inputSchema={"type": "object", "properties": {"source_id": {"type": "string"}},
             "required": ["source_id"], "additionalProperties": False},
         handler=supprimer_transcription),
    dict(name="rafraichir_transcription",
         description="Relancer la récupération du texte d'une source YouTube dont la transcription "
                     "manque ou a échoué (travail en arrière-plan).",
         inputSchema={"type": "object", "properties": {"source_id": {"type": "string"}},
             "required": ["source_id"], "additionalProperties": False},
         handler=rafraichir_transcription),
    dict(name="supprimer_idee",
         description="Supprimer une idée. Pour l'écarter sans la perdre, utiliser plutôt "
                     "modifier_idees avec archived=true.",
         inputSchema={"type": "object", "properties": {"idea_id": {"type": "string"}},
             "required": ["idea_id"], "additionalProperties": False},
         handler=supprimer_idee),
    dict(name="renommer_dossier",
         description="Renommer un dossier. Les sources et idées rangées dedans ne bougent pas.",
         inputSchema={"type": "object", "properties": {
             "folder_id": {"type": "string"}, "name": {"type": "string"}},
             "required": ["folder_id", "name"], "additionalProperties": False},
         handler=renommer_dossier),
    dict(name="supprimer_dossier",
         description="Supprimer un dossier. Les sources et idées qu'il contenait sont détachées, "
                     "jamais supprimées.",
         inputSchema={"type": "object", "properties": {"folder_id": {"type": "string"}},
             "required": ["folder_id"], "additionalProperties": False},
         handler=supprimer_dossier),
    dict(name="analyser_sources",
         description="Lancer l'analyse IA de 1 à 20 sources : elle en extrait des idées sourcées et "
                     "des tags proposés. Consomme des crédits du fournisseur IA : sans confirme=true, "
                     "l'outil se contente d'annoncer le coût.",
         inputSchema={"type": "object", "properties": {
             "source_ids": {"type": "array", "items": {"type": "string"}},
             "confirme": {"type": "boolean"}},
             "required": ["source_ids"], "additionalProperties": False},
         handler=analyser_sources),
    dict(name="proposer_chapitres",
         description="Demander à l'IA un plan de chapitres pour une source transcrite (proposition à "
                     "valider ensuite). Consomme des crédits : sans confirme=true, l'outil annonce "
                     "seulement le coût.",
         inputSchema={"type": "object", "properties": {
             "source_id": {"type": "string"}, "confirme": {"type": "boolean"}},
             "required": ["source_id"], "additionalProperties": False},
         handler=proposer_chapitres),
    dict(name="synchroniser_bibliotheque",
         description="Importer les sources déposées sur le serveur (corpus et inventaires locaux). "
                     "Aucune source existante n'est écrasée.",
         inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
         handler=synchroniser_bibliotheque),
    dict(name="matieres_livre",
         description="Lister les sources qui nourrissent un projet de livre (l'onglet « Matière »), et celles "
                     "citées dans les chapitres sans y être rattachées. À appeler avant ajouter_sources_livre.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Identifiant du livre (défaut book-main)."}}},
         handler=matieres_livre),
    dict(name="ajouter_sources_livre",
         description="Rattacher des sources de la bibliothèque aux matières d'un projet de livre : c'est ce qui "
                     "alimente l'accompagnement éditorial. 60 sources maximum par livre ; les sources déjà "
                     "rattachées sont ignorées. Identifiants obtenus avec chercher_sources ou matieres_livre.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Identifiant du livre (défaut book-main)."},
             "source_ids": {"type": "array", "items": {"type": "string"},
                            "description": "Identifiants des sources à rattacher."}},
             "required": ["source_ids"]},
         handler=ajouter_sources_livre),
    dict(name="retirer_sources_livre",
         description="Détacher des sources des matières d'un projet de livre. Les sources, leurs transcriptions "
                     "et leurs idées restent dans la bibliothèque : seul le rattachement au projet est retiré.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Identifiant du livre (défaut book-main)."},
             "source_ids": {"type": "array", "items": {"type": "string"},
                            "description": "Identifiants des sources à détacher."}},
             "required": ["source_ids"]},
         handler=retirer_sources_livre),
    dict(name="lire_reglages",
         description="Connexion IA de l'atelier : fournisseur, modèle, adresse et instruction. La clé API "
                     "n'est jamais renvoyée ni modifiable ici.",
         inputSchema={"type": "object", "properties": {}},
         handler=lire_reglages),
    dict(name="lire_prompts_ia",
         description="Prompts des missions IA (analyse, réécriture, chapitres, éditorial…) : libellé, texte "
                     "courant, prompt d'origine, et si le texte a été personnalisé. À lire avant definir_prompt_ia.",
         inputSchema={"type": "object", "properties": {}},
         handler=lire_prompts_ia),
    dict(name="lister_modeles_ia",
         description="Modèles proposés par le fournisseur IA configuré, avec le modèle actuellement utilisé.",
         inputSchema={"type": "object", "properties": {}},
         handler=lister_modeles_ia),
    dict(name="lire_version_livre",
         description="Détail d'une version enregistrée d'un livre : libellé, date et diff mot à mot de chaque "
                     "changement. Utile avant restaurer_version_livre pour voir ce qui a bougé.",
         inputSchema={"type": "object", "properties": {
             "version_id": {"type": "string", "description": "Identifiant de version donné par historique_livre."}},
             "required": ["version_id"]},
         handler=lire_version_livre),
    dict(name="lister_fichiers",
         description="Médias de l'atelier : images (dont les couvertures possibles) et documents importés, "
                     "avec identifiant, nom, type et taille.",
         inputSchema={"type": "object", "properties": {}},
         handler=lister_fichiers),
    dict(name="suivre_redaction",
         description="État de l'accompagnement éditorial : sans job_id, les dernières préparations du livre ; "
                     "avec job_id, l'avancement et la proposition complète (plan, brouillon ou relecture) avec "
                     "les indices à passer à appliquer_proposition.",
         inputSchema={"type": "object", "properties": {
             "job_id": {"type": "string", "description": "Identifiant du travail renvoyé par lancer_redaction."},
             "book_id": {"type": "string", "description": "Sans job_id : le livre dont lister les préparations."}}},
         handler=suivre_redaction),
    dict(name="verifier_export_livre",
         description="Vérifier qu'un livre s'exporte (markdown, PDF ou EPUB) et obtenir la taille du fichier "
                     "produit. Le fichier lui-même reste dans l'atelier : le MCP ne transporte pas de binaire.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Identifiant du livre (défaut book-main)."},
             "format": {"type": "string", "enum": ["md", "pdf", "epub"],
                        "description": "Format à vérifier (défaut pdf)."}}},
         handler=verifier_export_livre),
    dict(name="definir_prompt_ia",
         description="Personnaliser le prompt d'une mission IA. Un texte vide rétablit le prompt d'origine. "
                     "Les clés viennent de lire_prompts_ia.",
         inputSchema={"type": "object", "properties": {
             "cle": {"type": "string", "description": "Clé du prompt (ex. editorial, analyse, chapitres)."},
             "texte": {"type": "string", "description": "Nouveau texte, 20 000 caractères maximum."}},
             "required": ["cle"]},
         handler=definir_prompt_ia),
    dict(name="regler_connexion_ia",
         description="Régler le modèle, l'adresse et l'instruction de l'IA du fournisseur déjà configuré. "
                     "La clé API ne passe jamais par le MCP : elle se saisit dans l'Atelier → Paramètres.",
         inputSchema={"type": "object", "properties": {
             "modele": {"type": "string", "description": "Modèle à utiliser (voir lister_modeles_ia)."},
             "base_url": {"type": "string", "description": "Adresse HTTPS du fournisseur actuel."},
             "instruction": {"type": "string", "description": "Consigne générale donnée à l'IA."}}},
         handler=regler_connexion_ia),
    dict(name="lancer_redaction",
         description="Demander à l'accompagnateur du livre une proposition : plan (plan de chapitres), draft "
                     "(brouillon d'un chapitre, chapter_id requis) ou review (relecture critique d'un chapitre). "
                     "Interroge l'IA : renvoie d'abord un devis, puis part avec confirme=true. Suivre ensuite "
                     "avec suivre_redaction, appliquer avec appliquer_proposition.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Identifiant du livre (défaut book-main)."},
             "mode": {"type": "string", "enum": ["plan", "draft", "review"],
                      "description": "Nature de la proposition (défaut plan)."},
             "chapter_id": {"type": "string", "description": "Chapitre visé : obligatoire pour draft et review."},
             "instruction": {"type": "string", "description": "Consigne particulière pour cette demande."},
             "confirme": {"type": "boolean",
                          "description": "true pour lancer réellement la génération (consomme des crédits)."}}},
         handler=lancer_redaction),
    dict(name="appliquer_proposition",
         description="Intégrer au manuscrit les éléments retenus d'une proposition éditoriale : picked est la "
                     "liste des indices (0 = premier élément) fournis par suivre_redaction. Sans picked, "
                     "l'outil montre seulement ce qui est en attente. C'est la seule façon d'écrire une "
                     "proposition dans le livre depuis l'extérieur.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Identifiant du livre (défaut book-main)."},
             "chapter_id": {"type": "string", "description": "Chapitre visé pour un brouillon ou une relecture."},
             "picked": {"type": "array", "items": {"type": "integer"},
                        "description": "Indices des éléments à intégrer."}}},
         handler=appliquer_proposition),
    dict(name="reecrire_transcription",
         description="Réécriture éditoriale d'une transcription : prose condensée (environ un tiers) et sourcée, "
                     "pour rendre une source exploitable dans un chapitre. Travail IA par lots : renvoie d'abord "
                     "un devis, puis part avec confirme=true.",
         inputSchema={"type": "object", "properties": {
             "source_id": {"type": "string", "description": "Source à réécrire (chercher_sources)."},
             "confirme": {"type": "boolean", "description": "true pour lancer réellement (consomme des crédits)."}},
             "required": ["source_id"]},
         handler=reecrire_transcription),
    dict(name="definir_couverture_livre",
         description="Choisir la première ou la quatrième de couverture d'un livre parmi les images de l'atelier "
                     "(lister_fichiers). Un asset_id vide retire la couverture. La variante choisie rejoint les "
                     "variantes conservées du livre.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Identifiant du livre (défaut book-main)."},
             "face": {"type": "string", "enum": ["front", "back"], "description": "front ou back (défaut front)."},
             "asset_id": {"type": "string", "description": "Identifiant de l'image à utiliser, vide pour retirer."}}},
         handler=definir_couverture_livre),
    dict(name="historique_livre",
         description="Lister les versions enregistrées d'un livre (date, libellé, changements) : chaque "
                     "écriture en crée une. Sert à retrouver un état antérieur.",
         inputSchema={"type": "object", "properties": {"book_id": {"type": "string", "description": "Défaut : book-main."}},
             "additionalProperties": False},
         handler=historique_livre),
    dict(name="restaurer_version_livre",
         description="Remettre un livre dans l'état d'une version enregistrée. L'état actuel est lui "
                     "aussi conservé dans l'historique, donc l'opération est réversible.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string"}, "version_id": {"type": "string"}},
             "required": ["version_id"], "additionalProperties": False},
         handler=restaurer_version_livre),
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


# --------------------------------------------------------------------------- MCP

def describe(tool):
    return dict(name=tool["name"], description=tool["description"], inputSchema=tool["inputSchema"])


def call_tool(name, arguments):
    tool = TOOLS_BY_NAME.get(name)
    if not tool:
        raise ApiError("Outil inconnu : %s" % name)
    return tool["handler"](arguments or {})


_SINK = None  # en mode HTTP, les réponses s'accumulent ici au lieu de partir sur stdout


def respond(message_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    if _SINK is not None:
        _SINK.append(payload)
        return
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def visible_tools():
    """Outils exposés au client — le mode lecture seule masque l'écriture."""
    if READ_ONLY:
        return [t for t in TOOLS if t["name"] not in WRITE_TOOLS]
    return list(TOOLS)


def handle(message):
    method = message.get("method", "")
    message_id = message.get("id")
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        respond(message_id, {
            "protocolVersion": asked if asked in KNOWN_PROTOCOLS else PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "Atelier : bibliothèque de sources, idées sourcées et projets de livre. "
                            "Commencez par etat_bibliotheque, utilisez chercher_passages pour "
                            "répondre sur le contenu, et citez toujours auteur, titre et horodatage.",
        })
    elif method == "notifications/initialized":
        return
    elif method == "ping":
        respond(message_id, {})
    elif method == "tools/list":
        respond(message_id, {"tools": [describe(t) for t in visible_tools()]})
    elif method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name", "")
        if READ_ONLY and name in WRITE_TOOLS:
            respond(message_id, {"content": [{"type": "text",
                     "text": "Serveur en lecture seule : l'outil %s n'est pas disponible." % name}],
                     "isError": True})
            return
        try:
            result = call_tool(name, params.get("arguments") or {})
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1)
            respond(message_id, {"content": [{"type": "text", "text": clip(text)}], "isError": False})
        except ApiError as error:
            respond(message_id, {"content": [{"type": "text", "text": str(error)}], "isError": True})
        except Exception as error:  # noqa: BLE001 — toute erreur devient une réponse lisible
            respond(message_id, {"content": [{"type": "text",
                     "text": "Erreur %s : %s" % (type(error).__name__, error)}], "isError": True})
    elif message_id is not None:
        respond(message_id, error={"code": -32601, "message": "Méthode non prise en charge : %s" % method})


def serve():
    sys.stderr.write("atelier-mcp %s : serveur prêt (base %s)\n"
                     % (SERVER_VERSION, api.base or " à détecter"))
    sys.stderr.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, list):
            for item in message:
                handle(item)
        else:
            handle(message)


# --------------------------------------------------------------------------- HTTP


# ──────────────────────────────────── OAuth 2.1 ────────────────────────────────────
# L'interface des connecteurs ChatGPT n'offre que « OAuth » ou « aucune authentification » :
# aucun champ pour un en-tête de clé. Le serveur se comporte donc aussi comme serveur
# d'autorisation : métadonnées de découverte, enregistrement dynamique du client, page de
# consentement (le MCP_HTTP_TOKEN y sert de secret), puis code + PKCE S256. Un seul fichier,
# aucune dépendance. Le jeton Bearer statique reste accepté pour les autres clients.

_OAUTH_LOCK = threading.Lock()
AUTH_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Autoriser {{client}} — Atelier</title>
<style>
body{margin:0;font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:#f6f5f0;color:#253e33;display:grid;place-items:center;min-height:100vh}
main{box-sizing:border-box;background:#fff;border:1px solid #e2e0d6;border-radius:14px;padding:28px;max-width:470px;width:calc(100% - 32px);box-shadow:0 12px 30px rgba(37,62,51,.08)}
h1{margin:0 0 6px;font-size:20px}
p.sub{margin:0 0 14px;color:#5d6d64;font-size:14px}
label{display:block;margin:16px 0 6px;font-size:13px;font-weight:600}
input[type=password]{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #d8d6cc;border-radius:9px;font-size:15px;background:#fdfcf9}
button{margin-top:16px;width:100%;padding:11px;border:0;border-radius:9px;background:#253e33;color:#fff;font-size:15px;cursor:pointer}
p.err{margin:14px 0 0;padding:10px 12px;border-radius:9px;background:#fdf1ee;color:#8c3b22;font-size:14px}
p.foot{margin:14px 0 0;color:#7a8880;font-size:12px}
</style></head><body><main>
<h1>Autoriser l’accès à votre Atelier</h1>
<p class="sub"><strong>{{client}}</strong> demande à se connecter à ce serveur MCP ({{redirect}}).</p>
<p class="sub">Saisissez le jeton du serveur MCP : il est vérifié ici, sur votre serveur, et n’est jamais transmis à {{client}}.</p>
{{error}}
<form method="post" action="/authorize">{{hidden}}
<label for="token">Jeton du serveur MCP</label>
<input id="token" name="token" type="password" autocomplete="off" autofocus required>
<button type="submit">Autoriser</button>
</form>
<p class="foot">Pour refuser, fermez simplement cet onglet : rien ne sera partagé.</p>
</main></body></html>
"""


def oauth_load():
    """État OAuth : clients enregistrés, codes en cours, jetons émis."""
    try:
        data = json.loads(OAUTH_STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"clients": data.get("clients") or {}, "codes": data.get("codes") or {},
            "tokens": data.get("tokens") or {}, "refresh": data.get("refresh") or {}}


def oauth_save(data):
    try:
        OAUTH_STORE.parent.mkdir(parents=True, exist_ok=True)
        temporary = OAUTH_STORE.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(OAUTH_STORE)
    except OSError as error:
        sys.stderr.write("atelier-mcp : état OAuth non écrit (%s)\n" % error)


def oauth_purge(data, now):
    """Retire codes, jetons et refresh expirés."""
    for bucket in ("codes", "tokens", "refresh"):
        data[bucket] = {key: value for key, value in data[bucket].items()
                        if float(value.get("expires") or 0) > now}


def oauth_access_valid(value):
    """Vrai si le jeton présenté est un jeton d'accès OAuth encore valide."""
    if not value:
        return False
    now = time.time()
    with _OAUTH_LOCK:
        data = oauth_load()
        oauth_purge(data, now)
        valid = any(secrets.compare_digest(key, value) for key in data["tokens"])
        oauth_save(data)
    return valid


def oauth_base(handler):
    """URL publique du serveur : MCP_PUBLIC_URL, sinon déduite de la requête (derrière un proxy)."""
    if OAUTH_PUBLIC_URL:
        return OAUTH_PUBLIC_URL
    forwarded = (handler.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    host = (forwarded or handler.headers.get("Host") or "").split(",")[0].strip()
    if not host:
        return ""
    scheme = (handler.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    # Derrière un proxy : https par défaut. En direct (tests, local) : http.
    return "%s://%s" % (scheme or ("https" if forwarded else "http"), host)


class McpHttpHandler(BaseHTTPRequestHandler):
    """Transport Streamable HTTP, sans session — pour les clients distants."""

    protocol_version = "HTTP/1.1"
    server_version = "atelier-mcp/%s" % SERVER_VERSION

    def log_message(self, fmt, *args):
        # Journal minimal : jamais le contenu des requêtes (jeton, requêtes de recherche).
        sys.stderr.write("[http] %s %s\n" % (self.address_string(), fmt % args))

    def _authorized(self):
        if not HTTP_TOKEN:
            return True
        header = self.headers.get("Authorization", "").strip()
        value = header[7:].strip() if header[:7].lower() == "bearer " else header
        if value and secrets.compare_digest(value, HTTP_TOKEN):
            return True
        # Jeton issu du flux OAuth (ChatGPT et autres clients hébergés).
        return oauth_access_valid(value)

    # ─────────────── OAuth 2.1 : métadonnées, enregistrement, consentement, jetons ───────────────
    def _read_body(self):
        """Lit le corps en entier — y compris en Transfer-Encoding: chunked — sinon les octets
        restants salissent la connexion que le proxy réutilise pour la requête suivante."""
        if (self.headers.get("Transfer-Encoding") or "").lower().strip() == "chunked":
            blocks = []
            while True:
                line = self.rfile.readline(9000).strip()
                if not line:
                    break
                try:
                    size = int(line.split(b";")[0], 16)
                except ValueError:
                    break
                if size == 0:
                    self.rfile.readline(9000)  # CRLF final
                    break
                blocks.append(self.rfile.read(size))
                self.rfile.read(2)  # CRLF après chaque bloc
            return b"".join(blocks)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        return self.rfile.read(length) if length else b""

    def _protected_resource(self, base):
        return {"resource": base + "/mcp", "resource_name": "Atelier des sources",
                "authorization_servers": [base], "bearer_methods_supported": ["header"],
                "scopes_supported": ["atelier"]}

    def _authorization_server(self, base):
        return {"issuer": base, "authorization_endpoint": base + "/authorize",
                "token_endpoint": base + "/token", "registration_endpoint": base + "/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"], "scopes_supported": ["atelier"]}

    def _authorize_page(self, params, error=""):
        """Page de consentement : le client autorisé y saisit le jeton du serveur MCP."""
        client_id = (params.get("client_id") or [""])[0]
        redirect_uri = (params.get("redirect_uri") or [""])[0]
        with _OAUTH_LOCK:
            client = oauth_load()["clients"].get(client_id)
        if not client:
            return self._write(400, {"error": "invalid_client",
                                     "error_description": "client_id inconnu : enregistrez le client avant d'autoriser"})
        if redirect_uri not in client.get("redirect_uris", []):
            return self._write(400, {"error": "invalid_request",
                                     "error_description": "redirect_uri non déclarée par ce client"})
        if (params.get("response_type") or [""])[0] != "code":
            return self._write(400, {"error": "unsupported_response_type",
                                     "error_description": "response_type=code attendu"})
        if (params.get("code_challenge_method") or [""])[0] != "S256" or not (params.get("code_challenge") or [""])[0]:
            return self._write(400, {"error": "invalid_request", "error_description": "PKCE S256 requis"})
        hidden = "".join('<input type="hidden" name="%s" value="%s">' % (html_escape(name), html_escape(value))
                         for name, values in params.items() if name != "token" for value in values)
        name = str(client.get("client_name") or "un client")[:80]
        site = urllib.parse.urlparse(redirect_uri).netloc or redirect_uri
        page = (AUTH_PAGE.replace("{{client}}", html_escape(name))
                        .replace("{{redirect}}", html_escape(site))
                        .replace("{{hidden}}", hidden)
                        .replace("{{error}}", error))
        return self._write(200, page.encode("utf-8"), content_type="text/html; charset=utf-8",
                           extra={"Cache-Control": "no-store"})

    def _register(self):
        """Enregistrement dynamique du client (RFC 7591) : ChatGPT s'annonce une fois."""
        try:
            payload = json.loads(self._read_body().decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._write(400, {"error": "invalid_client_metadata", "error_description": "JSON invalide"})
        uris = payload.get("redirect_uris") or []
        if isinstance(uris, str):
            uris = [uris]
        uris = [uri for uri in uris if isinstance(uri, str) and uri.startswith(("https://", "http://"))]
        if not uris:
            return self._write(400, {"error": "invalid_redirect_uri", "error_description": "redirect_uris manquant"})
        now = time.time()
        client_id = "atc_" + secrets.token_urlsafe(24)
        record = {"client_id": client_id, "client_name": str(payload.get("client_name") or "client MCP")[:80],
                  "redirect_uris": uris, "created": now, "token_endpoint_auth_method": "none"}
        with _OAUTH_LOCK:
            data = oauth_load()
            oauth_purge(data, now)
            data["clients"][client_id] = record
            oauth_save(data)
        sys.stderr.write("atelier-mcp : client OAuth enregistré (%s)\n" % record["client_name"])
        return self._write(201, {"client_id": client_id, "client_id_issued_at": int(now),
                                 "client_name": record["client_name"], "redirect_uris": uris,
                                 "token_endpoint_auth_method": "none",
                                 "grant_types": ["authorization_code", "refresh_token"],
                                 "response_types": ["code"]})

    def _authorize_submit(self):
        """Consentement donné : un code (cinq minutes) part vers le client, avec son state."""
        try:
            raw = self._read_body().decode("utf-8")
        except UnicodeDecodeError:
            return self._write(400, {"error": "invalid_request", "error_description": "encodage inattendu"})
        params = urllib.parse.parse_qs(raw, keep_blank_values=True)
        given = (params.pop("token", [""])[0] or "").strip()
        client_id = (params.get("client_id") or [""])[0]
        redirect_uri = (params.get("redirect_uri") or [""])[0]
        with _OAUTH_LOCK:
            client = oauth_load()["clients"].get(client_id)
        if not client or redirect_uri not in client.get("redirect_uris", []):
            return self._write(400, {"error": "invalid_request",
                                     "error_description": "client ou redirect_uri inconnus"})
        if HTTP_TOKEN and not secrets.compare_digest(given, HTTP_TOKEN):
            sys.stderr.write("atelier-mcp : autorisation refusée (jeton incorrect)\n")
            return self._authorize_page(params, error='<p class="err">Jeton incorrect. Réessayez.</p>')
        challenge = (params.get("code_challenge") or [""])[0]
        if ((params.get("response_type") or [""])[0] != "code"
                or (params.get("code_challenge_method") or [""])[0] != "S256" or not challenge):
            return self._write(400, {"error": "invalid_request", "error_description": "PKCE S256 requis"})
        now = time.time()
        code = secrets.token_urlsafe(32)
        with _OAUTH_LOCK:
            data = oauth_load()
            oauth_purge(data, now)
            data["codes"][code] = {"client_id": client_id, "redirect_uri": redirect_uri,
                                   "code_challenge": challenge,
                                   "scope": (params.get("scope") or ["atelier"])[0],
                                   "expires": now + OAUTH_CODE_TTL}
            oauth_save(data)
        query = {"code": code}
        state = (params.get("state") or [""])[0]
        if state:
            query["state"] = state
        target = redirect_uri + ("&" if "?" in redirect_uri else "?") + urllib.parse.urlencode(query)
        sys.stderr.write("atelier-mcp : autorisation accordée à %s\n" % client.get("client_name"))
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.close_connection = True

    def _token(self):
        """Échange code+PKCE (ou refresh) contre un jeton d'accès."""
        try:
            raw = self._read_body().decode("utf-8")
        except UnicodeDecodeError:
            raw = ""
        form = urllib.parse.parse_qs(raw, keep_blank_values=True)

        def field(name):
            return (form.get(name) or [""])[0].strip()

        grant, client_id, now = field("grant_type"), field("client_id"), time.time()
        with _OAUTH_LOCK:
            data = oauth_load()
            oauth_purge(data, now)
            client = data["clients"].get(client_id)
            if not client:
                return self._write(400, {"error": "invalid_client", "error_description": "client_id inconnu"})
            if grant == "authorization_code":
                code = field("code")
                record = data["codes"].get(code)
                verifier = field("code_verifier")
                if (not record or record.get("client_id") != client_id
                        or record.get("redirect_uri") != field("redirect_uri") or not verifier):
                    oauth_save(data)
                    return self._write(400, {"error": "invalid_grant",
                                             "error_description": "code inconnu, déjà utilisé, expiré, ou redirect_uri différente"})
                expected = base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode("ascii", "ignore")).digest()).rstrip(b"=").decode("ascii")
                if not secrets.compare_digest(expected, str(record.get("code_challenge") or "")):
                    # Le code n'est pas consommé : un client peut se tromper de code_verifier et réessayer.
                    oauth_save(data)
                    return self._write(400, {"error": "invalid_grant",
                                             "error_description": "code_verifier ne correspond pas au défi PKCE"})
                data["codes"].pop(code, None)
                scope = record.get("scope") or "atelier"
            elif grant == "refresh_token":
                previous = data["refresh"].pop(field("refresh_token"), None)
                if not previous or previous.get("client_id") != client_id:
                    oauth_save(data)
                    return self._write(400, {"error": "invalid_grant",
                                             "error_description": "refresh_token inconnu ou expiré"})
                scope = previous.get("scope") or "atelier"
            else:
                oauth_save(data)
                return self._write(400, {"error": "unsupported_grant_type",
                                         "error_description": "authorization_code ou refresh_token attendu"})
            refresh = "atr_" + secrets.token_urlsafe(32)  # rotation à chaque usage
            data["refresh"][refresh] = {"client_id": client_id, "expires": now + OAUTH_REFRESH_TTL, "scope": scope}
            access = "ata_" + secrets.token_urlsafe(32)
            data["tokens"][access] = {"client_id": client_id, "expires": now + OAUTH_ACCESS_TTL,
                                      "refresh": refresh, "created": now}
            oauth_save(data)
        sys.stderr.write("atelier-mcp : jeton émis pour %s (%s)\n" % (client.get("client_name"), grant))
        return self._write(200, {"access_token": access, "token_type": "Bearer",
                                 "expires_in": OAUTH_ACCESS_TTL, "refresh_token": refresh, "scope": scope},
                           extra={"Cache-Control": "no-store"})

    def _oauth_get(self, path):
        """Routes GET de la partie OAuth — True si la requête a été traitée."""
        if path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            base = oauth_base(self)
            if not base:
                self._write(400, {"error": "invalid_request", "error_description": "hôte inconnu"})
            else:
                self._write(200, self._protected_resource(base), extra={"Cache-Control": "no-store"})
            return True
        if path in ("/.well-known/oauth-authorization-server", "/.well-known/oauth-authorization-server/mcp"):
            base = oauth_base(self)
            if not base:
                self._write(400, {"error": "invalid_request", "error_description": "hôte inconnu"})
            else:
                self._write(200, self._authorization_server(base), extra={"Cache-Control": "no-store"})
            return True
        if path == "/authorize":
            query = urllib.parse.urlparse(self.path).query
            self._authorize_page(urllib.parse.parse_qs(query, keep_blank_values=True))
            return True
        return False

    def _oauth_post(self, path):
        """Routes POST de la partie OAuth — True si la requête a été traitée."""
        if path == "/register":
            self._register()
            return True
        if path == "/token":
            self._token()
            return True
        if path == "/authorize":
            self._authorize_submit()
            return True
        return False

    def _write(self, status, payload, content_type="application/json", extra=None, close=False):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _unknown_path(self):
        self._write(404, {"error": "chemin inconnu — utilisez POST /mcp"})

    def _unauthorized(self):
        # `resource_metadata` (RFC 9728) : c'est ce qui indique au client où découvrir OAuth.
        header = 'Bearer realm="atelier-mcp", scope="atelier"'
        base = oauth_base(self)
        if base:
            header += ', resource_metadata="%s/.well-known/oauth-protected-resource"' % base
        self._write(401, {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32001, "message": "Jeton d'accès requis"}},
                    extra={"WWW-Authenticate": header})

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if self._oauth_get(path):
            return
        if path == "/health":
            self._write(200, {"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION,
                              "outils": len(visible_tools()), "lecture_seule": READ_ONLY,
                              "oauth": bool(HTTP_TOKEN), "clients_oauth": len(oauth_load()["clients"]),
                              "base": api.base or "à détecter"})
        elif path in ("/mcp", "/"):
            # Aucun flux serveur→client : 405, comme la spécification l'autorise.
            self._write(405, {"jsonrpc": "2.0", "id": None,
                              "error": {"code": -32601, "message": "Utilisez POST sur /mcp"}},
                        extra={"Allow": "POST"})
        else:
            self._unknown_path()

    def do_DELETE(self):
        self._write(405, {"error": "serveur sans session"}, extra={"Allow": "POST"})

    def do_POST(self):
        global _SINK
        path = urllib.parse.urlparse(self.path).path
        if self._oauth_post(path):
            return
        # Le corps est TOUJOURS lu avant de répondre : un corps laissé dans la socket salit la
        # connexion que le proxy réutilise pour la requête suivante (400 « Bad request »).
        raw = self._read_body()
        if path not in ("/mcp", "/"):
            return self._unknown_path()
        if not self._authorized():
            return self._unauthorized()
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._write(400, {"jsonrpc": "2.0", "id": None,
                                     "error": {"code": -32700, "message": "JSON invalide"}})

        collected = []
        _SINK = collected
        try:
            for item in (message if isinstance(message, list) else [message]):
                handle(item)
        finally:
            _SINK = None

        if not collected:  # notifications seules : rien à renvoyer
            return self._write(202, b"", close=True)
        if "text/event-stream" in self.headers.get("Accept", ""):
            stream = "".join("event: message\ndata: %s\n\n" % json.dumps(payload, ensure_ascii=False)
                             for payload in collected)
            return self._write(200, stream.encode("utf-8"),
                               content_type="text/event-stream", close=True)
        self._write(200, collected if isinstance(message, list) else collected[0])


def serve_http():
    if not HTTP_TOKEN:
        sys.stderr.write("atelier-mcp : ATTENTION — MCP_HTTP_TOKEN vide, serveur ouvert à tous\n")
    httpd = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), McpHttpHandler)
    sys.stderr.write("atelier-mcp %s : HTTP prêt sur %s:%d/mcp (%d outils%s, base %s)\n"
                     % (SERVER_VERSION, HTTP_HOST, HTTP_PORT, len(visible_tools()),
                        ", lecture seule" if READ_ONLY else "", api.base or "à détecter"))
    if HTTP_TOKEN:
        sys.stderr.write("atelier-mcp : OAuth 2.1 actif (/authorize, /token, /register, "
                         "/.well-known/oauth-*) — état : %s\n" % OAUTH_STORE)
    sys.stderr.flush()
    httpd.serve_forever()


def selftest():
    """Vérifie l'API et les outils sans client MCP."""
    def show(label, call):
        try:
            print("— %s : %s" % (label, json.dumps(call(), ensure_ascii=False)[:600]))
        except Exception as error:  # noqa: BLE001 — diagnostic lisible avant tout
            print("— %s : ÉCHEC (%s) %s" % (label, type(error).__name__, error))

    print("Base utilisée :", api.base or "à détecter")
    print("Jeton :", "présent" if api.token else "ABSENT (ATELIER_TOKEN ou ATELIER_TOKEN_FILE)")
    show("etat_bibliotheque", lambda: etat_bibliotheque({}))
    show("chercher_passages('budget client')",
         lambda: chercher_passages({"q": "budget client", "limite": 2}))
    show("lister_idees", lambda: lister_idees({"limite": 2}))
    show("lister_tags", lambda: lister_tags({})["tags"][:5])
    show("lire_livre", lambda: {k: v for k, v in lire_livre({"book_id": "book-main"}).items()
                                if k != "chapitres"})
    print("— outils (%d) : %s" % (len(TOOLS), ", ".join(t["name"] for t in TOOLS)))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--tools" in sys.argv:
        print(json.dumps([describe(t) for t in visible_tools()], ensure_ascii=False, indent=1))
    elif "--http" in sys.argv:
        serve_http()
    else:
        serve()
