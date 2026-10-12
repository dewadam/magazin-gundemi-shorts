from __future__ import annotations
import json, re, sys, unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
STOP = set('ve veya ile icin bir bu su da de mi ne kim nasil iste son sonra once yeni ilk kez magazin gundem oldu olan etti dedi haber haberi izle full hd ekrani linki video foto fotograf resmen sok dizi oyuncu unlu'.split())
PROGRAMS = {'masterchef', 'survivor'}
MAX_PER_PROGRAM = 1
ACTION_GROUPS = {
 'wedding': {'evlendi','nikah','dugun'}, 'divorce': {'bosandi','ayrildi'},
 'death': {'vefat','olum','hayatini','kaybetti'},
 'arrest': {'gozaltina','tutuklandi'},
 'elimination': {'elendi','eleme','adayi','potaya'},
 'immunity': {'dokunulmazlik'}, 'winner': {'kazandi','sampiyon'},
 'trailer': {'fragman','fragmani'}, 'birth': {'dogum','bebek','hamile'},
}

def norm(s):
 s = str(s or '').replace('ı','i').replace('İ','i')
 s = unicodedata.normalize('NFKD',s.casefold())
 return re.sub(r'\s+',' ',re.sub('[^a-z0-9]+',' ',''.join(x for x in s if not unicodedata.combining(x)))).strip()

def tok(s): return {x for x in norm(s).split() if len(x)>2 and x not in STOP}
def title_tokens(i): return tok(i.get('title',''))
def action(i):
 w=set(norm(i.get('title','')).split())
 return {k for k,v in ACTION_GROUPS.items() if w & v}
def episode(i): return set(re.findall(r'\b(\d{1,4})\s+bolum\b',norm(i.get('title',''))))
def publisher(i):
 return str(i.get('source_domain') or urlparse(str(i.get('url',''))).netloc).lower().removeprefix('www.')
def role(i):
 s=str(i.get('source','')).lower()
 configured=i.get('source_role')
 if configured == 'google_news_cluster':
  return 'discovery_only'
 return configured or ('discovery_only' if 'google news' in s or 'keşif' in s or 'kesif' in s else 'publisher')
def date(i):
 try: return datetime.fromisoformat(str(i.get('published_at')).replace('Z','+00:00'))
 except (TypeError,ValueError): return None

def compare(a,b):
 if a.get('url') and a.get('url')==b.get('url'): return (True,1.0,'same_url')
 ea,eb=episode(a),episode(b)
 if ea and eb and ea.isdisjoint(eb): return (False,0.0,'different_episode')
 da,db=date(a),date(b)
 if da and db:
  try:
   if abs((da-db).total_seconds())>72*3600: return (False,0.0,'different_date')
  except TypeError: pass
 aa,ab=action(a),action(b)
 if aa and ab and aa.isdisjoint(ab): return (False,0.0,'different_action')
 ta,tb=title_tokens(a),title_tokens(b)
 common=ta & tb
 if len(common)<2: return (False,0.0,'too_few_shared_title_terms')
 # A shared show name alone must never establish an event.
 distinctive=common-PROGRAMS
 if len(distinctive)<2: return (False,0.0,'shared_topic_only')
 j=len(common)/len(ta|tb)
 containment=len(common)/min(len(ta),len(tb))
 sequence=SequenceMatcher(None,norm(a.get('title')),norm(b.get('title'))).ratio()
 sa,sb=tok(a.get('summary','')),tok(b.get('summary',''))
 context=len(sa & sb)/max(1,min(len(sa),len(sb)))
 score=max(j,0.8*containment,0.9*sequence)
 matched=score>=0.72 or (score>=0.58 and context>=0.35)
 return matched,round(score,3),'strong_match' if matched else 'ambiguous'

def source_articles(item: dict) -> list[dict]:
    """Return unique direct-publisher references; discovery feeds never count as votes."""
    articles = []
    if role(item) != "discovery_only":
        articles.append({
            "source": item.get("source", "Bilinmeyen kaynak"),
            "source_domain": publisher(item),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "published_at": item.get("published_at"),
        })
    for other in item.get("also_reported_by", []) or []:
        if (other.get("source_role") or "publisher") == "discovery_only":
            continue
        domain = str(other.get("source_domain") or publisher(other)).lower().removeprefix("www.")
        articles.append({
            "source": other.get("source", "Bilinmeyen kaynak"),
            "source_domain": domain,
            "title": other.get("title", item.get("title", "")),
            "url": other.get("url", ""),
            "published_at": other.get("published_at"),
        })
    unique = {}
    for article in articles:
        key = article["source_domain"] or article["source"]
        if key and key not in unique:
            unique[key] = article
    return list(unique.values())


