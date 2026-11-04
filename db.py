import os
import sqlite3
from contextlib import contextmanager


# Путь к БД считается от папки с кодом, а не от текущей папки запуска
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "barbershops.db")


@contextmanager
def get_conn():
    """Соединение с БД: commit при успехе, rollback при ошибке, всегда close."""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return column in [row[1] for row in cursor.fetchall()]


def create_tables():
    with get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS barbershops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                city TEXT NOT NULL,
                address TEXT NOT NULL,
                phone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                telegram_id INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barbershop_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                FOREIGN KEY (barbershop_id) REFERENCES barbershops(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER NOT NULL,
                client_telegram_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                appointment_date TEXT,
                FOREIGN KEY (service_id) REFERENCES services(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS working_hours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barbershop_id INTEGER NOT NULL,
                day_of_week INTEGER NOT NULL,
                start_time TEXT,
                end_time TEXT,
                is_day_off INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (barbershop_id) REFERENCES barbershops(id)
            )
        """)

        # Миграции для баз, созданных старой версией кода
        if not _column_exists(cursor, "barbershops", "telegram_id"):
            cursor.execute(
                "ALTER TABLE barbershops ADD COLUMN telegram_id INTEGER"
            )

        if not _column_exists(cursor, "appointments", "appointment_date"):
            cursor.execute(
                "ALTER TABLE appointments ADD COLUMN appointment_date TEXT"
            )

        # Защита от дубля: один клиент, одна услуга, одна дата
        # (старые записи с NULL-датой индекс не затрагивает)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique
            ON appointments (service_id, client_telegram_id, appointment_date)
        """)


# ---------- Регистрация парикмахерской ----------

def register_barbershop(name, city, address, phone, telegram_id,
                        services, working_days, start_time, end_time):
    """
    Сохраняет парикмахерскую, услуги и график ОДНОЙ транзакцией.
    services: список (название, цена); working_days: список чисел 1..7.
    Статус всегда 'pending' — одобряется вручную.
    """
    with get_conn() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO barbershops (name, city, address, phone, status, telegram_id)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (name, city, address, phone, telegram_id))

        barbershop_id = cursor.lastrowid

        cursor.executemany("""
            INSERT INTO services (barbershop_id, name, price)
            VALUES (?, ?, ?)
        """, [(barbershop_id, n, p) for n, p in services])

        cursor.executemany("""
            INSERT INTO working_hours (
                barbershop_id, day_of_week, start_time, end_time, is_day_off
            )
            VALUES (?, ?, ?, ?, 0)
        """, [(barbershop_id, d, start_time, end_time) for d in working_days])

    return barbershop_id


# ---------- Чтение (для клиентов) ----------

def get_approved_barbershops(city):
    with get_conn() as conn:
        return conn.execute("""
            SELECT id, name
            FROM barbershops
            WHERE city = ? AND status = 'approved'
        """, (city,)).fetchall()


def get_barbershop(barbershop_id):
    """Только одобренная парикмахерская."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT id, name, city, address, phone
            FROM barbershops
            WHERE id = ? AND status = 'approved'
        """, (barbershop_id,)).fetchone()


def get_services(barbershop_id):
    """Список (id, name, price)."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT id, name, price
            FROM services
            WHERE barbershop_id = ?
        """, (barbershop_id,)).fetchall()


def get_service(service_id):
    """(id, barbershop_id, name, price) — только если парикмахерская одобрена."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT s.id, s.barbershop_id, s.name, s.price
            FROM services s
            JOIN barbershops b ON b.id = s.barbershop_id
            WHERE s.id = ? AND b.status = 'approved'
        """, (service_id,)).fetchone()


def get_barbershop_telegram_id(barbershop_id):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT telegram_id
            FROM barbershops
            WHERE id = ?
        """, (barbershop_id,)).fetchone()

    return row[0] if row else None


def get_working_hours(barbershop_id, day_of_week):
    """(start_time, end_time) или None, если в этот день не работает."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT start_time, end_time
            FROM working_hours
            WHERE barbershop_id = ? AND day_of_week = ? AND is_day_off = 0
            LIMIT 1
        """, (barbershop_id, day_of_week)).fetchone()


# ---------- Записи ----------

def create_appointment(service_id, client_telegram_id, appointment_date):
    """
    appointment_date — строка 'YYYY-MM-DD'.
    Возвращает False, если такая запись у клиента уже есть.
    """
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO appointments (service_id, client_telegram_id, appointment_date)
                VALUES (?, ?, ?)
            """, (service_id, client_telegram_id, appointment_date))
    except sqlite3.IntegrityError:
        return False

    return True


# ---------- Проверка администратором ----------

def get_barbershop_for_review(barbershop_id):
    """
    Все данные парикмахерской для карточки администратора (любой статус).
    Возвращает словарь или None.
    """
    with get_conn() as conn:
        row = conn.execute("""
            SELECT id, name, city, address, phone, status, telegram_id
            FROM barbershops
            WHERE id = ?
        """, (barbershop_id,)).fetchone()

        if row is None:
            return None

        services = conn.execute("""
            SELECT name, price FROM services WHERE barbershop_id = ?
        """, (barbershop_id,)).fetchall()

        hours = conn.execute("""
            SELECT day_of_week, start_time, end_time
            FROM working_hours
            WHERE barbershop_id = ? AND is_day_off = 0
            ORDER BY day_of_week
        """, (barbershop_id,)).fetchall()

    return {
        "id": row[0],
        "name": row[1],
        "city": row[2],
        "address": row[3],
        "phone": row[4],
        "status": row[5],
        "telegram_id": row[6],
        "services": services,
        "days": [h[0] for h in hours],
        "start_time": hours[0][1] if hours else None,
        "end_time": hours[0][2] if hours else None,
    }


def count_pending_by_owner(telegram_id):
    """Сколько заявок владельца сейчас ждут проверки."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT COUNT(*) FROM barbershops
            WHERE telegram_id = ? AND status = 'pending'
        """, (telegram_id,)).fetchone()[0]


def get_pending_barbershop_ids():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id FROM barbershops WHERE status = 'pending' ORDER BY id
        """).fetchall()

    return [r[0] for r in rows]


def set_barbershop_status(barbershop_id, new_status):
    """
    Меняет статус только у заявки в статусе 'pending'
    (повторное нажатие кнопки ничего не ломает).
    Возвращает True, если статус изменён.
    """
    with get_conn() as conn:
        cursor = conn.execute("""
            UPDATE barbershops
            SET status = ?
            WHERE id = ? AND status = 'pending'
        """, (new_status, barbershop_id))

        return cursor.rowcount > 0
