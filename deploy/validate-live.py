"""Opt-in smoke/load test; run in an app-network-only container with test keys mounted."""
import asyncio,base64,json,time,struct,zlib
from pathlib import Path
import httpx
KEYS=json.loads(Path('/run/secrets/app-keys.json').read_text())
BASE='http://llm-gateway:8000'
def headers(app='admin'):return {'Authorization':'Bearer '+KEYS[app]}
async def main():
 result={}
 async with httpx.AsyncClient(timeout=180,trust_env=False) as c:
  result['ready']=(await c.get(BASE+'/ready',headers=headers())).json()
  result['unauthenticated_status']=(await c.get(BASE+'/v1/models')).status_code
  try:
   r=await c.get('http://172.30.81.1:8080/health',timeout=3);result['backend_bypass_status']=r.status_code
  except httpx.HTTPError:result['backend_bypass']='blocked'
  async def request(app,marker):
   start=time.monotonic()
   r=await c.post(BASE+'/v1/chat/completions',headers=headers(app),json={'model':'qwen-local','messages':[{'role':'system','content':'Start your answer with exactly '+marker+'. Explain technical ideas clearly in Spanish.'},{'role':'user','content':'Explica el funcionamiento de un indice B-tree en 100 palabras.'}],'max_tokens':180})
   r.raise_for_status();d=r.json();return {'app':app,'seconds':round(time.monotonic()-start,2),'usage':d.get('usage'),'marker_ok':d['choices'][0]['message']['content'].strip().startswith(marker)}
  t=time.monotonic(); result['concurrent']=await asyncio.gather(*(request(a,m) for a,m in zip(['sara','skilldex','alumni','examgen'],['ALFA','BETA','GAMMA','DELTA'])));result['concurrent_wall_seconds']=round(time.monotonic()-t,2)
  r=await c.post(BASE+'/v1/chat/completions',headers=headers(),json={'model':'local-model','messages':[{'role':'user','content':'Devuelve voltaje de 12 voltios en JSON.'}],'max_tokens':80,'response_format':{'type':'json_schema','json_schema':{'name':'measurement','strict':True,'schema':{'type':'object','properties':{'voltage':{'type':'number'}},'required':['voltage'],'additionalProperties':False}}}})
  r.raise_for_status();result['structured']=json.loads(r.json()['choices'][0]['message']['content'])
  def chunk(t,d):return struct.pack('!I',len(d))+t+d+struct.pack('!I',zlib.crc32(t+d)&0xffffffff)
  png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',64,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\xff\x00\x00'*64)*64))+chunk(b'IEND',b'')
  r=await c.post(BASE+'/v1/chat/completions',headers=headers(),json={'model':'qwen-local','messages':[{'role':'user','content':[{'type':'text','text':'What is the single color in this image? Reply one word.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}]}],'max_tokens':20})
  r.raise_for_status();result['vision']=r.json()['choices'][0]['message']['content']
  start=time.monotonic()
  async with c.stream('POST',BASE+'/v1/chat/completions',headers=headers(),json={'model':'qwen-local','messages':[{'role':'user','content':'Cuenta del uno al mil con palabras.'}],'max_tokens':2048,'stream':True}) as r:
   r.raise_for_status()
   async for line in r.aiter_lines():
    if line.startswith('data: {'):
     d=json.loads(line[6:])
     if any(x.get('delta',{}).get('content') for x in d.get('choices',[])):
      result['stream_first_content_seconds']=round(time.monotonic()-start,2);break
  await asyncio.sleep(2)
  result['after_cancel']=(await c.get(BASE+'/metrics',headers=headers())).json()
  result['oversize_output_status']=(await c.post(BASE+'/v1/chat/completions',headers=headers(),json={'messages':[{'role':'user','content':'hola'}],'max_tokens':30000})).status_code
 print(json.dumps(result,indent=2))
 assert result['ready']['status'] == 'ready'
 assert result['unauthenticated_status'] == 401
 assert result.get('backend_bypass') == 'blocked'
 assert all(x['marker_ok'] for x in result['concurrent'])
 assert result['structured'] == {'voltage': 12}
 assert 'red' in result['vision'].lower()
 assert result['after_cancel']['inflight'] == 0
 assert result['oversize_output_status'] == 422
asyncio.run(main())
