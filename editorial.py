"""Source-grounded editorial proposals. Generation never mutates a manuscript."""
import json, re


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
    budget = max(800, 60000 // len(ids))
    terms = set(app.tokens(' '.join([book['title'], brief.get('intention',''), chapter['title'] if chapter else '', data.get('instruction','')])))
    for sid in ids:
        s = app.get_source(sid)
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
    if not evidence:
        raise ValueError('Aucun texte exploitable dans ces sources. Ajoutez une transcription ou du texte aux documents numérisés.')
    return book, chapter, mode, evidence, omissions


def propose(studio, data, progress=None):
    app = studio.a
    book, chapter, mode, evidence, omissions = prepare(studio, data)
    if progress:progress('prompt',f'{len(evidence)} passages retenus · préparation de la demande…',35)
    schema = {
        'plan': 'chapters: [{title, purpose, evidence_ids: ["E1"]}], rationale: texte, questions: [texte]',
        'draft': 'paragraphs: [{text, evidence_ids: ["E1"]}], rationale: texte, questions: [texte]',
        'review': 'rationale: bilan, questions: [lacune, contradiction ou vérification nécessaire]'
    }[mode]
    prompt = app.prompt_text('editorial') + ' Réponds en JSON avec les champs suivants: ' + schema
    payload = dict(book=dict(title=book['title'], brief=book.get('brief',{}), plan=[dict(title=c['title'],purpose=c.get('purpose','')) for c in book['chapters']]),
                   chapter=dict(title=chapter['title'],text=chapter.get('notes','')[:18000],purpose=chapter.get('purpose','')) if chapter else None,
                   instruction=str(data.get('instruction',''))[:3000], excerpts=evidence)
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
                evidence=evidence,omitted=omissions,model=cfg['model'],created=app.now(),
                notice='Sélection de passages, pas lecture exhaustive. Vérifiez le sens et les sources avant intégration.')
