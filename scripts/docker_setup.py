"""Migrate local accounts to Docker's bind-mounted data directory. Stop the app first."""
import os
from pathlib import Path
import sqlite3
from dotenv import dotenv_values, set_key


def main():
    root=Path(__file__).resolve().parents[1]
    env=root/'.env'
    if not env.exists():
        env.write_text((root/'.env.example').read_text())
    source=Path(dotenv_values(env).get('DATABASE_PATH') or 'localai.sqlite3')
    if not source.is_absolute():
        source=root/source
    target=root/'data'/'localai.sqlite3'
    target.parent.mkdir(exist_ok=True,mode=0o700)
    if source.resolve()!=target.resolve() and source.exists():
        if target.exists():
            raise SystemExit('Docker database already exists. Refusing to overwrite accounts; review DATABASE_PATH.')
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
        target.chmod(0o600)
        print('Existing accounts, sessions and invitations copied to data/localai.sqlite3. Original retained.')
    set_key(str(env),'DATABASE_PATH','data/localai.sqlite3')
    set_key(str(env),'LOCALAI_UID',str(os.getuid()))
    set_key(str(env),'LOCALAI_GID',str(os.getgid()))
    print('Docker data directory and user mapping configured.')

if __name__=='__main__':
    main()
