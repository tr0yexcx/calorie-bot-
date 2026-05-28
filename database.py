import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "calorie_bot.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                goal_cal    REAL,
                goal_protein REAL,
                goal_fat    REAL,
                goal_carbs  REAL
            );

            CREATE TABLE IF NOT EXISTS custom_products (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                name        TEXT NOT NULL,
                barcode     TEXT,
                calories    REAL NOT NULL,
                protein     REAL NOT NULL,
                fat         REAL NOT NULL,
                carbs       REAL NOT NULL,
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS dishes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                name        TEXT NOT NULL,
                calories    REAL NOT NULL,
                protein     REAL NOT NULL,
                fat         REAL NOT NULL,
                carbs       REAL NOT NULL,
                total_grams REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dish_ingredients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                dish_id     INTEGER NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
                product_name TEXT NOT NULL,
                grams       REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS diary (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                logged_at   TEXT NOT NULL,
                description TEXT NOT NULL,
                grams       REAL NOT NULL,
                calories    REAL NOT NULL,
                protein     REAL NOT NULL,
                fat         REAL NOT NULL,
                carbs       REAL NOT NULL
            );
        """)


# ── Users ──────────────────────────────────────────────────────────────────────

def ensure_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,)
        )


def set_goal(user_id: int, cal: float, protein: float, fat: float, carbs: float) -> None:
    ensure_user(user_id)
    with get_conn() as conn:
        conn.execute(
            """UPDATE users
               SET goal_cal=?, goal_protein=?, goal_fat=?, goal_carbs=?
               WHERE user_id=?""",
            (cal, protein, fat, carbs, user_id),
        )


def get_goal(user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT goal_cal, goal_protein, goal_fat, goal_carbs FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()


# ── Custom Products ────────────────────────────────────────────────────────────

def save_custom_product(
    user_id: int, name: str, calories: float, protein: float,
    fat: float, carbs: float, barcode: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO custom_products(user_id, name, barcode, calories, protein, fat, carbs)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id, name) DO UPDATE
               SET barcode=excluded.barcode, calories=excluded.calories,
                   protein=excluded.protein, fat=excluded.fat, carbs=excluded.carbs""",
            (user_id, name.lower(), barcode, calories, protein, fat, carbs),
        )


def find_custom_products(
    user_id: int, query: str
) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT name, calories, protein, fat, carbs
               FROM custom_products
               WHERE user_id=? AND name LIKE ?""",
            (user_id, f"%{query.lower()}%"),
        ).fetchall()


def get_custom_product_by_barcode(user_id: int, barcode: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM custom_products WHERE user_id=? AND barcode=?",
            (user_id, barcode),
        ).fetchone()


# ── Dishes ─────────────────────────────────────────────────────────────────────

def save_dish(
    user_id: int, name: str, calories: float, protein: float,
    fat: float, carbs: float, total_grams: float,
    ingredients: list[tuple[str, float]],
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO dishes(user_id, name, calories, protein, fat, carbs, total_grams)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, name, calories, protein, fat, carbs, total_grams),
        )
        dish_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO dish_ingredients(dish_id, product_name, grams) VALUES (?,?,?)",
            [(dish_id, ing_name, grams) for ing_name, grams in ingredients],
        )
        return dish_id


def get_user_dishes(user_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM dishes WHERE user_id=? ORDER BY name",
            (user_id,),
        ).fetchall()


def get_dish(dish_id: int, user_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM dishes WHERE id=? AND user_id=?", (dish_id, user_id)
        ).fetchone()


def get_dish_ingredients(dish_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT product_name, grams FROM dish_ingredients WHERE dish_id=?",
            (dish_id,),
        ).fetchall()


def delete_dish(dish_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM dishes WHERE id=? AND user_id=?", (dish_id, user_id)
        )
        return cur.rowcount > 0


# ── Diary ──────────────────────────────────────────────────────────────────────

def log_entry(
    user_id: int, description: str, grams: float,
    calories: float, protein: float, fat: float, carbs: float,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO diary(user_id, logged_at, description, grams, calories, protein, fat, carbs)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                user_id,
                datetime.now().isoformat(timespec="seconds"),
                description, grams, calories, protein, fat, carbs,
            ),
        )


def get_entries_for_date(user_id: int, day: date) -> list[sqlite3.Row]:
    prefix = day.isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM diary WHERE user_id=? AND logged_at LIKE ? ORDER BY logged_at",
            (user_id, f"{prefix}%"),
        ).fetchall()


def get_entries_for_range(user_id: int, start: date, end: date) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM diary
               WHERE user_id=? AND DATE(logged_at) BETWEEN ? AND ?
               ORDER BY logged_at""",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchall()


def delete_entries_for_date(user_id: int, day: date) -> int:
    prefix = day.isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM diary WHERE user_id=? AND logged_at LIKE ?",
            (user_id, f"{prefix}%"),
        )
        return cur.rowcount
