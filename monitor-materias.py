#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar de Pauta — Revista Duas Rodas.
Monitora os maiores portais/perfis de MOTO (Brasil + mundo) para a revista
noticiar rapido e nunca chegar atrasada.

Fontes SEM chave (sempre ativas):
  - Google News RSS por dominio de cada fonte  -> radar de materias (links reais, clicaveis)
  - Reddit (r/motorcycles, r/MotoGP)           -> sinal de tendencia global

Fontes COM chave (ligam sozinhas quando o secret existir no repo):
  - ANTHROPIC_API_KEY -> Claude agrupa em temas, acha o que esta bombando e sugere pauta
  - APIFY_TOKEN       -> posts recentes do Instagram dos concorrentes + redes da Duas Rodas

Saida: monitor-data.json (consumido pelo dashboard).
Roda de hora em hora no GitHub Actions. Cada fonte falha de forma silenciosa.
"""
import json, os, re, sys, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

OUT_FILE = 'monitor-data.json'
UA = {'User-Agent': 'Mozilla/5.0 (duas-rodas-radar)'}
AGORA = datetime.now(timezone.utc)
HOJE = AGORA.strftime('%Y-%m-%d')

# Perfil proprio da Duas Rodas (preencher quando tiver os handles/dominio):
DUAS_RODAS_IG = os.environ.get('DUAS_RODAS_IG', 'revistaduasrodas')  # ajuste se o @ for outro
DUAS_RODAS_SITE = os.environ.get('DUAS_RODAS_SITE', '')               # dominio do site, se houver

# ───────────────────────── FONTES MONITORADAS ─────────────────────────
# nome, instagram (sem @), site, escopo, tier
FONTES = [
    # Brasil - prioridade
    ('Grid Motors', 'gridmotors', 'https://www.gridmotors.com.br/', 'Brasil', 'Brasil'),
    ('Motociclismo', 'motociclismo_br', 'https://motociclismoonline.com.br/', 'Brasil', 'Brasil'),
    ('MOTO.com.br', 'moto.com.br', 'https://www.moto.com.br/', 'Brasil', 'Brasil'),
    ('Revista Moto Adventure', 'revistamotoadventure', 'https://motoadventure.com.br/', 'Brasil', 'Brasil'),
    ('Motonline', 'motonline', 'https://www.motonline.com.br/', 'Brasil', 'Brasil'),
    ('MotoRede', 'motorede', 'https://www.motorede.com.br/', 'Brasil', 'Brasil'),
    ('AndarDeMoto Brasil', 'andardemoto', 'https://www.andardemoto.com.br/', 'Brasil', 'Brasil'),
    # Mundo - prioridade
    ('Motorcycle News (MCN)', 'motorcyclenews', 'https://www.motorcyclenews.com/', 'Global', 'Mundo'),
    ('RideApart', 'rideapart', 'https://www.rideapart.com/', 'Global', 'Mundo'),
    ('Cycle World', 'cycleworld', 'https://www.cycleworld.com/', 'Global', 'Mundo'),
    ('Moto.it', 'motoit', 'https://www.moto.it/', 'Global', 'Mundo'),
    ('Bike EXIF', 'bikeexif', 'https://www.bikeexif.com/', 'Global', 'Mundo'),
    ('Bennetts BikeSocial', 'bennetts_bike', 'https://www.bennetts.co.uk/bikesocial', 'Global', 'Mundo'),
    ('Motorrad', 'motorradonline', 'https://www.motorradonline.de/', 'Global', 'Mundo'),
    ('Motorcyclist', 'motorcyclistonline', 'https://www.motorcyclistonline.com/', 'Global', 'Mundo'),
    ('Visordown', 'visordown', 'https://www.visordown.com/', 'Global', 'Mundo'),
    # MotoGP / Corrida (oficiais)
    ('MotoGP', 'motogp', 'https://www.motogp.com/', 'Global', 'Corrida'),
    ('WorldSBK (Superbike)', 'worldsbk', 'https://www.worldsbk.com/', 'Global', 'Corrida'),
    ('SuperBike Brasil', 'superbikebrasil', 'https://superbike.com.br/', 'Brasil', 'Corrida'),
    ('Crash MotoGP', 'crashmotogp_', 'https://www.crash.net/motogp', 'Global', 'Corrida'),
    ('GP do Brasil MotoGP', 'bra.mgp', 'https://motogpbra.com.br/', 'Brasil', 'Corrida'),
    ('MOTO1000GP', 'moto1000gp', 'https://m1gp.com.br/', 'Brasil', 'Corrida'),
    ('Box Repsol', 'box_repsol', 'https://www.boxrepsol.com/', 'Global', 'Corrida'),
    ('Ducati Corse', 'ducaticorse', 'https://www.ducati.com/ww/en/racing', 'Global', 'Corrida'),
    ('Yamaha Racing', 'yamaharacingcomofficial', 'https://www.yamaha-racing.com/', 'Global', 'Corrida'),
    ('GPOne', 'gponedotcom', 'https://www.gpone.com/en', 'Global', 'Corrida'),
    ('Grande Premio', 'grandepremio', 'https://www.grandepremio.com.br/', 'Brasil', 'Corrida'),
    ('Motorsport.com Brasil', 'motorsportcom.brasil', 'https://br.motorsport.com/', 'Brasil', 'Corrida'),
    ('The Race MotoGP', 'theracemoto', 'https://www.the-race.com/category/motogp/', 'Global', 'Corrida'),
    # Montadoras (oficiais)
    ('Ducati', 'ducati', 'https://www.ducati.com/', 'Global', 'Montadora'),
    ('Harley-Davidson', 'harleydavidson', 'https://www.harley-davidson.com/', 'Global', 'Montadora'),
    ('KTM', 'ktm_official', 'https://www.ktm.com/', 'Global', 'Montadora'),
    ('BMW Motorrad', 'bmwmotorrad', 'https://www.bmw-motorrad.com/', 'Global', 'Montadora'),
    ('Triumph Motorcycles', 'officialtriumph', 'https://www.triumphmotorcycles.com', 'Global', 'Montadora'),
    ('Kawasaki USA', 'kawasakiusa', 'https://www.kawasaki.com', 'Global', 'Montadora'),
    ('Honda Powersports US', 'honda_powersports_us', 'https://powersports.honda.com/', 'Global', 'Montadora'),
    ('Suzuki Cycles', 'suzukicycles', 'https://suzukicycles.com', 'Global', 'Montadora'),
    # Generalistas com cobertura de moto
    ('Quatro Rodas', 'quatro_rodas', 'https://quatrorodas.abril.com.br/', 'Brasil', 'Generalista'),
    ('UOL Carros', 'uolcarros', 'https://www.uol.com.br/carros/', 'Brasil', 'Generalista'),
    ('Motor1.com Brasil', 'motor1brasil', 'https://www.motor1.com.br/', 'Brasil', 'Generalista'),
    ('Motorsport.com', 'motorsportcom', 'https://www.motorsport.com/motogp/', 'Global', 'Generalista'),
    ('Autosport', 'autosport', 'https://www.autosport.com/motogp/', 'Global', 'Generalista'),
    ('Garagem 360', 'sitegaragem360', 'https://garagem360.com.br/', 'Brasil', 'Generalista'),
    ('Rider Magazine', 'ridermag', 'https://ridermagazine.com/', 'Global', 'Generalista'),
    # Complementares / criadores
    ('Celina Martins', 'celinamarttins', 'https://celinamarttins.com.br/', 'Brasil', 'Criador'),
    ('Diego Faustino (TF68)', 'treinamentofaustino68', 'https://www.lojafaustino68.com.br/', 'Brasil', 'Criador'),
    ('Willian Brito', 'willmn', '', 'Brasil', 'Criador'),
    ('MotoMundo', 'motomundo.com.br', 'https://motomundo.com.br/', 'Brasil', 'Criador'),
    ('MotoNews Brasil', 'motonewsbrasil', 'https://motonewsbrasil.com/', 'Brasil', 'Criador'),
]


def fetch(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def dominio(site):
    if not site:
        return ''
    net = urllib.parse.urlparse(site).netloc.lower().replace('www.', '')
    return net


def _limpa(x):
    """Remove travessao e tags (regra da casa: nunca travessao em texto gerado)."""
    if isinstance(x, str):
        x = re.sub(r'(?<=\d)\s*[–—]\s*(?=\d)', ' a ', x)
        x = re.sub(r'\s*[–—]\s*', ', ', x).replace('<', '').replace('>', '')
        return re.sub(r'^[,\s]+', '', x).strip()
    if isinstance(x, list):
        return [_limpa(i) for i in x]
    if isinstance(x, dict):
        return {k: _limpa(v) for k, v in x.items()}
    return x


def _ts_iso(pubdate):
    try:
        dt = parsedate_to_datetime(pubdate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        return AGORA.strftime('%Y-%m-%dT%H:%M:%SZ')


def _locale(escopo):
    if escopo == 'Brasil':
        return 'hl=pt-BR&gl=BR&ceid=BR:pt-150'
    return 'hl=en-US&gl=US&ceid=US:en'


def google_news_fonte(fonte, vistos, dias=10):
    """Materias recentes publicadas no dominio da fonte, via Google News RSS (site:)."""
    nome, ig, site, escopo, tier = fonte
    dom = dominio(site)
    if not dom:
        return []
    out = []
    try:
        q = f'site:{dom} when:{dias}d'
        url = ('https://news.google.com/rss/search?q=' + urllib.parse.quote(q) + '&' + _locale(escopo))
        root = ElementTree.fromstring(fetch(url))
        for item in list(root.iter('item'))[:8]:
            t = (item.findtext('title') or '').strip()
            l = (item.findtext('link') or '').strip()
            if not t or not l or l in vistos:
                continue
            # o titulo do Google News vem "Titulo - Fonte"; limpa o sufixo da fonte
            t = re.sub(r'\s*[\-–—]\s*[^\-–—]{1,40}$', '', t).strip() or t
            out.append({
                'titulo': _limpa(t), 'url': l, 'fonte': nome, 'ig': ig,
                'escopo': escopo, 'tier': tier, 'dominio': dom,
                'ts': _ts_iso(item.findtext('pubDate') or ''),
            })
            vistos.add(l)
    except Exception as e:
        print(f'[news:{nome}] {e}', file=sys.stderr)
    return out


def reddit_trends():
    """Sinal de tendencia global (titulos quentes em comunidades de moto)."""
    out = []
    for sub, q in [('motorcycles', 'top'), ('MotoGP', 'hot')]:
        try:
            url = f'https://www.reddit.com/r/{sub}/{q}.json?t=week&limit=12'
            data = json.loads(fetch(url))
            for ch in (data.get('data', {}).get('children', []) or []):
                p = ch.get('data', {})
                t = (p.get('title') or '').strip()
                if not t:
                    continue
                out.append({'titulo': t, 'sub': 'r/' + sub,
                            'score': p.get('score', 0), 'comentarios': p.get('num_comments', 0),
                            'url': 'https://reddit.com' + (p.get('permalink') or '')})
        except Exception as e:
            print(f'[reddit:{sub}] {e}', file=sys.stderr)
    out.sort(key=lambda x: -(x.get('score') or 0))
    return out[:15]


# ───────── tendencia por palavra-chave (fallback sem Claude) ─────────
STOP = set('de da do das dos a o e em no na para por com que the of to in on and a um uma '
           'moto motos motorcycle bike new nova novo 2026 2025 video'.split())
TERMOS = re.compile(r'\b(MotoGP|Superbike|WSBK|Ducati|Yamaha|Honda|Kawasaki|Suzuki|KTM|BMW|Triumph|'
                    r'Harley|Royal Enfield|Marc Marquez|Marquez|Bagnaia|Acosta|Bastianini|Quartararo|'
                    r'Vinales|Aprilia|Bezzecchi|el[ée]trica|el[ée]trico|big trail|naked|scooter|'
                    r'Interlagos|Goi[âa]nia|Brasil|lan[çc]amento|recall)\b', re.I)

def em_alta_keywords(materias):
    cont = {}
    exemplos = {}
    for m in materias:
        for termo in set(x.group(0) for x in TERMOS.finditer(m.get('titulo', ''))):
            k = termo.title()
            cont[k] = cont.get(k, 0) + 1
            exemplos.setdefault(k, []).append({'titulo': m['titulo'], 'url': m['url'], 'fonte': m['fonte']})
    tops = sorted(cont.items(), key=lambda kv: -kv[1])
    return [{'tema': k, 'mencoes': v, 'materias': exemplos[k][:4]} for k, v in tops if v >= 2][:8]


# ───────────────────────── Claude (opcional) ─────────────────────────
def claude_analise(materias, data):
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key or not materias:
        return
    try:
        amostra = [{'i': i, 't': m['titulo'], 'f': m['fonte'], 'e': m['escopo']}
                   for i, m in enumerate(materias[:90])]
        prompt = (
            'Voce e o editor de pauta da Revista Duas Rodas (revista de MOTO). Abaixo estao as materias '
            'mais recentes publicadas pelos maiores portais/perfis de moto do Brasil e do mundo (cada uma com '
            'indice i, titulo t, fonte f, escopo e). Objetivo: a Duas Rodas precisa saber o que esta bombando '
            'para noticiar rapido e nunca chegar atrasada.\n'
            'Tarefas:\n'
            '1) TENDENCIAS: agrupe as materias por TEMA/assunto e identifique os temas mais quentes (cobertos por '
            'varias fontes ou claramente relevantes). Para cada tema: titulo curto, 1 frase de resumo, lista de '
            'indices das materias relacionadas e um nivel "calor" (alto/medio).\n'
            '2) PAUTAS SUGERIDAS: 3 a 5 pautas que a Duas Rodas deveria publicar JA, com 1 frase de porque e '
            'urgencia (Agora/Hoje/Esta semana).\n'
            '3) RESUMO: 2 frases do panorama do dia no setor de moto.\n'
            'REGRAS: portugues do Brasil; NUNCA use travessao; nao invente materia que nao esteja na lista; '
            'use os indices reais.\n'
            'Responda APENAS JSON valido: {"tendencias":[{"tema":"","resumo":"","calor":"alto|medio","materias":[i,...]}],'
            '"pautas":[{"pauta":"","porque":"","urgencia":""}],"resumo":""}\n\nMATERIAS:\n'
            + json.dumps(amostra, ensure_ascii=False))
        body = json.dumps({'model': 'claude-haiku-4-5-20251001', 'max_tokens': 3000,
                           'messages': [{'role': 'user', 'content': prompt}]}).encode()
        req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body,
                                     headers={'x-api-key': key, 'anthropic-version': '2023-06-01',
                                              'content-type': 'application/json'})
        with urllib.request.urlopen(req, timeout=150) as r:
            out = json.loads(r.read())
        txt = out['content'][0]['text']
        m = re.search(r'\{.*\}', txt, re.S)
        d = _limpa(json.loads(m.group(0)))
        # resolve indices -> materias reais
        tend = []
        for t in d.get('tendencias', []) or []:
            mats = [materias[i] for i in (t.get('materias') or []) if isinstance(i, int) and 0 <= i < len(materias)]
            if t.get('tema'):
                tend.append({'tema': t['tema'], 'resumo': t.get('resumo', ''), 'calor': t.get('calor', 'medio'),
                             'mencoes': len(mats), 'materias': [{'titulo': x['titulo'], 'url': x['url'],
                                                                'fonte': x['fonte']} for x in mats[:5]]})
        if tend:
            data['em_alta'] = tend
        if d.get('pautas'):
            data['pautas'] = d['pautas'][:5]
        if d.get('resumo'):
            data['resumo_ia'] = d['resumo']
        print(f'[claude] {len(tend)} tendencias, {len(d.get("pautas") or [])} pautas')
    except Exception as e:
        print(f'[claude] {e}', file=sys.stderr)


# ───────────────────────── Apify (opcional) ─────────────────────────
def apify_call(actor, payload, token, timeout=300):
    url = f'https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}'
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={**UA, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def apify_instagram(data):
    """Posts recentes do Instagram dos concorrentes + seguidores da Duas Rodas."""
    token = os.environ.get('APIFY_TOKEN')
    if not token:
        return
    handles = [f[1] for f in FONTES if f[1]][:30]
    try:
        posts = apify_call('apify~instagram-post-scraper',
                           {'username': handles, 'resultsLimit': 2}, token)
        items = []
        for p in posts:
            u = p.get('url') or ''
            if not u:
                continue
            items.append({
                'perfil': p.get('ownerUsername') or '?',
                'legenda': (p.get('caption') or '')[:180],
                'url': u, 'likes': p.get('likesCount') or 0, 'coments': p.get('commentsCount') or 0,
                'thumb': p.get('displayUrl') or '',
                'ts': _data_ig(p.get('timestamp')),
            })
        items.sort(key=lambda x: x.get('ts') or '', reverse=True)
        data['instagram'] = items[:60]
        print(f'[apify-ig] {len(items)} posts')
    except Exception as e:
        print(f'[apify-ig] {e}', file=sys.stderr)
    # seguidores da propria Duas Rodas
    if DUAS_RODAS_IG:
        try:
            prof = apify_call('apify~instagram-profile-scraper', {'usernames': [DUAS_RODAS_IG]}, token)
            if prof:
                it = prof[0]
                data.setdefault('marca', {})['instagram'] = {
                    'handle': DUAS_RODAS_IG, 'seguidores': it.get('followersCount'),
                    'posts': it.get('postsCount')}
        except Exception as e:
            print(f'[apify-dr] {e}', file=sys.stderr)


def _data_ig(ts):
    if isinstance(ts, str) and re.match(r'\d{4}-\d{2}-\d{2}', ts):
        return ts[:19] + ('Z' if 'T' in ts and not ts.endswith('Z') else '')
    return ''


def marca_ga4(data):
    """Le ga4-data.json se existir (tráfego do site da Duas Rodas)."""
    try:
        with open('ga4-data.json', encoding='utf-8') as f:
            g = json.load(f)
        tot = g.get('totals') or {}
        data.setdefault('marca', {})['ga4'] = {
            'sessions': tot.get('sessions'), 'users': tot.get('users'),
            'updated_at': g.get('updated_at')}
        print('[ga4] ok')
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f'[ga4] {e}', file=sys.stderr)


def main():
    materias, vistos = [], set()
    for f in FONTES:
        materias.extend(google_news_fonte(f, vistos))
    materias.sort(key=lambda m: m.get('ts') or '', reverse=True)
    materias = materias[:300]

    data = {
        'updated_at': AGORA.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'fontes_monitoradas': [{'nome': n, 'ig': ig, 'site': s, 'escopo': e, 'tier': t}
                               for (n, ig, s, e, t) in FONTES],
        'materias': materias,
        'total_materias': len(materias),
        'materias_24h': len([m for m in materias if m.get('ts', '') >= (AGORA - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')]),
        'reddit': reddit_trends(),
        'em_alta': em_alta_keywords(materias),
        'pautas': [],
        'marca': {},
    }

    marca_ga4(data)
    apify_instagram(data)
    claude_analise(materias, data)  # sobrescreve em_alta/pautas/resumo se a chave existir

    data['integracoes'] = {
        'google_news': True,
        'reddit': bool(data['reddit']),
        'claude': bool(os.environ.get('ANTHROPIC_API_KEY')),
        'apify': bool(os.environ.get('APIFY_TOKEN')),
        'ga4': 'ga4' in data.get('marca', {}),
    }

    tmp = OUT_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_FILE)
    print(f'ok: {len(materias)} materias ({data["materias_24h"]} em 24h), '
          f'{len(data["em_alta"])} temas em alta, {len(data["reddit"])} trends reddit')


if __name__ == '__main__':
    main()
