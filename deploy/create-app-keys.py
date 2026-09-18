"""Run as root on the server; never prints credentials or overwrites existing keys."""
import json
import os
from pathlib import Path
import pwd
import secrets

apps = (
    'admin', 'sara', 'skilldex', 'alumni', 'examgen', 'slidercreator',
    'smartdoc', 'enterprisechat', 'guardai', 'agentagenda', 'sarapad'
)
keyfile = Path('/etc/ailauncher/app-keys.json')
keyfile.parent.mkdir(mode=0o750, exist_ok=True)
keys = json.loads(keyfile.read_text()) if keyfile.exists() else {}
for app in apps:
    keys.setdefault(app, secrets.token_urlsafe(36))
os.umask(0o077)
keyfile.write_text(json.dumps(keys))
os.chown(keyfile, 10001, 10001)
keyfile.chmod(0o400)
owner = pwd.getpwnam('cite')
clients = Path('/home/cite/local-ai/clients')
clients.mkdir(mode=0o700, exist_ok=True)
os.chown(clients, owner.pw_uid, owner.pw_gid)
for app in apps:
    target = clients / (app + '.env')
    target.write_text('OPENAI_BASE_URL=http://llm-gateway:8000/v1\nOPENAI_MODEL=qwen-local\nOPENAI_API_KEY=' + keys[app] + '\n')
    os.chown(target, owner.pw_uid, owner.pw_gid)
    target.chmod(0o600)
