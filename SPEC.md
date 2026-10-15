# API Challenge Portal: Technical Task (v1.0)

Small fun project: a Python web server where friends register, upload their challenge pages
(single `.html` file or external link), browse them in a gallery and star the ones they like.
Keep everything as simple as possible.

## 1. Decisions

- Hosting: Linux VPS with own domain. Caddy (automatic HTTPS) in front of gunicorn.
- One Flask app, one origin. Uploaded pages are served from the same origin as the portal.
  Friends are trusted, so no isolation of their JavaScript.
- Stack: Python 3.12+, Flask, Jinja2, SQLite (`sqlite3`), plain CSS, a little vanilla JS.
  Dependencies: `flask`, `markdown`, `pygments`, `gunicorn`.
- Registration is open, viewing is public.
- Nothing is ever deleted. Pages are hidden with `is_deleted = 1`. Only exception: un-starring
  removes the star row.
- No password change, no login rate limit, no email.
- UI language: English.

## 2. Roles

- **guest**: view gallery, challenges, page details, hosted pages, sources.
- **user**: guest rights + star pages, submit pages, edit and delete own pages, change own name.
- **admin**: user rights + edit, delete and restore any page. Set via CLI.

## 3. Names

- **user name**: `[a-z0-9_-]{3,20}`, unique. Used for login and shown as author name.
  Can be changed on `/account`.
- **page name**: `[a-z0-9-]{3,40}`, unique, used directly in URLs (`/page/fluffy-cats`).
  Fixed after creation. Names of deleted pages stay reserved forever.
- **challenge slug**: `[a-z0-9-]{3,40}`, unique, matches `challenges/<slug>.md`.

## 4. Routes

```
GET       /                        gallery
GET       /challenge[/<slug>]      challenge text (default: newest challenge)
GET/POST  /register                name, password, confirm
GET/POST  /login                   name, password, ?next= (relative paths only)
POST      /logout
GET/POST  /submit                  new page (login required)
GET       /page/<name>             page detail
GET       /page/<name>/source      highlighted html source (file pages only)
POST      /page/<name>/star        toggle star (JSON for fetch, redirect for plain form)
GET/POST  /page/<name>/edit        owner or admin
POST      /page/<name>/publish     draft to published, owner or admin
POST      /page/<name>/delete      sets is_deleted, owner or admin
POST      /page/<name>/restore     clears is_deleted, admin
GET       /view/<name>             raw uploaded html, query string untouched
                                   (link pages redirect to their external url)
GET       /thumbs/<file>           thumbnail images
GET       /account                 own pages + change name (+ deleted pages for admin)
POST      /account/name            change name
```

## 5. Features

### 5.1 Gallery `/`
- Shows pages of one challenge: newest challenge by default, others via `?challenge=<slug>`.
- Card: thumbnail (or placeholder with page name), page name, author, star button with count.
- "submit work" button.
- Sort: newest (default), fewest stars, most stars (`?sort=new|fewest|most`).
- Filter by author: `?author=<name>`.
- Lists only published, not deleted pages.

### 5.2 Challenges
- Challenge texts are markdown files in `challenges/<slug>.md`, rendered as-is.
- Registered with `flask --app app add-challenge <slug> "<title>"`. Newest one is the current one.

### 5.3 Submit and edit
Fields:
- **name**: rules above. Shown read-only on edit.
- **challenge**: dropdown, newest selected by default.
- **description**: optional, up to 1000 chars, plain text, line breaks kept.
- **html file** (`.html` / `.htm`, up to 5 MB, saved byte for byte) **or link** (`https://` only).
  Exactly one on submit.
- **git link**: optional, `https://` only.
- **thumbnail**: optional png, jpg or webp, up to 2 MB. Type checked by file signature.
  SVG not allowed.
- **draft** checkbox: drafts are hidden from the gallery but reachable by their URL.

Edit rules, stated next to each field in the UI:
- empty html file field keeps the current file;
- empty thumbnail field keeps the current thumbnail;
- uploading a file replaces a link, filling a link replaces a file;
- re-uploading overwrites the stored file (no history).

Validation errors show as toasts, entered values are kept.

### 5.4 Page detail `/page/<name>`
- Name, challenge, author, description, created and updated dates, draft/deleted badge.
- Star button with count, list of who starred.
- Live iframe preview (`allow="geolocation; autoplay; clipboard-write; fullscreen"`)
  with a fullscreen button.
- Buttons: open in new window, git (if set), source (file pages), edit, publish (drafts),
  delete, restore (admin, deleted pages).

### 5.5 Stars
- One star per user per page, unlimited in total. Cannot star own page.
- Toggles without page reload; guests get a toast asking them to log in.

### 5.6 Account `/account`
- Own pages (drafts included) with star counts and edit links.
- Change name form.
- Admin: list of deleted pages with restore buttons.

### 5.7 Auth
- Name + password (min 6 chars), Werkzeug password hash.
- Flask signed session cookie: HttpOnly, SameSite=Lax, Secure (except in debug mode), 30 days.
- Forgotten password: admin runs `flask --app app reset-password <name>`.

## 6. Storage

```
data/                     created automatically, back up by copying it
  app.db                  SQLite database
  secret_key              generated on first start (or SECRET_KEY env var)
  pages/<name>.html       uploaded files, saved as-is
  thumbs/<name>.<ext>     thumbnails
challenges/<slug>.md      challenge texts
```

```
users       id, name UNIQUE COLLATE NOCASE, password_hash, is_admin, created_at
challenges  id, slug UNIQUE, title, created_at
pages       id, name UNIQUE, challenge_id, user_id, description,
            kind (file|link), link_url NULL, git_url NULL, thumb_ext NULL,
            is_draft, is_deleted, created_at, updated_at
stars       user_id, page_id, created_at, PRIMARY KEY (user_id, page_id)
```

## 7. Design

- Very minimalistic. Dark navy palette with white text and white accents.
- Lower case everywhere in UI text (user content shown as entered).
- No emojis, no long dashes.
- Toast notifications (bottom right, auto-hide after 4 s, click to close) for every
  success and error message.
- Responsive: single column on phones, grid on desktop.

## 8. CLI

```
flask --app app create-admin <name>     create admin, or promote existing user
flask --app app reset-password <name>
flask --app app add-challenge <slug> "<title>"
```

## 9. Known caveat

All hosted pages share one origin with the portal, so they share localStorage.
Pages using the same storage key with different formats can affect each other.
