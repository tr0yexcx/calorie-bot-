# Calorie Bot 🥗

Telegram-бот для подсчёта калорий и ведения дневника питания.

## Возможности

- 🔍 База 100+ продуктов с КБЖУ на 100г
- 📷 Сканирование штрихкодов (фото или ввод цифр) через Open Food Facts
- 🍳 Конструктор блюд с сохранением в «Мои блюда»
- 🧮 Быстрый калькулятор КБЖУ без сохранения
- 📅 Дневник питания (сегодня / неделя / месяц)
- 🎯 Дневные нормы КБЖУ с прогресс-баром
- 🗃 SQLite — всё хранится локально

## Установка

### 1. Системные зависимости

**Windows** — установите [ZBar](http://zbar.sourceforge.net/) и добавьте путь к `zbar.dll` в `PATH`.  
Либо установите через conda: `conda install -c conda-forge zbar`

**Linux/macOS:**
```bash
# Ubuntu/Debian
sudo apt-get install libzbar0

# macOS
brew install zbar
```

### 2. Python-зависимости

```bash
pip install -r requirements.txt
```

### 3. Настройка токена

```bash
cp .env.example .env
# Откройте .env и вставьте токен от @BotFather
```

Получить токен: откройте Telegram → [@BotFather](https://t.me/BotFather) → `/newbot`

### 4. Запуск

```bash
python bot.py
```

## Деплой на Railway

[Railway](https://railway.app) — бесплатный хостинг для ботов (500 часов/месяц на Free-плане).

### Шаг 1 — Подготовьте репозиторий

```bash
git init
git add .
git commit -m "initial commit"
```

Создайте репозиторий на GitHub и запушьте:

```bash
git remote add origin https://github.com/<ваш-username>/<repo>.git
git push -u origin main
```

### Шаг 2 — Создайте проект на Railway

1. Зайдите на [railway.app](https://railway.app) и войдите через GitHub
2. Нажмите **New Project → Deploy from GitHub repo**
3. Выберите ваш репозиторий
4. Railway автоматически обнаружит `nixpacks.toml` и `Procfile`

### Шаг 3 — Добавьте переменную окружения

В панели проекта: **Variables → New Variable**

| Имя | Значение |
|---|---|
| `BOT_TOKEN` | токен от @BotFather |

> ⚠️ Никогда не коммитьте файл `.env` с реальным токеном в Git.

### Шаг 4 — Деплой

Railway автоматически запустит сборку и поднимет воркер.  
Статус видно во вкладке **Deployments**. Логи — **Deploy Logs**.

### Персистентность SQLite на Railway

SQLite-файл хранится в эфемерной файловой системе — при каждом передеплое данные **сбрасываются**.  
Для сохранения данных между деплоями подключите Volume:

1. В проекте: **+ New → Volume**
2. Задайте Mount Path: `/data`
3. В `database.py` измените путь к базе:

```python
import os
DB_PATH = Path(os.getenv("DB_DIR", str(Path(__file__).parent))) / "calorie_bot.db"
```

4. Добавьте переменную окружения: `DB_DIR=/data`

### Файлы деплоя

| Файл | Назначение |
|---|---|
| `Procfile` | Объявляет процесс `worker: python bot.py` (без HTTP-порта) |
| `railway.json` | Политика перезапуска при сбоях |
| `nixpacks.toml` | Устанавливает системный пакет `zbar` (нужен для `pyzbar`) |

---

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Приветствие и список команд |
| `/find <название>` | Поиск продукта в базе |
| `/log` | Добавить приём пищи в дневник |
| `/today` | Дневник за сегодня + прогресс к норме |
| `/week` | Сводка за 7 дней |
| `/month` | Сводка за 30 дней по неделям |
| `/reset` | Сбросить записи за сегодня |
| `/goal` | Установить дневную норму КБЖУ |
| `/create_dish` | Конструктор блюд |
| `/my_dishes` | Список сохранённых блюд |
| `/calc` | Быстрый калькулятор КБЖУ |
| `/cancel` | Отменить текущее действие |

## Сканер штрихкодов

1. Отправьте фото штрихкода прямо в чат — бот распознает его через `pyzbar`
2. Или введите цифры штрихкода вручную (8–14 цифр)
3. Бот запросит данные у [Open Food Facts](https://world.openfoodfacts.org/)
4. Если продукт не найден — предложит ввести КБЖУ вручную и сохранит в вашу базу

## Структура проекта

```
calorie_bot/
├── bot.py           # Точка входа, сборка приложения
├── handlers.py      # Все обработчики команд и ConversationHandler
├── database.py      # SQLite — пользователи, дневник, блюда, продукты
├── products.py      # Встроенная база 100+ продуктов
├── dishes.py        # Логика конструктора блюд (DishDraft)
├── barcode.py       # Распознавание штрихкодов + Open Food Facts API
├── reports.py       # Отчёты /today, /week, /month
├── requirements.txt
├── .env.example
├── Procfile         # Railway: объявление воркера
├── railway.json     # Railway: политика перезапуска
├── nixpacks.toml    # Railway: системный пакет zbar
└── README.md
```

## База данных

При первом запуске автоматически создаётся файл `calorie_bot.db` (SQLite).

Таблицы:
- `users` — пользователи и их цели
- `diary` — дневник питания
- `dishes` + `dish_ingredients` — сохранённые блюда
- `custom_products` — личная база продуктов (из штрихкодов)
