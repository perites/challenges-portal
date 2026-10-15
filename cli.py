import re
from pathlib import Path

import click
from werkzeug.security import generate_password_hash

from db import get_db

CHALLENGES_DIR = Path(__file__).parent / "challenges"
SLUG_RE = re.compile(r"[a-z0-9-]{3,40}")


def prompt_password():
    password = click.prompt("password", hide_input=True, confirmation_prompt=True)
    if len(password) < 6:
        raise click.ClickException("password must be at least 6 chars")
    return password


def register(app):
    @app.cli.command("create-admin")
    @click.argument("name")
    def create_admin(name):
        """Create an admin user, or promote an existing one."""
        db = get_db()
        user = db.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
        if user:
            db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user["id"],))
            click.echo(f"{name} is now admin")
        else:
            db.execute(
                "INSERT INTO users (name, password_hash, is_admin) VALUES (?, ?, 1)",
                (name, generate_password_hash(prompt_password())),
            )
            click.echo(f"admin {name} created")
        db.commit()

    @app.cli.command("reset-password")
    @click.argument("name")
    def reset_password(name):
        """Set a new password for a user."""
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone() is None:
            raise click.ClickException(f"no user named {name}")
        db.execute(
            "UPDATE users SET password_hash = ? WHERE name = ?",
            (generate_password_hash(prompt_password()), name),
        )
        db.commit()
        click.echo(f"password for {name} changed")

    @app.cli.command("add-challenge")
    @click.argument("slug")
    @click.argument("title")
    def add_challenge(slug, title):
        """Register challenges/<slug>.md as a new (current) challenge."""
        if not SLUG_RE.fullmatch(slug):
            raise click.ClickException("slug: 3 to 40 chars, a-z 0-9 -")
        if not (CHALLENGES_DIR / f"{slug}.md").exists():
            raise click.ClickException(f"challenges/{slug}.md not found")
        db = get_db()
        if db.execute("SELECT 1 FROM challenges WHERE slug = ?", (slug,)).fetchone():
            raise click.ClickException(f"challenge {slug} already exists")
        db.execute("INSERT INTO challenges (slug, title) VALUES (?, ?)", (slug, title))
        db.commit()
        click.echo(f"challenge {slug} added")
