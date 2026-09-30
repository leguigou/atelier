"""Source-grounded editorial proposals. Generation never mutates a manuscript."""
import json, re

MAX_IDEAS = 24          # ideas mobilised at most in one proposal
IDEA_BUDGET = 14000     # characters reserved for the transcript passages behind the ideas
PASSAGE_CHARS = 2200    # characters kept per idea passage


def _source_cache(app, ids):
    cache = {}
    for sid in ids:
        try: cache[sid] = app.get_source(sid)
        except Exception: pass
    return cache


def _source(sources, app, sid):
    """Fetch on demand: an idea may point at a source that is not among the book's selection."""
    if sid and sources.get(sid) is None:
        try: sources[sid] = app.get_source(sid)
        except Exception: sources[sid] = False
    return sources.get(sid) or None


def _passages(app, sources, refs, budget):
    """Rebuild the transcript passages an idea points at, so the writer works from the real context."""
    passages, used = [], 0
    for ref in (refs or [])[:3]:
        source = _source(sources, app, ref.get('source_id'))
        if not source or not source.get('segments'): continue
        start = float(ref.get('start') or 0)
        end = float(ref.get('end') or start)
        picked = [seg for seg in source['segments'] if start <= float(seg.get('start') or 0) <= end] or [source['segments'][0]]
        text = ' '.join(seg.get('text', '') for seg in picked)[:PASSAGE_CHARS]
        if not text.strip(): continue
        locator = ('p. ' + str(ref['page'])) if ref.get('page') else ref.get('section') or (app.timestamp(start) if source['kind'] in ('Vidéo', 'Short') else 'extrait')
        passages.append(dict(source_id=source['id'], title=source['title'], author=source['author'], locator=locator, url=source.get('url', ''), quote=ref.get('quote', ''), text=text))
        used += len(text)
        if used >= budget: break
    return passages


