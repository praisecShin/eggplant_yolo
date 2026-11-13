#!/usr/bin/env bash
# Codex 시험 환경 준비 — sudo 없이 사용자 폴더에만 설치
set -euo pipefail
python3 -m pip install --user numpy pillow pyflakes
mkdir -p "$HOME/.local/bin"
if ! command -v rclone >/dev/null 2>&1; then
  curl -fsSL https://downloads.rclone.org/rclone-current-linux-amd64.zip -o /tmp/rclone.zip
  python3 -c "import zipfile,sys;z=zipfile.ZipFile('/tmp/rclone.zip');n=[x for x in z.namelist() if x.endswith('/rclone')][0];open(sys.argv[1],'wb').write(z.read(n))" "$HOME/.local/bin/rclone"
  chmod +x "$HOME/.local/bin/rclone"
fi
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  . "$HOME/.nvm/nvm.sh"
  nvm install --lts
fi
grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
echo "준비 끝: python $(python3 --version 2>&1) · rclone $("$HOME/.local/bin/rclone" version 2>/dev/null | head -1 || echo 없음) · node $(node --version 2>/dev/null || echo 없음)"
