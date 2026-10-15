import os
import re
import secrets
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import markdown
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from markupsafe import Markup
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import HtmlLexer
from werkzeug.security import check_password_hash, generate_password_hash

import cli
from db import close_db, get_db, init_db

BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
PAGES_DIR = DATA_DIR / "pages"
THUMBS_DIR = DATA_DIR / "thumbs"
CHALLENGES_DIR = BASE_DIR / "challenges"

USER_NAME_RE = re.compile(r"[a-z0-9_-]{3,20}")
PAGE_NAME_RE = re.compile(r"[a-z0-9-]{3,40}")
MIN_PASSWORD = 6
MAX_DESCRIPTION = 1000
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_THUMB_BYTES = 2 * 1024 * 1024

SORTS = {
    "new": "p.created_at DESC, p.id DESC",
    "fewest": "stars ASC, p.created_at DESC, p.id DESC",
    "most": "stars DESC, p.created_at DESC, p.id DESC",
}


def load_secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    key_file = DATA_DIR / "secret_key"
    try:
        with open(key_file, "x", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return key_file.read_text(encoding="utf-8").strip()


PAGES_DIR.mkdir(parents=True, exist_ok=True)
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    DATABASE=DATA_DIR / "app.db",
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_DEBUG") != "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
app.teardown_appcontext(close_db)
init_db(app.config["DATABASE"])
cli.register(app)


# helpers

def is_admin():
    return g.user is not None and bool(g.user["is_admin"])


def can_edit(page):
    return g.user is not None and (g.user["id"] == page["user_id"] or is_admin())


def current_user_id():
    return g.user["id"] if g.user else None


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("gallery")


def valid_https_url(value):
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and len(value) <= 500
        and not any(c.isspace() for c in value)
    )


