"""Loopback-only RTSP/RTP H.264 fixture. No camera/customer data required.

Used only for regression tests; NOT a production RTSP server. Test frames are
encoded locally with FFmpeg, then RTP packetized over RTSP interleaved TCP.
"""
import base64
import hashlib
import re
import socket
import socketserver
import struct
import subprocess
import threading
import time
from urllib.parse import urlsplit


def make_h264(path, size="320x240", fps=12):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i',f'testsrc2=size={size}:rate={fps}',
        '-t','2','-an','-c:v','libx264','-profile:v','baseline','-preset','ultrafast','-tune','zerolatency',
        '-x264-params',f'keyint={fps}:repeat-headers=1:aud=1','-bf','0','-f','h264','-y',str(path)],check=True,timeout=15)
    raw=path.read_bytes();marks=list(re.finditer(b'\x00\x00\x00?\x01',raw));nals=[]
    for i,m in enumerate(marks):
        end=marks[i+1].start() if i+1<len(marks) else len(raw)
        nals.append(raw[m.end():end])
    sps=next(n for n in nals if n[0]&31==7);pps=next(n for n in nals if n[0]&31==8)
    frames=[];cur=[]
    for n in nals:
        if n[0]&31==9:
            if cur:frames.append(cur)
            cur=[]
        else:cur.append(n)
    if cur:frames.append(cur)
    return sps,pps,frames


