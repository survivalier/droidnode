from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, send_from_directory, Response, send_file
import time
from datetime import datetime
import os
import shutil
import tempfile
import socket
import subprocess
import json

app = Flask("droidnode")
app.secret_key = "droidnode_by_survivalier"

SAFE_ROOT = os.path.abspath("/droidnode)
MAX_READ_BYTES = 500 * 1024
USERS_FILE = os.path.join(os.path.dirname(__file__), "templates", "user.json")


# ----------------- GESTION UTILISATEURS -----------------

def load_users():
    """Charge et retourne la liste des utilisateurs depuis templates/user.json."""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("users", [])
    except Exception as e:
        app.logger.error(f"Impossible de charger user.json : {e}")
        return []


def get_user(username):
    """Retourne le dict utilisateur correspondant à username, ou None."""
    for u in load_users():
        if u.get("username") == username:
            return u
    return None


def current_user():
    """Retourne le dict de l'utilisateur actuellement connecté, ou None."""
    username = session.get("username")
    if not username:
        return None
    return get_user(username)


def get_wallpaper():
    """Retourne le wallpaper_url de l'utilisateur connecté, ou la valeur par défaut basée sur l'IP du serveur."""
    user = current_user()
    
    if user and "wallpaper_url" in user:
        return user["wallpaper_url"]
    
    # Récupère l'IP ou le nom de domaine (ex: 192.168.1.10:5000)
    server_ip = request.host
    
    return f"http://{server_ip}/background"


def require_login():
    if not session.get("logged_in"):
        abort(401)


# ----------------- SÉCURITÉ DES CHEMINS -----------------

def safe_path_join(base, user_path):
    """
    Vérifie que user_path reste dans `base` ET dans l'un des allowed_paths
    de l'utilisateur connecté.
    """
    base_real = os.path.realpath(base)

    if not user_path or user_path == "/":
        return base_real

    candidate = os.path.join(base_real, user_path.lstrip("/"))
    target = os.path.realpath(candidate)

    # Vérification confinement dans SAFE_ROOT
    if not target.startswith(base_real):
        raise ValueError("Accès interdit : chemin hors de la racine.")

    # Vérification allowed_paths de l'utilisateur
    user = current_user()
    if user is not None:
        allowed = user.get("allowed_paths", [])
        # "/" = accès total
        if "/" not in allowed:
            rel = "/" + os.path.relpath(target, base_real)
            authorized = any(
                rel == ap or rel.startswith(ap.rstrip("/") + "/")
                for ap in allowed
            )
            if not authorized:
                raise ValueError(f"Accès interdit : chemin non autorisé ({rel}).")

    return target


# ----------------- ROUTES -----------------
@app.route("/background")
def serve_background():
    # On définit le chemin vers le dossier templates
    templates_dir = os.path.join(app.root_path, "templates")
    # On envoie le fichier background.png depuis ce dossier
    return send_from_directory(templates_dir, "background.png")


@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_user(username)
        if user and user.get("password") == password:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("dashboard"))
        else:
            time.sleep(1)
            error = "Identifiants incorrects."

    return render_template("login.html", error=error, wallpaper_url=get_wallpaper())


@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    now = datetime.now()
    return render_template("dashboard.html",
                           wallpaper_url=get_wallpaper(),
                           username=session.get("username", ""),
                           current_time=now.strftime("%H:%M:%S"),
                           current_date=now.strftime("%d/%m/%Y"))


@app.route("/settings", methods=["POST"])
def settings():
    require_login()
    username = session.get("username")
    users_data = {"users": load_users()}

    for u in users_data["users"]:
        if u["username"] == username:
            new_wall = request.form.get("wallpaper_url")
            if new_wall:
                u["wallpaper_url"] = new_wall
            new_pw = request.form.get("new_password")
            if new_pw:
                u["password"] = new_pw
            break

    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        app.logger.error(f"Erreur écriture user.json : {e}")

    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/web")
