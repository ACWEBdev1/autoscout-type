# 1. 非常に新しく安定している「Node.js 20 (Debian 12 Bookworm)」をベースにします
FROM node:20-bookworm

USER root

# 2. Python3と必要なシステムツールをインストール（Debian 12なので最新のaptが動きます）
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    coreutils \
    && rm -rf /var/lib/apt/lists/*

# 3. Pythonのパッケージ（Playwright, Requests）をインストール
# Debian 12では --break-system-packages が必須になります
RUN pip3 install --no-cache-dir --break-system-packages playwright requests

# 4. Playwrightのブラウザ（Chromium）と、それに必要なOSの依存パッケージをインストール
# （古いDebian 10ではここで失敗していましたが、Debian 12なら完璧に成功します）
RUN playwright install chromium \
    && playwright install-deps chromium

# 5. n8n本体を最新のnpm経由でシステムに直接インストールします
# （古いn8nのベースイメージに頼るのをやめ、自前で最新版のn8nを用意します）
RUN npm install -g n8n

# 6. 実行用スクリプトをコピー
WORKDIR /scout
COPY scout_automation.py /scout/scout_automation.py
RUN chmod +x /scout/scout_automation.py

# 7. ボリュームマウント時の権限エラー（EACCES）を回避するためのツール(gosu)をインストール
RUN apt-get update && apt-get install -y gosu && rm -rf /var/lib/apt/lists/*

# 8. 起動スクリプトを作成（起動時にボリュームの権限をnodeユーザーに書き換えてからn8nを起動）
RUN echo '#!/bin/bash\n\
mkdir -p /home/node/.n8n\n\
chown -R node:node /home/node/.n8n\n\
exec gosu node n8n\n\
' > /start.sh && chmod +x /start.sh

# 9. コンテナ起動時にスクリプトを実行
CMD ["/start.sh"]
