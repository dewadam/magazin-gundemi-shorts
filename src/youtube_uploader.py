from __future__ import annotations
import json,os,sys,re,unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import ResumableUploadError
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/"output";HISTORY=ROOT/"data/youtube_upload_history.json";SCOPES=["https://www.googleapis.com/auth/youtube.upload"]
DAILY_UPLOAD_LIMIT=max(1,int(os.getenv("YOUTUBE_DAILY_UPLOAD_LIMIT","3")))
TURKEY_TZ=ZoneInfo("Europe/Istanbul")
def norm_title(value):
 value=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode("ascii").lower()
 value=re.sub(r"[^a-z0-9]+"," ",value)
 value=re.sub(r"\bshorts\b"," ",value)
 return " ".join(value.split())
try:
 from event_matcher import same_event
except ImportError:
 from src.event_matcher import same_event

def main():
 raw=os.getenv("YOUTUBE_TOKEN_JSON","").strip()
 if not raw:print("YOUTUBE_TOKEN_JSON tanımlı değil; yükleme atlandı. Videolar artifact olarak saklanacak.");return 0
 try:
  info=json.loads(raw);creds=Credentials.from_authorized_user_info(info,scopes=SCOPES)
  if creds.expired and creds.refresh_token:creds.refresh(Request())
  if not creds.valid:raise RuntimeError("OAuth token geçersiz veya yenilenemedi.")
  api=build("youtube","v3",credentials=creds,cache_discovery=False)
 except Exception as e:print(f"YouTube OAuth kurulumu başarısız: {e}",file=sys.stderr);return 2
 mp=OUT/"manifest.json"
 if not mp.exists():print("Video manifest yok.",file=sys.stderr);return 3
 history={"items":[]}
 if HISTORY.exists():
  try:history=json.loads(HISTORY.read_text(encoding="utf-8"))
  except Exception:history={"items":[]}
 known_urls={str(x.get("source_url") or "").strip().rstrip("/").lower() for x in history.get("items",[]) if x.get("source_url")}
 known_titles={norm_title(x.get("title","")) for x in history.get("items",[]) if x.get("title")}
 today=datetime.now(TURKEY_TZ).date()
 def uploaded_today(record):
  stamp=record.get("uploaded_at")
  if not stamp:return False
  try:
   dt=datetime.fromisoformat(stamp.replace("Z","+00:00"))
   if dt.tzinfo is None:dt=dt.replace(tzinfo=TURKEY_TZ)
   return dt.astimezone(TURKEY_TZ).date()==today
  except (ValueError,TypeError):return False
 daily_count=sum(1 for record in history.get("items",[]) if uploaded_today(record))
 print(f"Türkiye tarihiyle bugünkü yükleme: {daily_count}/{DAILY_UPLOAD_LIMIT}")
 uploaded=[]
 if daily_count>=DAILY_UPLOAD_LIMIT:
  print("Günlük YouTube yükleme kotası dolu; bu çalıştırmada hiçbir video yüklenmeyecek.")
  (OUT/"upload_results.json").write_text("[]",encoding="utf-8")
  return 0
 for item in json.loads(mp.read_text(encoding="utf-8")).get("items",[]):
  if daily_count+len(uploaded)>=DAILY_UPLOAD_LIMIT:
   print(f"Günlük yükleme sınırı ({DAILY_UPLOAD_LIMIT}) doldu; kalan videolar atlandı.")
   break
  source_url=str(item.get("source_url") or "").strip().rstrip("/").lower()
  folder=ROOT/item["folder"];vp=ROOT/item["video"];tp=ROOT/item["thumbnail"];meta=json.loads((folder/"youtube-metadata.json").read_text(encoding="utf-8"))
  source_image=folder/"source-image.jpg"
  # Fail closed: never upload a video unless its original publisher image and generated thumbnail are valid.
  try:
   if not vp.is_file() or vp.stat().st_size<100_000:raise RuntimeError("video dosyası yok veya geçersiz")
   if not source_image.is_file() or source_image.stat().st_size<10_000:raise RuntimeError("kaynak haber görseli yok veya boş")
   if not tp.is_file() or tp.stat().st_size<10_000:raise RuntimeError("YouTube thumbnail dosyası yok veya boş")
   from PIL import Image
   with Image.open(source_image) as im:im.verify()
   with Image.open(tp) as im:im.verify()
  except Exception as e:
   print(f"GÖRSEL KONTROLÜ BAŞARISIZ — YouTube yüklemesi engellendi: {item.get('title','')}: {e}",file=sys.stderr)
   continue
  title_key=norm_title(meta.get("title") or item.get("title",""))
  prior_event=next((old for old in history.get("items",[]) if old.get("title") and same_event({"title":meta.get("title") or item.get("title","")},{"title":old.get("title","")})[0]),None)
  if (source_url and source_url in known_urls) or (title_key and title_key in known_titles) or prior_event:
   print(f"Zaten yüklenmiş (kaynak, başlık veya aynı olay eşleşti), tekrar atlandı: {meta.get('title','')}")
   continue
  # Force public visibility; metadata cannot override this.
  body={"snippet":{"title":meta["title"],"description":meta["description"],"tags":meta.get("tags",[]),"categoryId":meta.get("categoryId","25")},"status":{"privacyStatus":"public","selfDeclaredMadeForKids":bool(meta.get("madeForKids",False))}}
  req=api.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(vp),chunksize=-1,resumable=True));response=None
  try:
   while response is None:_,response=req.next_chunk()
  except ResumableUploadError as e:
   error_text=str(e)
   if "uploadLimitExceeded" in error_text or "exceeded the number of videos they may upload" in error_text:
    print("YouTube günlük/hesap yükleme sınırına ulaşıldı. Bu video yüklenmedi; kalan videolar atlanıyor. Limit yenilendiğinde tekrar deneyin.")
    (OUT/"upload_results.json").write_text(json.dumps(uploaded,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0
   raise
  vid=response.get("id")
  if vid and tp.exists():
   try:api.thumbnails().set(videoId=vid,media_body=MediaFileUpload(str(tp),mimetype="image/jpeg"))
   except Exception as e:print(f"Thumbnail yüklenemedi {vid}: {e}")
  record={"title":meta["title"],"video_id":vid,"url":f"https://www.youtube.com/watch?v={vid}","source_url":source_url,"uploaded_at":datetime.now(TURKEY_TZ).isoformat()}
  uploaded.append(record)
  if vid:
   history.setdefault("items",[]).append(record)
   if source_url:known_urls.add(source_url)
   if title_key:known_titles.add(title_key)
   HISTORY.parent.mkdir(parents=True,exist_ok=True)
   HISTORY.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8")
  print(f"Yüklendi (public): https://www.youtube.com/watch?v={vid}")
 (OUT/"upload_results.json").write_text(json.dumps(uploaded,ensure_ascii=False,indent=2),encoding="utf-8")
 if not uploaded:print("Yeni video yok; tüm videolar daha önce yüklenmiş. İşlem başarılı.")
 return 0
if __name__=="__main__":sys.exit(main())