@app.route("/web/<path:filename>")
def serve_web_dev(filename=""):
    web_dev_root = os.path.join(SAFE_ROOT, "web dev")
    error_root = os.path.join(web_dev_root, "error")
    os.makedirs(web_dev_root, exist_ok=True)
    try:
        is_forced_dir = filename.endswith("/")
        target = safe_path_join(web_dev_root, filename.rstrip("/"))
        if not os.path.exists(target):
            raise FileNotFoundError()
        if os.path.isdir(target) or is_forced_dir:
            for candidate in ["index.html", "index.htm", "index", ".index"]:
                p = os.path.join(target, candidate)
                if os.path.exists(p):
                    if candidate == "index":
                        with open(p, "r", encoding="utf-8", errors="replace") as f:
                            return Response(f.read(), content_type="text/html; charset=utf-8")
                    return send_from_directory(target, candidate)
            e403 = os.path.join(error_root, "403.html")
            return (send_from_directory(error_root, "403.html"), 403) if os.path.exists(e403) else abort(403)
        fn = os.path.basename(target)
        if fn == "index":
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                return Response(f.read(), content_type="text/html; charset=utf-8")
        return send_from_directory(os.path.dirname(target), fn)
    except Exception:
        e404 = os.path.join(error_root, "404.html")
        return (send_from_directory(error_root, "404.html"), 404) if os.path.exists(e404) else abort(404)


@app.route("/droid node web server/help")
def server_help():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "IP introuvable"
    now = datetime.now()
    return render_template("webserver/help.html",
                           wallpaper_url=get_wallpaper(),
                           local_ip=local_ip,
                           current_time=now.strftime("%H:%M:%S"),
                           current_date=now.strftime("%d/%m/%Y"))


# ----------------- API DISQUE -----------------

