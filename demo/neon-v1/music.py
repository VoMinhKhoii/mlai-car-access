import numpy as np, wave
SR=48000; DUR=56.0; N=int(SR*DUR); BPM=120; B=60/BPM
L=np.zeros(N); Rr=np.zeros(N)
rng=np.random.default_rng(3)
def add(sig,t0,pan=0.,g=1.):
    i=int(t0*SR); s=sig[:max(0,min(len(sig),N-i))]
    if i<0: return
    L[i:i+len(s)]+=s*g*(1-max(0,pan)); Rr[i:i+len(s)]+=s*g*(1+min(0,pan))
def env(n,a,d):
    t=np.arange(n)/SR; return np.minimum(1,t/max(a,1e-4))*np.exp(-t/d)
def lp(x,a):  # one-pole lowpass, a in (0,1)
    y=np.empty_like(x); acc=0.
    for i in range(len(x)): acc+= a*(x[i]-acc); y[i]=acc
    return y
def lp_fast(x,cut):
    # FFT brickwall-ish smooth lowpass
    X=np.fft.rfft(x); f=np.fft.rfftfreq(len(x),1/SR); X*=1/(1+(f/cut)**4); return np.fft.irfft(X,len(x))
def hp_fast(x,cut):
    X=np.fft.rfft(x); f=np.fft.rfftfreq(len(x),1/SR); X*=1-1/(1+(f/cut)**4); return np.fft.irfft(X,len(x))
note=lambda m:440*2**((m-69)/12)
def saw(f,n,det=0):
    t=np.arange(n)/SR; return 2*((t*f*(1+det))%1)-1
# kick
def kick():
    n=int(.5*SR); t=np.arange(n)/SR; f=45+110*np.exp(-t*28); ph=2*np.pi*np.cumsum(f)/SR
    return np.sin(ph)*np.exp(-t*7)*1.0 + 0.3*rng.standard_normal(n)*np.exp(-t*300)
K=kick()
def snare():
    n=int(.35*SR); t=np.arange(n)/SR
    return hp_fast(rng.standard_normal(n),1500)*np.exp(-t*16)*.5+np.sin(2*np.pi*190*t)*np.exp(-t*30)*.4
S=snare()
def hat(op=False):
    n=int((.25 if op else .06)*SR); t=np.arange(n)/SR
    return hp_fast(rng.standard_normal(n),7000)*np.exp(-t*(12 if op else 70))*.35
HC=hat(); HO=hat(True)
kick_times=[]
# chords: Am F C G (2 bars each = 4 s)
prog=[[57,60,64],[53,57,60],[48,52,55,60],[55,59,62]]
roots=[45,41,48,43]
def pad_seg(ch,t0,dur,g):
    n=int(dur*SR); s=np.zeros(n)
    for m in ch:
        for d in (-.004,0,.005): s+=saw(note(m),n,d)
    s=lp_fast(s,1400)*.06; a=np.minimum(1,np.arange(n)/(SR*.6))*np.minimum(1,(n-np.arange(n))/(SR*.6))
    add(s*a,t0,0,g)
for k in range(14):
    t0=k*4; ch=prog[k%4]
    g=1.0 if t0<6 or t0>=48 else .55
    pad_seg(ch,t0,4.2,g)