class TestRTSPServer:
    def __init__(self, path, *, password='Test@%40Only', hang=False, digest=False, size='320x240', fps=12):
        self.sps,self.pps,self.frames=make_h264(path,size,fps)
        self.digest=digest;self.fps=fps;self.auth_denials=0;self.auth_successes=0
        self.password=password;self.hang=hang
        self.clients=set();self.tcp_setups=0;self.requests=[]
        self.stop=threading.Event()
        outer=self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                outer.clients.add(self.request)
                lock=threading.Lock();closing=threading.Event();sender=None
                def response(status,seq,headers=None,body=b''):
                    head={'CSeq':seq,'Server':'BTMH-loopback-test','Content-Length':str(len(body)),**(headers or {})}
                    data=('RTSP/1.0 '+status+'\r\n'+''.join(k+': '+v+'\r\n' for k,v in head.items())+'\r\n').encode()+body
                    with lock:self.request.sendall(data)
                def stream():
                    seq=1;ts=90000;index=0
                    try:
                        while not closing.is_set() and not outer.stop.is_set():
                            started=time.monotonic();nals=outer.frames[index%len(outer.frames)]
                            for j,nal in enumerate(nals):
                                parts=[]
                                if len(nal)<=1200:parts=[nal]
                                else:
                                    payload=nal[1:];pieces=[payload[i:i+1198] for i in range(0,len(payload),1198)]
                                    for k,chunk in enumerate(pieces):
                                        parts.append(bytes([(nal[0]&0xe0)|28,(nal[0]&31)|(0x80 if k==0 else 0)|(0x40 if k==len(pieces)-1 else 0)])+chunk)
                                for k,part in enumerate(parts):
                                    mark=j==len(nals)-1 and k==len(parts)-1
                                    rtp=struct.pack('!BBHII',0x80,96|(0x80 if mark else 0),seq&65535,ts&0xffffffff,0x54400001)+part
                                    packet=b'$\x00'+struct.pack('!H',len(rtp))+rtp
                                    with lock:self.request.sendall(packet)
                                    seq+=1
                            index+=1;ts+=90000//outer.fps
                            closing.wait(max(0,1/outer.fps-(time.monotonic()-started)))
                    except (OSError,ValueError):pass
                try:
                    while not outer.stop.is_set():
                        first=self.rfile.read(1)
                        if not first:break
                        if first==b'$':
                            extra=self.rfile.read(3)
                            if len(extra)<3:break
                            self.rfile.read(struct.unpack('!H',extra[1:])[0]);continue
                        line=first+self.rfile.readline(8192)
                        if not line:break
                        words=line.decode(errors='ignore').strip().split(' ')
                        if len(words)!=3:break
                        method,url,_=words;headers={}
                        while True:
                            line=self.rfile.readline(8192)
                            if line in {b'\r\n',b'\n',b''}:break
                            key,_,val=line.decode(errors='ignore').partition(':');headers[key.lower()]=val.strip()
                        length=int(headers.get('content-length','0'))
                        if length:self.rfile.read(length)
                        cseq=headers.get('cseq','1');outer.requests.append(method)
                        if method=='OPTIONS':response('200 OK',cseq,{'Public':'OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER'});continue
                        if outer.hang:
                            outer.stop.wait(20);break
                        auth=headers.get('authorization','')
                        realm='BTMH-test';nonce='test-nonce-545';h=lambda v:hashlib.md5(v.encode()).hexdigest()
                        if outer.digest:
                            pairs={}
                            for key,q,bare in re.findall(r'(\w+)=(?:"([^"]*)"|([^, ]+))',auth):pairs[key]=q or bare
                            ha1=h('camera:'+realm+':'+outer.password);ha2=h(method+':'+pairs.get('uri',''))
                            response_hash=(h(ha1+':'+nonce+':'+pairs.get('nc','')+':'+pairs.get('cnonce','')+':'+pairs['qop']+':'+ha2)
                                           if pairs.get('qop') else h(ha1+':'+nonce+':'+ha2))
                            authenticated=auth.startswith('Digest ') and pairs.get('username')=='camera' and pairs.get('response')==response_hash
                            challenge='Digest realm="'+realm+'", nonce="'+nonce+'", algorithm=MD5, qop="auth"'
                        else:
                            expected='Basic '+base64.b64encode(('camera:'+outer.password).encode()).decode()
                            authenticated=auth==expected;challenge='Basic realm="BTMH-test"'
                        if not authenticated:
                            outer.auth_denials+=1
                            response('401 Unauthorized',cseq,{'WWW-Authenticate':challenge});continue
                        outer.auth_successes+=1
                        path=urlsplit(url).path
                        if not path.startswith('/Streaming/Channels/101'):
                            response('404 Not Found',cseq);continue
                        if method=='DESCRIBE':
                            sprop=base64.b64encode(outer.sps).decode()+','+base64.b64encode(outer.pps).decode()
                            profile=outer.sps[1:4].hex()
                            body=('v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=Test\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\na=control:*\r\n'
                                  'm=video 0 RTP/AVP 96\r\na=rtpmap:96 H264/90000\r\n'
                                  f'a=fmtp:96 packetization-mode=1;profile-level-id={profile};sprop-parameter-sets={sprop}\r\n'
                                  'a=control:trackID=0\r\n').encode()
                            response('200 OK',cseq,{'Content-Type':'application/sdp','Content-Base':url.rstrip('/')+'/'},body)
                        elif method=='SETUP':
                            if 'RTP/AVP/TCP' not in headers.get('transport',''):
                                response('461 Unsupported Transport',cseq);continue
                            outer.tcp_setups+=1
                            response('200 OK',cseq,{'Transport':'RTP/AVP/TCP;unicast;interleaved=0-1','Session':'544;timeout=60'})
                        elif method=='PLAY':
                            response('200 OK',cseq,{'Session':'544','Range':'npt=0.000-','RTP-Info':f'url={url.rstrip("/")}/trackID=0;seq=1;rtptime=90000'})
                            if sender is None:sender=threading.Thread(target=stream,daemon=True);sender.start()
                        elif method=='TEARDOWN':response('200 OK',cseq,{'Session':'544'});break
                        else:response('200 OK',cseq,{'Session':'544'})
                except (OSError,ValueError):pass
                finally:
                    closing.set();outer.clients.discard(self.request)
                    if sender:sender.join(.3)
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address=True;daemon_threads=True
        self.server=Server(('127.0.0.1',0),Handler)
        self.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def url(self,password=None,path='/Streaming/Channels/101'):
        from urllib.parse import quote
        pw=self.password if password is None else password
        return f'rtsp://camera:{quote(pw,safe="")}@127.0.0.1:{self.port}{path}'

    def close(self):
        self.stop.set()
        for sock in list(self.clients):
            try:sock.shutdown(socket.SHUT_RDWR);sock.close()
            except OSError:pass
        self.server.shutdown();self.server.server_close();self.thread.join(1.)
