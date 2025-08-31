# -*- coding: utf-8 -*-
import sqlite3
import hashlib
import json
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

# ---------------------------------
# Config
# ---------------------------------
DB_PATH = "library.db"
CATALOG_JSON = "bookdetails.json"  # JSON catalog for autofill

DEFAULT_LOAN_DAYS = 14

# ---------------------------------
# Utilities
# ---------------------------------
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_conn():
    return sqlite3.connect(DB_PATH)

# ---------------------------------
# Database init and helpers
# ---------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT CHECK(role IN ('admin','user')) NOT NULL DEFAULT 'user'
        )
    """)

    # Books inventory (DB authoritative for stock/borrowing)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS books (
            book_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT,
            year INTEGER,
            qty_total INTEGER NOT NULL DEFAULT 1,
            qty_available INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Borrow records
    cur.execute("""
        CREATE TABLE IF NOT EXISTS borrowed (
            borrow_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            borrow_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            return_date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(book_id) REFERENCES books(book_id)
        )
    """)

    conn.commit()

    # Seed default admin if none exists
    cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?,?,?)",
            ("admin", hash_password("admin123"), "admin")
        )
        conn.commit()

    conn.close()

# ---------------------------------
# Auth
# ---------------------------------
def register_user(username, password, role="user"):
    if not username or not password:
        return False, "Username and password required"
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                (username, hash_password(password), role)
            )
            conn.commit()
        return True, "User registered"
    except sqlite3.IntegrityError:
        return False, "Username already exists"

def login_user(username, password):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, role, password_hash FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        if row and row[3] == hash_password(password):
            return True, {"user_id": row[0], "username": row[1], "role": row[2]}
        return False, "Invalid username or password"

# ---------------------------------
# Users (Admin management)
# ---------------------------------
def list_all_users_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, role FROM users ORDER BY username ASC")
        return cur.fetchall()

def delete_user_db(user_id_to_delete, requester_user_id=None):
    """
    Delete a user with safety checks:
      - Cannot delete last remaining admin.
      - Cannot delete if user has active (unreturned) borrows.
      - (UI prevents self-delete; we keep an extra guard just in case.)
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # Ensure target exists
        cur.execute("SELECT user_id, role FROM users WHERE user_id=?", (user_id_to_delete,))
        target = cur.fetchone()
        if not target:
            return False, "User not found"

        target_role = target[1]

        # Prevent deleting yourself (defensive)
        if requester_user_id is not None and int(user_id_to_delete) == int(requester_user_id):
            return False, "You cannot delete your own account while logged in."

        # Check active borrows
        cur.execute("""SELECT COUNT(*) FROM borrowed
                       WHERE user_id=? AND return_date IS NULL""", (user_id_to_delete,))
        active = cur.fetchone()[0]
        if active > 0:
            return False, "Cannot delete: user has active (unreturned) borrowed books"

        # Prevent deleting last admin
        if target_role == "admin":
            cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
            admin_count = cur.fetchone()[0]
            if admin_count <= 1:
                return False, "Cannot delete the last remaining admin"

        # Safe to delete
        cur.execute("DELETE FROM users WHERE user_id=?", (user_id_to_delete,))
        conn.commit()
        return True, "User deleted successfully"

# ---------------------------------
# Books (DB inventory ops)
# ---------------------------------
def add_book(title, author, isbn, year, qty):
    if not title or not author or qty is None:
        return False, "Title, author and quantity required"

    try:
        year_val = int(year) if str(year).strip() else None
    except ValueError:
        return False, "Year must be a number"

    try:
        qty_val = int(qty)
        if qty_val <= 0:
            raise ValueError
    except Exception:
        return False, "Quantity must be a positive integer"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO books (title, author, isbn, year, qty_total, qty_available)
               VALUES (?,?,?,?,?,?)""",
            (title.strip(), author.strip(), (isbn or "").strip(),
             year_val, qty_val, qty_val)
        )
        conn.commit()
    return True, "Book added"

def update_book(book_id, title, author, isbn, year, qty_total, qty_available):
    try:
        year_val = int(year) if str(year).strip() else None
        qt = int(qty_total)
        qa = int(qty_available)
        if qt < 0 or qa < 0 or qa > qt:
            return False, "Quantities invalid (available <= total, non-negative)"
    except Exception:
        return False, "Invalid numeric input"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE books
               SET title=?, author=?, isbn=?, year=?, qty_total=?, qty_available=?
               WHERE book_id=?""",
            (title.strip(), author.strip(), (isbn or "").strip(),
             year_val, qt, qa, book_id)
        )
        conn.commit()
    return True, "Book updated"

