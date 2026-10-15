"""Tek seferlik kurulum: Tapo kimlik bilgilerini Windows Credential Manager'a yazar."""
import getpass
import sys

import keyring

KEYRING_SERVICE = "Pasa-Tapo"

def main():
    print("Paşa - Akıllı Priz kurulum")
    print("-" * 40)

    mevcut_email = keyring.get_password(KEYRING_SERVICE, "email")
    if mevcut_email:
        print(f"Kayıtlı e-posta: {mevcut_email}")
        if input("Üzerine yazmak ister misin? (e/H): ").strip().lower() != "e":
            print("İptal edildi.")
            return 0

    email = input("Tapo e-posta: ").strip()
    if not email:
        print("E-posta boş olamaz.", file=sys.stderr)
        return 1

    sifre = getpass.getpass("Tapo şifre: ")
    if not sifre:
        print("Şifre boş olamaz.", file=sys.stderr)
        return 1

    keyring.set_password(KEYRING_SERVICE, "email", email)
    keyring.set_password(KEYRING_SERVICE, "sifre", sifre)
    print("✅ Kimlik bilgileri Windows Credential Manager'a kaydedildi.")
    print("   Artık priz.py keyring'den okuyacak, kodda düz metin şifre yok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
