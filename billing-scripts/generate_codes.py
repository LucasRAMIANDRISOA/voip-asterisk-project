import psycopg2
import secrets
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
def generate_code():
    # Code lisible du type XXXX-XXXX-XXXX
    raw = secrets.token_hex(6).upper()
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"

def hash_code(code):
    return hashlib.sha256(code.encode()).hexdigest()

def create_codes(montant, quantite):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    codes_generes = []

    for _ in range(quantite):
        code = generate_code()
        code_hash = hash_code(code)
        cur.execute(
            "INSERT INTO recharge_codes (code_hash, montant) VALUES (%s, %s)",
            (code_hash, montant)
        )
        codes_generes.append(code)

    conn.commit()
    cur.close()
    conn.close()
    return codes_generes

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 generate_codes.py <montant> <quantite>")
        print("Exemple: python3 generate_codes.py 1000 5")
        sys.exit(1)

    montant = float(sys.argv[1])
    quantite = int(sys.argv[2])

    codes = create_codes(montant, quantite)

    from datetime import datetime
    filename = f"codes_{int(montant)}Ar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    with open(filename, "w") as f:
        f.write(f"Codes de recharge {montant} Ar - generes le {datetime.now()}\n")
        f.write("=" * 50 + "\n\n")
        for c in codes:
            f.write(c + "\n")

    print(f"\n{quantite} code(s) de recharge de {montant} Ar generes :\n")
    for c in codes:
        print(f"  {c}")
    print(f"\nCodes egalement sauvegardes dans : {filename}")
    print("ATTENTION : ce fichier est la SEULE copie en clair. Securise-le puis supprime-le du serveur une fois distribue.\n")
