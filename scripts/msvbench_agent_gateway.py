"""Loopback-only relay for the existing Qwen provider during DNS failure."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests
from msvbench_dns import install

install()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Never log prompts, credentials or request bodies.

    def relay(self):
        if not self.path.startswith(('/responses', '/chat/completions', '/models')):
            self.send_error(404)
            return
        print('RELAY_BEGIN', self.command, self.path, flush=True)
        size = int(self.headers.get('Content-Length', '0'))
        if size > 64 * 1024 * 1024:
            self.send_error(413)
            return
        data = self.rfile.read(size) if size else None
        headers = {key: value for key, value in self.headers.items()
                   if key.lower() not in ['host', 'connection', 'content-length', 'accept-encoding']}
        try:
            print('RELAY_CONNECT', flush=True)
            with requests.request(self.command,
                                  'https://dashscope.aliyuncs.com/compatible-mode/v1' + self.path,
                                  headers=headers, data=data, stream=True, timeout=(30, 900)) as response:
                print('RELAY_STATUS',response.status_code,flush=True)
                self.send_response(response.status_code)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                self.send_header('Connection', 'close')
                self.end_headers()
                for chunk in response.iter_content(chunk_size=256):
                    if chunk:
                        self.wfile.write(chunk)
                        self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except requests.RequestException:
            self.close_connection = True
        finally:
            self.close_connection = True

    do_POST = relay
    do_GET = relay


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 19083), Handler).serve_forever()