def delete_book(book_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT COUNT(*) FROM borrowed
                       WHERE book_id=? AND return_date IS NULL""", (book_id,))
        if cur.fetchone()[0] > 0:
            return False, "Cannot delete: book currently borrowed"
        cur.execute("DELETE FROM books WHERE book_id=?", (book_id,))
        conn.commit()
    return True, "Book deleted"

def search_books_db(keyword):
    kw = f"%{keyword.strip()}%"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT book_id, title, author, isbn, year, qty_total, qty_available
                       FROM books
                       WHERE title LIKE ? OR author LIKE ? OR IFNULL(isbn,'') LIKE ?
                       ORDER BY title ASC""", (kw, kw, kw))
        return cur.fetchall()

def list_all_books_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT book_id, title, author, isbn, year, qty_total, qty_available
                       FROM books ORDER BY title ASC""")
        return cur.fetchall()

# ---------------------------------
# Borrow/Return (DB)
# ---------------------------------
def borrow_book(user_id, book_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT qty_available FROM books WHERE book_id=?", (book_id,))
        row = cur.fetchone()
        if not row:
            return False, "Book not found"
        if row[0] <= 0:
            return False, "No copies available"

        borrow_date = datetime.now()
        due_date = borrow_date + timedelta(days=DEFAULT_LOAN_DAYS)
        cur.execute(
            """INSERT INTO borrowed (user_id, book_id, borrow_date, due_date, return_date)
               VALUES (?,?,?,?,NULL)""",
            (user_id,
             book_id,
             borrow_date.strftime("%Y-%m-%d %H:%M:%S"),
             due_date.strftime("%Y-%m-%d %H:%M:%S"))
        )
        cur.execute("""UPDATE books SET qty_available = qty_available - 1 WHERE book_id=?""", (book_id,))
        conn.commit()
    return True, "Borrowed successfully"

def return_book(borrow_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT book_id, return_date FROM borrowed WHERE borrow_id=?""", (borrow_id,))
        row = cur.fetchone()
        if not row:
            return False, "Borrow record not found"
        if row[1] is not None:
            return False, "Already returned"
        book_id = row[0]
        cur.execute("""UPDATE borrowed SET return_date=? WHERE borrow_id=?""", (now_iso(), borrow_id))
        cur.execute("""UPDATE books SET qty_available = qty_available + 1 WHERE book_id=?""", (book_id,))
        conn.commit()
    return True, "Returned successfully"

def list_borrowed_all():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT b.borrow_id, u.username, bo.title, b.borrow_date, b.due_date, b.return_date
            FROM borrowed b
            JOIN users u ON b.user_id = u.user_id
            JOIN books bo ON b.book_id = bo.book_id
            ORDER BY b.borrow_date DESC
        """)
        return cur.fetchall()

def list_borrowed_by_user(user_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT b.borrow_id, bo.title, b.borrow_date, b.due_date, b.return_date
            FROM borrowed b
            JOIN books bo ON b.book_id = bo.book_id
            WHERE b.user_id=?
            ORDER BY b.borrow_date DESC
        """, (user_id,))
        return cur.fetchall()

