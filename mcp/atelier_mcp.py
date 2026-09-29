#!/usr/bin/env python3
"""Serveur MCP (Model Context Protocol) pour l'Atelier — « des sources au livre ».

Expose la bibliothèque de l'Atelier (sources, transcriptions, idées, dossiers, livres)
à n'importe quel client MCP : Hermes, Claude Desktop, un agent maison…

Transport : stdio, JSON-RPC 2.0, protocole MCP. Aucune dépendance hors bibliothèque
standard : il suffit d'un python3 et d'un jeton API Atelier.

Configuration (variables d'environnement) :
  ATELIER_BASE           URL de l'Atelier (défaut : http://127.0.0.1:8765)
  ATELIER_FALLBACK_BASE  seconde URL essayée si la première est injoignable
  ATELIER_TOKEN          jeton API « atelier_… »
  ATELIER_TOKEN_FILE     fichier contenant le jeton (défaut : atelier-token.txt, à côté du script)
  ATELIER_MAX_CHARS      taille maximale d'une réponse d'outil (défaut 40000)

Lancer : python3 atelier_mcp.py            (mode serveur MCP sur stdin/stdout)
         python3 atelier_mcp.py --selftest (vérifie l'API sans client MCP)
         python3 atelier_mcp.py --tools    (liste les outils, sans réseau)
"""
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
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
    items = []
    for s in data.get("items", []):
        items.append(dict(
            id=s["id"], titre=s["title"], auteur=s.get("author", ""), format=s.get("kind", ""),
            date=s.get("date", ""), duree=stamp(s.get("duration")), segments=s.get("segment_count", 0),
            url=s.get("url", ""), statut=s.get("status", ""),
            tags=(s.get("annotation") or {}).get("tags", []),
            favori=bool((s.get("annotation") or {}).get("liked")),
            archive=bool((s.get("annotation") or {}).get("archived")),
        ))
    return dict(total=data.get("total", 0), renvoye=len(items), sources=items)


def _hit_windows(segments, needles, context=1, per_source=6):
    """Repère les segments contenant un mot-clé et rend la fenêtre autour."""
    hits = [i for i, seg in enumerate(segments) if any(n in folded(seg.get("text", "")) for n in needles)]
    windows, used = [], set()
    for index in hits:
        start = max(0, index - context)
        end = min(len(segments) - 1, index + context)
        if any(i in used for i in range(start, end + 1)):
            continue
        used.update(range(start, end + 1))
        windows.append(dict(
            debut=stamp(segments[start].get("start", 0)),
            start=segments[start].get("start", 0),
            page=segments[start].get("page"),
            section=segments[start].get("section"),
            texte=clip(" ".join(s.get("text", "").strip() for s in segments[start:end + 1]), 1800),
        ))
        if len(windows) >= per_source:
            break
    return windows


def chercher_passages(args):
    args = args or {}
    question = str(args.get("q") or "").strip()
    if not question:
        raise ApiError("Donnez une question ou des mots-clés (champ q).")
    needles = terms_of(question) or [folded(question)]
    limite = max(1, min(20, int(args.get("limite") or 6)))
    sources_max = max(1, min(30, int(args.get("sources_max") or 12)))

    candidates, catalogue = [], {}
    for needle in needles[:4]:
        page = api.call("GET", "/api/v1/sources",
                        {"q": needle, "has_transcript": "true", "limit": 200})
        for s in page.get("items", []):
            catalogue[s["id"]] = s
            candidates.append(s["id"])
    ranked = [sid for sid, _ in Counter(candidates).most_common(sources_max)]

    found = []
    for sid in ranked:
        meta = catalogue[sid]
        try:
            transcript = api.call("GET", "/api/v1/sources/%s/transcript" % sid)
        except ApiError:
            continue
        windows = _hit_windows(transcript.get("segments", []), needles)
        if not windows:
            continue
        found.append(dict(
            source_id=sid, titre=meta["title"], auteur=meta.get("author", ""),
            format=meta.get("kind", ""), date=meta.get("date", ""), url=meta.get("url", ""),
            passages=windows,
        ))
        if len(found) >= limite:
            break
    for item in found:
        item["duree"] = stamp(next(
            (s.get("duration") for s in [catalogue[item["source_id"]]]), 0))
    return dict(
        requete=question, mots_cles=needles, sources_candidates=len(catalogue),
        sources_avec_passages=len(found), resultats=found,
        note="Passages bruts : citez l'auteur, le titre et l'horodatage dans toute réponse.",
    )


