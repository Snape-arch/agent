"""Private loopback worker; started exclusively by ClawOS VisionRuntime."""
import argparse
import hmac
import json
import os
from pathlib import Path
import sys
import threading


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--ready',type=Path,required=True);ap.add_argument('--session',required=True)
    a=ap.parse_args()
    # A fresh per-process gateway secret arrives on a private pipe, never argv,
    # a persisted token file, browser storage, a source .env or provider setting.
    secret=json.loads(sys.stdin.readline())['gateway']
    if not isinstance(secret,str) or len(secret)<40: raise ValueError('gateway handshake missing')
    sys.path.insert(0,str(Path(__file__).resolve().parent/'backend'))
    import server
    from security import Principal
    server.authenticate=lambda _header:Principal('local-user','default','owner',('*',))
    class Handler(server.Handler):
        def parse_request(self):
            if not super().parse_request(): return False
            if not hmac.compare_digest(self.headers.get('X-ClawOS-Vision-Gateway',''),secret):
                self.send_error(403,'private gateway required');return False
            return True
        def log_message(self,*_): pass
        def do_POST(self):
            if self.path=='/api/__clawos_shutdown':
                self._json({'stopping':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            super().do_POST()
    service=server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    try:
        server.initialize()
        ready=dict(pid=os.getpid(),port=service.server_port,session=a.session)
        temp=a.ready.with_suffix('.tmp');temp.write_text(json.dumps(ready),encoding='utf-8');temp.replace(a.ready)
        service.serve_forever(poll_interval=.2)
    finally:
        server.stop_synthesis_recovery();server.shutdown_text3d_workers()
        server.EXECUTOR.shutdown(wait=False,cancel_futures=True);service.server_close()


if __name__=='__main__': main()
