from __future__ import annotations

import argparse
from pathlib import Path

MARKER = '# CampusFace temporary localhost recovery rule'
RULES = (
    f'{MARKER}\n'
    'host all all 127.0.0.1/32 trust\n'
    'host all all ::1/128 trust\n'
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('enable', 'restore'))
    parser.add_argument('--data-dir', required=True)
    args = parser.parse_args()

    data = Path(args.data_dir)
    hba = data / 'pg_hba.conf'
    backup = data / 'pg_hba.campusface-before-recovery.conf'
    if not hba.exists():
        print(f'[ERROR] pg_hba.conf not found: {hba}')
        return 2

    if args.action == 'enable':
        text = hba.read_text(encoding='utf-8', errors='ignore')
        if MARKER not in text:
            if not backup.exists():
                backup.write_bytes(hba.read_bytes())
            hba.write_text(RULES + text, encoding='utf-8')
        print('[OK] Temporary localhost trust enabled for recovery.')
        return 0

    if backup.exists():
        hba.write_bytes(backup.read_bytes())
        backup.unlink(missing_ok=True)
        print('[OK] Original pg_hba.conf restored.')
        return 0
    text = hba.read_text(encoding='utf-8', errors='ignore')
    if MARKER in text:
        lines = text.splitlines()
        out = []
        skip = 0
        for line in lines:
            if line.strip() == MARKER:
                skip = 2
                continue
            if skip:
                skip -= 1
                continue
            out.append(line)
        hba.write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('[OK] No recovery backup was present; temporary rule removed if found.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