@app.route("/api/disk")
def api_disk():
    require_login()
    try:
        usage = shutil.disk_usage(SAFE_ROOT)
        total = usage.total
        used  = usage.used
        free  = usage.free
        pct   = round(used * 100 / total, 1) if total else 0

        partitions = []

        try:
            r = subprocess.run(["df", "-k", SAFE_ROOT],
                               capture_output=True, text=True, timeout=5)
            lines = r.stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[-1].split()
                if len(parts) >= 6:
                    partitions.append({
                        "label":      "Termux / stockage interne",
                        "filesystem": parts[0],
                        "mountpoint": parts[5],
                        "total_kb":   int(parts[1]) if parts[1].isdigit() else None,
                        "used_kb":    int(parts[2]) if parts[2].isdigit() else None,
                        "free_kb":    int(parts[3]) if parts[3].isdigit() else None,
                        "use_pct":    parts[4],
                    })
        except Exception:
            pass

        for sdcard in ("/sdcard", "/storage/emulated/0", "/storage/self/primary"):
            if os.path.exists(sdcard):
                try:
                    sd = shutil.disk_usage(sdcard)
                    partitions.append({
                        "label":      "Stockage interne Android",
                        "filesystem": "sdcard",
                        "mountpoint": sdcard,
                        "total_kb":   sd.total // 1024,
                        "used_kb":    sd.used  // 1024,
                        "free_kb":    sd.free  // 1024,
                        "use_pct":    f"{round(sd.used*100/sd.total,1)}%" if sd.total else "—",
                    })
                    break
                except Exception:
                    pass

        for ext in ("/storage/sdcard1", "/mnt/media_rw/sdcard1", "/mnt/sdcard1"):
            if os.path.exists(ext):
                try:
                    sd2 = shutil.disk_usage(ext)
                    partitions.append({
                        "label":      "Carte SD externe",
                        "filesystem": "sdcard1",
                        "mountpoint": ext,
                        "total_kb":   sd2.total // 1024,
                        "used_kb":    sd2.used  // 1024,
                        "free_kb":    sd2.free  // 1024,
                        "use_pct":    f"{round(sd2.used*100/sd2.total,1)}%" if sd2.total else "—",
                    })
                    break
                except Exception:
                    pass

        return jsonify({"total": total, "used": used, "free": free,
                        "pct": pct, "partitions": partitions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------- API SYSTÈME -----------------

@app.route("/api/system/set-time", methods=["POST"])
def set_system_time():
    require_login()
    data = request.json
    new_date = data.get("date")
    new_time_val = data.get("time")
    if not new_date or not new_time_val:
        return jsonify({"error": "Données incomplètes"}), 400
    try:
        fmt = f"{new_date[5:7]}{new_date[8:10]}{new_time_val[0:2]}{new_time_val[3:5]}{new_date[0:4]}"
        result = subprocess.run(['su', '-c', f'date {fmt}'], capture_output=True, text=True)
        if result.returncode != 0:
            return jsonify({"ok": False, "error": "Root requis"}), 403
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------- API FICHIERS -----------------

@app.route("/api/list")
def api_list():
    require_login()
    path_req = request.args.get("path", "/")
    try:
        target = safe_path_join(SAFE_ROOT, path_req)
        entries = []
        for name in sorted(os.listdir(target), key=lambda x: x.lower()):
            p = os.path.join(target, name)
            st = os.stat(p)
            rel_p = os.path.relpath(p, SAFE_ROOT)
            entries.append({
                "name":   name,
                "path":   "/" + rel_p if rel_p != "." else "/",
                "is_dir": os.path.isdir(p),
                "size":   st.st_size
            })
        return jsonify({"path": path_req, "entries": entries})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/read")
def api_read():
    require_login()
    path_req = request.args.get("path")
    offset = int(request.args.get("offset", 0))  # position de lecture

    try:
        target = safe_path_join(SAFE_ROOT, path_req)

        # Taille totale du fichier
        file_size = os.path.getsize(target)

        # Lecture partielle (chunk)
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            content = f.read(MAX_READ_BYTES)

        # Calcul de la suite
        next_offset = offset + len(content)
        eof = next_offset >= file_size

        return jsonify({
            "content": content,
            "offset": offset,
            "next_offset": next_offset,
            "eof": eof,
            "total_size": file_size
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/write", methods=["POST"])
def api_write():
    require_login()
    data = request.json
    try:
        target = safe_path_join(SAFE_ROOT, data.get("path"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(data.get("content", ""))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rename", methods=["POST"])
def api_rename():
    require_login()
    data = request.json
    try:
        old_path = safe_path_join(SAFE_ROOT, data.get("old_path"))
        new_path = safe_path_join(SAFE_ROOT, data.get("new_path"))
        os.rename(old_path, new_path)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/copy", methods=["POST"])
def api_copy():
    require_login()
    data = request.json
    try:
        src  = safe_path_join(SAFE_ROOT, data.get("src"))
        dest = safe_path_join(SAFE_ROOT, data.get("dest"))
        if os.path.isdir(src):
            shutil.copytree(src, dest)
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/paste", methods=["POST"])
def api_paste():
    require_login()
    data = request.json
    try:
        src        = safe_path_join(SAFE_ROOT, data.get("source"))
        dest_dir   = safe_path_join(SAFE_ROOT, data.get("destination"))
        final_dest = os.path.join(dest_dir, os.path.basename(src))
        if data.get("action") == "cut":
            shutil.move(src, final_dest)
        else:
            shutil.copytree(src, final_dest) if os.path.isdir(src) else shutil.copy2(src, final_dest)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/create", methods=["POST"])
def api_create():
    require_login()
    data = request.json
    try:
        target = safe_path_join(SAFE_ROOT, data.get("path"))
        if data.get("is_dir"):
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            open(target, "w").close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/delete", methods=["POST"])
def api_delete():
    require_login()
    path_req = request.json.get("path")
    try:
        target = safe_path_join(SAFE_ROOT, path_req)
        shutil.rmtree(target) if os.path.isdir(target) else os.remove(target)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload", methods=["POST"])
def api_upload():
    require_login()
    file     = request.files.get("file")
    path_req = request.form.get("path")
    if not file:
        return jsonify({"error": "Aucun fichier"}), 400
    try:
        target = safe_path_join(SAFE_ROOT, path_req)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        file.save(target)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download")
def api_download():
    require_login()
    path_req = request.args.get("path")
    try:
        target = safe_path_join(SAFE_ROOT, path_req)
        if os.path.isdir(target):
            zip_base = os.path.join(tempfile.gettempdir(), os.path.basename(target))
            zip_path = shutil.make_archive(zip_base, "zip", target)
            return send_file(zip_path, as_attachment=True,
                             download_name=f"{os.path.basename(target)}.zip")
        return send_from_directory(os.path.dirname(target),
                                   os.path.basename(target), as_attachment=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/exec", methods=["POST"])
def api_exec():
    require_login()
    cmd = request.json.get("cmd", "").strip()
    if not cmd:
        return jsonify({"output": ""}), 200
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=15, cwd=SAFE_ROOT)
        out = r.stdout + (("\n" + r.stderr) if r.stderr else "")
        return jsonify({"output": out.rstrip()})
    except subprocess.TimeoutExpired:
        return jsonify({"output": "Timeout (15s)"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------- ERREURS GLOBALES -----------------

@app.errorhandler(401)
def error_401(e): return render_template("401.html"), 401

@app.errorhandler(403)
def error_403(e): return render_template("403.html"), 403

@app.errorhandler(404)
def error_404(e): return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
