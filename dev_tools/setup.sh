#!/usr/bin/env bash
# Codex·검토용 시험 환경 준비 — sudo 없이 사용자 폴더에만 설치 (AGENTS.md 4장)
set -euo pipefail
# v4.31.10: pip이 없는 환경 — ensurepip → get-pip.py 순서로 사용자 폴더에 pip을 먼저 설치
if ! python3 -m pip --version >/dev/null 2>&1; then
  python3 -m ensurepip --user >/dev/null 2>&1 || {
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    python3 /tmp/get-pip.py --user 2>/dev/null || python3 /tmp/get-pip.py --user --break-system-packages
  }
fi
export PATH="$HOME/.local/bin:$PATH"
python3 -m pip install --user numpy pillow pyflakes 2>/dev/null || python3 -m pip install --user --break-system-packages numpy pillow pyflakes
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
echo "준비 끝: $(python3 --version 2>&1) · rclone $("$HOME/.local/bin/rclone" version 2>/dev/null | head -1 || rclone version 2>/dev/null | head -1 || echo 없음) · node $(node --version 2>/dev/null || echo 없음)"
