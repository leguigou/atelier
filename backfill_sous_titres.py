#!/usr/bin/env python3
"""Rattraper les transcriptions que l'application Atelier n'a pas réussi à importer.

L'application récupère les sous-titres avec `youtube_transcript_api`, que YouTube limite
régulièrement : la source reste alors avec le statut « Texte non récupéré » et zéro segment,
alors que la vidéo a des sous-titres. Ce script fait le travail autrement (yt-dlp), puis écrit
la transcription dans la source via l'API v1 — sans supprimer ni recréer la source.

Pour chaque source sans texte :
  1. sous-titres fr (sinon en) téléchargés en json3 avec yt-dlp ;
  2. conversion en segments [{start, duration, text}] ;
  3. métadonnées réelles (titre, auteur, durée, date, vues) ;
  4. PATCH /api/v1/sources/<id> — fusion, le reste du payload est conservé.

Une vidéo sans sous-titre récupérable est notée « rien » et n'est plus retentée (sauf --force).

Configuration (variables d'environnement) :
  ATELIER_BASE         URL de l'Atelier (défaut http://127.0.0.1:8765)
  ATELIER_TOKEN        jeton API « atelier_… »
  ATELIER_TOKEN_FILE   fichier contenant le jeton (défaut atelier-token.txt à côté du script)
  YTDLP                binaire yt-dlp (défaut : yt-dlp du PATH)

Usage :
  python3 backfill_sous-titres.py --liste            # ce qui serait traité, sans rien écrire
  python3 backfill_sous-titres.py --limite 10        # traite 10 sources
  python3 backfill_sous-titres.py                    # tout ce qui reste
  python3 backfill_sous-titres.py --avec-archives    # inclut les sources archivées
  python3 backfill_sous-titres.py --force            # retente même les échecs passés

L'état est conservé dans `backfill-etat.json` : le script reprend où il s'est arrêté.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BASE = "http://127.0.0.1:8765"
DEFAULT_TOKEN_FILE = "atelier-token.txt"
STATE_FILE = "backfill-etat.json"
LANGUAGES = ("fr", "en")  # ordre de préférence
PAUSE = 8.0               # secondes entre deux vidéos, pour ne pas se faire limiter
RETRY_PAUSE = 60.0        # attente après un HTTP 429 avant de réessayer


# --------------------------------------------------------------------------- API


def token():
    value = os.environ.get("ATELIER_TOKEN", "").strip()
    if value:
        return value
    path = Path(os.environ.get("ATELIER_TOKEN_FILE") or HERE / DEFAULT_TOKEN_FILE).expanduser()
    if path.exists():
        return path.read_text().strip()
    sys.exit("Jeton absent : ATELIER_TOKEN ou ATELIER_TOKEN_FILE (fichier %s)." % path)


def api(method, path, payload=None, base=None, bearer=None, timeout=60):
    url = "%s%s" % (base or os.environ.get("ATELIER_BASE", DEFAULT_BASE).rstrip("/"), path)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer %s" % bearer,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        raise RuntimeError("HTTP %s sur %s — %s" % (error.code, path, detail)) from None


def sans_texte(base, bearer):
    """Sources sans transcription, toutes pages confondues."""
    items, offset = [], 0
    while True:
        page = api("GET", "/api/v1/sources?has_transcript=false&limit=200&offset=%d" % offset,
                   base=base, bearer=bearer)
        batch = page.get("items") or []
        items += batch
        offset += len(batch)
        if not batch or offset >= int(page.get("total") or 0):
            return items


# --------------------------------------------------------------------------- yt-dlp


def ytdlp_bin():
    return os.environ.get("YTDLP") or shutil.which("yt-dlp") or "yt-dlp"


def run(args, timeout=180):
    result = subprocess.run([ytdlp_bin(), "--no-update", "--no-warnings"] + args,
                            capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def subtitles(url, folder, languages=LANGUAGES):
    """Télécharge les sous-titres (manuels ou automatiques) dans les langues demandées.

    Renvoie (segments, langue, automatique, raison) où raison vaut :
      ok                sous-titres récupérés
      sans_sous_titres  YouTube n'en propose aucun (définitif)
      limite            HTTP 429 : à retenter plus tard
      erreur            autre échec (réseau, extraction…)

    Attention : yt-dlp écrit « There are no subtitles … » sur **stdout**, pas stderr — les deux
    flux doivent être inspectés pour classer l'échec.
    """
    template = str(Path(folder) / "subs")
    _code, stdout, stderr = run(["--skip-download", "--write-subs", "--write-auto-subs",
                                 "--sub-langs", ",".join(languages), "--sub-format", "json3",
                                 "-o", template, url])
    for language in languages:
        for pattern in ("%s.%s.json3" % ("subs", language),
                        "%s.%s.auto.json3" % ("subs", language)):
            candidate = Path(folder) / pattern
            if candidate.exists():
                segments = parse_json3(candidate)
                if len(segments) >= 3:
                    return segments, language, "auto" in pattern, "ok"
    messages = (stdout or "") + "\n" + (stderr or "")
    if re.search(r"\b429\b|Too Many Requests", messages, re.IGNORECASE):
        return [], "", False, "limite"
    if re.search(r"has no subtitles", messages, re.IGNORECASE):
        return [], "", False, "sans_sous_titres"
    if re.search(r"no subtitles", messages, re.IGNORECASE):
        # Aucune piste dans les langues voulues : la vidéo en a peut-être une seule, la sienne.
        code, listing, _ = run(["--skip-download", "--list-subs", url])
        found = re.findall(r"^([A-Za-z]{2,3}(?:-[A-Za-z]+)?)\s+\S+", listing or "", re.MULTILINE)
        others = [code for code in dict.fromkeys(found) if code.lower() not in languages]
        if others:
            segments, language, automatic, raison = subtitles(url, folder, others[:1])
            if raison == "ok":
                return segments, language, automatic, "ok"
        return [], "", False, "sans_sous_titres"
    return [], "", False, "erreur"


def parse_json3(path):
    """json3 de YouTube → [{start, duration, text}] en secondes."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    segments = []
    for event in data.get("events") or []:
        text = "".join(part.get("utf8", "") for part in (event.get("segs") or []))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        segments.append(dict(start=round(event.get("tStartMs", 0) / 1000, 3),
                             duration=round(event.get("dDurationMs", 0) / 1000, 3),
                             text=text))
    return segments