# ---------------------------------
# JSON catalog (for autofill only)
# ---------------------------------
def load_catalog():
    try:
        with open(CATALOG_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Normalize keys & types
            norm = []
            for b in data:
                norm.append({
                    "title": str(b.get("title", "")).strip(),
                    "author": str(b.get("author", "")).strip(),
                    "isbn": str(b.get("isbn", "")).strip(),
                    "year": int(b["year"]) if str(b.get("year", "")).strip().isdigit() else None
                })
            return norm
    except FileNotFoundError:
        return []
    except Exception as e:
        messagebox.showerror("Catalog Error", f"Failed to read {CATALOG_JSON}\n{e}")
        return []

def search_catalog(keyword):
    kw = (keyword or "").strip().lower()
    books = load_catalog()
    if not kw:
        return books
    # startswith OR contains (prioritize startswith by ordering)
    starts = [b for b in books if b["title"].lower().startswith(kw)]
    contains = [b for b in books if kw in b["title"].lower() and b not in starts]
    return starts + contains

# ---------------------------------
# Styles & animation
# ---------------------------------
def apply_styles(win):
    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Window background
    win.configure(bg="#141725")

    # General
    style.configure("TFrame", background="#3F5AD0")
    style.configure("TLabel", background="#3751C5", foreground="#E6E9F5", font=("Segoe UI", 11))
    style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
    style.configure("SubHeader.TLabel", font=("Segoe UI", 12, "bold"), foreground="#B6C1FF")

    # Buttons
    style.configure("TButton",
                    background="#C3C7E1",
                    foreground="#FFFFFF",
                    padding=8,
                    font=("Segoe UI", 10, "bold"),
                    relief="flat")
    style.map("TButton",
              background=[("active", "#3B4163")],
              relief=[("pressed", "sunken")])

    # Entry & Combobox
    style.configure("TEntry", fieldbackground="#1C2033", foreground="#FFFFFF")
    style.configure("TCombobox", fieldbackground="#1C2033", foreground="#FFFFFF")

    # Treeview
    style.configure("Treeview",
                    background="#1C2033",
                    foreground="#E6E9F5",
                    fieldbackground="#1C2033",
                    rowheight=26,
                    borderwidth=0)
    style.map("Treeview",
              background=[("selected", "#3B4163")],
              foreground=[("selected", "#FFFFFF")])
    style.configure("Treeview.Heading",
                    background="#232845",
                    foreground="#E6E9F5",
                    font=("Segoe UI", 10, "bold"))

def fade_in(win, alpha=0.0):
    if alpha < 1.0:
        try:
            win.attributes("-alpha", alpha)
            win.after(18, lambda: fade_in(win, alpha + 0.06))
        except tk.TclError:
            pass
    else:
        try:
            win.attributes("-alpha", 1.0)
        except tk.TclError:
            pass

# ---------------------------------
# GUI
# ---------------------------------
class LoginWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Library Management System - Login")
        self.geometry("460x280")
        self.resizable(False, False)
        apply_styles(self)
        fade_in(self)

        ttk.Label(self, text="📚 ------Library Management System-------📚", style="Header.TLabel").pack(pady=14)

        frm = ttk.Frame(self); frm.pack(pady=6, padx=20, fill="x")

        ttk.Label(frm, text="Username").grid(row=0, column=0, sticky="w", pady=6)
        self.entry_user = ttk.Entry(frm); self.entry_user.grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Password").grid(row=1, column=0, sticky="w", pady=6)
        self.entry_pass = ttk.Entry(frm, show="*"); self.entry_pass.grid(row=1, column=1, sticky="ew", pady=6)

        frm.columnconfigure(1, weight=1)

        btns = ttk.Frame(self); btns.pack(pady=12)
        ttk.Button(btns, text="Login", command=self.do_login).grid(row=0, column=0, padx=6)
        ttk.Button(btns, text="Register", command=self.open_register).grid(row=0, column=1, padx=6)

        self.bind("<Return>", lambda e: self.do_login())

    def do_login(self):
        u = self.entry_user.get().strip()
        p = self.entry_pass.get().strip()
        ok, data = login_user(u, p)
        if ok:
            self.destroy()
            if data["role"] == "admin":
                AdminWindow(data).mainloop()
            else:
                UserWindow(data).mainloop()
        else:
            messagebox.showerror("Login Failed", data)

    def open_register(self):
        RegisterWindow(self).grab_set()

class RegisterWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Register User")
        self.geometry("390x240")
        self.resizable(False, False)
        apply_styles(self)
        fade_in(self)

        frm = ttk.Frame(self); frm.pack(padx=20, pady=18, fill="x")
        ttk.Label(frm, text="Create an account", style="SubHeader.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,10))

        ttk.Label(frm, text="Username").grid(row=1, column=0, sticky="w", pady=6)
        self.u = ttk.Entry(frm); self.u.grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Password").grid(row=2, column=0, sticky="w", pady=6)
        self.p = ttk.Entry(frm, show="*"); self.p.grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(frm, text="Role").grid(row=3, column=0, sticky="w", pady=6)
        self.role = ttk.Combobox(frm, values=["user"], state="readonly") # first registering a admin,and then removing the admin role option.
        self.role.current(0)
        self.role.grid(row=3, column=1, sticky="ew", pady=6)

        frm.columnconfigure(1, weight=1)

        ttk.Button(self, text="Create Account", command=self.do_register).pack(pady=10)

    def do_register(self):
        ok, msg = register_user(self.u.get().strip(), self.p.get().strip(), self.role.get())
        if ok:
            messagebox.showinfo("Success", msg)
            self.destroy()
        else:
            messagebox.showerror("Error", msg)

# ----------------- Admin -----------------
class AdminWindow(tk.Tk):
    def __init__(self, user_info):
        super().__init__()
        self.user_info = user_info
        self.title(f"Admin Dashboard - {user_info['username']}")
        self.geometry("1200x720")
        apply_styles(self)
        fade_in(self)

        # Top bar
        topbar = ttk.Frame(self); topbar.pack(fill="x", pady=6, padx=10)
        ttk.Label(topbar, text=f"Welcome, {user_info['username']} (Admin)", style="SubHeader.TLabel").pack(side="left")
        ttk.Button(topbar, text="Logout", command=self.logout).pack(side="right")

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.books_tab = ttk.Frame(nb)
        self.borrowed_tab = ttk.Frame(nb)
        self.users_tab = ttk.Frame(nb)  # NEW TAB

        nb.add(self.books_tab, text="Manage Books")
        nb.add(self.borrowed_tab, text="Borrowed Records")
        nb.add(self.users_tab, text="Manage Users")  # NEW TAB

        self._build_books_tab()
        self._build_borrowed_tab()
        self._build_users_tab()  # NEW

    def logout(self):
        self.destroy()
        LoginWindow().mainloop()

    # --------- Manage Books Tab ---------
    def _build_books_tab(self):
        container = ttk.Frame(self.books_tab)
        container.pack(fill="both", expand=True, padx=6, pady=6)
        container.columnconfigure(0, weight=5)
        container.columnconfigure(1, weight=4)
        container.rowconfigure(2, weight=1)

        # Form (left - top)
        form = ttk.LabelFrame(container, text="Book Details (DB Inventory)")
        form.grid(row=0, column=0, sticky="nsew", padx=(0,6), pady=(0,6))

        self.vars = {k: tk.StringVar() for k in ["Title","Author","ISBN","Year","Total","Avail"]}

        def add_row(r, label, var):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=6)
            ttk.Entry(form, textvariable=var).grid(row=r, column=1, sticky="ew", padx=6, pady=6)

        add_row(0, "Title", self.vars["Title"])
        add_row(1, "Author", self.vars["Author"])
        add_row(2, "ISBN", self.vars["ISBN"])
        add_row(3, "Year", self.vars["Year"])
        add_row(4, "Total Qty", self.vars["Total"])
        add_row(5, "Available", self.vars["Avail"])
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(container); btns.grid(row=1, column=0, sticky="ew", padx=(0,6), pady=6)
        ttk.Button(btns, text="Add New", command=self.add_new_book).pack(side="left", padx=4)
        ttk.Button(btns, text="Update Selected", command=self.update_selected_book).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete Selected", command=self.delete_selected_book).pack(side="left", padx=4)

        # DB search/list (left - bottom)
        search_frame = ttk.Frame(container); search_frame.grid(row=2, column=0, sticky="nsew", padx=(0,6), pady=(6,0))
        ttk.Label(search_frame, text="Search in DB").pack(side="left", padx=(0,6))
        self.search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self.search_var).pack(side="left", fill="x", expand=True)
        ttk.Button(search_frame, text="Go", command=self.refresh_books).pack(side="left", padx=6)
        ttk.Button(search_frame, text="Show All", command=self.load_all_books).pack(side="left")

        cols = ("book_id","title","author","isbn","year","qty_total","qty_available")
        self.tree = ttk.Treeview(self.books_tab, columns=cols, show="headings", height=14)
        # place under the grid area using pack (simple) but full width:
        self.tree.pack(fill="both", expand=True, padx=6, pady=(0,6))
        for c in cols:
            self.tree.heading(c, text=c.title().replace("_"," "))
            self.tree.column(c, anchor="w", stretch=True, width=120)
        self.tree.column("book_id", width=80, anchor="center")
        self.tree.bind("<<TreeviewSelect>>", self.on_select_book)

        # Catalog lookup (right side)
        catalog = ttk.LabelFrame(container, text=f"Catalog Lookup (JSON: {CATALOG_JSON})")
        catalog.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(6,0), pady=(0,0))
        catalog.rowconfigure(2, weight=1)
        catalog.columnconfigure(0, weight=1)

        ttk.Label(catalog, text="Type letter/word to find titles").grid(row=0, column=0, sticky="w", padx=8, pady=(8,4))
        self.catalog_kw = tk.StringVar()
        entry = ttk.Entry(catalog, textvariable=self.catalog_kw)
        entry.grid(row=1, column=0, sticky="ew", padx=8, pady=(0,8))
        entry.bind("<KeyRelease>", self.update_catalog_results)

        self.catalog_tree = ttk.Treeview(catalog, columns=("title","author","isbn","year"), show="headings", height=12)
        for col in ("title","author","isbn","year"):
            self.catalog_tree.heading(col, text=col.title())
            self.catalog_tree.column(col, width=140, anchor="w", stretch=True)
        self.catalog_tree.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0,8))
        self.catalog_tree.bind("<<TreeviewSelect>>", self.catalog_select_fill)

        hint = ttk.Label(catalog, text="Select a row to auto-fill the form on the left.\nQuantities are not in JSON.", foreground="#AAB2E8")
        hint.grid(row=3, column=0, sticky="we", padx=8, pady=(0,10))

        # initial loads
        self.load_all_books()
        self.update_catalog_results()

    def _build_borrowed_tab(self):
        cols = ("borrow_id","username","title","borrow_date","due_date","return_date")
        self.borrow_tree = ttk.Treeview(self.borrowed_tab, columns=cols, show="headings", height=16)
        for c in cols:
            self.borrow_tree.heading(c, text=c.title().replace("_"," "))
            self.borrow_tree.column(c, anchor="w", stretch=True, width=160)
        self.borrow_tree.column("borrow_id", width=90, anchor="center")
        self.borrow_tree.pack(fill="both", expand=True, padx=8, pady=8)

        ttk.Button(self.borrowed_tab, text="Refresh", command=self.load_borrowed_all).pack(pady=(0,8))
        self.load_borrowed_all()

    # ---------- Manage Users Tab (NEW) ----------
    def _build_users_tab(self):
        wrapper = ttk.Frame(self.users_tab)
        wrapper.pack(fill="both", expand=True, padx=8, pady=8)

        cols = ("user_id","username","role")
        self.users_tree = ttk.Treeview(wrapper, columns=cols, show="headings", height=18)
        for c in cols:
            self.users_tree.heading(c, text=c.title().replace("_"," "))
            self.users_tree.column(c, anchor="w", stretch=True, width=200)
        self.users_tree.column("user_id", width=90, anchor="center")
        self.users_tree.pack(fill="both", expand=True, padx=4, pady=4)

        btns = ttk.Frame(self.users_tab); btns.pack(pady=(2,10))
        ttk.Button(btns, text="Refresh", command=self.load_users_all).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete Selected User", command=self.delete_selected_user).pack(side="left", padx=4)

        self.load_users_all()

    # ---- Admin helpers / actions ----
    def load_borrowed_all(self):
        for i in self.borrow_tree.get_children():
            self.borrow_tree.delete(i)
        rows = list_borrowed_all()
        for r in rows:
            self.borrow_tree.insert("", "end", values=r)

    def load_all_books(self):
        self.search_var.set("")
        self._populate_books(list_all_books_db())

    def refresh_books(self):
        kw = self.search_var.get().strip()
        rows = search_books_db(kw) if kw else list_all_books_db()
        self._populate_books(rows)

    def _populate_books(self, rows):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in rows:
            self.tree.insert("", "end", values=r)

    def on_select_book(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        self.vars["Title"].set(vals[1])
        self.vars["Author"].set(vals[2])
        self.vars["ISBN"].set(vals[3])
        self.vars["Year"].set("" if vals[4] is None else vals[4])
        self.vars["Total"].set(vals[5])
        self.vars["Avail"].set(vals[6])

    def _get_selected_book_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(self.tree.item(sel[0], "values")[0])

    def add_new_book(self):
        ok, msg = add_book(
            self.vars["Title"].get(),
            self.vars["Author"].get(),
            self.vars["ISBN"].get(),
            self.vars["Year"].get(),
            self.vars["Total"].get()
        )
        if ok:
            messagebox.showinfo("Success", msg)
            self.load_all_books()
        else:
            messagebox.showerror("Error", msg)

    def update_selected_book(self):
        book_id = self._get_selected_book_id()
        if not book_id:
            messagebox.showwarning("No selection", "Please select a book from the table")
            return
        ok, msg = update_book(
            book_id,
            self.vars["Title"].get(),
            self.vars["Author"].get(),
            self.vars["ISBN"].get(),
            self.vars["Year"].get(),
            self.vars["Total"].get(),
            self.vars["Avail"].get(),
        )
        if ok:
            messagebox.showinfo("Updated", msg)
            self.refresh_books()
        else:
            messagebox.showerror("Error", msg)

    def delete_selected_book(self):
        book_id = self._get_selected_book_id()
        if not book_id:
            messagebox.showwarning("No selection", "Please select a book")
            return
        if messagebox.askyesno("Confirm", "Delete selected book?"):
            ok, msg = delete_book(book_id)
            if ok:
                messagebox.showinfo("Deleted", msg)
                self.refresh_books()
            else:
                messagebox.showerror("Error", msg)

    # ---- Catalog JSON UI ----
    def update_catalog_results(self, event=None):
        kw = self.catalog_kw.get().strip()
        results = search_catalog(kw)
        for i in self.catalog_tree.get_children():
            self.catalog_tree.delete(i)
        for b in results:
            self.catalog_tree.insert("", "end", values=(b["title"], b["author"], b["isbn"], b["year"] if b["year"] else ""))

    def catalog_select_fill(self, event=None):
        sel = self.catalog_tree.selection()
        if not sel:
            return
        vals = self.catalog_tree.item(sel[0], "values")
        # Auto-fill left form fields
        self.vars["Title"].set(vals[0])
        self.vars["Author"].set(vals[1])
        self.vars["ISBN"].set(vals[2])
        self.vars["Year"].set(vals[3])

    # ---- Users tab helpers/actions (NEW) ----
    def load_users_all(self):
        for i in self.users_tree.get_children():
            self.users_tree.delete(i)
        rows = list_all_users_db()
        for r in rows:
            self.users_tree.insert("", "end", values=r)

    def _get_selected_user_id(self):
        sel = self.users_tree.selection()
        if not sel:
            return None
        return int(self.users_tree.item(sel[0], "values")[0])

    def delete_selected_user(self):
        uid = self._get_selected_user_id()
        if not uid:
            messagebox.showwarning("No selection", "Please select a user")
            return
        # Prevent deleting yourself
        if uid == int(self.user_info["user_id"]):
            messagebox.showwarning("Not allowed", "You cannot delete your own account while logged in.")
            return
        # Confirm
        if messagebox.askyesno("Confirm", "Delete selected user?"):
            ok, msg = delete_user_db(uid, requester_user_id=self.user_info["user_id"])
            if ok:
                messagebox.showinfo("Deleted", msg)
                self.load_users_all()
            else:
                messagebox.showerror("Error", msg)

# ----------------- User -----------------
class UserWindow(tk.Tk):
    def __init__(self, user_info):
        super().__init__()
        self.user = user_info
        self.title(f"User Dashboard - {user_info['username']}")
        self.geometry("980x620")
        apply_styles(self)
        fade_in(self)

        topbar = ttk.Frame(self); topbar.pack(fill="x", pady=6, padx=10)
        ttk.Label(topbar, text=f"Welcome, {user_info['username']} (User)", style="SubHeader.TLabel").pack(side="left")
        ttk.Button(topbar, text="Logout", command=self.logout).pack(side="right")

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.search_tab = ttk.Frame(nb)
        self.my_tab = ttk.Frame(nb)
        nb.add(self.search_tab, text="Search & Borrow")
        nb.add(self.my_tab, text="My Borrowed")

        self._build_search_tab()
        self._build_my_tab()

    def logout(self):
        self.destroy()
        LoginWindow().mainloop()

    # Search & Borrow
    def _build_search_tab(self):
        top = ttk.Frame(self.search_tab); top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Search").pack(side="left")
        self.kw = tk.StringVar()
        ttk.Entry(top, textvariable=self.kw).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Go", command=self.refresh_books).pack(side="left", padx=4)
        ttk.Button(top, text="Show All", command=self.load_all_books).pack(side="left")

        cols = ("book_id","title","author","isbn","year","qty_total","qty_available")
        self.tree = ttk.Treeview(self.search_tab, columns=cols, show="headings", height=16)
        for c in cols:
            self.tree.heading(c, text=c.title().replace("_"," "))
            self.tree.column(c, anchor="w", stretch=True, width=140)
        self.tree.column("book_id", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)

        ttk.Button(self.search_tab, text="Borrow Selected", command=self.borrow_selected).pack(pady=(0,8))

        self.load_all_books()

    def _build_my_tab(self):
        cols = ("borrow_id","title","borrow_date","due_date","return_date")
        self.my_tree = ttk.Treeview(self.my_tab, columns=cols, show="headings", height=16)
        for c in cols:
            self.my_tree.heading(c, text=c.title().replace("_"," "))
            self.my_tree.column(c, anchor="w", stretch=True, width=170)
        self.my_tree.column("borrow_id", width=90, anchor="center")
        self.my_tree.pack(fill="both", expand=True, padx=8, pady=8)

        btns = ttk.Frame(self.my_tab); btns.pack(pady=(0,8))
        ttk.Button(btns, text="Refresh", command=self.load_my_borrowed).pack(side="left", padx=4)
        ttk.Button(btns, text="Return Selected", command=self.return_selected).pack(side="left", padx=4)

        self.load_my_borrowed()

    # Helpers
    def _get_selected_book_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(self.tree.item(sel[0], "values")[0])

    def _get_selected_borrow_id(self):
        sel = self.my_tree.selection()
        if not sel:
            return None
        return int(self.my_tree.item(sel[0], "values")[0])

    # Actions
    def load_all_books(self):
        self.kw.set("")
        self._populate_books(list_all_books_db())

    def refresh_books(self):
        kw = self.kw.get().strip()
        rows = search_books_db(kw) if kw else list_all_books_db()
        self._populate_books(rows)

    def _populate_books(self, rows):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in rows:
            self.tree.insert("", "end", values=r)

    def borrow_selected(self):
        book_id = self._get_selected_book_id()
        if not book_id:
            messagebox.showwarning("No selection", "Please select a book")
            return
        ok, msg = borrow_book(self.user["user_id"], book_id)
        if ok:
            messagebox.showinfo("Success", msg)
            self.refresh_books()
            self.load_my_borrowed()
        else:
            messagebox.showerror("Error", msg)

    def load_my_borrowed(self):
        for i in self.my_tree.get_children():
            self.my_tree.delete(i)
        rows = list_borrowed_by_user(self.user["user_id"])
        for r in rows:
            self.my_tree.insert("", "end", values=r)

    def return_selected(self):
        borrow_id = self._get_selected_borrow_id()
        if not borrow_id:
            messagebox.showwarning("No selection", "Please select a borrow record")
            return
        ok, msg = return_book(borrow_id)
        if ok:
            messagebox.showinfo("Returned", msg)
            self.load_my_borrowed()
            self.refresh_books()
        else:
            messagebox.showerror("Error", msg)

# ---------------------------------
# Entrypoint
# ---------------------------------
def main():
    init_db()
    app = LoginWindow()
    app.mainloop()

if __name__ == "__main__":
    main()
#This is the complete code of library management system
#Built with python
#done by : Laxmi Prasad Rimal, Pranish Pudasaini, Laxman Magaranti, Parakh Dhoj
#<<<<<<<<<<<<<<<<----------------Thank you-------------------->>>>>>>>>>>>>>>>> 