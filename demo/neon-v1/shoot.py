import sys, time, subprocess, os
from playwright.sync_api import sync_playwright
mode=sys.argv[1]
here=os.path.dirname(os.path.abspath(__file__))
with sync_playwright() as p:
    b=p.chromium.launch(args=['--force-color-profile=srgb','--disable-gpu-vsync'])
    pg=b.new_page(viewport={'width':1920,'height':1080})
    errs=[]; pg.on('console',lambda m: errs.append(m.text) if m.type=='error' else None); pg.on('pageerror',lambda e: errs.append(str(e)))
    pg.goto('file://'+here+'/index.html?render'); pg.evaluate('window.ready')
    if mode=='stills':
        os.makedirs('stills',exist_ok=True)
        for t in sys.argv[2:]:
            pg.evaluate(f'render({t})'); pg.screenshot(path=f'stills/t{float(t):05.1f}.png')
    else:
        fps=int(sys.argv[2]); total=pg.evaluate('TOTAL'); n=int(total*fps)
        ff=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','image2pipe','-framerate',str(fps),'-c:v','mjpeg','-i','-','-c:v','copy','frames.mkv'],stdin=subprocess.PIPE)
        t0=time.time()
        for i in range(n):
            pg.evaluate(f'render({i/fps})')
            ff.stdin.write(pg.screenshot(type='jpeg',quality=96))
            if i%120==0: print(i,n,round(time.time()-t0),flush=True)
        ff.stdin.close(); ff.wait()
    print('ERRORS',errs[:5])
    b.close()
