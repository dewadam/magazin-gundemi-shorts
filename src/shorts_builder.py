from __future__ import annotations
import asyncio, html, json, logging, os, re, shutil, subprocess, sys, urllib.parse, urllib.request
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import edge_tts

ROOT=Path(__file__).resolve().parents[1]; INPUT=ROOT/"data/selected_news.json"; OUT=ROOT/"output"
W,H=1080,1920; VOICE=os.getenv("TTS_VOICE","tr-TR-EmelNeural")
BOLD=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]
REG=["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s"); LOG=logging.getLogger("shorts_builder")
def clean(s): return re.sub(r"\s+"," ",html.unescape(str(s or ""))).strip()
class Parser(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True); self.meta={}; self.title=[]; self.ps=[]; self.intitle=False; self.inp=False; self.skip=0; self.cur=[]
 def handle_starttag(self,tag,attrs):
  a={k.lower():(v or "") for k,v in attrs}
  if tag in ("script","style","noscript","svg","nav","footer","header"): self.skip+=1
  if tag=="meta":
   k=(a.get("property") or a.get("name") or "").lower()
   if k and a.get("content"): self.meta[k]=a["content"]
  if tag=="title": self.intitle=True
  if tag=="p" and not self.skip: self.inp=True; self.cur=[]
 def handle_endtag(self,tag):
  if tag in ("script","style","noscript","svg","nav","footer","header") and self.skip: self.skip-=1
  if tag=="title": self.intitle=False
  if tag=="p" and self.inp:
   s=clean(" ".join(self.cur))
   if len(s)>55: self.ps.append(s)
   self.inp=False; self.cur=[]
 def handle_data(self,data):
  if self.skip:return
  s=clean(data)
  if s and self.intitle:self.title.append(s)
  if s and self.inp:self.cur.append(s)
def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept-Language":"tr-TR,tr;q=0.9,en;q=0.5"})
 with urllib.request.urlopen(req,timeout=18) as r:return r.read(4000000).decode(r.headers.get_content_charset() or "utf-8",errors="replace")
