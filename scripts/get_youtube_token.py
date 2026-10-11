from __future__ import annotations
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    root = Path(__file__).resolve().parents[1]
    client_path = Path(input("Google Cloud'dan indirdiginiz OAuth istemci JSON dosyasinin yolu [client_secret.json]: ").strip().strip('"') or "client_secret.json")
    if not client_path.is_absolute():
        client_path = Path.cwd() / client_path
    if not client_path.exists():
        raise SystemExit(f"Dosya bulunamadi: {client_path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", authorization_prompt_message="Tarayicida YouTube kanalina erisim izni verin.")
    if not creds.refresh_token:
        raise SystemExit("Refresh token alinmadi. Google izin ekraninda erisimi onaylayip tekrar deneyin.")
    token = json.loads(creds.to_json())
    token_path = root / "authorized_user.json"
    token_path.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Token dosyasi olusturuldu: {token_path}")
    print("Bu dosyayi GitHub deposuna yuklemeyin. Icerigini Settings > Secrets and variables > Actions > YOUTUBE_TOKEN_JSON secret'ina yapistirin.")
    print("Guvenlik icin isiniz bitince client_secret JSON dosyasini ve token dosyasini paylasmayin.")

if __name__ == "__main__":
    main()
