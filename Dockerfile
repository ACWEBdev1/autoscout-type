FROM n8nio/n8n:latest-debian

USER root

# 1. Python環境とPlaywrightの依存パッケージ、およびbase64（coreutils）をインストール
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    coreutils \
    && rm -rf /var/lib/apt/lists/*

# 2. pipの警告（Break System Packages）を回避してPlaywrightとrequestsをシステムにインストール
RUN pip3 install --no-cache-dir --break-system-packages playwright requests

# 3. Playwright用ブラウザ（Chromium）とそのOSレベルの依存関係をインストール
RUN playwright install chromium \
    && playwright install-deps chromium

# 4. 実行用スクリプトをコンテナ内へコピーできるようにディレクトリを作成
# （GitHubからデプロイする際、同じ階層にある scout_automation.py がコピーされます）
WORKDIR /scout
COPY scout_automation.py /scout/scout_automation.py
RUN chmod +x /scout/scout_automation.py

# 権限をn8nを動かす標準のnodeユーザーに戻す
USER node
