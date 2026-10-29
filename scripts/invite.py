"""Create or rotate the reusable registration code. Existing accounts are unaffected."""
import secrets
from app.main import db, digest, MAX_USERS


def main():
    code = secrets.token_urlsafe(24)
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('INSERT OR REPLACE INTO registration_codes(id,hash) VALUES(1,?)', (digest(code),))
        con.execute('DELETE FROM invites')
        total = con.execute('SELECT count(*) FROM users').fetchone()[0]
    print(code)
    print(f'Share this same code with your group. {max(0, MAX_USERS-total)} of {MAX_USERS} account places remain. Existing accounts are unchanged.')

if __name__ == '__main__':
    main()
