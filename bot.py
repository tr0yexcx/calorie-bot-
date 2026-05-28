"""Entry point — build and run the Telegram bot."""

import logging
import os

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import database as db
from handlers import (
    build_conv_handlers,
    cmd_find,
    cmd_help,
    cmd_month,
    cmd_my_dishes,
    cmd_reset,
    cmd_start,
    cmd_today,
    cmd_week,
    my_dishes_cb,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    db.init_db()

    app = Application.builder().token(token).build()

    # ConversationHandlers (must come first — they catch photos/text too)
    for conv in build_conv_handlers():
        app.add_handler(conv)

    # Simple commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("find", cmd_find))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("month", cmd_month))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("my_dishes", cmd_my_dishes))

    # Callback queries from /my_dishes
    app.add_handler(CallbackQueryHandler(my_dishes_cb, pattern=r"^dish_(info|del)_\d+$"))

    logger.info("Бот запущен.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
