"""Render the three approved temporary ending lines with existing neural TTS.

Dedicated stable files can later be replaced by the author's voice. No existing
recordings are overwritten. Keeps clips short, mono and at 48 kHz for Unreal.
"""
import asyncio
import json
import subprocess
import wave
from pathlib import Path
import placeholder_voices_edge as voices

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/EndingVoice'
OUT.mkdir(parents=True,exist_ok=True)
LINES=[
 ('END_ELDER_01','Just a little farther.','en-GB-RyanNeural','-12%','-12Hz'),
 ('END_ELDER_02','Places. People. Stories. Keep them together.','en-GB-RyanNeural','-12%','-12Hz'),
 ('END_SYSTEM_01','Transmission complete.','en-GB-SoniaNeural','-4%','+0Hz'),
]
manifest=[]
existing={row['id']:row for row in json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))} if (OUT/'manifest.json').exists() else {}
for ident,text,voice,rate,pitch in LINES:
    mp3=OUT/(ident+'.mp3')
    wav=OUT/(ident+'.wav')
    if wav.exists():
        with wave.open(str(wav)) as reader:
            duration=reader.getnframes()/reader.getframerate()
        manifest.append({**existing.get(ident,{}),'id':ident,'text':text,'duration_s':duration,'wav':str(wav)})
        print(ident,'kept existing take',flush=True)
        continue
    if not mp3.exists():
        data=asyncio.run(voices._fetch(text,voice,rate,pitch))
        if not data:
            raise RuntimeError('Empty neural voice response: '+ident)
        mp3.write_bytes(data)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(mp3),
      '-af','silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB,loudnorm=I=-18:TP=-1.5:LRA=7',
      '-ac','1','-ar','48000','-c:a','pcm_s16le',str(wav)],check=True)
    with wave.open(str(wav)) as reader:
        duration=reader.getnframes()/reader.getframerate()
    manifest.append({'id':ident,'text':text,'voice':voice,'placeholder':True,'engine':'edge-tts','duration_s':duration,'wav':str(wav)})
    print(ident,round(duration,2),'seconds',flush=True)
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
