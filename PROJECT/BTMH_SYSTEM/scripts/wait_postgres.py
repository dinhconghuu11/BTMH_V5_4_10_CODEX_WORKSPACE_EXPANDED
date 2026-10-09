from __future__ import annotations

import argparse
import socket
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=55432)
    parser.add_argument('--timeout', type=float, default=60.0)
    parser.add_argument('--interval', type=float, default=1.0)
    args = parser.parse_args()

    deadline = time.monotonic() + max(1.0, args.timeout)
    last_error = ''
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((args.host, args.port), timeout=1.5):
                print(f'[OK] PostgreSQL port is ready at {args.host}:{args.port}.')
                return 0
        except OSError as exc:
            last_error = str(exc)
            time.sleep(max(0.2, args.interval))
    print(f'[ERROR] PostgreSQL did not become ready at {args.host}:{args.port} within {args.timeout:.0f}s.')
    if last_error:
        print(f'[DETAIL] {last_error}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