# sub bass 8ths 6..48
for i in range(int(6/ (B/2)), int(48/(B/2))):
    t0=i*B/2; r=roots[int(t0//4)%4]; n=int(B/2*SR*.95); t=np.arange(n)/SR
    s=(np.sin(2*np.pi*note(r-12)*t)+.4*np.tanh(3*np.sin(2*np.pi*note(r)*t)))*np.exp(-t*3)*.32
    add(s,t0)
# kicks 6..48 four on floor; 49 impact
for i in range(int(6/B),int(48/B)):
    t0=i*B; add(K,t0,0,.9); kick_times.append(t0)
# snares 20..48 on 2,4
for i in range(int(20/B),int(48/B)):
    if i%2==1: add(S,i*B,0,.8)
# hats 12..48
for i in range(int(12/(B/4)),int(48/(B/4))):
    t0=i*B/4
    if i%4==2: add(HO,t0,.3,.6)
    elif i%2==1: add(HC,t0,-.3,.5)
# arp 20..48 16ths
for i in range(int(20/(B/4)),int(48/(B/4))):
    t0=i*B/4; ch=prog[int(t0//4)%4]; seq=[0,1,2,1,2,0,2,1]; m=ch[seq[i%8]%len(ch)]+12*(1+(i%16>=8))
    n=int(.22*SR); t=np.arange(n)/SR
    s=(saw(note(m),n)+saw(note(m),n,.006))*np.exp(-t*14)*.05
    add(s,t0,.5*np.sin(i*.7),1)
    add(s*.35,t0+B*.75,-.5*np.sin(i*.7),1)  # echo
# risers into 6 and 49
def riser(t1,dur,g=.5):
    n=int(dur*SR); t=np.arange(n)/SR; x=rng.standard_normal(n)
    s=hp_fast(x,2500)*(t/dur)**2.5
    sw=np.sin(2*np.pi*np.cumsum(200+1800*(t/dur)**2)/SR)*(t/dur)**2*.3
    add((s*.6+sw)*g,t1-dur)
riser(6,3.5,.45); riser(49,3,.5); riser(20,1.5,.25); riser(40,1.5,.3)
# impacts at cuts
def impact(t0,g=1.):
    n=int(2.5*SR); t=np.arange(n)/SR
    boom=np.sin(2*np.pi*np.cumsum(30+80*np.exp(-t*10))/SR)*np.exp(-t*1.8)
    nz=lp_fast(rng.standard_normal(n),3000)*np.exp(-t*4)*.5
    add((boom+nz)*.7*g,t0)
for c,g in [(6,1.2),(12,.6),(20,.8),(28,.6),(36,.6),(40,.9),(49,1.3),(50.8,.7)]: impact(c,g)
# whooshes at cuts (reverse noise)
for c in [12,20,28,36,40]:
    n=int(.5*SR); t=np.arange(n)/SR; s=hp_fast(rng.standard_normal(n),1200)*(t/.5)**3*.25; add(s,c-.5,.4)
# glitch stutters
def glitch(t0,dur=.3):
    n=int(dur*SR); t=np.arange(n)/SR; s=np.sign(np.sin(2*np.pi*(800+600*np.sin(t*90))*t))*.08*((t*40)%1<.5)
    add(s,t0,-.3)
for g in [1.45,3.0,5.1,22.6,50.9,52.6]: glitch(g,.25)
# scan beeps during alley scan, blips for stats
for i in range(10): 
    n=int(.08*SR); t=np.arange(n)/SR; add(np.sin(2*np.pi*(1500+i*120)*t)*np.exp(-t*40)*.12, 8.6+i*.18, .6*(-1)**i)
for i in range(16):
    n=int(.06*SR); t=np.arange(n)/SR; add(np.sin(2*np.pi*2200*t)*np.exp(-t*50)*.08, 23.4+i*.25, .5*(-1)**i)
# sidechain duck
duck=np.ones(N)
for kt in kick_times:
    i=int(kt*SR); n=int(.3*SR); seg=1-.55*np.exp(-np.arange(n)/SR*14); duck[i:i+n]=np.minimum(duck[i:i+n],seg[:len(duck[i:i+n])])
# apply duck to everything except kick: approximate by ducking whole mix lightly
L*=duck**.6; Rr*=duck**.6
# master
mix=np.stack([L,Rr],1)
t=np.arange(N)/SR; fade=np.minimum(1,t/.3)*np.clip((DUR-t)/2.5,0,1)[:,None].T[0]
mix*=fade[:,None]
mix=np.tanh(mix*1.6)/np.tanh(1.6)
mix/=np.max(np.abs(mix))*1.05
with wave.open('music.wav','wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((mix*32767).astype('<i2').tobytes())
print('ok')
