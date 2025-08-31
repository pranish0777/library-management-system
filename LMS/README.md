📚 Library Management System

A Tkinter + SQLite based Library Management System with user authentication, book management, borrowing system, and admin control.

Admins can:

Manage books (add, update, delete, search).

View borrowed books.

Manage users (view all, delete users safely).

Users can:

Log in and borrow books.

View their borrowed books.

🚀 Features
🔑 Authentication

Secure login with username & password.

Role-based system: Admin or User.

👨‍💻 Admin Features

Add, update, delete books.

Search books by title, author, category.

View borrowed records.

Manage users:

View all users.

Delete users (with safety check to prevent removing last admin).

🙋 User Features

Search available books.

Borrow books (with date recorded).

View borrowed books.

⚙️ Installation
1. Clone Repository
git clone https://github.com/laxmirimal/Python_assignment.git
cd library-management

2. Install Dependencies

Make sure you have Python 3.8+ installed.
Install required packages:

pip install -r requirements.txt


requirements.txt

tk

▶️ Run the App
python library.py

🗄️ Database

SQLite database file: library.db (auto-created).

Tables:

users(user_id, username, password, role)

books(book_id, title, author, category, available)

borrowed(borrow_id, user_id, book_id, borrow_date)

👤 Default Admin

On first run, a default admin account is created:

Username: admin
Password: admin


(You should change the password after first login!)

📌 Usage

Login as admin → Manage books & users.

Login as user → Borrow & view books.

🛠️ Future Improvements

Password hashing for better security.

Fine/return system for borrowed books.

Export borrowed records to Excel/PDF.

Dark mode UI.

📄 License

© 2025 Pranish Pudasaini. All rights reserved.
