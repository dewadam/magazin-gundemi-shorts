from __future__ import annotations
import json, re, sys, unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
STOP = set('ve veya ile icin bir bu su da de mi ne kim nasil iste son sonra once yeni ilk kez magazin gundem oldu olan etti dedi haber haberi izle full hd ekrani linki video foto fotograf resmen sok dizi oyuncu unlu'.split())
PROGRAMS = {'masterchef', 'survivor'}
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
 return i.get('source_role') or ('discovery_only' if 'google news' in s or 'keşif' in s or 'kesif' in s else 'publisher')
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

def observations(items):
 result=[]
 for item in items:
  result.append(item)
  for other in item.get('also_reported_by',[]) or []:
   result.append({**item,**other,'summary':other.get('summary',item.get('summary','')),'source_role':other.get('source_role','publisher')})
 return result

def group_events(items):
 candidates=observations(items)
 # Prefer direct publishers; keep discovery feeds available only for event discovery.
 candidates.sort(key=lambda i:(role(i)!='discovery_only',len(tok(i.get('title',''))),len(tok(i.get('summary','')))),reverse=True)
 groups=[]
 for item in candidates:
  match=None
  for group in groups:
   # Match to representative only to prevent chain-merging different events.
   ok,_,_=compare(item,group[0])
   if ok:
    match=group;break
  if match is None: groups.append([item])
  else: match.append(item)
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
  output.append({**representative,'source_articles':sources,'publisher_domains':domains,
   'publisher_count':len(domains),'event_member_count':len(members),
   'discovery_item_count':sum(role(i)=='discovery_only' for i in members),
   'possible_syndication':possible_syndication,
   'verification_status':'manual_review_required', 'publication_approved':False,
   'coverage_label': 'multi_publisher' if len(domains)>1 else 'single_publisher'})
 output.sort(key=lambda x:(x['publisher_count'],not x['possible_syndication'],len(tok(x.get('title','')))),reverse=True)
 return output

def main():
 path=ROOT/'data/news_latest.json'
 if not path.exists(): print(f'Girdi bulunamadı: {path}',file=sys.stderr);return 2
 payload=json.loads(path.read_text(encoding='utf-8'))
 ranked=rank(payload.get('items',[]))
 multi=[x for x in ranked if x['publisher_count']>=2 and not x['possible_syndication']]
 selected=multi[:3]
 output={'generated_at':datetime.now(timezone.utc).isoformat(),
  'candidate_count':len(payload.get('items',[])), 'event_group_count':len(ranked),
  'multi_publisher_event_count':len(multi),'selection_count':len(selected),
  'target_count':3,'note':'Publisher coverage is a popularity signal, not factual verification. Exact headline matches across outlets are flagged as possible syndication and excluded from automatic top-three selection pending review.',
  'items':selected,'event_groups_preview':ranked[:30]}
 target=ROOT/'data/selected_news.json';target.parent.mkdir(parents=True,exist_ok=True)
 target.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(f'Ham aday: {output["candidate_count"]} | Olay grubu: {len(ranked)} | Çok yayın kuruluşlu olay (sendikasyon hariç): {len(multi)}')
 for idx,item in enumerate(selected,1):
  print(f'{idx}. [{item["publisher_count"]} yayın kuruluşu] {item["title"]}')
  print('   Kaynaklar: '+', '.join(s['source'] or s['source_domain'] for s in item['source_articles']))
  print('   Manuel kontrol: içerik ve kaynak bağımsızlığı henüz doğrulanmadı.')
 if len(selected)<3: print('UYARI: Üç çok kaynaklı ve olası sendikasyon dışı olay bulunamadı; kota zorlanmadı.')
 return 0

if __name__=='__main__': sys.exit(main())
