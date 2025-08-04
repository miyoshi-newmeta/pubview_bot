# ベースとなる公式Pythonイメージを指定
FROM python:3.10-slim

# Pythonの出力バッファリングを無効にする環境変数を設定
ENV PYTHONUNBUFFERED=1

# コンテナ内の作業ディレクトリを設定
WORKDIR /app

# まずはライブラリ定義ファイルだけをコピー
COPY requirements.txt .

# ライブラリをインストール
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# コンテナ起動時に実行するコマンドを指定
CMD ["python", "main.py"]
