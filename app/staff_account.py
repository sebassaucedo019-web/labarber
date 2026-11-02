"""Run python -m app.staff_account USERNAME PHONE to create/reset a staff login."""

import argparse
import getpass
import re

from sqlalchemy import delete

from app.identity import normalize_phone
from app.panel_auth import password_hash
from app.staff import scope
from app.store.models import StaffAccount, StaffSession
from app.store.postgres import get_session, init_db


def main():
    parser = argparse.ArgumentParser(description="Crear o restablecer acceso privado de WAIA")
    parser.add_argument("username")
    parser.add_argument("phone")
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    username = args.username.lower()
    phone = normalize_phone(args.phone)
    if not re.fullmatch(r"[a-z0-9_.-]{1,80}", username) or not phone or not scope(phone):
        parser.error("Usa un usuario válido y un teléfono del equipo ya configurado")
    password = None
    if not args.disable:
        value = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
        if value != getpass.getpass("Repite la contraseña: "):
            parser.error("Las contraseñas no coinciden")
        password = password_hash(value)
    init_db()
    with get_session() as session:
        account = session.get(StaffAccount, username)
        if account is None:
            if args.disable:
                parser.error("No existe ese usuario")
            account = StaffAccount(username=username)
            session.add(account)
        account.wa_id, account.active = phone, not args.disable
        if password:
            account.password_hash = password
        session.execute(delete(StaffSession).where(StaffSession.username == username))
        session.commit()
    print("Acceso actualizado. Las sesiones anteriores quedaron cerradas.")


if __name__ == "__main__":
    main()
