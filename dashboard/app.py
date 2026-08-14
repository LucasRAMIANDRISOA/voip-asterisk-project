from flask import Flask, render_template, request, redirect, send_from_directory
from flask import Flask, render_template, request, redirect
from flask import Flask, render_template, request
import psycopg2
import secrets
import os
import psycopg2.extras
from datetime import datetime, timedelta
import hashlib

app = Flask(__name__)

import os
from dotenv import load_dotenv
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

@app.route("/")
def index():
    period = request.args.get("period", "all")

    now = datetime.now()
    date_from = None
    date_to = None

    if period == "today":
        date_from = now.strftime("%Y-%m-%d 00:00:00")
        date_to = now.strftime("%Y-%m-%d 23:59:59")
    elif period == "yesterday":
        y = now - timedelta(days=1)
        date_from = y.strftime("%Y-%m-%d 00:00:00")
        date_to = y.strftime("%Y-%m-%d 23:59:59")
    elif period == "month":
        date_from = now.strftime("%Y-%m-01 00:00:00")
        date_to = now.strftime("%Y-%m-%d 23:59:59")

    where_clause = ""
    params = []
    if date_from and date_to:
        where_clause = "WHERE calldate BETWEEN %s AND %s"
        params = [date_from, date_to]

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(f"""
        SELECT calldate, src, dst, duration, billsec, disposition
        FROM cdr
        {where_clause}
        ORDER BY calldate DESC
        LIMIT 50
    """, params)
    calls = cur.fetchall()

    cur.execute(f"SELECT COUNT(*) AS total_calls FROM cdr {where_clause}", params)
    total_calls = cur.fetchone()["total_calls"]

    answered_where = where_clause + (" AND" if where_clause else "WHERE") + " disposition='ANSWERED'"
    cur.execute(f"SELECT COALESCE(SUM(duration),0) AS total_duration, COALESCE(SUM(billsec),0) AS total_billsec FROM cdr {answered_where}", params)
    row = cur.fetchone()
    total_duration = row["total_duration"]
    total_billsec = row["total_billsec"]

    cur.execute(f"""
        SELECT src, COUNT(*) AS nb_appels, COALESCE(SUM(billsec),0) AS duree_totale
        FROM cdr
        {where_clause}
        GROUP BY src
        ORDER BY nb_appels DESC
    """, params)
    stats_users = cur.fetchall()

    # --- Donnees de billing ---
    cur.execute("""
        SELECT extension, nom, solde, cout_par_seconde, actif
        FROM billing_accounts
        ORDER BY extension
    """)
    accounts = cur.fetchall()

    cur.execute("""
        SELECT extension, montant, date_recharge
        FROM recharge_history
        ORDER BY date_recharge DESC
        LIMIT 20
    """)
    recharges = cur.fetchall()

    cur.execute("""
        SELECT extension, destination, duree_sec, cout, date_appel
        FROM billing_calls
        ORDER BY date_appel DESC
        LIMIT 20
    """)
    billing_calls = cur.fetchall()

    cur.execute("SELECT COUNT(*) AS total FROM recharge_codes WHERE utilise = false")
    codes_disponibles = cur.fetchone()["total"]

    cur.close()
    conn.close()

    return render_template(
        "index.html",
        calls=calls,
        total_calls=total_calls,
        total_duration=total_duration,
        total_billsec=total_billsec,
        stats_users=stats_users,
        current_period=period,
        accounts=accounts,
        recharges=recharges,
        billing_calls=billing_calls,
        codes_disponibles=codes_disponibles
    )
@app.route("/recharge", methods=["GET", "POST"])
def recharge():
    message = None
    success = False

    if request.method == "POST":
        extension = request.form.get("extension", "").strip()
        code = request.form.get("code", "").strip().upper()
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT id, montant FROM recharge_codes WHERE code_hash = %s AND utilise = false",
            (code_hash,)
        )
        result = cur.fetchone()

        if not result:
            message = "Code invalide ou deja utilise."
        else:
            code_id, montant = result
            cur.execute("SELECT solde FROM billing_accounts WHERE extension = %s", (extension,))
            account = cur.fetchone()

            if not account:
                message = f"Extension {extension} introuvable."
            else:
                solde_avant = account[0]
                solde_apres = solde_avant + montant

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
                message = f"Recharge reussie : +{montant} Ar sur {extension}. Nouveau solde : {solde_apres} Ar."
                success = True

        cur.close()
        conn.close()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT extension, nom FROM billing_accounts ORDER BY extension")
    accounts = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("recharge.html", message=message, success=success, accounts=accounts)
@app.route("/reset", methods=["GET", "POST"])
def reset():
    message = None
    success = False

    if request.method == "POST":
        confirm = request.form.get("confirm", "")
        if confirm != "EFFACER":
            message = "Confirmation incorrecte. Tape exactement EFFACER pour valider."
        else:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("TRUNCATE TABLE cdr, billing_calls, recharge_history RESTART IDENTITY")
            cur.execute("UPDATE billing_accounts SET solde = 0")
            conn.commit()
            cur.close()
            conn.close()
            message = "Historique efface : journal d'appels, facturation, recharges. Soldes remis a zero."
            success = True

    return render_template("reset.html", message=message, success=success)
@app.route("/reset-balance/<extension>", methods=["POST"])
def reset_balance(extension):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE billing_accounts SET solde = 0 WHERE extension = %s", (extension,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect("/")
CODES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_codes")
os.makedirs(CODES_DIR, exist_ok=True)

def generate_code_string():
    raw = secrets.token_hex(6).upper()
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"

@app.route("/generate-codes", methods=["GET", "POST"])
def generate_codes_route():
    message = None
    filename = None

    if request.method == "POST":
        montant = float(request.form.get("montant"))
        quantite = int(request.form.get("quantite"))

        conn = get_connection()
        cur = conn.cursor()
        codes = []

        for _ in range(quantite):
            code = generate_code_string()
            code_hash = hashlib.sha256(code.encode()).hexdigest()
            cur.execute(
                "INSERT INTO recharge_codes (code_hash, montant) VALUES (%s, %s)",
                (code_hash, montant)
            )
            codes.append(code)

        conn.commit()
        cur.close()
        conn.close()

        from datetime import datetime
        filename = f"codes_{int(montant)}Ar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(CODES_DIR, filename)

        with open(filepath, "w") as f:
            f.write(f"Codes de recharge {montant} Ar - generes le {datetime.now()}\n")
            f.write("=" * 50 + "\n\n")
            for c in codes:
                f.write(c + "\n")

        message = f"{quantite} code(s) de {montant} Ar generes avec succes."

    return render_template("generate_codes.html", message=message, filename=filename)

@app.route("/download-codes/<filename>")
def download_codes(filename):
    return send_from_directory(CODES_DIR, filename, as_attachment=True)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