def observations(items):
 result=[]
 for item in items:
  result.append(item)
  for other in item.get('also_reported_by',[]) or []:
   result.append({**item,**other,'summary':other.get('summary',item.get('summary','')),'source_role':other.get('source_role','publisher')})
 return result

def group_events(items):
 # Use the dedicated conservative matcher shared with regression tests.
 try:
  from event_matcher import group_events as match_groups
 except ImportError:
  from src.event_matcher import group_events as match_groups
 candidates=observations(items)
 groups, review=match_groups(candidates)
 return groups

def rank(items):
 groups=group_events(items)
 output=[]
 for members in groups:
  publisher_items=[i for i in members if role(i)!='discovery_only' and publisher(i)]
  domains=sorted({publisher(i) for i in publisher_items})
  if not domains: continue
  representative=max(publisher_items,key=lambda i:(len(tok(i.get('title',''))),len(tok(i.get('summary','')))))
  sources=[]; seen=set()
  for item in publisher_items:
   domain=publisher(item)
   if domain in seen: continue
   seen.add(domain)
   sources.append({'source':item.get('source'), 'source_domain':domain,'url':item.get('url'),'title':item.get('title')})
  # Exact same titles across publishers can be syndicated wire copy, not independent confirmation.
  title_norms=[norm(i.get('title')) for i in publisher_items]
  possible_syndication=len(domains)>=2 and len(set(title_norms))==1
  # Count distinct article URLs as mentions; keep publisher reach separate so one outlet
  # publishing several updates cannot masquerade as broad independent coverage.
  direct_urls={str(i.get('url') or '') for i in publisher_items if i.get('url')}
  direct_article_count=len(direct_urls)
  discovery_count=sum(1 for i in members if role(i)=='discovery_only')
  latest=max((date(i) for i in members if date(i) is not None), default=None)
  age_hours=max(0.0,(datetime.now(timezone.utc)-latest.astimezone(timezone.utc)).total_seconds()/3600) if latest else 48.0
  # Trend proxy: distinct publisher reach is strongest, extra article mentions and
  # discovery-feed appearances add evidence, freshness breaks ties. Not view/share analytics.
  recency_score=max(0.0, 24.0-age_hours)/24.0
  # Independent publisher reach must dominate discovery-feed repetition.
  # Three Google News query feeds are discovery hints, not three independent publishers.
  popularity_score=round(10.0*len(domains)+0.5*max(0,direct_article_count-len(domains))+0.5*min(discovery_count,6)+1.0*recency_score,3)
  output.append({**representative,'source_articles':sources,'publisher_domains':domains,
   'publisher_count':len(domains),'direct_article_count':direct_article_count,'event_member_count':len(members),
   'discovery_item_count':discovery_count,'latest_published_at':latest.isoformat() if latest else None,
   'age_hours':round(age_hours,2),'popularity_score':popularity_score,
   'possible_syndication':possible_syndication,
   'verification_status':'manual_review_required', 'publication_approved':False,
   'coverage_label': 'multi_publisher' if len(domains)>1 else 'single_publisher'})
 # Trend-first ordering: spread across publishers/discovery feeds plus freshness, not a hard
 # requirement that every selected story appear in two publisher RSS feeds.
 output.sort(key=lambda x:(x['popularity_score'], x['publisher_count'], -x['age_hours']),reverse=True)
 return output


def topic_key(item):
 """Avoid filling the daily shortlist with several stories from one reality show."""
 title=norm(item.get('title',''))
 for program in PROGRAMS:
  if re.search(r'\b'+re.escape(program)+r'\b', title):
   return 'program:'+program
 return ''

def load_upload_history():
 path=ROOT/'data/youtube_upload_history.json'
 try:
  payload=json.loads(path.read_text(encoding='utf-8'))
  return [x for x in payload.get('items',[]) if isinstance(x,dict)]
 except (OSError,ValueError,TypeError):
  return []