def metadata(url):
    code, stdout, _ = run(["--skip-download", "--print",
                           "%(title)s|%(uploader)s|%(duration)s|%(upload_date)s|%(view_count)s|%(language)s",
                           url])
    if code != 0 or not stdout.strip():
        return {}
    parts = (stdout.strip().splitlines()[-1]).split("|")
    keys = ("title", "author", "duration", "date", "views", "language")
    out = {}
    for key, value in zip(keys, parts):
        value = value.strip()
        if key in ("duration", "views"):
            try:
                out["duration" if key == "duration" else "views"] = int(float(value))
            except ValueError:
                pass
        elif value and value.lower() != "na":
            out[key] = value
    return out


# --------------------------------------------------------------------------- Principal


def main():
    parser = argparse.ArgumentParser(description="Rattraper les transcriptions manquantes.")
    parser.add_argument("--base", help="URL de l'Atelier")
    parser.add_argument("--limite", type=int, default=0, help="nombre de sources à traiter (0 = tout)")
    parser.add_argument("--liste", action="store_true", help="afficher les candidates, ne rien écrire")
    parser.add_argument("--avec-archives", action="store_true", help="inclure les sources archivées")
    parser.add_argument("--force", action="store_true", help="retenter les échecs déjà notés")
    parser.add_argument("--pause", type=float, default=PAUSE,
                        help="secondes d'attente entre deux vidéos (défaut %.0f)" % PAUSE)
    parser.add_argument("--etat", default=str(HERE / STATE_FILE), help="fichier d'état (reprise)")
    args = parser.parse_args()

    base = args.base or os.environ.get("ATELIER_BASE", DEFAULT_BASE)
    bearer = token()
    state_path = Path(args.etat)
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}

    sources = sans_texte(base, bearer)
    if not args.avec_archives:
        sources = [s for s in sources if not (s.get("annotation") or {}).get("archived")]
    sources = [s for s in sources if s.get("youtube_id") or "youtube" in str(s.get("url", ""))]
    if not args.force:
        sources = [s for s in sources if state.get(s["id"], {}).get("resultat") != "rien"]
    if args.limite:
        sources = sources[:args.limite]

    print("%d source(s) à traiter" % len(sources))
    if args.liste or not sources:
        for source in sources:
            print("  %-14s %s" % (source["id"], str(source.get("title"))[:64]))
        return

    faits = {"ok": 0, "rien": 0, "limite": 0, "erreur": 0}
    for index, source in enumerate(sources, 1):
        sid = source["id"]
        ref = source.get("youtube_id") or sid
        url = source.get("url") or "https://www.youtube.com/watch?v=%s" % ref
        label = str(source.get("title"))[:52]
        with tempfile.TemporaryDirectory(prefix="atelier-subs-") as folder:
            meta = metadata(url)
            langues = list(LANGUAGES)
            native = str(meta.get("language") or "").split("-")[0].lower()
            if native and native not in langues:
                langues.append(native)
            try:
                segments, language, automatic, raison = subtitles(url, folder, langues)
            except subprocess.TimeoutExpired:
                segments, language, automatic, raison = [], "", False, "erreur"
            if raison == "limite":
                # YouTube limite les téléchargements : on laisse retomber la pression, puis un essai.
                print("[%d/%d] %-14s limite YouTube (429) — pause %.0f s puis nouvel essai"
                      % (index, len(sources), sid, RETRY_PAUSE))
                time.sleep(RETRY_PAUSE)
                try:
                    segments, language, automatic, raison = subtitles(url, folder, langues)
                except subprocess.TimeoutExpired:
                    segments, language, automatic, raison = [], "", False, "erreur"
            if raison != "ok" or not segments:
                resultat = "rien" if raison == "sans_sous_titres" else "limite"
                faits[resultat] += 1
                state[sid] = dict(resultat=resultat, titre=label, raison=raison,
                                  quand=time.strftime("%Y-%m-%d %H:%M"))
                libelle = {"sans_sous_titres": "RIEN — YouTube n'a aucune piste",
                           "limite": "À RETENTER — limite YouTube (429)",
                           "erreur": "ERREUR — extraction"}.get(raison, raison)
                print("[%d/%d] %-14s %s — %s" % (index, len(sources), sid, libelle, label))
            else:
                payload = dict(segments=segments, status="Récupérée", language=language,
                               automatic=automatic)
                for key in ("title", "author", "duration", "date", "views"):
                    if key in meta:
                        payload[key] = meta[key]
                payload.setdefault("title", source.get("title"))
                try:
                    api("PATCH", "/api/v1/sources/%s" % sid, payload, base=base, bearer=bearer)
                except RuntimeError as error:
                    faits["erreur"] += 1
                    state[sid] = dict(resultat="erreur", titre=label, detail=str(error),
                                      quand=time.strftime("%Y-%m-%d %H:%M"))
                    print("[%d/%d] %-14s ERREUR — %s" % (index, len(sources), sid, error))
                else:
                    faits["ok"] += 1
                    state[sid] = dict(resultat="ok", titre=label, segments=len(segments),
                                      langue=language, quand=time.strftime("%Y-%m-%d %H:%M"))
                    print("[%d/%d] %-14s OK — %d segments en %s — %s"
                          % (index, len(sources), sid, len(segments), language, label))
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(args.pause)

    print("\nRécupérées %(ok)d · sans sous-titre %(rien)d · à retenter %(limite)d · erreurs %(erreur)d"
          % faits)
    print("Détail dans %s" % state_path)


if __name__ == "__main__":
    main()
