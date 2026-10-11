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
 url=str(item.get("url") or "")
 if not url.startswith(("https://","http://")):return {}, "invalid URL"
 try:
  p=Parser();p.feed(fetch(url)); body=" ".join(p.ps[:10])
  desc=p.meta.get("og:description") or p.meta.get("description") or p.meta.get("twitter:description") or (body[:900] if body else "")
  img=p.meta.get("og:image") or p.meta.get("twitter:image") or ""
  return {"page_title":clean(p.meta.get("og:title") or " ".join(p.title) or item.get("title")),"description":clean(desc),"image_url":urllib.parse.urljoin(url,img) if img else "","body":body,"url":url}, ""
 except Exception as e:return {},str(e)[:180]
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
 if url:
  try:
   req=urllib.request.Request(url,headers={"User-Agent":UA})
   with urllib.request.urlopen(req,timeout=15) as r:path.write_bytes(r.read(8000000))
   return Image.open(path).convert("RGB")
  except Exception as e:LOG.warning("Görsel alınamadı, özgün marka zemini kullanılacak: %s",str(e)[:100])
 im=Image.new("RGB",(W,H),(16,22,42));d=ImageDraw.Draw(im)
 for y in range(H):
  q=y/H;d.line((0,y,W,y),fill=(int(16+q*18),int(22+q*12),int(42+q*34)))
 d.ellipse((650,160,1280,790),fill=(75,44,90));d.ellipse((-250,980,550,1800),fill=(40,68,104))
 return im