def select_top_stories(ranked, limit=3, upload_history=None):
 """Select distinct events and exclude stories already uploaded to the channel."""
 try:
  from event_matcher import same_event
 except ImportError:
  from src.event_matcher import same_event
 upload_history=upload_history or []
 old_urls={str(x.get('source_url') or '').strip().rstrip('/').lower() for x in upload_history if x.get('source_url')}
 selected=[]
 seen_urls=set()
 seen_topics=set()
 for item in ranked:
  if role(item) == 'discovery_only' or not publisher(item):
   continue
  url=str(item.get('url') or '')
  if url and url.rstrip('/').lower() in old_urls:
   print(f"Önceden yayınlandığı için aday atlandı: {item.get('title','')}")
   continue
  # Headline text and source URL may change between publishers, so also compare
  # event identity against the saved upload history.
  duplicate=next((old for old in upload_history if old.get('title') and same_event(item, {'title':old.get('title','')})[0]),None)
  if duplicate:
   print(f"Önceden yayınlanan aynı olay atlandı: {item.get('title','')} (eski video: {duplicate.get('video_id','bilinmiyor')})")
   continue
  topic=topic_key(item)
  if topic and topic in seen_topics:
   continue
  # The grouping step is conservative; this second check prevents near-identical
  # headlines about the same event being selected twice when cluster members differ.
  if any(same_event(item, chosen)[0] for chosen in selected):
   continue
  selected.append(item)
  if url: seen_urls.add(url)
  if topic: seen_topics.add(topic)
  if len(selected) >= limit: break
 return selected

def expand_with_google_search(items, max_queries=0, results_per_query=0):
 # The collector now resolves Google News /read URLs in one batch. Re-querying
 # Google News for every headline triggers HTTP 429 and adds no reliable signal.
 # Keep only the collected publisher records; unresolved Google News cluster
 # cards remain discovery-only and can never be counted as publisher votes.
 expanded = list(items)
 direct = sum(1 for item in expanded if role(item) != "discovery_only" and publisher(item) and not publisher(item).startswith("google-news-cluster:"))
 unresolved = sum(1 for item in expanded if role(item) == "discovery_only")
 print(f"Doğrudan yayıncı adayı: {direct} | yayıncıya çözülemeyen Google News adayı: {unresolved} | toplam: {len(expanded)}")
 return expanded

def main():
 path=ROOT/'data/news_latest.json'
 if not path.exists(): print(f'Girdi bulunamadı: {path}',file=sys.stderr);return 2
 payload=json.loads(path.read_text(encoding='utf-8'))
 discovered=payload.get('items',[])
 expanded=expand_with_google_search(discovered)
 ranked=rank(expanded)
 multi=[x for x in ranked if x['publisher_count']>=2 and not x['possible_syndication']]
 history=load_upload_history()
 selected=select_top_stories(ranked, 3, history)
 output={'generated_at':datetime.now(timezone.utc).isoformat(),
  'candidate_count':len(payload.get('items',[])), 'event_group_count':len(ranked),
  'multi_publisher_event_count':len(multi),'selection_count':len(selected),
  'target_count':3,'note':'Trend score is a heuristic proxy based on distinct publisher coverage, discovery-feed repetition and recency; it is not a measured view/share count. Selected items still require verification and visual-rights review.',
  'items':selected,'event_groups_preview':ranked[:30]}
 target=ROOT/'data/selected_news.json';target.parent.mkdir(parents=True,exist_ok=True)
 target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(f'Ham aday: {output["candidate_count"]} | Olay grubu: {len(ranked)} | Çok yayın kuruluşlu olay (sendikasyon hariç): {len(multi)}')
 for idx,item in enumerate(selected,1):
  print(f'{idx}. Trend puanı {item["popularity_score"]} | {item["publisher_count"]} farklı yayın | {item.get("direct_article_count", 0)} doğrudan haber | {item["discovery_item_count"]} keşif görünümü')
  print('   '+item['title'])
  print('   Kaynaklar: '+', '.join(s['source'] or s['source_domain'] for s in item['source_articles']))
  print('   Manuel kontrol: içerik ve kaynak bağımsızlığı henüz doğrulanmadı.')
 if len(selected)<3: print('UYARI: Üç ayrı doğrudan yayıncı haberi bulunamadı; mevcut sayı seçildi.')
 return 0

if __name__=='__main__': sys.exit(main())
