from __future__ import annotations

import getpass
import sys

from app.config import SECRET_NAMES, set_secret


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in SECRET_NAMES:
        sys.stderr.write(f"Dùng: python -m app.setkey <{'|'.join(SECRET_NAMES)}>\n")
        return 2
    value = getpass.getpass(f"Nhập khóa {argv[0]} (không hiện khi gõ): ").strip()
    if not value:
        sys.stderr.write("Khóa rỗng, không lưu.\n")
        return 1
    set_secret(argv[0], value)
    sys.stdout.write(f"Đã lưu khóa {argv[0]} vào Windows Credential Manager.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