def posters(item,article,imagepath,poster,thumb):
 source_image=background(article.get("image_url",""),imagepath)
 im=source_image.resize((W,H),Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(16)).convert("RGBA")
 im=Image.alpha_composite(im,Image.new("RGBA",(W,H),(8,13,28,125)))
 # Keep the article photo visible, not just as a blurred background.
 photo=ImageOps.fit(source_image,(900,820),method=Image.Resampling.LANCZOS).convert("RGBA")
 mask=Image.new("L",photo.size,0);md=ImageDraw.Draw(mask);md.rounded_rectangle((0,0,899,819),radius=34,fill=255)
 im.paste(photo,(90,250),mask);d=ImageDraw.Draw(im)
 d.rounded_rectangle((86,246,994,1074),radius=38,outline=(246,201,92,255),width=6)
 d.rounded_rectangle((58,80,530,166),radius=28,fill=(246,201,92,255));d.text((84,101),"MAGAZİN GÜNDEMİ",font=fnt(38),fill=(20,25,42,255))
 d.rounded_rectangle((58,1190,1022,1710),radius=42,fill=(8,12,24,225),outline=(246,201,92,230),width=3)
 title=clean(item.get("title","Magazin gündemi")); lines=wrap(d,title,fnt(67),850)
 if len(lines)>6:lines=lines[:5]+["…"]
 y=1260
 for line in lines:d.text((105,y),line,font=fnt(67),fill=(255,255,255,255),stroke_width=1,stroke_fill=(0,0,0,150));y+=82
 d.text((78,1780),"Her gün gündemde ne varsa!",font=fnt(34,False),fill=(246,201,92,255));im.convert("RGB").save(poster,quality=92)
 t=im.resize((1280,720),Image.Resampling.LANCZOS);td=ImageDraw.Draw(t)
 td.rounded_rectangle((35,35,1245,685),radius=28,fill=(8,12,24,185),outline=(246,201,92,240),width=4)
 lines=wrap(td,title,fnt(58),1110)
 if len(lines)>4:lines=lines[:3]+["…"]
 y=(720-len(lines)*76)//2-25
 for line in lines:
  box=td.textbbox((0,0),line,font=fnt(58));td.text(((1280-(box[2]-box[0]))//2,y),line,font=fnt(58),fill=(255,255,255,255));y+=76
 td.text((58,615),"MAGAZİN GÜNDEMİ",font=fnt(30),fill=(246,201,92,255));t.convert("RGB").save(thumb,quality=93)
def narration(item,a):
 title=clean(item.get("title",""));desc=clean(a.get("description",""));body=clean(a.get("body",""))
 if not desc and body:desc=body[:650]
 if not title or len(desc)<35:return ""
 desc=desc[:500].rsplit(" ",1)[0]+"…" if len(desc)>500 else desc
 src=clean(item.get("source") or item.get("source_domain") or "kaynak haber")
 text=(f"Magazin Gündemi'nde öne çıkan haber: {title}. Haberde aktarılanlara göre, {desc} "
       f"Bu gelişmenin ayrıntıları kaynak haberde yer alıyor. Detayları ve bağlamı görmek için kaynak haberi okuyabilirsiniz. "
       f"Magazin dünyasındaki gelişmeler için Magazin Gündemi'ni takip edin. Her gün gündemde ne varsa!")
 if len(text.split())<65:text+=f" Haber başlığı: {title}. Kaynak yayın: {src}."
 return text
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
def build(item,index):
 slug=re.sub(r"[^a-z0-9]+","-",clean(item.get("title","")).lower().replace("ı","i"))[:55].strip("-") or f"haber-{index}"
 folder=OUT/f"{index:02d}-{slug}";folder.mkdir(parents=True,exist_ok=True)
 a,err=article_data(item);script=narration(item,a)
 if not script:raise RuntimeError(f"Kaynak sayfasında yeterli açıklama yok: {err or 'metin bulunamadı'}")
 (folder/"narration.txt").write_text(script,encoding="utf-8")
 (folder/"source.json").write_text(json.dumps({"title":item.get("title"),"url":item.get("url"),"source":item.get("source"),"article_metadata":a,"created_at":datetime.now(timezone.utc).isoformat(),"visual_rights_note":"Open Graph görselinin yeniden kullanım lisansı otomatik doğrulanmamıştır."},ensure_ascii=False,indent=2),encoding="utf-8")
 image=folder/"source-image.jpg";poster=folder/"poster.jpg";thumb=folder/"thumbnail.jpg";voice=folder/"narration.mp3";srt=folder/"captions.srt";video=folder/"short.mp4"
 posters(item,a,image,poster,thumb);asyncio.run(tts(script,voice));dur=duration(voice);make_srt(script,dur,srt)
 music=ROOT/"assets/music/selected_track.mp3"
 vf=f"subtitles='{esc(srt)}':force_style='FontName=DejaVu Sans,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=210'"
 if music.exists():
  args=["ffmpeg","-y","-loop","1","-framerate","30","-i",str(poster),"-i",str(voice),"-stream_loop","-1","-i",str(music),"-filter_complex","[1:a]volume=1.0[voice];[2:a]volume=0.10[music];[voice][music]amix=inputs=2:duration=first:dropout_transition=2[a]","-vf",vf,"-map","0:v","-map","[a]","-t",f"{dur:.2f}"]
 else:args=["ffmpeg","-y","-loop","1","-framerate","30","-i",str(poster),"-i",str(voice),"-vf",vf,"-map","0:v","-map","1:a","-t",f"{dur:.2f}"]
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
 # Generate channel branding assets alongside the daily video set.
 brand=OUT/"branding";brand.mkdir(parents=True,exist_ok=True)
 icon=Image.new("RGB",(800,800),(16,22,42));idraw=ImageDraw.Draw(icon)
 idraw.ellipse((55,55,745,745),fill=(246,201,92),outline=(255,255,255),width=8)
 idraw.text((168,205),"MG",font=fnt(230),fill=(16,22,42))
 idraw.text((140,490),"MAGAZİN",font=fnt(68),fill=(16,22,42))
 idraw.text((165,575),"GÜNDEMİ",font=fnt(68),fill=(16,22,42))
 icon.save(brand/"channel-icon.png")
 banner=Image.new("RGB",(2560,1440),(16,22,42));bd=ImageDraw.Draw(banner)
 bd.ellipse((1710,80,2700,1070),fill=(75,44,90));bd.ellipse((-350,600,900,1800),fill=(40,68,104))
 bd.rounded_rectangle((220,330,2340,1040),radius=80,fill=(8,12,24),outline=(246,201,92),width=8)
 bd.text((360,470),"MAGAZİN GÜNDEMİ",font=fnt(150),fill=(246,201,92))
 bd.text((365,700),"Her gün gündemde ne varsa!",font=fnt(76,False),fill=(255,255,255))
 banner.save(brand/"channel-banner.png")
 (brand/"channel-description.txt").write_text("Magazin Gündemi; ünlüler, televizyon, müzik ve magazin dünyasındaki güncel gelişmeleri kaynak bağlantılarıyla kısa ve anlaşılır videolarla aktarır. Her gün gündemde ne varsa! Haberlerin ayrıntıları için videolardaki kaynak bağlantılarını ziyaret edin.",encoding="utf-8")
 built=[];errors=[]
 for i,item in enumerate(items,1):
  try:built.append(build(item,i))
  except Exception as e:errors.append({"title":item.get("title",""),"error":str(e)[:400]});LOG.exception("Video üretilemedi: %s",item.get("title"))
 (OUT/"manifest.json").write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"target_count":3,"built_count":len(built),"items":built,"errors":errors},ensure_ascii=False,indent=2),encoding="utf-8")
 LOG.info("Video üretimi: %d/3, hata: %d",len(built),len(errors))
 return 0 if built else 5
if __name__=="__main__":sys.exit(main())