def image_ext(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def get_challenges():
    return get_db().execute(
        "SELECT * FROM challenges ORDER BY created_at DESC, id DESC"
    ).fetchall()


def get_page(name):
    page = get_db().execute(
        """SELECT p.*, u.name AS author, c.slug AS challenge_slug, c.title AS challenge_title
           FROM pages p
           JOIN users u ON u.id = p.user_id
           JOIN challenges c ON c.id = p.challenge_id
           WHERE p.name = ?""",
        (name,),
    ).fetchone()
    if page is None or (page["is_deleted"] and not is_admin()):
        abort(404)
    return page


def name_taken(table, name):
    return get_db().execute(f"SELECT 1 FROM {table} WHERE name = ?", (name,)).fetchone() is not None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("log in first", "error")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def start_session(user_id):
    session.clear()
    session.permanent = True
    session["user_id"] = user_id


@app.before_request
def load_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


@app.context_processor
def template_helpers():
    return {"can_edit": can_edit, "is_admin": is_admin}


# gallery and challenges

@app.get("/")
def gallery():
    challenges = get_challenges()
    sort = request.args.get("sort", "new")
    if sort not in SORTS:
        sort = "new"
    author = request.args.get("author", "").strip()
    slug = request.args.get("challenge")
    challenge = next((c for c in challenges if c["slug"] == slug), challenges[0] if challenges else None)

    pages = []
    if challenge:
        author_filter = "AND u.name = ?" if author else ""
        params = [current_user_id(), challenge["id"]] + ([author] if author else [])
        pages = get_db().execute(
            f"""SELECT p.*, u.name AS author, COUNT(s.page_id) AS stars,
                       COALESCE(MAX(s.user_id = ?), 0) AS starred
                FROM pages p
                JOIN users u ON u.id = p.user_id
                LEFT JOIN stars s ON s.page_id = p.id
                WHERE p.challenge_id = ? AND p.is_draft = 0 AND p.is_deleted = 0 {author_filter}
                GROUP BY p.id
                ORDER BY {SORTS[sort]}""",
            params,
        ).fetchall()

    return render_template(
        "gallery.html",
        challenges=challenges,
        challenge=challenge,
        pages=pages,
        sort=sort,
        author=author,
    )


@app.get("/challenges")
@app.get("/challenge/<slug>")
def challenge(slug=None):
    challenges = get_challenges()
    if not challenges:
        return render_template("challenge.html", challenges=[], challenge=None, body=None)
    chosen = next((c for c in challenges if c["slug"] == slug), None) if slug else challenges[0]
    if chosen is None:
        abort(404)
    path = CHALLENGES_DIR / f"{chosen['slug']}.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    body = Markup(markdown.markdown(text, extensions=["extra", "sane_lists"]))
    return render_template("challenge.html", challenges=challenges, challenge=chosen, body=body)


# auth

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        error = None
        if not USER_NAME_RE.fullmatch(name):
            error = "name: 3 to 20 chars, only a-z 0-9 _ -"
        elif len(password) < MIN_PASSWORD:
            error = f"password: at least {MIN_PASSWORD} chars"
        elif password != request.form.get("confirm", ""):
            error = "passwords do not match"
        elif name_taken("users", name):
            error = "name already taken"
        if error:
            flash(error, "error")
            return render_template("register.html", name=name)

        db = get_db()
        cursor = db.execute(
            "INSERT INTO users (name, password_hash) VALUES (?, ?)",
            (name, generate_password_hash(password)),
        )
        db.commit()
        start_session(cursor.lastrowid)
        flash(f"welcome, {name}", "ok")
        return redirect(safe_next(request.args.get("next")))
    return render_template("register.html", name="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        user = get_db().execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], request.form.get("password", "")):
            flash("wrong name or password", "error")
            return render_template("login.html", name=name)
        start_session(user["id"])
        flash(f"hi, {user['name']}", "ok")
        return redirect(safe_next(request.args.get("next")))
    return render_template("login.html", name="")


@app.post("/logout")
def logout():
    session.clear()
    flash("logged out", "ok")
    return redirect(url_for("gallery"))


# submit and edit

def form_values(page=None):
    if request.method == "POST":
        return request.form
    if page:
        return {
            "name": page["name"],
            "challenge_id": str(page["challenge_id"]),
            "description": page["description"],
            "link_url": page["link_url"] or "",
            "git_url": page["git_url"] or "",
            "is_draft": "1" if page["is_draft"] else "",
        }
    challenges = get_challenges()
    return {"challenge_id": str(challenges[0]["id"]) if challenges else ""}


def save_page_form(page=None):
    """Validate the submit/edit form and save it. Returns page name, or None on errors."""
    form = request.form
    name = page["name"] if page else form.get("name", "").strip()
    challenge_id = form.get("challenge_id", type=int)
    description = form.get("description", "").strip()
    link_url = form.get("link_url", "").strip()
    git_url = form.get("git_url", "").strip()
    is_draft = 1 if form.get("is_draft") else 0
    html_file = request.files.get("html_file")
    thumb_file = request.files.get("thumb_file")
    has_html = html_file is not None and html_file.filename != ""
    keeps_file = page is not None and page["kind"] == "file"

    errors = []
    if page is None:
        if not PAGE_NAME_RE.fullmatch(name):
            errors.append("name: 3 to 40 chars, only a-z 0-9 -")
        elif name_taken("pages", name):
            errors.append("page name already taken")
    if challenge_id not in {c["id"] for c in get_challenges()}:
        errors.append("pick a challenge")
    if len(description) > MAX_DESCRIPTION:
        errors.append(f"description: up to {MAX_DESCRIPTION} chars")
    if has_html and link_url:
        errors.append("upload a file or give a link, not both")
    elif not has_html and not link_url and not keeps_file:
        errors.append("upload an html file or give a link")
    if link_url and not valid_https_url(link_url):
        errors.append("link must be a valid https:// url")
    if git_url and not valid_https_url(git_url):
        errors.append("git link must be a valid https:// url")

    html_bytes = None
    if has_html:
        if not html_file.filename.lower().endswith((".html", ".htm")):
            errors.append("file must be .html or .htm")
        else:
            html_bytes = html_file.read()
            if not html_bytes:
                errors.append("html file is empty")
            elif len(html_bytes) > MAX_HTML_BYTES:
                errors.append("html file: up to 5 mb")

    thumb_bytes = thumb_ext = None
    if thumb_file is not None and thumb_file.filename:
        thumb_bytes = thumb_file.read()
        thumb_ext = image_ext(thumb_bytes)
        if thumb_ext is None:
            errors.append("thumbnail must be png, jpg or webp")
        elif len(thumb_bytes) > MAX_THUMB_BYTES:
            errors.append("thumbnail: up to 2 mb")

    if errors:
        for error in errors:
            flash(error, "error")
        return None

    if has_html:
        kind, link_url = "file", None
        (PAGES_DIR / f"{name}.html").write_bytes(html_bytes)
    elif link_url:
        kind = "link"
    else:
        kind, link_url = "file", None
    if thumb_bytes:
        (THUMBS_DIR / f"{name}.{thumb_ext}").write_bytes(thumb_bytes)

    db = get_db()
    if page is None:
        db.execute(
            """INSERT INTO pages (name, challenge_id, user_id, description, kind,
                                  link_url, git_url, thumb_ext, is_draft)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, challenge_id, g.user["id"], description, kind,
             link_url, git_url or None, thumb_ext, is_draft),
        )
    else:
        db.execute(
            """UPDATE pages SET challenge_id = ?, description = ?, kind = ?, link_url = ?,
                                git_url = ?, thumb_ext = COALESCE(?, thumb_ext), is_draft = ?,
                                updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (challenge_id, description, kind, link_url, git_url or None,
             thumb_ext, is_draft, page["id"]),
        )
    db.commit()
    return name


@app.route("/submit", methods=["GET", "POST"])
@login_required
def submit():
    if request.method == "POST":
        name = save_page_form()
        if name:
            flash("draft saved" if request.form.get("is_draft") else "page submitted", "ok")
            return redirect(url_for("page_detail", name=name))
    return render_template("edit.html", page=None, challenges=get_challenges(), values=form_values())


@app.route("/page/<name>/edit", methods=["GET", "POST"])
@login_required
def edit_page(name):
    page = get_page(name)
    if not can_edit(page):
        abort(403)
    if request.method == "POST" and save_page_form(page):
        flash("changes saved", "ok")
        return redirect(url_for("page_detail", name=name))
    return render_template("edit.html", page=page, challenges=get_challenges(), values=form_values(page))


def set_page_flag(name, column, value, message, admin_only=False):
    page = get_page(name)
    if not (is_admin() if admin_only else can_edit(page)):
        abort(403)
    db = get_db()
    db.execute(f"UPDATE pages SET {column} = ? WHERE id = ?", (value, page["id"]))
    db.commit()
    flash(message, "ok")


@app.post("/page/<name>/publish")
@login_required
def publish_page(name):
    set_page_flag(name, "is_draft", 0, "page published")
    return redirect(url_for("page_detail", name=name))


@app.post("/page/<name>/delete")
@login_required
def delete_page(name):
    set_page_flag(name, "is_deleted", 1, "page deleted")
    return redirect(url_for("account"))


@app.post("/page/<name>/restore")
@login_required
def restore_page(name):
    set_page_flag(name, "is_deleted", 0, "page restored", admin_only=True)
    return redirect(url_for("page_detail", name=name))


# page views

@app.get("/page/<name>")
def page_detail(name):
    page = get_page(name)
    stargazers = get_db().execute(
        """SELECT u.id, u.name FROM stars s JOIN users u ON u.id = s.user_id
           WHERE s.page_id = ? ORDER BY s.created_at""",
        (page["id"],),
    ).fetchall()
    starred = any(s["id"] == current_user_id() for s in stargazers)
    view_url = url_for("view_page", name=name) if page["kind"] == "file" else page["link_url"]
    return render_template(
        "page.html", page=page, stargazers=stargazers, starred=starred, view_url=view_url
    )


@app.get("/page/<name>/source")
def page_source(name):
    page = get_page(name)
    if page["kind"] != "file":
        abort(404)
    code = (PAGES_DIR / f"{name}.html").read_bytes().decode("utf-8", errors="replace")
    formatter = HtmlFormatter(style="github-dark", linenos="table")
    return render_template(
        "source.html",
        page=page,
        code=Markup(highlight(code, HtmlLexer(), formatter)),
        css=Markup(formatter.get_style_defs(".highlight")),
    )


@app.post("/page/<name>/star")
def star(name):
    page = get_page(name)
    wants_json = request.headers.get("X-Requested-With") == "fetch"
    back = safe_next(request.form.get("next"))

    if g.user is None:
        if wants_json:
            return jsonify(error="log in to star pages"), 401
        flash("log in to star pages", "error")
        return redirect(url_for("login", next=back))
    if page["user_id"] == g.user["id"]:
        if wants_json:
            return jsonify(error="you can't star your own page"), 400
        flash("you can't star your own page", "error")
        return redirect(back)

    db = get_db()
    removed = db.execute(
        "DELETE FROM stars WHERE user_id = ? AND page_id = ?", (g.user["id"], page["id"])
    ).rowcount
    if not removed:
        db.execute("INSERT INTO stars (user_id, page_id) VALUES (?, ?)", (g.user["id"], page["id"]))
    db.commit()
    starred = not removed
    count = db.execute("SELECT COUNT(*) FROM stars WHERE page_id = ?", (page["id"],)).fetchone()[0]

    if wants_json:
        return jsonify(starred=starred, count=count)
    flash("starred" if starred else "unstarred", "ok")
    return redirect(back)


@app.get("/view/<name>")
def view_page(name):
    page = get_page(name)
    if page["kind"] == "link":
        return redirect(page["link_url"])
    return send_from_directory(PAGES_DIR, f"{name}.html", mimetype="text/html")


@app.get("/thumbs/<path:filename>")
def thumb(filename):
    return send_from_directory(THUMBS_DIR, filename)


# account

@app.get("/account")
@login_required
def account():
    db = get_db()
    pages = db.execute(
        """SELECT p.*, COUNT(s.page_id) AS stars FROM pages p
           LEFT JOIN stars s ON s.page_id = p.id
           WHERE p.user_id = ? AND p.is_deleted = 0
           GROUP BY p.id ORDER BY p.created_at DESC, p.id DESC""",
        (g.user["id"],),
    ).fetchall()
    deleted = []
    if is_admin():
        deleted = db.execute(
            """SELECT p.name, u.name AS author FROM pages p JOIN users u ON u.id = p.user_id
               WHERE p.is_deleted = 1 ORDER BY p.updated_at DESC"""
        ).fetchall()
    return render_template("account.html", pages=pages, deleted=deleted)


@app.post("/account/name")
@login_required
def change_name():
    name = request.form.get("name", "").strip()
    if name == g.user["name"]:
        flash("that is already your name", "error")
    elif not USER_NAME_RE.fullmatch(name):
        flash("name: 3 to 20 chars, only a-z 0-9 _ -", "error")
    elif name_taken("users", name):
        flash("name already taken", "error")
    else:
        db = get_db()
        db.execute("UPDATE users SET name = ? WHERE id = ?", (name, g.user["id"]))
        db.commit()
        flash(f"name changed to {name}", "ok")
    return redirect(url_for("account"))


# errors

@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="this is not yours to change"), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="nothing here"), 404


@app.errorhandler(413)
def too_large(_error):
    return render_template("error.html", code=413, message="upload too big"), 413