def mobilised_ideas(app, chapter, terms, sources):
    """Ideas attached to the chapter first, completed by the closest visible ones — each with its passages."""
    with app.connect() as c:
        stored = {v['id']: v for v in app.objects(c, 'ideas')}
    attached = [stored[i] for i in (chapter or {}).get('ideas', []) if i in stored]
    taken = {i['id'] for i in attached}
    def relevance(idea):
        words = set(app.tokens(idea.get('title', '') + ' ' + idea.get('notes', '') + ' ' + ' '.join(idea.get('tags') or [])))
        return len(terms.intersection(words))
    ranked = sorted([i for i in stored.values() if not i.get('archived') and i['id'] not in taken and relevance(i) >= 2],
                    key=relevance, reverse=True)
    per_idea, used, out = max(1200, IDEA_BUDGET // max(1, min(MAX_IDEAS, len(attached) + len(ranked)))), 0, []
    forced = {i['id'] for i in attached}
    for idea in attached + ranked:
        if len(out) >= MAX_IDEAS or used >= IDEA_BUDGET: break
        passages = _passages(app, sources, idea.get('refs'), min(per_idea, IDEA_BUDGET - used))
        if not passages and idea['id'] not in forced: continue  # an idea we cannot ground in a transcript adds noise
        used += sum(len(x['text']) for x in passages)
        out.append(dict(label='I' + str(len(out) + 1), idea=idea, passages=passages))
    return out


def prepare(studio, data):
    app = studio.a
    book = studio.book(data.get('book_id'))
    mode = data.get('mode', 'plan')
    if mode not in ('plan', 'draft', 'review'):
        raise ValueError('Accompagnement inconnu.')
    brief = book.get('brief', {})
    if not brief.get('intention', '').strip():
        raise ValueError('Décrivez d’abord ce que vous voulez transmettre dans ce livre.')
    ids = book.get('source_ids', [])
    if not ids:
        raise ValueError('Choisissez les sources de ce livre avant de demander une proposition.')
    chapter = next((c for c in book['chapters'] if c['id'] == data.get('chapter_id')), None)
    if mode != 'plan' and not chapter:
        raise ValueError('Choisissez un chapitre.')
    # Bound provider input and distribute excerpts across every selected source.
    evidence, omissions = [], []
    sources = _source_cache(app, ids)
    budget = max(800, 60000 // len(ids))
    terms = set(app.tokens(' '.join([book['title'], brief.get('intention',''), chapter['title'] if chapter else '', (chapter or {}).get('purpose',''), data.get('instruction','')])))
    for sid in ids:
        s = sources.get(sid)
        if not s: continue
        segments = s.get('segments', [])
        if not segments:
            omissions.append(s['title']); continue
        ranked = sorted(enumerate(segments), key=lambda x: (-len(terms.intersection(app.tokens(x[1]['text']))), x[0]))
        chosen, size = [], 0
        for index, seg in ranked:
            if size >= budget: break
            text = seg['text'][:min(4000, budget-size)]
            if text.strip(): chosen.append((index, seg, text)); size += len(text)
            if len(chosen) >= 12: break
        for index, seg, text in sorted(chosen):
            label = 'E' + str(len(evidence)+1)
            locator = ('p. '+str(seg['page'])) if seg.get('page') else seg.get('section') or (app.timestamp(seg.get('start',0)) if s['kind'] in ('Vidéo','Short') else 'passage '+str(index+1))
            evidence.append(dict(id=label, source_id=sid, title=s['title'], author=s['author'], locator=locator, url=s.get('url',''), text=text))
    # A retained idea arrives with the transcript passages it was extracted from.
    ideas, idea_blocks = mobilised_ideas(app, chapter, terms, sources), []
    for entry in ideas:
        idea, passages = entry['idea'], entry['passages']
        first = passages[0] if passages else {}
        body = '\n'.join([t for t in [idea.get('notes', '')] + [p['text'] for p in passages] if t and t.strip()])
        if not body: continue
        idea_blocks.append(dict(label=entry['label'], idea_id=idea['id'], title=idea['title'], nature=idea.get('nature', ''),
                                importance=idea.get('importance', ''), status=idea.get('status', ''), notes=idea.get('notes', ''),
                                tags=idea.get('tags') or [], passages=[p['text'][:1200] for p in passages], evidence_ids=[]))
        evidence.append(dict(id=entry['label'], kind='idea', idea_id=idea['id'], idea_title=idea['title'], source_id=first.get('source_id', ''),
                             title=first.get('title', ''), author=first.get('author', ''), locator=first.get('locator', ''),
                             url=first.get('url', ''), text=body[:4*PASSAGE_CHARS], quote=first.get('quote', '')))
    if not evidence:
        raise ValueError('Aucun texte exploitable dans ces sources. Ajoutez une transcription ou du texte aux documents numérisés.')
    return book, chapter, mode, evidence, omissions, idea_blocks


METHOD = (' Procède en quatre temps et rends-les séparément. '
          'analysis: ce que les idées retenues et les extraits disent réellement, avec leurs références. '
          'interpretation: l’angle que tu retiens pour ce chapitre et ce lecteur, et ce que tu en fais. '
          'paragraphs: le texte du chapitre, dans la voix de l’auteur, chaque paragraphe appuyé sur au moins une référence. '
          'questions: ce qui reste à vérifier ou à trancher avant publication. '
          'Les références I… sont des idées déjà retenues par l’auteur (champ ideas), chacune accompagnée des passages de '
          'transcription d’où elle vient : leur nature (fait, opinion, témoignage, résultat déclaré) et leur statut '
          '(À vérifier, Relue) disent comment les employer — n’énonce jamais une opinion ou un témoignage comme un fait '
          'établi, et range dans questions toute affirmation encore à vérifier. Les références E… sont des extraits bruts. '
          'Si le chapitre contient déjà du texte écrit, prolonge-le et complète-le au lieu de le répéter ou de repartir de zéro.')

METHOD_REVIEW = (' Ta tâche est une relecture critique, pas une réécriture. Confronte le texte déjà écrit du chapitre aux idées '
                 'retenues et aux passages de transcription, puis rends quatre temps séparés. '
                 'analysis: ce que le chapitre affirme, en face de ce que les sources disent réellement — nomme explicitement '
                 'les affirmations sans source, les chiffres non sourcés et les contresens. '
                 'interpretation: le diagnostic, du plus grave au plus léger (contradictions internes, promesses '
                 'invérifiables, manques, répétitions, passages trop abstraits pour ce lecteur). '
                 'rationale: ce que tu recommandes, dans l’ordre — pour chaque point l’action concrète à mener (vérifier tel '
                 'chiffre, nuancer telle affirmation, déplacer tel passage), sans écrire le texte à la place de l’auteur. '
                 'questions: ce qui doit être tranché, vérifié ou complété avant publication, une question par point. '
                 'Les quatre temps sont obligatoires et aucun ne se répète : ne propose aucun paragraphe de remplacement, '
                 'la décision revient à l’auteur.')


def propose(studio, data, progress=None):
    app = studio.a
    book, chapter, mode, evidence, omissions, ideas = prepare(studio, data)
    if progress:progress('prompt',f'{len(evidence)} passages retenus · {len(ideas)} idées mobilisées · préparation de la demande…',35)
    schema = {
        'plan': 'chapters: [{title, purpose, evidence_ids: ["E1"]}], rationale: texte, questions: [texte]',
        'draft': 'analysis: texte (ce que les idées et les extraits disent, avec leurs références), interpretation: texte (l’angle retenu pour ce chapitre), paragraphs: [{text, evidence_ids: ["E1","I1"]}], rationale: texte, questions: [texte]',
        'review': 'analysis: texte (ce que le chapitre affirme, confronté aux idées et aux passages), interpretation: texte (diagnostic, du plus grave au plus léger), rationale: texte (les actions recommandées, dans l’ordre), questions: [lacune, contradiction ou vérification nécessaire]'
    }[mode]
    prompt = app.prompt_text('editorial') + {'draft': METHOD, 'review': METHOD_REVIEW}.get(mode, '') + ' Réponds en JSON avec les champs suivants: ' + schema
    written = '\n\n'.join((blk.get('text') or '').strip() for blk in (chapter.get('blocks') or []) if (blk.get('text') or '').strip()) if chapter else ''
    payload = dict(book=dict(title=book['title'], brief=book.get('brief',{}), plan=[dict(title=c['title'],purpose=c.get('purpose','')) for c in book['chapters']]),
                   chapter=dict(title=chapter['title'],text=(written or chapter.get('notes',''))[:18000],notes=chapter.get('notes','')[:4000],
                                purpose=chapter.get('purpose','')) if chapter else None,
                   instruction=str(data.get('instruction',''))[:3000], ideas=ideas, excerpts=evidence)
    cfg = app.settings()
    if progress:progress('generation',f'Génération avec {cfg["model"]}…',55)
    request=dict(model=cfg['model'],messages=[dict(role='system',content=prompt),dict(role='user',content=app.dumps(payload))],response_format={'type':'json_object'},max_tokens=16000)
    if cfg.get('provider')=='deepseek':request['reasoning_effort']='low'
    response=app.llm_request('/chat/completions',request)
    if progress:progress('validation','Réponse reçue · vérification du plan et des références…',85)
    try:
        raw = response['choices'][0]['message']['content'].strip()
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
        result = json.loads(raw)
        if not isinstance(result,dict):raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('La réponse IA est illisible. Aucun changement n’a été effectué.') from None
    known = {e['id']:e for e in evidence}
    key = 'chapters' if mode == 'plan' else 'paragraphs'
    clean = []
    if mode != 'review':
        items = result.get(key)
        if not isinstance(items,list) or not 1 <= len(items) <= 20:
            raise ValueError('Proposition vide ou trop longue. Aucun changement n’a été effectué.')
        for item in items:
            if not isinstance(item,dict):raise ValueError('Proposition mal formée.')
            refs = item.get('evidence_ids',[])
            if not isinstance(refs,list) or any(not isinstance(r,str) or r not in known for r in refs):
                raise ValueError('Une référence proposée n’existe pas dans les extraits. Proposition rejetée.')
            refs = list(dict.fromkeys(refs))
            if mode == 'draft' and not refs:raise ValueError('Un paragraphe sans source a été rejeté. Reformulez votre demande.')
            itemtext = str(item.get('title' if mode == 'plan' else 'text','')).strip()
            if not itemtext:raise ValueError('Proposition incomplète.')
            clean.append(dict(title=itemtext[:500],purpose=str(item.get('purpose',''))[:2500],evidence_ids=refs) if mode=='plan' else dict(text=itemtext[:12000],evidence_ids=refs))
    questions=result.get('questions',[])
    if not isinstance(questions,list):questions=[str(questions)]
    return dict(mode=mode,book_id=book['_book_id'],revision=book['_revision'],chapter_id=chapter['id'] if chapter else None,
                **{key:clean},rationale=str(result.get('rationale',''))[:8000],questions=[str(q)[:3000] for q in questions[:20]],
                analysis=str(result.get('analysis',''))[:8000],interpretation=str(result.get('interpretation',''))[:5000],
                ideas_used=[dict(label=b['label'],idea_id=b['idea_id'],title=b['title'],nature=b['nature'],importance=b['importance'],status=b['status']) for b in ideas],
                evidence=evidence,omitted=omissions,model=cfg['model'],created=app.now(),
                notice='Sélection de passages, pas lecture exhaustive. Vérifiez le sens et les sources avant intégration.')