def lire_source(args):
    args = args or {}
    sid = str(args.get("source_id") or "").strip()
    if not sid:
        raise ApiError("source_id requis.")
    source = api.call("GET", "/api/v1/sources/%s" % sid)
    segments = source.get("segments") or []
    annotation = source.get("annotation") or {}
    query = str(args.get("q") or "").strip()
    body = []
    if query:
        needles = terms_of(query) or [folded(query)]
        windows = _hit_windows(segments, needles, per_source=40)
        body = ["[%s] %s" % (w["debut"], w["texte"]) for w in windows]
    if not body:
        body = [
            "[%s] %s" % (stamp(s.get("start", 0)), s.get("text", "").strip())
            for s in segments if s.get("text")
        ]
    return dict(
        id=sid, titre=source.get("title", ""), auteur=source.get("author", ""),
        format=source.get("kind", ""), date=source.get("date", ""), url=source.get("url", ""),
        statut=source.get("status", ""), duree=stamp(source.get("duration", 0)),
        segments=len(segments), tags=annotation.get("tags", []),
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


def lire_livre(args):
    args = args or {}
    book_id = str(args.get("book_id") or "book-main")
    book = api.call("GET", "/api/v1/books/%s" % book_id)
    chapters = []
    for chapter in book.get("chapters", []):
        texte = "\n\n".join(
            b.get("text", "") for b in chapter.get("blocks", [])
            if b.get("type") in ("text", "heading", "quote")
        )
        chapters.append(dict(
            id=chapter["id"], titre=chapter.get("title", ""), objectif=chapter.get("purpose", ""),
            blocs=len(chapter.get("blocks", [])), mots=len(texte.split()),
            texte=clip(texte, 6000),
        ))
    return dict(id=book_id, titre=book.get("title", ""), auteur=book.get("author", ""),
                revision=book.get("_revision"), intention=book.get("brief", {}),
                sources_du_livre=book.get("source_ids", []), chapitres=chapters)


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


TOOLS = [
    dict(name="etat_bibliotheque",
         description="Vue d'ensemble de l'Atelier : nombre de sources et de transcriptions, "
                     "idées totales/archivées, dossiers, livres, tags principaux, travaux IA en cours.",
         inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
         handler=etat_bibliotheque),
    dict(name="chercher_sources",
         description="Chercher des sources (vidéos, documents) dans l'Atelier par mots-clés, "
                     "auteur ou format. Renvoie les métadonnées, pas la transcription.",
         inputSchema={"type": "object", "properties": {
             "q": {"type": "string", "description": "Mots-clés (titres, auteurs, texte)."},
             "auteur": {"type": "string", "description": "Auteur exact."},
             "format": {"type": "string", "description": "Vidéo, Short, PDF, EPUB, Document…"},
             "avec_texte": {"type": "boolean", "description": "Ne garder que les sources transcrites."},
             "limite": {"type": "integer", "description": "Nombre de sources (max 200, défaut 25)."}},
             "additionalProperties": False},
         handler=chercher_sources),
    dict(name="chercher_passages",
         description="LA recherche à utiliser pour répondre à une question sur le contenu : "
                     "cherche dans TOUTES les transcriptions et renvoie les passages horodatés "
                     "correspondants, avec source, auteur et horodatage.",
         inputSchema={"type": "object", "properties": {
             "q": {"type": "string", "description": "Question ou mots-clés à chercher."},
             "limite": {"type": "integer", "description": "Sources à détailler (défaut 6, max 20)."},
             "sources_max": {"type": "integer", "description": "Sources candidates à balayer (défaut 12)."}},
             "required": ["q"], "additionalProperties": False},
         handler=chercher_passages),
    dict(name="lire_source",
         description="Lire une source précise : transcription horodatée (complète ou filtrée sur "
                     "un mot-clé), métadonnées, synthèse IA, tags et notes.",
         inputSchema={"type": "object", "properties": {
             "source_id": {"type": "string", "description": "Identifiant de la source."},
             "q": {"type": "string", "description": "Filtrer la transcription sur ces mots-clés."}},
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
    dict(name="lire_livre",
         description="Lire un projet de livre : intention (brief), chapitres, objectifs, texte "
                     "actuel et sources rattachées.",
         inputSchema={"type": "object", "properties": {
             "book_id": {"type": "string", "description": "Défaut : book-main."}},
             "additionalProperties": False},
         handler=lire_livre),
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


def respond(message_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


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
        respond(message_id, {"tools": [describe(t) for t in TOOLS]})
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            result = call_tool(params.get("name", ""), params.get("arguments") or {})
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
        print(json.dumps([describe(t) for t in TOOLS], ensure_ascii=False, indent=1))
    else:
        serve()