def article_data(item):
 # Publisher HTML varies: try JSON-LD articleBody, OpenGraph metadata, semantic
 # article containers and normal paragraphs. Never treat Google News boilerplate as article text.
 candidates=[]
 for entry in [item, *(item.get("source_articles",[]) or []), *(item.get("also_reported_by",[]) or [])]:
  url=str(entry.get("url") or "")
  if url.startswith(("https://","http://")) and url not in candidates:
   candidates.append(url)
 errors=[]
 for url in candidates:
  try:
   raw=fetch(url)
   p=Parser();p.feed(raw)
   meta=p.meta
   # Many Turkish publishers expose the full article in JSON-LD even when the
   # visible HTML is rendered by JavaScript or paragraph extraction is blocked.
   jsonld_text=[]
   for match in re.findall(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>',raw,re.I|re.S):
    try:
     obj=json.loads(html.unescape(match).strip())
    except Exception:
     continue
    stack=obj if isinstance(obj,list) else [obj]
    while stack:
     node=stack.pop(0)
     if isinstance(node,list):
      stack.extend(node); continue
     if not isinstance(node,dict): continue
     graph=node.get("@graph")
     if isinstance(graph,list): stack.extend(graph)
     for key in ("articleBody","text","description"):
      value=node.get(key)
      if isinstance(value,str) and len(clean(value))>100:
       jsonld_text.append(clean(value))
     for key in ("mainEntity","mainEntityOfPage","article","subjectOf"):
      value=node.get(key)
      if isinstance(value,(dict,list)): stack.append(value)
   # Remove non-editorial blocks, then collect visible paragraphs and text from
   # common article/main containers as a fallback for sites without JSON-LD.
   stripped=re.sub(r'<(script|style|noscript|svg|nav|footer|header|aside)\b[^>]*>.*?</\1\s*>'," ",raw,flags=re.I|re.S)
   container_text=[]
   for block in re.findall(r'<(?:article|main|div|section)\b[^>]*(?:itemprop=["\']articleBody["\']|class=["\'][^"\']*(?:article|content|detail|news|story|text|body)[^"\']*["\'])[^>]*>(.*?)</(?:article|main|div|section)\s*>',stripped,re.I|re.S):
    text=clean(re.sub(r"<[^>]+>"," ",block))
    if len(text)>160:container_text.append(text)
   body_parts=[]
   body_parts.extend(jsonld_text)
   body_parts.extend(p.ps)
   body_parts.extend(container_text)
   # De-duplicate while preserving source order; strip cookie/site boilerplate.
   boilerplate=("çerez politikası","gizlilik politikası","reklam","bizi takip edin","abone olun","tüm hakları saklıdır","çerez tercihleri","devamı için tıklayın")
   seen=set(); kept=[]
   for part in body_parts:
    part=clean(part)
    key=part.casefold()
    if len(part)<65 or key in seen or any(x in key for x in boilerplate):continue
    seen.add(key);kept.append(part)
   body=" ".join(kept[:30])
   desc=clean(meta.get("og:description") or meta.get("description") or meta.get("twitter:description") or "")
   img=meta.get("og:image") or meta.get("twitter:image") or ""
   page_title=clean(meta.get("og:title") or " ".join(p.title) or item.get("title"))
   data={"page_title":page_title,"description":desc,"image_url":urllib.parse.urljoin(url,img) if img else clean(item.get("image_url") or ""),"body":body,"url":url}
   if len(body)>180 or len(desc)>180:
    LOG.info("Kaynak metni alındı: %s (gövde=%d, açıklama=%d)",urllib.parse.urlparse(url).netloc,len(body),len(desc))
    return data,""
   errors.append(f"{urllib.parse.urlparse(url).netloc}: yeterli haber metni yok (gövde={len(body)}, açıklama={len(desc)})")
  except Exception as e:
   errors.append(f"{urllib.parse.urlparse(url).netloc}: {str(e)[:120]}")
 return {}, "; ".join(errors[:4]) or "Erişilebilir yayıncı metni bulunamadı"

def fnt(size,bold=True):
 for p in (BOLD if bold else REG):
  if Path(p).exists():return ImageFont.truetype(p,size=size)
 return ImageFont.load_default()
def wrap(draw,text,ft,maxw):
 lines=[];line=""
 for word in clean(text).split():
  test=(line+" "+word).strip()
  if draw.textbbox((0,0),test,font=ft)[2]<=maxw:line=test
  else:
   if line:lines.append(line)
   line=word
 if line:lines.append(line)
 return lines
def background(url,path):
 if not url or not str(url).startswith(("https://","http://")):
  raise RuntimeError("Haber görseli bulunamadı; görselsiz video üretimi/yüklemesi yasak.")
 try:
  req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8"})
  with urllib.request.urlopen(req,timeout=20) as r:
   content_type=(r.headers.get("Content-Type") or "").lower()
   payload=r.read(8000000)
  if not payload or (content_type and not content_type.startswith("image/")):
   raise RuntimeError(f"URL bir görsel döndürmedi (Content-Type={content_type or 'bilinmiyor'}).")
  path.write_bytes(payload)
  with Image.open(path) as probe:
   probe.verify()
  return Image.open(path).convert("RGB")
 except Exception as e:
  path.unlink(missing_ok=True)
  raise RuntimeError(f"Haber görseli indirilemedi veya geçersiz; video oluşturulmayacak: {e}") from e

def posters(item,article,imagepath,poster,thumb):
 source_image=background(article.get("image_url",""),imagepath)
 title=clean(item.get("title","Magazin gündemi"))
 # Header: centered channel identity with a compact, decorated headline plaque.
 im=Image.new("RGB",(W,H),(7,12,25)).convert("RGBA")
 d=ImageDraw.Draw(im)
 d.rectangle((0,0,W,270),fill=(12,19,38,255))
 d.rectangle((0,0,W,8),fill=(246,201,92,255))
 logo_w=64; logo_x=(W-logo_w)//2
 d.rounded_rectangle((logo_x,18,logo_x+logo_w,82),radius=16,fill=(246,201,92,255))
 mg=fnt(34); box=d.textbbox((0,0),"MG",font=mg)
 d.text((logo_x+(logo_w-(box[2]-box[0]))//2,29),"MG",font=mg,fill=(16,22,42,255))
 brand="MAGAZİN GÜNDEMİ"; bf=fnt(34); bb=d.textbbox((0,0),brand,font=bf)
 d.text(((W-(bb[2]-bb[0]))//2,89),brand,font=bf,fill=(246,201,92,255))
 slogan="Her gün gündemde ne varsa!"; sf=fnt(21,False); sb=d.textbbox((0,0),slogan,font=sf)
 d.text(((W-(sb[2]-sb[0]))//2,128),slogan,font=sf,fill=(235,238,245,255))
 # Decorated headline plaque: centered, compact, never overlaps the celebrity image.
 d.rounded_rectangle((34,158,1046,254),radius=22,fill=(25,34,57,255),outline=(246,201,92,255),width=3)
 d.rounded_rectangle((34,158,47,254),radius=6,fill=(246,201,92,255))
 # Never slice the headline. Reduce the font and wrap until every word fits inside the plaque.
 tf=None; lines=[]
 for size in range(31,17,-1):
  candidate_font=fnt(size)
  candidate_lines=wrap(d,title,candidate_font,940)
  line_h=size+5
  if len(candidate_lines)<=3 and len(candidate_lines)*line_h<=88:
   tf=candidate_font;lines=candidate_lines;break
 if tf is None:
  tf=fnt(18);lines=wrap(d,title,tf,940)
 total_h=len(lines)*23; y=206-total_h//2
 for line in lines:
  b=d.textbbox((0,0),line,font=tf)
  d.text(((W-(b[2]-b[0]))//2,y),line,font=tf,fill=(255,255,255,255),stroke_width=1,stroke_fill=(0,0,0,110))
  y+=23
 # Fit the whole source image without cutting off faces or bodies. Fill any unused space with a soft blurred version.
 photo_bg=ImageOps.fit(source_image,(W,1280),method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(24)).convert("RGBA")
 photo_bg=Image.alpha_composite(photo_bg,Image.new("RGBA",photo_bg.size,(7,12,25,75)))
 im.paste(photo_bg,(0,270))
 photo=ImageOps.contain(source_image,(W,1280),method=Image.Resampling.LANCZOS).convert("RGBA")
 px=(W-photo.width)//2; py=270+(1280-photo.height)//2
 im.paste(photo,(px,py),photo if photo.mode=="RGBA" else None)
 # Bottom ticker strip: no subtitles and no duplicated static slogan.
 d=ImageDraw.Draw(im)
 d.rectangle((0,1550,W,H),fill=(7,12,25,255))
 d.rectangle((0,1550,14,H),fill=(246,201,92,255))
 d.rounded_rectangle((36,1580,208,1638),radius=16,fill=(246,201,92,255))
 d.text((52,1593),"GÜNDEM",font=fnt(25),fill=(16,22,42,255))
 d.rectangle((28,1660,1052,1663),fill=(50,61,82,255))
 d.text((40,1690),"MAGAZİN GÜNDEMİ",font=fnt(28),fill=(246,201,92,255))
 im.convert("RGB").save(poster,quality=92)
 # Photo-forward thumbnail; preserve the full source photo in the main video.
 t=ImageOps.fit(source_image,(1280,720),method=Image.Resampling.LANCZOS).convert("RGBA")
 td=ImageDraw.Draw(t)
 td.rectangle((0,0,1280,112),fill=(8,12,24,238))
 td.rounded_rectangle((20,20,88,88),radius=15,fill=(246,201,92,255))
 td.text((30,28),"MG",font=fnt(32),fill=(16,22,42,255))
 brand="MAGAZİN GÜNDEMİ"; bf=fnt(31); bb=td.textbbox((0,0),brand,font=bf)
 td.text((108,28),brand,font=bf,fill=(246,201,92,255))
 td.rectangle((0,586,1280,720),fill=(8,12,24,240))
 # Thumbnail headline also keeps the complete text; font size adapts to long headlines.
 thumb_font=None;lines=[]
 for size in range(34,21,-1):
  candidate_font=fnt(size)
  candidate_lines=wrap(td,title,candidate_font,1210)
  if len(candidate_lines)<=3 and len(candidate_lines)*(size+6)<=126:
   thumb_font=candidate_font;lines=candidate_lines;break
 if thumb_font is None:
  thumb_font=fnt(22);lines=wrap(td,title,thumb_font,1210)
 line_h=max(27,thumb_font.size+6)
 total_h=len(lines)*line_h
 y=586+(134-total_h)//2
 for line in lines:
  td.text((28,y),line,font=thumb_font,fill=(255,255,255,255));y+=line_h
 t.convert("RGB").save(thumb,quality=93)
def narration(item,a):
 title=clean(item.get("title",""))
 desc=clean(a.get("description",""))
 body=clean(a.get("body",""))
 boilerplate=[
  "devamı için tıklayın","haberimizin devamı","haberin devamı","detaylar için tıklayın",
  "kaynak haberde yer alıyor","kaynak haberi okuyabilirsiniz","bizi takip etmeyi unutmayın",
  "abone olmayı unutmayın","tüm hakları saklıdır","çerez politikası","ilgili haberler",
  "daha fazlası için","reklam","foto galerisi","videoyu izlemek için"
 ]
 def useful(s):
  s=clean(s);low=s.casefold()
  if len(s)<45 or len(s)>900 or len(s.split())<8:return False
  if any(x in low for x in boilerplate):return False
  if low in title.casefold():return False
  return True
 # Prefer the article body; use metadata only if the publisher blocks the body.
 paragraphs=[]
 for p in re.split(r"(?<=[.!?])\s+",body):
  p=clean(p)
  if useful(p) and p not in paragraphs:paragraphs.append(p)
 if not paragraphs and useful(desc):paragraphs=[desc]
 # Do not narrate the generic Google News collector placeholder.
 feed_summary=clean(item.get("summary",""))
 if not paragraphs and useful(feed_summary) and "google news bağlantı çözücüsüyle doğrudan url" not in feed_summary.casefold():
  paragraphs=[feed_summary]
 if not title or not paragraphs:return ""
 # Build a fuller 40–60 second report from several concrete article details.
 # Avoid reading an entire article verbatim: use a short quote only if the source
 # itself contains a clearly marked quotation, then report the remaining details.
 selected=[];total=0
 for p in paragraphs:
  n=len(p.split())
  if total+n>112 and selected:break
  selected.append(p);total+=n
  if total>=92:break
 if total<35:return ""
 story=" ".join(selected).strip()
 story=re.sub(r"(?:\\s*…|\\.\\.\\.)$","",story).strip()
 # Remove the article title if the body repeats it at the start.
 story=re.sub(r"^"+re.escape(title)+r"[.:,!?\\s-]*","",story,flags=re.I).strip()
 if len(story.split())<30:return ""
 # Presenter-style intro and close, without the empty "kaynak haberde" filler.
 intro=f"Magazin Gündemi'nde bugün: {title}. "
 outro=" Gelişmeleri aktarmaya devam edeceğiz. Her gün gündemde ne varsa!"
 return intro+story.rstrip(".")+"."+outro

def cmd(args):subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
def duration(path):
 r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],check=True,capture_output=True,text=True)
 return max(1.0,float(r.stdout.strip()))
def stamp(sec):
 ms=int((sec%1)*1000);n=int(sec);hh,rem=divmod(n,3600);mm,ss=divmod(rem,60);return f"{hh:02}:{mm:02}:{ss:02},{ms:03}"
def make_srt(text,dur,path):
 words=text.split();chunks=[words[i:i+7] for i in range(0,len(words),7)];lines=[]
 for i,c in enumerate(chunks):
  lines.extend([str(i+1),f"{stamp(dur*i/len(chunks))} --> {stamp(dur*(i+1)/len(chunks))}"," ".join(c),""])
 path.write_text("\n".join(lines),encoding="utf-8")
def esc(p):return str(p.resolve()).replace("\\\\","\\\\\\\\").replace(":","\\\\:").replace("'","\\\\'")
async def tts(text,path):await edge_tts.Communicate(text,VOICE,rate="-4%",volume="+0%").save(str(path))

def azure_tts(text,path):
 # Official Microsoft Azure Neural TTS fallback for GitHub-hosted runners where
 # the public Edge read-aloud websocket returns HTTP 403.
 key=os.getenv("AZURE_SPEECH_KEY","").strip()
 region=os.getenv("AZURE_SPEECH_REGION","").strip()
 if not key or not region:
  raise RuntimeError("Azure TTS yedeği yapılandırılmamış (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION secret gerekli)")
 safe=html.escape(text,quote=True)
 ssml=(f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
       f'xml:lang="tr-TR"><voice name="{html.escape(VOICE,quote=True)}">'
       f'<prosody rate="-4%">{safe}</prosody></voice></speak>')
 endpoint=f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
 req=urllib.request.Request(endpoint,data=ssml.encode("utf-8"),headers={
  "Ocp-Apim-Subscription-Key":key,
  "Content-Type":"application/ssml+xml",
  "X-Microsoft-OutputFormat":"audio-24khz-48kbitrate-mono-mp3",
  "User-Agent":"MagazinGundemiShorts/1.0"
 },method="POST")
 with urllib.request.urlopen(req,timeout=90) as response:
  audio=response.read()
 if not audio or len(audio)<1000:raise RuntimeError("Azure TTS boş veya geçersiz ses döndürdü")
 path.write_bytes(audio)
def build(item,index):
 slug=re.sub(r"[^a-z0-9]+","-",clean(item.get("title","")).lower().replace("ı","i"))[:55].strip("-") or f"haber-{index}"
 folder=OUT/f"{index:02d}-{slug}";folder.mkdir(parents=True,exist_ok=True)
 a,err=article_data(item);script=narration(item,a)
 if not script:raise RuntimeError(f"Kaynak sayfasında yeterli açıklama yok: {err or 'metin bulunamadı'}")
 (folder/"narration.txt").write_text(script,encoding="utf-8")
 (folder/"source.json").write_text(json.dumps({"title":item.get("title"),"url":item.get("url"),"source":item.get("source"),"article_metadata":a,"created_at":datetime.now(timezone.utc).isoformat(),"visual_rights_note":"Open Graph görselinin yeniden kullanım lisansı otomatik doğrulanmamıştır."},ensure_ascii=False,indent=2),encoding="utf-8")
 image=folder/"source-image.jpg";poster=folder/"poster.jpg";thumb=folder/"thumbnail.jpg";voice=folder/"narration.mp3";srt=folder/"captions.srt";video=folder/"short.mp4"
 posters(item,a,image,poster,thumb)
 # Keep the preferred Edge neural voice, retry three times, then use official Azure Neural TTS
 # if configured. Never use the robotic espeak fallback.
 tts_error=None
 for attempt in range(1,4):
  try:
   voice.unlink(missing_ok=True)
   asyncio.run(asyncio.wait_for(tts(script,voice),timeout=75))
   tts_error=None
   break
  except Exception as e:
   tts_error=e
   voice.unlink(missing_ok=True)
   LOG.warning("Edge TTS denemesi %d/3 başarısız: %s",attempt,str(e)[:180])
   if attempt<3:
    import time
    time.sleep(2*attempt)
 if tts_error is not None:
  LOG.warning("Edge TTS başarısız; Microsoft Azure Neural TTS yedeği deneniyor.")
  try:
   azure_tts(script,voice)
   LOG.info("Microsoft Azure Neural TTS başarılı: %s",VOICE)
  except Exception as azure_error:
   voice.unlink(missing_ok=True)
   raise RuntimeError(f"Edge TTS ve Azure Neural TTS başarısız; düşük kaliteli yedek sesle video yayınlanmayacak. Edge: {tts_error}; Azure: {azure_error}")
 dur=duration(voice)
 music=ROOT/"assets/music/selected_track.mp3"
 ticker=folder/"ticker.txt"
 ticker.write_text("   "+clean(item.get("title","Magazin gündemi"))+"     •     MAGAZİN GÜNDEMİ     •     HER GÜN GÜNDEMDE NE VARSA!     ",encoding="utf-8")
 ticker_filter=f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile='{esc(ticker)}':reload=0:fontsize=34:fontcolor=white:box=1:boxcolor=0x080C18@0.95:boxborderw=18:x=w-mod(t*170\\,w+tw):y=h-190"
 if music.exists():
  args=["ffmpeg","-y","-loop","1","-framerate","30","-i",str(poster),"-i",str(voice),"-stream_loop","-1","-i",str(music),"-filter_complex","[1:a]volume=1.0[voice];[2:a]volume=0.10[music];[voice][music]amix=inputs=2:duration=first:dropout_transition=2[a]","-vf",ticker_filter,"-map","0:v","-map","[a]","-t",f"{dur:.2f}"]
 else:args=["ffmpeg","-y","-loop","1","-framerate","30","-i",str(poster),"-i",str(voice),"-vf",ticker_filter,"-map","0:v","-map","1:a","-t",f"{dur:.2f}"]
 args += ["-c:v","libx264","-preset","veryfast","-tune","stillimage","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(video)];cmd(args)
 meta={"title":(title_clean(item.get("title",""))+" #Shorts")[:100],"description":f"{item.get('title','')}\n\nKaynak haber: {item.get('url','')}\nAyrıntılar ve bağlam için kaynak haberi okuyun.\n\n#MagazinGündemi #Magazin #Shorts","tags":["Magazin Gündemi","magazin","magazin haberleri","ünlüler","Shorts"],"categoryId":"25","privacyStatus":os.getenv("YOUTUBE_PRIVACY_STATUS","public"),"madeForKids":False}
 (folder/"youtube-metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
 LOG.info("Video hazır (%.1fs): %s",dur,item.get("title"))
 return {"title":item.get("title"),"folder":str(folder.relative_to(ROOT)),"video":str(video.relative_to(ROOT)),"thumbnail":str(thumb.relative_to(ROOT)),"duration":round(dur,2),"source_url":item.get("url","")}
def title_clean(s):return clean(s)
def main():
 if not INPUT.exists():LOG.error("selected_news.json yok");return 2
 items=json.loads(INPUT.read_text(encoding="utf-8")).get("items",[])[:3]
 if not items:LOG.error("Seçilmiş haber yok; video üretimi durduruldu.");return 3
 if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):LOG.error("FFmpeg/ffprobe kurulu değil");return 4
 OUT.mkdir(parents=True,exist_ok=True)
 for child in OUT.iterdir():
  if child.is_dir():shutil.rmtree(child)
  else:child.unlink()
 # Generate a matched navy-and-gold logo, YouTube banner and channel description.
 brand=OUT/"branding";brand.mkdir(parents=True,exist_ok=True)
 icon=Image.new("RGB",(800,800),(7,12,25));idraw=ImageDraw.Draw(icon)
 idraw.ellipse((35,35,765,765),fill=(10,19,39),outline=(246,201,92),width=15)
 idraw.ellipse((58,58,742,742),outline=(190,139,42),width=4)
 idraw.polygon([(265,210),(300,145),(355,205),(400,125),(445,205),(500,145),(535,210),(520,250),(280,250)],fill=(246,201,92))
 mg=fnt(230);mb=idraw.textbbox((0,0),"MG",font=mg)
 idraw.text(((800-(mb[2]-mb[0]))//2,230),"MG",font=mg,fill=(246,201,92),stroke_width=2,stroke_fill=(255,235,170))
 idraw.line((130,490,670,490),fill=(246,201,92),width=5)
 for text,y in [("MAGAZİN",510),("GÜNDEMİ",570)]:
  ft=fnt(54);tb=idraw.textbbox((0,0),text,font=ft)
  idraw.text(((800-(tb[2]-tb[0]))//2,y),text,font=ft,fill=(255,255,255))
 slogan="Her gün gündemde ne varsa!";sf=fnt(24,False);sb=idraw.textbbox((0,0),slogan,font=sf)
 idraw.text(((800-(sb[2]-sb[0]))//2,655),slogan,font=sf,fill=(246,201,92))
 icon.save(brand/"channel-icon.png")
 # YouTube banner: 2560x1440; keep all essential text inside the centered 1546x423 safe area.
 banner=Image.new("RGB",(2560,1440),(7,12,26));bd=ImageDraw.Draw(banner)
 for x,y,r,col in [(120,160,310,(24,35,61)),(2440,190,360,(48,31,66)),(200,1290,380,(19,43,69)),(2370,1250,420,(28,30,54))]:
  bd.ellipse((x-r,y-r,x+r,y+r),fill=col)
 bd.rectangle((0,0,2560,14),fill=(246,201,92))
 for x in range(60,2560,110):
  bd.ellipse((x,100,x+5,105),fill=(246,201,92));bd.ellipse((x,1335,x+5,1340),fill=(246,201,92))
 # Strictly centered safe panel: x=507..2053, y=508..931.
 bd.rounded_rectangle((507,508,2053,931),radius=52,fill=(8,14,30),outline=(246,201,92),width=5)
 cx=1280
 bd.ellipse((1202,522,1358,678),fill=(10,19,39),outline=(246,201,92),width=4)
 ft=fnt(76);tb=bd.textbbox((0,0),"MG",font=ft)
 bd.text((cx-(tb[2]-tb[0])//2,554),"MG",font=ft,fill=(246,201,92))
 name="MAGAZİN GÜNDEMİ";nf=fnt(82);nb=bd.textbbox((0,0),name,font=nf)
 bd.text((cx-(nb[2]-nb[0])//2,692),name,font=nf,fill=(246,201,92))
 bd.line((cx-380,797,cx-170,797),fill=(159,111,35),width=3)
 bd.polygon([(cx-12,787),(cx,797),(cx+12,787),(cx,807)],fill=(246,201,92))
 bd.line((cx+170,797,cx+380,797),fill=(159,111,35),width=3)
 tagline="Her gün gündemde ne varsa!";tf=fnt(40,False);tb=bd.textbbox((0,0),tagline,font=tf)
 tw=tb[2]-tb[0]
 bd.rounded_rectangle((cx-tw//2-26,829,cx+tw//2+26,891),radius=22,fill=(246,201,92))
 bd.text((cx-tw//2,837),tagline,font=tf,fill=(7,12,25))
 banner.save(brand/"channel-banner.png")
 description=("Magazin Gündemi'ne hoş geldin! Ünlüler dünyasından son gelişmeler, televizyon programları, müzik, ilişkiler ve çok konuşulan magazin haberlerini kısa, anlaşılır videolarla takip et. Günün öne çıkan gelişmeleri kaynak bağlantılarıyla birlikte burada. Yeni Shorts videolarını kaçırmamak için kanala abone ol!\\n\\nHer gün gündemde ne varsa!\\n\\n#MagazinGündemi #Magazin #Ünlüler #Shorts")
 (brand/"channel-description.txt").write_text(description,encoding="utf-8")
 built=[];errors=[]
 for i,item in enumerate(items,1):
  try:built.append(build(item,i))
  except Exception as e:errors.append({"title":item.get("title",""),"error":str(e)[:400]});LOG.exception("Video üretilemedi: %s",item.get("title"))
 (OUT/"manifest.json").write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"target_count":3,"built_count":len(built),"items":built,"errors":errors},ensure_ascii=False,indent=2),encoding="utf-8")
 LOG.info("Video üretimi: %d/3, hata: %d",len(built),len(errors))
 return 0 if built else 5
if __name__=="__main__":sys.exit(main())
