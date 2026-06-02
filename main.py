from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import hashlib
import jwt
import datetime
import os

# ==================== КОНФИГ ====================
SECRET_KEY = "kumis-japyrak-2024-secret"
DB_NAME = "library.db"

app = FastAPI(title="Күміс жапырақ", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== БАЗА ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            avatar TEXT DEFAULT '📖',
            role TEXT DEFAULT 'user',
            banned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            author TEXT DEFAULT '',
            description TEXT DEFAULT '',
            genre TEXT DEFAULT 'Жалпы',
            pages TEXT NOT NULL,
            likes INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            hidden INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            hidden INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            UNIQUE(book_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            page INTEGER DEFAULT 1,
            UNIQUE(book_id, user_id)
        );

        INSERT OR IGNORE INTO users (username, password, role) 
        VALUES ('admin', '{}', 'admin');
    '''.format(hashlib.sha256('admin123'.encode()).hexdigest()))
    conn.commit()
    conn.close()

init_db()

# ==================== МОДЕЛЬДЕР ====================
class UserAuth(BaseModel):
    username: str
    password: str

class BookCreate(BaseModel):
    title: str
    author: str = ""
    description: str = ""
    genre: str = "Жалпы"
    pages: List[str]

class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    genre: Optional[str] = None
    pages: Optional[List[str]] = None

class CommentCreate(BaseModel):
    book_id: int
    text: str

# ==================== КӨМЕКШІ ====================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def get_user(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (payload["user_id"],)).fetchone()
        conn.close()
        if not user or user["banned"]:
            raise HTTPException(403, "Бұғатталған")
        return user
    except:
        raise HTTPException(401, "Рұқсат жоқ")

def is_admin(user):
    return user["role"] == "admin"

# ==================== ТІРКЕЛУ / КІРУ ====================
@app.post("/api/register")
def register(data: UserAuth):
    if len(data.username) < 3:
        raise HTTPException(400, "Аты кемінде 3 таңба")
    if len(data.password) < 4:
        raise HTTPException(400, "Құпиясөз кемінде 4 таңба")
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (username,password) VALUES (?,?)",
                     (data.username, hashlib.sha256(data.password.encode()).hexdigest()))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE username=?", (data.username,)).fetchone()
        token = jwt.encode({"user_id": user["id"], "role": user["role"]}, SECRET_KEY, algorithm="HS256")
        return {"token": token, "user_id": user["id"], "username": user["username"], "role": user["role"]}
    except:
        raise HTTPException(400, "Бұл атпен қолданушы бар")
    finally:
        conn.close()

@app.post("/api/login")
def login(data: UserAuth):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
                        (data.username, hashlib.sha256(data.password.encode()).hexdigest())).fetchone()
    conn.close()
    if not user:
        raise HTTPException(401, "Аты немесе құпиясөз қате")
    if user["banned"]:
        raise HTTPException(403, "Аккаунт бұғатталған")
    token = jwt.encode({"user_id": user["id"], "role": user["role"]}, SECRET_KEY, algorithm="HS256")
    return {"token": token, "user_id": user["id"], "username": user["username"], "role": user["role"]}

@app.get("/api/me")
def me(token: str):
    user = get_user(token)
    return {"id": user["id"], "username": user["username"], "avatar": user["avatar"], "role": user["role"]}

# ==================== АВТОРЛАР ====================
@app.get("/api/authors")
def get_authors():
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.username, COUNT(b.id) as count 
        FROM users u JOIN books b ON u.id = b.user_id 
        WHERE b.hidden=0 GROUP BY u.id ORDER BY count DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ==================== КІТАПТАР ====================
@app.get("/api/books")
def get_books(search: str = "", genre: str = "", sort: str = "newest", author: int = 0):
    conn = get_db()
    q = "SELECT b.*, u.username FROM books b JOIN users u ON b.user_id=u.id WHERE b.hidden=0"
    params = []
    if search:
        q += " AND (b.title LIKE ? OR b.author LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if genre:
        q += " AND b.genre=?"
        params.append(genre)
    if author:
        q += " AND b.user_id=?"
        params.append(author)
    order = "b.created_at DESC" if sort == "newest" else "b.likes DESC" if sort == "popular" else "b.views DESC"
    q += f" ORDER BY {order}"
    books = conn.execute(q, params).fetchall()
    conn.close()
    return [{
        "id": b["id"], "user_id": b["user_id"], "username": b["username"],
        "title": b["title"], "author": b["author"], "description": b["description"],
        "genre": b["genre"], "pages": b["pages"].split("|||"),
        "likes": b["likes"], "views": b["views"],
        "page_count": len(b["pages"].split("|||")),
        "created_at": b["created_at"], "updated_at": b["updated_at"]
    } for b in books]

@app.get("/api/books/{book_id}")
def get_book(book_id: int):
    conn = get_db()
    b = conn.execute("SELECT b.*, u.username FROM books b JOIN users u ON b.user_id=u.id WHERE b.id=?",
                     (book_id,)).fetchone()
    if not b:
        conn.close()
        raise HTTPException(404)
    conn.execute("UPDATE books SET views=views+1 WHERE id=?", (book_id,))
    conn.commit()
    comments = conn.execute("""
        SELECT c.*, u.username FROM comments c 
        JOIN users u ON c.user_id=u.id 
        WHERE c.book_id=? AND c.hidden=0 ORDER BY c.created_at DESC
    """, (book_id,)).fetchall()
    conn.close()
    return {
        "id": b["id"], "user_id": b["user_id"], "username": b["username"],
        "title": b["title"], "author": b["author"], "description": b["description"],
        "genre": b["genre"], "pages": b["pages"].split("|||"),
        "likes": b["likes"], "views": b["views"],
        "page_count": len(b["pages"].split("|||")),
        "created_at": b["created_at"], "comments": [dict(c) for c in comments]
    }

@app.post("/api/books")
def create_book(data: BookCreate, token: str):
    user = get_user(token)
    conn = get_db()
    c = conn.execute("INSERT INTO books (user_id,title,author,description,genre,pages) VALUES (?,?,?,?,?,?)",
                     (user["id"], data.title, data.author, data.description, data.genre, "|||".join(data.pages)))
    conn.commit()
    bid = c.lastrowid
    conn.close()
    return {"id": bid, "message": "Кітап сақталды ✅"}

@app.put("/api/books/{book_id}")
def update_book(book_id: int, data: BookUpdate, token: str):
    user = get_user(token)
    conn = get_db()
    b = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not b:
        conn.close()
        raise HTTPException(404)
    if b["user_id"] != user["id"] and not is_admin(user):
        conn.close()
        raise HTTPException(403)
    updates = []
    params = []
    for field in ["title", "author", "description", "genre"]:
        val = getattr(data, field)
        if val is not None:
            updates.append(f"{field}=?")
            params.append(val)
    if data.pages is not None:
        updates.append("pages=?")
        params.append("|||".join(data.pages))
    if updates:
        updates.append("updated_at=datetime('now')")
        params.append(book_id)
        conn.execute(f"UPDATE books SET {','.join(updates)} WHERE id=?", params)
        conn.commit()
    conn.close()
    return {"message": "Жаңартылды ✅"}

@app.delete("/api/books/{book_id}")
def delete_book(book_id: int, token: str):
    user = get_user(token)
    conn = get_db()
    b = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not b:
        conn.close()
        raise HTTPException(404)
    if b["user_id"] != user["id"] and not is_admin(user):
        conn.close()
        raise HTTPException(403)
    conn.execute("DELETE FROM comments WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM likes WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM bookmarks WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM books WHERE id=?", (book_id,))
    conn.commit()
    conn.close()
    return {"message": "Жойылды"}

# ==================== ЛАЙК ====================
@app.post("/api/like/{book_id}")
def like_book(book_id: int, token: str):
    user = get_user(token)
    conn = get_db()
    try:
        conn.execute("INSERT INTO likes (book_id,user_id) VALUES (?,?)", (book_id, user["id"]))
        conn.execute("UPDATE books SET likes=likes+1 WHERE id=?", (book_id,))
        conn.commit()
        return {"liked": True}
    except:
        conn.execute("DELETE FROM likes WHERE book_id=? AND user_id=?", (book_id, user["id"]))
        conn.execute("UPDATE books SET likes=likes-1 WHERE id=?", (book_id,))
        conn.commit()
        return {"liked": False}
    finally:
        conn.close()

@app.get("/api/liked")
def get_liked(token: str):
    user = get_user(token)
    conn = get_db()
    rows = conn.execute("SELECT book_id FROM likes WHERE user_id=?", (user["id"],)).fetchall()
    conn.close()
    return [r["book_id"] for r in rows]

# ==================== ПІКІР ====================
@app.post("/api/comments")
def add_comment(data: CommentCreate, token: str):
    user = get_user(token)
    conn = get_db()
    conn.execute("INSERT INTO comments (book_id,user_id,text) VALUES (?,?,?)",
                 (data.book_id, user["id"], data.text))
    conn.commit()
    conn.close()
    return {"message": "Пікір қосылды 💬"}

@app.delete("/api/comments/{comment_id}")
def delete_comment(comment_id: int, token: str):
    user = get_user(token)
    conn = get_db()
    c = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
    if not c:
        conn.close()
        raise HTTPException(404)
    if c["user_id"] != user["id"] and not is_admin(user):
        conn.close()
        raise HTTPException(403)
    conn.execute("DELETE FROM comments WHERE id=?", (comment_id,))
    conn.commit()
    conn.close()
    return {"message": "Жойылды"}

# ==================== БЕТБЕЛГІ ====================
@app.post("/api/bookmark/{book_id}")
def set_bookmark(book_id: int, page: int, token: str):
    user = get_user(token)
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO bookmarks (book_id,user_id,page) VALUES (?,?,?)",
                 (book_id, user["id"], page))
    conn.commit()
    conn.close()
    return {"message": "🔖 Сақталды"}

@app.get("/api/bookmark/{book_id}")
def get_bookmark(book_id: int, token: str):
    user = get_user(token)
    conn = get_db()
    row = conn.execute("SELECT page FROM bookmarks WHERE book_id=? AND user_id=?",
                       (book_id, user["id"])).fetchone()
    conn.close()
    return {"page": row["page"] if row else 1}

# ==================== ЖАНРЛАР ====================
@app.get("/api/genres")
def get_genres():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT genre FROM books WHERE hidden=0").fetchall()
    conn.close()
    return [r["genre"] for r in rows]

# ==================== АДМИН ====================
@app.get("/api/admin/stats")
def admin_stats(token: str):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    return {
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "books": conn.execute("SELECT COUNT(*) FROM books").fetchone()[0],
        "comments": conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0],
        "likes": conn.execute("SELECT SUM(likes) FROM books").fetchone()[0] or 0,
        "views": conn.execute("SELECT SUM(views) FROM books").fetchone()[0] or 0,
    }

@app.get("/api/admin/users")
def admin_users(token: str):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close()
    return [dict(u) for u in users]

@app.post("/api/admin/users/{uid}/ban")
def admin_ban(uid: int, token: str):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        conn.close()
        raise HTTPException(404)
    new = 1 if u["banned"] == 0 else 0
    conn.execute("UPDATE users SET banned=? WHERE id=?", (new, uid))
    conn.commit()
    conn.close()
    return {"banned": new}

@app.delete("/api/admin/users/{uid}")
def admin_delete_user(uid: int, token: str):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    conn.execute("DELETE FROM comments WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM likes WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM bookmarks WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM books WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=? AND role!='admin'", (uid,))
    conn.commit()
    conn.close()
    return {"message": "Жойылды"}

@app.get("/api/admin/books")
def admin_books(token: str, search: str = ""):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    q = "SELECT b.*, u.username FROM books b JOIN users u ON b.user_id=u.id"
    if search:
        q += " WHERE b.title LIKE ?"
        books = conn.execute(q, (f"%{search}%",)).fetchall()
    else:
        books = conn.execute(q).fetchall()
    conn.close()
    return [{
        "id": b["id"], "title": b["title"], "username": b["username"],
        "hidden": b["hidden"], "likes": b["likes"], "views": b["views"]
    } for b in books]

@app.post("/api/admin/books/{bid}/toggle")
def admin_toggle_book(bid: int, token: str):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    b = conn.execute("SELECT hidden FROM books WHERE id=?", (bid,)).fetchone()
    if not b:
        conn.close()
        raise HTTPException(404)
    new = 1 if b["hidden"] == 0 else 0
    conn.execute("UPDATE books SET hidden=? WHERE id=?", (new, bid))
    conn.commit()
    conn.close()
    return {"hidden": new}

@app.get("/api/admin/comments")
def admin_comments(token: str):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    rows = conn.execute("""
        SELECT c.*, u.username, b.title as book_title 
        FROM comments c JOIN users u ON c.user_id=u.id 
        JOIN books b ON c.book_id=b.id ORDER BY c.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/admin/comments/{cid}/toggle")
def admin_toggle_comment(cid: int, token: str):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    c = conn.execute("SELECT hidden FROM comments WHERE id=?", (cid,)).fetchone()
    if not c:
        conn.close()
        raise HTTPException(404)
    new = 1 if c["hidden"] == 0 else 0
    conn.execute("UPDATE comments SET hidden=? WHERE id=?", (new, cid))
    conn.commit()
    conn.close()
    return {"hidden": new}

@app.delete("/api/admin/comments/{cid}")
def admin_delete_comment(cid: int, token: str):
    user = get_user(token)
    if not is_admin(user):
        raise HTTPException(403)
    conn = get_db()
    conn.execute("DELETE FROM comments WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return {"message": "Жойылды"}

# ==================== FRONTEND ====================
os.makedirs("static", exist_ok=True)

@app.get("/")
def index():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    print("🍂 Күміс жапырақ · API іске қосылды")
    print("   Админ: admin / admin123")
    uvicorn.run(app, host="0.0.0.0", port=8000)
