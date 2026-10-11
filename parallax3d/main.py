#!/usr/bin/env python
"""parallax3d giris noktasi.

Ornek:
    python main.py foto.jpg
    python main.py foto.jpg -o cikti.mp4 -m orbit -d 4 --gif
    python main.py ./fotograflar -m zoom -s 1.3        # klasorun tamami
"""

from parallax3d.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
