from __future__ import annotations
import json,os,sys
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/"output";HISTORY=ROOT/"data/youtube_upload_history.json";SCOPES=["https://www.googleapis.com/auth/youtube.upload"]
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
 known={str(x.get("source_url") or "") for x in history.get("items",[]) if x.get("source_url")}
 uploaded=[]
 for item in json.loads(mp.read_text(encoding="utf-8")).get("items",[]):
  source_url=str(item.get("source_url") or "")
  if source_url and source_url in known:
   print(f"Zaten yüklenmiş, tekrar atlandı: {item.get('title','')}")
   continue
  folder=ROOT/item["folder"];vp=ROOT/item["video"];tp=ROOT/item["thumbnail"];meta=json.loads((folder/"youtube-metadata.json").read_text(encoding="utf-8"))
  # Force public visibility here; metadata cannot accidentally override it.
  body={"snippet":{"title":meta["title"],"description":meta["description"],"tags":meta.get("tags",[]),"categoryId":meta.get("categoryId","25")},"status":{"privacyStatus":"public","selfDeclaredMadeForKids":bool(meta.get("madeForKids",False))}}
  req=api.videos().insert(part="snippet,status",body=body,media_body=MediaFileUpload(str(vp),chunksize=-1,resumable=True));response=None
  while response is None:_,response=req.next_chunk()
  vid=response.get("id")
  if vid and tp.exists():
   try:api.thumbnails().set(videoId=vid,media_body=MediaFileUpload(str(tp),mimetype="image/jpeg"))
   except Exception as e:print(f"Thumbnail yüklenemedi {vid}: {e}")
  record={"title":meta["title"],"video_id":vid,"url":f"https://www.youtube.com/watch?v={vid}","source_url":source_url}
  uploaded.append(record)
  if vid:
   history.setdefault("items",[]).append(record)
   known.add(source_url)
   HISTORY.parent.mkdir(parents=True,exist_ok=True)
   HISTORY.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8")
  print(f"Yüklendi (public): https://www.youtube.com/watch?v={vid}")
 (OUT/"upload_results.json").write_text(json.dumps(uploaded,ensure_ascii=False,indent=2),encoding="utf-8")
 return 0 if uploaded else 4
if __name__=="__main__":sys.exit(main())
