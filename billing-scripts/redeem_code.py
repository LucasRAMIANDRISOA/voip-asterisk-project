import psycopg2
import hashlib
import sys
import os
from dotenv import load_dotenv
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}

def hash_code(code):
    return hashlib.sha256(code.encode()).hexdigest()

def redeem(extension, code):
    code_hash = hash_code(code.strip().upper())
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Verifier que le code existe et n'est pas deja utilise
    cur.execute(
        "SELECT id, montant FROM recharge_codes WHERE code_hash = %s AND utilise = false",
        (code_hash,)
    )
    result = cur.fetchone()

    if not result:
        print("ERREUR: code invalide ou deja utilise.")
        cur.close()
        conn.close()
        return False

    code_id, montant = result

    # Verifier que le compte existe
    cur.execute("SELECT solde FROM billing_accounts WHERE extension = %s", (extension,))
    account = cur.fetchone()
    if not account:
        print(f"ERREUR: extension {extension} introuvable.")
        cur.close()
        conn.close()
        return False

    solde_avant = account[0]
    solde_apres = solde_avant + montant

    # Transaction : marquer le code utilise + crediter le compte + logger
    cur.execute(
        "UPDATE recharge_codes SET utilise = true, utilise_par = %s, utilise_le = now() WHERE id = %s",
        (extension, code_id)
    )
    cur.execute(
        "UPDATE billing_accounts SET solde = %s WHERE extension = %s",
        (solde_apres, extension)
    )
    cur.execute(
        "INSERT INTO recharge_history (extension, montant, solde_avant, solde_apres) VALUES (%s, %s, %s, %s)",
        (extension, montant, solde_avant, solde_apres)
    )

    conn.commit()
    cur.close()
    conn.close()

    print(f"Recharge reussie: +{montant} Ar sur le compte {extension}")
    print(f"Nouveau solde: {solde_apres} Ar")
    return True

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 redeem_code.py <extension> <code>")
        sys.exit(1)

    extension = sys.argv[1]
    code = sys.argv[2]
    redeem(extension, code)
